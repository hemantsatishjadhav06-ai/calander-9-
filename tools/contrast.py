"""Check the design system's colour pairs in both themes (docs/DESIGN_SYSTEM.md §21 and §23).

Reads ``theme/static_src/src/styles.css`` without a browser: Layer 1 (the raw scales) and Layer 2
(the semantic tokens) from the light ``:root`` blocks, the dark blocks under
``:root[data-theme="dark"]`` and under ``@media (prefers-color-scheme: dark)`` with
``:root[data-theme-ready]:not([data-theme="light"])``, and the light content scope
``[data-theme-scope="light"]`` (platform previews and creatives). It resolves ``var()`` chains,
``rgb()`` and ``color-mix(in srgb, …)``, and measures every pair in ``PAIRS`` with the WCAG 2.x
relative-luminance ratio, the method of §23 (text 4.5:1, large text and non-text 3:1). The
translucent sticky bar is blended over the worst creatives (8-bit sRGB, as a browser paints it).

``apps/common/tests/test_contrast.py`` runs it as a pytest; ``--markdown`` prints the tables §21
holds.

Usage::

    python tools/contrast.py               # every pair in both themes; exit 1 on any failure
    python tools/contrast.py --markdown    # the §21 tables
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STYLES = ROOT / "theme" / "static_src" / "src" / "styles.css"

#: A Layer 1 property: one step of a raw scale.
SCALE_RE = re.compile(r"^--(ink|brand|success|warning|danger|info)-\d+$")
#: A colour written as a value (what Layer 1 is for, and what a dark value must not inherit).
LITERAL_RE = re.compile(r"#[0-9a-f]{3,8}\b|\brgba?\(|\bhsla?\(", re.I)
#: Any value that paints a colour once resolved.
COLOUR_RE = re.compile(r"#[0-9a-f]{3,8}\b|\brgba?\(|\bhsla?\(|\bcolor-mix\(", re.I)

DARK_SELECTOR = ':root[data-theme="dark"]'
DARK_MEDIA = "@media (prefers-color-scheme:dark)"
DARK_MEDIA_SELECTOR = ':root[data-theme-ready]:not([data-theme="light"])'
LIGHT_SCOPE = '[data-theme-scope="light"]'

#: The tokens F1 adds, with the light value of the literal each one replaces (so light cannot move).
NEW_TOKENS: dict[str, str] = {
    "--on-fill": "#FFFFFF",  # text-white on a fill
    "--surface-inverse": "#1C1F24",  # the toast, tooltip and selected chip fill (ink-900)
    "--text-on-inverse": "#FFFFFF",  # their white text
    "--scrim": "#0E1114",  # bg-ink-950/NN behind a dialog
}
#: Their utilities (``@theme inline``): text-on-fill, bg-inverse, text-on-inverse, bg-scrim.
UTILITIES: dict[str, str] = {
    "--color-on-fill": "var(--on-fill)",
    "--color-inverse": "var(--surface-inverse)",
    "--color-on-inverse": "var(--text-on-inverse)",
    "--color-scrim": "var(--scrim)",
}

Colour = tuple[float, float, float, float]  # r, g, b in 0–255, alpha in 0–1


# ── Parsing ─────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Rule:
    """One block of the stylesheet: its prelude, the at-rules around it, its own declarations."""

    selector: str
    parents: tuple[str, ...]
    declarations: dict[str, str]


def _normal(prelude: str) -> str:
    text = " ".join(prelude.split()).replace("'", '"')
    if text.startswith("@media"):
        text = re.sub(r"\s*:\s*", ":", text)
    return text


def _declare(into: dict[str, str], text: str) -> None:
    name, colon, value = text.partition(":")
    name = name.strip()
    if colon and name and not name.startswith("@") and (name.startswith("--") or name.isidentifier() or "-" in name):
        into[name] = " ".join(value.split())


def parse(css: str) -> list[Rule]:
    """Every block in *css*, inner blocks before the block that holds them (comments skipped)."""
    rules: list[Rule] = []
    stack: list[tuple[str, dict[str, str]]] = []
    buffer: list[str] = []
    quote = ""
    index = 0
    while index < len(css):
        char = css[index]
        index += 1
        if quote:
            buffer.append(char)
            if char == quote:
                quote = ""
            continue
        if char == "/" and css.startswith("*", index):  # a comment, outside any string
            end = css.find("*/", index + 1)
            index = len(css) if end < 0 else end + 2
            continue
        if char in "\"'":
            quote = char
            buffer.append(char)
        elif char == "{":
            stack.append((_normal("".join(buffer)), {}))
            buffer = []
        elif char == ";":
            if stack:
                _declare(stack[-1][1], "".join(buffer))
            buffer = []
        elif char == "}":
            if stack:
                _declare(stack[-1][1], "".join(buffer))
                selector, declarations = stack.pop()
                rules.append(Rule(selector, tuple(prelude for prelude, _ in stack), declarations))
            buffer = []
        else:
            buffer.append(char)
    return rules


def _merge(rules: Iterable[Rule]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for rule in rules:
        merged.update(rule.declarations)
    return merged


@dataclass(frozen=True)
class Sheet:
    """The themed blocks of one stylesheet."""

    layer1: dict[str, str]
    layer2: dict[str, str]
    dark: dict[str, str]
    dark_media: dict[str, str]
    light_scope: dict[str, str]
    theme_inline: dict[str, str] = field(default_factory=dict)

    @property
    def light(self) -> dict[str, str]:
        return {**self.layer1, **self.layer2}

    def theme(self, name: str) -> dict[str, str]:
        """The declarations ``<html>`` holds in ``light`` or ``dark`` (the media block must equal it)."""
        if name == "light":
            return self.light
        if name == "dark":
            return {**self.light, **self.dark}
        raise KeyError(name)

    def layer1_names(self) -> list[str]:
        return list(self.layer1)

    def layer2_names(self) -> list[str]:
        """Layer 2's themed properties: ``color-scheme`` and every token that paints a colour."""
        light = self.light
        names = []
        for name, value in self.layer2.items():
            if name == "color-scheme":
                names.append(name)
                continue
            try:
                resolved = resolve(value, light)
            except LookupError:
                continue
            if COLOUR_RE.search(resolved):
                names.append(name)
        return names


