"""The illustrator: the picture behind a graphic, generated with fal.ai.

The art director writes the prompt and the reusable picture style; this asks
fal.ai (``apps.blog.ai_images``, the same client the blog's covers use) for
one wordless picture shaped like the area it will fill, and stores it in the
workspace's media library. Words are never drawn by the image model — the
designer sets them afterwards.
"""

from __future__ import annotations

from django.core.files.base import ContentFile

from apps.blog import ai_images

from . import design

#: Pixels to ask for: about 1.2 megapixels, each side a multiple of 16.
_TARGET_PIXELS = 1_200_000


def is_configured() -> bool:
    return ai_images.is_configured()


def request_size(template: str, fmt: str) -> dict[str, int]:
    """A fal ``image_size`` with the aspect ratio of the layout's picture area."""
    width, height = design.picture_box(template, fmt)
    aspect = width / height
    out_height = (_TARGET_PIXELS / aspect) ** 0.5
    out_width = out_height * aspect

    def snap(value: float) -> int:
        return max(512, min(2048, int(round(value / 16)) * 16))

    return {"width": snap(out_width), "height": snap(out_height)}


def build_prompt(picture_prompt: str, picture_style: str) -> str:
    subject = " ".join((picture_prompt or "").split()).rstrip(".")
    style = " ".join((picture_style or "").split()).rstrip(".")
    parts = [subject]
    if style:
        parts.append(f"Style: {style}")
    parts.append(ai_images.NO_TEXT)
    return ". ".join(part for part in parts if part)


def generate(spec: dict) -> ai_images.GeneratedImage:
    """One picture for ``spec``. Raises ``ai_images.ImageGenerationError`` with a readable message."""
    prompt = build_prompt(spec.get("picture_prompt", ""), spec.get("picture_style", ""))
    size = request_size(spec.get("template", "editorial"), spec.get("format", "portrait"))
    return ai_images.generate_from_prompt(prompt, image_size=size)


#: About what one generated picture takes in the media library (a 1–2 MP JPEG or PNG).
PICTURE_BYTES_ESTIMATE = 4 * 1024 * 1024


def check_room_for_picture(workspace) -> None:
    """Raise ``StorageQuotaExceededError`` before a paid picture is made with nowhere to keep it."""
    from apps.media_library.quotas import enforce_storage_quota

    enforce_storage_quota(workspace.organization, PICTURE_BYTES_ESTIMATE)


def save_picture(brief, generated: ai_images.GeneratedImage):
    """Store a generated picture in the brief's workspace media library."""
    from apps.media_library.models import MediaAsset
    from apps.media_library.quotas import enforce_storage_quota
    from apps.media_library.tasks import process_media_asset

    width, height = ai_images.validate_image(generated.content)
    workspace = brief.workspace
    enforce_storage_quota(workspace.organization, len(generated.content))
    filename = f"studio-picture-{str(brief.pk)[:8]}-r{brief.revision}.{generated.extension}"
    asset = MediaAsset.objects.create(
        organization=workspace.organization,
        workspace=workspace,
        uploaded_by=brief.author,
        file=ContentFile(generated.content, name=filename),
        filename=filename,
        title=f"AI Studio picture: {brief.title}"[:255],
        media_type=MediaAsset.MediaType.IMAGE,
        mime_type=generated.content_type,
        file_size=len(generated.content),
        width=width,
        height=height,
        source="fal.ai",
        attribution=f"Generated with {generated.model} on fal.ai",
        alt_text="",
        tags=["ai", "ai-studio", "picture"],
    )
    process_media_asset(str(asset.id))
    return asset


def save_graphic(brief, content: bytes, alt_text: str):
    """Store the finished graphic in the brief's workspace media library."""
    from apps.media_library.models import MediaAsset
    from apps.media_library.quotas import enforce_storage_quota
    from apps.media_library.tasks import process_media_asset

    width, height = ai_images.validate_image(content)
    workspace = brief.workspace
    enforce_storage_quota(workspace.organization, len(content))
    filename = f"studio-graphic-{str(brief.pk)[:8]}-r{brief.revision}.jpg"
    asset = MediaAsset.objects.create(
        organization=workspace.organization,
        workspace=workspace,
        uploaded_by=brief.author,
        file=ContentFile(content, name=filename),
        filename=filename,
        title=f"AI Studio graphic: {brief.title}"[:255],
        media_type=MediaAsset.MediaType.IMAGE,
        mime_type="image/jpeg",
        file_size=len(content),
        width=width,
        height=height,
        source="ai-studio",
        attribution="Designed by SM Bean's AI Studio",
        alt_text=(alt_text or "")[:500],
        tags=["ai-studio", "graphic"],
    )
    process_media_asset(str(asset.id))
    return asset
