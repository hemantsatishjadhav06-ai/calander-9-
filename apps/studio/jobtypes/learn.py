"""The ``learn`` job: keep creative memory fresh (``apps.studio.memory`` is the read side).

Two stages:

1. **rank** (code): every published post of the workspace that has a picture
   and a measured result becomes a :class:`~apps.studio.models.CreativeInsight`
   row — its percentile among its own account's posts (``score``), its ratio to
   that account's median, the metric it was measured on, its caption, and, for
   posts the Studio made, the design behind it (layout, colour treatment,
   picture style and the picture prompt). Rows a person marked as a reference
   keep that mark; rows of posts that aged out of the look-back window go,
   unless they are references.
2. **describe** (the creative memory curator, Claude vision): the top
   best-performers and every reference that has no description yet are shown
   to the curator, downscaled, and it writes one line on each one's look plus
   the house-style paragraph the art director and prompt engineer start from.

Who wrote the house style — a rule, documented here because two writers share
one field (``BrandProfile.house_style``): the curator, after each refresh, and
a person, on the creative memory page. Each finished learn job records the
exact text the curator wrote (``result["house_style_written"]``, carried
forward by later jobs). The curator may write the house style when

* it is empty, or
* it is still exactly the text the curator last wrote, or
* a person last saved it more than :data:`PERSON_EDIT_HOLD` (30 days) ago —
  ``house_style_updated_at``, which the memory page sets when a person saves
  a changed text (empty means no person edit is on record).

Otherwise a person wrote it recently: the curator leaves it alone, says so on
its timeline row, and still describes the creatives.

Nothing here approves, schedules or publishes; the only writes are the
workspace's own creative memory rows and its brand profile's house style.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.utils import timezone

from .. import budget, engine, performance
from ..models import AgencyJob, AgentRun, BrandProfile, CreativeInsight
from ..roles import insights

logger = logging.getLogger(__name__)

#: Best performers the curator looks at per refresh (references come on top).
TOP_FOR_CURATOR = 8
#: Undescribed references shown per refresh; the rest wait for the next one.
#: A cost guard: each image is roughly 800 input tokens at 768px.
MAX_REFERENCES = 12
#: How long the curator leaves a house style a person wrote.
PERSON_EDIT_HOLD = timedelta(days=30)


def _first_images(post_ids) -> dict[Any, Any]:
    """``{post_id: MediaAsset}`` — each post's first picture, by position."""
    from apps.composer.models import PostMedia
    from apps.media_library.models import MediaAsset

    firsts: dict[Any, Any] = {}
    rows = (
        PostMedia.objects.filter(post_id__in=list(post_ids), media_asset__media_type=MediaAsset.MediaType.IMAGE)
        .select_related("media_asset")
        .order_by("post_id", "position", "pk")
    )
    for row in rows:
        firsts.setdefault(row.post_id, row.media_asset)
    return firsts


def _studio_designs(workspace, post_ids) -> dict[Any, dict[str, Any]]:
    """``{post_id: features}`` from the newest Studio brief behind each post."""
    from ..models import StudioBrief

    designs: dict[Any, dict[str, Any]] = {}
    briefs = (
        StudioBrief.objects.filter(workspace=workspace, post_id__in=list(post_ids))
        .select_related("chosen_concept")
        .order_by("-created_at")
    )
    for brief in briefs:
        if brief.post_id in designs:
            continue
        spec = brief.design_spec or {}
        designs[brief.post_id] = {
            "template": spec.get("template", ""),
            "canvas": spec.get("format", ""),
            "grade": spec.get("grade", ""),
            "picture_style": spec.get("picture_style", ""),
            "picture_prompt": spec.get("picture_prompt", ""),
            "post_format": brief.chosen_concept.post_format if brief.chosen_concept else "",
        }
    return designs


