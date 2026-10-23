"""Move templates, JS and Python class strings to the "Quiet graphite + Pine" palette.

This is the codemod behind the October 2026 redesign (the design system's migration map,
sections 1-7). It rewrites, in place:

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

What it leaves alone: platform and brand colours (only colours in the old palettes are
mapped, so LinkedIn ``#0A66C2`` or a client's navy never move), user-chosen label colours
(colour pickers and their presets), component classes such as ``btn-neutral``, tests,
migrations and vendored JS.

It is idempotent: the output contains no old palette names and no mapped hex, so a second
run changes nothing.

Usage::

    python tools/recolor.py            # rewrite every target file
    python tools/recolor.py --check    # change nothing; list files that would change and any
                                       # old palette class left anywhere (exit 1 if either)
    python tools/recolor.py path ...   # only these files
    python tools/recolor.py --diff     # print a unified diff instead of writing
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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
# Default step per scale (the migration map's role-correct tables; Layer 0 renders the same).
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

        css = re.sub(
            r"rgba\(\s*var\(--primary-rgb\s*,\s*249\s*,\s*115\s*,\s*22\s*\)",
            "rgba(var(--primary-rgb)" if self.tokens else "rgba(17, 86, 65",
            css,
        )
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


def transform(path: Path, text: str, *, tokens: bool, defined: set[str]) -> str:
    if path.suffix == ".py":
        form_file = path.name.startswith(("forms", "widgets"))
        return recolor_classes(text, python_form_file=form_file)
    out = recolor_scrims(recolor_classes(text))
    if path.suffix == ".html":
        out = recolor_html_colours(out, tokens=tokens, defined=defined)
    return out


def leftovers(paths: Iterable[Path]) -> list[str]:
    found = []
    for p in paths:
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if LEFTOVER_RE.search(line):
                found.append(f"{p.relative_to(ROOT)}:{n}: {line.strip()[:160]}")
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

    changed = []
    for path in targets:
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
        for name in rel:
            print(f"would recolour: {name}")
        for line in left:
            print(f"old palette class: {line}")
        if rel or left:
            print(f"{len(rel)} file(s) to recolour, {len(left)} old palette class line(s) left", file=sys.stderr)
            return 1
        print("recolor: nothing left to do")
        return 0
    if not args.diff:
        print(f"recoloured {len(rel)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