def load(css: str | None = None) -> Sheet:
    """The themed blocks of *css* (``styles.css`` when omitted)."""
    rules = parse(STYLES.read_text(encoding="utf-8") if css is None else css)
    roots = [rule for rule in rules if rule.selector == ":root" and not rule.parents]
    layer1 = [rule for rule in roots if rule.declarations and all(SCALE_RE.match(name) for name in rule.declarations)]
    layer2 = [rule for rule in roots if rule not in layer1]
    if not layer1:
        raise LookupError("no Layer 1 :root block")
    return Sheet(
        layer1=_merge(layer1),
        layer2=_merge(layer2),
        dark=_merge(rule for rule in rules if rule.selector == DARK_SELECTOR and not rule.parents),
        dark_media=_merge(
            rule for rule in rules if rule.selector == DARK_MEDIA_SELECTOR and rule.parents == (DARK_MEDIA,)
        ),
        light_scope=_merge(rule for rule in rules if rule.selector == LIGHT_SCOPE and not rule.parents),
        theme_inline=_merge(rule for rule in rules if rule.selector == "@theme inline" and not rule.parents),
    )


# ── Resolving ───────────────────────────────────────────────────────────────────────────────────


def _closing(text: str, start: int) -> int:
    """The index of the parenthesis that closes the one opened just before *start*."""
    depth = 1
    for index in range(start, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"unbalanced parentheses in {text!r}")


