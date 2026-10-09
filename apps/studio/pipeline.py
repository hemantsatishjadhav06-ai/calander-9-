"""The producer: runs the creative team on a brief and hands the result to approval.

A brief moves through ten stages, one worker task each, so a single
worker never spends more than one agent's turn away from the publishing
cycle (studio tasks run at a lower priority than publishing):

    strategy → copy → art → picture → render → review → channel → qa → schedule → handoff

* **strategy** — the strategist proposes three angles; the recommended one is chosen.
* **copy** — the copywriter writes the post for the chosen angle.
* **art** — the art director designs the graphic, in the look of the last post
  (``apps.studio.style``) unless the person asked for a fresh one.
* **picture** — the prompt engineer writes the image prompt from the art
  director's direction and the brand's creative memory, and the illustrator
  generates the picture with fal.ai (or uses the photo the person chose, or none).
* **render** — the designer sets the graphic (``apps.studio.design``).
* **review** — the brand reviewer checks facts, rules, craft and consistency.
  It may send the post back once for another pass; after that its notes go to
  the approver instead.
* **channel** — the channel editor writes the versions Instagram, Facebook,
  Threads... need (skipped when every destination takes the copywriter's text).
* **qa** — the QA inspector runs plain checks (lengths, hashtags, links, alt
  text, contrast) and notes anything off for the approver.
* **schedule** — the scheduler proposes the best open time from the account's
  history and posting slots. It only proposes.
* **handoff** — the producer creates (or updates) the composer post with the
  graphic attached and submits it for review. From here the workspace's normal
  approval rules apply: only an approver can approve it, and only an approved
  post can be scheduled or published.

Every agent's turn is an ``AgentRun`` row: the timeline the Studio shows. A
step that fails marks the brief failed with a message for people and stops;
Retry resumes from the failed stage. Each step re-checks that the brief is
still on the same revision before it writes, so a person who requests changes
or discards the brief mid-run is never overwritten by a stale step.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from . import agents, design, guards, images, llm, qa, scheduling, style
from .brand_defaults import ensure_profile
from .models import AgentRun, StudioBrief, StudioConcept

logger = logging.getLogger(__name__)

STAGES = ("strategy", "copy", "art", "picture", "render", "review", "channel", "qa", "schedule", "handoff")
#: Extra passes the brand reviewer may ask for on one revision.
MAX_AUTO_REVISIONS = 1
#: A brief with no progress for this long is assumed abandoned by a dead worker.
STUCK_AFTER = timedelta(minutes=20)
#: django-background-tasks runs higher numbers first; publishing uses 0.
STEP_PRIORITY = -10
#: Composer statuses in which the team may still change the post.
REVISABLE_STATUSES = frozenset({"draft", "pending_review", "changes_requested", "rejected"})
MAX_HASHTAGS = 5

StudioError = llm.StudioAgentError


class _StaleStepError(Exception):
    """The brief moved on (new revision, discarded) while a step was running."""


# ---------------------------------------------------------------------------
# Queueing
# ---------------------------------------------------------------------------


def enqueue(brief: StudioBrief, stage: str) -> None:
    """Queue ``stage`` for ``brief`` once the current transaction commits."""
    from .tasks import run_studio_step

    brief_id, revision = str(brief.pk), brief.revision
    transaction.on_commit(lambda: run_studio_step(brief_id, revision, stage, priority=STEP_PRIORITY))


def start(brief: StudioBrief, stage: str = "strategy") -> None:
    """Put the team to work on ``brief`` from ``stage``."""
    brief.status = StudioBrief.Status.QUEUED
    brief.stage = stage
    brief.error = ""
    brief.save(update_fields=["status", "stage", "error", "updated_at"])
    enqueue(brief, stage)


def _save(brief: StudioBrief, **fields: Any) -> None:
    """Write step results, but only while the brief is still on the step's revision."""
    fields["updated_at"] = timezone.now()
    updated = StudioBrief.objects.filter(
        pk=brief.pk, revision=brief.revision, status=StudioBrief.Status.WORKING
    ).update(**fields)
    if not updated:
        raise _StaleStepError
    for name, value in fields.items():
        setattr(brief, name, value)


