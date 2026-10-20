"""Launch fault injection: authorization changes, stale work and concurrent confirmations.

The model and source collector are deterministic fakes. Concurrency cases use
separate PostgreSQL connections; no real provider or publication is contacted.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.db import close_old_connections, connections
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals import services as approval_services
from apps.approvals.actor import acting_as
from apps.composer.models import PlatformPost, Post
from apps.media_library.models import MediaAsset
from apps.members.models import CustomRole, WorkspaceMembership
from apps.organizations.models import Organization
from apps.studio import budget, chat, creative_sources, engine, guards, pipeline
from apps.studio.jobtypes import chat as chat_job
from apps.studio.models import AgencyJob, AgencySettings, AgentRun, Conversation, Message, StudioBrief
from apps.studio.roles import client as client_roles
from apps.studio.tests.conftest import make_brief, run_all
from apps.studio.tests.test_chat import drive
from apps.studio.tests.test_guided_chat import GuidedManager, confirmation_job, intake
from apps.workspaces.models import Workspace


@pytest.fixture
def jobs(monkeypatch):
    queued = []
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: queued.append((job.pk, job.revision, stage)))
    return queued


@pytest.fixture
def guided_manager(monkeypatch):
    fake = GuidedManager()
    monkeypatch.setattr(client_roles, "account_manager", fake)
    return fake


@pytest.fixture(autouse=True)
def sources(monkeypatch):
    def collect(workspace, profile, accounts):
        return {
            "fetched_at": timezone.now().isoformat(),
            "website": {"url": "https://neopolis.example/", "status": "ready", "excerpt": "Owner-checked source."},
            "channels": [],
            "notes": [],
        }

    monkeypatch.setattr(creative_sources, "collect", collect)


def _other_workspace():
    return Workspace.objects.create(organization=Organization.objects.create(name="Private agency"), name="Private")


def _mid_model(monkeypatch, manager, callback):
    def answer(profile, **kwargs):
        result = manager(profile, **kwargs)
        callback()
        return result

    monkeypatch.setattr(client_roles, "account_manager", answer)


@pytest.mark.parametrize("revocation", ["membership", "inactive", "custom_role", "archive"])
def test_revocation_during_model_call_cannot_revise_a_ready_draft(
    world, jobs, fake_team, guided_manager, monkeypatch, revocation
):
    brief = run_all(make_brief(world))
    role = None
    if revocation == "custom_role":
        role = CustomRole.objects.create(
            organization=world.org, name="Launch maker", permissions={"create_posts": True}
        )
        WorkspaceMembership.objects.filter(workspace=world.workspace, user=world.editor).update(custom_role=role)
    conversation = chat.conversation_for(world.workspace, brief, audience=Conversation.Audience.INTERNAL)
    posted = chat.post_message(conversation, world.editor, "Make the headline shorter")
    guided_manager.action = "revise_copy"
    guided_manager.creative_brief = None
    original_queued = list(fake_team.queued)

    def revoke():
        if revocation == "membership":
            WorkspaceMembership.objects.filter(workspace=world.workspace, user=world.editor).delete()
        elif revocation == "inactive":
            User.objects.filter(pk=world.editor.pk).update(is_active=False)
        elif revocation == "archive":
            Workspace.objects.filter(pk=world.workspace.pk).update(is_archived=True)
        else:
            CustomRole.objects.filter(pk=role.pk).update(permissions={"create_posts": False})

    _mid_model(monkeypatch, guided_manager, revoke)
    drive(posted.job)

    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.READY and brief.revision == 1
    assert fake_team.queued == original_queued
    assert not conversation.messages.filter(author_kind=Message.AuthorKind.AGENT).exists()
    run = AgentRun.objects.get(job=posted.job)
    assert run.input_tokens == 200  # The answered model turn still incurred usage.


def test_permission_revoked_before_claim_does_not_make_a_paid_model_request(world, jobs, guided_manager):
    conversation = chat.general_conversation(world.workspace)
    posted = chat.post_message(conversation, world.editor, "Please create a post")
    WorkspaceMembership.objects.filter(workspace=world.workspace, user=world.editor).delete()
    drive(posted.job)
    assert not guided_manager.calls and not StudioBrief.objects.exists()


@pytest.mark.parametrize("supersession", ["cancel", "restart"])
def test_superseded_model_answer_cannot_mutate_or_reply(
    world, jobs, fake_team, guided_manager, monkeypatch, supersession
):
    brief = run_all(make_brief(world))
    conversation = chat.conversation_for(world.workspace, brief, audience=Conversation.Audience.INTERNAL)
    posted = chat.post_message(conversation, world.editor, "Use a stronger graphic")
    guided_manager.action = "revise_design"
    guided_manager.creative_brief = None

    def supersede():
        current = AgencyJob.objects.get(pk=posted.job.pk)
        engine.cancel(current) if supersession == "cancel" else engine.restart(current)

    _mid_model(monkeypatch, guided_manager, supersede)
    engine.run_step(str(posted.job.pk), posted.job.revision, posted.job.stage)

    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.READY and brief.revision == 1
    assert not conversation.messages.filter(author_kind=Message.AuthorKind.AGENT).exists()
    current = AgencyJob.objects.get(pk=posted.job.pk)
    assert current.status == (AgencyJob.Status.CANCELLED if supersession == "cancel" else AgencyJob.Status.QUEUED)
    assert AgentRun.objects.get(job=current, revision=1).input_tokens == 200


def test_cancel_during_confirmation_resolution_does_not_start_creative_work(world, jobs, guided_manager, monkeypatch):
    conversation, _, reply = intake(world, guided_manager)
    confirmed = confirmation_job(conversation, world.editor, reply)
    resolve = chat_job._selected_accounts
    creative_tasks = []

    def cancel_while_resolving(channels, accounts):
        result = resolve(channels, accounts)
        # Simulate cancellation committed after the worker claimed its task.
        AgencyJob.objects.filter(pk=confirmed.pk).update(status=AgencyJob.Status.CANCELLED)
        return result

    monkeypatch.setattr(chat_job, "_selected_accounts", cancel_while_resolving)
    monkeypatch.setattr(pipeline, "enqueue", lambda *args: creative_tasks.append(args))
    engine.run_step(str(confirmed.pk), confirmed.revision, confirmed.stage)
    assert not StudioBrief.objects.exists()
    assert not creative_tasks
    assert not conversation.messages.filter(job=confirmed, author_kind=Message.AuthorKind.AGENT).exists()


def test_budget_exhausted_after_model_answer_does_not_start_a_revision(
    world, jobs, fake_team, guided_manager, monkeypatch
):
    brief = run_all(make_brief(world))
    conversation = chat.conversation_for(world.workspace, brief, audience=Conversation.Audience.INTERNAL)
    posted = chat.post_message(conversation, world.editor, "New caption please")
    guided_manager.action = "revise_copy"
    guided_manager.creative_brief = None
    _mid_model(monkeypatch, guided_manager, lambda: monkeypatch.setattr(budget, "can_spend", lambda workspace: False))
    drive(posted.job)
    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.READY and brief.revision == 1


def test_cross_workspace_job_result_is_not_exposed_as_thread_source_evidence(client, world, jobs, guided_manager):
    conversation, source_job, _ = intake(world, guided_manager)
    foreign = _other_workspace()
    foreign_job = AgencyJob.objects.create(
        workspace=foreign,
        conversation=chat.general_conversation(foreign),
        kind=AgencyJob.Kind.CHAT,
        status=AgencyJob.Status.DONE,
        result={
            **source_job.result,
            "sources": {"website": {"title": "PRIVATE OTHER TENANT SOURCE", "excerpt": "Private commercial terms"}},
            "creative_brief": {**source_job.result["creative_brief"], "topic": "PRIVATE OTHER TENANT TOPIC"},
        },
    )
    Message.objects.create(
        conversation=conversation,
        author_kind=Message.AuthorKind.AGENT,
        agent="account_manager",
        job=foreign_job,
        body="A stale job reference",
    )
    client.force_login(world.editor)
    response = client.get(
        reverse(
            "studio:thread_messages", kwargs={"workspace_id": world.workspace.pk, "conversation_id": conversation.pk}
        )
    )
    html = response.content.decode()
    assert response.status_code == 200
    assert "PRIVATE OTHER TENANT SOURCE" not in html and "PRIVATE OTHER TENANT TOPIC" not in html
    assert "Private commercial terms" not in html


def test_reference_moved_to_another_workspace_after_intake_blocks_confirmation(world, jobs, guided_manager, photo):
    reference = photo()
    conversation, _, reply = intake(world, guided_manager, reference_id=str(reference.pk))
    MediaAsset.objects.filter(pk=reference.pk).update(workspace=_other_workspace())
    drive(confirmation_job(conversation, world.editor, reply))
    assert not StudioBrief.objects.exists()


def test_confirmed_destination_disconnected_while_refreshing_evidence_stays_unsent(
    world, jobs, guided_manager, monkeypatch
):
    conversation, intake_job, reply = intake(world, guided_manager)
    snapshot = intake_job.result
    # Evidence is good for a day; older than that it is refreshed before the team starts.
    snapshot["sources"]["fetched_at"] = (timezone.now() - timedelta(hours=25)).isoformat()
    intake_job.result = snapshot
    intake_job.save(update_fields=["result"])
    original = chat_job._collect_sources

    def disconnect(workspace, profile, accounts):
        result = original(workspace, profile, accounts)
        world.linkedin.connection_status = "disconnected"
        world.linkedin.save(update_fields=["connection_status"])
        return result

    monkeypatch.setattr(chat_job, "_collect_sources", disconnect)
    drive(confirmation_job(conversation, world.editor, reply))
    assert not StudioBrief.objects.exists() and not Post.objects.exists()


def test_lost_approval_privileges_do_not_leave_a_client_draft_owned_by_the_old_lead(world, jobs, guided_manager):
    user = User.objects.create_user(email="client-launch@example.com", password="test-password", name="Client")
    WorkspaceMembership.objects.create(user=user, workspace=world.workspace, workspace_role="client")
    AgencySettings.objects.create(workspace=world.workspace, lead=world.manager)
    conversation = chat.general_conversation(world.workspace, audience=Conversation.Audience.CLIENT)
    posted = chat.post_message(conversation, user, "Please create a new post")
    WorkspaceMembership.objects.filter(workspace=world.workspace, user__in=[world.owner, world.manager]).update(
        workspace_role="viewer"
    )
    guided_manager.creative_brief = None
    drive(posted.job)
    assert not StudioBrief.objects.exists()
    posted.job.refresh_from_db()
    assert posted.job.result["status"] == Message.ActionStatus.NEEDS_HUMAN


def test_agent_work_cannot_approve_even_if_a_dashboard_actor_is_accidentally_present(
    world, jobs, guided_manager, monkeypatch
):
    post = Post.objects.create(workspace=world.workspace, author=world.owner, caption="Review me")
    pp = PlatformPost.objects.create(post=post, social_account=world.linkedin, status="pending_review")
    conversation = chat.general_conversation(world.workspace)
    posted = chat.post_message(conversation, world.owner, "Approve this draft")
    guided_manager.action = "answer"
    guided_manager.creative_brief = None

    def illicit_approval():
        with acting_as(world.owner), pytest.raises(guards.AgentMayNotApproveError):
            approval_services.approve_post(post, world.owner, world.workspace)

    _mid_model(monkeypatch, guided_manager, illicit_approval)
    drive(posted.job)
    pp.refresh_from_db()
    assert pp.status == "pending_review" and pp.approved_by_id is None


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_confirmations_create_one_draft_and_no_publication(
    world, jobs, guided_manager, fake_team, monkeypatch
):
    conversation, _, reply = intake(world, guided_manager)
    first = confirmation_job(conversation, world.editor, reply)
    second = confirmation_job(conversation, world.editor, reply)
    rendezvous = Barrier(2, timeout=10)
    confirm = chat_job._confirm

    def together(*args, **kwargs):
        rendezvous.wait()
        return confirm(*args, **kwargs)

    monkeypatch.setattr(chat_job, "_confirm", together)

    def worker(job):
        close_old_connections()
        try:
            engine.run_step(str(job.pk), job.revision, job.stage)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker, [first, second]))

    assert StudioBrief.objects.filter(workspace=world.workspace).count() == 1
    assert not Post.objects.exists()
    assert len(fake_team.queued) == 1
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == second.status == AgencyJob.Status.DONE
    assert first.result["brief_id"] == second.result["brief_id"]
