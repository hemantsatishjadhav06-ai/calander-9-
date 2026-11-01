"""Motion (Phase 3, T9; docs/specs/phase-3.md, spec D7 and F5).

Micro-interactions take 160 or 200 ms: ``--dur-fast`` (160 ms) and the new ``--dur-snap`` (200 ms);
a sheet or drawer leaves at 70 % of its entrance, ``--dur-exit`` (``calc(var(--dur-snap) * .7)``,
140 ms). ``--dur-base`` (220 ms) and ``--dur-slow`` (320 ms) stay for the pages not rebuilt.

styles.css carries the motion classes a rebuilt screen uses, each on those tokens only, and each with
its reduced-motion form in the stylesheet's reduced-motion block:

* ``.motion-rise``: a message arriving, opacity and a 6 px rise, ``--dur-snap``; reduced, it appears.
* ``.motion-sheet-enter`` / ``-leave`` with ``.motion-sheet-out`` / ``-in``: a sheet comes up from the
  bottom below 1024 px and in from the right from 1024 px, enters in ``--dur-snap`` and leaves in
  ``--dur-exit``; reduced, it appears and goes in place, with no transform.
* ``.motion-fill``: the approve fill, ``--dur-snap``; reduced, the fill swaps at once.
* ``.motion-snap``: the calendar chip's snap, ``--dur-snap``; reduced, the chip moves without it.

The global reduced-motion rule stays as it is. ``base.html`` keeps no ``@keyframes`` and no local
reduced-motion block (its progress bar's moved into styles.css), and neither does any template in a
``gated`` screen's tree, which also never reaches for ``--dur-base`` or ``--dur-slow``. The list of
gated screens is empty until screen 1's gate, so the tree guard is proved on fixture templates.
``tests/e2e/self/reduced-motion.spec.ts`` checks the same in the browser.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from apps.common import screens
from tools import recolor

ROOT = Path(__file__).resolve().parents[3]
STYLES = ROOT / "theme" / "static_src" / "src" / "styles.css"
BASE = ROOT / "templates" / "base.html"

REDUCE = "@media (prefers-reduced-motion: reduce)"
DESKTOP = "@media (min-width: 1024px)"
#: The tokens new motion may use, by name, and the longest any motion class may run (spec F5).
MOTION_TOKENS = ("--dur-fast", "--dur-snap", "--dur-exit")
LONGEST_MS = 200.0
#: The motion classes the plan names, with the one token each runs on.
CLASSES = {
    ".motion-rise": "--dur-snap",
    ".motion-sheet-enter": "--dur-snap",
    ".motion-sheet-leave": "--dur-exit",
    ".motion-fill": "--dur-snap",
    ".motion-snap": "--dur-snap",
}
#: The global rule, which stays exactly as it is (spec D7).
GLOBAL_RULE = (
    "animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; "
    "transition-duration: 0.01ms !important; scroll-behavior: auto !important;"
)

Rule = tuple[tuple[str, ...], str, str]


def css_rules(css: str) -> list[Rule]:
    """``(the at-rules around it, its prelude, its declarations)`` for every rule holding declarations,
    keyframe steps included (their prelude is ``from``, ``to`` or a percentage)."""
    css = recolor._mask_css_comments(css)
    found: list[Rule] = []
    stack: list[tuple[str, int]] = []
    start = 0
    for index, char in enumerate(css):
        if char == "{":
            stack.append((" ".join(css[start:index].split()), index))
            start = index + 1
        elif char == "}":
            if stack:
                prelude, opening = stack.pop()
                body = css[opening + 1 : index]
                if "{" not in body and not prelude.startswith("@"):
                    found.append((tuple(p for p, _ in stack), prelude, " ".join(body.split())))
            start = index + 1
        elif char == ";":
            start = index + 1
    return found


def declarations(body: str) -> dict[str, str]:
    """A rule's declarations by property (the last one wins, as in the browser)."""
    found: dict[str, str] = {}
    for part in body.split(";"):
        name, colon, value = part.partition(":")
        if colon:
            found[name.strip()] = value.strip()
    return found


def root_tokens(css: str) -> dict[str, str]:
    """Every custom property set on a bare ``:root`` outside any at-rule (the light Layer 2)."""
    found: dict[str, str] = {}
    for around, prelude, body in css_rules(css):
        if prelude == ":root" and not around:
            found.update({k: v for k, v in declarations(body).items() if k.startswith("--")})
    return found


