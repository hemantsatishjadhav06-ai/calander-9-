"""Human photo/style choices survive real chat jobs, revisions and approval handoff."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals import services as approval_services
from apps.approvals.actor import acting_as
from apps.approvals.models import ApprovalAction
from apps.composer.models import PlatformPost
from apps.media_library.models import MediaAsset
from apps.members.models import WorkspaceMembership
from apps.organizations.models import Organization
from apps.publisher import delivery
from apps.studio import chat, engine, llm, services
from apps.studio.models import AgencyJob, Conversation, Message, StudioBrief
from apps.studio.roles import client
from apps.studio.tests.conftest import jpeg_bytes, make_brief, run_all
from apps.workspaces.models import Workspace


@pytest.fixture
def revision_agent(monkeypatch):
    fake = SimpleNamespace(action="revise_design", calls=[], after_answer=None)

    def answer(_profile, **kwargs):
        fake.calls.append(kwargs)
        if fake.after_answer:
            fake.after_answer()
        return llm.AgentResult(
            output=client.ChatAnswer(
                reply="The finished post will be ready within two minutes.",
                action=fake.action,
                instructions="Keep the verified facts and update the requested creative treatment.",
                needs_human=False,
                reason="A human asked for a creative change.",
                creative_brief=None,
            ),
            model="claude-opus-5-5",
            input_tokens=30,
            output_tokens=30,
            cache_read_tokens=0,
            duration_ms=1,
        )

    monkeypatch.setattr(client, "account_manager", answer)
    monkeypatch.setattr(engine, "enqueue", lambda *_args: None)
    return fake


def _ready(world, photo, *, style_lock=True):
    original = photo(filename="original.jpg")
    brief = run_all(make_brief(world, source_picture=original, style_lock=style_lock))
    conversation = chat.conversation_for(world.workspace, brief, audience=Conversation.Audience.INTERNAL)
    return brief, original, conversation


def _drive(job):
    engine.run_step(str(job.pk), job.revision, job.stage)
    job.refresh_from_db()
    assert job.status == AgencyJob.Status.DONE
    return job


def _reply(job):
    return Message.objects.get(pk=job.result["message_id"])


def _snapshot(brief):
    brief.refresh_from_db()
    return (brief.revision, brief.status, brief.source_picture_id, brief.picture_id, brief.style_lock)


def test_explicit_replacement_wins_over_model_generation_and_reaches_rendered_draft(
    world, fake_team, photo, revision_agent
):
    brief, original, conversation = _ready(world, photo)
    replacement = photo(data=jpeg_bytes(color=(180, 80, 60)), filename="replacement.jpg")
    revision_agent.action = "new_picture"
    job = _drive(
        chat.post_message(
            conversation,
            world.editor,
            "Use this new photo with a fresh layout.",
            reference_id=str(replacement.pk),
            style_mode="fresh",
        ).job
    )

    brief.refresh_from_db()
    assert brief.source_picture_id == replacement.pk != original.pk
    assert brief.picture_id is None and not brief.regenerate_picture and not brief.style_lock
    assert job.result["photo_action"] == "replace" and job.result["reference_id"] == str(replacement.pk)
    assert job.result["style_mode"] == "fresh" and job.result["queued"]
    assert "queued" in _reply(job).body and "two minutes" not in _reply(job).body
    assert replacement.filename in revision_agent.calls[-1]["item"]
    assert "fresh layout option" in revision_agent.calls[-1]["item"]
    assert set(brief.post.platform_posts.values_list("status", flat=True)) == {"changes_requested"}

    revised = run_all(brief)
    assert revised.picture_id == replacement.pk and revised.status == StudioBrief.Status.READY
    with replacement.file.open("rb") as handle:
        assert fake_team.calls["art_director"][-1]["source_picture"] == handle.read()
    assert set(revised.post.platform_posts.values_list("status", flat=True)) == {"pending_review"}
    assert not ApprovalAction.objects.filter(post=revised.post, action="approved").exists()


def test_clear_choice_removes_supplied_and_old_generated_photos_before_work(world, fake_team, photo, revision_agent):
    brief, _, conversation = _ready(world, photo)
    job = _drive(chat.post_message(conversation, world.editor, "Clear the old photo.", reference_id="none").job)
    brief.refresh_from_db()
    assert brief.source_picture_id is None and brief.picture_id is None and brief.regenerate_picture
    assert job.result["photo_action"] == "clear" and job.result["reference_id"] == "none"
    revised = run_all(brief)
    assert revised.picture_id is None  # No FAL_KEY: honest brand-background fallback.
    assert fake_team.calls["art_director"][-1]["source_picture"] is None


def test_unqualified_new_picture_cannot_keep_the_old_source_photo(world, fake_team, photo, revision_agent):
    brief, _, conversation = _ready(world, photo)
    revision_agent.action = "new_picture"
    job = _drive(chat.post_message(conversation, world.editor, "Generate a new picture.").job)
    brief.refresh_from_db()
    assert brief.source_picture_id is None and brief.picture_id is None and brief.regenerate_picture
    assert job.result["photo_action"] == "clear"


def test_ordinary_caption_revision_preserves_current_photo_and_style(world, fake_team, photo, revision_agent):
    brief, original, conversation = _ready(world, photo, style_lock=False)
    revision_agent.action = "revise_copy"
    job = _drive(chat.post_message(conversation, world.editor, "Shorten the caption.").job)
    brief.refresh_from_db()
    assert brief.source_picture_id == brief.picture_id == original.pk and not brief.style_lock
    assert job.result["photo_action"] == "keep" and job.result["style_mode"] == "fresh"


def test_brand_style_change_is_applied_without_discarding_current_photo(world, fake_team, photo, revision_agent):
    brief, original, conversation = _ready(world, photo, style_lock=False)
    _drive(chat.post_message(conversation, world.editor, "Match our brand layout.", style_mode="brand").job)
    brief.refresh_from_db()
    assert brief.style_lock and brief.source_picture_id == original.pk


def test_new_angles_can_apply_replacement_and_fresh_style(world, fake_team, photo, revision_agent):
    brief, _, conversation = _ready(world, photo)
    replacement = photo(filename="new-angle.jpg")
    revision_agent.action = "new_angles"
    _drive(
        chat.post_message(
            conversation,
            world.editor,
            "Try a new angle using this photo.",
            reference_id=str(replacement.pk),
            style_mode="fresh",
        ).job
    )
    brief.refresh_from_db()
    assert brief.stage == StudioBrief.Stage.STRATEGY and brief.chosen_concept_id is None
    assert brief.source_picture_id == replacement.pk and not brief.style_lock


@pytest.mark.parametrize("invalid", ["workspace", "organization", "type", "deleted"])
def test_service_rejects_reference_that_lost_scope_before_mutation(world, fake_team, photo, invalid):
    brief, _, _ = _ready(world, photo)
    selected = photo(filename="selected.jpg")
    before = _snapshot(brief)
    if invalid == "workspace":
        selected.workspace = Workspace.objects.create(organization=world.org, name="Other brand")
        selected.save(update_fields=["workspace"])
    elif invalid == "organization":
        selected.organization = Organization.objects.create(name="Other organization")
        selected.save(update_fields=["organization"])
    elif invalid == "type":
        selected.media_type = MediaAsset.MediaType.VIDEO
        selected.save(update_fields=["media_type"])
    else:
        MediaAsset.objects.filter(pk=selected.pk).delete()
    with pytest.raises(services.StudioActionError, match="available photo"):
        services.request_changes(
            brief,
            "Use the selected photo.",
            requested_by=world.editor,
            source_picture_mode="replace",
            source_picture=selected,
        )
    assert _snapshot(brief) == before
    assert set(brief.post.platform_posts.values_list("status", flat=True)) == {"pending_review"}


def test_worker_rechecks_reference_scope_after_the_model_answers(world, fake_team, photo, revision_agent):
    brief, _, conversation = _ready(world, photo)
    selected = photo(filename="selected.jpg")
    posted = chat.post_message(conversation, world.editor, "Use selected photo.", reference_id=str(selected.pk))
    before = _snapshot(brief)
    other = Workspace.objects.create(organization=world.org, name="Another brand")
    revision_agent.after_answer = lambda: MediaAsset.objects.filter(pk=selected.pk).update(workspace=other)
    job = _drive(posted.job)
    assert _snapshot(brief) == before
    assert _reply(job).action_status == Message.ActionStatus.DECLINED


def test_current_permission_revocation_prevents_photo_and_style_revision(world, fake_team, photo, revision_agent):
    brief, _, conversation = _ready(world, photo)
    selected = photo(filename="selected.jpg")
    posted = chat.post_message(
        conversation,
        world.editor,
        "Use selected photo and fresh style.",
        reference_id=str(selected.pk),
        style_mode="fresh",
    )
    before = _snapshot(brief)
    revision_agent.after_answer = lambda: WorkspaceMembership.objects.filter(
        workspace=world.workspace, user=world.editor
    ).update(workspace_role="viewer")
    job = _drive(posted.job)
    assert _snapshot(brief) == before
    assert job.result["skipped"] == "This request no longer has an authorized author."


def test_service_selector_rechecks_current_staff_permission(world, fake_team, photo):
    brief, _, _ = _ready(world, photo)
    selected = photo(filename="selected.jpg")
    before = _snapshot(brief)
    with pytest.raises(services.StudioActionError, match="permissions"):
        services.request_changes(
            brief,
            "Replace the photo.",
            requested_by=world.viewer,
            source_picture_mode="replace",
            source_picture=selected,
            style_mode="fresh",
        )
    assert _snapshot(brief) == before


def test_dashboard_actor_permission_is_rechecked_when_service_caller_omits_requester(world, fake_team, photo):
    brief, _, _ = _ready(world, photo)
    before = _snapshot(brief)
    with acting_as(world.viewer), pytest.raises(services.StudioActionError, match="permissions"):
        services.request_changes(brief, "Change the style.", style_mode="fresh")
    assert _snapshot(brief) == before


def test_forged_client_selectors_cannot_change_staff_creative_choices(world, fake_team, photo, revision_agent):
    brief, _, _ = _ready(world, photo)
    selected = photo(filename="selected.jpg")
    client_user = User.objects.create_user(email="client@photo.test", password="test-pass", name="Client")
    WorkspaceMembership.objects.create(user=client_user, workspace=world.workspace, workspace_role="client")
    conversation = chat.conversation_for(world.workspace, brief, audience=Conversation.Audience.CLIENT)
    posted = chat.post_message(conversation, client_user, "Update the layout.")
    posted.job.input.update(reference_id=str(selected.pk), style_mode="fresh")
    posted.job.save(update_fields=["input"])
    before = _snapshot(brief)
    job = _drive(posted.job)
    assert _snapshot(brief) == before
    assert _reply(job).action_status == Message.ActionStatus.DECLINED


def test_stale_ready_object_cannot_revise_a_now_scheduled_post(world, fake_team, photo):
    brief, _, _ = _ready(world, photo)
    selected = photo(filename="selected.jpg")
    before = _snapshot(brief)
    PlatformPost.objects.filter(post=brief.post).update(
        status="scheduled", scheduled_at=timezone.now() + timedelta(days=1)
    )
    with pytest.raises(services.StudioActionError, match="can't be revised"):
        services.request_changes(
            brief,
            "Replace it.",
            requested_by=world.editor,
            source_picture_mode="replace",
            source_picture=selected,
        )
    assert _snapshot(brief) == before


@pytest.mark.parametrize("operation", ["request_changes", "new_angles", "use_concept"])
def test_unknown_delivery_receipt_blocks_revisions_without_changing_evidence(world, fake_team, photo, operation):
    brief, _, _ = _ready(world, photo)
    receipt = {"_delivery_state": {"kind": "unknown", "attempt_id": "attempt-photo", "fingerprint": "original-content"}}
    PlatformPost.objects.filter(post=brief.post).update(platform_extra=receipt)
    before = _snapshot(brief)
    assert not services.can_revise(brief) and not services.reopen(brief)
    with pytest.raises(services.StudioActionError, match="previous delivery"):
        if operation == "use_concept":
            services.use_concept(brief, brief.concepts.exclude(pk=brief.chosen_concept_id).first())
        else:
            getattr(services, operation)(brief, "Revise the creative.")
    assert _snapshot(brief) == before
    assert PlatformPost.objects.get(post=brief.post).platform_extra == receipt


def test_expired_delivery_requires_human_return_for_review_before_revision(world, fake_team, photo):
    brief, _, _ = _ready(world, photo)
    row = PlatformPost.objects.get(post=brief.post)
    PlatformPost.objects.filter(pk=row.pk).update(status="scheduled", scheduled_at=timezone.now() - timedelta(days=2))
    row.refresh_from_db()
    assert delivery.mark(
        row, kind="expired", reason="The approved publishing time expired without dispatch.", from_status="scheduled"
    )
    evidence = delivery.state(row)
    before = _snapshot(brief)
    with pytest.raises(services.StudioActionError, match="Return for review"):
        services.request_changes(brief, "Use a fresh layout.", requested_by=world.editor, style_mode="fresh")
    assert _snapshot(brief) == before and delivery.state(row) == evidence
    with acting_as(world.owner):
        returned = delivery.checked_absent(
            row.pk,
            world.workspace,
            world.owner,
            confirmed=True,
            reason="The expired attempt was never dispatched; return the unchanged draft for review.",
            expected_attempt_id=evidence["attempt_id"],
            expected_fingerprint=evidence["content_fingerprint"],
        )
    assert returned.status == "pending_review" and not services.has_unconfirmed_delivery(brief)
    services.request_changes(brief, "Now use a fresh layout.", requested_by=world.editor, style_mode="fresh")
    brief.refresh_from_db()
    assert brief.revision == 2 and not brief.style_lock and brief.status == StudioBrief.Status.QUEUED


@pytest.mark.parametrize("kind", ["unknown", "expired"])
@pytest.mark.parametrize("mutation", ["raw_marker_removed", "row_recreated", "all_rows_removed"])
def test_durable_native_delivery_hold_blocks_edit_even_after_channel_rows_change(
    world, fake_team, photo, kind, mutation
):
    brief, _, _ = _ready(world, photo)
    row = PlatformPost.objects.get(post=brief.post)
    assert delivery.mark(row, kind=kind, reason="Unresolved original delivery evidence.", from_status="pending_review")
    brief.post.refresh_from_db()
    original_holds = brief.post.delivery_holds
    before = _snapshot(brief)
    with delivery.delivery_write():
        if mutation == "raw_marker_removed":
            PlatformPost.objects.filter(pk=row.pk).update(status="draft", platform_extra={})
        else:
            PlatformPost.objects.filter(pk=row.pk).delete()
            if mutation == "row_recreated":
                row = PlatformPost.objects.create(post=brief.post, social_account=world.linkedin, status="draft")
    assert services.has_unconfirmed_delivery(brief)
    assert not services.can_revise(brief) and not services.reopen(brief)
    with pytest.raises(services.StudioActionError, match="previous delivery"):
        services.request_changes(brief, "Keep the original delivery proof intact.", requested_by=world.editor)
    assert _snapshot(brief) == before
    brief.post.refresh_from_db()
    assert brief.post.delivery_holds == original_holds


def test_invalid_replacement_rolls_back_reopening_a_returned_client_draft(world, fake_team, photo):
    brief, _, _ = _ready(world, photo)
    selected = photo(filename="foreign.jpg")
    selected.workspace = Workspace.objects.create(organization=world.org, name="Other brand")
    selected.save(update_fields=["workspace"])
    StudioBrief.objects.filter(pk=brief.pk).update(status=StudioBrief.Status.APPROVED)
    PlatformPost.objects.filter(post=brief.post).update(status="changes_requested")
    before = _snapshot(brief)
    with pytest.raises(services.StudioActionError, match="available photo"):
        services.request_changes(
            brief,
            "Replace the photo.",
            requested_by=world.editor,
            allow_reopen=True,
            source_picture_mode="replace",
            source_picture=selected,
        )
    assert _snapshot(brief) == before


def test_queued_revision_withdraws_old_review_and_stale_approval_stamps(world, fake_team, photo):
    brief, _, _ = _ready(world, photo)
    PlatformPost.objects.filter(post=brief.post).update(
        approved_fingerprint="stale",
        approved_revision=1,
        approved_by=world.owner,
        approved_at=timezone.now(),
        approved_publish_at=timezone.now() + timedelta(days=1),
    )
    services.request_changes(brief, "Fresh layout.", requested_by=world.editor, style_mode="fresh")
    channel = PlatformPost.objects.get(post=brief.post)
    assert channel.status == "changes_requested" and channel.approved_fingerprint == ""
    assert channel.approved_by_id is channel.approved_at is channel.approved_publish_at is None
    with acting_as(world.owner):
        approval_services.approve_post(brief.post, world.owner, world.workspace)
    channel.refresh_from_db()
    assert channel.status == "changes_requested"
    assert not ApprovalAction.objects.filter(post=brief.post, action="approved").exists()


def test_schedule_reply_uses_workspace_timezone_without_delivery_deadline(world, fake_team, photo):
    brief, _, _ = _ready(world, photo)
    when = timezone.now() + timedelta(days=2)
    with acting_as(world.owner):
        message = services.approve(brief, world.owner, publish_at=when)
    expected = when.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%a %d %b, %H:%M")
    assert expected in message and "Asia/Kolkata" in message and "within" not in message


def test_publish_now_reply_describes_queue_without_completion_promise(world, fake_team, photo):
    brief, _, _ = _ready(world, photo)
    with acting_as(world.owner):
        message = services.approve(brief, world.owner, publish_now=True)
    assert "queued" in message and "within" not in message