def stage_rank(job: AgencyJob) -> str:
    """Upsert a CreativeInsight per measured, pictured post of this workspace."""
    from apps.composer.models import PlatformPost

    workspace = job.workspace
    run = engine.begin(job, "performance_analyst", stage="rank")
    items = performance.measured(workspace=workspace)
    pps: dict[Any, Any] = {
        pp.pk: pp
        for pp in PlatformPost.objects.filter(
            pk__in=[m.platform_post_id for m in items], post__workspace=workspace
        ).select_related("post")
    }
    post_ids = {pp.post_id for pp in pps.values()}
    images = _first_images(post_ids)
    designs = _studio_designs(workspace, post_ids)

    ranked = scored = 0
    for item in items:
        pp = pps.get(item.platform_post_id)
        asset = images.get(item.post_id)
        if pp is None or asset is None:
            continue  # another workspace's row can't get here, and a post without a picture teaches no look
        caption = (pp.platform_specific_caption or pp.post.caption or "").strip()
        design = designs.get(item.post_id)
        features = dict(design) if design else {}
        features.update(
            {
                "caption_length": len(caption),
                "hashtags": caption.count("#"),
                "hook": (caption.splitlines() or [""])[0][:200],
            }
        )
        defaults = {
            "post_id": item.post_id,
            "social_account_id": item.account_id,
            "platform": item.platform,
            "source": CreativeInsight.Source.STUDIO if design else CreativeInsight.Source.EXTERNAL,
            "score": item.percentile,
            "ratio": item.ratio,
            "metrics": {"metric": item.metric, "value": item.value},
            "features": features,
            "caption": caption[:4000],
            "published_at": item.published_at,
        }
        insight = CreativeInsight.objects.filter(workspace=workspace, platform_post_id=pp.pk).first()
        if insight is None:
            CreativeInsight.objects.create(workspace=workspace, platform_post_id=pp.pk, media_asset=asset, **defaults)
        else:
            if insight.media_asset_id != asset.pk:
                # A different picture: the old description no longer applies.
                defaults.update({"media_asset": asset, "description": "", "described_at": None})
            for name, value in defaults.items():
                setattr(insight, name, value)
            # Only the ranked fields: a person marking this creative as a reference at the
            # same moment (is_reference, reference_note) must not be overwritten.
            fields = [name.removesuffix("_id") for name in defaults] + ["computed_at"]
            insight.save(update_fields=fields)
        ranked += 1
        scored += item.percentile is not None

    aged_out = CreativeInsight.objects.filter(
        workspace=workspace,
        is_reference=False,
        platform_post__isnull=False,
        published_at__lt=timezone.now() - performance.LOOKBACK,
    ).delete()[0]
    engine.update_state(job, ranked=ranked, scored=scored)
    if ranked:
        summary = (
            f"Ranked {ranked} published post(s) with a picture against their own account's usual result"
            f" ({scored} with enough history to score)."
        )
    else:
        summary = "No published posts with a picture and results yet; working from your references."
    engine.end(run, summary=summary, output={"ranked": ranked, "scored": scored, "aged_out": aged_out})
    return "describe"


# ---------------------------------------------------------------------------
# The curator
# ---------------------------------------------------------------------------


def last_curator_text(workspace) -> str | None:
    """The house style the curator last wrote here, or None when it never has."""
    rows = AgencyJob.objects.filter(
        workspace=workspace, kind=AgencyJob.Kind.LEARN, status=AgencyJob.Status.DONE
    ).order_by("-finished_at", "-created_at")
    for result in rows.values_list("result", flat=True)[:20]:
        if isinstance(result, dict) and "house_style_written" in result:
            return str(result["house_style_written"] or "")
    return None


def person_holds_house_style(profile, now=None) -> bool:
    """True while a house style a person wrote is protected from the curator (see the module docstring)."""
    current = (profile.house_style or "").strip()
    if not current:
        return False
    if current == (last_curator_text(profile.workspace) or "").strip():
        return False
    edited = profile.house_style_updated_at
    return edited is not None and edited > (now or timezone.now()) - PERSON_EDIT_HOLD


def _context(insight: CreativeInsight) -> str:
    if insight.is_reference:
        note = f" Note from the team: {insight.reference_note}" if insight.reference_note else ""
        return f"A reference the team picked as their best designer's work.{note}"
    where = insight.platform.replace("_", " ") or "its network"
    if insight.ratio:
        return f"A published post that did {insight.ratio:.1f}× its account's usual result on {where}."
    return f"A published post on {where}."


def _candidates(workspace) -> tuple[list[CreativeInsight], list[CreativeInsight]]:
    """``(to show, already described)`` — undescribed references and top performers, then the rest of the top."""
    references = list(
        CreativeInsight.objects.filter(workspace=workspace, is_reference=True, media_asset__isnull=False)
        .select_related("media_asset")
        .order_by("-created_at")
    )
    top = list(
        CreativeInsight.objects.filter(
            workspace=workspace, is_reference=False, score__isnull=False, media_asset__isnull=False
        )
        .select_related("media_asset")
        .order_by("-score", "-published_at")[:TOP_FOR_CURATOR]
    )
    show = [i for i in references if not i.description][:MAX_REFERENCES] + [i for i in top if not i.description]
    described = [i for i in references + top if i.description]
    return show, described


