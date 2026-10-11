"""The graphic designer: a post's words set over its picture, in the brand's look.

The art director decides *what* the graphic says and which layout carries it;
this module draws it, with Pillow only, so the same spec renders the same
JPEG on the worker and in tests. A feed reads as one series because the
things that make a look — layout, canvas, colour treatment of the picture,
typeface, colours, wordmark — come from the spec and the brand, not from the
image model:

* four layouts (``editorial``, ``split``, ``statement``, ``stat``) on three
  canvases (``portrait`` 4:5, ``square``, ``landscape`` 1.91:1);
* a colour ``grade`` that pulls any picture towards the brand colours, so two
  different generated pictures still look like siblings;
* type auto-fitted to its box (it shrinks, then ellipsises — it never spills),
  colours lifted until they read against what is behind them, and characters
  the typeface lacks swapped for ones it has instead of drawn as boxes.

The fonts are the blog covers' (``apps/blog/fonts``, SIL Open Font Licence).
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from apps.blog.covers import FONT_DIR, cover_crop

RGB = tuple[int, int, int]

CANVASES: dict[str, tuple[int, int]] = {
    "portrait": (1080, 1350),
    "square": (1080, 1080),
    "landscape": (1200, 628),
}
TEMPLATES = ("editorial", "split", "statement", "stat")
GRADES = ("natural", "brand_tint", "duotone", "mono")
FONT_FILES = {"oswald": "Oswald-Variable.ttf", "outfit": "Outfit-Variable.ttf"}
JPEG_QUALITY = 90

# Type sizes per canvas: (start size, smallest size, most lines) for the
# headline and the supporting line, then single sizes for the small type.
METRICS: dict[str, dict[str, Any]] = {
    "portrait": {
        "margin": 80,
        "headline": (104, 54, 4),
        "statement": (124, 60, 6),
        "sub": (38, 28, 3),
        "kicker": 26,
        "footer": 30,
        "cta": 30,
        "stat": (260, 120),
        "strip": 12,
    },
    "square": {
        "margin": 72,
        "headline": (92, 50, 3),
        "statement": (108, 54, 5),
        "sub": (34, 26, 2),
        "kicker": 24,
        "footer": 28,
        "cta": 28,
        "stat": (230, 110),
        "strip": 12,
    },
    "landscape": {
        "margin": 56,
        "headline": (66, 38, 3),
        "statement": (76, 40, 3),
        "sub": (28, 22, 2),
        "kicker": 20,
        "footer": 22,
        "cta": 22,
        "stat": (160, 84),
        "strip": 10,
    },
}

#: How much of the canvas the picture takes in the split and stat layouts.
SPLIT_PORTRAIT, SPLIT_SQUARE, SPLIT_SIDE = 0.54, 0.5, 0.48
STAT_PORTRAIT, STAT_SQUARE, STAT_SIDE = 0.36, 0.3, 0.4

WHITE: RGB = (255, 255, 255)
INK: RGB = (17, 24, 39)


# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------


def hex_to_rgb(value: str, default: RGB = (8, 29, 74)) -> RGB:
    value = (value or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return default
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def rgb_to_hex(color: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*color)


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return (round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t), round(a[2] + (b[2] - a[2]) * t))


def _luminance(color: RGB) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: RGB, b: RGB) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def is_dark(color: RGB) -> bool:
    return _luminance(color) < 0.4


def readable(color: RGB, background: RGB, minimum: float = 3.0) -> RGB:
    """``color``, lifted towards white (or black) until it reads on ``background``."""
    target = WHITE if is_dark(background) else INK
    for step in range(11):
        candidate = _mix(color, target, step / 10)
        if contrast(candidate, background) >= minimum:
            return candidate
    return target


@dataclass(frozen=True)
class Look:
    """What the brand contributes to every graphic."""

    primary: RGB
    accent: RGB
    font: str
    wordmark: str
    domain: str = ""
    logo: bytes | None = None

    @classmethod
    def from_profile(cls, profile, logo: bytes | None = None) -> Look:
        return cls(
            primary=hex_to_rgb(profile.primary_color),
            accent=hex_to_rgb(profile.accent_color, default=(255, 102, 0)),
            font=profile.display_font if profile.display_font in FONT_FILES else "outfit",
            wordmark=(profile.wordmark or profile.brand_name or "").strip(),
            domain=(profile.domain or "").strip(),
            logo=logo,
        )

    @property
    def panel(self) -> RGB:
        """The solid colour panels and scrims are made of: the primary, kept dark enough for light type."""
        return self.primary if is_dark(self.primary) else _mix(self.primary, (0, 0, 0), 0.65)

    @property
    def text(self) -> RGB:
        return WHITE

    @property
    def soft_text(self) -> RGB:
        return (230, 235, 245)


# ---------------------------------------------------------------------------
# Type
# ---------------------------------------------------------------------------


@lru_cache(maxsize=128)
def _font(key: str, size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_DIR / FONT_FILES.get(key, FONT_FILES["outfit"])), max(8, int(size)))
    # A static (non-variable) font file has one weight; use it as it is.
    with contextlib.suppress(OSError):
        font.set_variation_by_axes([weight])
    return font


def _render_mask(font: ImageFont.FreeTypeFont, text: str) -> bytes:
    size = int(font.size)
    image = Image.new("L", (size * 2, size * 2), 0)
    ImageDraw.Draw(image).text((size // 4, size // 4), text, font=font, fill=255)
    return image.tobytes()


@lru_cache(maxsize=2048)
def _has_glyph(key: str, char: str) -> bool:
    font = _font(key, 40, 400)
    return _render_mask(font, char) != _render_mask(font, "")


_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0000fe00-\U0000fe0f\U0000200d\U00002b00-\U00002bff\U0001f1e6-\U0001f1ff]"
)
_SUBSTITUTES = {
    "₹": "Rs ",
    "→": "–",
    "←": "–",
    "…": "...",
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "—": "–",
    "–": "-",
}


def clean_text(text: str, font_key: str) -> str:
    """``text`` without emoji, on one line, using only characters the typeface can draw."""
    text = _EMOJI.sub("", text or "")
    text = " ".join(text.split())
    out = []
    for char in text:
        if char.isascii() or _has_glyph(font_key, char):
            out.append(char)
            continue
        substitute = _SUBSTITUTES.get(char, "")
        # A substitute may itself be missing ("—" → "–" → "-").
        while substitute and not all(c.isascii() or _has_glyph(font_key, c) for c in substitute):
            substitute = _SUBSTITUTES.get(substitute, "")
        out.append(substitute)
    return " ".join("".join(out).split())


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    lines: list[str] = []
    current: list[str] = []
    for word in text.split():
        candidate = " ".join([*current, word])
        if current and font.getlength(candidate) > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def fit_text(
    text: str,
    font_key: str,
    *,
    weight: int,
    max_width: float,
    max_lines: int,
    start: int,
    minimum: int,
    max_height: float | None = None,
    leading: float = 1.1,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """The biggest size at which ``text`` fits the box, and its lines.

    Below ``minimum`` the text is cut to the last line that fits, with an
    ellipsis, rather than spilling out of its box.
    """
    text = text or ""
    size = start
    while True:
        font = _font(font_key, size, weight)
        lines = _wrap(text, font, max_width)
        height = len(lines) * size * leading
        fits = len(lines) <= max_lines and all(font.getlength(line) <= max_width for line in lines)
        if max_height is not None and height > max_height:
            fits = False
        if fits or size <= minimum:
            break
        size = max(minimum, size - 2)
    limit = max_lines
    if max_height is not None:
        limit = max(1, min(max_lines, int(max_height // (size * leading))))
    if len(lines) > limit or any(font.getlength(line) > max_width for line in lines):
        lines = lines[:limit]
        last = lines[-1] if lines else ""
        while last and font.getlength(last + "...") > max_width:
            last = last[:-1].rstrip()
        lines[-1] = (last.rstrip(" ,;:–-") + "...") if last else "..."
    return font, lines


def _line_height(font: ImageFont.FreeTypeFont, leading: float) -> int:
    return round(font.size * leading)


def _draw_lines(draw, lines, font, *, x, y, fill, leading, shadow=None, canvas=None) -> int:
    """Draw ``lines`` from ``y`` down; returns the y below the block."""
    step = _line_height(font, leading)
    if shadow is not None and canvas is not None:
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(layer)
        for index, line in enumerate(lines):
            shadow_draw.text((x + 2, y + index * step + 5), line, font=font, fill=(*shadow, 140))
        layer = layer.filter(ImageFilter.GaussianBlur(9))
        canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), layer).convert("RGB"))
        draw = ImageDraw.Draw(canvas)
    for index, line in enumerate(lines):
        draw.text((x, y + index * step), line, font=font, fill=fill)
    return y + len(lines) * step


def _tracked(draw, xy, text, font, fill, tracking: float) -> float:
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += font.getlength(char) + tracking
    return x - tracking if text else x


def _tracked_width(font, text: str, tracking: float) -> float:
    return sum(font.getlength(c) for c in text) + tracking * max(0, len(text) - 1)


def _leading(font_key: str) -> float:
    return 1.06 if font_key == "oswald" else 1.12


# ---------------------------------------------------------------------------
# Pictures and backgrounds
# ---------------------------------------------------------------------------


def grade_picture(image: Image.Image, grade: str, look: Look) -> Image.Image:
    """Apply the colour treatment that makes different pictures read as one series."""
    image = image.convert("RGB")
    if grade == "mono":
        return ImageOps.autocontrast(ImageOps.grayscale(image), cutoff=1).convert("RGB")
    image = ImageOps.autocontrast(image, cutoff=1)
    if grade not in ("brand_tint", "duotone"):
        return image
    gray = ImageOps.grayscale(image)
    shadow = _mix(look.panel, (0, 0, 0), 0.45)
    if grade == "duotone":
        highlight = _mix(look.accent, WHITE, 0.6)
        return ImageOps.colorize(gray, black=shadow, white=highlight, mid=_mix(look.primary, highlight, 0.5))
    tint = ImageOps.colorize(gray, black=shadow, white=_mix(look.primary, WHITE, 0.88))
    return Image.blend(image, tint, 0.36)


def load_picture(picture: bytes, size: tuple[int, int], grade: str, look: Look, centering=(0.5, 0.45)) -> Image.Image:
    try:
        with Image.open(io.BytesIO(picture)) as opened:
            opened.load()
            fitted = cover_crop(opened, size)
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError(f"The picture could not be read as an image ({exc}).") from exc
    if centering != (0.5, 0.45):
        fitted = ImageOps.fit(fitted, size, method=Image.Resampling.LANCZOS, centering=centering)
    return grade_picture(fitted, grade, look)


def _seed(text: str) -> int:
    return int.from_bytes(hashlib.sha256((text or "").encode("utf-8")).digest()[:4], "big")


def brand_background(size: tuple[int, int], look: Look, seed_text: str = "") -> Image.Image:
    """A picture-free background: a deep gradient in the brand colour with soft geometric blocks."""
    width, height = size
    top, bottom = _mix(look.panel, WHITE, 0.07), _mix(look.panel, (0, 0, 0), 0.5)
    strip = Image.new("RGB", (1, height))
    strip.putdata([_mix(top, bottom, y / max(1, height - 1)) for y in range(height)])
    base = strip.resize(size, Image.Resampling.BILINEAR).convert("RGBA")
    offset = _seed(seed_text) % 9
    slabs = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(slabs)
    unit = width / 1080
    for index in range(5):
        x = width * 0.52 + index * 130 * unit + offset * 7 * unit
        rise = height * (0.18 + ((index * 37 + offset * 11) % 30) / 100)
        draw.polygon(
            [(x, height), (x + 110 * unit, height), (x + 190 * unit, rise), (x + 80 * unit, rise)],
            fill=(255, 255, 255, 12 + (index % 3) * 6),
        )
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        (width * 0.55, -height * 0.3, width * 1.35, height * 0.45), fill=(*_mix(look.accent, WHITE, 0.15), 80)
    )
    glow = glow.filter(ImageFilter.GaussianBlur(max(40, width // 7)))
    return Image.alpha_composite(Image.alpha_composite(base, glow), slabs).convert("RGB")


def _gradient_mask(size: tuple[int, int], stops: list[tuple[float, float]], *, vertical: bool) -> Image.Image:
    width, height = size
    length = height if vertical else width
    values = []
    for i in range(length):
        t = i / max(1, length - 1)
        alpha = stops[-1][1]
        for (t0, a0), (t1, a1) in zip(stops, stops[1:], strict=False):
            if t0 <= t <= t1:
                alpha = a0 + (a1 - a0) * ((t - t0) / (t1 - t0) if t1 > t0 else 0)
                break
        values.append(max(0, min(255, round(255 * alpha))))
    if vertical:
        strip = Image.new("L", (1, height))
        strip.putdata(values)
    else:
        strip = Image.new("L", (width, 1))
        strip.putdata(values)
    return strip.resize(size, Image.Resampling.BILINEAR)


def _scrim(canvas: Image.Image, look: Look, strength: float, *, text_top: int) -> Image.Image:
    """Darken the picture where the type sits, in the brand colour.

    Light at the top (just enough for the kicker), fading in above
    ``text_top`` so the darkest part is always behind the headline, however
    many lines it took.
    """
    size = canvas.size
    height = size[1]
    k = max(0.3, min(0.9, strength)) / 0.7
    full = min(0.96, 0.9 * k)
    start = max(0.12, (text_top - height * 0.24) / height)
    at_text = max(start + 0.01, min(0.97, text_top / height))
    vertical = _gradient_mask(
        size,
        [(0.0, 0.32 * k), (start * 0.6, 0.1 * k), (start, 0.12 * k), (at_text, full * 0.82), (1.0, full)],
        vertical=True,
    )
    horizontal = _gradient_mask(size, [(0.0, 0.5 * k), (0.65, 0.1 * k), (1.0, 0.02)], vertical=False)
    mask = ImageChops.lighter(vertical, horizontal)
    return Image.composite(Image.new("RGB", size, _mix(look.panel, (0, 0, 0), 0.25)), canvas, mask)


# ---------------------------------------------------------------------------
# Shared elements
# ---------------------------------------------------------------------------


def _logo_image(look: Look, max_height: int, max_width: int) -> Image.Image | None:
    if not look.logo:
        return None
    try:
        with Image.open(io.BytesIO(look.logo)) as opened:
            opened.load()
            logo = ImageOps.exif_transpose(opened).convert("RGBA")
    except (OSError, Image.DecompressionBombError):
        return None
    logo.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    return logo


def _footer(
    canvas: Image.Image, look: Look, m: dict, *, x: int, bottom: int, color: RGB, accent: RGB, measure: bool = False
) -> int:
    """Wordmark (or logo) and domain on one line ending at ``bottom``; returns the line's top.

    With ``measure`` nothing is drawn: it only says where the line would start.
    """
    draw = ImageDraw.Draw(canvas)
    size = m["footer"]
    logo = _logo_image(look, max_height=round(size * 1.9), max_width=round(canvas.width * 0.32))
    font_key = look.font
    if measure:
        if logo is not None:
            return bottom - logo.height
        ascent, descent = _font(font_key, size, 600).getmetrics()
        return bottom - (ascent + descent)
    if logo is not None:
        top = bottom - logo.height
        canvas.paste(logo, (x, top), logo)
        end_x = x + logo.width
        line_top, line_height = top, logo.height
    else:
        mark_font = _font(font_key, size, 600)
        wordmark = clean_text(look.wordmark.upper(), font_key)
        ascent, descent = mark_font.getmetrics()
        line_height = ascent + descent
        top = bottom - line_height
        end_x = round(_tracked(draw, (x, top), wordmark, mark_font, color, size * 0.13))
        line_top = top
    if look.domain:
        domain_font = _font(font_key, round(size * 0.82), 400)
        sep_x = end_x + round(size * 0.8)
        bar_top = line_top + round(line_height * 0.22)
        draw.rectangle((sep_x, bar_top, sep_x + 2, line_top + round(line_height * 0.82)), fill=accent)
        domain = clean_text(look.domain, font_key)
        d_ascent, d_descent = domain_font.getmetrics()
        draw.text(
            (sep_x + round(size * 0.8), line_top + (line_height - d_ascent - d_descent) // 2 + 2),
            domain,
            font=domain_font,
            fill=_mix(color, look.panel, 0.18),
        )
    return line_top


def _strip(canvas: Image.Image, look: Look, m: dict) -> None:
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, canvas.height - m["strip"], canvas.width, canvas.height), fill=look.accent)


def _chip(canvas: Image.Image, look: Look, m: dict, text: str, *, x: int, y: int) -> int:
    """The kicker as an accent-coloured tag; returns its bottom edge (``y`` when there is no kicker)."""
    text = clean_text((text or "").upper(), look.font)
    if not text:
        return y
    draw = ImageDraw.Draw(canvas)
    size = m["kicker"]
    font = _font(look.font, size, 600)
    tracking = size * 0.12
    pad_x, pad_y = round(size * 0.9), round(size * 0.45)
    ascent, descent = font.getmetrics()
    width = _tracked_width(font, text, tracking)
    max_width = canvas.width - x - m["margin"]
    while width + pad_x * 2 > max_width and len(text) > 3:
        text = text[:-1].rstrip()
        width = _tracked_width(font, text, tracking)
    box = (x, y, round(x + width + pad_x * 2), y + ascent + descent + pad_y * 2 - round(size * 0.2))
    draw.rounded_rectangle(box, radius=round(size * 0.3), fill=look.accent)
    ink = WHITE if contrast(WHITE, look.accent) >= 2.5 else INK
    _tracked(draw, (x + pad_x, y + pad_y - round(size * 0.12)), text, font, ink, tracking)
    return box[3]


def _kicker_text(canvas: Image.Image, look: Look, m: dict, text: str, *, x: int, y: int, background: RGB) -> int:
    """The kicker as tracked capitals with an accent bar before it; returns its bottom edge."""
    text = clean_text((text or "").upper(), look.font)
    if not text:
        return y
    draw = ImageDraw.Draw(canvas)
    size = m["kicker"]
    font = _font(look.font, size, 600)
    color = readable(look.accent, background, 3.0)
    bar_w = round(size * 1.8)
    ascent, descent = font.getmetrics()
    mid = y + (ascent + descent) // 2
    draw.rectangle((x, mid - 3, x + bar_w, mid + 3), fill=color)
    _tracked(draw, (x + bar_w + round(size * 0.6), y), text, font, color, size * 0.14)
    return y + ascent + descent


def _cta(
    canvas: Image.Image, look: Look, m: dict, text: str, *, x: int, bottom: int, background: RGB, measure: bool = False
) -> int:
    """The call to action with a small arrow; returns its top edge (``bottom`` when there is none)."""
    text = clean_text(text or "", look.font)
    if not text:
        return bottom
    draw = ImageDraw.Draw(canvas)
    size = m["cta"]
    font = _font(look.font, size, 600)
    color = readable(look.accent, background, 3.0)
    ascent, descent = font.getmetrics()
    top = bottom - (ascent + descent)
    if measure:
        return top
    max_width = canvas.width - x - m["margin"] - size
    while font.getlength(text) > max_width and len(text) > 4:
        text = text[:-1].rstrip()
    tri = size * 0.42
    cy = top + (ascent + descent) / 2 + size * 0.05
    draw.polygon([(x, cy - tri), (x + tri * 1.2, cy), (x, cy + tri)], fill=color)
    draw.text((x + round(tri * 1.2 + size * 0.45), top), text, font=font, fill=color)
    return top


# ---------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------


def _editorial(size, spec, look, picture) -> Image.Image:
    m = METRICS[spec["format"]]
    width, height = size
    margin = m["margin"]
    canvas = (
        load_picture(picture, size, spec["grade"], look)
        if picture is not None
        else brand_background(size, look, spec["headline"])
    )

    # Measure from the foot up first, so the scrim can sit behind the type.
    kicker = clean_text((spec["kicker"] or "").upper(), look.font)
    if kicker:
        k_ascent, k_descent = _font(look.font, m["kicker"], 600).getmetrics()
        chip_bottom = margin + k_ascent + k_descent + round(m["kicker"] * 0.7)
    else:
        chip_bottom = margin
    bottom = height - m["strip"] - round(margin * 0.75)
    footer_top = _footer(canvas, look, m, x=margin, bottom=bottom, color=look.text, accent=look.accent, measure=True)
    cursor = footer_top - round(margin * 0.55)
    cta_bottom = cursor
    cta_top = _cta(canvas, look, m, spec["cta_label"], x=margin, bottom=cursor, background=look.panel, measure=True)
    if cta_top != cursor:
        cursor = cta_top - round(margin * 0.45)

    leading = _leading(look.font)
    text_width = width - margin * 2
    sub_lines: list[str] = []
    sub_font = None
    sub_top = cursor
    if spec["subheadline"]:
        start, minimum, lines = m["sub"]
        sub_font, sub_lines = fit_text(
            spec["subheadline"],
            look.font,
            weight=400,
            max_width=text_width,
            max_lines=lines,
            start=start,
            minimum=minimum,
            leading=1.25,
        )
        cursor -= len(sub_lines) * _line_height(sub_font, 1.25)
        sub_top = cursor
        cursor -= round(margin * 0.3)

    start, minimum, lines = m["headline"]
    room = cursor - (chip_bottom + round(margin * 0.6))
    head_font, head_lines = fit_text(
        spec["headline"],
        look.font,
        weight=700,
        max_width=text_width,
        max_lines=lines,
        start=start,
        minimum=minimum,
        max_height=room,
        leading=leading,
    )
    head_height = len(head_lines) * _line_height(head_font, leading)
    head_top = cursor - head_height

    if picture is not None:
        canvas = _scrim(canvas, look, spec["overlay"], text_top=head_top)
    _chip(canvas, look, m, spec["kicker"], x=margin, y=margin)
    _footer(canvas, look, m, x=margin, bottom=bottom, color=look.text, accent=look.accent)
    _cta(canvas, look, m, spec["cta_label"], x=margin, bottom=cta_bottom, background=look.panel)
    draw = ImageDraw.Draw(canvas)
    rule_x = margin - round(margin * 0.36)
    draw.rectangle(
        (rule_x, head_top + round(head_font.size * 0.14), rule_x + max(6, round(m["kicker"] * 0.3)), cursor - 4),
        fill=look.accent,
    )
    _draw_lines(
        draw,
        head_lines,
        head_font,
        x=margin,
        y=head_top,
        fill=look.text,
        leading=leading,
        shadow=(0, 0, 0),
        canvas=canvas,
    )
    draw = ImageDraw.Draw(canvas)
    if sub_lines and sub_font is not None:
        _draw_lines(draw, sub_lines, sub_font, x=margin, y=sub_top, fill=look.soft_text, leading=1.25)
    _strip(canvas, look, m)
    return canvas


def _panel_stack(canvas, look, m, spec, *, x, top, bottom, width) -> None:
    """Kicker, headline and supporting line in a solid panel, the footer at its foot."""
    leading = _leading(look.font)
    footer_top = _footer(canvas, look, m, x=x, bottom=bottom, color=look.text, accent=look.accent)
    cursor = _kicker_text(canvas, look, m, spec["kicker"], x=x, y=top, background=look.panel)
    if cursor != top:
        cursor += round(m["margin"] * 0.35)
    limit = footer_top - round(m["margin"] * 0.5)
    cta_top = _cta(canvas, look, m, spec["cta_label"], x=x, bottom=limit, background=look.panel)
    if cta_top != limit:
        limit = cta_top - round(m["margin"] * 0.4)

    sub_font: ImageFont.FreeTypeFont | None = None
    sub_lines: list[str] = []
    sub_height = 0
    if spec["subheadline"]:
        start, minimum, lines = m["sub"]
        sub_font, sub_lines = fit_text(
            spec["subheadline"],
            look.font,
            weight=400,
            max_width=width,
            max_lines=lines,
            start=start,
            minimum=minimum,
            leading=1.25,
        )
        sub_height = len(sub_lines) * _line_height(sub_font, 1.25) + round(m["margin"] * 0.3)
    start, minimum, lines = m["headline"]
    head_font, head_lines = fit_text(
        spec["headline"],
        look.font,
        weight=700,
        max_width=width,
        max_lines=lines,
        start=round(start * 0.92),
        minimum=minimum,
        max_height=max(minimum * leading, limit - cursor - sub_height),
        leading=leading,
    )
    draw = ImageDraw.Draw(canvas)
    cursor = _draw_lines(draw, head_lines, head_font, x=x, y=cursor, fill=look.text, leading=leading)
    if sub_lines and sub_font is not None:
        _draw_lines(
            draw, sub_lines, sub_font, x=x, y=cursor + round(m["margin"] * 0.3), fill=look.soft_text, leading=1.25
        )


def _split(size, spec, look, picture) -> Image.Image:
    m = METRICS[spec["format"]]
    width, height = size
    margin = m["margin"]
    canvas = Image.new("RGB", size, look.panel)
    draw = ImageDraw.Draw(canvas)
    pic_size = picture_box("split", spec["format"])
    if spec["format"] == "landscape":
        pic = (
            load_picture(picture, pic_size, spec["grade"], look)
            if picture is not None
            else (brand_background(pic_size, look, spec["headline"]))
        )
        canvas.paste(pic, (0, 0))
        seam = pic_size[0]
        draw.rectangle((seam - 4, margin, seam + 4, margin + round(height * 0.22)), fill=look.accent)
        _panel_stack(
            canvas,
            look,
            m,
            spec,
            x=seam + margin,
            top=margin,
            bottom=height - m["strip"] - round(margin * 0.7),
            width=width - seam - margin * 2,
        )
    else:
        pic = (
            load_picture(picture, pic_size, spec["grade"], look, centering=(0.5, 0.4))
            if picture is not None
            else brand_background(pic_size, look, spec["headline"])
        )
        canvas.paste(pic, (0, 0))
        seam = pic_size[1]
        draw.rectangle((margin, seam - 6, margin + round(width * 0.14), seam + 6), fill=look.accent)
        _panel_stack(
            canvas,
            look,
            m,
            spec,
            x=margin,
            top=seam + round(margin * 0.7),
            bottom=height - m["strip"] - round(margin * 0.7),
            width=width - margin * 2,
        )
    _strip(canvas, look, m)
    return canvas


def _statement(size, spec, look, picture) -> Image.Image:
    m = METRICS[spec["format"]]
    width, height = size
    margin = m["margin"]
    canvas = brand_background(size, look, spec["headline"])
    if picture is not None:
        faint = load_picture(picture, size, "mono", look)
        canvas = Image.blend(canvas, faint, 0.14)
    top = _kicker_text(canvas, look, m, spec["kicker"], x=margin, y=margin, background=look.panel)
    bottom = height - m["strip"] - round(margin * 0.75)
    footer_top = _footer(canvas, look, m, x=margin, bottom=bottom, color=look.text, accent=look.accent)
    limit = footer_top - round(margin * 0.6)
    cta_top = _cta(canvas, look, m, spec["cta_label"], x=margin, bottom=limit, background=look.panel)
    if cta_top != limit:
        limit = cta_top - round(margin * 0.5)

    leading = _leading(look.font)
    text_width = width - margin * 2
    sub_font: ImageFont.FreeTypeFont | None = None
    sub_lines: list[str] = []
    sub_height = 0
    if spec["subheadline"]:
        start, minimum, lines = m["sub"]
        sub_font, sub_lines = fit_text(
            spec["subheadline"],
            look.font,
            weight=400,
            max_width=text_width,
            max_lines=lines,
            start=start,
            minimum=minimum,
            leading=1.25,
        )
        sub_height = len(sub_lines) * _line_height(sub_font, 1.25) + round(margin * 0.45)
    region_top = top + round(margin * 0.8)
    start, minimum, lines = m["statement"]
    head_font, head_lines = fit_text(
        spec["headline"],
        look.font,
        weight=700,
        max_width=text_width,
        max_lines=lines,
        start=start,
        minimum=minimum,
        max_height=limit - region_top - sub_height,
        leading=leading,
    )
    block = len(head_lines) * _line_height(head_font, leading) + sub_height
    y = region_top + max(0, (limit - region_top - block) // 2)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle(
        (margin, y - round(margin * 0.42), margin + round(width * 0.12), y - round(margin * 0.42) + 8),
        fill=readable(look.accent, look.panel, 2.0),
    )
    y = _draw_lines(draw, head_lines, head_font, x=margin, y=y, fill=look.text, leading=leading)
    if sub_lines and sub_font is not None:
        _draw_lines(draw, sub_lines, sub_font, x=margin, y=y + round(margin * 0.45), fill=look.soft_text, leading=1.25)
    _strip(canvas, look, m)
    return canvas


def _stat(size, spec, look, picture) -> Image.Image:
    m = METRICS[spec["format"]]
    width, height = size
    margin = m["margin"]
    canvas = Image.new("RGB", size, look.panel)
    pic_size = picture_box("stat", spec["format"])
    if spec["format"] == "landscape":
        pic = (
            load_picture(picture, pic_size, spec["grade"], look)
            if picture is not None
            else (brand_background(pic_size, look, spec["headline"]))
        )
        canvas.paste(pic, (width - pic_size[0], 0))
        x, top, text_width = margin, margin, width - pic_size[0] - margin * 2
    else:
        pic = (
            load_picture(picture, pic_size, spec["grade"], look, centering=(0.5, 0.45))
            if picture is not None
            else brand_background(pic_size, look, spec["headline"])
        )
        canvas.paste(pic, (0, 0))
        x, top, text_width = margin, pic_size[1] + round(margin * 0.55), width - margin * 2
    draw = ImageDraw.Draw(canvas)
    stat_color = readable(look.accent, look.panel, 3.0)
    start, minimum = m["stat"]
    value = clean_text(spec["stat_value"], look.font)
    stat_font, stat_lines = fit_text(
        value, look.font, weight=700, max_width=text_width, max_lines=1, start=start, minimum=minimum, leading=1.0
    )
    ascent, descent = stat_font.getmetrics()
    draw.text(
        (x - round(stat_font.size * 0.04), top - round(stat_font.size * 0.12)),
        stat_lines[0] if stat_lines else "",
        font=stat_font,
        fill=stat_color,
    )
    cursor = top + ascent - round(stat_font.size * 0.05)
    label = clean_text((spec["stat_label"] or "").upper(), look.font)
    if label:
        label_font, label_lines = fit_text(
            label,
            look.font,
            weight=600,
            max_width=text_width,
            max_lines=2,
            start=round(m["kicker"] * 1.25),
            minimum=m["kicker"] - 4,
            leading=1.2,
        )
        cursor += round(margin * 0.15)
        for line in label_lines:
            _tracked(draw, (x, cursor), line, label_font, look.soft_text, label_font.size * 0.1)
            cursor += _line_height(label_font, 1.2)
    bottom = height - m["strip"] - round(margin * 0.7)
    footer_top = _footer(canvas, look, m, x=x, bottom=bottom, color=look.text, accent=look.accent)
    limit = footer_top - round(margin * 0.5)
    cta_top = _cta(canvas, look, m, spec["cta_label"], x=x, bottom=limit, background=look.panel)
    if cta_top != limit:
        limit = cta_top - round(margin * 0.4)
    leading = _leading(look.font)
    cursor += round(margin * 0.45)
    sub_font: ImageFont.FreeTypeFont | None = None
    sub_lines: list[str] = []
    sub_height = 0
    if spec["subheadline"]:
        s_start, s_minimum, s_lines = m["sub"]
        sub_font, sub_lines = fit_text(
            spec["subheadline"],
            look.font,
            weight=400,
            max_width=text_width,
            max_lines=s_lines,
            start=round(s_start * 0.9),
            minimum=s_minimum,
            leading=1.25,
        )
        sub_height = len(sub_lines) * _line_height(sub_font, 1.25) + round(margin * 0.25)
        if limit - cursor - sub_height < m["headline"][1] * leading:
            sub_lines, sub_height = [], 0  # no room: the headline matters more
    start, minimum, lines = m["headline"]
    head_font, head_lines = fit_text(
        spec["headline"],
        look.font,
        weight=700,
        max_width=text_width,
        max_lines=3,
        start=round(start * 0.62),
        minimum=round(minimum * 0.75),
        max_height=max(minimum * leading, limit - cursor - sub_height),
        leading=leading,
    )
    cursor = _draw_lines(draw, head_lines, head_font, x=x, y=cursor, fill=look.text, leading=leading)
    if sub_lines and sub_font is not None:
        _draw_lines(draw, sub_lines, sub_font, x=x, y=cursor + round(margin * 0.25), fill=look.soft_text, leading=1.25)
    _strip(canvas, look, m)
    return canvas


LAYOUTS = {"editorial": _editorial, "split": _split, "statement": _statement, "stat": _stat}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def normalise_spec(spec: dict[str, Any], look: Look) -> dict[str, Any]:
    """The spec with every field present, valid and cleaned for the typeface."""
    template = spec.get("template") if spec.get("template") in TEMPLATES else "editorial"
    if template == "stat" and not (spec.get("stat_value") or "").strip():
        template = "editorial"
    fmt = spec.get("format") if spec.get("format") in CANVASES else "portrait"
    grade = spec.get("grade") if spec.get("grade") in GRADES else "brand_tint"
    try:
        overlay = float(spec.get("overlay_strength", 0.65))
    except (TypeError, ValueError):
        overlay = 0.65
    font = look.font
    headline = clean_text(spec.get("headline") or "", font) or clean_text(look.wordmark, font) or "..."
    return {
        "template": template,
        "format": fmt,
        "grade": grade,
        "overlay": max(0.3, min(0.9, overlay)),
        "kicker": clean_text(spec.get("kicker") or "", font)[:40],
        "headline": headline[:160],
        "subheadline": clean_text(spec.get("subheadline") or "", font)[:220],
        "stat_value": clean_text(spec.get("stat_value") or "", font)[:12],
        "stat_label": clean_text(spec.get("stat_label") or "", font)[:60],
        "cta_label": clean_text(spec.get("cta_label") or "", font)[:60],
    }


def render(spec: dict[str, Any], look: Look, picture: bytes | None = None) -> bytes:
    """Draw the graphic for ``spec`` as JPEG bytes.

    ``picture`` is the generated (or uploaded) image; without it the layout
    uses the brand background. Raises ``ValueError`` when ``picture`` is not a
    readable image.
    """
    normalised = normalise_spec(spec, look)
    size = CANVASES[normalised["format"]]
    canvas = LAYOUTS[normalised["template"]](size, normalised, look, picture)
    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return out.getvalue()


def canvas_size(fmt: str) -> tuple[int, int]:
    return CANVASES.get(fmt, CANVASES["portrait"])


def picture_box(template: str, fmt: str) -> tuple[int, int]:
    """The size of the area the picture fills in a layout — what to ask the image model for."""
    width, height = canvas_size(fmt)
    if template == "split":
        if fmt == "landscape":
            return round(width * SPLIT_SIDE), height
        return width, round(height * (SPLIT_PORTRAIT if fmt == "portrait" else SPLIT_SQUARE))
    if template == "stat":
        if fmt == "landscape":
            return round(width * STAT_SIDE), height
        return width, round(height * (STAT_PORTRAIT if fmt == "portrait" else STAT_SQUARE))
    return width, height


def dominant_colours(content: bytes, count: int = 5) -> list[str]:
    """The ``count`` most common colours of an image, as hex, most common first."""
    try:
        with Image.open(io.BytesIO(content)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((160, 160))
    except (OSError, Image.DecompressionBombError):
        return []
    quantised = image.quantize(colors=max(2, count), method=Image.Quantize.MEDIANCUT)
    palette = quantised.getpalette() or []
    counts = sorted(quantised.getcolors() or [], key=lambda pair: int(pair[0]), reverse=True)
    colours = []
    for _count, index in counts[:count]:
        offset = int(index) * 3  # type: ignore[call-overload]
        r, g, b = palette[offset : offset + 3]
        colours.append(rgb_to_hex((r, g, b)))
    return colours
