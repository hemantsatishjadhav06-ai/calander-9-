"""Move templates, JS and Python class strings to the "Quiet graphite + Pine" palette.

This is the codemod behind the October 2026 redesign (the design round's migration map,
sections 1-7; the system itself is docs/DESIGN_SYSTEM.md). It rewrites, in place:

* Tailwind colour utilities from the default palettes (stone, gray, neutral, slate, zinc,
  orange, amber, yellow, red, rose, green, emerald, teal, lime, indigo, blue, sky, cyan,
  violet, purple, pink, fuchsia) to the new scales: ``ink`` (neutrals), ``brand`` (Pine,
  was orange), ``success``, ``warning``, ``danger`` and ``info``. Variant chains
  (``hover:``, ``focus-visible:``, ``md:hover:``, ``peer-checked:`` ...) and opacity
  modifiers are kept, except where a modifier only lightened a tint (``bg-orange-50/40`` is
  ``bg-brand-50``). Steps are role-correct, not 1:1: text never lands on a step below 4.5:1
  (``text-stone-400`` is ``text-ink-500``), a form control's edge is the 3:1 boundary
  ``border-ink-400``, focus is ``brand-600``, a busy spinner is ``info``.
* Hard-coded colours in ``<style>`` blocks, ``style=""`` attributes, SVG ``fill``/``stroke``/
  ``stop-color`` attributes and data-URI SVGs: old palette hex and ``rgba()`` values become
  the matching ``var(--token)`` in pages that load the compiled stylesheet, and the new
  literal hex everywhere else (emails, the marketing site, legal and error pages, which do not
  load the tokens). ``var(--x, #hex)`` loses its now-pointless fallback when ``--x`` is a token.

* The dark pass (Phase 3, F1; docs/specs/phase-3.md T3). The scale utilities follow the theme
  by themselves (``@theme inline``); what does not follow moves to a token whose light value is
  the literal it replaces, so light cannot move: ``bg-white`` is ``bg-surface``; ``text-white``
  on a fill that flips (its own or the nearest ancestor's) is ``text-on-fill``; a solid
  ``bg-ink-800|900|950`` whose children use white or 200/300 steps, or that ``INVERSE_ROLES``
  names (logo marks, a tooltip, a selected chip), stays dark in both themes as
  ``bg-inverse``/``text-on-inverse`` (and keeps its light look through ``data-theme-scope``
  when a child uses a step that flips); scrims are ``bg-scrim/NN``; white edges are ``-surface``,
  ``-on-fill`` or ``-on-inverse`` by what they sit on; ink-300 edges (a text grey in dark) are
  the edge token. The light content scope (``data-theme-scope="light"``: platform previews) and
  pages that do not load the stylesheet are left alone.

What it leaves alone: platform and brand colours (only colours in the old palettes are
mapped, so LinkedIn ``#0A66C2`` or a client's navy never move), user-chosen label colours
(colour pickers and their presets), component classes such as ``btn-neutral``, tests,
migrations and vendored JS, and any line marked ``recolor: keep`` (white over a photo).

It is idempotent: the output contains no old palette names and no mapped hex, so a second
run changes nothing.

Usage::

    python tools/recolor.py            # rewrite every target file
    python tools/recolor.py --check    # change nothing; list files that would change, any old
                                       # palette class left anywhere, any marketing screenshot
                                       # that still shows the orange interface, what the dark
                                       # rules find, and any colour styles.css writes outside
                                       # Layer 1 (exit 1 if any)
    python tools/recolor.py path ...   # only these files
    python tools/recolor.py --diff     # print a unified diff instead of writing
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: The repository this file belongs to (ROOT may be pointed elsewhere by the tests).
REPO = ROOT
if str(REPO) not in sys.path:  # `python tools/recolor.py` puts tools/ on the path, not the repository
    sys.path.insert(0, str(REPO))

# ─────────────────────────────── Tailwind classes ───────────────────────────────

FAMILIES = (
    "stone|gray|neutral|slate|zinc|orange|amber|yellow|red|rose|green|emerald|teal|lime|indigo|blue|sky|cyan|"
    "violet|purple|pink|fuchsia"
)
UTILITIES = (
    r"bg|text|border(?:-[xytrbl])?|ring-offset|ring|outline|divide|accent|caret|fill|stroke|from|via|to|"
    r"decoration|placeholder|shadow|inset-ring"
)
# Group 1 variant chain, 2 negative sign, 3 utility, 4 family, 5 step, 6 opacity modifier.
CLASS_RE = re.compile(
    r"(?<![\w-])((?:[a-z0-9-]+:|\[[^\]\s]+\]:)*)(-?)("
    + UTILITIES
    + r")-("
    + FAMILIES
    + r")-(\d{2,3})((?:/\d{1,3})?)(?![\w-])"
)
# What CI greps for (migration map section 13): any old palette class anywhere.
LEFTOVER_RE = re.compile(
    r"(^|[^a-z-])(bg|text|border|ring|outline|divide|accent|fill|stroke|from|via|to|decoration|placeholder)-("
    + FAMILIES
    + r")-[0-9]{2,3}"
)

NEUTRAL = {"stone", "gray", "neutral", "slate", "zinc"}
SCALE_OF = {
    **dict.fromkeys(NEUTRAL, "ink"),
    "orange": "brand",
    **dict.fromkeys(("red", "rose"), "danger"),
    **dict.fromkeys(("amber", "yellow"), "warning"),
    **dict.fromkeys(("green", "emerald", "teal", "lime"), "success"),
    **dict.fromkeys(("indigo", "blue", "sky", "cyan"), "info"),
    **dict.fromkeys(("violet", "purple", "pink", "fuchsia"), "decorative"),
}
# Default step per scale (the migration map's role-correct tables).
STEPS = {
    "ink": {50: 50, 100: 100, 200: 200, 300: 300, 400: 500, 500: 500, 600: 600, 700: 700, 800: 800, 900: 900, 950: 950},
    "brand": {
        50: 50,
        100: 100,
        200: 200,
        300: 300,
        400: 400,
        500: 600,
        600: 600,
        700: 700,
        800: 800,
        900: 900,
        950: 950,
    },
    "warning": {
        50: 50,
        100: 100,
        200: 200,
        300: 300,
        400: 400,
        500: 500,
        600: 500,
        700: 600,
        800: 600,
        900: 700,
        950: 800,
    },
    "danger": {
        50: 50,
        100: 100,
        200: 200,
        300: 300,
        400: 500,
        500: 500,
        600: 500,
        700: 600,
        800: 600,
        900: 700,
        950: 800,
    },
    "success": {
        50: 50,
        100: 100,
        200: 200,
        300: 300,
        400: 500,
        500: 500,
        600: 600,
        700: 600,
        800: 700,
        900: 800,
        950: 900,
    },
    "info": {
        50: 50,
        100: 100,
        200: 200,
        300: 300,
        400: 500,
        500: 500,
        600: 600,
        700: 600,
        800: 700,
        900: 800,
        950: 900,
    },
    # violet / purple / pink / fuchsia were decorative tiles: they become neutral ink.
    "decorative": {
        50: 50,
        100: 100,
        200: 200,
        300: 300,
        400: 500,
        500: 500,
        600: 700,
        700: 700,
        800: 800,
        900: 900,
        950: 950,
    },
}
TEXTISH = {"text", "placeholder", "decoration", "caret"}
FORM_TAGS = {"input", "select", "textarea"}
SEPARATOR_RE = re.compile(r"^\s*(?:·|•|\||/|—|–|-|&middot;|&bull;|&mdash;|&ndash;|&#183;)\s*<")


def _has(variants: str, name: str) -> bool:
    return any(v == name for v in variants.split(":") if v)


def _focusish(variants: str) -> bool:
    return any(v in ("focus", "focus-visible", "focus-within") for v in variants.split(":") if v)


def map_class(m: re.Match, ctx: dict | None = None) -> str:
    """Return the new class for one old palette utility match."""
    ctx = ctx or {}
    variants, neg, util, fam, step_s, mod = m.groups()
    step = int(step_s)
    scale = SCALE_OF[fam]
    base_util = util.split("-")[0] if util.startswith("border-") else util
    new_scale = "ink" if scale == "decorative" else scale
    new_step = STEPS[scale].get(step, step)
    keep_mod = mod

    # Malformed `text-stone-300/400` (a step typed as a modifier): plain tertiary text.
    if mod and len(mod) == 4 and int(mod[1:]) in (300, 400, 500):
        return f"{variants}{neg}{util}-ink-500"

    if scale == "ink":
        if util == "bg" and step == 50 and _has(variants, "hover"):
            new_step = 25  # row/menu hover on white: the subtler ink-25
        if step == 400:
            new_step = 500 if util in TEXTISH and not ctx.get("svg") else 400
        if step == 300 and util in TEXTISH:
            new_step = 400 if (ctx.get("svg") or ctx.get("separator")) and util == "text" else 500
        if base_util == "border" and step in (200, 300, 400) and ctx.get("form_control"):
            new_step = 500 if _has(variants, "hover") else 400  # control boundary >= 3:1
        if util == "bg" and step == 900 and mod and 20 <= int(mod[1:]) <= 60:
            return f"{variants}{neg}bg-ink-950/35"  # overlay scrim
        if util == "ring" and mod and step >= 500 and int(mod[1:]) <= 20:
            new_step, keep_mod = 200, ""  # old Tailwind UI pill hairline
    elif scale == "brand":
        if base_util == "border":
            if _focusish(variants) and step >= 300:
                new_scale, new_step = "brand", 600
            elif step in (300, 400):
                new_scale, new_step = "ink", step  # clickable-card hover edges are neutral
            elif util == "border-t" and step in (500, 600):
                new_scale, new_step = "info", 500  # spinners: busy is info, never the accent
        elif util == "ring":
            if _focusish(variants) and step <= 200 and not _has(variants, "peer-focus-visible"):
                new_step, keep_mod = 600, "/20"  # decorative halo; the border carries 3:1
            elif step >= 300 or _has(variants, "peer-focus-visible"):
                new_step = 600
        elif util == "outline":
            new_step = 600  # the focus colour
        elif util == "accent":
            new_step = 700
        elif util == "bg" and step in (500, 600):
            new_step = 700  # fills: toggles, unread dots, selected ticks
        elif util == "bg" and _has(variants, "active") and step >= 700:
            new_step = 900
        elif util == "text" and step in (400, 500):
            new_step = 600
        elif util == "text" and step == 600:
            new_step = 700
    else:  # status scales and the decorative ones
        if scale != "decorative":
            if util == "text":
                if step in (400, 500):
                    new_step = 500 if scale == "danger" else 600
                elif step in (600, 700, 800):
                    new_step = 600
                elif step in (900, 950):
                    new_step = 700
            elif util == "bg" and step in (400, 500, 600):
                new_step = 500
            elif base_util in ("ring", "border") and step in (100, 200):
                new_step = 200
            elif util == "ring" and mod and step >= 500 and int(mod[1:]) <= 20:
                new_step, keep_mod = 200, ""  # old Tailwind UI pill hairline -> the scale's 200 ring

    # Modifiers that only lightened a tint are dropped (the new 50/100 steps are already pale).
    if keep_mod and util in ("bg", "via", "from", "to") and step in (50, 100):
        keep_mod = ""
        if scale == "ink" and util == "bg" and step == 50:
            new_step = 25
    if keep_mod and base_util == "border" and step in (100, 200):
        keep_mod = ""
    return f"{variants}{neg}{util}-{new_scale}-{new_step}{keep_mod}"


def _unquoted_gt(segment: str) -> int:
    """Index of the first `>` outside quotes in `segment`, or -1."""
    quote = ""
    for i, ch in enumerate(segment):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == ">":
            return i
    return -1


def _element_context(text: str, pos: int) -> dict:
    """What element a class sits on (only what the rules above need): an SVG shape, a form
    control, or an element whose whole text is a separator such as "·"."""
    start = text.rfind("<", 0, pos)
    if start == -1 or _unquoted_gt(text[start:pos]) != -1:
        return {}  # not inside a start tag (JS string, text, a Python literal)
    tag_match = re.match(r"<([a-zA-Z][\w-]*)", text[start : start + 40])
    if not tag_match:
        return {}
    tag = tag_match.group(1).lower()
    ctx = {
        "svg": tag in ("svg", "path", "circle", "line", "polyline", "polygon", "rect", "g"),
        "form_control": tag in FORM_TAGS,
    }
    end = _unquoted_gt(text[pos : pos + 4000])
    if end != -1:
        ctx["separator"] = bool(SEPARATOR_RE.match(text[pos + end + 1 : pos + end + 40]))
    return ctx


def recolor_classes(text: str, *, python_form_file: bool = False) -> str:
    def repl(m: re.Match) -> str:
        if python_form_file:
            ctx = {"form_control": "checkbox" not in text[max(0, m.start() - 200) : m.start()].lower()}
        else:
            ctx = _element_context(text, m.start())
        return map_class(m, ctx)

    return CLASS_RE.sub(repl, text)


# A few non-palette classes the spec retires: the black scrims become the graphite overlay.
SCRIM_RE = re.compile(r"(?<![\w-])((?:[a-z0-9-]+:)*)bg-black/(30|40)(?![\w-])")


def recolor_scrims(text: str) -> str:
    return SCRIM_RE.sub(lambda m: f"{m.group(1)}bg-ink-950/35", text)


# ─────────────────────────────── Hard-coded colours ───────────────────────────────


# old hex -> (token for non-text use, token for `color:` use, new hex for non-text, new hex for text)
def _same(token: str, hex_: str) -> tuple[str, str, str, str]:
    return token, token, hex_, hex_


HEX_MAP: dict[str, tuple[str, str, str, str]] = {
    # stone (and the old AA-tuned stone-500)
    "FAFAF9": _same("var(--surface-1)", "#F6F7F8"),
    "F5F5F4": _same("var(--surface-2)", "#EDEFF2"),
    "E7E5E4": _same("var(--border)", "#E1E4E8"),
    "D6D3D1": ("var(--ink-300)", "var(--ink-400)", "#CED2D7", "#83888F"),
    "A8A29E": ("var(--ink-400)", "var(--text-tertiary)", "#83888F", "#656B73"),
    "78716C": ("var(--ink-500)", "var(--text-tertiary)", "#656B73", "#656B73"),
    "766F6A": ("var(--ink-500)", "var(--text-tertiary)", "#656B73", "#656B73"),
    "57534E": ("var(--ink-600)", "var(--text-secondary)", "#52575F", "#52575F"),
    "44403C": _same("var(--ink-700)", "#3E434A"),
    "292524": _same("var(--ink-800)", "#2E3238"),
    "1C1917": ("var(--ink-900)", "var(--text-primary)", "#1C1F24", "#1C1F24"),
    "171412": _same("var(--ink-950)", "#0E1114"),
    "0C0A09": _same("var(--ink-950)", "#0E1114"),
    # gray
    "F9FAFB": _same("var(--surface-sheet)", "#FBFCFD"),
    "F3F4F6": _same("var(--surface-2)", "#EDEFF2"),
    "E5E7EB": _same("var(--border)", "#E1E4E8"),
    "D1D5DB": _same("var(--ink-300)", "#CED2D7"),
    "9CA3AF": ("var(--ink-400)", "var(--text-tertiary)", "#83888F", "#656B73"),
    "6B7280": ("var(--ink-500)", "var(--text-tertiary)", "#656B73", "#656B73"),
    "4B5563": ("var(--ink-600)", "var(--text-secondary)", "#52575F", "#52575F"),
    "374151": _same("var(--ink-700)", "#3E434A"),
    "1F2937": _same("var(--ink-800)", "#2E3238"),
    "111827": ("var(--ink-900)", "var(--text-primary)", "#1C1F24", "#1C1F24"),
    # orange -> Pine
    "FFF7ED": _same("var(--primary-soft)", "#EFFAF5"),
    "FFEDD5": _same("var(--brand-100)", "#DDF3EA"),
    "FED7AA": _same("var(--brand-200)", "#BFE7D6"),
    "FDBA74": _same("var(--brand-300)", "#94D2BA"),
    "FB923C": _same("var(--brand-400)", "#62B194"),
    "F97316": _same("var(--primary)", "#115641"),
    "EA580C": _same("var(--brand-600)", "#1E7057"),
    "C2410C": _same("var(--primary)", "#115641"),
    "9A3412": _same("var(--brand-800)", "#0D4534"),
    "7C2D12": _same("var(--brand-900)", "#0B3629"),
    # red / rose -> danger
    "FEF2F2": _same("var(--error-50)", "#FFF3F1"),
    "FFF1F2": _same("var(--danger-50)", "#FFF3F1"),
    "FEE2E2": _same("var(--danger-100)", "#FFE4E0"),
    "FECACA": _same("var(--danger-200)", "#FFCDC6"),
    "FCA5A5": _same("var(--danger-300)", "#FEA69C"),
    "F87171": _same("var(--danger-500)", "#991618"),
    "EF4444": _same("var(--error-500)", "#991618"),
    "F43F5E": _same("var(--danger-500)", "#991618"),
    "DC2626": _same("var(--danger-500)", "#991618"),
    "E11D48": _same("var(--danger-500)", "#991618"),
    "B91C1C": _same("var(--error-700)", "#7C1213"),
    "991B1B": _same("var(--danger-600)", "#7C1213"),
    "7F1D1D": _same("var(--danger-700)", "#6A0E0E"),
    # amber / yellow -> warning
    "FFFBEB": _same("var(--warning-50)", "#FFF7EB"),
    "FEFCE8": _same("var(--warning-50)", "#FFF7EB"),
    "FEF3C7": _same("var(--warning-100)", "#FFEED4"),
    "FEF9C3": _same("var(--warning-100)", "#FFEED4"),
    "FDE68A": _same("var(--warning-200)", "#FFDDAE"),
    "FEF08A": _same("var(--warning-200)", "#FFDDAE"),
    "FCD34D": _same("var(--warning-300)", "#FFCA82"),
    "FBBF24": _same("var(--warning-400)", "#FCAA38"),
    "F59E0B": _same("var(--warning-500)", "#9B5A00"),
    "EAB308": _same("var(--warning-500)", "#9B5A00"),
    "D97706": _same("var(--warning-500)", "#9B5A00"),
    "CA8A04": _same("var(--warning-500)", "#9B5A00"),
    "B45309": _same("var(--warning-600)", "#7F4700"),
    "A16207": _same("var(--warning-600)", "#7F4700"),
    "92400E": _same("var(--warning-700)", "#683904"),
    "854D0E": _same("var(--warning-700)", "#683904"),
    "78350F": _same("var(--warning-700)", "#683904"),
    # green / emerald / teal (and the old olive tint and checkbox accent) -> success / brand
    "F0FDF4": _same("var(--success-50)", "#EDFCED"),
    "ECFDF5": _same("var(--success-50)", "#EDFCED"),
    "F0FDFA": _same("var(--success-50)", "#EDFCED"),
    "DCFCE7": _same("var(--success-100)", "#DAF8DA"),
    "D1FAE5": _same("var(--success-100)", "#DAF8DA"),
    "CCFBF1": _same("var(--success-100)", "#DAF8DA"),
    "D9F1D1": _same("var(--success-100)", "#DAF8DA"),
    "BBF7D0": _same("var(--success-200)", "#BCF0BC"),
    "A7F3D0": _same("var(--success-200)", "#BCF0BC"),
    "99F6E4": _same("var(--success-200)", "#BCF0BC"),
    "86EFAC": _same("var(--success-300)", "#95E097"),
    "4ADE80": _same("var(--success-500)", "#429E4A"),
    "34D399": _same("var(--success-500)", "#429E4A"),
    "22C55E": _same("var(--success-500)", "#429E4A"),
    "10B981": _same("var(--success-500)", "#429E4A"),
    "14B8A6": _same("var(--success-500)", "#429E4A"),
    "16A34A": _same("var(--success-600)", "#317F38"),
    "059669": _same("var(--success-600)", "#317F38"),
    "0D9488": _same("var(--success-600)", "#317F38"),
    "15803D": _same("var(--success-600)", "#317F38"),
    "047857": _same("var(--success-600)", "#317F38"),
    "0F766E": _same("var(--success-600)", "#317F38"),
    "166534": _same("var(--success-700)", "#28682D"),
    "065F46": _same("var(--success-700)", "#28682D"),
    "115E59": _same("var(--success-700)", "#28682D"),
    "14532D": _same("var(--success-800)", "#215525"),
    "94A43F": _same("var(--brand-700)", "#115641"),
    "7B8A33": _same("var(--brand-800)", "#0D4534"),
    # blue / indigo / sky -> info
    "EFF6FF": _same("var(--info-50)", "#EFF8FD"),
    "EEF2FF": _same("var(--info-50)", "#EFF8FD"),
    "F0F9FF": _same("var(--info-50)", "#EFF8FD"),
    "DBEAFE": _same("var(--info-100)", "#DDF1FC"),
    "E0E7FF": _same("var(--info-100)", "#DDF1FC"),
    "E0F2FE": _same("var(--info-100)", "#DDF1FC"),
    "BFDBFE": _same("var(--info-200)", "#BEE3F8"),
    "C7D2FE": _same("var(--info-200)", "#BEE3F8"),
    "93C5FD": _same("var(--info-300)", "#95CDEB"),
    "60A5FA": _same("var(--info-500)", "#035A7B"),
    "3B82F6": _same("var(--info-500)", "#035A7B"),
    "6366F1": _same("var(--info-500)", "#035A7B"),
    "0EA5E9": _same("var(--info-500)", "#035A7B"),
    "2563EB": _same("var(--info-600)", "#044E6B"),
    "4F46E5": _same("var(--info-600)", "#044E6B"),
    "0284C7": _same("var(--info-600)", "#044E6B"),
    "1D4ED8": _same("var(--info-600)", "#044E6B"),
    "4338CA": _same("var(--info-600)", "#044E6B"),
    "0369A1": _same("var(--info-600)", "#044E6B"),
    "1E40AF": _same("var(--info-700)", "#064058"),
    "3730A3": _same("var(--info-700)", "#064058"),
    "1E3A8A": _same("var(--info-800)", "#073548"),
    # violet (on hold) -> neutral
    "F5F3FF": _same("var(--ink-100)", "#EDEFF2"),
    "EDE9FE": _same("var(--ink-100)", "#EDEFF2"),
    "DDD6FE": _same("var(--ink-200)", "#E1E4E8"),
    "8B5CF6": _same("var(--ink-500)", "#656B73"),
    "7C3AED": _same("var(--ink-500)", "#656B73"),
    "6D28D9": _same("var(--ink-700)", "#3E434A"),
}


# Text colours that sat on a dark surface (a toast, a dark preview) keep a light ink: the
# light-surface steps above would drop to about 3:1 on ink-900.
DARK_TEXT = {
    "E7E5E4": ("var(--ink-200)", "#E1E4E8"),
    "D6D3D1": ("var(--ink-200)", "#E1E4E8"),
    "A8A29E": ("var(--ink-300)", "#CED2D7"),
    "9CA3AF": ("var(--ink-300)", "#CED2D7"),
    "78716C": ("var(--ink-400)", "#83888F"),
    "766F6A": ("var(--ink-400)", "#83888F"),
}
DARK_BG_RE = re.compile(
    r"background(?:-color)?\s*:\s*(?:#(?:1C1917|292524|0C0A09|171412|44403C|000|000000|111827|1F2937)\b|"
    r"var\(--(?:neutral-900|neutral-800|neutral-950|text-primary)\)|rgba?\(\s*0\s*,\s*0\s*,\s*0\s*,\s*0?\.[5-9])",
    re.I,
)


def _rgb(hex_: str) -> tuple[int, int, int]:
    h = hex_.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# rgba() triples of the old palette -> the new triple (non-text mapping). Black shadows and scrims
# take the graphite tint so depth stays neutral-cool.
RGB_MAP: dict[tuple[int, int, int], tuple[int, int, int]] = {_rgb(old): _rgb(new[2]) for old, new in HEX_MAP.items()}
RGB_MAP[(0, 0, 0)] = (14, 17, 20)
RGB_MAP[(23, 20, 18)] = (14, 17, 20)  # the old stone-tinted shadow
RGB_MAP[(28, 25, 23)] = (28, 31, 36)
RGB_MAP[(120, 113, 108)] = (101, 107, 115)
RGB_MAP[(147, 162, 64)] = (17, 86, 65)  # the old olive accent glow

HEX_RE = re.compile(r"(?<![\w&])#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})(?![0-9A-Fa-f\w])")
URI_HEX_RE = re.compile(r"%23([0-9A-Fa-f]{6})(?![0-9A-Fa-f])")
RGBA_RE = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(,\s*[\d.]+\s*)?\)")
VAR_FALLBACK_RE = re.compile(r"var\(\s*(--[\w-]+)\s*,\s*([^()]*?(?:\([^()]*\))?[^()]*?)\)")
STYLE_BLOCK_RE = re.compile(r"(<style\b[^>]*>)(.*?)(</style>)", re.S | re.I)
STYLE_ATTR_RE = re.compile(r"""(\sstyle=)(["'])(.*?)\2""", re.S)
SVG_ATTR_RE = re.compile(r"""(\s(?:fill|stroke|stop-color|flood-color|color)=)(["'])(#[0-9A-Fa-f]{3,6})\2""")


def _expand(h: str) -> str:
    h = h.upper()
    return "".join(c * 2 for c in h) if len(h) == 3 else h


def _is_text_property(css: str, pos: int) -> bool:
    """True when the colour at `pos` is the value of a `color:` declaration (not background, border...)."""
    decl = css[max(0, css.rfind(";", 0, pos), css.rfind("{", 0, pos), css.rfind("\n", 0, pos)) : pos]
    m = re.search(r"([\w-]+)\s*:[^:]*$", decl)
    return bool(m and m.group(1).lower() in ("color", "-webkit-text-fill-color", "caret-color"))


def _on_dark(css: str, pos: int) -> bool:
    """True when the declaration at `pos` sits in a rule (or style attribute) with a dark background."""
    start = css.rfind("{", 0, pos) + 1
    end = css.find("}", pos)
    return bool(DARK_BG_RE.search(css[start : end if end != -1 else len(css)]))


class CssRecolor:
    """Recolour one chunk of CSS (a style block or a style attribute)."""

    def __init__(self, *, tokens: bool, defined: set[str]):
        self.tokens = tokens
        self.defined = defined

    def __call__(self, css: str) -> str:
        css = self._fallbacks(css)
        css = self._rgba(css)
        css = URI_HEX_RE.sub(self._uri_hex, css)
        return HEX_RE.sub(lambda m: self._hex(m, css), css)

    def _fallbacks(self, css: str) -> str:
        def repl(m: re.Match) -> str:
            name, fallback = m.group(1), m.group(2)
            if self.tokens and name in self.defined:
                return f"var({name})"
            bare = HEX_RE.fullmatch(fallback.strip())
            if self.tokens and bare and _expand(bare.group(1)) in HEX_MAP:
                return HEX_MAP[_expand(bare.group(1))][0]
            literal = HEX_RE.sub(lambda h: self._literal(h.group(1), text=False), fallback)
            literal = self._rgba(literal)
            return f"var({name}, {literal.strip()})"

        return VAR_FALLBACK_RE.sub(repl, css)

    def _rgba(self, css: str) -> str:
        def repl(m: re.Match) -> str:
            triple = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            new = RGB_MAP.get(triple)
            if new is None:
                return m.group(0)
            alpha = m.group(4)
            if alpha is None:
                return f"#{new[0]:02X}{new[1]:02X}{new[2]:02X}"
            return f"rgba({new[0]}, {new[1]}, {new[2]}{alpha.rstrip()})"

        # --primary-rgb is retired (Phase 3, F1): the old orange fallback becomes the literal Pine.
        css = re.sub(r"rgba\(\s*var\(--primary-rgb\s*,\s*249\s*,\s*115\s*,\s*22\s*\)", "rgba(17, 86, 65", css)
        return RGBA_RE.sub(repl, css)

    def _literal(self, raw: str, *, text: bool) -> str:
        entry = HEX_MAP.get(_expand(raw))
        if entry is None:
            return "#" + raw
        return entry[3] if text else entry[2]

    def _hex(self, m: re.Match, css: str) -> str:
        key = _expand(m.group(1))
        entry = HEX_MAP.get(key)
        if entry is None:
            return m.group(0)
        text = _is_text_property(css, m.start())
        if text and key in DARK_TEXT and _on_dark(css, m.start()):
            return DARK_TEXT[key][0] if self.tokens else DARK_TEXT[key][1]
        if self.tokens:
            return entry[1] if text else entry[0]
        return entry[3] if text else entry[2]

    @staticmethod
    def _uri_hex(m: re.Match) -> str:
        entry = HEX_MAP.get(m.group(1).upper())
        return "%23" + entry[2].lstrip("#") if entry else m.group(0)


# Lines carrying user-chosen colours (pickers, their presets, label defaults) are never touched.
KEEP_LINE_RE = re.compile(r"presets|type=\"color\"|recolor:\s*keep", re.I)


def recolor_html_colours(text: str, *, tokens: bool, defined: set[str]) -> str:
    css = CssRecolor(tokens=tokens, defined=defined)
    literal_css = CssRecolor(tokens=False, defined=defined)

    def guarded(fn, chunk: str) -> str:
        if KEEP_LINE_RE.search(chunk):
            return "\n".join(line if KEEP_LINE_RE.search(line) else fn(line) for line in chunk.split("\n"))
        return fn(chunk)

    text = STYLE_BLOCK_RE.sub(lambda m: m.group(1) + guarded(css, m.group(2)) + m.group(3), text)

    def style_attr(m: re.Match) -> str:
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        if KEEP_LINE_RE.search(text[line_start : line_end if line_end != -1 else None]):
            return m.group(0)
        # Alpine :style="..." bindings are JS expressions; colours in them are plain strings too.
        return m.group(1) + m.group(2) + css(m.group(3)) + m.group(2)

    text = STYLE_ATTR_RE.sub(style_attr, text)
    text = re.sub(
        r"""(\s:style=)(["'])(.*?)\2""",
        lambda m: m.group(1) + m.group(2) + css(m.group(3)) + m.group(2),
        text,
        flags=re.S,
    )
    # var(--token, #old) anywhere else (SVG attributes, Alpine bindings): drop or remap the fallback.
    text = css._fallbacks(text) if tokens else literal_css._fallbacks(text)
    # SVG presentation attributes cannot read CSS variables reliably: literal new hex.
    text = SVG_ATTR_RE.sub(lambda m: m.group(1) + m.group(2) + literal_css(m.group(3)) + m.group(2), text)
    return text


# ─────────────────────────────── Dark mode (Phase 3, F1) ───────────────────────────────
#
# The dark theme redefines Layer 1, so every scale utility flips by itself. These rules move what does
# not follow to tokens whose light value is the literal they replace (docs/specs/phase-3.md T3):
# bg-white -> bg-surface, text-white on a fill that flips -> text-on-fill, the elements that stay dark
# in both themes -> bg-inverse/text-on-inverse, scrims -> bg-scrim/NN, white edges by what they sit on,
# ink-300 edges (a text grey in dark) -> the edge token. They read the element a class sits on and its
# ancestors, so a child's white is judged by the fill it is drawn over.

INVERSE, DARK, FLIP, LIGHT = "inverse", "dark", "flips", "light"

#: Elements that stay dark in both themes by role though nothing inside them is white: per template,
#: markers of the element's start tag. The workspace initial (the logo mark), the composer's tooltip and
#: its selected override chip (a selected filter chip). The selection bars and toasts need no entry:
#: their children use white or 200/300 steps, which makes a dark fill inverse by itself.
INVERSE_ROLES: dict[str, tuple[str, ...]] = {
    "base.html": ("rounded-[7px] flex items-center justify-center",),
    "client_portal/portal_base.html": ("flex size-7 flex-shrink-0 items-center justify-center rounded-[7px]",),
    "client_portal/magic_link_confirm.html": ("rounded-[10px]",),
    "workspaces/list.html": ("grid size-9 shrink-0 place-items-center rounded-[7px]",),
    "organizations/partials/workspace_card.html": ("grid size-9 shrink-0 place-items-center rounded-[7px]",),
    "onboarding/connection_page.html": ("inline-flex h-14 w-14 items-center justify-center rounded-2xl",),
    "composer/compose.html": (
        "pointer-events-none absolute left-3 -top-6",
        ":data-testid=\"'compose-override-toggle-' + accId\"",
    ),
}
#: Component classes that paint a fill (styles.css and the toast partial).
CLASS_FILLS: dict[str, str] = {
    "ui-toast": INVERSE,
    "bb-toast": INVERSE,
    "chart-tip": INVERSE,
    "sidebar-logo-mark": INVERSE,
    "ui-btn-primary": FLIP,
    "ui-btn-danger": FLIP,
    "ui-badge-turn": FLIP,
    "ui-badge-danger": FLIP,
    "btn-brand": FLIP,
}
#: Colours that flip and are not a scale step (they follow the theme through Layer 2).
SEMANTIC_FLIPS = {
    "on-fill",
    "surface",
    "canvas",
    "sunken",
    "sidebar",
    "fg",
    "fg-strong",
    "fg-muted",
    "fg-subtle",
    "line",
    "line-strong",
    "control",
}
#: A platform's own colours (glyphs and previews show the platform as it is).
PLATFORM_HEX = {"0A66C2", "1877F2", "FF0000", "E60023", "FE2C55", "3897F0", "0085FF", "6364FF"}

#: A colour utility: 1 variant chain, 2 important, 3 utility, 4 colour, 5 opacity modifier.
UTIL_RE = re.compile(
    r"(?<![\w-])((?:[a-z0-9-]+:|\[[^\]\s]+\]:)*)(!?)"
    r"(bg|text|ring|outline|border(?:-[xytrbl])?|divide(?:-[xy])?|stroke|fill|from|via|to|decoration|"
    r"placeholder|accent|caret)"
    r"-([a-z]+(?:-[a-z]+)*(?:-\d+)?)((?:/\d{1,3})?)(?![\w/-])"
)
SCALE_STEP_RE = re.compile(r"^(ink|brand|success|warning|danger|info)-(\d+)$")
SOLID_WHITE_RE = re.compile(r"(?<![\w-])((?:[a-z0-9-]+:|\[[^\]\s]+\]:)*!?)bg-white(?![\w/-])")
SCRIM_SRC_RE = re.compile(r"(?<![\w-])((?:[a-z0-9-]+:|\[[^\]\s]+\]:)*!?)bg-ink-(950|900)/(\d{1,3})(?![\w/-])")
INK300_EDGE_RE = re.compile(
    r"(?<![\w-])((?:[a-z0-9-]+:|\[[^\]\s]+\]:)*!?)"
    r"(border(?:-[xytrbl])?|ring|divide(?:-[xy])?|outline|stroke)-ink-300(?![\w/-])"
)
ARBITRARY_SHADOW_RE = re.compile(r"(?<![\w-])shadow-\[([^\]\s]+)\]")
SHADOW_INK_RE = re.compile(r"rgba?\(14[,_\s]+17[,_\s]+20[,_\s/]+([\d.]+)\)")
CSS_EDGE_PROPERTY_RE = re.compile(r"^(?:border(?:-[a-z-]+)?|outline(?:-color)?|box-shadow|column-rule(?:-color)?)$")
CLASS_ATTR_RE = re.compile(r"""(?<![\w.-])((?:x-bind)?:?class)\s*=\s*(["'])(.*?)\2""", re.S)
TAG_OPEN_RE = re.compile(r"<(/?)([a-zA-Z][\w:-]*)")
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
BREAKPOINT_RE = re.compile(r"^(?:max-|min-)?(?:sm|md|lg|xl|2xl)$")
SCOPE_ATTR = 'data-theme-scope="light"'


def _blank(match: re.Match) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def _mask(text: str) -> str:
    """*text* with comments and template tags blanked (same length), so markup can be read around them."""
    text = re.sub(r"{%\s*comment\b.*?%}.*?{%\s*endcomment\s*%}", _blank, text, flags=re.S)
    text = re.sub(r"<!--.*?-->", _blank, text, flags=re.S)
    return re.sub(r"{#.*?#}|{{.*?}}|{%.*?%}", _blank, text, flags=re.S)


@dataclass
class Token:
    """One colour utility in a class attribute, at its place in the template."""

    start: int
    end: int
    chain: str
    bang: str
    util: str
    colour: str
    mod: str

    @property
    def text(self) -> str:
        return f"{self.chain}{self.bang}{self.util}-{self.colour}{self.mod}"

    @property
    def state(self) -> str:
        """The variant chain without breakpoints: ``md:hover:`` is ``hover:``; ``lg:`` is the base."""
        return "".join(part + ":" for part in self.chain.split(":") if part and not BREAKPOINT_RE.match(part))


@dataclass
class Element:
    """A start tag, where it sits in the tree, and the classes it carries (``class``, ``:class``)."""

    name: str
    start: int
    tag_end: int
    tag: str
    ancestors: tuple[int, ...]
    in_light_scope: bool
    classes: tuple[str, ...]
    tokens: tuple[Token, ...]
    close: int = -1


def _tokens(masked: str, start: int, end: int) -> tuple[list[str], list[Token]]:
    classes: list[str] = []
    tokens: list[Token] = []
    for attr in CLASS_ATTR_RE.finditer(masked, start, end):
        value_start = attr.start(3)
        value = attr.group(3)
        classes += [word.strip("'\"{}(),:") for word in value.split()]
        for m in UTIL_RE.finditer(value):
            tokens.append(Token(value_start + m.start(), value_start + m.end(), *m.groups()))
    return [word for word in classes if word], tokens


def elements(text: str) -> list[Element]:
    """Every start tag of a template, in order, with its ancestors (a tolerant HTML reading).

    Comments and template tags are blanked first, so a quote inside ``{{ … }}`` cannot end an attribute
    and a tag in a comment is not markup; ``<script>`` and ``<style>`` hold no elements; a closing tag
    closes the nearest open element of its name.
    """
    masked = _mask(text)
    found: list[Element] = []
    stack: list[int] = []
    pos = 0
    while True:
        m = TAG_OPEN_RE.search(masked, pos)
        if not m:
            break
        name = m.group(2).lower()
        if m.group(1):  # a closing tag
            for depth in range(len(stack) - 1, -1, -1):
                if found[stack[depth]].name == name:
                    for index in stack[depth:]:
                        found[index].close = m.start()
                    del stack[depth:]
                    break
            pos = m.end()
            continue
        gt = _unquoted_gt(masked[m.start() :])
        if gt == -1:
            break
        end = m.start() + gt + 1
        tag = masked[m.start() : end]
        classes, tokens = _tokens(masked, m.start(), end)
        parent_scoped = bool(stack) and found[stack[-1]].in_light_scope
        element = Element(
            name=name,
            start=m.start(),
            tag_end=end,
            tag=text[m.start() : end],
            ancestors=tuple(reversed(stack)),
            in_light_scope=parent_scoped or SCOPE_ATTR in tag,
            classes=tuple(classes),
            tokens=tuple(tokens),
            close=end,
        )
        found.append(element)
        pos = end
        if name in ("script", "style") and not tag.endswith("/>"):
            close = masked.lower().find(f"</{name}", end)
            element.close = len(text) if close == -1 else close
            pos = element.close
        elif name not in VOID_TAGS and not tag.endswith("/>"):
            stack.append(len(found) - 1)
    for index in stack:
        found[index].close = len(text)
    return found


def _line_span(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text[start : end if end != -1 else len(text)]


def _kept(text: str, pos: int) -> bool:
    return bool(KEEP_LINE_RE.search(_line_span(text, pos)))


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _scope_ranges(found: list[Element]) -> list[tuple[int, int]]:
    return [(element.start, element.close) for element in found if SCOPE_ATTR in element.tag]


def _in(ranges: list[tuple[int, int]], pos: int) -> bool:
    return any(start <= pos < end for start, end in ranges)


def fill_kind(util: str, colour: str, mod: str) -> str | None:
    """What a ``bg-*`` utility paints: inverse, dark in both themes, a fill that flips, or a light fill."""
    if util != "bg":
        return None
    alpha = int(mod[1:]) if mod else 100
    if colour == "inverse":
        return INVERSE
    if colour in ("scrim", "black"):
        return DARK if alpha >= 20 else None
    if alpha < 50:
        return None  # a tint, not a fill
    if colour in ("white", "surface", "canvas", "sunken", "sidebar"):
        return LIGHT
    step = SCALE_STEP_RE.match(colour)
    if not step:
        return None
    scale, number = step.group(1), int(step.group(2))
    dark_from = {"ink": 700, "brand": 600}.get(scale, 500)
    return FLIP if number >= dark_from else LIGHT


def _own_fills(element: Element) -> dict[str, set[str]]:
    """The fills an element paints, per state (``""`` is the base)."""
    fills: dict[str, set[str]] = {}
    for token in element.tokens:
        kind = fill_kind(token.util, token.colour, token.mod)
        if kind:
            fills.setdefault(token.state, set()).add(kind)
    for word in element.classes:
        kind = CLASS_FILLS.get(word) or (DARK if word.startswith("pi-") else None)
        if kind:
            fills.setdefault("", set()).add(kind)
    return fills


def _ancestor_fill(fills: list[dict[str, set[str]]], element: Element) -> set[str]:
    """The base fill of the nearest ancestor that paints one (empty when none does)."""
    for index in element.ancestors:
        base = fills[index].get("")
        if base:
            return base
    return set()


def _named_inverse(name: str, element: Element) -> bool:
    return any(marker in element.tag for marker in INVERSE_ROLES.get(name, ()))


def _children_use_white_or_pale_steps(found: list[Element], element: Element) -> bool:
    for child in found:
        if child.start <= element.start:
            continue
        if child.start >= element.close:
            break
        for token in child.tokens:
            step = SCALE_STEP_RE.match(token.colour)
            if token.colour == "white" or (step and step.group(2) in ("200", "300")):
                return True
    return False


_CONSTANT_CACHE: dict[str, frozenset[str]] = {}


def constant_steps() -> frozenset[str]:
    """The scale steps whose dark value equals their light value (styles.css): they read the same on
    the inverse surface in both themes."""
    path = ROOT / "theme" / "static_src" / "src" / "styles.css"
    css = path.read_text(encoding="utf-8") if path.exists() else ""
    if css not in _CONSTANT_CACHE:
        from tools import contrast

        try:
            sheet = contrast.load(css)
        except LookupError:
            _CONSTANT_CACHE[css] = frozenset()
        else:
            _CONSTANT_CACHE[css] = frozenset(
                name[2:] for name, value in sheet.layer1.items() if sheet.dark.get(name, "").upper() == value.upper()
            )
    return _CONSTANT_CACHE[css]


def _flips_on_inverse(token: Token, constant: frozenset[str]) -> bool:
    """A colour that would change on the inverse surface, which does not (white, on-inverse and the
    constant steps read the same; ink-300 is the inverse surface's detail grey in both themes)."""
    if token.util == "text" and token.colour == "ink-300":
        return False
    if token.colour in SEMANTIC_FLIPS:
        return True
    return bool(SCALE_STEP_RE.match(token.colour)) and token.colour not in constant


def _scrim(m: re.Match) -> str:
    chain, step, alpha = m.group(1), m.group(2), int(m.group(3))
    if step == "950" or alpha >= 30:
        return f"{chain}bg-scrim/{alpha}"
    return m.group(0)


def _arbitrary_shadow(m: re.Match) -> str:
    value = m.group(1)
    if value == "inset_0_0_0_1px_rgba(14,17,20,.06)":
        return "shadow-[var(--shadow-creative)]"

    def mix(colour: re.Match) -> str:
        percent = f"{float(colour.group(1)) * 100:g}"
        return f"color-mix(in_srgb,var(--scrim)_{percent}%,transparent)"

    return f"shadow-[{SHADOW_INK_RE.sub(mix, value)}]"


def _rewrite_outside(text: str, pattern: re.Pattern, repl, ranges: list[tuple[int, int]]) -> str:
    def guarded(m: re.Match) -> str:
        if _in(ranges, m.start()) or _kept(text, m.start()):
            return m.group(0)
        return repl(m) if callable(repl) else m.expand(repl)

    return pattern.sub(guarded, text)


def _css_edges(css: str) -> str:
    """``var(--ink-300)`` drawn as an edge (border, outline, box-shadow) in template CSS -> the edge token."""

    def declaration(m: re.Match) -> str:
        if not CSS_EDGE_PROPERTY_RE.match(m.group(1).lower()):
            return m.group(0)
        return m.group(0).replace("var(--ink-300)", "var(--border-hover)")

    return re.sub(r"([-\w]+)(\s*:[^;{}]*)", declaration, css)


def dark_class_strings(text: str, ranges: list[tuple[int, int]] | None = None) -> str:
    """The rules that need no element: bg-white, scrims, ink-300 edges, literal arbitrary shadows."""
    ranges = ranges or []
    text = _rewrite_outside(text, SOLID_WHITE_RE, r"\1bg-surface", ranges)
    text = _rewrite_outside(text, SCRIM_SRC_RE, _scrim, ranges)
    text = _rewrite_outside(text, INK300_EDGE_RE, r"\1\2-line-strong", ranges)
    return _rewrite_outside(text, ARBITRARY_SHADOW_RE, _arbitrary_shadow, ranges)


def _token_text(token: Token, colour: str, mod: str | None = None) -> str:
    return f"{token.chain}{token.bang}{token.util}-{colour}{token.mod if mod is None else mod}"


def _edge_colour(own: set[str], around: set[str]) -> str | None:
    """What a white edge becomes: None keeps white (over a photo or a scrim)."""
    if DARK in own:
        return None
    if INVERSE in own:
        return "on-inverse"
    if FLIP in own:
        return "surface"  # a ring around a disc sits on the card
    if INVERSE in around:
        return "on-inverse"
    if DARK in around:
        return None
    return "on-fill" if FLIP in around else "surface"


def recolor_dark(text: str, *, name: str = "") -> str:
    """The dark pass over a template that loads the stylesheet (*name* as the loader knows it)."""
    ranges = _scope_ranges(elements(text))
    text = dark_class_strings(text, ranges)
    text = STYLE_BLOCK_RE.sub(lambda m: m.group(1) + _keep_lines(_css_edges, m.group(2)) + m.group(3), text)
    text = STYLE_ATTR_RE.sub(
        lambda m: (
            m.group(0) if _kept(text, m.start()) else m.group(1) + m.group(2) + _css_edges(m.group(3)) + m.group(2)
        ),
        text,
    )
    return _dark_in_context(text, name)


def _keep_lines(fn, chunk: str) -> str:
    return "\n".join(line if KEEP_LINE_RE.search(line) else fn(line) for line in chunk.split("\n"))


def _decide(text: str, name: str) -> tuple[list[Element], list[dict[str, set[str]]], set[int]]:
    """The elements, their fills per state, and which solid ink fills are inverse."""
    found = elements(text)
    fills = [_own_fills(element) for element in found]
    inverse: set[int] = set()
    for index, element in enumerate(found):
        if element.in_light_scope:
            continue
        solid = [
            token
            for token in element.tokens
            if token.util == "bg" and not token.mod and token.colour in ("ink-800", "ink-900", "ink-950")
        ]
        if solid and (_named_inverse(name, element) or _children_use_white_or_pale_steps(found, element)):
            inverse.add(index)
            fills[index] = {state: (kinds - {FLIP}) | {INVERSE} for state, kinds in fills[index].items()}
            fills[index].setdefault("", set()).add(INVERSE)
    return found, fills, inverse


def _dark_in_context(text: str, name: str) -> str:
    found, fills, inverse = _decide(text, name)
    constant = constant_steps()
    edits: list[tuple[int, int, str]] = []
    for index, element in enumerate(found):
        if element.in_light_scope:
            continue
        own = fills[index]
        around = _ancestor_fill(fills, element)
        base_white: Token | None = None
        for token in element.tokens:
            if _kept(text, token.start):
                continue
            state_fill = own.get(token.state) or own.get("", set())
            if (
                index in inverse
                and token.util == "bg"
                and token.colour in ("ink-800", "ink-900", "ink-950")
                and not token.mod
            ):
                edits.append((token.start, token.end, _token_text(token, "inverse")))
            elif token.util == "text" and token.colour == "white":
                if FLIP in state_fill:
                    edits.append((token.start, token.end, _token_text(token, "on-fill")))
                elif INVERSE in state_fill and index in inverse:
                    edits.append((token.start, token.end, _token_text(token, "on-inverse")))
                elif not state_fill and FLIP in around and not ({INVERSE, DARK} & around):
                    edits.append((token.start, token.end, _token_text(token, "on-fill")))
                elif not token.state:
                    base_white = token
            elif token.util == "bg" and token.colour == "white" and token.mod:
                if {INVERSE, DARK} & around:
                    continue
                own_fill = {kind for kinds in own.values() for kind in kinds}
                colour = "on-fill" if FLIP in own_fill or FLIP in around else "surface"
                edits.append((token.start, token.end, _token_text(token, colour)))
            elif token.colour == "white" and token.util.startswith(("ring", "outline", "border", "divide")):
                edge = _edge_colour(own.get("", set()) - {LIGHT}, around)
                if edge:
                    edits.append((token.start, token.end, _token_text(token, edge)))
        if base_white is not None:
            written = {token.state for token in element.tokens if token.util == "text"}
            extra = [
                f" {state}text-on-fill"
                for state, kinds in own.items()
                if state and FLIP in kinds and state not in written
            ]
            if extra:
                edits.append((base_white.end, base_white.end, "".join(extra)))
        # An inverse surface whose children use a step that flips keeps its light look in both themes.
        if (index in inverse or any(t.util == "bg" and t.colour == "inverse" for t in element.tokens)) and any(
            _flips_on_inverse(token, constant)
            for child in found
            if element.start < child.start < element.close and not child.in_light_scope
            for token in child.tokens
        ):
            at = element.start + 1 + len(element.name)
            edits.append((at, at, f" {SCOPE_ATTR}"))
    for start, end, replacement in sorted(edits, key=lambda edit: (edit[0], edit[1]), reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


# ─────────────────────────────── Files ───────────────────────────────

TOKEN_ROOTS = {
    "base.html",
    "client_portal/portal_base.html",
    "client_portal/magic_link_expired.html",
    "client_portal/magic_link_confirm.html",
    "account/accept_terms.html",
}
# Partials rendered outside the token stylesheet (emails and the public, legal and error pages).
LITERAL_DIRS = ("marketing/", "legal/", "errors/", "oauth2_provider/", "ninja/")
EXTENDS_RE = re.compile(r"""{%\s*extends\s+["']([^"']+)["']""")


def template_name(path: Path) -> str:
    parts = path.relative_to(ROOT).parts
    idx = parts.index("templates")
    return "/".join(parts[idx + 1 :])


def classify_templates(paths: Iterable[Path]) -> dict[Path, bool]:
    """Map each template to True when it is rendered with the token stylesheet loaded."""
    by_name = {template_name(p): p for p in paths}
    extends: dict[str, str | None] = {}
    for name, p in by_name.items():
        m = EXTENDS_RE.search(p.read_text(encoding="utf-8", errors="ignore"))
        extends[name] = m.group(1) if m else None

    def tokens(name: str, seen: frozenset = frozenset()) -> bool:
        if name in TOKEN_ROOTS:
            return True
        parent = extends.get(name)
        if parent and parent not in seen:
            return tokens(parent, seen | {name})
        text = by_name[name].read_text(encoding="utf-8", errors="ignore") if name in by_name else ""
        if re.search(r"<!doctype|<html", text, re.I):
            return "css/dist/styles.css" in text
        email = "/email/" in f"/{name}" or name.startswith("email") or "email" in Path(name).stem
        return not (email or name.startswith(LITERAL_DIRS) or name in ("pricing.html",))

    return {by_name[name]: tokens(name) for name in by_name}


def defined_tokens() -> set[str]:
    css = (ROOT / "theme/static_src/src/styles.css").read_text(encoding="utf-8")
    return set(re.findall(r"(--[\w-]+)\s*:", css))


def target_files() -> tuple[list[Path], list[Path], list[Path]]:
    html = sorted(set((ROOT / "templates").rglob("*.html")) | set(ROOT.glob("apps/**/templates/**/*.html")))
    js = sorted(p for p in (ROOT / "static/js").glob("*.js") if not p.name.endswith(".min.js"))
    py = sorted(
        p
        for p in (ROOT / "apps").rglob("*.py")
        if "migrations" not in p.parts and "tests" not in p.parts and not p.name.startswith("test_")
    )
    return html, js, py


def _loader_name(path: Path) -> str:
    """The template's name as the loader knows it (the part after ``templates/``), or the file name."""
    parts = path.parts
    if "templates" not in parts:
        return path.name
    index = len(parts) - 1 - parts[::-1].index("templates")
    return "/".join(parts[index + 1 :])


def transform(path: Path, text: str, *, tokens: bool, defined: set[str]) -> str:
    if path.suffix == ".py":
        form_file = path.name.startswith(("forms", "widgets"))
        return dark_class_strings(recolor_classes(text, python_form_file=form_file))
    out = recolor_scrims(recolor_classes(text))
    if path.suffix == ".html":
        out = recolor_html_colours(out, tokens=tokens, defined=defined)
        if tokens:  # pages that do not load the stylesheet (emails, legal, error) keep their literals
            out = recolor_dark(out, name=_loader_name(path))
    else:
        out = dark_class_strings(out)
    return out


def leftovers(paths: Iterable[Path]) -> list[str]:
    found = []
    for p in paths:
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if LEFTOVER_RE.search(line):
                found.append(f"{p.relative_to(ROOT)}:{n}: {line.strip()[:160]}")
    return found


# ─────────────────────────────── Dark checks ───────────────────────────────


def class_string_problems(text: str, ranges: list[tuple[int, int]] | None = None) -> list[tuple[int, str]]:
    """(line, problem) for the rules that need no element: bg-white and ink-300 edges."""
    ranges = ranges or []
    found = []
    for pattern, message in (
        (SOLID_WHITE_RE, "{token} outside the light scope"),
        (INK300_EDGE_RE, "{token} is a text grey in dark"),
    ):
        for m in pattern.finditer(text):
            if not (_in(ranges, m.start()) or _kept(text, m.start())):
                found.append((_line_of(text, m.start()), message.format(token=m.group(0))))
    return found


def dark_problems(text: str) -> list[tuple[int, str]]:
    """(line, problem) for a template that loads the stylesheet: what would read wrong in dark.

    bg-white outside the light scope; text-white, bg-white/NN or hover:bg-white/NN on an element whose
    own fill or nearest ancestor's fill flips; a colour that flips on an inverse surface (without the
    light scope that keeps its light look); an ink-300 edge. ``recolor: keep`` lines are accepted.
    """
    found_elements = elements(text)
    ranges = _scope_ranges(found_elements)
    problems = class_string_problems(text, ranges)
    fills = [_own_fills(element) for element in found_elements]
    constant = constant_steps()
    for element, own in zip(found_elements, fills, strict=True):
        if element.in_light_scope:
            continue
        around = _ancestor_fill(fills, element)
        on_inverse = INVERSE in around
        written = {token.state for token in element.tokens if token.util == "text"}
        for token in element.tokens:
            if _kept(text, token.start):
                continue
            line = _line_of(text, token.start)
            state_fill = own.get(token.state) or own.get("", set())
            if token.util == "text" and token.colour == "white":
                flips = FLIP in state_fill or (not state_fill and FLIP in around and not ({INVERSE, DARK} & around))
                if not flips and not token.state:
                    flips = any(state and FLIP in kinds and state not in written for state, kinds in own.items())
                if flips:
                    problems.append((line, f"{token.text} on a fill that flips"))
            elif token.util == "bg" and token.colour == "white" and token.mod:
                own_fill = {kind for kinds in own.values() for kind in kinds}
                if not ({INVERSE, DARK} & around) and (FLIP in own_fill or FLIP in around):
                    problems.append((line, f"{token.text} on a fill that flips"))
            if on_inverse and _flips_on_inverse(token, constant):
                problems.append((line, f"{token.text} flips on an inverse surface"))
    return sorted(problems)


RAW_COLOUR_RE = re.compile(
    r"(?<![&\w{])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])|(?<![a-zA-Z-])(?:rgba?|hsla?)\("
)
SVG_COLOUR_ATTR_RE = re.compile(r"""\s(?:fill|stroke|stop-color|flood-color|lighting-color|color)=(["'])(.*?)\1""")
STYLE_ANY_ATTR_RE = re.compile(r"""\s(?:x-bind)?:?style=(["'])(.*?)\1""", re.S)
ARBITRARY_RE = re.compile(r"(?<![\w-])[a-z][\w-]*-\[[^\]\s]+\]")


def raw_colour_problems(text: str) -> list[tuple[int, str]]:
    """(line, problem) for a colour value written in a template: in a ``<style>`` block's declarations,
    a ``style=`` or ``:style=`` attribute, an SVG colour attribute or an arbitrary class. A platform's
    own colour, the light scope's subtrees and ``presets|type="color"|recolor: keep`` lines are exempt."""
    ranges = _scope_ranges(elements(text))
    spans: list[tuple[int, int, bool]] = []  # start, end, platform colours allowed
    for block in STYLE_BLOCK_RE.finditer(text):
        body_start = block.start(2)
        for declaration in re.finditer(r"([-\w]+)\s*:([^;{}]*)", _mask_css_comments(block.group(2))):
            spans.append((body_start + declaration.start(2), body_start + declaration.end(2), False))
    for attr in STYLE_ANY_ATTR_RE.finditer(text):
        spans.append((attr.start(2), attr.end(2), False))
    for attr in SVG_COLOUR_ATTR_RE.finditer(text):
        spans.append((attr.start(2), attr.end(2), True))
    for arbitrary in ARBITRARY_RE.finditer(text):
        spans.append((arbitrary.start(), arbitrary.end(), True))
    found = set()
    for start, end, platform in spans:
        for m in RAW_COLOUR_RE.finditer(text, start, end):
            literal = m.group(0)
            if platform and literal.lstrip("#").upper() in PLATFORM_HEX:
                continue
            if _in(ranges, m.start()) or _kept(text, m.start()):
                continue
            found.add((_line_of(text, m.start()), f"raw colour {literal}"))
    return sorted(found)


def _mask_css_comments(css: str) -> str:
    """*css* with its comments blanked (same length); a ``/*`` inside a string is not a comment."""
    out = list(css)
    quote = ""
    index = 0
    while index < len(css):
        char = css[index]
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif css.startswith("/*", index):
            end = css.find("*/", index + 2)
            end = len(css) if end < 0 else end + 2
            for blank in range(index, end):
                if out[blank] != "\n":
                    out[blank] = " "
            index = end
            continue
        index += 1
    return "".join(out)


def dark_ready_templates() -> set[str]:
    """The templates of every page declared dark-ready, and every rebuilt screen's fragments."""
    from apps.common import screens

    dirs = (ROOT / "templates", *sorted(ROOT.glob("apps/*/templates")))
    names: set[str] = set()
    for page in screens.DARK_READY:
        names.update(screens.template_tree(screens.PAGE_TEMPLATES.get(page, ()), dirs))
    for screen in screens.SCREENS.values():
        names.update(screens.template_tree(screen.fragments, dirs))
    return names


STYLES_REL = "theme/static_src/src/styles.css"
STYLES_LITERAL_RE = re.compile(r"#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(", re.I)
LAYER1_NAME_RE = re.compile(r"^--(ink|brand|success|warning|danger|info)-\d+$")
PALETTE_LOCK = {("--color-white", "#fff"), ("--color-black", "#000")}


def styles_problems(css: str) -> list[str]:
    """Each colour styles.css writes in a declaration's value outside a Layer 1 block (a block that
    declares only raw scale steps: the light, dark, media and light-scope Layer 1), but for the
    palette lock's ``--color-white: #fff`` and ``--color-black: #000`` inside ``@theme``."""
    masked = _mask_css_comments(css)
    found: list[tuple[int, str]] = []
    stack: list[tuple[str, list[tuple[str, str, int]]]] = []
    start = 0
    quote = ""
    for index, char in enumerate(masked):
        if quote:
            quote = "" if char == quote else quote
            continue
        if char in "\"'":
            quote = char
        elif char == "{":
            stack.append((" ".join(masked[start:index].split()), []))
            start = index + 1
        elif char in ";}":
            text = masked[start:index]
            name, colon, value = text.partition(":")
            if stack and colon and name.strip() and not name.strip().startswith("@"):
                stack[-1][1].append((name.strip(), value, start + len(name) + 1))
            if char == "}" and stack:
                prelude, declarations = stack.pop()
                layer1 = bool(declarations) and all(LAYER1_NAME_RE.match(n) for n, _, _ in declarations)
                for decl_name, decl_value, offset in declarations:
                    if layer1 or (prelude == "@theme" and (decl_name, decl_value.strip()) in PALETTE_LOCK):
                        continue
                    for m in STYLES_LITERAL_RE.finditer(decl_value):
                        line = _line_of(masked, offset + m.start())
                        found.append((line, f"{m.group(0)} in {decl_name} (outside Layer 1)"))
            start = index + 1
    return [f"{STYLES_REL}:{line}: {problem}" for line, problem in sorted(found)]


def dark_findings(paths: Iterable[Path], kinds: dict[Path, bool]) -> list[str]:
    """What the dark rules find in *paths*, one line each."""
    ready = dark_ready_templates()
    lines: list[str] = []
    for path in paths:
        if path.suffix not in (".html", ".js", ".py"):
            continue
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        if path.suffix == ".html":
            if not kinds.get(path, True):
                continue  # emails and standalone pages keep their literal colours
            found = dark_problems(text)
            name = _loader_name(path)
            if name in ready and Path(name).name != "_platform_icon.html":
                found += raw_colour_problems(text)
        else:
            found = class_string_problems(text)
        lines += [f"dark: {rel}:{line}: {problem}" for line, problem in sorted(found)]
    return lines


# Product screenshots on the public site (static/img/marketing). The retired interface was orange
# (Tailwind orange-400..700: hue 20-27 degrees, saturated, bright); the redesigned one has no orange at
# all, so a screenshot where more than a sliver of pixels is that orange was captured before the
# redesign. Creatives inside a screenshot keep their own colours; an amber or gold accent (hue 33+)
# is outside the band. Measured: the old captures were 0.44-0.85% orange, the new ones 0.00-0.06%.
MARKETING_IMAGES = ROOT / "static" / "img" / "marketing"
ORANGE_HUE = (15, 32)  # degrees
ORANGE_MIN_SATURATION = 150  # of 255
ORANGE_MIN_VALUE = 140  # of 255
ORANGE_LIMIT = 0.002  # share of pixels


def orange_share(path: Path) -> float:
    """The share of pixels in ``path`` that are the retired interface orange."""
    from PIL import Image

    with Image.open(path) as image:
        hsv = image.convert("RGB").convert("HSV")
        hsv.thumbnail((1000, 1000))
        data = hsv.tobytes()
    lo, hi = (round(d / 360 * 255) for d in ORANGE_HUE)
    total = len(data) // 3
    hits = sum(
        1
        for i in range(0, len(data), 3)
        if lo <= data[i] <= hi and data[i + 1] >= ORANGE_MIN_SATURATION and data[i + 2] >= ORANGE_MIN_VALUE
    )
    return hits / total if total else 0.0


def orange_screenshots(folder: Path = MARKETING_IMAGES) -> list[str]:
    """Marketing screenshots that still show the retired orange interface (re-capture them)."""
    found = []
    for path in sorted(folder.glob("*")):
        if path.suffix.lower() not in {".webp", ".png", ".jpg", ".jpeg"}:
            continue
        share = orange_share(path)
        if share > ORANGE_LIMIT:
            name = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
            found.append(f"{name}: {share:.2%} of its pixels are the retired orange interface")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="*", type=Path, help="only these files (default: every target)")
    parser.add_argument("--check", action="store_true", help="change nothing; exit 1 if anything is left to do")
    parser.add_argument("--diff", action="store_true", help="print a unified diff instead of writing")
    args = parser.parse_args(argv)

    html, js, py = target_files()
    kinds = classify_templates(html)
    defined = defined_tokens()
    targets = [p.resolve() for p in args.paths] if args.paths else html + js + py
    styles = (ROOT / STYLES_REL).resolve()

    changed = []
    for path in targets:
        if path.suffix == ".css":
            continue  # styles.css is checked, never rewritten (its tokens are written by hand)
        before = path.read_text(encoding="utf-8")
        after = transform(path, before, tokens=kinds.get(path, True), defined=defined)
        if after == before:
            continue
        changed.append(path)
        if args.diff:
            sys.stdout.writelines(
                difflib.unified_diff(
                    before.splitlines(True),
                    after.splitlines(True),
                    str(path.relative_to(ROOT)),
                    str(path.relative_to(ROOT)),
                )
            )
        elif not args.check:
            path.write_text(after, encoding="utf-8")

    rel = [str(p.relative_to(ROOT)) for p in changed]
    if args.check:
        tests = sorted(p for p in (ROOT / "apps").rglob("*.py") if "tests" in p.parts or p.name.startswith("test_"))
        left = leftovers(html + js + py + tests) if not args.paths else leftovers(targets)
        images = orange_screenshots(MARKETING_IMAGES) if not args.paths else []
        dark = dark_findings(targets, kinds)
        if not args.paths or styles in targets:
            dark += styles_problems(styles.read_text(encoding="utf-8")) if styles.exists() else []
        for name in rel:
            print(f"would recolour: {name}")
        for line in left:
            print(f"old palette class: {line}")
        for line in images:
            print(f"old screenshot: {line}")
        for line in dark:
            print(line)
        if rel or left or images or dark:
            print(
                f"{len(rel)} file(s) to recolour, {len(left)} old palette class line(s) left, "
                f"{len(images)} marketing screenshot(s) to re-capture, {len(dark)} dark finding(s)",
                file=sys.stderr,
            )
            return 1
        print("recolor: nothing left to do")
        return 0
    if not args.diff:
        print(f"recoloured {len(rel)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
