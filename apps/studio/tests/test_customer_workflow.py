"""Saved ideas, canonical handoffs and honest progress remain scoped and resumable."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections
from django.urls import reverse
from django.utils import timezone

from apps.composer.models import PlatformPost, Post
from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
from apps.studio import chat, customer_workflow, engine
from apps.studio.models import AgencyJob, Conversation, StudioBrief
from apps.studio.tests.test_chat import assert_nothing_approved, drive
from apps.studio.tests.test_guided_chat import guided_manager as guided_manager_fixture
from apps.studio.tests.test_guided_chat import source_collector as source_collector_fixture
from apps.workspaces.models import Workspace

guided_manager = guided_manager_fixture
source_collector = source_collector_fixture


@pytest.fixture
def queued(monkeypatch):
    rows = []
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: rows.append((job.pk, job.revision, stage)))
    return rows


def saved(world, **fields):
    fields.setdefault("request_id", uuid4())
    fields.setdefault("idea", "Explain what first-time buyers should check before a site visit")
    return customer_workflow.save_idea(world.workspace, world.editor, **fields)


def journey(world, conversation):
    rows = customer_workflow.context(world.workspace, world.editor)["journeys"]
    return next(row for row in rows if row["id"] == str(conversation.pk))


def url(world, name, **kwargs):
    return reverse(f"studio:{name}", kwargs={"workspace_id": world.workspace.pk, **kwargs})


class TestSavedIdeas:
    def test_manual_save_and_reload_need_no_provider_or_job(self, world, settings, queued):
        settings.ANTHROPIC_API_KEY = ""
        settings.OPENROUTER_API_KEY = ""
        conversation = saved(world)
        first = journey(world, conversation)
        second = journey(world, conversation)
        assert first["state"] == second["state"] == "blocked"
        assert first["current_step"] == 1 and not first["can_resume"]
        assert not AgencyJob.objects.filter(workspace=world.workspace).exists()
        assert not StudioBrief.objects.filter(workspace=world.workspace).exists()
        assert conversation.messages.count() == 1 and not queued

    def test_duplicate_save_is_idempotent_and_cannot_replace_the_idea(self, world):
        nonce = uuid4()
        first = saved(world, request_id=nonce, idea="First idea")
        second = saved(world, request_id=nonce, idea="First idea")
        assert first.pk == second.pk and first.messages.count() == 1
        with pytest.raises(customer_workflow.WorkflowError):
            saved(world, request_id=nonce, idea="Replaced idea")
        assert first.messages.get().body == "First idea"

    def test_saved_idea_does_not_become_the_general_thread(self, world):
        conversation = saved(world)
        assert chat.find_general(world.workspace) is None
        general = chat.general_conversation(world.workspace, created_by=world.editor)
        assert general.pk != conversation.pk
        assert chat.find_general(world.workspace).pk == general.pk

    def test_another_workspace_cannot_reuse_a_form_nonce(self, world):
        conversation = saved(world)
        other = Workspace.objects.create(organization=world.org, name="Other")
        WorkspaceMembership.objects.create(user=world.editor, workspace=other, workspace_role="editor")
        with pytest.raises(customer_workflow.WorkflowError):
            customer_workflow.save_idea(other, world.editor, request_id=conversation.pk, idea=conversation.title)
        assert Conversation.objects.filter(pk=conversation.pk).get().workspace_id == world.workspace.pk

    def test_telegram_prompts_require_the_original_authors_explicit_per_idea_opt_in(self, world):
        conversation = saved(world)
        with pytest.raises(PermissionDenied, match="not enabled"):
            customer_workflow.validate_author(conversation, world.editor, require_telegram_opt_in=True)
        opted_in = saved(world, telegram_updates=True)
        _workspace, person, _member, original = customer_workflow.validate_author(
            opted_in, world.editor, require_telegram_opt_in=True
        )
        assert person.pk == original.author_id == world.editor.pk
        marker = opted_in.messages.get(action=customer_workflow.TELEGRAM_OPT_IN_ACTION)
        assert marker.is_internal and marker.author_id == world.editor.pk
        with pytest.raises(PermissionDenied):
            customer_workflow.validate_author(opted_in, world.owner, require_telegram_opt_in=True)

    def test_duplicate_form_cannot_silently_change_telegram_sharing(self, world):
        conversation = saved(world, telegram_updates=False)
        with pytest.raises(customer_workflow.WorkflowError):
            saved(world, request_id=conversation.pk, idea=conversation.title, telegram_updates=True)
        assert not conversation.messages.filter(action=customer_workflow.TELEGRAM_OPT_IN_ACTION).exists()

    def test_private_threads_cannot_become_shared_workflow_reply_targets(self, world):
        conversation = saved(world, telegram_updates=True)
        conversation.is_private = True
        conversation.save(update_fields=["is_private"])
        with pytest.raises(PermissionDenied):
            customer_workflow.validate_author(conversation, world.editor, require_telegram_opt_in=True)


class TestCanonicalStart:
    def test_start_and_duplicate_click_queue_one_guided_turn(self, world, queued):
        conversation = saved(world)
        first = customer_workflow.start_idea(world.workspace, world.editor, conversation.pk)
        second = customer_workflow.start_idea(world.workspace, world.editor, conversation.pk)
        assert first.job.pk == second.job.pk and second.already_started
        assert len(queued) == 1 and conversation.messages.count() == 2
        assert not StudioBrief.objects.filter(workspace=world.workspace).exists()
        assert journey(world, conversation)["state"] == "queued"
        assert_nothing_approved(world.workspace)

    def test_configuration_and_budget_blocks_keep_the_saved_idea(self, world, queued, settings, monkeypatch):
        conversation = saved(world)
        settings.ANTHROPIC_API_KEY = ""
        result = customer_workflow.start_idea(world.workspace, world.editor, conversation.pk)
        assert result.job is None and "open Set up" in result.note and "administrator" not in result.note
        settings.ANTHROPIC_API_KEY = "fake-provider-key"
        monkeypatch.setattr(customer_workflow.budget, "can_spend", lambda ws: False)
        result = customer_workflow.start_idea(world.workspace, world.editor, conversation.pk)
        assert result.job is None and "budget" in result.note
        assert conversation.messages.count() == 1 and not queued

    def test_other_staff_cannot_start_as_the_original_requester(self, world, queued):
        conversation = saved(world)
        with pytest.raises(PermissionDenied):
            customer_workflow.start_idea(world.workspace, world.owner, conversation.pk)
        assert not queued and conversation.messages.count() == 1

    @pytest.mark.parametrize("revocation", ["workspace", "organization", "archived", "disabled", "custom_role"])
    def test_fresh_permissions_are_required_after_the_idea_is_saved(self, world, queued, revocation):
        conversation = saved(world)
        if revocation == "workspace":
            WorkspaceMembership.objects.filter(user=world.editor, workspace=world.workspace).delete()
        elif revocation == "organization":
            OrgMembership.objects.filter(user=world.editor, organization=world.org).delete()
        elif revocation == "archived":
            Workspace.objects.filter(pk=world.workspace.pk).update(is_archived=True)
        elif revocation == "disabled":
            type(world.editor).objects.filter(pk=world.editor.pk).update(is_active=False)
        else:
            custom = CustomRole.objects.create(
                organization=world.org, name="Read only", permissions={"create_posts": False}
            )
            WorkspaceMembership.objects.filter(user=world.editor, workspace=world.workspace).update(custom_role=custom)
        with pytest.raises(PermissionDenied):
            customer_workflow.start_idea(world.workspace, world.editor, conversation.pk)
        assert not queued and not AgencyJob.objects.filter(conversation=conversation).exists()

    @pytest.mark.parametrize("status", [AgencyJob.Status.CANCELLED, AgencyJob.Status.FAILED, AgencyJob.Status.DONE])
    def test_restart_button_cannot_bypass_existing_task_controls(self, world, queued, status):
        conversation = saved(world)
        first = customer_workflow.start_idea(world.workspace, world.editor, conversation.pk)
        first.job.status = status
        first.job.state = {"_opendots_control": {"paused": True, "review_required": True}}
        first.job.save(update_fields=["status", "state"])
        again = customer_workflow.start_idea(world.workspace, world.editor, conversation.pk)
        assert again.already_started and again.job.pk == first.job.pk and len(queued) == 1
        assert AgencyJob.objects.get(pk=first.job.pk).status == status

    def test_missing_answers_then_confirmation_continue_in_the_same_canonical_thread(
        self, world, queued, guided_manager, source_collector, fake_team
    ):
        conversation = saved(world)
        # The manager's one allowed question: the topic itself was unclear.
        guided_manager.action = "answer"
        guided_manager.creative_brief["topic"] = ""
        first = customer_workflow.start_idea(world.workspace, world.editor, conversation.pk)
        assert first.job.input["kind"] == "create"
        drive(first.job)
        assert journey(world, conversation)["state"] == "needs_input"
        waiting = customer_workflow.context(world.workspace, world.editor)
        assert waiting["polling"] and not waiting["active"]
        assert not StudioBrief.objects.filter(workspace=world.workspace).exists()
        guided_manager.action = "new_post"
        guided_manager.creative_brief["topic"] = "What first-time buyers should check before a site visit"
        answer = drive(chat.post_message(conversation, world.editor, "A checklist before the site visit").job)
        assert journey(world, conversation)["state"] == "needs_confirmation"
        assert not StudioBrief.objects.filter(workspace=world.workspace).exists()
        confirmation = chat.post_message(
            conversation,
            world.editor,
            "Confirm this brief and create a draft for review.",
            kind="confirm_brief",
            confirmation_message_id=answer.result["message_id"],
            facts_confirmed=True,
        )
        drive(confirmation.job)
        brief = StudioBrief.objects.get(workspace=world.workspace)
        assert brief.job.conversation_id == conversation.pk
        assert brief.status == StudioBrief.Status.QUEUED
        assert journey(world, conversation)["current_step"] == 2
        assert_nothing_approved(world.workspace)


class TestHonestReadOnlyProgress:
    def test_private_history_and_other_workspaces_are_excluded(self, world):
        public = saved(world)
        private = saved(world, idea="Private history must never be shown")
        private.is_private = True
        private.save(update_fields=["is_private"])
        visible = customer_workflow.context(world.workspace, world.editor)["journeys"]
        assert [row["id"] for row in visible] == [str(public.pk)]

    def test_client_custom_role_cannot_open_the_staff_workflow(self, world):
        custom = CustomRole.objects.create(
            organization=world.org, name="Client creator", permissions={"create_posts": True}
        )
        WorkspaceMembership.objects.filter(user=world.editor, workspace=world.workspace).update(
            workspace_role="client", custom_role=custom
        )
        with pytest.raises(PermissionDenied):
            customer_workflow.context(world.workspace, world.editor)

    def test_every_destination_must_be_published_before_a_journey_claims_completion(self, world, queued):
        conversation = saved(world)
        job = customer_workflow.start_idea(world.workspace, world.editor, conversation.pk).job
        job.status = AgencyJob.Status.DONE
        job.save(update_fields=["status"])
        post = Post.objects.create(workspace=world.workspace, author=world.editor, title="Draft")
        brief = StudioBrief.objects.create(
            workspace=world.workspace,
            author=world.editor,
            idea="Draft",
            origin="chat",
            job=job,
            status="approved",
            post=post,
        )
        brief.social_accounts.set([world.linkedin, world.x])
        PlatformPost.objects.create(
            post=post,
            social_account=world.linkedin,
            status="published",
            platform_post_id="native-1",
            published_at=timezone.now(),
        )
        second = PlatformPost.objects.create(
            post=post, social_account=world.x, status="scheduled", scheduled_at=timezone.now()
        )
        assert journey(world, conversation)["state"] == "delivering"
        second.status = "published"
        second.platform_post_id = "native-2"
        second.published_at = timezone.now()
        second.save(update_fields=["status", "platform_post_id", "published_at"])
        assert journey(world, conversation)["state"] == "published"
        assert all(step["state"] == "complete" for step in journey(world, conversation)["steps"])
        second.published_at = None
        second.save(update_fields=["published_at"])
        assert journey(world, conversation)["state"] == "held"
        assert not customer_workflow.context(world.workspace, world.editor)["active"]

    def test_http_status_poll_does_not_create_work_or_private_output(self, client, world, queued, settings):
        settings.ANTHROPIC_API_KEY = ""
        conversation = saved(world, idea="<script>alert('idea')</script>")
        client.force_login(world.editor)
        first = client.get(url(world, "workflow_status"))
        second = client.get(url(world, "workflow_status"))
        assert first.status_code == second.status_code == 200
        assert first["Cache-Control"] == "no-store, private"
        assert not first.json()["active"]
        assert "<script>alert" not in first.json()["html"]
        assert "&lt;script&gt;" in first.json()["html"]
        # The compact In progress rows, the same partial Home renders.
        assert 'id="workflow-journeys"' in first.json()["html"]
        assert f'data-workflow-journey="{conversation.pk}"' in first.json()["html"]
        assert conversation.messages.count() == 1 and not queued

    def test_the_guided_page_is_home_now(self, client, world):
        client.force_login(world.editor)
        response = client.get(url(world, "workflow"))
        assert response.status_code == 302 and response["Location"] == url(world, "index")
        # Viewers and clients never reach the staff entry points.
        client.force_login(world.viewer)
        assert client.get(url(world, "workflow")).status_code == 403

    def test_create_without_provider_keeps_an_actionable_saved_idea(self, client, world, queued, settings):
        settings.ANTHROPIC_API_KEY = ""
        client.force_login(world.editor)
        response = client.post(
            url(world, "workflow_create"), {"request_id": str(uuid4()), "idea": "Useful idea"}, follow=True
        )
        assert response.status_code == 200
        assert "Useful idea" in response.content.decode()
        assert "AI setup needed" in response.content.decode()
        assert not queued and not StudioBrief.objects.filter(workspace=world.workspace).exists()

    def test_status_access_is_rechecked_after_membership_revocation(self, client, world, queued):
        client.force_login(world.editor)
        assert client.get(url(world, "workflow_status")).status_code == 200
        WorkspaceMembership.objects.filter(user=world.editor, workspace=world.workspace).delete()
        assert client.get(url(world, "workflow_status")).status_code in (403, 404)
        assert not queued


@pytest.mark.django_db(transaction=True)
def test_concurrent_resume_dispatches_exactly_once(world, monkeypatch):
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: None)
    conversation = saved(world)
    rendezvous = Barrier(2)

    def dispatch():
        close_old_connections()
        try:
            rendezvous.wait(timeout=10)
            return customer_workflow.start_idea(world.workspace, world.editor, conversation.pk).job.pk
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(lambda _: dispatch(), range(2)))
    assert ids[0] == ids[1]
    assert AgencyJob.objects.filter(workspace=world.workspace, conversation=conversation).count() == 1
    assert conversation.messages.count() == 2
