"""Dark tokens and the contrast checker (docs/specs/phase-3.md T2, spec D2; DESIGN_SYSTEM.md §21, §23).

``tools/contrast.py`` reads Layer 1 and Layer 2 of ``theme/static_src/src/styles.css`` for both
themes, resolves ``var()`` chains and measures every pair with the WCAG 2.x method of §23. These tests
prove the method on fixtures and §23's own rows, then hold the stylesheet to it: every pair passes in
both themes, the dark media block equals the dark attribute block, every token has a dark value, the
new tokens keep light where it was, and the light content scope equals the light ``:root``.
"""

from __future__ import annotations

import re
from dataclasses import replace

import pytest

from tools import contrast

FIXTURE = """
@theme inline { --probe-utility: var(--surface-0); }
/* Layer 1 */
:root { --ink-0: #FFFFFF; --ink-50: #F6F7F8; --ink-900: #1C1F24; --brand-700: #115641; }
/* Layer 2 */
:root {
  color-scheme: light;
  --surface-0: var(--ink-0);
  --card: var(--surface-0);
  --veil: rgb(246 247 248 / .92);
  --halo: color-mix(in srgb, var(--brand-700) 18%, transparent);
  --radius: 0.5rem;
}
@media (max-width: 1023px) { :root { --ink-0: #000000; } }
:root[data-theme="dark"] { --ink-0: #14171C; --ink-50: #0B0F13; --ink-900: #E9EBEE; --brand-700: #6CC4A1; }
:root[data-theme="dark"] { color-scheme: dark; --veil: color-mix(in srgb, var(--ink-50) 92%, transparent); }
@media (prefers-color-scheme: dark) {
  :root[data-theme-ready]:not([data-theme='light']) { --ink-0: #14171C; }
}
[data-theme-scope="light"] { color-scheme: light; --ink-0: #FFFFFF; }
"""


@pytest.fixture(scope="module")
def sheet() -> contrast.Sheet:
    return contrast.load()


# (a) The parser reads Layer 1 and Layer 2 for both themes and resolves var() chains.


def test_parser_reads_both_themes_and_resolves_var_chains():
    fixture = contrast.load(FIXTURE)
    assert list(fixture.layer1) == ["--ink-0", "--ink-50", "--ink-900", "--brand-700"]
    assert fixture.layer2["--card"] == "var(--surface-0)"
    assert fixture.dark["--ink-0"] == "#14171C" and fixture.dark["color-scheme"] == "dark"
    assert fixture.dark_media == {"--ink-0": "#14171C"}  # the quotes are normalised
    assert fixture.light_scope == {"color-scheme": "light", "--ink-0": "#FFFFFF"}
    assert fixture.theme_inline == {"--probe-utility": "var(--surface-0)"}
    # A :root nested in another media query is neither layer.
    assert fixture.layer1["--ink-0"] == "#FFFFFF"

    light, dark = fixture.theme("light"), fixture.theme("dark")
    assert contrast.resolve_name("--card", light) == "#FFFFFF"  # two hops: --card → --surface-0 → --ink-0
    assert contrast.resolve_name("--card", dark) == "#14171C"
    assert contrast.hex_of(contrast.colour_of("--veil over #FFFFFF", dark)) == "#1F2226"
    assert contrast.parse_colour(contrast.resolve_name("--halo", light)) == pytest.approx((17, 86, 65, 0.18))
    assert contrast.parse_colour("rgba(14, 17, 20, .05)") == pytest.approx((14, 17, 20, 0.05))
    assert contrast.parse_colour("color-mix(in srgb, #000000 50%, #FFFFFF)") == pytest.approx((127.5, 127.5, 127.5, 1))
    # Themed Layer 2 is what paints a colour; a radius is not themed.
    assert fixture.layer2_names() == ["color-scheme", "--surface-0", "--card", "--veil", "--halo"]
    with pytest.raises(ValueError, match="cycle"):
        contrast.resolve("var(--a)", {"--a": "var(--b)", "--b": "var(--a)"})


def test_parser_reads_the_light_layers_of_the_stylesheet(sheet):
    light = sheet.theme("light")
    assert sheet.layer1["--ink-950"] == "#0E1114" and sheet.layer1["--brand-700"] == "#115641"
    assert len(sheet.layer1) == 13 + 11 * 5  # ink 0–950, and brand and the four statuses 50–950
    assert contrast.resolve_name("--primary-strong", light) == "#115641"
    assert contrast.resolve_name("--text-ghost", light) == "#656B73"
    assert "--radius-lg" not in sheet.layer2_names() and "--surface-sticky" in sheet.layer2_names()


# (b) Five light rows of §23 are reproduced to two decimals (the method is §23's).


@pytest.mark.parametrize(("fg", "bg", "expected"), contrast.SECTION_23_ROWS)
def test_the_method_reproduces_section_23(sheet, fg, bg, expected):
    light = sheet.theme("light")
    measured = contrast.ratio(contrast.colour_of(fg, light), contrast.colour_of(bg, light))
    assert f"{measured:.2f}" == expected


