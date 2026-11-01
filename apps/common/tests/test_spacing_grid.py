"""The 8 px spacing grid and the card padding (Phase 3, T7; docs/specs/phase-3.md, spec D4 and F3).

Rebuilt screens space on 8 px steps (Tailwind 2, 4, 6, 8, 10, 12, 16, 20 …). The guard reads every
template in the tree of a ``gated`` screen (``apps/common/screens.py``: its root templates and
fragments, and everything they reach through a literal include or extends) and flags, on every
spacing utility (``p``, ``px``, ``py``, ``pt`` …, ``m`` …, ``gap``, ``gap-x|y``, ``space-x|y``,
``inset``, ``top|right|bottom|left``, ``start|end``), whatever breakpoint or state prefix it carries:

* an odd integer step (1, 3, 5, 7, 9, 11 …): 4 px apart is off the grid;
* a fractional step (``.5`` and any other): ``p-1.5`` is 6 px;
* ``px`` spacing (``mt-px``): 1 px;
* an arbitrary value with a length that is not a multiple of 8 px (``p-[13px]``, ``top-[calc(100%+4px)]``;
  a percentage, a viewport unit, ``env()`` or ``var()`` is not a length on the grid and passes).

Steps 1 and 3 (4 px and 12 px) pass only in the places ``SMALL_STEP_ALLOWLIST`` names, and the guard
reads that list as its rule: inside a control (the element itself or an ancestor in the same template
carries one of the ``control:`` classes, ``ui-btn`` and the rest, or the ``data-control`` marker) and
as the gap of an icon-and-label pair (an element whose children are one ``aria-hidden`` svg and
words). Classes come from ``class`` (every branch of a template tag included), from the strings of a
bound ``:class`` or ``x-bind:class`` (``{'mt-4':open}``, ``open?'pb-4':'pb-2'``), and from the
``*class*="…"`` arguments of an include or with tag (their element is in another file, so they get no
exemption).

The list of gated screens is empty until screen 1's gate; each rule is proved here on fixture strings,
and the wiring on fixture templates. The card padding is set in CSS, not by a utility, so the guard
never sees it: ``.ui-card`` is 20 px below 1024 px and 24 px from 1024 px, ``.ui-card-nested`` 16 px,
and ``.ui-sections`` puts 32 px between a screen's sections (``tests/e2e/self/foundations.spec.ts``
measures the card in the browser).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from apps.common import screens
from tools import recolor

ROOT = Path(__file__).resolve().parents[3]
STYLES = ROOT / "theme" / "static_src" / "src" / "styles.css"
GRID_PX = 8
STEP_PX = 4  # one Tailwind spacing step
ROOT_PX = 16

#: The steps that pass in the allowlisted places only (4 px and 12 px, spec D4).
SMALL_STEPS = frozenset({1, 3})

#: Where steps 1 and 3 may appear, and why: the explicit allowlist the plan asks for, and the rule the
#: guard applies (``_in_control`` and ``_icon_and_label`` read it when they run). ``control:<class>``
#: passes an element carrying that class (or ``<class>-…``, so ``ui-btn-sm`` and ``ui-pill-success``
#: count; ``ui-tabs`` and ``ui-table`` do not) and everything inside it in the same template;
#: ``control:[<attribute>]`` does the same for an element marked with that attribute; ``icon-and-label``
#: passes the gap of an element whose children are one ``aria-hidden`` svg and words.
SMALL_STEP_ALLOWLIST: dict[str, str] = {
    "control:ui-btn": "a button's padding and the space between its icon and its words",
    "control:ui-input": "a field's own padding",
    "control:ui-select": "the select control's toggle, panel and options",
    "control:ui-chip": "a chip's padding and its icon gap",
    "control:ui-tab": "a tab's padding and its icon gap",
    "control:ui-pill": "a status pill's padding and its icon gap",
    "control:[data-control]": "a control drawn without the shared classes marks itself",
    "icon-and-label": "the gap of an element whose children are one aria-hidden svg and its words",
}
CONTROL = "control:"
ICON_AND_LABEL = "icon-and-label"

SPACING_PREFIXES = r"p[xytrblse]?|m[xytrblse]?|gap(?:-[xy])?|space-[xy]|inset(?:-[xy])?|top|right|bottom|left|start|end"
UTILITY_RE = re.compile(rf"!?-?(?P<prefix>{SPACING_PREFIXES})-(?P<value>.+?)!?")
GAP_PREFIXES = frozenset({"gap", "gap-x", "gap-y", "space-x", "space-y"})
LENGTH_RE = re.compile(r"(?<![\d.a-zA-Z])(\d*\.?\d+)(px|rem|em)(?![a-zA-Z])")
ARIA_HIDDEN_RE = re.compile(r"""\saria-hidden(?:\s*=\s*(["'])true\1)?(?=[\s/>])""")
#: A string in a bound class (``:class``, ``x-bind:class``): a binding is a script expression, so the
#: class names it may add are its strings (``{'mt-4':open}``, ``open?'pb-4':'pb-2'``, a template
#: literal); the words around them are names and operators. Read before the value is split into words.
BOUND_STRING_RE = re.compile(r"""(['"`])(.*?)\1""", re.S)
#: ``{% include "x.html" with extra_class="…" %}`` and ``{% with icon_class="…" %}``.
TAG_CLASS_ARG_RE = re.compile(r"""\b\w*class\w*\s*=\s*(["'])(.*?)\1""")
TEMPLATE_TAG_RE = re.compile(r"{%\s*(?:include|with)\b.*?%}", re.S)
COMMENT_RE = re.compile(r"{%\s*comment\b.*?%}.*?{%\s*endcomment\s*%}|{#.*?#}|<!--.*?-->", re.S)
#: What is not a word of a label: comments, template tags (``{{ … }}`` is a word) and markup.
NOT_WORDS_RE = re.compile(COMMENT_RE.pattern + r"|{%.*?%}|<[^>]*>", re.S)
NOT_A_LABEL = frozenset({"svg", "img", "picture", "video", "canvas", "input", "select", "textarea", "button"})


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    word: str
    reason: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.word} ({self.reason})"


def _utility(word: str) -> tuple[str, str] | None:
    """``(prefix, value)`` of a spacing utility, its variant chain (``max-lg:``, ``[&>*]:``) dropped."""
    depth, cut = 0, 0
    for index, char in enumerate(word):
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        elif char == ":" and depth == 0:
            cut = index + 1
    found = UTILITY_RE.fullmatch(word[cut:])
    return (found["prefix"], found["value"]) if found else None


def step_problem(prefix: str, value: str, *, small_step_allowed: bool) -> str | None:
    """Why a spacing value is off the 8 px grid, or None."""
    if value == "px":
        return "px spacing"
    if re.fullmatch(r"\d*\.\d+", value):
        return f"step {value} is a fractional step"
    if value.isdigit():
        step = int(value)
        if step % 2 == 0:
            return None
        if step in SMALL_STEPS and small_step_allowed:
            return None
        if step in SMALL_STEPS:
            return f"step {step} ({step * STEP_PX} px) outside a control or an icon-and-label pair"
        return f"step {step} is {step * STEP_PX} px, off the 8 px grid"
    if value.startswith("[") and value.endswith("]"):
        for number, unit in LENGTH_RE.findall(value):
            pixels = float(number) * (1 if unit == "px" else ROOT_PX)
            if pixels % GRID_PX:
                return f"{number}{unit} is not a multiple of 8 px"
    return None


def _children(found: Sequence[recolor.Element], index: int) -> list[int]:
    return [child for child, element in enumerate(found) if element.ancestors[:1] == (index,)]


def _end(text: str, element: recolor.Element) -> int:
    """Where *element* ends, its closing tag included."""
    if element.close <= element.tag_end:
        return element.tag_end
    closing = text.find(">", element.close)
    return len(text) if closing == -1 else closing + 1


def _controls() -> tuple[tuple[str, ...], tuple[re.Pattern[str], ...]]:
    """The control classes and the marker attributes ``SMALL_STEP_ALLOWLIST`` names, as it stands now."""
    names: list[str] = []
    markers: list[re.Pattern[str]] = []
    for entry in SMALL_STEP_ALLOWLIST:
        if not entry.startswith(CONTROL):
            continue
        name = entry.removeprefix(CONTROL)
        if name.startswith("[") and name.endswith("]"):
            markers.append(re.compile(rf"\s{re.escape(name[1:-1])}(?=[\s=/>])"))
        else:
            names.append(name)
    return tuple(names), tuple(markers)


def _in_control(found: Sequence[recolor.Element], index: int) -> bool:
    """True when the element or an ancestor is a control the allowlist names."""
    names, markers = _controls()
    for place in (index, *found[index].ancestors):
        element = found[place]
        if any(marker.search(element.tag) for marker in markers):
            return True
        if any(word == name or word.startswith(name + "-") for word in element.classes for name in names):
            return True
    return False


def _icon_and_label(text: str, found: Sequence[recolor.Element], index: int) -> bool:
    """True when the allowlist names the pair and the element's children are one aria-hidden svg and
    words (text, or plain text elements)."""
    if ICON_AND_LABEL not in SMALL_STEP_ALLOWLIST:
        return False
    element = found[index]
    children = _children(found, index)
    icons = [child for child in children if found[child].name == "svg"]
    if len(icons) != 1 or not ARIA_HIDDEN_RE.search(found[icons[0]].tag):
        return False
    for child in children:
        if child != icons[0] and (found[child].name in NOT_A_LABEL or _children(found, child)):
            return False
    icon = found[icons[0]]
    words = text[element.tag_end : icon.start] + text[_end(text, icon) : element.close]
    return bool(NOT_WORDS_RE.sub(" ", words).strip())


def off_grid(text: str, path: str = "<string>") -> list[Finding]:
    """Every spacing utility in *text* (a template's source) that is off the 8 px grid."""
    masked = recolor._mask(text)
    found = recolor.elements(text)
    findings: list[Finding] = []

    def check(word: str, position: int, index: int | None) -> None:
        utility = _utility(word)
        if utility is None:
            return
        prefix, value = utility
        allowed = index is not None and (
            _in_control(found, index) or (prefix in GAP_PREFIXES and _icon_and_label(text, found, index))
        )
        problem = step_problem(prefix, value, small_step_allowed=allowed)
        if problem:
            findings.append(Finding(path, text.count("\n", 0, position) + 1, word, problem))

    for index, element in enumerate(found):
        for attribute in recolor.CLASS_ATTR_RE.finditer(masked, element.start, element.tag_end):
            value, start = attribute.group(3), attribute.start(3)
            parts = (
                [(value, start)]
                if attribute.group(1) == "class"
                else [(string.group(2), start + string.start(2)) for string in BOUND_STRING_RE.finditer(value)]
            )
            for part, offset in parts:
                for word in re.finditer(r"\S+", part):
                    check(word.group(0).strip("'\"{}(),:"), offset + word.start(), index)
    for tag in TEMPLATE_TAG_RE.finditer(COMMENT_RE.sub(recolor._blank, text)):
        for argument in TAG_CLASS_ARG_RE.finditer(tag.group(0)):
            for word in re.finditer(r"\S+", argument.group(2)):
                check(word.group(0), tag.start() + argument.start(2) + word.start(), None)
    return findings


def gated_templates(
    registry: Mapping[str, screens.Screen] | None = None, dirs: Sequence[Path] | None = None
) -> tuple[str, ...]:
    """Every template in the tree of a gated screen: its roots, its fragments and what they reach."""
    names: list[str] = []
    for screen in (screens.SCREENS if registry is None else registry).values():
        if screen.gated:
            for name in screens.template_tree((*screen.templates, *screen.fragments), dirs):
                if name not in names:
                    names.append(name)
    return tuple(names)


def grid_findings(
    registry: Mapping[str, screens.Screen] | None = None, dirs: Sequence[Path] | None = None
) -> list[Finding]:
    findings: list[Finding] = []
    for name in gated_templates(registry, dirs):
        path = screens.find_template(name, dirs)
        assert path is not None, name
        findings += off_grid(path.read_text(encoding="utf-8"), name)
    return findings


# ── The guard on the gated screens ─────────────────────────────────────────────────────────────


def test_gated_screens_space_on_the_8px_grid() -> None:
    findings = grid_findings()
    assert not findings, "Spacing off the 8 px grid in a gated screen (spec D4):\n" + "\n".join(map(str, findings))


def test_the_shell_spaces_on_the_8px_grid() -> None:
    """The shell (``base.html`` and every template it includes) is on the grid before any screen is gated.

    Every screen extends ``base.html``, so screen 1's gate reads the shell through its tree, and the owner
    signs the shell pair off at the foundations gate (plan T13). The rule is the gated screens' rule:
    steps 1 and 3 only inside a control or as an icon-and-label gap, no fractional or ``px`` steps.
    """
    tree = screens.template_tree(("base.html",))
    assert tree[0] == "base.html", tree
    findings: list[Finding] = []
    for name in tree:
        path = screens.find_template(name)
        assert path is not None, name
        findings += off_grid(path.read_text(encoding="utf-8"), name)
    assert not findings, f"{len(findings)} spacing utilities off the 8 px grid in the shell (spec D4):\n" + "\n".join(
        map(str, findings)
    )


def test_the_guard_reads_every_template_of_a_gated_screen_and_nothing_else(tmp_path: Path) -> None:
    def write(name: str, body: str) -> None:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    write("base.html", '<html><body class="p-4">{% block content %}{% endblock %}</body></html>')
    write(
        "pages/rebuilt.html",
        '{% extends "base.html" %}{% block content %}\n{% include "partials/row.html" %}{% endblock %}',
    )
    write("partials/row.html", '<div class="flex gap-4">\n  <p class="mt-5">Off the grid</p>\n</div>')
    write("partials/fragment.html", '<ul class="space-y-1.5"><li>One</li></ul>')
    write("pages/untouched.html", '<div class="p-3">Not rebuilt yet</div>')
    registry = {
        "rebuilt": screens.Screen(templates=("pages/rebuilt.html",), fragments=("partials/fragment.html",), gated=True),
        "next": screens.Screen(templates=("pages/untouched.html",)),
    }

    assert gated_templates(registry, [tmp_path]) == (
        "pages/rebuilt.html",
        "partials/fragment.html",
        "base.html",
        "partials/row.html",
    )
    found = {(finding.path, finding.line, finding.word) for finding in grid_findings(registry, [tmp_path])}
    assert found == {("partials/row.html", 2, "mt-5"), ("partials/fragment.html", 1, "space-y-1.5")}


# ── Each rule, on fixture strings ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "source",
    [
        # Odd steps, every spacing family, any prefix.
        '<div class="mt-5">',
        '<div class="gap-7">',
        '<div class="px-9">',
        '<div class="py-11">',
        '<div class="mb-13">',
        '<div class="sm:p-5">',
        '<div class="max-lg:-mx-7">',
        '<div class="hover:pl-9">',
        '<div class="group-hover:pr-5">',
        '<div class="data-[open=true]:pt-5">',
        '<div class="[&>*]:mb-7">',
        '<div class="lg:hover:ms-5">',
        '<div class="!me-5">',
        '<div class="mb-5!">',
        '<div class="gap-x-5 gap-y-4">',
        '<div class="space-x-5">',
        '<div class="-space-y-7">',
        '<div class="absolute inset-5">',
        '<div class="absolute inset-x-7">',
        '<div class="absolute inset-y-9">',
        '<div class="absolute top-5">',
        '<div class="absolute right-7">',
        '<div class="absolute bottom-9">',
        '<div class="absolute left-11">',
        '<div class="absolute start-5">',
        '<div class="absolute end-7">',
        # Steps 1 and 3 outside a control or an icon-and-label pair.
        '<div class="p-3">',
        '<div class="mt-1">',
        '<div class="-mt-3">',
        '<div class="flex gap-1"><span>Words only</span></div>',
        '<div class="absolute top-1 right-3">',
        '<span class="ui-table p-3">',
        '<div class="ui-tabs gap-1">',
        # Fractional steps, everywhere (inside a control too).
        '<div class="p-0.5">',
        '<div class="gap-1.5">',
        '<div class="space-y-2.5">',
        '<div class="mt-3.5">',
        '<div class="top-0.25">',
        '<button class="ui-btn gap-1.5">',
        # px spacing, everywhere.
        '<div class="mt-px">',
        '<div class="-mt-px">',
        '<div class="gap-px">',
        '<div class="absolute top-px">',
        '<span class="ui-pill mt-px">',
        # Odd steps other than 1 and 3 are never allowed, a control included.
        '<button class="ui-btn px-5">',
        '<span class="ui-chip gap-5"><svg aria-hidden="true"></svg>Label</span>',
        # Arbitrary values off the grid.
        '<div class="p-[13px]">',
        '<div class="max-lg:-my-[13px]">',
        '<div class="mt-[6px]">',
        '<div class="gap-x-[0.3rem]">',
        '<div class="absolute top-[3px]">',
        '<div class="absolute left-[calc(100%+4px)]">',
        '<div class="absolute bottom-[calc(1.25rem+env(safe-area-inset-bottom))]">',
        '<div class="p-[length:10px]">',
        '<div class="absolute top-[calc(100%_-_4px)]">',
        # Every place a class is written.
        "<div :class=\"{ 'mt-3': open }\">",
        "<div x-bind:class=\"open ? 'pb-5' : 'pb-4'\">",
        "<div :class=\"{'mt-5':open}\">",
        "<div :class=\"open?'pb-5':'pb-4'\">",
        '<div x-bind:class=\'open?"gap-1.5":"gap-2"\'>',
        "<div :class=\"`mt-5 ${open ? 'pb-4' : ''}`\">",
        '<div class="{% if wide %}px-5{% else %}px-4{% endif %}">',
        '<div\n    class="flex\n           mt-7">',
        '{% include "components/button.html" with extra_class="mt-3" %}',
        '{% with icon_class="mr-1.5" %}<span class="{{ icon_class }}"></span>{% endwith %}',
    ],
)
def test_the_guard_flags_off_grid_spacing(source: str) -> None:
    assert off_grid(source), source