def milliseconds(value: str, tokens: Mapping[str, str]) -> float:
    """A time written as ``200ms``, ``.2s``, ``var(--dur-…)`` or ``calc(var(--dur-…) * .7)``."""
    value = value.strip()
    reference = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if reference:
        return milliseconds(tokens[reference.group(1)], tokens)
    product = re.fullmatch(r"calc\(\s*(.+?)\s*\*\s*([0-9]*\.?[0-9]+)\s*\)", value)
    if product:
        return milliseconds(product.group(1), tokens) * float(product.group(2))
    literal = re.fullmatch(r"([0-9]*\.?[0-9]+)(ms|s)", value)
    assert literal, f"not a time this test reads: {value}"
    return float(literal.group(1)) * (1 if literal.group(2) == "ms" else 1000)


#: A time in a declaration: a duration token, a ``calc()`` of one, or a literal (``200ms``, ``.2s``).
TIME_RE = re.compile(r"var\(--dur-[\w-]+\)|calc\((?:[^()]|\([^()]*\))*\)|(?<![\w.-])[0-9]*\.?[0-9]+m?s(?![\w-])")


def times(property_name: str, value: str) -> list[str]:
    """The durations a ``transition`` or ``animation`` declaration (or its ``-duration``) sets.

    A shorthand's first time is its duration; a second would be a delay, which motion never uses."""
    if property_name in ("transition-duration", "animation-duration"):
        return [part.strip() for part in value.split(",")]
    durations = []
    for part in value.split(","):
        found = TIME_RE.findall(part)
        assert len(found) <= 1, f"a delay in {property_name}: {part.strip()}"
        durations += found
    return durations


MOTION_PROPERTIES = ("transition", "transition-duration", "animation", "animation-duration")


def motion_rules(css: str) -> list[Rule]:
    """The rules whose selector names a ``.motion-…`` class, outside the reduced-motion block."""
    return [rule for rule in css_rules(css) if ".motion-" in rule[1] and REDUCE not in rule[0]]


@pytest.fixture(scope="module")
def css() -> str:
    return STYLES.read_text(encoding="utf-8")


# ── The tokens ─────────────────────────────────────────────────────────────────────────────────


def test_the_motion_tokens_and_their_values(css):
    tokens = root_tokens(css)
    assert tokens.get("--dur-snap") == "200ms"
    assert tokens.get("--dur-exit") == "calc(var(--dur-snap) * .7)"
    assert milliseconds("var(--dur-exit)", tokens) == pytest.approx(140.0)
    # The ones that were there stay as they were: the pages not rebuilt still use them.
    assert {name: tokens.get(name) for name in ("--dur-instant", "--dur-fast", "--dur-base", "--dur-slow")} == {
        "--dur-instant": "100ms",
        "--dur-fast": "160ms",
        "--dur-base": "220ms",
        "--dur-slow": "320ms",
    }


# ── The motion classes ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("selector", "token"), CLASSES.items())
def test_each_motion_class_runs_on_its_token(css, selector, token):
    rules = [body for around, prelude, body in motion_rules(css) if prelude == selector and not around]
    assert rules, f"styles.css has no {selector} rule"
    found = [
        duration
        for body in rules
        for name, value in declarations(body).items()
        if name in MOTION_PROPERTIES
        for duration in times(name, value)
    ]
    assert found and set(found) == {f"var({token})"}, (selector, found)


def test_every_motion_class_runs_on_the_fast_or_snap_tokens_and_never_longer_than_200ms(css):
    tokens = root_tokens(css)
    seen = 0
    for _around, prelude, body in motion_rules(css):
        for name, value in declarations(body).items():
            if name not in MOTION_PROPERTIES:
                continue
            for duration in times(name, value):
                seen += 1
                assert duration in {f"var({token})" for token in MOTION_TOKENS}, (prelude, name, duration)
                assert milliseconds(duration, tokens) <= LONGEST_MS, (prelude, duration)
    assert seen >= len(CLASSES)


def test_a_message_rises_6px_as_it_fades_in(css):
    rules = css_rules(css)
    rise = declarations(next(body for around, prelude, body in rules if prelude == ".motion-rise" and not around))
    name = rise["animation"].split()[0]
    steps = {prelude: declarations(body) for around, prelude, body in rules if around == (f"@keyframes {name}",)}
    assert steps.get("from") == {"opacity": "0", "transform": "translateY(6px)"}, steps
    assert steps.get("to", {"opacity": "1", "transform": "none"}) == {"opacity": "1", "transform": "none"}, steps


