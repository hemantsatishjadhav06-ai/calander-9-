"""The shared components (Phase 3, T8; docs/specs/phase-3.md; spec D5, D6, D8 and F4).

- ``components/primary_action.html``: the view's one solid Pine button. One ``<a>`` or ``<button>``
  with its words, an ``aria-hidden`` icon and the test id it is given; ``aria-haspopup="dialog"``,
  ``aria-expanded`` and ``aria-controls`` when it opens a dialog. Below 1024 px it floats (``.ui-fab``,
  fixed 16 px from the right above the phone bar, 56 px tall); from 1024 px it is ``lg:static`` in the
  page header. ``test_one_primary.py`` checks where it sits on a page.
- ``components/empty_state.html``: a 32 px line icon, one sentence, one tinted or secondary button.
- ``components/inline_confirm.html``: the act's button with ``aria-expanded``; a ``role="group"``
  region labelled by the words of what it removes or starts; Cancel and the confirm, which repeats the
  act; Escape cancels and returns focus to the act. No modal, no ``hx-confirm``, no ``confirm()``.
- styles.css: ``.ui-fab``; the status border on ``[data-tone]`` rows (2 px, the tone's 500 step); the
  toasts lifted above the floating button on phones while ``body.has-fab`` (as ``has-selection`` lifts
  them over the selection bars); the button hidden while a selection bar shows.
- One status mapping each: ``approval_extras.status_tone`` reads ``STATUS_META``, and
  ``studio_status.brief_status_meta`` / ``brief_tone`` hold the briefs' (the brief pill renders exactly
  as before, status by status). Every ``data-tone`` written in a template is one of the five tones.
- The guard (D8): no template in a gated screen's tree contains ``hx-confirm`` or ``confirm(``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from django.template import engines
from django.template.loader import render_to_string

from apps.approvals.templatetags.approval_extras import STATUS_META
from apps.common import screens
from apps.common.tests.test_one_primary import ABOVE_THE_BAR, Node, elements, parse
from apps.studio.models import StudioBrief
from tools import recolor

ROOT = Path(__file__).resolve().parents[3]
STYLES = ROOT / "theme" / "static_src" / "src" / "styles.css"
TONES = ("neutral", "info", "success", "warning", "danger")


def _render(name: str, context: Mapping[str, object]) -> Node:
    return parse(render_to_string(name, dict(context)))


def _only(root: Node, *tags: str) -> Node:
    found = [node for node in elements(root) if node.tag in tags]
    assert len(found) == 1, [node.tag for node in found]
    return found[0]


def _source(name: str) -> str:
    path = screens.find_template(name)
    assert path is not None, name
    return path.read_text(encoding="utf-8")


# ── components/primary_action.html ─────────────────────────────────────────────────────────────

NEW_POST = {"label": "New post", "testid": "new-post-open", "controls": "new-post-sheet", "dispatch": "new-post:open"}


def test_the_primary_action_is_one_button_with_its_words_icon_and_test_id():
    root = _render("components/primary_action.html", NEW_POST)
    button = _only(root, "a", "button")

    assert button.tag == "button" and button.attrs["type"] == "button"
    assert button.attrs["data-testid"] == "new-post-open"
    assert button.text() == "New post"
    icons = [node for node in elements(button) if node.tag == "svg"]
    assert len(icons) == 1 and icons[0].attrs.get("aria-hidden") == "true"
    # It opens a dialog: it says so, and the dialog keeps aria-expanded current.
    assert button.attrs["aria-haspopup"] == "dialog"
    assert button.attrs["aria-expanded"] == "false"
    assert button.attrs["aria-controls"] == "new-post-sheet"
    assert button.attrs["@click"] == "$dispatch('new-post:open')"


def test_the_primary_action_floats_above_the_phone_bar_and_sits_in_the_header_from_1024px():
    button = _only(_render("components/primary_action.html", NEW_POST), "a", "button")
    classes = button.classes

    assert {"ui-btn", "ui-btn-primary", "ui-fab"} <= classes
    # Below 1024px: fixed, 16px from the right, above the phone bar (the toasts' and bars' class string).
    assert {"fixed", "right-4", ABOVE_THE_BAR} <= classes
    assert "max-sm:bottom-4" not in classes and not any(
        word.startswith("bottom-") and word != ABOVE_THE_BAR for word in classes
    )
    # From 1024px: in the page header's flow.
    assert "lg:static" in classes
    # Under the drawer's scrim (z-30) and the dialogs, beside the phone bar (z-20).
    assert "z-20" in classes


def test_a_primary_link_is_an_a_and_claims_no_dialog_it_does_not_open():
    root = _render("components/primary_action.html", {"label": "New post", "testid": "x-open", "href": "/compose/"})
    link = _only(root, "a", "button")

    assert link.tag == "a" and link.attrs["href"] == "/compose/"
    assert {"aria-haspopup", "aria-expanded", "aria-controls", "type", "@click"}.isdisjoint(link.attrs)
    assert {"ui-btn-primary", "ui-fab", "lg:static", ABOVE_THE_BAR} <= link.classes


def test_the_primary_action_escapes_its_words():
    html = render_to_string("components/primary_action.html", {"label": "<b>New</b>", "testid": "t"})
    assert "<b>" not in html and "&lt;b&gt;New&lt;/b&gt;" in html


# ── components/empty_state.html ────────────────────────────────────────────────────────────────


def test_the_empty_state_is_a_line_icon_one_sentence_and_one_button():
    root = _render(
        "components/empty_state.html",
        {
            "icon": "approvals",
            "sentence": "Nothing waits for you.",
            "action_label": "Open Calendar",
            "action_href": "/calendar/",
            "testid": "approvals-empty",
        },
    )
    block = next(elements(root))
    assert "ui-empty" in block.classes and block.attrs["data-testid"] == "approvals-empty"

    icon = block.children[0]
    assert icon.tag == "svg" and icon.attrs["aria-hidden"] == "true"
    assert icon.attrs["fill"] == "none" and icon.attrs["stroke"] == "currentColor"  # a line icon
    assert "size-8" in icon.classes  # 32px (and .ui-empty > svg says so in styles.css)

    sentences = [node for node in elements(block) if node.tag == "p"]
    assert [node.text() for node in sentences] == ["Nothing waits for you."]

    action = _only(block, "a", "button")
    assert action.tag == "a" and action.attrs["href"] == "/calendar/" and action.text() == "Open Calendar"
    assert {"ui-btn", "ui-btn-tinted"} <= action.classes
    assert action.attrs["data-testid"] == "approvals-empty-action"


@pytest.mark.parametrize(
    ("tone", "expected"), [("secondary", "ui-btn-secondary"), ("primary", "ui-btn-tinted"), ("", "ui-btn-tinted")]
)
def test_the_empty_states_button_is_tinted_or_secondary_never_primary(tone, expected):
    context = {
        "icon": "inbox",
        "sentence": "No messages yet.",
        "action_label": "Connect an account",
        "action_href": "/x/",
    }
    action = _only(_render("components/empty_state.html", {**context, "action_tone": tone}), "a", "button")
    assert expected in action.classes
    assert "ui-btn-primary" not in action.classes and "bg-brand-700" not in action.classes


def test_an_empty_states_button_can_open_a_dialog():
    root = _render(
        "components/empty_state.html",
        {
            "icon": "home",
            "sentence": "Nothing yet.",
            "action_label": "New post",
            "action_dispatch": "new-post:open",
            "action_controls": "new-post-sheet",
        },
    )
    button = _only(root, "a", "button")
    assert button.tag == "button" and button.attrs["type"] == "button"
    assert button.attrs["@click"] == "$dispatch('new-post:open')"
    assert (button.attrs["aria-haspopup"], button.attrs["aria-expanded"], button.attrs["aria-controls"]) == (
        "dialog",
        "false",
        "new-post-sheet",
    )


def test_an_empty_state_without_an_action_has_no_button():
    root = _render("components/empty_state.html", {"icon": "activity", "sentence": "Nothing ran today."})
    assert not [node for node in elements(root) if node.tag in ("a", "button")]


# ── components/inline_confirm.html ─────────────────────────────────────────────────────────────

DELETE_ROUTINE = {
    "confirm_id": "routine-7-delete",
    "label": "Delete",
    "words": "Delete the routine Morning post? It stops running.",
    "confirm_label": "Delete routine",
    "action": "/workspace/1/studio/routines/7/delete/",
    "testid": "routine-delete",
}


def _parts(root: Node) -> tuple[Node, Node, Node, Node, Node]:
    """The wrapper, the act's button, the region, Cancel and the confirm."""
    wrapper = next(elements(root))
    by_id = {node.attrs["data-testid"]: node for node in elements(root) if "data-testid" in node.attrs}
    stem = min(by_id, key=len)
    return wrapper, by_id[stem], by_id[f"{stem}-region"], by_id[f"{stem}-cancel"], by_id[f"{stem}-confirm"]


