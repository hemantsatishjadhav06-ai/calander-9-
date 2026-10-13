"""Fault-injected publication review and paid-stage boundaries for Neopolis.

Providers are replaced by the schema-valid fake team. These tests inspect the
actual outbound content and persisted workflow states, not factual truth in
external property sources or the quality of a live model's judgement.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.composer.models import PlatformPost, Post
from apps.social_accounts.models import SocialAccount
from apps.studio import agents, autopilot, llm, pipeline
from apps.studio.models import AgencyJob, AgencySettings, AgentRun, StudioBrief
from apps.studio.roles import creative
from apps.studio.tests.conftest import _result, jpeg_bytes, make_brief, review_answer, run_all


def _destination(world, platform="instagram", account_id="launch-ig"):
    return SocialAccount.objects.create(
        workspace=world.workspace,
        platform=platform,
        account_platform_id=account_id,
        account_name="Neopolis Infra",
        oauth_access_token="fake-token",
    )


def _capture_reviews(monkeypatch, fake_team, decide=None):
    reviewed = []

    def reviewer(brief, profile, post_copy, spec, graphic, reference_image=None):
        reviewed.append(deepcopy(post_copy["_publication_payload"]))
        result = fake_team.__class__.reviewer(fake_team, brief, profile, post_copy, spec, graphic, reference_image)
        return replace(result, output=decide(reviewed[-1])) if decide else result

    monkeypatch.setattr(agents, "reviewer", reviewer)
    return reviewed


def _channel(monkeypatch, caption, *, platform="instagram"):
    monkeypatch.setattr(
        creative,
        "channel_editor",
        lambda *_: _result(
            creative.ChannelAnswer(
                versions=[creative.ChannelVersion(platform=platform, caption=caption)],
                notes="Injected platform version for a launch regression.",
            )
        ),
    )


def _until(brief, stage):
    for _ in range(30):
        brief.refresh_from_db()
        if brief.stage == stage:
            assert brief.status == StudioBrief.Status.QUEUED
            return brief
        assert brief.is_active, brief.error
        pipeline.run_step(str(brief.pk), brief.revision, brief.stage)
    raise AssertionError(f"The pipeline never reached {stage}")


@pytest.mark.parametrize(
    "claim",
    [
        "Book now at a fixed price of ₹50 lakh.",
        "RERA registration P02400099999 is verified.",
        "Neopolis guarantees 20% annual returns.",
        "Call More Space at +91 12345 67890 for this Neopolis flat.",
    ],
)
def test_new_channel_claim_is_reviewed_and_held_after_one_correction(world, fake_team, monkeypatch, claim):
    destination = _destination(world)
    _channel(monkeypatch, "Understand the allocation before buying. " + claim)

    def decision(payload):
        if any(claim in row["caption"] for row in payload):
            return review_answer(
                "revise",
                risk_flags=[f"Unsupported channel claim: {claim}"],
                copy_fixes=[f"Remove the unsupported claim: {claim}"],
            )
        return review_answer()

    reviewed = _capture_reviews(monkeypatch, fake_team, decision)
    brief = run_all(make_brief(world, accounts=[world.linkedin, destination]))

    assert brief.status == StudioBrief.Status.FAILED and brief.stage == "qa"
    assert brief.auto_revisions == 1 and len(fake_team.calls["copywriter"]) == 2
    assert claim not in reviewed[0][-1]["caption"]
    assert any(claim in row["caption"] for payload in reviewed[1:] for row in payload)
    assert "Unsupported channel claim" in brief.error
    assert brief.post_id is None and not Post.objects.filter(workspace=world.workspace).exists()
    assert not PlatformPost.objects.filter(social_account=destination).exists()


def test_claim_near_end_of_long_final_caption_reaches_model_and_holds(world, fake_team, monkeypatch):
    destination = _destination(world, "facebook", "launch-fb")
    claim = "Guaranteed 25% return without risk."
    caption = "A calm view of the allocation process. " * 190 + claim
    assert 6000 < len(caption) < destination.char_limit
    _channel(monkeypatch, caption, platform="facebook")
    prompt_calls = []

    def run_agent(**kwargs):
        prompt_calls.append(kwargs)
        text = "\n".join(block.get("text", "") for block in kwargs["content"])
        answer = (
            review_answer("revise", risk_flags=[claim], copy_fixes=["Remove the unsupported guarantee."])
            if claim in text
            else review_answer()
        )
        return _result(answer)

    monkeypatch.setattr(llm, "run_agent", run_agent)
    # Exercise the real reviewer prompt, not only its monkeypatched API input.
    monkeypatch.setattr(agents, "reviewer", _REAL_REVIEWER)
    brief = run_all(make_brief(world, accounts=[destination]))
    final_prompts = [
        "\n".join(block.get("text", "") for block in call["content"])
        for call in prompt_calls
        if any(claim in block.get("text", "") for block in call["content"])
    ]

    assert final_prompts and all(caption in text for text in final_prompts)
    assert brief.status == StudioBrief.Status.FAILED and brief.post is None
    assert brief.auto_revisions == 1 and claim in brief.error


# Save the real prompt-building callable before fake_team replaces the module.
_REAL_REVIEWER = agents.reviewer


def test_unchanged_outbound_text_reuses_one_review_and_matches_saved_content(world, fake_team, monkeypatch):
    reviewed = _capture_reviews(monkeypatch, fake_team)
    brief = run_all(make_brief(world, accounts=[world.linkedin, world.x]))

    assert brief.status == StudioBrief.Status.READY
    assert len(reviewed) == len(fake_team.calls["reviewer"]) == 1
    assert brief.runs.filter(agent=AgentRun.Agent.REVIEWER).count() == 1
    rows = {row["account_id"]: row for row in reviewed[0]}
    for platform_post in brief.post.platform_posts.select_related("social_account"):
        row = rows[str(platform_post.social_account_id)]
        assert platform_post.effective_caption == row["caption"]
        assert platform_post.effective_first_comment == row["first_comment"]
        assert platform_post.status == PlatformPost.Status.PENDING_REVIEW
        assert platform_post.scheduled_at is None
    assert any(check["name"] == "Final publication content reviewed" for check in brief.review_notes["qa"]["checks"])


def test_short_caption_fallback_and_oidc_comment_are_reviewed_before_handoff(world, fake_team, monkeypatch):
    personal = _destination(world, "linkedin_personal", "personal-launch")
    monkeypatch.setattr(
        "apps.publisher.engine._resolve_publish_credentials",
        lambda account: {"_oauth_mode": "oidc"} if account.platform == "linkedin_personal" else {},
    )
    fake_team.copy = {"caption": "The allocation explained. " * 40}
    reviewed = _capture_reviews(monkeypatch, fake_team)
    brief = run_all(make_brief(world, accounts=[world.linkedin, world.x, personal]))

    assert brief.status == StudioBrief.Status.READY and len(reviewed) == 1
    rows = {row["platform"]: row for row in reviewed[0]}
    assert rows["x"]["caption"] == brief.post_copy["short_caption"]
    assert rows["x"]["first_comment"] == ""
    assert rows["linkedin_personal"]["caption"].endswith(brief.post_copy["first_comment"])
    assert rows["linkedin_personal"]["first_comment"] == ""


def test_first_comment_unsupported_claim_is_part_of_review(world, fake_team, monkeypatch):
    claim = "RERA P02400099999; guaranteed 15% return."
    fake_team.copy = {"first_comment": claim}
    reviewed = _capture_reviews(
        monkeypatch,
        fake_team,
        lambda payload: (
            review_answer("revise", risk_flags=[claim], copy_fixes=["Remove the unsupported claims."])
            if any(claim in row["first_comment"] or claim in row["caption"] for row in payload)
            else review_answer()
        ),
    )
    brief = run_all(make_brief(world, accounts=[world.linkedin, world.x]))

    assert any(row["first_comment"] == claim for row in reviewed[0])
    assert any(claim in row["caption"] for row in reviewed[0])
    assert brief.status == StudioBrief.Status.FAILED and brief.post is None


@pytest.mark.parametrize("change", ["caption", "first_comment", "graphic", "account", "revision"])
def test_changed_review_evidence_cannot_reach_handoff(world, fake_team, photo, change):
    brief = _until(make_brief(world), "handoff")
    if change in ("caption", "first_comment"):
        post_copy = {**brief.post_copy, change: "Unreviewed guaranteed return claim."}
        StudioBrief.objects.filter(pk=brief.pk).update(post_copy=post_copy)
    elif change == "graphic":
        graphic = brief.graphic
        graphic.file.save("changed-after-review.jpg", ContentFile(jpeg_bytes(color=(200, 0, 0))), save=True)
    elif change == "account":
        SocialAccount.objects.filter(pk=world.linkedin.pk).update(account_platform_id="another-company-page")
    else:
        StudioBrief.objects.filter(pk=brief.pk).update(revision=brief.revision + 1)
    brief.refresh_from_db()
    pipeline.run_step(str(brief.pk), brief.revision, "handoff")
    brief.refresh_from_db()

    assert brief.status == StudioBrief.Status.FAILED and brief.post_id is None
    if change == "revision":
        assert "source review" in brief.error and "another revision" in brief.error
    else:
        assert "changed after review" in brief.error
    assert brief.runs.filter(agent=AgentRun.Agent.PRODUCER).count() == 0


def test_oversized_final_text_is_held_before_extra_paid_review(world, fake_team, monkeypatch):
    destination = _destination(world, "facebook", "large-fb")
    _channel(monkeypatch, "Allocation details. " * 1400, platform="facebook")
    reviewed = _capture_reviews(monkeypatch, fake_team)
    brief = run_all(make_brief(world, accounts=[destination]))

    assert brief.status == StudioBrief.Status.FAILED and brief.stage == "qa"
    assert "too long for one complete review" in brief.error
    assert len(reviewed) == 1 and brief.post_id is None


def test_failed_final_review_holds_handoff_and_records_bill(world, fake_team, monkeypatch):
    destination = _destination(world)
    _channel(monkeypatch, "The allocation process, explained for first-time buyers.")
    calls = []

    def reviewer(*args, **kwargs):
        calls.append(args[2]["_publication_payload"])
        if len(calls) > 1:
            raise llm.StudioAgentError("Final reviewer timed out.", provider_cost_usd="0.125")
        return _result(review_answer())

    monkeypatch.setattr(agents, "reviewer", reviewer)
    brief = run_all(make_brief(world, accounts=[destination]))

    assert brief.status == StudioBrief.Status.FAILED and brief.post is None
    run = brief.runs.get(agent=AgentRun.Agent.REVIEWER, stage="qa")
    assert run.status == AgentRun.Status.FAILED and run.output["provider_cost_usd"] == "0.125"


def test_repeated_working_stage_delivery_does_not_repeat_paid_call(world, fake_team, monkeypatch):
    brief = make_brief(world)
    calls = []

    def strategist(*args, **kwargs):
        calls.append(1)
        pipeline.run_step(str(brief.pk), brief.revision, "strategy")
        return fake_team.__class__.strategist(fake_team, *args, **kwargs)

    monkeypatch.setattr(agents, "strategist", strategist)
    pipeline.run_step(str(brief.pk), brief.revision, "strategy")
    brief.refresh_from_db()

    assert len(calls) == 1 and brief.stage == "copy" and brief.status == StudioBrief.Status.QUEUED
    assert brief.runs.filter(agent=AgentRun.Agent.STRATEGIST).count() == 1
    assert [stage for _, _, stage in fake_team.queued].count("copy") == 1


def _automatic_brief(world, *, manual=False, plan_status=AgencyJob.Status.DONE):
    settings = AgencySettings.objects.create(workspace=world.workspace, autopilot_enabled=True, lead=world.owner)
    job = AgencyJob.objects.create(
        workspace=world.workspace,
        kind=AgencyJob.Kind.PLAN,
        status=plan_status,
        input={"manual": manual, "week_id": "launch-week"},
    )
    brief = make_brief(world, origin=StudioBrief.Origin.AUTOPILOT, job=job)
    return settings, job, brief


def test_off_switch_stops_next_paid_stage_and_resumes_once_with_cap(world, fake_team):
    settings, _, brief = _automatic_brief(world)
    pipeline.run_step(str(brief.pk), brief.revision, "strategy")
    brief.refresh_from_db()
    settings.autopilot_enabled = False
    settings.save(update_fields=["autopilot_enabled"])
    pipeline.run_step(str(brief.pk), brief.revision, "copy")
    brief.refresh_from_db()

    assert brief.status == StudioBrief.Status.QUEUED and brief.stage == "copy"
    assert brief.error == autopilot.AUTOPILOT_PAUSED and not fake_team.calls["copywriter"]
    assert pipeline.resume_paused_briefs(world.workspace, limit=1) == 0
    settings.autopilot_enabled = True
    settings.save(update_fields=["autopilot_enabled"])
    assert pipeline.resume_paused_briefs(world.workspace, limit=0) == 0
    before = len(fake_team.queued)
    assert pipeline.resume_paused_briefs(world.workspace, limit=1) == 1
    assert len(fake_team.queued) == before + 1
    assert pipeline.resume_paused_briefs(world.workspace, limit=1) == 0
    pipeline.run_step(str(brief.pk), brief.revision, "copy")
    assert len(fake_team.calls["copywriter"]) == 1


def test_explicit_manual_plan_can_continue_while_recurring_is_off(world, fake_team):
    settings, _, brief = _automatic_brief(world, manual=True)
    settings.autopilot_enabled = False
    settings.save(update_fields=["autopilot_enabled"])
    pipeline.run_step(str(brief.pk), brief.revision, "strategy")
    brief.refresh_from_db()

    assert len(fake_team.calls["strategist"]) == 1
    assert brief.status == StudioBrief.Status.QUEUED and brief.stage == "copy"


@pytest.mark.parametrize("policy", ["archive", "org_deletion"])
def test_manual_plan_still_stops_for_archived_or_deleting_workspace(world, fake_team, policy):
    _, _, brief = _automatic_brief(world, manual=True)
    if policy == "archive":
        world.workspace.is_archived = True
        world.workspace.save(update_fields=["is_archived"])
    else:
        world.org.deletion_requested_at = timezone.now()
        world.org.save(update_fields=["deletion_requested_at"])
    pipeline.run_step(str(brief.pk), brief.revision, "strategy")
    brief.refresh_from_db()

    assert brief.status == StudioBrief.Status.QUEUED and brief.error == autopilot.WORKSPACE_PAUSED
    assert not fake_team.calls["strategist"]


@pytest.mark.parametrize("status", [AgencyJob.Status.QUEUED, AgencyJob.Status.WORKING, AgencyJob.Status.FAILED])
def test_partial_or_failed_plan_does_not_start_paid_child_brief(world, fake_team, status):
    _, job, brief = _automatic_brief(world, manual=True, plan_status=status)
    pipeline.run_step(str(brief.pk), brief.revision, "strategy")
    brief.refresh_from_db()

    assert brief.status == StudioBrief.Status.QUEUED and brief.error == autopilot.PLAN_PAUSED
    assert not fake_team.calls["strategist"]
    job.status = AgencyJob.Status.DONE
    job.save(update_fields=["status"])
    assert pipeline.resume_paused_briefs(world.workspace, limit=1) == 1


def test_cancelled_plan_discards_queued_child_without_paid_work(world, fake_team):
    _, job, brief = _automatic_brief(world)
    job.status = AgencyJob.Status.CANCELLED
    job.save(update_fields=["status"])
    pipeline.run_step(str(brief.pk), brief.revision, "strategy")
    brief.refresh_from_db()

    assert brief.status == StudioBrief.Status.DISCARDED and not fake_team.calls["strategist"]
    assert brief.error == "The parent plan was cancelled."


def test_sweeper_preserves_old_policy_pause_instead_of_reporting_dead_worker(world, fake_team):
    settings, _, brief = _automatic_brief(world)
    settings.autopilot_enabled = False
    settings.save(update_fields=["autopilot_enabled"])
    pipeline.run_step(str(brief.pk), brief.revision, "strategy")
    StudioBrief.objects.filter(pk=brief.pk).update(updated_at=timezone.now() - timedelta(hours=2))

    assert pipeline.sweep_stuck() == 0
    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.QUEUED and brief.error == autopilot.AUTOPILOT_PAUSED


@pytest.mark.parametrize("reported", ["0", "0.125000"])
def test_provider_bill_survives_model_output_and_stage_completion(world, fake_team, reported):
    brief = make_brief(world)
    run = pipeline._begin(brief, AgentRun.Agent.REVIEWER)
    result = replace(_result(review_answer()), provider_cost_usd=reported)
    pipeline._note_usage(run, result)
    run.refresh_from_db()
    assert run.output["provider_cost_usd"] == llm.validated_provider_cost(reported)
    pipeline._end(run, summary="Complete", output={"provider_cost_usd": "9999", "verdict": "approve"}, result=result)
    run.refresh_from_db()

    assert run.output["provider_cost_usd"] == llm.validated_provider_cost(reported)
    assert run.output["verdict"] == "approve" and run.status == AgentRun.Status.SUCCEEDED


def test_untrusted_model_cost_is_not_recorded_as_provider_bill(world, fake_team):
    brief = make_brief(world)
    run = pipeline._begin(brief, AgentRun.Agent.REVIEWER)
    pipeline._end(run, summary="Complete", output={"provider_cost_usd": "9999"}, result=_result(review_answer()))
    run.refresh_from_db()
    assert "provider_cost_usd" not in run.output


def test_paid_superseded_step_keeps_cost_without_writing_draft(world, fake_team, monkeypatch):
    brief = make_brief(world)

    def strategist(*args, **kwargs):
        StudioBrief.objects.filter(pk=brief.pk).update(status=StudioBrief.Status.DISCARDED)
        return replace(fake_team.__class__.strategist(fake_team, *args, **kwargs), provider_cost_usd="0.25")

    monkeypatch.setattr(agents, "strategist", strategist)
    pipeline.run_step(str(brief.pk), brief.revision, "strategy")
    brief.refresh_from_db()
    run = brief.runs.get(agent=AgentRun.Agent.STRATEGIST)

    assert brief.status == StudioBrief.Status.DISCARDED and brief.post_copy == {}
    assert run.status == AgentRun.Status.SKIPPED and run.output["provider_cost_usd"] == "0.25"