def test_the_sticky_bar_blends_as_section_23_did(sheet):
    light = sheet.theme("light")
    assert contrast.hex_of(contrast.colour_of("--surface-sticky over #1E2533", light)) == "#E5E6E8"
    assert contrast.hex_of(contrast.colour_of("--surface-sticky over #F97316", light)) == "#F6ECE6"


def test_a_pair_under_its_bar_fails(sheet):
    broken = replace(sheet, dark={**sheet.dark, "--ink-500": "#FFFFFF", "--ink-0": "#FFFFFF"})
    assert any("tertiary ink-500 on card ink-0" in line for line in contrast.problems(broken, "dark"))


# (c) Every pair passes in both themes.


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_pair_passes(sheet, theme):
    assert sheet.dark, "no :root[data-theme=dark] block"
    assert contrast.problems(sheet, theme) == []


def test_the_checker_exits_cleanly(capsys):
    assert contrast.main([]) == 0, capsys.readouterr().err


def test_status_icons_are_paired_with_every_surface_and_their_chip():
    """3:1 for status-500 icons on every surface (plan T2), as the control border and the focus ring are."""
    checked = {(pair.fg, pair.bg) for pair in contrast.PAIRS if pair.needs == contrast.NON_TEXT}
    missing = [
        f"--{status}-500 on {bg}"
        for status in contrast.STATUSES
        for bg in (*(token for _, token in contrast.SURFACES), f"--{status}-50")
        if (f"--{status}-500", bg) not in checked
    ]
    assert missing == []


@pytest.mark.parametrize(
    ("surface", "status", "label"),
    [
        ("--brand-50", "--warning-500", "warning-500 icon on selected row brand-50"),
        ("--ink-100", "--danger-500", "danger-500 icon on sidebar ink-100"),
    ],
)
def test_a_status_icon_under_its_bar_on_any_surface_fails(sheet, surface, status, label):
    broken = replace(sheet, dark={**sheet.dark, surface: sheet.dark[status]})
    assert any(label in line for line in contrast.problems(broken, "dark"))


SIDEBAR_HOVER_ICON = "ink-600 icon on the sidebar's hover fill (line-strong)"


def test_the_sidebar_s_hover_fill_carries_its_icon_in_both_themes(sheet):
    """The collapsed sidebar's account button: an ink-600 icon on its hover fill. line-strong is ink-300
    in light (light does not move) and a fill in dark; ink-300 itself is a text grey in dark (1.49:1)."""
    (pair,) = [pair for pair in contrast.PAIRS if pair.label == SIDEBAR_HOVER_ICON]
    assert (pair.fg, pair.bg, pair.needs, pair.light_exception) == (
        "--ink-600",
        "--border-hover",
        contrast.NON_TEXT,
        "",
    )
    assert contrast.resolve_name("--border-hover", sheet.theme("light")) == sheet.layer1["--ink-300"]
    for theme in ("light", "dark"):
        assert contrast.problems(sheet, theme, [pair]) == []
    text_grey = replace(sheet, dark={**sheet.dark, "--border-hover": "var(--ink-300)"})
    (line,) = contrast.problems(text_grey, "dark", [pair])
    assert "1.49:1" in line


#: The selected filter chip (the owner's choice before Home and Calendar were declared ready, T22).
SELECTED_CHIP_RULE = re.compile(r'\.ui-filter-chip\[aria-pressed="true"\], \.ui-filter-chip\.is-selected \{([^}]*)\}')
SELECTED_CHIP_PAIRS = (
    "selected filter chip ink-900 on card ink-0",
    "selected filter chip ink-900 on canvas ink-50",
    "its words on-fill on ink-900",
    "its count on-fill-muted on ink-900",
)