def test_a_sheet_comes_up_from_the_bottom_on_phones_and_in_from_the_right_from_1024px(css):
    rules = motion_rules(css)

    def transform(selector: str, around: tuple[str, ...]) -> str | None:
        found = [
            declarations(body).get("transform") for a, prelude, body in rules if prelude == selector and a == around
        ]
        return found[-1] if found else None

    assert transform(".motion-sheet-out", ()) == "translateY(100%)"
    assert transform(".motion-sheet-out", (DESKTOP,)) == "translateX(100%)"
    assert transform(".motion-sheet-in", ()) == "none"
    for selector in (".motion-sheet-enter", ".motion-sheet-leave"):
        body = next(body for a, prelude, body in rules if prelude == selector and not a)
        assert declarations(body)["transition"].startswith("transform "), (selector, body)


def test_the_approve_fill_and_the_chip_snap_transition_what_they_change(css):
    rules = motion_rules(css)
    fill = declarations(next(body for a, prelude, body in rules if prelude == ".motion-fill" and not a))
    snap = declarations(next(body for a, prelude, body in rules if prelude == ".motion-snap" and not a))
    filled = {part.split()[0] for part in fill["transition"].split(",")}
    assert {"background-color", "color"} <= filled and "transform" not in filled, fill
    assert {part.split()[0] for part in snap["transition"].split(",")} == {"transform"}, snap


# ── Their reduced-motion forms, and the global rule ────────────────────────────────────────────


def _reduced(css: str) -> dict[str, dict[str, str]]:
    """What the reduced-motion block sets, by each selector of its rules."""
    found: dict[str, dict[str, str]] = {}
    for around, prelude, body in css_rules(css):
        if around == (REDUCE,):
            for selector in prelude.split(","):
                found.setdefault(selector.strip(), {}).update(declarations(body))
    return found


def test_every_motion_class_has_its_reduced_motion_form(css):
    reduced = _reduced(css)
    moving = set()
    for _around, prelude, body in motion_rules(css):
        if any(name in MOTION_PROPERTIES for name in declarations(body)):
            moving.update(selector.strip() for selector in prelude.split(","))
    assert moving >= set(CLASSES), moving
    for selector in sorted(moving):
        form = reduced.get(selector, {})
        stops = form.get("animation") == "none !important" or form.get("transition") == "none !important"
        assert stops, f"{selector} has no reduced-motion form in the stylesheet: {form}"
    # Reduced, the sheet appears and goes in place: no transform at all.
    assert reduced.get(".motion-sheet-out", {}).get("transform") == "none !important"


def test_the_global_reduced_motion_rule_is_unchanged(css):
    rules = [
        body for around, prelude, body in css_rules(css) if around == (REDUCE,) and prelude == "*, *::before, *::after"
    ]
    assert rules == [GLOBAL_RULE]


# ── base.html: no local motion block ───────────────────────────────────────────────────────────

COMMENTS_RE = re.compile(r"{%\s*comment\b.*?%}.*?{%\s*endcomment\s*%}|{#.*?#}|<!--.*?-->|/\*.*?\*/", re.S)
KEYFRAMES_RE = re.compile(r"@keyframes\b")
REDUCED_BLOCK_RE = re.compile(r"@media\b[^{;]*prefers-reduced-motion")
BASE_AND_SLOW_RE = re.compile(r"--dur-(?:base|slow)(?![\w-])")


def local_motion_findings(text: str, path: str = "<string>", *, durations: bool = True) -> list[str]:
    """``@keyframes``, a local reduced-motion block and (with *durations*) ``--dur-base`` or
    ``--dur-slow`` in a template's source, comments left out. A script asking ``matchMedia`` is not a
    block and passes."""
    masked = COMMENTS_RE.sub(lambda match: re.sub(r"[^\n]", " ", match.group(0)), text)
    checks = [(KEYFRAMES_RE, "@keyframes"), (REDUCED_BLOCK_RE, "a local reduced-motion block")]
    if durations:
        checks.append((BASE_AND_SLOW_RE, "a 220 or 320 ms token"))
    return [
        f"{path}:{masked.count(chr(10), 0, match.start()) + 1}: {what} ({match.group(0)})"
        for pattern, what in checks
        for match in pattern.finditer(masked)
    ]


def test_base_html_keeps_no_keyframes_and_no_local_reduced_motion_block():
    findings = local_motion_findings(BASE.read_text(encoding="utf-8"), "base.html", durations=False)
    assert not findings, "Move it into styles.css (spec D7):\n" + "\n".join(findings)