def run_step(brief_id: str, revision: int, stage: str) -> None:
    """Run one stage of one brief, then queue the next. Never raises."""
    with transaction.atomic():
        brief = (
            StudioBrief.objects.select_for_update(of=("self",))
            .select_related("workspace", "workspace__organization", "author")
            .filter(pk=brief_id)
            .first()
        )
        if brief is None or brief.revision != revision or brief.stage != stage or not brief.is_active:
            logger.info("Studio: skipping stale step %s for brief %s (r%s)", stage, brief_id, revision)
            return
        brief.status = StudioBrief.Status.WORKING
        brief.started_at = brief.started_at or timezone.now()
        brief.save(update_fields=["status", "started_at", "updated_at"])

    step = STEP_FUNCTIONS[stage]
    try:
        with guards.agent_work(f"brief {brief_id} {stage}"):
            next_stage = step(brief)
    except _StaleStepError:
        logger.info("Studio: brief %s moved on during %s; stopping this run", brief_id, stage)
        AgentRun.objects.filter(brief=brief, revision=revision, status=AgentRun.Status.RUNNING).update(
            status=AgentRun.Status.SKIPPED, error="Superseded by a newer request.", finished_at=timezone.now()
        )
        return
    except StudioError as exc:
        _fail(brief, str(exc))
        return
    except Exception:
        logger.exception("Studio: %s step crashed for brief %s", stage, brief_id)
        label = StudioBrief.Stage(stage).label.lower()
        _fail(brief, f"The {label} hit an unexpected error. Press Retry; if it keeps failing, tell your admin.")
        return

    if next_stage is None:
        return
    with transaction.atomic():
        moved = StudioBrief.objects.filter(pk=brief.pk, revision=revision, status=StudioBrief.Status.WORKING).update(
            stage=next_stage, updated_at=timezone.now()
        )
        if moved:
            brief.stage = next_stage
            enqueue(brief, next_stage)


def _fail(brief: StudioBrief, message: str) -> None:
    StudioBrief.objects.filter(pk=brief.pk, revision=brief.revision).exclude(
        status=StudioBrief.Status.DISCARDED
    ).update(status=StudioBrief.Status.FAILED, error=message[:2000], updated_at=timezone.now())
    AgentRun.objects.filter(brief=brief, status=AgentRun.Status.RUNNING).update(
        status=AgentRun.Status.FAILED, error=message[:2000], finished_at=timezone.now()
    )


def sweep_stuck() -> int:
    """Fail briefs whose worker died between (or during) steps, so they can be retried.

    A queued brief whose task is still in the queue is only waiting its turn
    behind other work, not stuck, and is left alone.
    """
    from .engine import _has_pending_task

    cutoff = timezone.now() - STUCK_AFTER
    stuck = [
        brief
        for brief in StudioBrief.objects.filter(status__in=StudioBrief.ACTIVE_STATUSES, updated_at__lt=cutoff)
        if not (
            brief.status == StudioBrief.Status.QUEUED
            and _has_pending_task("apps.studio.tasks.run_studio_step", str(brief.pk))
        )
    ]
    for brief in stuck:
        _fail(
            brief,
            "The team stopped part-way — the background worker restarted or isn't running. "
            "Press Retry to continue from where it stopped.",
        )
    return len(stuck)


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


def _begin(brief: StudioBrief, agent: str, *, model: str | None = None, effort: str = "") -> AgentRun:
    return AgentRun.objects.create(
        brief=brief,
        workspace_id=brief.workspace_id,
        revision=brief.revision,
        agent=agent,
        stage=brief.stage,
        effort=effort,
        model=llm.model_id() if model is None else model,
    )


def _end(
    run: AgentRun,
    *,
    summary: str,
    output: dict[str, Any] | None = None,
    result: llm.AgentResult | None = None,
    status: str = AgentRun.Status.SUCCEEDED,
    model: str | None = None,
) -> None:
    run.status = status
    run.summary = summary[:500]
    run.output = output or {}
    run.finished_at = timezone.now()
    run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
    fields = ["status", "summary", "output", "finished_at", "duration_ms"]
    if result is not None:
        run.model = result.model
        run.input_tokens = result.input_tokens
        run.output_tokens = result.output_tokens
        run.cache_read_tokens = result.cache_read_tokens
        run.fallback_used = result.fallback_used
        fields += ["model", "input_tokens", "output_tokens", "cache_read_tokens", "fallback_used"]
    elif model is not None:
        run.model = model
        fields.append("model")
    run.save(update_fields=fields)


