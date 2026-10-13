"""Designed blog covers: the post's title set over its picture, in the brand's look.

A cover is the 1600x900 hero JPEG a post page and the blog index show, and the
image social networks pick up from ``og:image``. ``compose_cover`` draws it
with Pillow only — no browser, no external service — so it renders the same on
the worker that publishes and in the dashboard preview:

* the picture (the featured image, cover-cropped) or, without one, a brand
  background built from the site's colours;
* a navy scrim fading in from the left and up from the bottom, so the title
  reads over any picture;
* the category as an accent-coloured tag, the title in the brand's display
  face (auto-sized to fit three lines), an accent rule beside it, and the
  brand's wordmark and domain at the foot.

The fonts live in ``apps/blog/fonts`` (Oswald and Outfit, both SIL Open Font
Licence, see the OFL.txt files there), so a fresh container renders text
identically to the last one. Everything here is pure: the same inputs give the
same JPEG bytes, which is what lets the publisher skip an unchanged image.
"""

from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

CANVAS = (1600, 900)
JPEG_QUALITY = 88
FONT_DIR = Path(__file__).resolve().parent / "fonts"

# Layout, in canvas pixels.
MARGIN_X = 96
TITLE_MAX_WIDTH = 1180
TITLE_MAX_LINES = 3
TITLE_START_SIZE = 112
TITLE_MIN_SIZE = 60
TITLE_BOTTOM = 712
TAG_TOP = 108
WORDMARK_BASELINE = 804
RULE_WIDTH = 10
BOTTOM_STRIP = 14


@dataclass(frozen=True)
class Brand:
    """How one website's covers look."""

    wordmark: str
    domain: str
    primary: tuple[int, int, int]
    accent: tuple[int, int, int]
    title_font: str
    ui_font: str
    default_category: str


BRANDS: dict[str, Brand] = {
    "neopolis_static": Brand(
        wordmark="NEOPOLIS INFRA",
        domain="neopolisinfra.com",
        primary=(8, 29, 74),  # navy #081d4a, the site's theme colour
        accent=(255, 102, 0),  # orange #ff6600, blog.css accent
        title_font="Oswald-Variable.ttf",
        ui_font="Oswald-Variable.ttf",
        default_category="Guide",
    ),
    "morespace_static": Brand(
        wordmark="MORE SPACE",
        domain="morespace.netlify.app",
        primary=(45, 35, 109),  # indigo #2d236d
        accent=(3, 0, 199),  # blue #0300c7
        title_font="Outfit-Variable.ttf",
        ui_font="Outfit-Variable.ttf",
        default_category="Insights",
    ),
}
DEFAULT_BRAND = BRANDS["neopolis_static"]


def brand_for(site_kind: str) -> Brand:
    return BRANDS.get(site_kind, DEFAULT_BRAND)


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------


@lru_cache(maxsize=64)
def _font(name: str, size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_DIR / name), size)
    # A static (non-variable) font file has one weight; use it as it is.
    with contextlib.suppress(OSError):
        font.set_variation_by_axes([weight])
    return font


def _text_width(font: ImageFont.FreeTypeFont, text: str, tracking: float = 0) -> float:
    if not text:
        return 0
    return font.getlength(text) + tracking * (len(text) - 1)


def _draw_tracked(draw: ImageDraw.ImageDraw, xy, text: str, font, fill, tracking: float = 0) -> float:
    """Draw ``text`` with letter-spacing; returns the x where it ended."""
    x, y = xy
    if tracking == 0:
        draw.text((x, y), text, font=font, fill=fill)
        return x + font.getlength(text)
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += font.getlength(char) + tracking
    return x - tracking


