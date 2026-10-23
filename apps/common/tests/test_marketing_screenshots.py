"""The public site's product screenshots show the redesigned app, not the retired orange one.

The hero and features images were captures from before the redesign (an orange New button, orange
nav and today circle). tools/recolor.py --check now flags any screenshot under static/img/marketing
where more than a sliver of pixels is the retired interface orange.
"""

from PIL import Image

from tools import recolor


def test_current_marketing_screenshots_have_no_orange_interface():
    assert recolor.orange_screenshots() == []


def test_an_orange_interface_capture_is_flagged(tmp_path):
    shot = Image.new("RGB", (400, 200), (246, 247, 248))  # the graphite canvas
    for x in range(20, 120):  # an orange-500 "New" button, as the old captures had
        for y in range(20, 44):
            shot.putpixel((x, y), (0xF9, 0x73, 0x16))
    shot.save(tmp_path / "calendar.webp", "WEBP")
    Image.new("RGB", (400, 200), (246, 247, 248)).save(tmp_path / "clean.png")

    found = recolor.orange_screenshots(tmp_path)

    assert len(found) == 1 and "calendar.webp" in found[0]


def test_a_creatives_amber_accent_is_not_the_interface_orange(tmp_path):
    creative = Image.new("RGB", (400, 200), (14, 42, 71))  # a navy creative
    for x in range(20, 380):
        for y in range(40, 160):
            creative.putpixel((x, y), (0xE8, 0xA3, 0x3D))  # amber headline
    creative.save(tmp_path / "creative.png")

    assert recolor.orange_screenshots(tmp_path) == []