def test_the_inline_confirm_opens_a_labelled_group_from_the_acts_button():
    root = _render("components/inline_confirm.html", DELETE_ROUTINE)
    wrapper, act, region, cancel, confirm = _parts(root)

    assert act.tag == "button" and act.attrs["type"] == "button" and act.text() == "Delete"
    assert act.attrs["aria-expanded"] == "false" and act.attrs[":aria-expanded"] == "open.toString()"
    assert act.attrs["aria-controls"] == "routine-7-delete" == region.attrs["id"]

    # The region is a group named by the words of what it removes; hidden at rest.
    assert region.attrs["role"] == "group"
    words = next(node for node in elements(root) if node.attrs.get("id") == region.attrs["aria-labelledby"])
    assert words.text() == "Delete the routine Morning post? It stops running."
    assert region.attrs["x-show"] == "open" and "x-cloak" in region.attrs

    # Cancel, then the confirm on the right, which repeats the act.
    assert cancel.tag == "button" and cancel.attrs["type"] == "button" and cancel.text() == "Cancel"
    assert confirm.text() == "Delete routine"
    buttons = [node for node in elements(region) if node.tag == "button"]
    assert buttons == [cancel, confirm]
    assert "x-data" in wrapper.attrs


def test_the_confirm_posts_the_act_with_its_token(rf):
    # Rendered with a request, as a page renders it, so the token is there.
    root = parse(render_to_string("components/inline_confirm.html", DELETE_ROUTINE, request=rf.get("/")))
    *_, confirm = _parts(root)
    form = next(node for node in confirm.ancestors() if node.tag == "form")

    assert form.attrs["method"] == "post" and form.attrs["action"] == DELETE_ROUTINE["action"]
    assert any(node.attrs.get("name") == "csrfmiddlewaretoken" for node in elements(form))
    assert confirm.attrs["type"] == "submit"