def _fail_run(run: AgentRun, error: str | Exception) -> None:
    """Close ``run`` as failed, recording what a failed Claude call still cost."""
    run.status = AgentRun.Status.FAILED
    run.error = str(error)[:2000]
    run.finished_at = timezone.now()
    run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
    fields = ["status", "error", "finished_at", "duration_ms"]
    usage = getattr(error, "usage", None)
    if usage:
        run.model, run.input_tokens, run.output_tokens, run.cache_read_tokens = usage
        fields += ["model", "input_tokens", "output_tokens", "cache_read_tokens"]
    run.save(update_fields=fields)


# ---------------------------------------------------------------------------
# Inputs the agents share
# ---------------------------------------------------------------------------


def recent_posts(brief: StudioBrief, limit: int = 6) -> list[dict[str, str]]:
    """The workspace's latest posts, newest first, for voice and to avoid repeating angles."""
    from apps.composer.models import Post

    posts = (
        Post.objects.filter(workspace_id=brief.workspace_id)
        .exclude(caption="")
        .prefetch_related("platform_posts__social_account")
        .order_by("-created_at")
    )
    if brief.post_id:
        posts = posts.exclude(pk=brief.post_id)
    items = []
    for post in posts[:limit]:
        where = ", ".join(sorted({pp.social_account.get_platform_display() for pp in post.platform_posts.all()}))
        when = post.published_at or post.scheduled_at or post.created_at
        items.append(
            {
                "when": timezone.localdate(when).isoformat(),
                "where": where or "draft",
                "text": " ".join(post.caption.split())[:280],
            }
        )
    return items


_TRAILING_TAGS = re.compile(r"(?:\s*(?:#\w+[\s,]*)+)\s*$", re.UNICODE)
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)


def normalise_hashtags(raw: list[str], brand_tags: list[str] | None = None) -> list[str]:
    """At most five ``#Word`` tags, de-duplicated; topped up from the brand's own when fewer than three."""
    tags: list[str] = []

    def add(value) -> None:
        word = re.sub(r"[^\w]", "", str(value).lstrip("#"), flags=re.UNICODE)
        if word and not word.isdigit() and f"#{word}".lower() not in {t.lower() for t in tags}:
            tags.append(f"#{word}")

    for value in raw or []:
        add(value)
    for value in brand_tags or []:
        if len(tags) >= 3:
            break
        add(value)
    return tags[:MAX_HASHTAGS]


def clean_caption(caption: str) -> str:
    """Plain text, no Markdown emphasis, no hashtag block at the end (hashtags are added separately)."""
    text = _BOLD.sub(lambda m: m.group(1) or m.group(2), caption or "")
    text = _TRAILING_TAGS.sub("", text.rstrip())
    lines = [line.rstrip() for line in text.strip().splitlines()]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def full_caption(post_copy: dict[str, Any]) -> str:
    caption = (post_copy.get("caption") or "").strip()
    tags = " ".join(post_copy.get("hashtags") or [])
    return f"{caption}\n\n{tags}" if tags else caption


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def step_strategy(brief: StudioBrief) -> str:
    profile = ensure_profile(brief.workspace)
    run = _begin(brief, AgentRun.Agent.STRATEGIST)
    try:
        result = agents.strategist(brief, profile, recent_posts(brief))
    except StudioError as exc:
        _fail_run(run, exc)
        raise
    answer = result.output
    concepts = [c for c in answer.concepts if c.title.strip() and c.hook.strip()][:3]
    if not concepts:
        _fail_run(run, "No angles came back.")
        raise StudioError("The strategist came back without any angles. Press Retry.")
    recommended = next((index for index, c in enumerate(concepts) if c.recommended), 0)
    created = []
    for position, concept in enumerate(concepts):
        created.append(
            StudioConcept.objects.create(
                brief=brief,
                revision=brief.revision,
                position=position,
                title=concept.title.strip()[:200],
                hook=concept.hook.strip(),
                angle=concept.angle.strip(),
                key_points=[p.strip() for p in concept.key_points if p.strip()][:5],
                post_format=concept.post_format,
                rationale=concept.rationale.strip(),
                recommended=position == recommended,
            )
        )
    chosen = created[recommended]
    _save(brief, chosen_concept=chosen)
    _end(
        run,
        summary=f"Proposed {len(created)} angles and recommends “{chosen.title}”.",
        output=answer.model_dump(),
        result=result,
    )
    return "copy"