@pytest.mark.parametrize(
    "source",
    [
        # Even steps and zero, any family and prefix.
        '<div class="p-0 m-0 gap-0 inset-0">',
        '<div class="p-2 px-4 py-6 pt-8 pr-10 pb-12 pl-16 ps-20 pe-2">',
        '<div class="m-2 mx-4 my-6 mt-8 mr-10 mb-12 ml-16 ms-20 me-24">',
        '<div class="gap-2 gap-x-4 gap-y-6 space-x-8 space-y-10">',
        '<div class="absolute inset-2 inset-x-4 inset-y-6 top-8 right-10 bottom-12 left-16 start-2 end-4">',
        '<div class="-mt-2 -mx-4 lg:p-8 max-lg:-my-6 hover:mt-2 [&>*]:mb-4 !mt-2 mt-2!">',
        # Not a step: keywords, fractions, variables.
        '<div class="m-auto mx-auto top-full left-1/2 -translate-x-1/2 space-x-reverse inset-auto">',
        '<div class="p-(--card-pad) top-(--bar-height)">',
        # Arbitrary values on the grid, or not lengths.
        '<div class="p-[16px] mt-[1rem] gap-[1.5rem] top-[0px] -mt-[8px]">',
        '<div class="fixed right-4 bottom-[calc(4.5rem+env(safe-area-inset-bottom))] lg:bottom-6">',
        '<div class="absolute top-[50%] left-[10vw] inset-x-[var(--edge)] bottom-[env(safe-area-inset-bottom)]">',
        # Not spacing at all.
        '<div class="w-3 h-5 size-7 ring-1 border-3 rounded-t-3 translate-x-1 col-end-3 row-start-5">',
        '<div class="items-end justify-end self-end text-left text-right float-left top-bar left-panel">',
        '<div class="leading-5 tracking-tight line-clamp-3 z-10 opacity-75 order-3 basis-1/3">',
        # Steps 1 and 3 inside a control: the element or an ancestor.
        '<button class="ui-btn ui-btn-sm gap-1 px-3">Go ahead</button>',
        '<a class="ui-btn-secondary px-3">Open</a>',
        '<span class="ui-pill ui-pill-success gap-1 px-3">Approved</span>',
        '<button class="ui-chip gap-1 px-3">Filter</button>',
        '<a class="ui-tab px-3 py-1">Queue</a>',
        '<input class="ui-input px-3 py-1">',
        '<div class="ui-select-panel p-1"><button class="ui-select-option px-3">One</button></div>',
        '<button class="ui-btn"><span class="ml-1">Words</span><span class="-mr-1 mt-3">x</span></button>',
        '<div data-control class="px-3 py-1"><span class="ml-1">x</span></div>',
        '<div data-control="segmented" class="p-1"><button class="px-3">Week</button></div>',
        # Steps 1 and 3 as the gap of an icon-and-label pair.
        '<span class="inline-flex items-center gap-1"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M1 1"/></svg>Approved</span>',
        '<a class="flex gap-3"><svg class="w-4 h-4" aria-hidden=\'true\'></svg><span>Calendar</span></a>',
        '<p class="flex gap-x-1">\n  <svg aria-hidden="true"/>\n  {{ item.label }}\n</p>',
        '<li class="flex space-x-3"><svg aria-hidden="true"></svg><strong>3</strong> waiting</li>',
        '<span class="flex gap-1">{% if x %}<svg aria-hidden="true"></svg>{% endif %}<span>Label</span></span>',
        # Template tags, comments and arguments that are not classes.
        '{% include "components/button.html" with label="mt-3" %}',
        '{# <div class="mt-5"> #}<div class="mt-4">',
        '{% comment %}<div class="p-3">{% endcomment %}<div class="p-4">',
        '<div class="mt-4"><!-- <p class="mt-5"> --></div>',
        '{% comment %}{% include "components/button.html" with extra_class="mt-3" %}{% endcomment %}',
        # A binding's words outside its strings are names and operators, not classes.
        "<div :class=\"{'mt-4':open,'pb-2':!open, hidden: !shown}\">",
        "<div :class=\"open?'pb-4':'pb-2'\">",
        '<button class="ui-btn" :class="{\'gap-1\':compact}">Go ahead</button>',
    ],
)
def test_the_guard_passes_the_grid_and_the_allowlisted_places(source: str) -> None:
    assert not off_grid(source), off_grid(source)