# ---------------------------------------------------------------------------
# Title fitting
# ---------------------------------------------------------------------------


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Greedy word wrap; a single word wider than the line is kept whole."""
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


def fit_title(title: str, font_name: str, *, max_width: int = TITLE_MAX_WIDTH, max_lines: int = TITLE_MAX_LINES):
    """The largest size (from ``TITLE_START_SIZE`` down) at which the title fits.

    Returns ``(font, lines)``. Below ``TITLE_MIN_SIZE`` the title is cut to the
    last fitting line with an ellipsis rather than overflowing the canvas.
    """
    title = " ".join((title or "").split()) or "Untitled"
    size = TITLE_START_SIZE
    while True:
        font = _font(font_name, size, 700)
        lines = _wrap(title, font, max_width)
        fits = len(lines) <= max_lines and all(font.getlength(line) <= max_width for line in lines)
        if fits or size <= TITLE_MIN_SIZE:
            break
        size -= 4
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and font.getlength(last + "…") > max_width:
            last = last[:-1].rstrip()
        lines[-1] = (last or lines[-1][: max(1, len(lines[-1]) - 1)]) + "…"
    return font, lines


# ---------------------------------------------------------------------------
# Backgrounds
# ---------------------------------------------------------------------------


def cover_crop(image: Image.Image, size: tuple[int, int] = CANVAS) -> Image.Image:
    """Scale ``image`` to fill ``size`` and crop the overflow around the centre."""
    image = ImageOps.exif_transpose(image)
    if image.mode != "RGB":
        if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
            rgba = image.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            image = flat
        else:
            image = image.convert("RGB")
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.45))


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _darken(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, round(c * factor)) for c in color)  # type: ignore[return-value]


def _vertical_gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    width, height = size
    strip = Image.new("RGB", (1, height))
    strip.putdata([_lerp(top, bottom, y / max(1, height - 1)) for y in range(height)])
    return strip.resize(size, Image.Resampling.BILINEAR)


def _horizontal_mask(width: int, height: int, stops: list[tuple[float, float]]) -> Image.Image:
    """An ``L`` mask whose value follows the ``(x_fraction, alpha)`` stops left to right."""
    strip = Image.new("L", (width, 1))
    values = []
    for x in range(width):
        t = x / max(1, width - 1)
        alpha = stops[-1][1]
        for (x0, a0), (x1, a1) in zip(stops, stops[1:], strict=False):
            if x0 <= t <= x1:
                alpha = a0 + (a1 - a0) * ((t - x0) / (x1 - x0) if x1 > x0 else 0)
                break
        values.append(round(255 * alpha))
    strip.putdata(values)
    return strip.resize((width, height), Image.Resampling.BILINEAR)


def _vertical_mask(width: int, height: int, stops: list[tuple[float, float]]) -> Image.Image:
    return _horizontal_mask(height, width, stops).rotate(-90, expand=True)


def brand_background(brand: Brand, seed_text: str = "") -> Image.Image:
    """A picture-free background: a deep gradient with soft geometric blocks.

    ``seed_text`` (the slug) shifts the blocks so two covers without pictures
    don't look identical.
    """
    width, height = CANVAS
    base = _vertical_gradient(CANVAS, _lerp(brand.primary, (255, 255, 255), 0.06), _darken(brand.primary, 0.55))
    layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    offset = sum(ord(c) for c in seed_text) % 7
    # Diagonal translucent slabs rising from the right: the "tower" motif.
    for index in range(5):
        x = 880 + index * 150 + offset * 9
        top = 120 + ((index * 97 + offset * 31) % 260)
        tone = (255, 255, 255, 14 + (index % 3) * 6)
        draw.polygon([(x, height), (x + 120, height), (x + 120 + 90, top), (x + 90, top)], fill=tone)
    # A glow in the accent colour, top right.
    glow = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((1080, -260, 1900, 560), fill=(*brand.accent, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(140))
    composed = Image.alpha_composite(base.convert("RGBA"), glow)
    composed = Image.alpha_composite(composed, layer)
    return composed.convert("RGB")


# ---------------------------------------------------------------------------
# The cover
# ---------------------------------------------------------------------------


def compose_cover(
    *,
    title: str,
    category: str = "",
    site_kind: str = "neopolis_static",
    picture: bytes | None = None,
    slug: str = "",
) -> bytes:
    """Render the designed cover as JPEG bytes (1600x900).

    ``picture`` is the featured image file (any still format Pillow reads); it
    is cover-cropped behind the scrim. Without it the brand background is used.
    Raises ``ValueError`` when ``picture`` is not a readable image.
    """
    brand = brand_for(site_kind)
    width, height = CANVAS

    if picture is not None:
        try:
            with Image.open(io.BytesIO(picture)) as opened:
                opened.load()
                background = cover_crop(opened)
        except (OSError, Image.DecompressionBombError) as exc:
            raise ValueError(f"The featured image could not be read as an image ({exc}).") from exc
        # A touch of depth on photos so white type sits on them.
        background = ImageOps.autocontrast(background, cutoff=1)
    else:
        background = brand_background(brand, slug)

    # Scrim: solid brand colour through a mask that is heavy on the left and
    # at the foot, where the type sits, and light elsewhere so the picture shows.
    scrim = Image.new("RGB", CANVAS, _darken(brand.primary, 0.85))
    horizontal = _horizontal_mask(width, height, [(0.0, 0.90), (0.42, 0.72), (0.78, 0.22), (1.0, 0.08)])
    vertical = _vertical_mask(width, height, [(0.0, 0.10), (0.40, 0.14), (0.72, 0.48), (1.0, 0.88)])
    mask = ImageChops.lighter(horizontal, vertical)
    if picture is None:
        # The brand background is already dark; a lighter scrim keeps its motif.
        mask = mask.point(lambda v: round(v * 0.55))
    canvas = Image.composite(scrim, background, mask)

    # Vignette: darken the corners slightly.
    vignette = Image.new("L", CANVAS, 0)
    ImageDraw.Draw(vignette).ellipse((-width * 0.25, -height * 0.45, width * 1.25, height * 1.45), fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(160)).point(lambda v: 255 - round((255 - v) * 0.45))
    canvas = Image.composite(canvas, Image.new("RGB", CANVAS, (0, 0, 0)), vignette)

    draw = ImageDraw.Draw(canvas)
    white = (255, 255, 255)

    # Category tag.
    tag_text = (category or brand.default_category).strip().upper()
    tag_font = _font(brand.ui_font, 30, 600)
    tag_tracking = 3
    tag_width = _text_width(tag_font, tag_text, tag_tracking)
    pad_x, pad_y = 24, 12
    ascent, descent = tag_font.getmetrics()
    tag_height = ascent + descent + pad_y * 2 - 6
    tag_box = (MARGIN_X, TAG_TOP, MARGIN_X + tag_width + pad_x * 2, TAG_TOP + tag_height)
    draw.rounded_rectangle(tag_box, radius=8, fill=brand.accent)
    _draw_tracked(draw, (MARGIN_X + pad_x, TAG_TOP + pad_y - 4), tag_text, tag_font, white, tag_tracking)

    # Title block, bottom-anchored above the wordmark, with an accent rule.
    title_font, lines = fit_title(title, brand.title_font)
    line_height = round(title_font.size * 1.08)
    block_height = line_height * len(lines)
    top = TITLE_BOTTOM - block_height
    min_top = tag_box[3] + 36
    if top < min_top:
        top = min_top
    rule_box = (MARGIN_X - 30, top + round(title_font.size * 0.12), MARGIN_X - 30 + RULE_WIDTH, top + block_height)
    draw.rectangle(rule_box, fill=brand.accent)

    # Soft shadow under the type for legibility on bright pictures.
    shadow = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    for index, line in enumerate(lines):
        shadow_draw.text((MARGIN_X + 3, top + index * line_height + 6), line, font=title_font, fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), shadow).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    for index, line in enumerate(lines):
        draw.text((MARGIN_X, top + index * line_height), line, font=title_font, fill=white)

    # Wordmark and domain.
    mark_font = _font(brand.ui_font, 34, 600)
    end_x = _draw_tracked(draw, (MARGIN_X, WORDMARK_BASELINE), brand.wordmark, mark_font, white, 4)
    domain_font = _font(brand.ui_font, 26, 400)
    sep_x = end_x + 26
    draw.rectangle((sep_x, WORDMARK_BASELINE + 10, sep_x + 2, WORDMARK_BASELINE + 34), fill=brand.accent)
    draw.text((sep_x + 28, WORDMARK_BASELINE + 4), brand.domain, font=domain_font, fill=(236, 240, 248))

    # Brand strip along the foot.
    draw.rectangle((0, height - BOTTOM_STRIP, width, height), fill=brand.accent)

    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return out.getvalue()


def read_asset_bytes(asset) -> bytes:
    with asset.file.open("rb") as handle:
        return handle.read()


def cover_for_post(post, content=None) -> bytes:
    """The designed cover for ``post`` (its featured image, if any, behind the title)."""
    picture = read_asset_bytes(post.featured_image) if post.featured_image_id else None
    title = content.title if content is not None else post.title
    category = content.category if content is not None else post.category
    return compose_cover(
        title=title,
        category=category,
        site_kind=post.site.kind,
        picture=picture,
        slug=post.slug,
    )


def hero_image_bytes(post, content) -> bytes | None:
    """What the publisher writes as ``<slug>-hero.jpg`` for this post, or None for no image.

    A designed cover always has an image. A plain cover is the featured image
    as uploaded (resized), and nothing when there is none.
    """
    from .renderers import hero_jpeg_bytes

    if content.cover_style == "designed":
        return cover_for_post(post, content)
    if content.has_image and post.featured_image_id:
        return hero_jpeg_bytes(post.featured_image)
    return None
