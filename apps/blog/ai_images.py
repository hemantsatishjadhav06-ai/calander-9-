"""Generate a blog post's picture with fal.ai.

The dashboard's "Generate with AI" button asks fal.ai for one wordless,
16:9 picture that fits the post, stores it in the media library and sets it
as the post's featured image. The designed cover (:mod:`apps.blog.covers`)
then puts the title over it, so the model is never asked to draw text — the
one thing image models still get wrong.

Configuration (environment):

* ``FAL_KEY`` — the fal.ai API key. Empty: the button explains it is not set up.
* ``FAL_IMAGE_MODEL`` — the model id, default ``fal-ai/flux/dev``. Any model
  on fal.run that takes ``prompt`` + ``image_size`` and answers with
  ``images[]`` works (``fal-ai/flux/schnell`` is faster and cheaper,
  ``fal-ai/flux-pro/v1.1`` finer).

Calls are synchronous (``https://fal.run/<model>``) and bounded by
``FAL_TIMEOUT`` seconds. The picture comes back either inline (a ``data:``
URL, when the model honours ``sync_mode``) or as a URL on fal's media hosts,
which is the only place this module will download from.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

FAL_RUN = "https://fal.run"
DEFAULT_MODEL = "fal-ai/flux/dev"
DEFAULT_TIMEOUT = 90.0
MAX_IMAGE_BYTES = 25 * 1024 * 1024
# Hosts fal serves generated files from. A URL anywhere else is refused.
ALLOWED_IMAGE_HOSTS = ("fal.media", "fal.run", "fal.ai")

# Distinct looks, rotated per post so a blog index doesn't read as one batch.
STYLES = (
    "Cinematic editorial photograph, golden-hour light, 35mm lens, shallow depth of field, rich warm tones",
    "Architectural photograph at blue hour, long exposure, glass and concrete towers, cool crisp light",
    "Flat vector illustration, geometric shapes, bold simple forms, generous negative space, modern poster style",
    "Isometric 3D render, clean studio lighting, soft shadows, miniature-city feel, pastel-free confident colours",
    "Moody documentary photograph, overcast soft light, textured surfaces, candid composition",
)
BRAND_SCENES = {
    "neopolis_static": (
        "modern residential apartment towers and gated communities in West Hyderabad, India — Kokapet, "
        "Narsingi, Tellapur, Financial District skyline, tree-lined avenues, balconies, interiors of premium flats"
    ),
    "morespace_static": (
        "premium high-rise residences in Hyderabad, India — glass towers, rooftop views, bright interiors, "
        "landscaped podiums, an aspirational but believable neighbourhood"
    ),
}
DEFAULT_SCENE = BRAND_SCENES["neopolis_static"]
NO_TEXT = "Absolutely no text, letters, numbers, words, logos, watermarks, signage or captions anywhere in the image."


class ImageGenerationError(Exception):
    """fal.ai could not give us a picture. The message is for people."""


class NotConfiguredError(ImageGenerationError):
    pass


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes
    content_type: str
    prompt: str
    model: str
    width: int = 0
    height: int = 0

    @property
    def extension(self) -> str:
        return "png" if "png" in self.content_type else "jpg"


def is_configured() -> bool:
    return bool((getattr(settings, "FAL_KEY", "") or "").strip())


def model_id() -> str:
    return (getattr(settings, "FAL_IMAGE_MODEL", "") or DEFAULT_MODEL).strip().strip("/")


def pick_style(seed: str) -> str:
    digest = hashlib.sha256((seed or "").encode("utf-8")).digest()
    return STYLES[digest[0] % len(STYLES)]


def build_prompt(*, title: str, category: str = "", site_kind: str = "", brief: str = "", seed: str = "") -> str:
    """The prompt for one post: subject from the title (or the editor's brief), look from the rotation."""
    title = " ".join((title or "").split())
    brief = " ".join((brief or "").split())
    style = pick_style(seed or title)
    scene = BRAND_SCENES.get(site_kind, DEFAULT_SCENE)
    subject = brief or f"A scene that represents the article “{title}”"
    if category:
        subject += f" (editorial category: {category.strip()})"
    return (
        f"{style}. {subject}. Setting: {scene}. "
        "Composition: wide 16:9 blog cover with calm, uncluttered space on the left third where a headline "
        "will be placed, the subject towards the right. Mood: premium, trustworthy, contemporary Indian real "
        f"estate. {NO_TEXT}"
    )


def _request_body(prompt: str, image_size: str | dict = "landscape_16_9") -> dict:
    return {
        "prompt": prompt,
        "image_size": image_size,
        "num_images": 1,
        "enable_safety_checker": True,
        "output_format": "jpeg",
        "sync_mode": True,
    }


_DATA_URL_RE = re.compile(r"^data:(?P<type>[\w/+.-]+)?(?:;charset=[\w-]+)?;base64,(?P<data>.+)$", re.DOTALL)


def _decode_data_url(url: str) -> tuple[bytes, str]:
    match = _DATA_URL_RE.match(url.strip())
    if not match:
        raise ImageGenerationError("fal.ai answered with an image this app couldn't decode.")
    try:
        content = base64.b64decode(match.group("data"), validate=False)
    except ValueError as exc:
        raise ImageGenerationError("fal.ai answered with an image this app couldn't decode.") from exc
    return content, match.group("type") or "image/jpeg"


def _allowed_host(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_IMAGE_HOSTS)


def _download(client: httpx.Client, url: str) -> tuple[bytes, str]:
    if not url.startswith("https://") or not _allowed_host(url):
        raise ImageGenerationError("fal.ai pointed at an image host this app doesn't trust; nothing was saved.")
    with client.stream("GET", url) as response:
        if response.status_code != 200:
            raise ImageGenerationError(f"The generated image couldn't be downloaded (HTTP {response.status_code}).")
        content_type = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_IMAGE_BYTES:
            raise ImageGenerationError("The generated image is larger than this app accepts.")
        buf = bytearray()
        for chunk in response.iter_bytes():
            buf += chunk
            if len(buf) > MAX_IMAGE_BYTES:
                raise ImageGenerationError("The generated image is larger than this app accepts.")
    return bytes(buf), content_type


def _explain(response: httpx.Response) -> str:
    status = response.status_code
    detail = ""
    try:
        payload = response.json()
        raw = payload.get("detail") if isinstance(payload, dict) else ""
        if isinstance(raw, list):
            detail = "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in raw)
        elif raw:
            detail = str(raw)
    except ValueError:
        detail = (response.text or "")[:200]
    if status in (401, 403):
        return "fal.ai rejected FAL_KEY: it is wrong, expired or has no access to this model."
    if status == 402:
        return "The fal.ai account has no credit left. Top it up at fal.ai, then try again."
    if status == 404:
        return f"fal.ai doesn't know the model {model_id()!r}. Check FAL_IMAGE_MODEL."
    if status == 422:
        return f"fal.ai refused the request: {detail or 'invalid input'}."
    if status == 429:
        return "fal.ai is rate-limiting this account; wait a minute and try again."
    return f"fal.ai returned HTTP {status}{(': ' + str(detail)) if detail else ''}."


def generate_image(
    *,
    title: str,
    category: str = "",
    site_kind: str = "",
    brief: str = "",
    seed: str = "",
    client: httpx.Client | None = None,
) -> GeneratedImage:
    """Ask fal.ai for one picture. Raises :class:`ImageGenerationError` with a readable message."""
    if not is_configured():
        raise NotConfiguredError(
            "AI pictures need FAL_KEY on the SM Bean service (an API key from fal.ai). "
            "Upload a picture to the media library instead, or ask your admin to add the key."
        )
    prompt = build_prompt(title=title, category=category, site_kind=site_kind, brief=brief, seed=seed)
    return generate_from_prompt(prompt, client=client)


def generate_from_prompt(
    prompt: str,
    *,
    image_size: str | dict = "landscape_16_9",
    client: httpx.Client | None = None,
) -> GeneratedImage:
    """Ask fal.ai for one picture for an already written ``prompt``.

    ``image_size`` is a fal preset (``landscape_16_9``, ``portrait_4_3``, …) or
    ``{"width": w, "height": h}``. Raises :class:`ImageGenerationError` with a
    readable message. Used by the blog (through :func:`generate_image`) and by
    the AI Studio's illustrator.
    """
    if not is_configured():
        raise NotConfiguredError("AI pictures need FAL_KEY on the SM Bean service (an API key from fal.ai).")
    model = model_id()
    timeout = float(getattr(settings, "FAL_TIMEOUT", DEFAULT_TIMEOUT))
    headers = {"Authorization": f"Key {settings.FAL_KEY.strip()}", "Content-Type": "application/json"}
    own_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(timeout, connect=15.0), follow_redirects=False)
    try:
        try:
            response = client.post(f"{FAL_RUN}/{model}", json=_request_body(prompt, image_size), headers=headers)
        except httpx.TimeoutException as exc:
            raise ImageGenerationError(
                f"fal.ai took longer than {int(timeout)} seconds; try again, or pick a faster model."
            ) from exc
        except httpx.HTTPError as exc:
            raise ImageGenerationError(f"Couldn't reach fal.ai ({exc.__class__.__name__}).") from exc
        if response.status_code != 200:
            raise ImageGenerationError(_explain(response))
        try:
            payload = response.json()
        except ValueError as exc:
            raise ImageGenerationError("fal.ai answered with something that isn't JSON.") from exc
        images = payload.get("images") if isinstance(payload, dict) else None
        if not images or not isinstance(images, list) or not isinstance(images[0], dict):
            raise ImageGenerationError("fal.ai answered without an image. Try again with a different brief.")
        first = images[0]
        url = str(first.get("url") or "")
        if not url:
            raise ImageGenerationError("fal.ai answered without an image URL.")
        if url.startswith("data:"):
            content, content_type = _decode_data_url(url)
        else:
            content, content_type = _download(client, url)
        if not content:
            raise ImageGenerationError("fal.ai answered with an empty image.")
        content_type = str(first.get("content_type") or content_type or "image/jpeg")
        return GeneratedImage(
            content=content,
            content_type=content_type,
            prompt=prompt,
            model=model,
            width=int(first.get("width") or 0),
            height=int(first.get("height") or 0),
        )
    finally:
        if own_client:
            client.close()


def validate_image(content: bytes) -> tuple[int, int]:
    """``(width, height)`` of ``content``, raising ImageGenerationError if it isn't an image."""
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            return image.width, image.height
    except (OSError, Image.DecompressionBombError) as exc:
        raise ImageGenerationError("fal.ai answered with a file that isn't a readable image.") from exc