def _split_args(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    parts.append("".join(current).strip())
    return parts


def resolve(value: str, values: Mapping[str, str], seen: tuple[str, ...] = ()) -> str:
    """*value* with every ``var(--name[, fallback])`` replaced from *values*, recursively."""
    out = []
    index = 0
    while True:
        start = value.find("var(", index)
        if start < 0:
            out.append(value[index:])
            return "".join(out)
        end = _closing(value, start + 4)
        name, _, fallback = value[start + 4 : end].partition(",")
        name = name.strip()
        if name in seen:
            raise ValueError(f"var() cycle through {name}")
        if name in values:
            replacement = resolve(values[name], values, (*seen, name))
        elif fallback.strip():
            replacement = resolve(fallback.strip(), values, seen)
        else:
            raise LookupError(name)
        out.append(value[index:start])
        out.append(replacement)
        index = end + 1


def resolve_name(name: str, values: Mapping[str, str]) -> str:
    return resolve(values[name], values, (name,))


def in_light_scope(sheet: Sheet, theme: str = "dark") -> dict[str, str]:
    """The resolved values an element inside the light scope sees under *theme*.

    A property the scope declares resolves against the scope's own values; one it leaves out is
    inherited from ``<html>`` already resolved (a custom property inherits its computed value), so
    an alias the scope forgets keeps the outer theme's colour, as it would in a browser.
    """
    outer = sheet.theme(theme)
    inherited = {}
    for name in outer:
        try:
            inherited[name] = resolve_name(name, outer)
        except LookupError:
            continue
    values = {**inherited, **sheet.light_scope}
    return {name: resolve_name(name, values) if name in sheet.light_scope else inherited[name] for name in values}


# ── Colours ─────────────────────────────────────────────────────────────────────────────────────


def _number(text: str, scale: float) -> float:
    text = text.strip()
    if text.endswith("%"):
        return float(text[:-1]) / 100 * scale
    return float(text)


def parse_colour(text: str) -> Colour:
    """A resolved colour: ``#rgb``, ``#rrggbb[aa]``, ``rgb()``/``rgba()``, ``color-mix(in srgb, …)``."""
    text = text.strip()
    lower = text.lower()
    if lower == "transparent":
        return (0.0, 0.0, 0.0, 0.0)
    if lower.startswith("#"):
        digits = lower[1:]
        if len(digits) in (3, 4):
            digits = "".join(char * 2 for char in digits)
        if len(digits) not in (6, 8) or not re.fullmatch(r"[0-9a-f]+", digits):
            raise ValueError(f"not a hex colour: {text}")
        channels = [int(digits[i : i + 2], 16) for i in range(0, len(digits), 2)]
        alpha = channels[3] / 255 if len(channels) == 4 else 1.0
        return (float(channels[0]), float(channels[1]), float(channels[2]), alpha)
    if lower.startswith(("rgb(", "rgba(")):
        inner = text[text.index("(") + 1 : text.rindex(")")]
        parts = [part for part in re.split(r"[\s,/]+", inner.strip()) if part]
        if len(parts) not in (3, 4):
            raise ValueError(f"not an rgb() colour: {text}")
        r, g, b = (_number(part, 255) for part in parts[:3])
        alpha = _number(parts[3], 1) if len(parts) == 4 else 1.0
        return (r, g, b, alpha)
    if lower.startswith("color-mix("):
        return _mix(text)
    raise ValueError(f"not a colour this checker reads: {text}")


def _mix(text: str) -> Colour:
    """``color-mix(in srgb, a [p%], b [q%])`` as CSS Color 5 computes it (premultiplied alpha)."""
    args = _split_args(text[text.index("(") + 1 : text.rindex(")")])
    if len(args) != 3 or " ".join(args[0].split()).lower() != "in srgb":
        raise ValueError(f"only color-mix(in srgb, a p%, b) is read: {text}")
    (first, given1), (second, given2) = (_mix_part(arg) for arg in args[1:])
    if given1 is None and given2 is None:
        given1 = given2 = 0.5
    p1 = 1 - given2 if given1 is None and given2 is not None else given1
    p2 = 1 - given1 if given2 is None and given1 is not None else given2
    assert p1 is not None and p2 is not None
    total = p1 + p2
    if total <= 0:
        raise ValueError(f"color-mix() weights add up to nothing: {text}")
    p1, p2 = p1 / total, p2 / total
    one, two = parse_colour(first), parse_colour(second)
    alpha = one[3] * p1 + two[3] * p2
    if alpha == 0:
        return (0.0, 0.0, 0.0, 0.0)
    r, g, b = ((one[i] * one[3] * p1 + two[i] * two[3] * p2) / alpha for i in range(3))
    return (r, g, b, alpha * min(1.0, total))


def _mix_part(text: str) -> tuple[str, float | None]:
    match = re.fullmatch(r"(.*?)\s+([\d.]+)%", text.strip())
    if match:
        return match.group(1), float(match.group(2)) / 100
    return text, None


def blend(top: Colour, under: Colour) -> Colour:
    """*top* painted over the opaque *under*, rounded to 8 bits as the screen shows it."""
    alpha = top[3]
    channels = [round(top[i] * alpha + under[i] * (1 - alpha)) for i in range(3)]
    return (float(channels[0]), float(channels[1]), float(channels[2]), 1.0)


def hex_of(colour: Colour) -> str:
    return "#" + "".join(f"{round(channel):02X}" for channel in colour[:3])


def luminance(colour: Colour) -> float:
    def linear(channel: float) -> float:
        c = channel / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(channel) for channel in colour[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg: Colour, bg: Colour) -> float:
    """The WCAG 2.x contrast ratio of two opaque colours."""
    high, low = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (high + 0.05) / (low + 0.05)


# ── Pairs ───────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Pair:
    """A foreground on a background, each a token (``--ink-950``), a literal, or ``top over #hex``."""

    group: str
    label: str
    fg: str
    bg: str
    needs: float
    #: Why light is not held to *needs* (``LIGHT_EXCEPTIONS``); empty for every other pair.
    light_exception: str = ""
    #: An upper bound, for an edge that must stay an edge (0: none).
    at_most: float = 0.0
    #: ``"light"``: measured inside the light content scope (what a subtree carrying
    #: ``data-theme-scope="light"`` sees in each theme); empty: on the page.
    scope: str = ""

    def held_in(self, theme: str) -> bool:
        """Whether *theme* is held to the bar: always in dark, in light unless excepted."""
        return not (theme == "light" and self.light_exception)


TEXT, LARGE = 4.5, 3.0
NON_TEXT = 3.0
#: An edge (a hover edge, a secondary button's ring, a table header's rule) is drawn, not read: it must
#: show, and must not weigh what a control boundary (3:1) or text (4.5:1) weighs. ink-300 is a text grey
#: in dark (the toast detail), so an edge drawn in it would read 6:1 on a dark card; --border-hover keeps
#: the edge's weight in both themes.
EDGE_MIN, EDGE_MAX = 1.2, 2.5
EDGES = "Edges stay edges (between 1.20:1 and 2.50:1)"
SELECTION_BARS = "Selection bars (inside the light scope, dark in both themes)"

#: The opaque surfaces text sits on (§23): card, row hover, canvas, sidebar, selected row.
SURFACES: tuple[tuple[str, str], ...] = (
    ("card ink-0", "--ink-0"),
    ("sheet ink-25", "--ink-25"),
    ("canvas ink-50", "--ink-50"),
    ("sidebar ink-100", "--ink-100"),
    ("selected row brand-50", "--brand-50"),
)
#: What the translucent sticky bar may scroll over: §23's navy and orange creatives, and white
#: (the worst case once the bar is dark).
CREATIVES: tuple[tuple[str, str], ...] = (("navy", "#1E2533"), ("orange", "#F97316"), ("white", "#FFFFFF"))
STICKY = "--surface-sticky"
TEXT_ROLES: tuple[tuple[str, str], ...] = (
    ("title ink-950", "--ink-950"),
    ("text ink-900", "--ink-900"),
    ("body-2 ink-700", "--ink-700"),
    ("secondary ink-600", "--ink-600"),
    ("tertiary ink-500", "--ink-500"),
    ("link brand-700", "--brand-700"),
    ("link hover brand-800", "--brand-800"),
)
#: Tertiary text is not allowed on the translucent bar (§23 shows why).
STICKY_ROLES = tuple(role for role in TEXT_ROLES if role[1] != "--ink-500")
STATUSES = ("success", "warning", "danger", "info")
#: Pairs held in dark only, each with its reason. Light was under the bar before F1 and light must
#: not move (spec D2); the reason quotes the light ratio, and the contrast test holds it to the
#: measurement, so light cannot drift unseen.
LIGHT_EXCEPTIONS: dict[tuple[str, str], str] = {
    ("--success-500", "--ink-100"): (
        "light pre-existing, 2.93:1; a success icon never sits on the sidebar ink-100 or a neutral chip"
    ),
}


def _pairs() -> tuple[Pair, ...]:
    pairs: list[Pair] = []
    add = pairs.append

    group = "Text on surfaces"
    for label, fg in TEXT_ROLES:
        for surface, bg in SURFACES:
            add(Pair(group, f"{label} on {surface}", fg, bg, TEXT))
    for label, fg in STICKY_ROLES:
        for creative, hexa in CREATIVES:
            add(Pair(group, f"{label} on the sticky bar over {creative}", fg, f"{STICKY} over {hexa}", TEXT))

    group = "On a fill"
    for step in ("--brand-700", "--brand-800", "--brand-900", "--danger-500", "--danger-600", "--ink-800", "--ink-900"):
        add(Pair(group, f"on-fill on {step[2:]}", "--on-fill", step, TEXT))
    for status in ("success", "warning", "info"):
        add(Pair(group, f"on-fill icon on a solid {status}-500 disc", "--on-fill", f"--{status}-500", NON_TEXT))

    group = "Tinted buttons, chips and callouts"
    add(Pair(group, "tinted button brand-700 on brand-100", "--brand-700", "--brand-100", TEXT))
    add(Pair(group, "tinted button hover brand-800 on brand-200", "--brand-800", "--brand-200", TEXT))
    for status in STATUSES:
        add(Pair(group, f"{status} chip text {status}-600 on {status}-50", f"--{status}-600", f"--{status}-50", TEXT))
    for status in STATUSES:
        add(Pair(group, f"{status} alert body {status}-700 on {status}-50", f"--{status}-700", f"--{status}-50", TEXT))
    add(Pair(group, "neutral chip ink-700 on ink-100", "--ink-700", "--ink-100", TEXT))
    add(Pair(group, "count badge ink-700 on ink-200", "--ink-700", "--ink-200", TEXT))
    add(Pair(group, "ink-900 body on a success-50 callout", "--ink-900", "--success-50", TEXT))

    group = "Status text"
    for status in STATUSES:
        for surface, bg in SURFACES[:1] + SURFACES[2:3]:
            add(Pair(group, f"{status} text {status}-600 on {surface}", f"--{status}-600", bg, TEXT))
    for status in STATUSES:
        needs = LARGE if status == "success" else TEXT  # as §23 measured them
        add(Pair(group, f"{status} icon-as-text {status}-500 on card ink-0", f"--{status}-500", "--ink-0", needs))

    group = "Inverse surfaces (toast, tooltip, chart tip, selection bars)"
    add(Pair(group, "text-on-inverse on surface-inverse", "--text-on-inverse", "--surface-inverse", TEXT))
    add(Pair(group, "white (palette lock) on surface-inverse", "#FFFFFF", "--surface-inverse", TEXT))
    add(Pair(group, "detail and icons ink-300 on surface-inverse", "--ink-300", "--surface-inverse", TEXT))
    add(Pair(group, "action brand-300 on surface-inverse", "--brand-300", "--surface-inverse", TEXT))
    for status in STATUSES:
        needs = TEXT if status == "danger" else NON_TEXT  # danger-300 labels Delete and Reject all
        add(Pair(group, f"{status}-300 on surface-inverse", f"--{status}-300", "--surface-inverse", needs))

    # The two selection bars carry data-theme-scope="light": their children use 200 steps that flip
    # (hover:text-danger-200 would read 1.21:1 on the dark inverse surface), so the bar keeps its light look.
    group = SELECTION_BARS
    for label, fg, bg, needs in (
        ("label white on surface-inverse", "#FFFFFF", "--surface-inverse", TEXT),
        ("clear icon ink-300 on surface-inverse", "--ink-300", "--surface-inverse", NON_TEXT),
        ("Delete and Reject all danger-300 on surface-inverse", "--danger-300", "--surface-inverse", TEXT),
        ("their hover danger-200 on surface-inverse", "--danger-200", "--surface-inverse", TEXT),
        ("Publish brand-950 on brand-200", "--brand-950", "--brand-200", TEXT),
        ("Publish hover brand-950 on brand-300", "--brand-950", "--brand-300", TEXT),
        ("Approve all brand-700 on brand-100", "--brand-700", "--brand-100", TEXT),
        ("focus outline on-inverse on surface-inverse", "--text-on-inverse", "--surface-inverse", NON_TEXT),
    ):
        add(Pair(group, f"{label} (light scope)", fg, bg, needs, scope="light"))

    group = EDGES
    for surface, bg in SURFACES[:4]:
        add(Pair(group, f"hover edge border-hover on {surface}", "--border-hover", bg, EDGE_MIN, at_most=EDGE_MAX))

    group = "Non-text: control edges, focus, status icons (3:1)"
    for surface, bg in SURFACES:
        add(Pair(group, f"control border on {surface}", "--border-control", bg, NON_TEXT))
    # Marks on a card: the current hour bar and the timeline's now line keep ink-900, which flips.
    add(Pair(group, "current hour and now line ink-900 on card ink-0", "--ink-900", "--ink-0", NON_TEXT))
    add(Pair(group, "toggle knob on-fill on the off track ink-400", "--on-fill", "--ink-400", NON_TEXT))
    add(Pair(group, "toggle knob on-fill on the on track brand-700", "--on-fill", "--brand-700", NON_TEXT))
    # The collapsed sidebar's account button: its icon on the hover fill, bg-line-strong (ink-300 in
    # light; ink-300 itself is a text grey in dark and carried the icon at 1.49:1 there).
    add(Pair(group, "ink-600 icon on the sidebar's hover fill (line-strong)", "--ink-600", "--border-hover", NON_TEXT))
    for surface, bg in (*SURFACES, ("tinted button brand-100", "--brand-100")):
        add(Pair(group, f"focus ring on {surface}", "--focus-ring", bg, NON_TEXT))
    for creative, hexa in CREATIVES:
        add(
            Pair(
                group,
                f"focus ring on the sticky bar over {creative}",
                "--focus-ring",
                f"{STICKY} over {hexa}",
                NON_TEXT,
            )
        )
    for status in STATUSES:
        fg = f"--{status}-500"
        for surface, bg in (*SURFACES, (f"{status}-50 chip", f"--{status}-50")):
            exception = LIGHT_EXCEPTIONS.get((fg, bg), "")
            add(Pair(group, f"{status}-500 icon on {surface}", fg, bg, NON_TEXT, exception))
    return tuple(pairs)


PAIRS: tuple[Pair, ...] = _pairs()

#: Five rows of §23, reproduced to two decimals to prove the method.
SECTION_23_ROWS: tuple[tuple[str, str, str], ...] = (
    ("--ink-950", "--ink-0", "18.94"),
    ("--ink-500", "--ink-100", "4.67"),
    ("--ink-400", "--ink-100", "3.10"),
    ("#FFFFFF", "--brand-700", "8.64"),
    ("--ink-900", "--surface-sticky over #1E2533", "13.23"),
)


def colour_of(expression: str, values: Mapping[str, str]) -> Colour:
    """The opaque colour *expression* paints: a token, a literal, or ``top over #hex``."""
    top, over, under = expression.partition(" over ")
    colour = parse_colour(resolve_name(top, values) if top.startswith("--") else top)
    if over:
        return blend(colour, parse_colour(under))
    if colour[3] < 1:
        raise ValueError(f"{expression} is translucent; name what it sits over")
    return colour


@dataclass(frozen=True)
class Result:
    pair: Pair
    fg: str
    bg: str
    ratio: float

    @property
    def passed(self) -> bool:
        return self.ratio >= self.pair.needs and not (self.pair.at_most and self.ratio > self.pair.at_most)


def measure(pair: Pair, values: Mapping[str, str]) -> Result:
    fg_colour = colour_of(pair.fg, values)
    bg_colour = colour_of(pair.bg, values)
    return Result(pair, hex_of(fg_colour), hex_of(bg_colour), ratio(fg_colour, bg_colour))


def _values_for(sheet: Sheet, theme: str) -> dict[str, Mapping[str, str]]:
    """The values a pair is measured with in *theme*: on the page, and inside the light scope."""
    return {"": sheet.theme(theme), "light": in_light_scope(sheet, theme) if sheet.light_scope else {}}


def check(sheet: Sheet, theme: str, pairs: Sequence[Pair] = PAIRS) -> list[Result]:
    values = _values_for(sheet, theme)
    return [measure(pair, values[pair.scope]) for pair in pairs]


def problems(sheet: Sheet, theme: str, pairs: Sequence[Pair] = PAIRS) -> list[str]:
    """Each pair *theme* holds that cannot be resolved or is outside its bounds, one line per pair."""
    values = _values_for(sheet, theme)
    lines = []
    for pair in pairs:
        if not pair.held_in(theme):
            continue
        try:
            result = measure(pair, values[pair.scope])
        except (LookupError, ValueError) as error:
            lines.append(f"{pair.label}: cannot resolve {error}")
            continue
        if result.ratio < pair.needs:
            lines.append(f"{pair.label}: {result.fg} on {result.bg} {_ratio(result.ratio)} < {_ratio(pair.needs)}")
        elif not result.passed:
            lines.append(f"{pair.label}: {result.fg} on {result.bg} {_ratio(result.ratio)} > {_ratio(pair.at_most)}")
    return lines


# ── Structure (the light scope, the two dark blocks, a dark value for every token) ──────────────


def missing_dark_values(sheet: Sheet, dark: Mapping[str, str] | None = None) -> list[str]:
    """Layer 1 and Layer 2 properties that would keep their light value in the dark theme."""
    dark = sheet.dark if dark is None else dark
    missing = [name for name in sheet.layer1 if name not in dark]
    if dark.get("color-scheme") != "dark":
        missing.append("color-scheme")
    marker = "\x00light"
    light = sheet.light
    blanked = {
        name: marker if name in sheet.layer1 or LITERAL_RE.search(value) else value for name, value in light.items()
    }
    values = {**blanked, **dark}
    for name in sheet.layer2_names():
        if name == "color-scheme":
            continue
        try:
            if marker in resolve_name(name, values):
                missing.append(name)
        except LookupError:
            missing.append(name)
    return missing


def scope_differences(sheet: Sheet) -> list[str]:
    """How the light scope differs from the light ``:root``, one line per property."""
    found: list[str] = []
    if sheet.light_scope.get("color-scheme") != "light":
        found.append("color-scheme: not light")
    light = sheet.light
    for name in [*sheet.layer1_names(), *sheet.layer2_names()]:
        if name == "color-scheme":
            continue
        if name not in sheet.light_scope:
            found.append(f"{name}: not declared")
        elif sheet.light_scope[name] != light[name]:
            found.append(f"{name}: {sheet.light_scope[name]} (light :root has {light[name]})")
    return found


# ── Output ──────────────────────────────────────────────────────────────────────────────────────


def _ratio(value: float) -> str:
    return f"{value:.2f}:1"


def markdown(sheet: Sheet) -> str:
    """§21's tables: the dark scales, the dark semantic tokens, and every pair in both themes."""
    lines: list[str] = []
    light = sheet.theme("light")

    steps: list[str] = []
    scales: dict[str, list[str]] = {}
    for name in sheet.layer1_names():
        scale, step = name[2:].rsplit("-", 1)
        scales.setdefault(scale, []).append(step)
        if step not in steps:
            steps.append(step)
    steps.sort(key=int)
    lines += [
        "#### Layer 1 in both themes",
        "",
        "| Scale | " + " | ".join(steps) + " |",
        "|---|" + "---|" * len(steps),
    ]
    for scale, own in scales.items():
        for theme, values in (("light", sheet.layer1), ("dark", sheet.dark)):
            cells = [f"`{values.get(f'--{scale}-{step}', '—')}`" if step in own else "" for step in steps]
            lines.append(f"| {scale} {theme} | " + " | ".join(cells) + " |")

    lines += ["", "#### Layer 2 tokens the dark theme sets", "", "| Token | Light | Dark |", "|---|---|---|"]
    for name, value in sheet.dark.items():
        if name in sheet.layer1:
            continue
        lines.append(f"| `{name}` | `{light.get(name, '—')}` | `{value}` |")

    light_results = check(sheet, "light")
    dark_results = check(sheet, "dark")
    group = ""
    for light_result, dark_result in zip(light_results, dark_results, strict=True):
        pair = light_result.pair
        if pair.group != group:
            group = pair.group
            lines += [
                "",
                f"#### {group}",
                "",
                "| Pair | Needs | Light | Ratio | Dark | Ratio | Result |",
                "|---|---:|---|---:|---|---:|---|",
            ]
        held = [result for theme, result in (("light", light_result), ("dark", dark_result)) if pair.held_in(theme)]
        verdict = "PASS" if all(result.passed for result in held) else "FAIL"
        if pair.light_exception:
            verdict += f" in dark; light excepted: {pair.light_exception}"
        needs = f"{_ratio(pair.needs)} to {_ratio(pair.at_most)}" if pair.at_most else _ratio(pair.needs)
        lines.append(
            f"| {pair.label} | {needs} "
            f"| `{light_result.fg}` on `{light_result.bg}` | {_ratio(light_result.ratio)} "
            f"| `{dark_result.fg}` on `{dark_result.bg}` | {_ratio(dark_result.ratio)} "
            f"| {verdict} |"
        )
    failures = sum(
        not result.passed
        for theme, results in (("light", light_results), ("dark", dark_results))
        for result in results
        if result.pair.held_in(theme)
    )
    excepted = sum(bool(pair.light_exception) for pair in PAIRS)
    lines += [
        "",
        f"Pairs checked: {len(PAIRS)} in each theme; failures: {failures}; excepted in light only: {excepted}.",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--markdown", action="store_true", help="print the tables for DESIGN_SYSTEM.md §21")
    parser.add_argument("--css", type=Path, default=STYLES, help="the stylesheet to read (default: styles.css)")
    args = parser.parse_args(argv)
    sheet = load(args.css.read_text(encoding="utf-8"))
    if args.markdown:
        print(markdown(sheet))
    found = [f"{theme}: {line}" for theme in ("light", "dark") for line in problems(sheet, theme)]
    found += [f"dark: no dark value for {name}" for name in missing_dark_values(sheet)]
    if sheet.dark_media != sheet.dark:
        found.append("the media block and the attribute block differ")
    found += [f"light scope: {line}" for line in scope_differences(sheet)]
    for problem in found:
        print(problem, file=sys.stderr)
    if not args.markdown:
        print(f"{len(PAIRS)} pairs in each theme; {len(found)} problems.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
