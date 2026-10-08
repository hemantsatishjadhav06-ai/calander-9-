"""Which look the next graphic follows: the last post this workspace made.

A brand's feed should read as one series, so by default (``style_lock``) the
art director designs within the look of the most recent post:

* ``studio`` — the last graphic the AI Studio made here. Its layout, canvas,
  colour treatment, scrim strength and picture style are copied exactly, and
  the art director only changes the words and the picture's subject.
* ``post`` — the last post that went out (or is scheduled) with a picture but
  wasn't made by the Studio. The art director sees that picture and matches
  it by eye; its main colours are passed along as a hint.
* ``brand`` — nothing posted yet: the brand profile's defaults.
* ``free`` — the person turned the lock off: any look within the brand.

Whichever is more recent of the first two wins. The chosen reference is stored
on the brief (without the image) so the review screen can say what the graphic
was matched to.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from django.db.models.functions import Coalesce

logger = logging.getLogger(__name__)

#: Spec keys that make up a look and are copied from a previous Studio graphic.
LOCKED_KEYS = ("template", "format", "grade", "overlay_strength", "picture_style")
#: Composer statuses that mean a post really went (or is going) out.
OUT_STATUSES = ("published", "publishing", "scheduled", "approved")
MAX_REFERENCE_BYTES = 20 * 1024 * 1024


@dataclass
class StyleReference:
    kind: str
    label: str
    locked: dict[str, Any] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    image: bytes | None = None
    palette: list[str] = field(default_factory=list)
    brief_id: str = ""
    post_id: str = ""
    asset_id: str = ""
    when: str = ""

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "locked": self.locked,
            "palette": self.palette,
            "brief_id": self.brief_id,
            "post_id": self.post_id,
            "asset_id": self.asset_id,
            "when": self.when,
        }


def read_asset(asset) -> bytes | None:
    """The asset's file, or None when it is missing, unreadable or implausibly large."""
    if asset is None or not getattr(asset, "file", None):
        return None
    try:
        if asset.file_size and asset.file_size > MAX_REFERENCE_BYTES:
            return None
        with asset.file.open("rb") as handle:
            data = handle.read(MAX_REFERENCE_BYTES + 1)
    except (OSError, ValueError) as exc:
        logger.warning("Studio: could not read media asset %s: %s", getattr(asset, "pk", None), exc)
        return None
    return data if data and len(data) <= MAX_REFERENCE_BYTES else None


def brand_defaults(profile) -> dict[str, Any]:
    return {
        "template": profile.default_template,
        "format": profile.default_format,
        "grade": profile.default_grade,
        "picture_style": profile.photo_style,
    }


def _latest_studio_brief(brief):
    from .models import StudioBrief

    return (
        StudioBrief.objects.filter(
            workspace_id=brief.workspace_id,
            status__in=(StudioBrief.Status.READY, StudioBrief.Status.APPROVED),
            graphic__isnull=False,
        )
        .exclude(pk=brief.pk)
        .exclude(design_spec={})
        .select_related("graphic")
        .order_by("-finished_at", "-created_at")
        .first()
    )


def _latest_post(brief, platforms=None):
    from apps.composer.models import Post

    posts = (
        Post.objects.filter(
            workspace_id=brief.workspace_id,
            platform_posts__status__in=OUT_STATUSES,
            media_attachments__media_asset__media_type="image",
        )
        .exclude(studio_briefs__isnull=False)
        .annotate(when=Coalesce("published_at", "scheduled_at", "created_at"))
    )
    if brief.post_id:
        posts = posts.exclude(pk=brief.post_id)
    if platforms:
        posts = posts.filter(platform_posts__social_account__platform__in=platforms)
    return posts.order_by("-when").distinct().first()


def resolve(brief, profile) -> StyleReference:
    """The look ``brief``'s graphic should follow."""
    defaults = brand_defaults(profile)
    if not brief.style_lock:
        return StyleReference(
            kind="free", label="A fresh look: the art director chose freely within the brand.", defaults=defaults
        )

    previous = _latest_studio_brief(brief)
    platforms = sorted({account.platform for account in brief.social_accounts.all()})
    post = _latest_post(brief, platforms) or _latest_post(brief)
    previous_when = (previous.finished_at or previous.created_at) if previous else None
    post_when = getattr(post, "when", None)

    if previous is not None and (post_when is None or (previous_when and previous_when >= post_when)):
        spec = previous.design_spec or {}
        locked = {key: spec[key] for key in LOCKED_KEYS if spec.get(key) not in (None, "")}
        when = previous_when.isoformat() if previous_when else ""
        return StyleReference(
            kind="studio",
            label=f"the last AI Studio post: “{previous.title[:80]}”",
            locked=locked,
            defaults=defaults,
            image=read_asset(previous.graphic),
            brief_id=str(previous.pk),
            asset_id=str(previous.graphic_id or ""),
            when=when,
        )

    if post is not None:
        from . import design

        attachment = (
            post.media_attachments.filter(media_asset__media_type="image")
            .select_related("media_asset")
            .order_by("position")
            .first()
        )
        asset = attachment.media_asset if attachment else None
        image = read_asset(asset)
        if image is not None:
            name = (post.title or post.caption_snippet or "a recent post").strip()
            return StyleReference(
                kind="post",
                label=f"the last post with a picture: “{name[:80]}”",
                defaults=defaults,
                image=image,
                palette=design.dominant_colours(image),
                post_id=str(post.pk),
                asset_id=str(asset.pk) if asset else "",
                when=post_when.isoformat() if post_when else "",
            )

    return StyleReference(
        kind="brand", label="the brand profile's defaults (nothing posted with a picture yet)", defaults=defaults
    )


def preview(workspace) -> dict[str, Any]:
    """What a new brief's graphic would follow, for the brief form: a label and a thumbnail URL."""
    from .models import StudioBrief

    probe = StudioBrief(workspace=workspace, style_lock=True)
    previous = _latest_studio_brief(probe)
    post = _latest_post(probe)
    previous_when = (previous.finished_at or previous.created_at) if previous else None
    post_when = getattr(post, "when", None)
    if previous is not None and (post_when is None or (previous_when and previous_when >= post_when)):
        return {"label": f"the last AI Studio post, “{previous.title[:70]}”", "asset": previous.graphic}
    if post is not None:
        attachment = (
            post.media_attachments.filter(media_asset__media_type="image")
            .select_related("media_asset")
            .order_by("position")
            .first()
        )
        name = (post.title or post.caption_snippet or "a recent post").strip()
        return {
            "label": f"the last post with a picture, “{name[:70]}”",
            "asset": attachment.media_asset if attachment else None,
        }
    return {"label": "the brand profile's look (nothing posted with a picture yet)", "asset": None}


def apply_lock(spec: dict[str, Any], reference: StyleReference) -> dict[str, Any]:
    """``spec`` with the locked look written over whatever the art director chose."""
    if reference.kind != "studio":
        return spec
    return {**spec, **reference.locked}