def test_the_confirm_can_post_with_htmx_instead():
    context = {**DELETE_ROUTINE, "action": "", "hx_post": "/x/delete/", "hx_target": "#rows", "hx_swap": "outerHTML"}
    root = _render("components/inline_confirm.html", context)
    *_, confirm = _parts(root)

    assert not [node for node in elements(root) if node.tag == "form"]
    assert (confirm.attrs["hx-post"], confirm.attrs["hx-target"], confirm.attrs["hx-swap"]) == (
        "/x/delete/",
        "#rows",
        "outerHTML",
    )
    assert confirm.attrs["type"] == "button"


@pytest.mark.parametrize(
    ("tone", "act_class", "confirm_class"),
    [
        ("danger", "ui-btn-danger-ghost", "ui-btn-danger"),
        ("", "ui-btn-danger-ghost", "ui-btn-danger"),
        ("paid", "ui-btn-secondary", "ui-btn-tinted"),
    ],
)
def test_a_destructive_confirm_is_danger_and_a_paid_one_tinted_never_primary(tone, act_class, confirm_class):
    root = _render("components/inline_confirm.html", {**DELETE_ROUTINE, "tone": tone})
    _, act, _, _, confirm = _parts(root)
    assert act_class in act.classes and confirm_class in confirm.classes
    assert not [node for node in elements(root) if "ui-btn-primary" in node.classes]