@pytest.mark.parametrize(
    "source",
    [
        '<span class="flex gap-1"><svg></svg>Not hidden from assistive technology</span>',
        '<span class="flex gap-1"><svg aria-hidden="false"></svg>Announced</span>',
        '<span class="flex gap-1"><svg aria-hidden="true"></svg><svg aria-hidden="true"></svg>Two icons</span>',
        '<span class="flex gap-1"><svg aria-hidden="true"></svg></span>',
        '<span class="flex gap-1"><svg aria-hidden="true"></svg>{% if x %}{% endif %}</span>',
        '<div class="flex gap-3"><svg aria-hidden="true"></svg><div><p>A block, not a label</p></div></div>',
        '<div class="flex gap-3"><svg aria-hidden="true"></svg><img alt="A picture"></div>',
        '<span class="flex mt-1"><svg aria-hidden="true"></svg>A margin, not the gap</span>',
        '<span class="flex gap-1"><svg aria-hidden="true"></svg>Label</span><span class="flex gap-1">No icon</span>',
    ],
)
def test_an_icon_and_label_pair_is_exactly_one_hidden_icon_and_words(source: str) -> None:
    assert off_grid(source), source


def test_a_finding_names_the_line_the_utility_is_on() -> None:
    source = '<div\n  class="flex\n         mt-4\n         pb-5">\n  <p class="mt-px">x</p>\n</div>'
    assert [(finding.line, finding.word) for finding in off_grid(source, "x.html")] == [(4, "pb-5"), (5, "mt-px")]
    assert str(off_grid(source, "x.html")[0]) == "x.html:4: pb-5 (step 5 is 20 px, off the 8 px grid)"


