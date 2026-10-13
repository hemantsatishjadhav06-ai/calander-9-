"""Camera photos must be bounded before decoding, while keeping orientation and crops."""

import base64
import io

import pytest
from PIL import Image, ImageDraw, JpegImagePlugin, PngImagePlugin

from apps.studio import design, llm

LOOK = design.Look(
    primary=(8, 29, 74), accent=(255, 102, 0), font="oswald", wordmark="NEOPOLIS", domain="neopolisinfra.com"
)


def _bytes(image, fmt="JPEG", **kwargs):
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def _block_image(block):
    assert block["source"]["media_type"] == "image/jpeg"
    return Image.open(io.BytesIO(base64.b64decode(block["source"]["data"])))


@pytest.fixture
def camera_photo():
    # Cheap enough for this test; deliberately larger than its configured decode budget.
    with Image.new("RGB", (3200, 2400), (40, 90, 130)) as picture:
        return _bytes(picture)


@pytest.fixture
def oriented_photo():
    with Image.new("RGB", (600, 400), (220, 20, 20)) as picture:
        ImageDraw.Draw(picture).rectangle((300, 0, 599, 399), fill=(20, 20, 220))
        exif = Image.Exif()
        exif[274] = 6  # Clockwise 90 degrees: red should be above blue.
        return _bytes(picture, exif=exif, quality=95)


def _record_decodes(monkeypatch, image_class):
    original_load = image_class.load
    decoded_sizes = []

    def load(image, *args, **kwargs):
        decoded_sizes.append(image.size)
        return original_load(image, *args, **kwargs)

    monkeypatch.setattr(image_class, "load", load)
    return decoded_sizes


def test_agent_photo_is_drafted_before_the_jpeg_decoder_runs(camera_photo, monkeypatch, settings):
    settings.MEDIA_LIBRARY_MAX_IMAGE_PIXELS = 500_000
    decoded_sizes = _record_decodes(monkeypatch, JpegImagePlugin.JpegImageFile)

    block = llm.image_block(camera_photo, max_side=128)

    assert decoded_sizes
    assert all(width * height <= 500_000 for width, height in decoded_sizes)
    assert (3200, 2400) not in decoded_sizes
    with _block_image(block) as result:
        assert result.mode == "RGB"
        assert result.size == (128, 96)


def test_renderer_photo_is_drafted_before_the_jpeg_decoder_runs(camera_photo, monkeypatch, settings):
    settings.MEDIA_LIBRARY_MAX_IMAGE_PIXELS = 500_000
    decoded_sizes = _record_decodes(monkeypatch, JpegImagePlugin.JpegImageFile)

    with design.load_picture(camera_photo, (200, 150), "natural", LOOK) as result:
        assert result.size == (200, 150)
        assert result.mode == "RGB"

    assert decoded_sizes
    assert all(width * height <= 500_000 for width, height in decoded_sizes)
    assert (3200, 2400) not in decoded_sizes


def test_agent_photo_resizing_keeps_exif_orientation(oriented_photo):
    block = llm.image_block(oriented_photo, max_side=192)

    with _block_image(block) as result:
        assert result.size == (128, 192)
        red = result.getpixel((64, 40))
        blue = result.getpixel((64, 150))
        assert red[0] > red[2] + 150
        assert blue[2] > blue[0] + 150
        assert result.getexif().get(274, 1) == 1


def test_renderer_crop_keeps_exif_orientation_and_requested_geometry(oriented_photo):
    with design.load_picture(oriented_photo, (200, 300), "natural", LOOK) as result:
        assert result.size == (200, 300)
        red = result.getpixel((100, 70))
        blue = result.getpixel((100, 230))
        assert red[0] > red[2] + 150
        assert blue[2] > blue[0] + 150

    graphic = design.render(
        {"template": "split", "format": "portrait", "grade": "natural", "headline": "A real site photo"},
        LOOK,
        oriented_photo,
    )
    with Image.open(io.BytesIO(graphic)) as result:
        assert result.format == "JPEG"
        assert result.size == design.canvas_size("portrait")


@pytest.mark.parametrize("consumer", ["agent", "renderer"])
def test_oversized_png_is_rejected_before_decoding_and_has_a_useful_error(consumer, monkeypatch, settings):
    with Image.new("RGB", (600, 400), (20, 80, 140)) as picture:
        photo = _bytes(picture, fmt="PNG")
    settings.MEDIA_LIBRARY_MAX_IMAGE_PIXELS = 100_000
    decoded_sizes = _record_decodes(monkeypatch, PngImagePlugin.PngImageFile)

    if consumer == "agent":
        with pytest.raises(llm.StudioAgentError, match=r"(?i)(limit|resize|smaller|too large)"):
            llm.image_block(photo, max_side=128)
    else:
        with pytest.raises(ValueError, match=r"(?i)(limit|resize|smaller|too large)"):
            design.load_picture(photo, (128, 128), "natural", LOOK)
        # The optional-picture fallback remains usable; an oversized source is
        # a clear error, rather than silently masquerading as a valid photo.
        graphic = design.render({"headline": "A factual headline", "format": "square"}, LOOK)
        with Image.open(io.BytesIO(graphic)) as result:
            assert result.size == design.canvas_size("square")
    assert decoded_sizes == []