def _pending_fixes(brief: StudioBrief) -> dict[str, Any]:
    return (brief.review_notes or {}).get("pending_fixes") or {}


def _feedback(brief: StudioBrief) -> str:
    return brief.feedback if brief.revision > 1 else ""


def step_copy(brief: StudioBrief) -> str:
    profile = ensure_profile(brief.workspace)
    concept = brief.chosen_concept
    if concept is None:
        raise StudioError("There is no chosen angle to write. Ask for new angles.")
    previous = brief.post_copy if (brief.post_copy or {}).get("concept_id") == str(concept.pk) else None
    fixes = _pending_fixes(brief).get("copy") or []
    feedback = _feedback(brief)
    run = _begin(brief, AgentRun.Agent.COPYWRITER)
    try:
        result = agents.copywriter(
            brief,
            profile,
            concept,
            recent_posts(brief),
            previous=previous if (feedback or fixes) else None,
            feedback=feedback,
            fixes=fixes,
        )
    except StudioError as exc:
        _fail_run(run, exc)
        raise
    answer = result.output.model_dump()
    caption = clean_caption(answer["caption"])
    if not caption:
        _fail_run(run, "Empty caption.")
        raise StudioError("The copywriter came back with an empty post. Press Retry.")
    post_copy = {
        **answer,
        "caption": caption,
        "hashtags": normalise_hashtags(answer["hashtags"], profile.hashtags),
        "first_comment": (answer.get("first_comment") or "").strip(),
        "short_caption": (answer.get("short_caption") or "").strip(),
        "concept_id": str(concept.pk),
    }
    _save(brief, post_copy=post_copy)
    revised = bool(previous and (feedback or fixes))
    summary = f"{'Revised' if revised else 'Wrote'} the post: {len(caption)} characters, {len(post_copy['hashtags'])} hashtags."
    if answer.get("notes"):
        summary += f" {answer['notes'].strip()}"
    _end(run, summary=summary, output=post_copy, result=result)
    return "art"


def step_art(brief: StudioBrief) -> str:
    profile = ensure_profile(brief.workspace)
    concept = brief.chosen_concept
    if concept is None:
        raise StudioError("There is no chosen angle to design. Ask for new angles.")
    reference = style.resolve(brief, profile)
    source_picture = style.read_asset(brief.source_picture) if brief.source_picture_id else None
    pending = _pending_fixes(brief)
    feedback = _feedback(brief)
    fixes = pending.get("design") or []
    previous = brief.design_spec or None
    run = _begin(brief, AgentRun.Agent.ART_DIRECTOR)
    try:
        result = agents.art_director(
            brief,
            profile,
            concept,
            brief.post_copy,
            reference,
            source_picture=source_picture,
            previous=previous if (feedback or fixes) else None,
            feedback=feedback,
            fixes=fixes,
        )
    except StudioError as exc:
        _fail_run(run, exc)
        raise
    spec = style.apply_lock(result.output.model_dump(), reference)
    if source_picture is not None:
        spec["use_picture"] = True
        spec["picture_prompt"] = ""
    _save(brief, design_spec=spec, style_reference=reference.as_json())
    look = {"studio": "kept the last post's look", "post": "matched the last post's picture"}.get(
        reference.kind, "set the look from the brand profile" if reference.kind == "brand" else "chose a fresh look"
    )
    _end(
        run,
        summary=f"{spec['template'].title()} layout, {spec['format']}, {spec['grade'].replace('_', ' ')} — {look}.",
        output={**spec, "reference": reference.as_json()},
        result=result,
    )
    return "picture"


