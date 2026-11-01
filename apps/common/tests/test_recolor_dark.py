"""The dark codemod and recolor's new rules (docs/specs/phase-3.md T3; spec D2 and F1).

``tools/recolor.py`` gains a dark pass and new ``--check`` rules, so the utilities that do not follow
Layer 1 (``bg-white``, ``text-white`` on a fill, the scrims, white edges, ink-300 edges) move to tokens
whose light value is the literal they replace, and light rendering cannot move:

* the inventory of solid dark fills: every ``bg-ink-800|900|950`` on main is listed below with its
  decision, *inverse* (stays dark in both themes: ``bg-inverse``/``text-on-inverse``), *flips*
  (``text-on-fill`` on it) or *light scope* (a platform preview, kept as the platform shows it);
* each rewrite, input against output; each check, a temporary template that makes ``--check`` fail
  and name the file; the styles.css rule (no colour literal outside Layer 1 but the palette lock);
* the contrast pairs these need: edges that stay edges in dark, marks on a card, the toggle knob, and
  the children of the selection bars measured inside their light scope.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from apps.common import screens
from tools import contrast, recolor

TEMPLATES = recolor.ROOT / "templates"

INVERSE, FLIPS, LIGHT_SCOPE = "inverse", "flips", "light scope"

#: Every solid ``bg-ink-800|900|950`` on main (045978b): 39 uses in 25 templates. Each entry is
#: (template, markers the element's start tag carries that survive the rewrite, decision, how many tags
#: carry them). A preview's fills sit inside the light scope and keep the platform's look; that entry
#: counts the file's solid dark fills instead of a marker.
DARK_FILLS: tuple[tuple[str, str | tuple[str, ...], str, int], ...] = (
    # Logo marks: the workspace initial, as the sidebar's logo mark (inverse in the spec, D2).
    ("base.html", ("rounded-[7px] flex items-center justify-center", "text-[13px] font-semibold"), INVERSE, 3),
    (
        "client_portal/portal_base.html",
        "flex size-7 flex-shrink-0 items-center justify-center rounded-[7px]",
        INVERSE,
        1,
    ),
    ("client_portal/magic_link_confirm.html", "rounded-[10px]", INVERSE, 1),
    ("workspaces/list.html", "grid size-9 shrink-0 place-items-center rounded-[7px]", INVERSE, 1),
    ("organizations/partials/workspace_card.html", "grid size-9 shrink-0 place-items-center rounded-[7px]", INVERSE, 1),
    ("onboarding/connection_page.html", "inline-flex h-14 w-14 items-center justify-center rounded-2xl", INVERSE, 1),
    # The two selection bars (their children use white and 200/300 steps), the composer's error toast,
    # its tooltip, and its selected override chip (a selected filter chip).
    ("calendar/calendar.html", 'data-testid="calendar-bulk-bar"', INVERSE, 1),
    ("calendar/partials/publish_approvals.html", "flex items-center gap-1 pl-4 pr-1.5 py-1.5", INVERSE, 1),
    ("composer/compose.html", 'x-show="formError"', INVERSE, 1),
    ("composer/compose.html", "pointer-events-none absolute left-3 -top-6", INVERSE, 1),
    ("composer/compose.html", ":data-testid=\"'compose-override-toggle-' + accId\"", INVERSE, 1),
    # Avatars, step numbers, today's date, badges and marks: an ink fill that flips with its text.
    ("components/agent_avatar.html", "{% if agent.slug == 'account_manager' %}bg-ink-900", FLIPS, 1),
    (
        "client_portal/partials/team_messages.html",
        "grid size-7 flex-shrink-0 place-items-center rounded-full bg-ink-900",
        FLIPS,
        1,
    ),
    ("client_portal/portal_base.html", 'href="#portal-main"', FLIPS, 1),
    ("composer/partials/csv_validation.html", "w-7 h-7 rounded-full bg-ink-900", FLIPS, 1),
    ("composer/partials/csv_mapping.html", "w-7 h-7 rounded-full bg-ink-900", FLIPS, 1),
    ("composer/csv_import.html", "w-7 h-7 rounded-full bg-ink-900", FLIPS, 1),
    ("composer/compose.html", "w-7 h-7 rounded-full bg-ink-900", FLIPS, 1),
    ("composer/compose.html", "w-9 h-9 rounded-lg bg-ink-900", FLIPS, 1),
    (
        "intelligence/subscribe.html",
        "absolute -top-2.5 right-4 inline-flex h-5 items-center rounded-full bg-ink-900",
        FLIPS,
        1,
    ),
    ("intelligence/_score_video_hook_result.html", "ui-pill mb-1 !bg-ink-900", FLIPS, 1),
    ("media_library/asset_edit.html", "absolute top-0 bottom-0 w-0.5 bg-ink-900", FLIPS, 1),
    ("organizations/partials/week_grid.html", "{% if day == today %}bg-ink-900", FLIPS, 1),
    (
        "inbox/partials/_assignment_dropdown.html",
        "grid size-5 flex-shrink-0 place-items-center rounded-full bg-ink-900",
        FLIPS,
        1,
    ),
    ("calendar/partials/week_grid.html", "{% if day == today %}bg-ink-900", FLIPS, 1),
    ("studio/partials/team_roster.html", "{% if agent.slug == 'account_manager' %}bg-ink-900", FLIPS, 1),
    (
        "studio/partials/thread_messages.html",
        "{% if m.agent == 'account_manager' or not m.agent %}bg-ink-900",
        FLIPS,
        1,
    ),
    ("studio/partials/team_track.html", "{% if track.agent.slug == 'account_manager' %}bg-ink-900", FLIPS, 1),
    (
        "studio/partials/team_upcoming.html",
        "inline-flex h-4 min-w-4 flex-none items-center justify-center rounded-full bg-ink-900",
        FLIPS,
        1,
    ),
    # The composer's previews: video canvases, an avatar and a carousel's dots, inside the light scope.
    ("composer/partials/preview_panel.html", (), LIGHT_SCOPE, 8),
)

SOLID_DARK_RE = re.compile(r"(?<![\w/-])(?:[a-z0-9-]+:)*!?bg-ink-(?:800|900|950)(?![\w/-])")


def _tags_with(template: str, marker: str | tuple[str, ...]) -> list[recolor.Element]:
    text = (TEMPLATES / template).read_text(encoding="utf-8")
    if not marker:  # every solid dark fill in the file
        return [element for element in recolor.elements(text) if SOLID_DARK_RE.search(" ".join(element.classes))]
    markers = (marker,) if isinstance(marker, str) else marker
    return [element for element in recolor.elements(text) if all(m in element.tag for m in markers)]


def test_the_inventory_counts_main_s_39_dark_fills():
    assert sum(count for *_, count in DARK_FILLS) == 39
    assert len({template for template, *_ in DARK_FILLS}) == 25


@pytest.mark.parametrize(("template", "marker", "decision", "count"), DARK_FILLS)
def test_each_dark_fill_carries_its_decision(template, marker, decision, count):
    found = _tags_with(template, marker)
    assert len(found) == count, f"{template}: {len(found)} tags carry {marker!r}"
    for element in found:
        classes = " ".join(element.classes)
        if decision == INVERSE:
            assert re.search(r"(?<![\w-])(?:[a-z-]+:)*!?bg-inverse\b", classes), element.tag
            assert not SOLID_DARK_RE.search(classes), element.tag
            assert not re.search(r"(?<![\w-])(?:[a-z-]+:)*text-white\b", classes), element.tag
        elif decision == FLIPS:
            assert SOLID_DARK_RE.search(classes), element.tag
            assert not re.search(r"(?<![\w-])(?:[a-z-]+:)*text-white\b", classes), element.tag
        else:
            assert element.in_light_scope, f"{template}: {element.tag} is outside the light scope"


def test_every_solid_dark_fill_left_is_in_the_inventory():
    """A new solid ink fill needs a decision here: it flips, or it is inverse (bg-inverse)."""
    listed = [(t, (m,) if isinstance(m, str) else m) for t, m, decision, _ in DARK_FILLS if decision != INVERSE]
    unlisted = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        name = recolor.template_name(path)
        for element in recolor.elements(path.read_text(encoding="utf-8")):
            if SOLID_DARK_RE.search(" ".join(element.classes)) and not any(
                name == t and all(m in element.tag for m in markers) for t, markers in listed
            ):
                unlisted.append(f"{name}: {element.tag[:120]}")
    assert unlisted == []


def test_the_selection_bars_keep_their_light_look_in_both_themes():
    """Their children use 200 and 300 steps that flip (hover:text-danger-200 would read 1.21:1 in dark)."""
    for template, marker in (
        ("calendar/calendar.html", 'data-testid="calendar-bulk-bar"'),
        ("calendar/partials/publish_approvals.html", "flex items-center gap-1 pl-4 pr-1.5 py-1.5"),
    ):
        (bar,) = _tags_with(template, marker)
        assert 'data-theme-scope="light"' in bar.tag


def test_the_previews_sit_in_the_light_scope_and_keep_the_platforms_white():
    text = (TEMPLATES / "composer/partials/preview_panel.html").read_text(encoding="utf-8")
    (card,) = [element for element in recolor.elements(text) if "preview-card" in element.classes]
    assert 'data-theme-scope="light"' in card.tag
    assert "bg-white" in text and "bg-white/90" in text  # the platform's canvas and carousel buttons


# ── Rewrites: input and expected output ─────────────────────────────────────────────────────────


def dark(text: str, name: str = "x/page.html") -> str:
    return recolor.recolor_dark(text, name=name)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        # bg-white is the card surface outside the light scope.
        ('<div class="rounded bg-white p-4"></div>', '<div class="rounded bg-surface p-4"></div>'),
        ('<a class="hover:bg-white bg-white/90"></a>', '<a class="hover:bg-surface bg-surface/90"></a>'),
        # The light scope keeps the platform's look.
        (
            '<div data-theme-scope="light"><div class="bg-white"><b class="bg-white/90 bg-ink-900 text-white">'
            "</b></div></div>",
            '<div data-theme-scope="light"><div class="bg-white"><b class="bg-white/90 bg-ink-900 text-white">'
            "</b></div></div>",
        ),
        # text-white on a fill that flips, its own or the nearest ancestor's, is text on the fill.
        ('<span class="grid bg-ink-900 text-white">A</span>', '<span class="grid bg-ink-900 text-on-fill">A</span>'),
        (
            '<span class="bg-success-500 text-white"><svg class="text-white"></svg></span>',
            '<span class="bg-success-500 text-on-fill"><svg class="text-on-fill"></svg></span>',
        ),
        (
            '<div class="bg-brand-700"><p>Hi <svg class="w-3 text-white"></svg></p></div>',
            '<div class="bg-brand-700"><p>Hi <svg class="w-3 text-on-fill"></svg></p></div>',
        ),
        (
            '<span class="x {% if a %}bg-ink-900 text-white{% else %}bg-ink-100 text-ink-700{% endif %}"></span>',
            '<span class="x {% if a %}bg-ink-900 text-on-fill{% else %}bg-ink-100 text-ink-700{% endif %}"></span>',
        ),
        (
            '<a class="sr-only focus:bg-ink-900 focus:text-white"></a>',
            '<a class="sr-only focus:bg-ink-900 focus:text-on-fill"></a>',
        ),
        (
            "<b class=\"h-8\" :class=\"on ? 'bg-ink-900 text-white' : 'bg-white text-ink-700 ring-1 ring-ink-300'\"></b>",
            "<b class=\"h-8\" :class=\"on ? 'bg-ink-900 text-on-fill' : 'bg-surface text-ink-700 ring-1 ring-line-strong'\"></b>",
        ),
        # A dark fill whose children use white or 200/300 steps is inverse: it stays dark, its own white
        # text becomes text-on-inverse, its children keep white (the palette lock) and their edges move
        # to on-inverse.
        (
            '<div class="bg-ink-900 text-white rounded-xl"><span class="bg-white/20"></span>'
            '<button class="text-white hover:bg-white/10 focus-visible:outline-white">Draft</button></div>',
            '<div class="bg-inverse text-on-inverse rounded-xl"><span class="bg-white/20"></span>'
            '<button class="text-white hover:bg-white/10 focus-visible:outline-on-inverse">Draft</button></div>',
        ),
        # ... and when a child uses a step that flips, the bar keeps its light look in both themes.
        (
            '<div class="bg-ink-900 text-white"><button class="text-danger-300 hover:text-danger-200">Delete</button></div>',
            '<div data-theme-scope="light" class="bg-inverse text-on-inverse">'
            '<button class="text-danger-300 hover:text-danger-200">Delete</button></div>',
        ),
        # Scrims: ink-950 at any opacity and ink-900 from 30 % are behind dialogs or over photos.
        ('<div class="ui-overlay bg-ink-950/35"></div>', '<div class="ui-overlay bg-scrim/35"></div>'),
        ('<span class="bg-ink-900/80 text-white"></span>', '<span class="bg-scrim/80 text-white"></span>'),
        ('<a class="hover:bg-ink-900/5"></a>', '<a class="hover:bg-ink-900/5"></a>'),
        (
            '<div class="bg-ink-950/0 group-hover:bg-ink-950/20"></div>',
            '<div class="bg-scrim/0 group-hover:bg-scrim/20"></div>',
        ),
        # A black photo overlay does not flip: it stays.
        (
            '<div class="bg-black/50"><svg class="text-white"></svg></div>',
            '<div class="bg-black/50"><svg class="text-white"></svg></div>',
        ),
        # A state whose fill flips gets text on the fill for that state; the photo's scrim keeps white.
        (
            '<button class="bg-ink-950/60 hover:bg-danger-500 text-white focus-visible:outline-white"></button>',
            '<button class="bg-scrim/60 hover:bg-danger-500 text-white hover:text-on-fill focus-visible:outline-white">'
            "</button>",
        ),
        # White edges: the card's colour on content.
        (
            '<span class="bg-success-500 text-white ring-[3px] ring-white"></span>',
            '<span class="bg-success-500 text-on-fill ring-[3px] ring-surface"></span>',
        ),
        ('<img class="border-2 border-white">', '<img class="border-2 border-surface">'),
        # ink-300 is a text grey in dark: its edges move to the edge token (ink-300 in light).
        (
            '<div class="border border-ink-300 hover:ring-ink-300 hover:border-ink-300 divide-ink-300">'
            '<svg><line class="stroke-ink-300"/></svg><span class="text-ink-300"></span></div>',
            '<div class="border border-line-strong hover:ring-line-strong hover:border-line-strong divide-line-strong">'
            '<svg><line class="stroke-line-strong"/></svg><span class="text-ink-300"></span></div>',
        ),
        (
            "<style>.a { border: 1px solid var(--ink-300); box-shadow: inset 0 0 0 1px var(--ink-300); "
            "color: var(--ink-300); }</style>",
            "<style>.a { border: 1px solid var(--border-hover); box-shadow: inset 0 0 0 1px var(--border-hover); "
            "color: var(--ink-300); }</style>",
        ),
        # An arbitrary shadow written as a literal reads its token.
        (
            '<img class="w-7 shadow-[inset_0_0_0_1px_rgba(14,17,20,.06)]">',
            '<img class="w-7 shadow-[var(--shadow-creative)]">',
        ),
        # A line marked `recolor: keep` is left alone.
        (
            '<span class="bg-brand-700 text-white"></span>{# recolor: keep #}',
            '<span class="bg-brand-700 text-white"></span>{# recolor: keep #}',
        ),
    ],
)
def test_each_rewrite(before, after):
    assert dark(before) == after
    assert dark(after) == after  # idempotent


def test_named_inverse_elements_are_inverse_only_where_named():
    tip = '<span class="pointer-events-none absolute left-3 -top-6 opacity-0 bg-ink-800 text-white">Tip</span>'
    assert dark(tip, "composer/compose.html") == tip.replace("bg-ink-800 text-white", "bg-inverse text-on-inverse")
    assert dark(tip, "x/page.html") == tip.replace("text-white", "text-on-fill")


def test_python_and_js_class_strings_move_too():
    form = 'attrs={"class": "w-full rounded-lg border border-ink-400 bg-white p-3"}'
    assert recolor.transform(Path("apps/x/forms.py"), form, tokens=True, defined=set()) == form.replace(
        "bg-white", "bg-surface"
    )
    js = "el.className = 'rounded bg-white ring-1 ring-ink-300';"
    assert recolor.transform(Path("static/js/x.js"), js, tokens=True, defined=set()) == (
        "el.className = 'rounded bg-surface ring-1 ring-line-strong';"
    )


def test_pages_without_the_stylesheet_keep_white():
    email = '<td class="bg-white">Hi</td>'
    assert recolor.transform(Path("templates/email/x.html"), email, tokens=False, defined=set()) == email


# ── New --check rules: each fails on a temporary template and names it ──────────────────────────────

CLEAN_CSS = """@theme {
  --color-*: initial;
  --color-white: #fff;
  --color-black: #000;
}
:root { --ink-0: #FFFFFF; --ink-900: #1C1F24; --danger-200: #FFCDC6; --danger-300: #FEA69C; }
:root { --surface-0: var(--ink-0); }
:root[data-theme="dark"] { --ink-0: #14171C; --ink-900: #E5E8EC; --danger-200: #642722; --danger-300: #FEA69C; }
"""


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A repository of its own: templates, a stylesheet, no screenshots."""
    (tmp_path / "templates").mkdir()
    (tmp_path / "static" / "js").mkdir(parents=True)
    (tmp_path / "apps").mkdir()
    css = tmp_path / "theme" / "static_src" / "src" / "styles.css"
    css.parent.mkdir(parents=True)
    css.write_text(CLEAN_CSS, encoding="utf-8")
    monkeypatch.setattr(recolor, "ROOT", tmp_path)
    monkeypatch.setattr(recolor, "MARKETING_IMAGES", tmp_path / "static" / "img" / "marketing")
    monkeypatch.setattr(screens, "DARK_READY", frozenset())
    monkeypatch.setattr(screens, "SCREENS", {})

    def write(name: str, text: str) -> Path:
        path = tmp_path / "templates" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    return write


def run_check(capsys) -> tuple[int, str]:
    code = recolor.main(["--check"])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_the_fixture_tree_is_clean(tree, capsys):
    tree("page.html", '{% extends "base.html" %}<div class="bg-surface text-ink-900"></div>')
    tree("base.html", '<html><link href="css/dist/styles.css"></html>')
    assert run_check(capsys) == (0, "recolor: nothing left to do\n")


@pytest.mark.parametrize(
    ("markup", "message"),
    [
        ('<div class="rounded bg-white"></div>', "bg-white outside the light scope"),
        ('<span class="bg-ink-900 text-white">A</span>', "text-white on a fill that flips"),
        ('<div class="bg-brand-700"><svg class="text-white"></svg></div>', "text-white on a fill that flips"),
        ('<div class="bg-success-500"><i class="bg-white/20"></i></div>', "bg-white/20 on a fill that flips"),
        ('<div class="bg-brand-700"><i class="hover:bg-white/10"></i></div>', "hover:bg-white/10 on a fill that flips"),
        (
            '<div class="bg-inverse text-on-inverse"><b class="hover:text-danger-200"></b></div>',
            "hover:text-danger-200 flips on an inverse surface",
        ),
        ('<div class="border border-ink-300"></div>', "border-ink-300 is a text grey in dark"),
    ],
)
def test_each_check_fails_and_names_the_file(tree, capsys, markup, message):
    tree("base.html", '<html><link href="css/dist/styles.css"></html>')
    tree("studio/bad.html", '{% extends "base.html" %}\n' + markup)
    code, out = run_check(capsys)
    assert code == 1
    assert f"templates/studio/bad.html:2: {message}" in out


@pytest.mark.parametrize(
    "markup",
    [
        '<div data-theme-scope="light"><div class="bg-white"><b class="bg-ink-900 text-white"></b></div></div>',
        '<span class="bg-ink-900 text-white">A</span> {# recolor: keep #}',
        '<div class="bg-inverse text-on-inverse"><b class="text-white hover:bg-white/10 text-ink-300 text-danger-300"></b></div>',
        '<div data-theme-scope="light" class="bg-inverse"><b class="hover:text-danger-200"></b></div>',
        '<div class="bg-scrim/60 text-white"><i class="bg-white/20"></i></div>',
        '<span class="pi-linkedin text-white"></span>',
    ],
)
def test_what_the_checks_accept(tree, capsys, markup):
    tree("base.html", '<html><link href="css/dist/styles.css"></html>')
    tree("studio/ok.html", '{% extends "base.html" %}\n' + markup)
    assert run_check(capsys)[0] == 0


def test_a_page_without_the_stylesheet_may_use_white(tree, capsys):
    tree("email/notice.html", '<html><body><td class="bg-white">Hi</td></body></html>')
    assert run_check(capsys)[0] == 0


@pytest.mark.parametrize(
    ("markup", "colour"),
    [
        ("<style>.a { color: #123456; }</style>", "#123456"),
        ('<p style="color: rgb(1 2 3)">x</p>', "rgb("),
        ("<p :style=\"'background: #fff'\">x</p>", "#fff"),
        ('<svg><path fill="#123456"/></svg>', "#123456"),
        ('<p class="bg-[#123456]">x</p>', "#123456"),
        ('<img class="shadow-[0_1px_2px_rgb(1_2_3/.24)]">', "rgb("),
    ],
)
def test_a_raw_colour_in_a_dark_ready_page_s_tree_fails(tree, capsys, monkeypatch, markup, colour):
    tree("base.html", '<html><link href="css/dist/styles.css">{% block content %}{% endblock %}</html>')
    tree(
        "studio/index.html",
        '{% extends "base.html" %}{% block content %}{% include "studio/part.html" %}{% endblock %}',
    )
    tree("studio/part.html", "<div>\n" + markup + "\n</div>")
    tree("studio/elsewhere.html", '{% extends "base.html" %}\n' + markup)
    assert run_check(capsys)[0] == 0  # nobody is declared yet
    monkeypatch.setattr(screens, "DARK_READY", frozenset({("studio", "index")}))
    monkeypatch.setattr(screens, "PAGE_TEMPLATES", {("studio", "index"): ("studio/index.html",)})
    code, out = run_check(capsys)
    assert code == 1
    assert f"templates/studio/part.html:2: raw colour {colour}" in out
    assert "elsewhere.html" not in out  # not in a declared page's tree


@pytest.mark.parametrize(
    "markup",
    [
        '<input type="color" value="#123456">',
        "<div data-presets='[\"#123456\"]'></div>",
        '<p style="color: #123456">x</p> {# recolor: keep #}',
        '<div data-theme-scope="light"><p style="color: #123456">x</p><svg><path fill="#FF0000"/></svg></div>',
        '<p class="bg-[#0A66C2]">in</p><svg><path fill="#FF0000"/></svg>',  # a platform's own colours
        '{% include "social_accounts/partials/_platform_icon.html" %}',
    ],
)
def test_raw_colours_the_rule_exempts(tree, capsys, monkeypatch, markup):
    tree("base.html", '<html><link href="css/dist/styles.css">{% block content %}{% endblock %}</html>')
    tree("studio/index.html", '{% extends "base.html" %}{% block content %}' + markup + "{% endblock %}")
    tree("social_accounts/partials/_platform_icon.html", '<svg><path fill="#0A66C2"/></svg>')
    monkeypatch.setattr(screens, "DARK_READY", frozenset({("studio", "index")}))
    monkeypatch.setattr(screens, "PAGE_TEMPLATES", {("studio", "index"): ("studio/index.html",)})
    assert run_check(capsys)[0] == 0


def test_a_screen_s_fragments_are_held_to_the_raw_colour_rule(tree, capsys, monkeypatch):
    tree("studio/fragment.html", '<p style="color: #123456">x</p>')
    monkeypatch.setattr(screens, "SCREENS", {"s": screens.Screen(templates=(), fragments=("studio/fragment.html",))})
    code, out = run_check(capsys)
    assert code == 1 and "templates/studio/fragment.html:1: raw colour #123456" in out


# ── styles.css: no colour literal outside Layer 1 ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("css", "literal"),
    [
        (".a { box-shadow: 0 1px 2px rgba(14, 17, 20, .05); }", "rgba("),
        (".a { color: #FFFFFF; }", "#FFFFFF"),
        (".a { color: hsl(0 0% 100%); }", "hsl("),
        (":root { --shadow-xs: 0 1px 2px rgba(14, 17, 20, .05); }", "rgba("),
        ("@theme { --shadow-sm: 0 1px 2px rgba(14, 17, 20, .04); }", "rgba("),
        ("@keyframes p { 0% { box-shadow: 0 0 0 0 rgb(3 90 123 / .35); } }", "rgb("),
        ('[data-theme-scope="light"] { --overlay: rgb(14 17 20 / .36); }', "rgb("),
    ],
)
def test_a_literal_outside_layer_1_fails(css, literal):
    (line,) = recolor.styles_problems(CLEAN_CSS + css)
    assert line.startswith(f"theme/static_src/src/styles.css:{CLEAN_CSS.count(chr(10)) + 1}:") and literal in line


def test_layer_1_the_palette_lock_selectors_and_comments_pass():
    css = (
        CLEAN_CSS
        + ':root[data-theme="dark"] { --ink-0: #14171C; }\n'
        + "@media (prefers-color-scheme: dark) { :root[data-theme-ready] { --ink-0: #14171C; } }\n"
        + '[data-theme-scope="light"] { --ink-0: #FFFFFF; }\n'
        + "#bb-toast-host { bottom: 1rem; } /* #fff on rgba(0,0,0,.5) */\n"
        + ".a { background: var(--surface-0); box-shadow: 0 1px 2px color-mix(in srgb, var(--scrim) 4%, transparent); }\n"
    )
    assert recolor.styles_problems(css) == []


def test_the_palette_lock_is_exempt_only_inside_theme():
    assert recolor.styles_problems(CLEAN_CSS + ".a { --color-white: #fff; }") != []


def test_styles_css_writes_no_colour_outside_layer_1():
    css = (recolor.ROOT / "theme/static_src/src/styles.css").read_text(encoding="utf-8")
    assert recolor.styles_problems(css) == []


def test_shadow_utilities_read_the_themed_tokens():
    """Tailwind inlines an @theme shadow's literal into .shadow-sm, so the utilities point at Layer 2."""
    rules = contrast.parse((recolor.ROOT / "theme/static_src/src/styles.css").read_text(encoding="utf-8"))
    shadows = {
        name: value
        for rule in rules
        if rule.selector == "@theme" and not rule.parents
        for name, value in rule.declarations.items()
        if name.startswith("--shadow-")
    }
    assert shadows and all(value == f"var({name})" for name, value in shadows.items())


def test_the_select_chevron_is_drawn_in_tertiary_text_in_each_theme():
    """A data URI cannot read a variable, so each theme carries its own; each matches --text-tertiary."""
    sheet = contrast.load()
    for theme, values in (
        ("light", sheet.theme("light")),
        ("dark", sheet.theme("dark")),
        ("light scope", contrast.in_light_scope(sheet, "dark")),
    ):
        chevron = contrast.resolve_name("--select-chevron", values)
        (encoded,) = re.findall(r"stroke='%23([0-9A-Fa-f]{6})'", chevron)
        tertiary = contrast.hex_of(contrast.colour_of("--text-tertiary", values))
        assert f"#{encoded.upper()}" == tertiary, theme


def test_the_check_passes_on_the_tree(capsys):
    """C6: nothing left to do, with the new rules."""
    code, out = run_check(capsys)
    assert code == 0, out


# ── Contrast pairs these rewrites rely on ─────────────────────────────────────────────────────────


def _pairs(group: str) -> list[contrast.Pair]:
    return [pair for pair in contrast.PAIRS if pair.group == group]


def test_edges_stay_edge_grade_in_both_themes():
    """ink-300 reads 6.03:1 on a dark card; the edge token keeps a border's weight (1.52:1 in light)."""
    edges = _pairs(contrast.EDGES)
    assert {pair.fg for pair in edges} == {"--border-hover"}
    assert all(pair.at_most for pair in edges)
    sheet = contrast.load()
    for theme in ("light", "dark"):
        assert contrast.problems(sheet, theme, edges) == []
    text_grey = replace(sheet, dark={**sheet.dark, "--border-hover": "var(--ink-300)"})
    assert contrast.problems(text_grey, "dark", edges) != []


def test_the_selection_bars_children_are_measured_inside_their_light_scope():
    bar = [pair for pair in contrast.PAIRS if pair.scope == "light"]
    assert {pair.fg for pair in bar} >= {"--danger-200", "--danger-300", "--brand-950", "--ink-300", "#FFFFFF"}
    sheet = contrast.load()
    assert contrast.problems(sheet, "dark", bar) == []
    # Outside the scope the hover step would read 1.21:1 on the dark inverse surface.
    unscoped = [contrast.Pair(p.group, p.label, p.fg, p.bg, p.needs) for p in bar if p.fg == "--danger-200"]
    assert contrast.problems(sheet, "dark", unscoped) != []


def test_marks_on_a_card_and_the_toggle_knob_are_paired():
    labelled = {pair.label for pair in contrast.PAIRS}
    assert {
        "current hour and now line ink-900 on card ink-0",
        "toggle knob on-fill on the off track ink-400",
        "toggle knob on-fill on the on track brand-700",
    } <= labelled
