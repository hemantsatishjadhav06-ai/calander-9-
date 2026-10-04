"""fal.ai pictures: the prompt, the HTTP exchange, and the dashboard button."""

import base64
import io
from unittest import mock

import httpx
import pytest
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from apps.blog import ai_images
from apps.blog.models import BlogPost
from apps.blog.tests.conftest import approved_post, make_post
from apps.media_library.models import MediaAsset


def _jpeg(width=1024, height=576):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (90, 120, 160)).save(buf, format="JPEG")
    return buf.getvalue()


def _data_url(data, content_type="image/jpeg"):
    return f"data:{content_type};base64," + base64.b64encode(data).decode()


class FakeHttp:
    """A stand-in for ``httpx.Client`` that answers fal.run and fal.media."""

    def __init__(self, status=200, payload=None, raise_exc=None, file_bytes=None, file_status=200):
        self.status = status
        self.payload = payload
        self.raise_exc = raise_exc
        self.file_bytes = file_bytes
        self.file_status = file_status
        self.posts = []
        self.gets = []

    def post(self, url, json=None, headers=None):
        self.posts.append((url, json, headers))
        if self.raise_exc:
            raise self.raise_exc
        request = httpx.Request("POST", url)
        return httpx.Response(self.status, json=self.payload, request=request)

    def stream(self, method, url):
        self.gets.append(url)
        request = httpx.Request(method, url)
        response = httpx.Response(
            self.file_status,
            content=self.file_bytes or b"",
            headers={"content-type": "image/jpeg", "content-length": str(len(self.file_bytes or b""))},
            request=request,
        )
        return _StreamContext(response)

    def close(self):
        pass


class _StreamContext:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self.response

    def __exit__(self, *exc):
        return False


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def test_prompt_names_the_subject_forbids_text_and_rotates_styles():
    prompt = ai_images.build_prompt(title="Flats in Kokapet 2026", category="Area Guide", site_kind="neopolis_static")
    assert "Flats in Kokapet 2026" in prompt and "Area Guide" in prompt
    assert "West Hyderabad" in prompt and "no text" in prompt.lower()
    assert ai_images.build_prompt(title="x", seed="a") == ai_images.build_prompt(title="x", seed="a")
    styles = {ai_images.pick_style(str(n)) for n in range(40)}
    assert len(styles) == len(ai_images.STYLES)


def test_an_editors_brief_replaces_the_subject():
    prompt = ai_images.build_prompt(title="Kokapet", brief="a family on a sunlit balcony", site_kind="morespace_static")
    assert "a family on a sunlit balcony" in prompt and "represents the article" not in prompt
    assert "high-rise residences in Hyderabad" in prompt


# ---------------------------------------------------------------------------
# The exchange
# ---------------------------------------------------------------------------


def test_unconfigured_raises_a_readable_error():
    with override_settings(FAL_KEY=""):
        assert not ai_images.is_configured()
        with pytest.raises(ai_images.NotConfiguredError, match="FAL_KEY"):
            ai_images.generate_image(title="x")


@override_settings(FAL_KEY="fal-test-key", FAL_IMAGE_MODEL="fal-ai/flux/schnell")
def test_inline_image_is_decoded_and_the_request_is_shaped_for_fal():
    picture = _jpeg()
    fake = FakeHttp(
        payload={"images": [{"url": _data_url(picture), "width": 1024, "height": 576, "content_type": "image/jpeg"}]}
    )
    result = ai_images.generate_image(title="Flats in Kokapet", category="Guide", client=fake)
    assert result.content == picture and result.model == "fal-ai/flux/schnell"
    assert result.width == 1024 and result.extension == "jpg"
    url, body, headers = fake.posts[0]
    assert url == "https://fal.run/fal-ai/flux/schnell"
    assert headers["Authorization"] == "Key fal-test-key"
    assert body["image_size"] == "landscape_16_9" and body["num_images"] == 1 and body["sync_mode"] is True
    assert "no text" in body["prompt"].lower()


@override_settings(FAL_KEY="fal-test-key")
def test_a_hosted_image_is_downloaded_only_from_fal_hosts():
    picture = _jpeg()
    fake = FakeHttp(payload={"images": [{"url": "https://v3.fal.media/files/abc/out.jpg"}]}, file_bytes=picture)
    assert ai_images.generate_image(title="x", client=fake).content == picture
    assert fake.gets == ["https://v3.fal.media/files/abc/out.jpg"]

    elsewhere = FakeHttp(payload={"images": [{"url": "https://evil.example.com/out.jpg"}]}, file_bytes=picture)
    with pytest.raises(ai_images.ImageGenerationError, match="doesn't trust"):
        ai_images.generate_image(title="x", client=elsewhere)
    assert elsewhere.gets == []