def step_picture(brief: StudioBrief) -> str:
    from apps.blog.ai_images import ImageGenerationError
    from apps.media_library.quotas import StorageQuotaExceededError

    spec = dict(brief.design_spec or {})
    run = _begin(brief, AgentRun.Agent.ILLUSTRATOR)
    if brief.source_picture_id:
        _save(brief, picture=brief.source_picture, regenerate_picture=False)
        _end(run, summary="Using the photo you chose.", status=AgentRun.Status.SKIPPED, model="")
        return "render"
    if not spec.get("use_picture"):
        _save(brief, picture=None, regenerate_picture=False)
        _end(run, summary="This design uses no picture.", status=AgentRun.Status.SKIPPED, model="")
        return "render"
    if not images.is_configured():
        _save(brief, picture=None, regenerate_picture=False)
        _end(
            run,
            summary="FAL_KEY isn't set, so the graphic uses the brand background instead of a picture.",
            status=AgentRun.Status.SKIPPED,
            model="",
        )
        return "render"
    current = brief.picture
    keep = current is not None and not brief.regenerate_picture and current.source == "fal.ai"
    if keep:
        _end(run, summary="Kept the current picture.", status=AgentRun.Status.SKIPPED, model="")
        return "render"
    # The illustrator's row was opened first so the timeline reads in order;
    # the prompt engineer's turn is recorded just before it.
    run.delete()
    spec = _engineer_prompt(brief, spec)
    run = _begin(brief, AgentRun.Agent.ILLUSTRATOR, model="")
    try:
        generated = images.generate(spec)
        asset = images.save_picture(brief, generated)
    except (ImageGenerationError, StorageQuotaExceededError) as exc:
        message = str(exc) if isinstance(exc, ImageGenerationError) else "The workspace is out of media storage."
        _fail_run(run, message)
        # A missing picture shouldn't sink the post: the brand background still works.
        _save(brief, picture=None, regenerate_picture=False)
        return "render"
    _save(brief, picture=asset, regenerate_picture=False)
    _end(
        run,
        summary=f"Painted the picture ({asset.width}×{asset.height}).",
        output={"prompt": generated.prompt, "asset_id": str(asset.pk)},
        model=generated.model,
    )
    return "render"


def _engineer_prompt(brief: StudioBrief, spec: dict[str, Any]) -> dict[str, Any]:
    """The prompt engineer's prompt for the picture, or the art director's own when that fails.

    A failed prompt engineer never sinks the post: the art director already
    wrote a usable prompt.
    """
    from . import memory
    from .roles import creative

    profile = ensure_profile(brief.workspace)
    platforms = {a.platform for a in brief.social_accounts.all()}
    run = _begin(brief, AgentRun.Agent.PROMPT_ENGINEER, effort=creative.PROMPT_ENGINEER_EFFORT)
    try:
        result = creative.prompt_engineer(
            profile,
            spec,
            memory.prompt_memory(brief.workspace, platforms=platforms),
            reference_images=memory.reference_images(brief.workspace, platforms=platforms),
        )
    except StudioError as exc:
        _fail_run(run, exc)
        return spec
    answer = result.output
    prompt = " ".join(answer.prompt.split())
    if not prompt:
        _fail_run(run, "Empty prompt.")
        return spec
    engineered = {**spec, "picture_prompt": prompt}
    if (brief.style_reference or {}).get("kind") != "studio" and answer.picture_style.strip():
        engineered["picture_style"] = answer.picture_style.strip()
    _save(brief, design_spec=engineered)
    _end(
        run,
        summary=f"Wrote a {len(prompt.split())}-word picture prompt. {answer.references_used.strip()}".strip(),
        output=answer.model_dump(),
        result=result,
    )
    return engineered


def _look(profile) -> design.Look:
    logo = style.read_asset(profile.logo) if profile.logo_id else None
    return design.Look.from_profile(profile, logo)


def step_render(brief: StudioBrief) -> str:
    from apps.media_library.quotas import StorageQuotaExceededError

    profile = ensure_profile(brief.workspace)
    spec = dict(brief.design_spec or {})
    picture = style.read_asset(brief.picture) if (brief.picture_id and spec.get("use_picture")) else None
    run = _begin(brief, AgentRun.Agent.DESIGNER)
    look = _look(profile)
    try:
        content = design.render(spec, look, picture)
    except ValueError:
        content = design.render(spec, look, None)
    try:
        asset = images.save_graphic(brief, content, (brief.post_copy or {}).get("alt_text", ""))
    except StorageQuotaExceededError as exc:
        _fail_run(run, "Out of storage.")
        raise StudioError(
            "The workspace is out of media storage. Delete unused media or ask your admin to raise the limit."
        ) from exc
    _save(brief, graphic=asset)
    normalised = design.normalise_spec(spec, look)
    _end(
        run,
        summary=f"Set the graphic: {asset.width}×{asset.height}, {normalised['template']} layout.",
        output={"asset_id": str(asset.pk), "width": asset.width, "height": asset.height, **normalised},
        model="",
    )
    return "review"


