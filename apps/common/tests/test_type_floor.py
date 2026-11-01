"""The type floor and the type tokens (Phase 3, T6; docs/specs/phase-3.md, spec D3 and F2).

Nothing a person reads is set under 13 px anywhere the stylesheet loads, the standalone pages
included (accept invite, the magic-link pages, legal, error, unsubscribe: they keep their literal
colours, not their small sizes). The guard reads source, so it sees every branch of a template:

* an arbitrary Tailwind size, ``text-[Npx]`` under 13 or ``text-[Nrem]`` under 0.8125, in a class
  string of a template, the app's own JavaScript (``static/js``, not the vendored files) or a Python
  module (form widget attrs and small fragments, which the stylesheet scans for classes too);
* a ``font-size`` under 13 px in a template's style block or style attribute, in ``styles.css`` or in
  the public site's stylesheet (``em`` is counted against 16 px, like ``rem``);
* a ``--text-*`` size token under 0.8125rem.

It walks the template directory itself rather than recolor's token classifier, which skips the pages
that do not load the stylesheet. Two named allowlists excuse what the spec leaves for later, each
entry with its reason: emails (the owner's one exception) and the public site (screen 11). Each must
still excuse something, so it is removed when its files come under the floor.

Tailwind's own ``text-xs`` is 12 px unless ``styles.css`` redefines it, which a test below pins with
the rest of D3's tokens: the running-text token (16/24 below 1024 px, 15/22 from 1024 px, on
``<body>`` and as ``text-read``), the display stack on headings at 700, and 16 px inputs on phones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
STYLES = ROOT / "theme" / "static_src" / "src" / "styles.css"
FLOOR_PX = 13.0
ROOT_PX = 16.0

#: Emails do not load the stylesheet and keep literal values; the owner chose them as the floor's one
#: exception (spec, owner question "Emails under 13 px"). Removed if that answer changes.
EMAILS: dict[str, str] = {
    "templates/client_portal/email/": "the client's magic-link email: emails are the owner's one exception",
    "templates/members/email/": "the invitation email: emails are the owner's one exception",
    "templates/notifications/email/": "notification and digest emails: emails are the owner's one exception",
    "templates/onboarding/email/": "the connection-link email: emails are the owner's one exception",
}

#: The public site has its own stylesheet; its 19 sub-13 px rules move with screen 11, which removes
#: these entries (spec D3).
MARKETING: dict[str, str] = {
    "static/css/marketing.css": "the public site's stylesheet: its small rules move in screen 11",
    "templates/marketing/": "the public site's pages: rebuilt in screen 11",
}

ALLOWLISTS: dict[str, dict[str, str]] = {"emails": EMAILS, "marketing": MARKETING}

_NUMBER = r"([0-9]*\.?[0-9]+)"
ARBITRARY_RE = re.compile(rf"(?<![\w-])text-\[(?:length:)?{_NUMBER}(px|rem|em)\]")
FONT_SIZE_RE = re.compile(rf"font-size\s*:\s*{_NUMBER}(px|rem|em)\b", re.IGNORECASE)
TOKEN_RE = re.compile(rf"(?<![\w-])--text-([\w-]+)\s*:\s*{_NUMBER}(px|rem|em)\b")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    text: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.text}"


def _px(value: str, unit: str) -> float:
    number = float(value)
    return number if unit.lower() == "px" else number * ROOT_PX


def small_sizes(source: str, *, classes: bool = True, css: bool = True) -> list[tuple[int, str]]:
    """Every size under the floor in *source*: (line, the matched text)."""
    found: list[tuple[int, str]] = []
    for number, line in enumerate(source.splitlines(), start=1):
        if classes:
            found += [(number, m.group(0)) for m in ARBITRARY_RE.finditer(line) if _px(m[1], m[2]) < FLOOR_PX]
        if css:
            found += [(number, m.group(0)) for m in FONT_SIZE_RE.finditer(line) if _px(m[1], m[2]) < FLOOR_PX]
            found += [
                (number, m.group(0)) for m in TOKEN_RE.finditer(line) if "--" not in m[1] and _px(m[2], m[3]) < FLOOR_PX
            ]
    return found


def _is_test_module(path: Path) -> bool:
    parts = path.relative_to(ROOT).parts
    return "tests" in parts or path.name.startswith("test_") or path.name in ("tests.py", "conftest.py")


def scanned() -> list[tuple[Path, bool, bool]]:
    """(file, read its class strings, read its CSS) for every place a size can be written."""
    files: list[tuple[Path, bool, bool]] = []
    templates = sorted((ROOT / "templates").rglob("*.html")) + sorted((ROOT / "apps").glob("*/templates/**/*.html"))
    files += [(path, True, True) for path in templates]
    files += [(path, True, True) for path in sorted((ROOT / "static" / "js").glob("*.js"))]
    files += [(STYLES, True, True)]
    files += [(path, True, True) for path in sorted((ROOT / "static" / "css").glob("*.css"))]
    files += [(path, True, False) for path in sorted((ROOT / "apps").rglob("*.py")) if not _is_test_module(path)]
    return files


def all_findings() -> list[Finding]:
    findings: list[Finding] = []
    for path, classes, css in scanned():
        relative = path.relative_to(ROOT).as_posix()
        for line, text in small_sizes(path.read_text(encoding="utf-8"), classes=classes, css=css):
            findings.append(Finding(relative, line, text))
    return findings


def allowlist_for(path: str) -> str | None:
    for name, entries in ALLOWLISTS.items():
        if any(path == entry or (entry.endswith("/") and path.startswith(entry)) for entry in entries):
            return name
    return None


def test_nothing_is_set_under_13px() -> None:
    small = [finding for finding in all_findings() if allowlist_for(finding.path) is None]
    assert not small, "Sizes under 13 px (use text-xs, which is 13/18, or 13 px):\n" + "\n".join(map(str, small))


@pytest.mark.parametrize("name", sorted(ALLOWLISTS))
def test_each_allowlist_names_real_files_and_still_excuses_something(name: str) -> None:
    for entry, reason in ALLOWLISTS[name].items():
        assert (ROOT / entry).exists(), f"{name}: {entry} does not exist"
        assert reason.strip(), f"{name}: {entry} needs its reason"
    excused = [finding for finding in all_findings() if allowlist_for(finding.path) == name]
    assert excused, f"The {name} allowlist excuses nothing now: remove it (spec D3)."


def test_the_guard_reads_the_standalone_pages_and_the_app_script() -> None:
    paths = {path.relative_to(ROOT).as_posix() for path, _, _ in scanned()}
    for page in (
        "templates/members/accept_invite.html",
        "templates/client_portal/magic_link_confirm.html",
        "templates/legal/base_legal.html",
        "templates/errors/base_error.html",
        "templates/notifications/unsubscribe.html",
        "static/js/live_board.js",
        "theme/static_src/src/styles.css",
    ):
        assert page in paths, page
    assert not any("/vendor/" in path for path in paths)


@pytest.mark.parametrize(
    "source",
    [
        '<span class="text-[12px] font-semibold">',
        '<span class="max-lg:text-[11px]">',
        "'<span class=\"block font-mono text-[12px]\">'",
        '<p class="text-[0.75rem]">',
        '<p class="text-[length:10px]">',
        '<p style="font-size:12px;color:#656B73">',
        ".label { font-size: 0.75rem; line-height: 1rem; }",
        ".note { font-size: .7em; }",
        "  --text-caption: 0.75rem;  --text-caption--line-height: 1rem;",
        "  --text-micro: 11px;",
    ],
)
def test_the_guard_flags_each_kind_of_small_size(source: str) -> None:
    assert small_sizes(source), source


@pytest.mark.parametrize(
    "source",
    [
        '<span class="text-[13px] font-semibold">',
        '<span class="text-[13px]/5">',
        '<span class="text-xs text-caption">',
        '<p class="text-[0.8125rem]">',
        '<p style="font-size:13px">',
        ".label { font-size: 0.8125rem; line-height: 1rem; }",
        "@media (max-width: 1023px) { .ui-input { height: 44px; font-size: 16px; } }",
        "  --text-caption--line-height: 1rem;  --text-micro--letter-spacing: 0.02em;",
        "  --text-body: var(--ink-700);",
        "  --mk-text-xs: 0.75rem;",
        '<div class="context-[12px] w-[11px]">',
    ],
)
def test_the_guard_passes_13px_and_what_is_not_a_size(source: str) -> None:
    assert not small_sizes(source), source


# ── The tokens (D3) ────────────────────────────────────────────────────────────────────────────


def _css() -> str:
    return STYLES.read_text(encoding="utf-8")


def _theme_blocks(css: str) -> str:
    """The text of every ``@theme`` block (inline or not)."""
    blocks = []
    for match in re.finditer(r"@theme(?:\s+inline)?\s*\{", css):
        depth, index = 1, match.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[index], 0)
            index += 1
        blocks.append(css[match.end() : index - 1])
    return "\n".join(blocks)


def _declaration(css: str, name: str) -> str:
    found = re.search(rf"(?<![\w-]){re.escape(name)}\s*:\s*([^;]+);", css)
    assert found, f"{name} is not declared"
    return found.group(1).strip()


def test_tailwind_text_xs_is_redefined_to_13_over_18() -> None:
    theme = _theme_blocks(_css())
    assert _declaration(theme, "--text-xs") == "0.8125rem"
    assert _declaration(theme, "--text-xs--line-height") == "1.125rem"


@pytest.mark.parametrize("role", ["caption", "micro"])
def test_caption_and_micro_are_13_over_18(role: str) -> None:
    theme = _theme_blocks(_css())
    assert _declaration(theme, f"--text-{role}") == "0.8125rem"
    assert _declaration(theme, f"--text-{role}--line-height") == "1.125rem"


def _rule(css: str, selector_pattern: str) -> str:
    found = re.search(selector_pattern + r"\s*\{([^{}]*)\}", css)
    assert found, selector_pattern
    return found.group(1)


def test_running_text_reads_16_over_24_on_phones_and_15_over_22_from_1024px() -> None:
    css = _css()
    root = re.search(r":root\s*\{(\s*/\* Running text[^{}]*)\}", css)
    assert root, "the running-text token"
    assert _declaration(root.group(1), "--read-size") == "1rem"
    assert _declaration(root.group(1), "--read-leading") == "1.5"  # 24 px at 16 px
    wide = re.search(r"@media \(min-width: 1024px\)\s*\{\s*:root\s*\{([^{}]*)\}", css)
    assert wide, "the running-text token's 1024 px step"
    assert _declaration(wide.group(1), "--read-size") == "0.9375rem"
    assert _declaration(wide.group(1), "--read-leading") == "calc(22 / 15)"  # 22 px at 15 px
    body = _rule(css, r"\n  body")
    assert _declaration(body, "font-size") == "var(--read-size)"
    assert _declaration(body, "line-height") == "var(--read-leading)"
    utility = _rule(css, r"@utility text-read")
    assert _declaration(utility, "font-size") == "var(--read-size)"
    assert _declaration(utility, "line-height") == "var(--read-leading)"


def test_inputs_stay_16px_below_1024px() -> None:
    css = _css()
    assert re.search(
        r"@media \(max-width: 1023px\) \{[^{}]*\n\s*input:not\(\[type=\"checkbox\"\]\):not\(\[type=\"radio\"\]\)"
        r":not\(\[type=\"range\"\]\), textarea, select \{ font-size: 16px; \}",
        css,
    )
    assert "@media (max-width: 1023px) { .ui-input { height: 44px; font-size: 16px; }" in css


DISPLAY_STACK = (
    'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI Variable Display", "Segoe UI", Roboto, '
    '"Noto Sans", "Helvetica Neue", Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji"'
)
HEADINGS = ("h1", "h2", ".ui-page-title", ".text-display", ".text-h1", ".text-h2", "h3", ".text-h3", ".ui-card-title")


def test_headings_use_the_system_display_cut() -> None:
    css = _css()
    assert _declaration(css, "--brand-font-display") == DISPLAY_STACK
    assert _declaration(css, "--font-display") == "var(--brand-font-display)"
    rule = re.search(r"^[ \t]*([^{}\n]+?)\s*\{\s*font-family: var\(--font-display\);\s*\}", css, re.MULTILINE)
    assert rule, "a rule that sets the display stack on the headings"
    selectors = {selector.strip() for selector in rule.group(1).split(",")}
    assert selectors == set(HEADINGS)
    assert "@font-face" not in css and "@import url" not in css  # 0 KB, nothing from another host


def test_titles_and_headings_are_700_with_the_display_tracking() -> None:
    theme = _theme_blocks(_css())
    assert _declaration(theme, "--text-display--font-weight") == "700"
    assert _declaration(theme, "--text-display--letter-spacing") == "-0.03em"
    assert _declaration(theme, "--text-h1--font-weight") == "700"
    assert _declaration(theme, "--text-h1--letter-spacing") == "-0.02em"
    assert _declaration(theme, "--text-h2--font-weight") == "700"
    assert _declaration(theme, "--text-h3--font-weight") == "700"
    css = _css()
    title = _rule(css, r"\n\s*\.ui-page-title")
    assert _declaration(title, "font-weight") == "700"
    assert _declaration(title, "letter-spacing") == "-0.02em"
    assert _declaration(_rule(css, r"\n\s*\.ui-card-title"), "font-weight") == "700"


def test_no_weight_above_700() -> None:
    weights = re.findall(r"font-weight\s*:\s*(\d+)", _css()) + re.findall(r"--font-weight\s*:\s*(\d+)", _css())
    assert weights and max(map(int, weights)) <= 700