def test_escape_and_cancel_close_the_confirm_and_return_focus_to_the_act():
    root = _render("components/inline_confirm.html", DELETE_ROUTINE)
    wrapper, act, region, cancel, _ = _parts(root)

    assert act.attrs["x-ref"] == "act" and cancel.attrs["x-ref"] == "cancel"
    # Opening moves focus to Cancel (the act that changes nothing), so the words are read out first.
    assert "open = !open" in act.attrs["@click"] and "$refs.cancel.focus()" in act.attrs["@click"]
    # Escape anywhere inside cancels, keeps an enclosing dialog open, and puts focus back on the act.
    escape = wrapper.attrs["@keydown.escape"]
    assert "if (open)" in escape and "$event.stopPropagation()" in escape
    assert "open = false" in escape and "$refs.act.focus()" in escape
    assert "open = false" in cancel.attrs["@click"] and "$refs.act.focus()" in cancel.attrs["@click"]


def test_no_component_asks_in_a_modal_or_the_browser():
    for name in ("components/inline_confirm.html", "components/primary_action.html", "components/empty_state.html"):
        assert not confirm_findings(_source(name), name), name


# ── styles.css: the floating button, the lifts, the status border ──────────────────────────────


def _css_rules() -> list[tuple[tuple[str, ...], str, str]]:
    """``(the at-rules around it, its selector, its declarations)`` for every rule in styles.css."""
    css = recolor._mask_css_comments(STYLES.read_text(encoding="utf-8"))
    found: list[tuple[tuple[str, ...], str, str]] = []
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


def _declarations(selector: str) -> list[tuple[tuple[str, ...], str]]:
    return [(around, body) for around, prelude, body in _css_rules() if prelude == selector]


PHONES = "@media (max-width: 1023px)"
#: The floating button's top on a phone: 4.5rem above the bottom edge, 56px tall, then a 16px gap.
ABOVE_THE_BUTTON = "calc(9rem + env(safe-area-inset-bottom))"


def test_the_floating_button_is_56px_tall_on_phones_in_the_components_layer():
    rules = _declarations(".ui-fab")
    assert rules, "styles.css has no .ui-fab rule"
    phone = [body for around, body in rules if around == ("@layer components", PHONES)]
    assert phone and re.search(r"(?<![\w-])height: 56px;", phone[0]), rules
    assert all(around[0] == "@layer components" for around, _ in rules), rules


@pytest.mark.parametrize("selector", ["body.has-fab #bb-toast-host", 'body.has-fab [data-testid="error-toast"]'])
def test_the_toasts_rise_above_the_floating_button_on_phones(selector):
    # Unlayered: the toast host's rules are an unlayered <style> in approvals/partials/_toasts.html and
    # the error toast's bottom is a utility; a layered rule would lose to both.
    assert _declarations(selector) == [((PHONES,), f"bottom: {ABOVE_THE_BUTTON};")]


def test_the_floating_button_hides_while_a_selection_bar_shows():
    rules = _declarations("body.has-selection .ui-fab, body.has-approval-selection .ui-fab")
    assert rules == [((), "visibility: hidden;")], rules


def test_the_last_line_and_a_focused_control_clear_the_floating_button_on_phones():
    # WCAG 2.4.11: the page's room at the end and its scrollers' bottom padding grow by the button.
    assert _declarations("body.has-fab [data-phone-bar-room]") == [((PHONES,), "height: 8.5rem;")]
    assert _declarations("body.has-fab [data-phone-bar-scroll]") == [
        ((PHONES,), "scroll-padding-bottom: calc(8.5rem + env(safe-area-inset-bottom));")
    ]


@pytest.mark.parametrize("tone", TONES)
def test_a_toned_row_draws_a_2px_left_border_in_its_tones_500_step(tone):
    scale = "ink" if tone == "neutral" else tone
    assert _declarations(f'[data-tone="{tone}"]') == [
        (("@layer components",), f"border-left: 2px solid var(--{scale}-500);")
    ]