def _reference_image(brief: StudioBrief) -> bytes | None:
    from apps.media_library.models import MediaAsset

    asset_id = (brief.style_reference or {}).get("asset_id")
    if not asset_id:
        return None
    asset = MediaAsset.objects.filter(pk=asset_id, workspace_id=brief.workspace_id).first()
    return style.read_asset(asset)


def step_review(brief: StudioBrief) -> str:
    profile = ensure_profile(brief.workspace)
    graphic = style.read_asset(brief.graphic) if brief.graphic_id else None
    if graphic is None:
        raise StudioError("The graphic couldn't be read back from storage. Press Retry.")
    run = _begin(brief, AgentRun.Agent.REVIEWER)
    try:
        result = agents.reviewer(brief, profile, brief.post_copy, brief.design_spec, graphic, _reference_image(brief))
    except StudioError as exc:
        _fail_run(run, exc)
        raise
    review = result.output.model_dump()
    review["score"] = max(1, min(10, int(review.get("score") or 0)))
    copy_fixes = [fix for fix in review.get("copy_fixes") or [] if fix.strip()]
    design_fixes = [fix for fix in review.get("design_fixes") or [] if fix.strip()]
    wants_pass = review["verdict"] == "revise" and (copy_fixes or design_fixes or review["regenerate_picture"])
    if wants_pass and brief.auto_revisions < MAX_AUTO_REVISIONS:
        review["pending_fixes"] = {"copy": copy_fixes, "design": design_fixes}
        _save(
            brief,
            review_notes=review,
            auto_revisions=brief.auto_revisions + 1,
            regenerate_picture=bool(review["regenerate_picture"]),
        )
        _end(
            run,
            summary=f"Scored {review['score']}/10 and sent it back for one more pass: {review['summary']}",
            output=review,
            result=result,
        )
        return "copy" if copy_fixes else "art"
    _save(brief, review_notes=review)
    verdict = "approves" if review["verdict"] == "approve" else "has notes for the approver"
    _end(run, summary=f"Scored {review['score']}/10 and {verdict}. {review['summary']}", output=review, result=result)
    return "channel"


def step_channel(brief: StudioBrief) -> str:
    """Per-network versions for destinations the copywriter's text doesn't fit."""
    from .roles import creative

    post_copy = dict(brief.post_copy or {})
    accounts = [a for a in brief.social_accounts.all() if not a.needs_reconnect]
    others = [a for a in accounts if a.platform not in creative.COPYWRITER_PLATFORMS]
    run = _begin(brief, AgentRun.Agent.CHANNEL_EDITOR, effort=creative.CHANNEL_EDITOR_EFFORT)
    if not others:
        if post_copy.get("channels"):
            post_copy.pop("channels")
            _save(brief, post_copy=post_copy)
        _end(
            run,
            summary="Every destination takes the copywriter's text as it is.",
            status=AgentRun.Status.SKIPPED,
            model="",
        )
        return "qa"
    destinations = [{"platform": a.platform, "name": a.account_name or a.get_platform_display()} for a in others]
    profile = ensure_profile(brief.workspace)
    try:
        result = creative.channel_editor(profile, post_copy, destinations)
    except StudioError as exc:
        # The copywriter's text still works everywhere (cut to the short version where too long).
        _fail_run(run, exc)
        return "qa"
    wanted = {d["platform"] for d in destinations}
    channels = {
        v.platform: clean_caption(v.caption)
        if v.platform not in ("instagram", "instagram_login")
        else v.caption.strip()
        for v in result.output.versions
        if v.platform in wanted and v.caption.strip()
    }
    post_copy["channels"] = channels
    _save(brief, post_copy=post_copy)
    names = ", ".join(sorted({d["name"] for d in destinations if d["platform"] in channels})) or "none"
    _end(
        run,
        summary=f"Wrote versions for {names}. {result.output.notes.strip()}".strip(),
        output={"channels": channels},
        result=result,
    )
    return "qa"