def test_a_finding_in_a_compact_binding_names_the_class_and_its_line() -> None:
    source = "<div\n  :class=\"{'mt-4':a,\n           'mb-5':b}\">x</div>"
    assert [(finding.line, finding.word) for finding in off_grid(source)] == [(3, "mb-5")]


def test_the_allowlist_names_each_place_with_its_reason() -> None:
    assert sorted(SMALL_STEPS) == [1, 3]
    assert set(SMALL_STEP_ALLOWLIST) == {
        "control:ui-btn",
        "control:ui-input",
        "control:ui-select",
        "control:ui-chip",
        "control:ui-tab",
        "control:ui-pill",
        "control:[data-control]",
        "icon-and-label",
    }
    assert all(reason.strip() for reason in SMALL_STEP_ALLOWLIST.values())


@pytest.mark.parametrize(
    ("entry", "source"),
    [
        ("control:ui-btn", '<button class="ui-btn ui-btn-sm gap-1 px-3">Go ahead</button>'),
        ("control:ui-input", '<input class="ui-input px-3 py-1">'),
        (
            "control:ui-select",
            '<div class="ui-select-panel p-1"><button class="ui-select-option px-3">One</button></div>',
        ),
        ("control:ui-chip", '<button class="ui-chip gap-1 px-3">Filter</button>'),
        ("control:ui-tab", '<a class="ui-tab px-3 py-1">Queue</a>'),
        ("control:ui-pill", '<span class="ui-pill ui-pill-success gap-1 px-3">Approved</span>'),
        (
            "control:[data-control]",
            '<div data-control="segmented" class="p-1"><button class="px-3">Week</button></div>',
        ),
        ("icon-and-label", '<span class="flex gap-1"><svg aria-hidden="true"></svg>Approved</span>'),
    ],
)
def test_the_allowlist_is_the_rule(entry: str, source: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each place passes steps 1 and 3 because the allowlist names it: take its entry out and it is flagged."""
    assert not off_grid(source), off_grid(source)
    monkeypatch.delitem(SMALL_STEP_ALLOWLIST, entry)
    assert off_grid(source), f"{source} still passes without {entry!r}"


def test_a_place_added_to_the_allowlist_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    sources = ['<div class="ui-stepper px-3 py-1">-</div>', '<div data-segmented class="p-1">x</div>']
    assert all(off_grid(source) for source in sources)
    monkeypatch.setitem(SMALL_STEP_ALLOWLIST, "control:ui-stepper", "a stepper's own padding")
    monkeypatch.setitem(SMALL_STEP_ALLOWLIST, "control:[data-segmented]", "a segmented control marks itself")
    assert not [finding for source in sources for finding in off_grid(source)]


# ── Cards and sections (set in CSS) ────────────────────────────────────────────────────────────


def _css() -> str:
    return recolor._mask_css_comments(STYLES.read_text(encoding="utf-8"))


def _rules(css: str, selector: str, around: str = "@media") -> list[tuple[str, str]]:
    """``(the at-rules around it that start with *around*, or "", its declarations)`` for each rule whose
    selector is *selector*."""
    found: list[tuple[str, str]] = []
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
                if prelude == selector and "{" not in body:
                    found.append((" ".join(p for p, _ in stack if p.startswith(around)), body))
            start = index + 1
        elif char == ";":
            start = index + 1
    return found


def _padding(declarations: str) -> str | None:
    found = re.findall(r"(?<![\w-])padding\s*:\s*([^;]+);", declarations)
    return found[-1].strip() if found else None


def test_a_card_is_20px_below_1024px_and_24px_from_1024px() -> None:
    paddings = {media: _padding(body) for media, body in _rules(_css(), ".ui-card") if _padding(body)}
    assert paddings == {"": "20px", "@media (min-width: 1024px)": "24px"}


@pytest.mark.parametrize("selector", [".ui-card", ".ui-card-nested", ".ui-sections"])
def test_a_utility_still_overrides_a_card(selector: str) -> None:
    # The rules sit in the components layer, so p-0, p-6 or sm:p-6 on a card (utilities) still win.
    layers = [layer for layer, _ in _rules(_css(), selector, around="@layer")]
    assert layers and all(layer == "@layer components" for layer in layers), layers


def test_a_nested_card_is_16px() -> None:
    paddings = {media: _padding(body) for media, body in _rules(_css(), ".ui-card-nested") if _padding(body)}
    assert paddings == {"": "16px"}


def test_a_screens_sections_are_32px_apart() -> None:
    rules = _rules(_css(), ".ui-sections")
    assert len(rules) == 1 and rules[0][0] == "", rules
    body = rules[0][1]
    assert re.search(r"(?<![\w-])display\s*:\s*flex\s*;", body)
    assert re.search(r"(?<![\w-])flex-direction\s*:\s*column\s*;", body)
    assert re.search(r"(?<![\w-])gap\s*:\s*32px\s*;", body)