def test_the_progress_bar_moved_into_the_stylesheet_with_its_reduced_form(css):
    rules = css_rules(css)
    bar = [declarations(body) for around, prelude, body in rules if prelude == "#htmx-progress" and not around]
    assert bar and bar[0]["transition"] == "width .2s var(--ease-out), opacity .25s ease", bar
    assert [declarations(body) for around, prelude, body in rules if prelude == "#htmx-progress.active"] == [
        {"opacity": "1"}
    ]
    assert _reduced(css).get("#htmx-progress") == {"transition": "opacity .1s"}
    assert "#htmx-progress{" not in BASE.read_text(encoding="utf-8")


# ── The guard on the gated screens ─────────────────────────────────────────────────────────────


def gated_tree(registry: Mapping[str, screens.Screen] | None = None, dirs: Sequence[Path] | None = None) -> list[str]:
    """Every template in the tree of a gated screen: its roots, its fragments and what they reach."""
    names: list[str] = []
    for screen in (screens.SCREENS if registry is None else registry).values():
        if screen.gated:
            names += [n for n in screens.template_tree((*screen.templates, *screen.fragments), dirs) if n not in names]
    return names


def guard_findings(
    registry: Mapping[str, screens.Screen] | None = None, dirs: Sequence[Path] | None = None
) -> list[str]:
    findings: list[str] = []
    for name in gated_tree(registry, dirs):
        path = screens.find_template(name, dirs)
        assert path is not None, name
        findings += local_motion_findings(path.read_text(encoding="utf-8"), name)
    return findings


def test_no_gated_screen_keeps_local_motion_or_the_220_and_320ms_tokens():
    findings = guard_findings()
    assert not findings, "Use --dur-fast or --dur-snap and the styles.css motion classes (spec D7):\n" + "\n".join(
        findings
    )


def test_the_guard_reads_every_template_of_a_gated_screen(tmp_path):
    def write(name: str, body: str) -> None:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    write("base.html", "<html>{% block content %}{% endblock %}</html>")
    write(
        "pages/rebuilt.html",
        '{% extends "base.html" %}{% block content %}{% include "partials/row.html" %}{% endblock %}',
    )
    write("partials/row.html", '<li>\n  <div style="transition: opacity var(--dur-slow)">Row</div>\n</li>')
    write(
        "partials/fragment.html",
        "<style>\n  @keyframes pop { from { opacity: 0; } }\n"
        "  @media (prefers-reduced-motion: reduce) { .pop { animation: none; } }\n</style>",
    )
    write("pages/untouched.html", "<style>@keyframes old { to { opacity: 1; } }</style>")
    registry = {
        "rebuilt": screens.Screen(templates=("pages/rebuilt.html",), fragments=("partials/fragment.html",), gated=True),
        "next": screens.Screen(templates=("pages/untouched.html",)),
    }

    assert guard_findings(registry, [tmp_path]) == [
        "partials/fragment.html:2: @keyframes (@keyframes)",
        "partials/fragment.html:3: a local reduced-motion block (@media (prefers-reduced-motion)",
        "partials/row.html:2: a 220 or 320 ms token (--dur-slow)",
    ]


@pytest.mark.parametrize(
    ("source", "bad"),
    [
        ("<style>@keyframes spin { to { transform: rotate(1turn); } }</style>", True),
        ("<style>@media (prefers-reduced-motion: reduce) { .x { animation: none; } }</style>", True),
        ("<style>@media screen and (prefers-reduced-motion: reduce) { .x { transition: none; } }</style>", True),
        ('<div style="transition: transform var(--dur-base) var(--ease-out)">', True),
        ('<div class="duration-(--dur-slow)">', True),
        ('<div class="[transition-duration:var(--dur-base)]">', True),
        ('<div style="transition: transform var(--dur-snap) var(--ease-out)">', False),
        ('<div class="motion-rise">', False),
        ('<p class="text-ink-600">The base of the dur-base pricing</p>', False),
        ('<div style="--dur-baseline: 1px">', False),
        ("<script>const calm = matchMedia('(prefers-reduced-motion: reduce)').matches;</script>", False),
        ("{# @keyframes was here #}<div>", False),
        ("{% comment %}\n@media (prefers-reduced-motion: reduce) {}\n{% endcomment %}<div>", False),
        ("<!-- var(--dur-slow) --><div>", False),
        ("<style>/* no @keyframes here */ .x { color: red; }</style>", False),
    ],
)
def test_the_local_motion_check_on_fixture_strings(source, bad):
    assert bool(local_motion_findings(source)) is bad, source