def step_qa(brief: StudioBrief) -> str:
    profile = ensure_profile(brief.workspace)
    accounts = [a for a in brief.social_accounts.all() if not a.needs_reconnect]
    run = _begin(brief, AgentRun.Agent.QA_INSPECTOR, model="")
    report = qa.inspect(brief.post_copy or {}, brief.design_spec or {}, accounts, _look(profile))
    _save(brief, review_notes={**(brief.review_notes or {}), "qa": report})
    notes = [c["name"] for c in report["checks"] if not c["passed"]]
    summary = f"{report['passed']} of {report['total']} checks pass."
    if notes:
        summary += " Note for you: " + "; ".join(notes) + "."
    _end(run, summary=summary, output=report, model="")
    return "schedule"


def step_schedule(brief: StudioBrief) -> str:
    accounts = [a for a in brief.social_accounts.all() if not a.needs_reconnect]
    run = _begin(brief, AgentRun.Agent.SCHEDULER, model="")
    if brief.proposed_publish_at and brief.proposed_publish_at > timezone.now() + scheduling.LEAD_TIME:
        local = timezone.localtime(brief.proposed_publish_at, scheduling._zone(brief.workspace))
        _end(run, summary=f"Keeping the planned time: {local:%a %d %b, %H:%M}.", model="")
        return "handoff"
    proposal = scheduling.propose(brief.workspace, accounts, exclude_brief=brief, exclude_post_id=brief.post_id)
    _save(brief, proposed_publish_at=proposal.when)
    _end(run, summary=f"Proposed {proposal.reason}", output={"when": proposal.when.isoformat()}, model="")
    return "handoff"


# ---------------------------------------------------------------------------
# Hand-off to the composer and the approval workflow
# ---------------------------------------------------------------------------


def propose_time(brief: StudioBrief, accounts) -> Any:
    """The scheduler's proposal: the best open posting slot, else the next weekday at 10:00 local time."""
    return scheduling.propose(brief.workspace, accounts, exclude_brief=brief, exclude_post_id=brief.post_id).when


def account_overrides(account, caption: str, post_copy: dict[str, Any]) -> tuple[str | None, str | None]:
    """``(caption override, first comment override)`` for one destination.

    The channel editor's version replaces the caption where there is one.
    Where the account can't take a first comment, its text (usually the link)
    moves into the caption so it isn't lost. Where the caption is over the
    network's limit (X, Threads), the short version is used instead.
    """
    first_comment = (post_copy.get("first_comment") or "").strip()
    original = caption
    # The channel editor's version for this network, when there is one.
    channel_text = ((post_copy.get("channels") or {}).get(account.platform) or "").strip()
    if channel_text:
        caption = channel_text
    text = caption
    comment_override = None
    if first_comment and not account.supports_first_comment():
        text = f"{caption}\n\n{first_comment}"
        comment_override = ""
    if account.caption_wire_length(text) > account.char_limit:
        short = (post_copy.get("short_caption") or "").strip()
        if short:
            text = short
    return (None if text == original else text), comment_override


def _internal_notes(brief: StudioBrief) -> str:
    concept = brief.chosen_concept
    review = brief.review_notes or {}
    lines = [f"Made in the AI Studio from the idea: {brief.idea.strip()[:500]}"]
    if concept is not None:
        lines.append(f"Angle: {concept.title}")
    if review.get("score"):
        lines.append(f"Brand reviewer: {review['score']}/10 — {review.get('summary', '')}".strip())
    flags = review.get("risk_flags") or []
    if flags:
        lines.append("Check before approving: " + "; ".join(flags))
    return "\n".join(lines)