@override_settings(FAL_KEY="fal-test-key")
@pytest.mark.parametrize(
    ("status", "fragment"),
    [
        (401, "rejected FAL_KEY"),
        (402, "no credit"),
        (404, "doesn't know the model"),
        (422, "refused"),
        (429, "rate-limiting"),
        (500, "HTTP 500"),
    ],
)
def test_fal_errors_are_explained(status, fragment):
    fake = FakeHttp(status=status, payload={"detail": "nope"})
    with pytest.raises(ai_images.ImageGenerationError, match=fragment):
        ai_images.generate_image(title="x", client=fake)


@override_settings(FAL_KEY="fal-test-key", FAL_TIMEOUT=7)
def test_timeouts_and_empty_answers_are_explained():
    with pytest.raises(ai_images.ImageGenerationError, match="longer than 7 seconds"):
        ai_images.generate_image(title="x", client=FakeHttp(raise_exc=httpx.ReadTimeout("slow")))
    with pytest.raises(ai_images.ImageGenerationError, match="without an image"):
        ai_images.generate_image(title="x", client=FakeHttp(payload={"images": []}))


def test_validate_image_reads_dimensions_and_rejects_junk():
    assert ai_images.validate_image(_jpeg(640, 360)) == (640, 360)
    with pytest.raises(ai_images.ImageGenerationError):
        ai_images.validate_image(b"junk")


# ---------------------------------------------------------------------------
# Dashboard button
# ---------------------------------------------------------------------------


def _url(name, world, post):
    return reverse(f"blog:{name}", kwargs={"workspace_id": world.workspace.id, "post_id": post.id})


def test_button_is_disabled_with_a_note_until_fal_key_is_set(client, world):
    post = make_post(world)
    client.force_login(world.editor)
    with override_settings(FAL_KEY=""):
        html = client.get(_url("edit", world, post)).content.decode()
    assert "FAL_KEY" in html and 'form="generate-cover-form" disabled' in html
    with override_settings(FAL_KEY="k", FAL_IMAGE_MODEL="fal-ai/flux/dev"):
        html = client.get(_url("edit", world, post)).content.decode()
    assert "fal-ai/flux/dev" in html and 'form="generate-cover-form" disabled' not in html


def test_generating_without_a_key_redirects_with_the_reason(client, world):
    post = make_post(world)
    client.force_login(world.editor)
    with override_settings(FAL_KEY=""):
        response = client.post(_url("generate_image", world, post), {"brief": ""}, follow=True)
    assert "FAL_KEY" in response.content.decode()
    assert BlogPost.objects.get(pk=post.pk).featured_image_id is None


@override_settings(FAL_KEY="fal-test-key")
def test_generating_stores_the_picture_and_selects_it(client, world):
    post = make_post(world, cover_style="designed")
    client.force_login(world.editor)
    picture = _jpeg()
    generated = ai_images.GeneratedImage(
        content=picture, content_type="image/jpeg", prompt="p", model="fal-ai/flux/dev", width=1024, height=576
    )
    with mock.patch("apps.blog.ai_images.generate_image", return_value=generated) as gen:
        response = client.post(_url("generate_image", world, post), {"brief": "a balcony at dusk"}, follow=True)
    assert response.redirect_chain[-1][0].endswith("/edit/")
    assert gen.call_args.kwargs["brief"] == "a balcony at dusk" and gen.call_args.kwargs["seed"] == post.slug
    saved = BlogPost.objects.get(pk=post.pk)
    asset = saved.featured_image
    assert asset is not None and asset.source == "fal.ai" and asset.width == 1024
    assert asset.filename.startswith("ai-cover-flats-in-kokapet-2026-r1.")
    assert saved.featured_image_alt == post.title and saved.revision == 2
    assert "set as the featured image" in response.content.decode()
    assert MediaAsset.objects.filter(workspace=world.workspace, tags__contains=["blog-cover"]).count() == 1


@override_settings(FAL_KEY="fal-test-key")
def test_generating_for_an_approved_post_withdraws_the_approval(client, world):
    post = approved_post(world)
    client.force_login(world.owner)
    generated = ai_images.GeneratedImage(content=_jpeg(), content_type="image/jpeg", prompt="p", model="m")
    with mock.patch("apps.blog.ai_images.generate_image", return_value=generated):
        response = client.post(_url("generate_image", world, post), follow=True)
    assert "needs approval again" in response.content.decode()
    assert BlogPost.objects.get(pk=post.pk).status == BlogPost.Status.PENDING_REVIEW


@override_settings(FAL_KEY="fal-test-key")
def test_a_viewer_cannot_generate(client, world):
    post = make_post(world)
    client.force_login(world.viewer)
    assert client.post(_url("generate_image", world, post)).status_code == 403