def _viewable(content: bytes) -> bool:
    """True when ``content`` is an image Pillow can open (what ``llm.image_block`` needs)."""
    import io

    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return False
    return True


def learned_lines(workspace, notes: str = "") -> list[str]:
    """A few plain lines for the agency home's "What the team learned" (``dashboard.learned``)."""
    lines = []
    best = (
        CreativeInsight.objects.filter(workspace=workspace, is_reference=False, ratio__isnull=False)
        .order_by("-ratio", "-published_at")
        .first()
    )
    if best is not None and best.ratio and best.ratio >= 1.2:
        from ..reports import network_name

        lines.append(
            f"Your strongest recent post did {best.ratio:.1f}× its account's usual on {network_name(best.platform)}."
        )
    notes = " ".join((notes or "").split())
    if notes:
        lines.append(notes[:300])
    return lines


def stage_describe(job: AgencyJob) -> None:
    """The curator describes new creatives and rewrites the house style (unless a person holds it)."""
    from ..brand_defaults import ensure_profile
    from ..style import read_asset

    workspace = job.workspace
    profile = ensure_profile(workspace)
    show, described = _candidates(workspace)
    images: list[dict[str, Any]] = []
    by_key: dict[str, CreativeInsight] = {}
    for insight in show:
        content = read_asset(insight.media_asset)
        if not content or not _viewable(content):
            continue  # a missing or broken file is skipped, not sent (and not billed)
        key = f"img{len(images) + 1}"
        images.append({"key": key, "content": content, "context": _context(insight)})
        by_key[key] = insight

    previous = last_curator_text(workspace)
    carried = {"house_style_written": previous} if previous is not None else {}
    state = job.state or {}
    base_result = {"ranked": state.get("ranked", 0), "scored": state.get("scored", 0), **carried}

    needs_house_style = not (profile.house_style or "").strip() and bool(described)
    if not images and not needs_house_style:
        run = engine.begin(job, "creative_curator", stage="describe")
        engine.end(run, summary="Nothing new to look at since the last refresh.", status=AgentRun.Status.SKIPPED)
        engine.finish(job, result={**base_result, "described": 0, "house_style_updated": False})
        return None
    if not budget.can_spend(workspace):
        run = engine.begin(job, "creative_curator", stage="describe")
        engine.end(run, summary=budget.over_budget_message(workspace), status=AgentRun.Status.SKIPPED)
        engine.finish(job, result={**base_result, "described": 0, "house_style_updated": False})
        return None

    run, result = engine.call(
        job,
        "creative_curator",
        lambda: insights.creative_curator(
            profile,
            images,
            described=[f"{_context(i)} {i.description}" for i in described][:12],
            current_house_style=profile.house_style or "",
        ),
        stage="describe",
        effort=insights.CREATIVE_CURATOR_EFFORT,
    )
    answer = result.output
    now = timezone.now()
    # Revision-guarded: a refresh someone cancelled during the call writes nothing.
    engine.update_state(job, described_at=now.isoformat())
    written = 0
    for look in answer.images:
        shown = by_key.get(look.key.strip())
        text = " ".join((look.look or "").split())[:1000]
        if shown is None or not text:
            continue  # keys come from this run's own listing; anything else is ignored
        CreativeInsight.objects.filter(pk=shown.pk, workspace=workspace).update(description=text, described_at=now)
        written += 1

    house_style = " ".join((answer.house_style or "").split())[:1500]
    updated = False
    if house_style and not person_holds_house_style(profile, now):
        # Compare-and-swap: a person saving at the same moment wins.
        updated = bool(
            BrandProfile.objects.filter(pk=profile.pk, house_style=profile.house_style).update(
                house_style=house_style, house_style_updated_at=now
            )
        )
    kept = bool(house_style) and not updated
    summary = f"Described {written} creative(s)" + (
        "; rewrote the house style." if updated else "; kept the house style a person wrote." if kept else "."
    )
    engine.end(
        run,
        summary=summary,
        output={"described": written, "house_style_updated": updated, "notes": answer.notes[:500]},
        result=result,
    )
    final = {
        **base_result,
        "described": written,
        "house_style_updated": updated,
        "learned": learned_lines(workspace, answer.notes),
    }
    if updated:
        final["house_style_written"] = house_style
    engine.finish(job, result=final)
    return None


JOB = engine.JobType(
    kind="learn",
    stages=(
        engine.Stage("rank", "performance_analyst", stage_rank),
        engine.Stage("describe", "creative_curator", stage_describe),
    ),
    priority=engine.PRIORITY_BACKGROUND,
    stuck_after=timedelta(minutes=45),
)