def step_handoff(brief: StudioBrief) -> None:
    from apps.approvals import services as approval_services
    from apps.composer.models import PlatformPost, Post, PostMedia
    from apps.composer.views import _save_version

    if brief.author is None:
        raise StudioError("The person who started this brief no longer has an account here.")
    graphic = brief.graphic
    if graphic is None:
        raise StudioError("There is no graphic to attach. Press Retry.")
    accounts = [a for a in brief.social_accounts.all() if not a.needs_reconnect]
    if not accounts:
        raise StudioError(
            "None of the chosen accounts is connected right now. Reconnect it under Settings → Social accounts, "
            "then press Retry."
        )
    run = _begin(brief, AgentRun.Agent.PRODUCER)
    post_copy = brief.post_copy or {}
    caption = full_caption(post_copy)
    first_comment = (post_copy.get("first_comment") or "").strip()
    title = (brief.design_spec or {}).get("headline") or post_copy.get("headline") or brief.idea[:120]
    proposed = brief.proposed_publish_at or propose_time(brief, accounts)

    with transaction.atomic():
        post = Post.objects.select_for_update().filter(pk=brief.post_id).first() if brief.post_id else None
        if post is not None:
            statuses = set(post.platform_posts.values_list("status", flat=True))
            if statuses - REVISABLE_STATUSES:
                _fail_run(run, "Post already approved or scheduled.")
                raise StudioError(
                    "This post was already approved or scheduled, so the team can't change it. "
                    "Edit it in the composer instead."
                )
            post.title = title[:255]
            post.caption = caption
            post.first_comment = first_comment
            post.internal_notes = _internal_notes(brief)
            post.proposed_publish_at = proposed
            post.save(
                update_fields=[
                    "title",
                    "caption",
                    "first_comment",
                    "internal_notes",
                    "proposed_publish_at",
                    "updated_at",
                ]
            )
            post.media_attachments.all().delete()
        else:
            post = Post.objects.create(
                workspace=brief.workspace,
                author=brief.author,
                title=title[:255],
                caption=caption,
                first_comment=first_comment,
                internal_notes=_internal_notes(brief),
                tags=["ai-studio"],
                proposed_publish_at=proposed,
            )
        PostMedia.objects.create(
            post=post, media_asset=graphic, position=0, alt_text=(post_copy.get("alt_text") or "")[:1000]
        )
        existing = {pp.social_account_id: pp for pp in post.platform_posts.all()}
        for account in accounts:
            caption_override, comment_override = account_overrides(account, caption, post_copy)
            pp = existing.pop(account.pk, None)
            if pp is None:
                PlatformPost.objects.create(
                    post=post,
                    social_account=account,
                    status=PlatformPost.Status.DRAFT,
                    platform_specific_caption=caption_override,
                    platform_specific_first_comment=comment_override,
                )
            else:
                pp.platform_specific_caption = caption_override
                pp.platform_specific_first_comment = comment_override
                pp.save(update_fields=["platform_specific_caption", "platform_specific_first_comment", "updated_at"])
        for pp in existing.values():
            if pp.status in REVISABLE_STATUSES:
                pp.delete()
        _save_version(post, brief.author)
        _save(
            brief,
            post=post,
            proposed_publish_at=proposed,
            status=StudioBrief.Status.READY,
            stage=StudioBrief.Stage.DONE,
            finished_at=timezone.now(),
        )

    if post.platform_posts.filter(status__in=("draft", "changes_requested", "rejected")).exists():
        approval_services.submit_for_review(post, brief.author, brief.workspace)
    _notify_author(brief, post)
    names = ", ".join(sorted({a.account_name or a.get_platform_display() for a in accounts}))
    _end(run, summary=f"Sent it for approval as a draft for {names}.", output={"post_id": str(post.pk)}, model="")


def _notify_author(brief: StudioBrief, post) -> None:
    try:
        from apps.notifications.engine import notify
        from apps.notifications.models import EventType

        notify(
            user=brief.author,
            event_type=EventType.POST_SUBMITTED,
            title="Your AI Studio post is ready for approval",
            body=f"The team turned “{brief.idea.strip()[:80]}” into a post and sent it for approval.",
            data={"post_id": str(post.pk), "workspace_id": str(brief.workspace_id), "studio_brief_id": str(brief.pk)},
        )
    except Exception:
        logger.exception("Studio: could not notify the author of brief %s", brief.pk)


STEP_FUNCTIONS = {
    "strategy": step_strategy,
    "copy": step_copy,
    "art": step_art,
    "picture": step_picture,
    "render": step_render,
    "review": step_review,
    "channel": step_channel,
    "qa": step_qa,
    "schedule": step_schedule,
    "handoff": step_handoff,
}