def test_the_selected_filter_chip_is_ink_900_with_on_fill_words(sheet):
    """ink-900 with on-fill words, as the current hour keeps ink-900: light does not move (the inverse
    surface and its words were the same #1C1F24 and white), and in dark the chip stands off the card and
    the canvas, where the inverse surface sat 1.32:1 and 1.41:1 and the selected state rested on that.
    Its count takes on-fill-muted, ink-300 in light (as before) and readable on the light chip in dark."""
    rule = SELECTED_CHIP_RULE.search(contrast.STYLES.read_text(encoding="utf-8"))
    assert rule, "styles.css has no rule for the selected filter chip"
    assert "background: var(--ink-900);" in rule.group(1) and "color: var(--on-fill);" in rule.group(1)
    light = sheet.theme("light")
    for now, was in (("--ink-900", "--surface-inverse"), ("--on-fill", "--text-on-inverse")):
        assert contrast.hex_of(contrast.colour_of(now, light)) == contrast.hex_of(contrast.colour_of(was, light))
    assert contrast.hex_of(contrast.colour_of("--on-fill-muted", light)) == sheet.layer1["--ink-300"]

    pairs = {pair.label: pair for pair in contrast.PAIRS}
    assert set(SELECTED_CHIP_PAIRS) <= set(pairs), sorted(set(SELECTED_CHIP_PAIRS) - set(pairs))
    chip = [pairs[label] for label in SELECTED_CHIP_PAIRS]
    assert [(pair.fg, pair.bg, pair.needs) for pair in chip] == [
        ("--ink-900", "--ink-0", contrast.NON_TEXT),
        ("--ink-900", "--ink-50", contrast.NON_TEXT),
        ("--on-fill", "--ink-900", contrast.TEXT),
        ("--on-fill-muted", "--ink-900", contrast.TEXT),
    ]
    for theme in ("light", "dark"):
        assert contrast.problems(sheet, theme, chip) == []
    # What the inverse surface would have been in dark: under 3:1 on both.
    dark = sheet.theme("dark")
    was = [contrast.measure(replace(pair, fg="--surface-inverse"), dark) for pair in chip[:2]]
    assert [f"{result.ratio:.2f}" for result in was] == ["1.32", "1.41"]
    # And ink-300, the count's light colour, on the dark chip.
    assert not contrast.measure(replace(chip[3], fg="--ink-300"), dark).passed


def test_the_one_light_exception_is_named_pinned_and_held_in_dark(sheet):
    """success-500 on ink-100 was 2.93:1 in light before F1 and light must not move; dark holds it."""
    excepted = [pair for pair in contrast.PAIRS if pair.light_exception]
    assert list(contrast.LIGHT_EXCEPTIONS) == [("--success-500", "--ink-100")]
    assert [(pair.fg, pair.bg) for pair in excepted] == list(contrast.LIGHT_EXCEPTIONS)  # each used once
    pair = excepted[0]
    light = contrast.measure(pair, sheet.theme("light"))
    assert not light.passed
    assert f"{light.ratio:.2f}:1" in pair.light_exception  # the reason quotes today's light ratio
    assert contrast.measure(pair, sheet.theme("dark")).passed
    assert not any(pair.label in line for line in contrast.problems(sheet, "light"))
    broken = replace(sheet, dark={**sheet.dark, "--ink-100": sheet.dark["--success-500"]})
    assert any(pair.label in line for line in contrast.problems(broken, "dark"))


# (d) The media block and the attribute block declare the same properties with the same values.


def test_the_media_block_equals_the_attribute_block(sheet):
    assert sheet.dark, "no :root[data-theme=dark] block"
    assert sheet.dark_media == sheet.dark


# (e) Every Layer 1 and Layer 2 property has a dark value.


def test_every_token_has_a_dark_value(sheet):
    assert contrast.missing_dark_values(sheet) == []
    assert contrast.missing_dark_values(sheet, sheet.dark_media) == []


def test_dark_layer_two_writes_no_colour_literal(sheet):
    """A dark semantic token points at a dark Layer 1 step; only Layer 1 writes a colour (T3's rule)."""
    literals = {
        name: value
        for name, value in sheet.dark.items()
        if name not in sheet.layer1 and contrast.LITERAL_RE.search(value)
    }
    assert literals == {}


# (f) The new tokens' light values equal the literals they replace, so light rendering cannot move.


def test_new_tokens_keep_the_light_values(sheet):
    light = sheet.theme("light")
    measured = {name: contrast.hex_of(contrast.colour_of(name, light)) for name in contrast.NEW_TOKENS}
    assert measured == contrast.NEW_TOKENS
    assert contrast.hex_of(contrast.colour_of("--surface-0", light)) == "#FFFFFF"
    assert {name: sheet.theme_inline.get(name) for name in contrast.UTILITIES} == contrast.UTILITIES


# (g) The light scope declares every Layer 1 and Layer 2 property with the light :root value.


def test_the_light_scope_equals_the_light_root(sheet):
    assert contrast.scope_differences(sheet) == []


def test_inside_the_light_scope_a_dark_page_paints_light(sheet):
    """What a preview inside the scope sees under the dark theme, resolved as a browser inherits."""
    assert sheet.dark and sheet.light_scope, "no dark block or no light scope"
    light = sheet.theme("light")
    inside = contrast.in_light_scope(sheet, "dark")
    names = [*sheet.layer1_names(), *(name for name in sheet.layer2_names() if name != "color-scheme")]
    moved = {
        name: (inside[name], contrast.resolve_name(name, light))
        for name in names
        if inside[name] != contrast.resolve_name(name, light)
    }
    assert moved == {}


def test_section_21_holds_the_checkers_tables(sheet):
    """DESIGN_SYSTEM.md §21 is ``python tools/contrast.py --markdown``, pasted verbatim (regenerate it)."""
    document = (contrast.ROOT / "docs" / "DESIGN_SYSTEM.md").read_text(encoding="utf-8")
    section = document[document.index("## 21. Dark mode") : document.index("## 22. ")]
    assert contrast.markdown(sheet) in section