def test_only_the_five_tones_draw_a_border():
    toned = {prelude for _, prelude, _ in _css_rules() if "[data-tone" in prelude}
    assert toned == {f'[data-tone="{tone}"]' for tone in TONES}, toned


# ── One status mapping each ────────────────────────────────────────────────────────────────────


def test_status_tone_reads_the_one_mapping():
    from apps.approvals.templatetags.approval_extras import status_tone

    for status, meta in STATUS_META.items():
        assert status_tone(status) == meta["tone"] in TONES, status
    assert status_tone("no-such-status") == "neutral" == status_tone(None)


def test_every_brief_status_has_one_tone_and_icon():
    from apps.studio.templatetags.studio_status import BRIEF_STATUS_META, brief_status_meta, brief_tone

    assert set(BRIEF_STATUS_META) == set(StudioBrief.Status.values)
    for status in StudioBrief.Status:
        meta = brief_status_meta(status)
        assert meta["tone"] in TONES and meta["icon"], status
        assert brief_tone(status) == meta["tone"] == brief_tone(str(status.value)), status
    assert brief_tone("no-such-status") == "neutral" == brief_tone(None)
    assert brief_status_meta("") == {"tone": "neutral", "icon": "dash"}


# The brief pill as it was before the move (templates/studio/partials/status_badge.html on 57af454).
OLD_BRIEF_PILL = (
    "{% comment %}Status pill for a Studio brief: icon and word in one tone (studio/partials/pill.html). "
    "Context: status (value), label (display).\nWorking and queued are in the team's hands (info); ready waits "
    "for a person (warning); approved happened (success); failed stopped (danger).{% endcomment %}\n"
    '{% if status == \'working\' %}{% include "studio/partials/pill.html" with tone="info" icon="spinner" label=label %}'
    '{% elif status == \'queued\' or status == \'planned\' %}{% include "studio/partials/pill.html" with tone="info" icon="dots" label=label %}'
    '{% elif status == \'ready\' %}{% include "studio/partials/pill.html" with tone="warning" icon="clock" label=label %}'
    '{% elif status == \'approved\' %}{% include "studio/partials/pill.html" with tone="success" icon="check" label=label %}'
    '{% elif status == \'failed\' %}{% include "studio/partials/pill.html" with tone="danger" icon="x" label=label %}'
    '{% else %}{% include "studio/partials/pill.html" with tone="neutral" icon="dash" label=label %}{% endif %}\n'
)


@pytest.mark.parametrize("status", [*StudioBrief.Status.values, "no-such-status", "", None])
@pytest.mark.parametrize("extra", [{}, {"data_state": "working"}])
def test_the_brief_pill_renders_exactly_as_before_status_by_status(status, extra):
    context = {"status": status, "label": "Ready <for> approval", **extra}
    before = engines["django"].from_string(OLD_BRIEF_PILL).render(context)
    after = render_to_string("studio/partials/status_badge.html", context)
    assert after == before


def test_the_brief_pill_reads_the_mapping_instead_of_its_own_branches():
    source = _source("studio/partials/status_badge.html")
    assert "brief_status_meta" in source and "status ==" not in source


DATA_TONE_RE = re.compile(r"""data-tone\s*=\s*(["'])(.*?)\1""", re.S)
ALLOWED_EXPRESSION = re.compile(r"{{\s*[\w.]+\s*\|\s*(?:status_tone|brief_tone)\s*}}")


def tone_findings(text: str, path: str = "<string>") -> list[str]:
    """Every ``data-tone`` value that is neither one of the five tones nor one of the two mappings' filters."""
    findings = []
    for match in DATA_TONE_RE.finditer(text):
        value = match.group(2).strip()
        if value not in TONES and not ALLOWED_EXPRESSION.fullmatch(value):
            findings.append(f"{path}:{text.count(chr(10), 0, match.start()) + 1}: data-tone={value!r}")
    return findings


def _all_templates() -> list[Path]:
    paths: list[Path] = []
    for directory in screens.TEMPLATE_DIRS:
        paths += sorted(directory.rglob("*.html"))
    return paths


def test_every_data_tone_in_a_template_is_one_of_the_five_tones():
    findings = [
        finding
        for path in _all_templates()
        for finding in tone_findings(path.read_text(encoding="utf-8"), str(path.relative_to(ROOT)))
    ]
    assert not findings, "A row's tone comes from the status mappings (spec D6):\n" + "\n".join(findings)


@pytest.mark.parametrize(
    ("source", "bad"),
    [
        ('<li data-tone="info">', False),
        ('<li data-tone="neutral">', False),
        ("<li data-tone='danger'>", False),
        ('<li data-tone="{{ post.status|status_tone }}">', False),
        ('<tr data-tone="{{ brief.status|brief_tone }}">', False),
        ('<li data-tone="pink">', True),
        ('<li data-tone="brand">', True),
        ('<li data-tone="">', True),
        ('<li data-tone="{{ row.tone }}">', True),
        ('<li data-tone="{{ post.status }}">', True),
        ('<li data-tone="{% if x %}info{% endif %}">', True),
    ],
)
def test_the_tone_check_on_fixture_strings(source, bad):
    assert bool(tone_findings(source)) is bad, source


# ── The guard: no modal, hx-confirm or confirm() in a gated screen (D8) ────────────────────────

COMMENTS_RE = re.compile(r"{%\s*comment\b.*?%}.*?{%\s*endcomment\s*%}|{#.*?#}|<!--.*?-->", re.S)
CONFIRM_RE = re.compile(r"hx-confirm|(?<![\w$])confirm\s*\(")


def confirm_findings(text: str, path: str = "<string>") -> list[str]:
    masked = COMMENTS_RE.sub(lambda match: re.sub(r"[^\n]", " ", match.group(0)), text)
    return [
        f"{path}:{masked.count(chr(10), 0, match.start()) + 1}: {match.group(0)}"
        for match in CONFIRM_RE.finditer(masked)
    ]


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
        findings += confirm_findings(path.read_text(encoding="utf-8"), name)
    return findings


def test_no_gated_screen_confirms_in_a_modal_or_the_browser():
    findings = guard_findings()
    assert not findings, "Confirm inline instead (spec D8, components/inline_confirm.html):\n" + "\n".join(findings)


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
    write("partials/row.html", '<li>\n  <button hx-post="/x/" hx-confirm="Delete it?">Delete</button>\n</li>')
    write("partials/fragment.html", "<button @click=\"if (window.confirm('Sure?')) go()\">Go</button>")
    write("pages/untouched.html", "<button onclick=\"return confirm('Sure?')\">Old</button>")
    registry = {
        "rebuilt": screens.Screen(templates=("pages/rebuilt.html",), fragments=("partials/fragment.html",), gated=True),
        "next": screens.Screen(templates=("pages/untouched.html",)),
    }

    assert guard_findings(registry, [tmp_path]) == [
        "partials/fragment.html:1: confirm(",
        "partials/row.html:2: hx-confirm",
    ]


@pytest.mark.parametrize(
    ("source", "bad"),
    [
        ('<button hx-delete="/x/" hx-confirm="Delete?">', True),
        ("<button onclick=\"return confirm('Sure?')\">", True),
        ("<button @click=\"confirm ('Sure?') && go()\">", True),
        ("<script>if (window.confirm('Sure?')) go();</script>", True),
        ('<button @click="confirming = true">Delete</button>', False),
        ('<button x-ref="confirm">Delete routine</button>', False),
        ("<button @click=\"inlineConfirm('x')\">", False),
        ("<button @click=\"$confirm('x')\">", False),
        ("{# hx-confirm was here #}<button>", False),
        ("{% comment %}\nconfirm('x')\n{% endcomment %}<button>", False),
        ("<!-- hx-confirm --><button>", False),
        ('{% include "components/inline_confirm.html" with label="Delete" %}', False),
    ],
)
def test_the_confirm_check_on_fixture_strings(source, bad):
    assert bool(confirm_findings(source)) is bad, source
