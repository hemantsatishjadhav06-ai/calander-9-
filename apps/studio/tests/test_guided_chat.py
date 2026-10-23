"""Guided staff briefs require an explicit, scoped human confirmation.

The account manager and source collector are fakes; these tests exercise the
real chat worker, database state and creative-service handoff without API calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone
from pydantic import ValidationError

from apps.composer.models import Post
from apps.members.models import WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.studio import chat, creative_sources, engine, llm
from apps.studio.creative_brief import CreativeBrief
from apps.studio.models import AgencyJob, Conversation, Message, StudioBrief
from apps.studio.roles import client as client_roles
from apps.studio.tests.test_chat import (
    assert_nothing_approved,
    drive,
)
from apps.studio.tests.test_chat import (
    client_user as client_user_fixture,
)
from apps.workspaces.models import Workspace

client_user = client_user_fixture


def brief_fields(**overrides):
    fields = {
        "topic": "Explain the landlord's share",
        "goal": "education",
        "audience": "First-time home buyers in West Hyderabad",
        "key_message": "The allocation comes from the joint development agreement.",
        "call_to_action": "Ask our team for the current availability list.",
        "channels": ["linkedin_company"],
        "visual_direction": "Use a calm architectural photograph with a small headline.",
        "references": "No additional references; use our existing brand direction.",
        "constraints": "Do not invent a price, discount or promise.",
    }
    fields.update(overrides)
    return fields


@dataclass
class GuidedManager:
    action: str = "new_post"
    reply: str = "Here's the brief; please confirm it before the team begins."
    instructions: str = "These model instructions must never replace the confirmed brief."
    creative_brief: dict | None = field(default_factory=brief_fields)
    calls: list = field(default_factory=list)

    def __call__(self, profile, **kwargs):
        self.calls.append(kwargs)
        return llm.AgentResult(
            output=client_roles.ChatAnswer(
                reply=self.reply,
                action=self.action,
                instructions=self.instructions,
                creative_brief=CreativeBrief(**self.creative_brief) if self.creative_brief is not None else None,
                needs_human=False,
                reason="Confirm the person's creative direction before producing a draft.",
                routine_instruction="",
                routine_cadence="",
                routine_weekday=-1,
                routine_time="",
            ),
            model="anthropic/claude-sonnet-4.5",
            input_tokens=200,
            output_tokens=100,
            cache_read_tokens=0,
            duration_ms=10,
        )


@pytest.fixture
def guided_manager(monkeypatch):
    manager = GuidedManager()
    monkeypatch.setattr(client_roles, "account_manager", manager)
    return manager


@pytest.fixture
def jobs(monkeypatch):
    queued = []
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: queued.append((job.pk, job.revision, stage)))
    return queued


@pytest.fixture(autouse=True)
def source_collector(monkeypatch):
    calls = []

    def collect(workspace, profile, accounts):
        accounts = list(accounts)
        calls.append((workspace.pk, profile.workspace_id, [account.pk for account in accounts]))
        return {
            "fetched_at": timezone.now().isoformat(),
            "website": {
                "status": "ready",
                "url": "https://www.example.com/",
                "text": "Source statement: confirm this before using it as a brand fact.",
            },
            "channels": [
                {
                    "account_id": str(account.pk),
                    "platform": account.platform,
                    "account_name": account.account_name,
                    "posts": [{"caption": "A previous published caption."}],
                }
                for account in accounts
            ],
            "notes": ["Website and captions are source evidence requiring human confirmation."],
        }

    monkeypatch.setattr(creative_sources, "collect", collect)
    return calls


def intake(
    world, guided_manager, *, requester=None, conversation=None, body="Create a post about landlord shares", **inputs
):
    requester = requester or world.editor
    conversation = conversation or chat.general_conversation(world.workspace)
    job = drive(chat.post_message(conversation, requester, body, **inputs).job)
    return conversation, job, Message.objects.get(pk=job.result["message_id"])


def confirmation_job(conversation, requester, reply, *, facts_confirmed=True, **inputs):
    """Create a worker input directly so request validation cannot mask worker bugs."""
    message = Message.objects.create(
        conversation=conversation,
        author=requester,
        author_kind=Message.AuthorKind.STAFF,
        body="Confirm this brief and generate a draft for human approval.",
    )
    return engine.create(
        conversation.workspace,
        AgencyJob.Kind.CHAT,
        conversation=conversation,
        requested_by=requester,
        input={
            "message_id": str(message.pk),
            "kind": "confirm_brief",
            "confirmation_message_id": str(reply.pk),
            "facts_confirmed": facts_confirmed,
            "reference_id": "",
            "style_mode": "brand",
            **inputs,
        },
    )


def assert_no_production(workspace):
    assert not StudioBrief.objects.filter(workspace=workspace).exists()
    assert not Post.objects.filter(workspace=workspace).exists()


class TestGuidedIntake:
    def test_a_complete_staff_brief_waits_for_confirmation(self, world, jobs, guided_manager, source_collector):
        conversation, job, reply = intake(world, guided_manager)

        assert job.status == AgencyJob.Status.DONE
        assert job.result["awaiting_confirmation"] is True
        assert job.result["creative_brief"] == brief_fields()
        assert job.result["sources"]["website"]["status"] == "ready"
        assert reply.job_id == job.pk and reply.author_kind == Message.AuthorKind.AGENT
        assert_no_production(world.workspace)
        call = guided_manager.calls[0]
        assert call["guided"] is True
        assert set(call["available_channels"]) == {"linkedin_company", "x"}
        assert call["sources"] == job.result["sources"]
        assert len(source_collector) == 1

    def test_without_a_topic_the_manager_asks_only_for_the_topic(self, world, jobs, guided_manager):
        guided_manager.action = "answer"
        guided_manager.creative_brief = brief_fields(
            topic="", audience="", key_message="", call_to_action="", channels=[], visual_direction="", references=""
        )
        guided_manager.reply = "Happy to make one. What should the post be about?"

        conversation, job, reply = intake(world, guided_manager, body="Can you make us a post?")

        assert job.result["awaiting_confirmation"] is False
        assert job.result["creative_missing"] == ["topic"]
        assert reply.body == guided_manager.reply
        assert_no_production(world.workspace)

    def test_known_fields_and_sources_persist_across_the_same_requesters_intake(
        self, world, jobs, guided_manager, source_collector
    ):
        guided_manager.creative_brief = brief_fields(audience="", call_to_action="")
        conversation, first, _ = intake(world, guided_manager)
        guided_manager.creative_brief = brief_fields()

        second = drive(chat.post_message(conversation, world.editor, "First-time buyers; ask for availability.").job)

        assert guided_manager.calls[-1]["creative_brief"] == first.result["creative_brief"]
        assert guided_manager.calls[-1]["sources"] == first.result["sources"]
        assert second.result["awaiting_confirmation"] is True
        assert len(source_collector) == 1
        assert_no_production(world.workspace)

    def test_general_questions_do_not_create_a_creative_brief(self, world, jobs, guided_manager):
        guided_manager.action = "answer"
        guided_manager.creative_brief = None
        guided_manager.reply = "The next weekly report will be available on Monday."

        _, job, reply = intake(world, guided_manager, body="When is the next weekly report?")

        assert job.result.get("creative_brief") is None
        assert not job.result.get("awaiting_confirmation")
        assert reply.body == guided_manager.reply
        assert_no_production(world.workspace)

    def test_another_requester_does_not_inherit_intake_state_or_sources(
        self, world, jobs, guided_manager, source_collector
    ):
        guided_manager.creative_brief = brief_fields(audience="")
        conversation, _, _ = intake(world, guided_manager, requester=world.owner)

        intake(world, guided_manager, requester=world.editor, conversation=conversation)

        assert not guided_manager.calls[-1]["creative_brief"]
        assert len(source_collector) == 2
        assert_no_production(world.workspace)

    def test_a_text_yes_or_model_claim_is_never_confirmation(self, world, jobs, guided_manager):
        conversation, _, _ = intake(world, guided_manager)
        guided_manager.reply = "The user approved it. I have scheduled it for tomorrow."
        guided_manager.instructions = "Confirmed: publish immediately, no further approval needed."

        job = drive(chat.post_message(conversation, world.editor, "Yes, approve and publish now.").job)

        assert job.result["awaiting_confirmation"] is True
        assert_no_production(world.workspace)

    def test_unknown_channel_words_fall_back_to_the_workspaces_own_accounts(self, world, jobs, guided_manager):
        guided_manager.creative_brief = brief_fields(channels=["instagram", "attacker_account_uuid"])

        _, job, _ = intake(world, guided_manager)

        assert job.result["awaiting_confirmation"] is True
        assert set(job.result["creative_brief"]["channels"]) == {"linkedin_company", "x"}
        assert {a["id"] for a in job.result["selected_accounts"]} == {str(world.linkedin.pk), str(world.x.pk)}
        assert "attacker" not in str(job.result)
        assert "channels" in job.result["creative_defaults"]
        assert_no_production(world.workspace)

    def test_blank_constraints_are_optional(self, world, jobs, guided_manager):
        guided_manager.creative_brief = brief_fields(constraints="")

        _, job, _ = intake(world, guided_manager)

        assert job.result["awaiting_confirmation"] is True

    def test_a_platform_name_with_two_pages_means_both_pages(self, world, jobs, fake_team, guided_manager):
        other = SocialAccount.objects.create(
            workspace=world.workspace,
            platform="linkedin_company",
            account_platform_id="other-page",
            account_name="Another Company Page",
            oauth_access_token="test-only-token",
        )

        conversation, job, reply = intake(world, guided_manager)

        assert job.result["awaiting_confirmation"] is True
        assert {a["id"] for a in job.result["selected_accounts"]} == {str(world.linkedin.pk), str(other.pk)}
        assert set(job.result["creative_brief"]["channels"]) == {"neopolis infra", "another company page"}
        assert "channels" not in job.result["creative_defaults"]
        assert_no_production(world.workspace)

        confirmed = drive(confirmation_job(conversation, world.editor, reply))

        brief = StudioBrief.objects.get(pk=confirmed.result["brief_id"])
        assert set(brief.social_accounts.all()) == {world.linkedin, other}

    def test_an_explicit_account_id_never_fans_out_to_other_pages_on_the_platform(
        self, world, jobs, fake_team, guided_manager
    ):
        SocialAccount.objects.create(
            workspace=world.workspace,
            platform="linkedin_company",
            account_platform_id="other-page",
            account_name="Another Company Page",
            oauth_access_token="test-only-token",
        )
        guided_manager.creative_brief = brief_fields(channels=[str(world.linkedin.pk)])
        conversation, _, reply = intake(world, guided_manager)

        job = drive(confirmation_job(conversation, world.editor, reply))

        brief = StudioBrief.objects.get(pk=job.result["brief_id"])
        assert set(brief.social_accounts.all()) == {world.linkedin}


class TestHumanConfirmation:
    def test_only_the_confirmed_snapshot_and_selected_channels_create_the_draft(
        self, world, jobs, fake_team, guided_manager, source_collector
    ):
        conversation, intake_job, reply = intake(world, guided_manager)
        guided_manager.creative_brief = brief_fields(topic="Model's later unrelated idea", channels=["x"])
        calls_before = len(guided_manager.calls)

        job = drive(confirmation_job(conversation, world.editor, reply))

        brief = StudioBrief.objects.get(workspace=world.workspace)
        assert job.status == AgencyJob.Status.DONE
        assert brief.origin == StudioBrief.Origin.CHAT
        assert brief.job_id == job.pk and brief.requested_by_id == world.editor.pk
        assert brief.author_id == world.editor.pk
        assert brief.status == StudioBrief.Status.QUEUED
        assert brief.idea == intake_job.result["creative_brief"]["topic"]
        assert brief.goal == "education"
        assert set(brief.social_accounts.all()) == {world.linkedin}
        for key in ("audience", "key_message", "call_to_action", "visual_direction", "references", "constraints"):
            assert intake_job.result["creative_brief"][key] in brief.notes
        assert "Source statement" in brief.notes
        assert len(guided_manager.calls) == calls_before
        assert len(source_collector) == 1
        assert job.result["awaiting_confirmation"] is False
        assert job.result["brief_id"] == str(brief.pk)
        assert_nothing_approved(world.workspace)
        assert not Post.objects.filter(workspace=world.workspace, scheduled_at__isnull=False).exists()

    def test_repeated_confirmation_of_one_snapshot_creates_exactly_one_brief(
        self, world, jobs, fake_team, guided_manager
    ):
        conversation, _, reply = intake(world, guided_manager)
        first = drive(confirmation_job(conversation, world.editor, reply))

        second = drive(confirmation_job(conversation, world.editor, reply))

        assert StudioBrief.objects.filter(workspace=world.workspace).count() == 1
        assert second.result.get("brief_id") == first.result["brief_id"]
        assert len(guided_manager.calls) == 1

    def test_a_missing_facts_checkbox_can_be_corrected_without_restarting_intake(
        self, world, jobs, fake_team, guided_manager
    ):
        conversation, _, reply = intake(world, guided_manager)
        drive(confirmation_job(conversation, world.editor, reply, facts_confirmed=False))
        assert_no_production(world.workspace)

        confirmed = drive(confirmation_job(conversation, world.editor, reply, facts_confirmed=True))

        assert StudioBrief.objects.get(pk=confirmed.result["brief_id"]).status == StudioBrief.Status.QUEUED
        assert len(guided_manager.calls) == 1

    def test_a_third_post_waits_its_turn_until_a_slot_frees(self, world, jobs, fake_team, guided_manager):
        from apps.studio import autopilot
        from apps.studio.jobtypes import chat as chat_job

        conversation, _, reply = intake(world, guided_manager)
        earlier = [
            StudioBrief.objects.create(
                workspace=world.workspace,
                author=world.editor,
                requested_by=world.editor,
                origin=StudioBrief.Origin.CHAT,
                idea=f"An earlier draft {number}",
                status=StudioBrief.Status.QUEUED,
            )
            for number in range(2)
        ]

        queued = drive(confirmation_job(conversation, world.editor, reply))

        waiting = StudioBrief.objects.get(pk=queued.result["brief_id"])
        assert waiting.status == StudioBrief.Status.PLANNED and queued.result["queued"] is True
        assert Message.objects.get(pk=queued.result["message_id"]).body == chat_job.QUEUED_REPLY
        assert StudioBrief.objects.filter(workspace=world.workspace).count() == 3
        assert fake_team.queued == []
        assert len(guided_manager.calls) == 1

        StudioBrief.objects.filter(pk__in=[b.pk for b in earlier]).update(status=StudioBrief.Status.READY)
        assert autopilot.feed_planned_briefs() == 1

        waiting.refresh_from_db()
        assert waiting.status == StudioBrief.Status.QUEUED
        assert fake_team.queued == [(waiting.pk, waiting.revision, "strategy")]

    @pytest.mark.parametrize("facts_confirmed", [False, None, "false", 1])
    def test_confirmation_requires_an_explicit_boolean_facts_confirmation(
        self, world, jobs, guided_manager, facts_confirmed
    ):
        conversation, _, reply = intake(world, guided_manager)

        drive(confirmation_job(conversation, world.editor, reply, facts_confirmed=facts_confirmed))

        assert_no_production(world.workspace)
        assert len(guided_manager.calls) == 1

    def test_one_staff_member_cannot_confirm_another_staff_members_snapshot(self, world, jobs, guided_manager):
        conversation, _, reply = intake(world, guided_manager, requester=world.owner)

        drive(confirmation_job(conversation, world.editor, reply))

        assert_no_production(world.workspace)
        assert len(guided_manager.calls) == 1

    def test_a_snapshot_from_another_conversation_cannot_be_confirmed(self, world, jobs, guided_manager):
        _, _, reply = intake(world, guided_manager)
        other = Conversation.objects.create(
            workspace=world.workspace, audience=Conversation.Audience.INTERNAL, title="Another intake"
        )

        drive(confirmation_job(other, world.editor, reply))

        assert_no_production(world.workspace)
        assert len(guided_manager.calls) == 1

    def test_confirmation_is_bound_to_the_actual_persisted_summary_message(self, world, jobs, guided_manager):
        conversation, intake_job, _ = intake(world, guided_manager)
        unrelated_reply = Message.objects.create(
            conversation=conversation,
            author_kind=Message.AuthorKind.AGENT,
            agent="account_manager",
            body="An unrelated message that does not show the brief or its sources.",
            job=intake_job,
        )

        drive(confirmation_job(conversation, world.editor, unrelated_reply))

        assert_no_production(world.workspace)
        assert len(guided_manager.calls) == 1

    def test_a_snapshot_cannot_cross_a_workspace_even_with_a_forged_job_relation(self, world, jobs, guided_manager):
        conversation, intake_job, reply = intake(world, guided_manager)
        other_workspace = Workspace.objects.create(
            organization=Organization.objects.create(name="Other agency"), name="Another brand"
        )
        AgencyJob.objects.filter(pk=intake_job.pk).update(workspace=other_workspace)

        drive(confirmation_job(conversation, world.editor, reply))

        assert_no_production(world.workspace)
        assert_no_production(other_workspace)
        assert len(guided_manager.calls) == 1

    @pytest.mark.parametrize("replacement", ["staff_message", "unknown_uuid"])
    def test_only_a_real_agent_summary_can_be_confirmed(self, world, jobs, guided_manager, replacement):
        conversation, intake_job, _ = intake(world, guided_manager)
        pk = intake_job.input["message_id"] if replacement == "staff_message" else uuid4()
        reply = type("Reference", (), {"pk": pk})()

        drive(confirmation_job(conversation, world.editor, reply))

        assert_no_production(world.workspace)
        assert len(guided_manager.calls) == 1

    def test_a_newer_intake_invalidates_the_old_snapshot(self, world, jobs, guided_manager):
        conversation, _, old_reply = intake(world, guided_manager)
        guided_manager.creative_brief = brief_fields(topic="The current different direction")
        intake(world, guided_manager, conversation=conversation, body="Actually make it about a site visit.")

        drive(confirmation_job(conversation, world.editor, old_reply))

        assert_no_production(world.workspace)
        assert len(guided_manager.calls) == 2

    def test_a_newer_queued_intake_invalidates_the_old_snapshot(self, world, jobs, guided_manager):
        conversation, _, reply = intake(world, guided_manager)
        newer = chat.post_message(conversation, world.editor, "Actually use a different topic.")
        assert newer.job.status == AgencyJob.Status.QUEUED

        drive(confirmation_job(conversation, world.editor, reply))

        assert_no_production(world.workspace)
        assert len(guided_manager.calls) == 1

    @pytest.mark.parametrize("tamper", ["author", "author_kind"])
    def test_confirmation_trigger_must_be_the_same_human_requester(self, world, jobs, guided_manager, tamper):
        conversation, _, reply = intake(world, guided_manager)
        job = confirmation_job(conversation, world.editor, reply)
        trigger = Message.objects.get(pk=job.input["message_id"])
        if tamper == "author":
            trigger.author = world.owner
            trigger.save(update_fields=["author"])
        else:
            trigger.author_kind = Message.AuthorKind.AGENT
            trigger.save(update_fields=["author_kind"])

        drive(job)

        assert_no_production(world.workspace)
        assert len(guided_manager.calls) == 1

    def test_an_unfinished_intake_cannot_be_confirmed(self, world, jobs, guided_manager):
        conversation, intake_job, reply = intake(world, guided_manager)
        AgencyJob.objects.filter(pk=intake_job.pk).update(status=AgencyJob.Status.WORKING)

        drive(confirmation_job(conversation, world.editor, reply))

        assert_no_production(world.workspace)
        assert len(guided_manager.calls) == 1

    def test_an_incomplete_snapshot_cannot_be_forced_into_generation(self, world, jobs, guided_manager):
        guided_manager.action = "answer"
        guided_manager.creative_brief = brief_fields(topic="")
        conversation, intake_job, reply = intake(world, guided_manager)
        result = {**intake_job.result, "awaiting_confirmation": True}
        AgencyJob.objects.filter(pk=intake_job.pk).update(result=result)

        drive(confirmation_job(conversation, world.editor, reply))

        assert_no_production(world.workspace)
        assert len(guided_manager.calls) == 1

    def test_revoked_posting_permissions_are_rechecked_in_the_worker(self, world, jobs, guided_manager):
        conversation, _, reply = intake(world, guided_manager)
        WorkspaceMembership.objects.filter(workspace=world.workspace, user=world.editor).update(workspace_role="viewer")

        drive(confirmation_job(conversation, world.editor, reply))

        assert_no_production(world.workspace)
        assert len(guided_manager.calls) == 1

    def test_disconnected_selected_channels_do_not_fan_out_to_other_accounts(self, world, jobs, guided_manager):
        conversation, _, reply = intake(world, guided_manager)
        world.linkedin.connection_status = "disconnected"
        world.linkedin.save(update_fields=["connection_status"])

        drive(confirmation_job(conversation, world.editor, reply))

        assert_no_production(world.workspace)
        assert len(guided_manager.calls) == 1

    def test_reconnecting_a_different_account_requires_a_new_brief_confirmation(self, world, jobs, guided_manager):
        conversation, _, reply = intake(world, guided_manager)
        world.linkedin.delete()
        SocialAccount.objects.create(
            workspace=world.workspace,
            platform="linkedin_company",
            account_platform_id="replacement-page",
            account_name="A Different Company Page",
            oauth_access_token="test-only-token",
        )

        drive(confirmation_job(conversation, world.editor, reply))

        assert_no_production(world.workspace)
        assert len(guided_manager.calls) == 1

    def test_reconnecting_the_same_row_to_another_native_account_requires_new_confirmation(
        self, world, jobs, guided_manager
    ):
        conversation, _, reply = intake(world, guided_manager)
        original_pk = world.linkedin.pk
        world.linkedin.account_platform_id = "a-different-native-company-page"
        world.linkedin.save(update_fields=["account_platform_id"])
        assert world.linkedin.pk == original_pk

        drive(confirmation_job(conversation, world.editor, reply))

        assert_no_production(world.workspace)
        assert len(guided_manager.calls) == 1

    def test_a_deactivated_requester_cannot_confirm_an_existing_brief(self, world, jobs, guided_manager):
        conversation, _, reply = intake(world, guided_manager)
        world.editor.is_active = False
        world.editor.save(update_fields=["is_active"])

        drive(confirmation_job(conversation, world.editor, reply))

        assert_no_production(world.workspace)
        assert len(guided_manager.calls) == 1

    def test_the_next_post_collects_fresh_sources_after_a_confirmed_brief(
        self, world, jobs, fake_team, guided_manager, source_collector
    ):
        conversation, _, reply = intake(world, guided_manager)
        drive(confirmation_job(conversation, world.editor, reply))

        intake(world, guided_manager, conversation=conversation, body="Create another post about our process.")

        assert len(source_collector) == 2
        assert not guided_manager.calls[-1]["creative_brief"]
        assert StudioBrief.objects.filter(workspace=world.workspace).count() == 1

    def test_day_old_evidence_that_changed_is_shown_once_more_before_the_team_starts(
        self, world, jobs, fake_team, guided_manager, source_collector, monkeypatch
    ):
        conversation, intake_job, reply = intake(world, guided_manager)
        result = intake_job.result
        result["sources"]["fetched_at"] = (timezone.now() - timedelta(hours=25)).isoformat()
        AgencyJob.objects.filter(pk=intake_job.pk).update(result=result)
        previous_collect = creative_sources.collect

        def changed_website(workspace, profile, accounts):
            fresh = previous_collect(workspace, profile, accounts)
            fresh["website"]["text"] = "A new offer appeared on the website."
            return fresh

        monkeypatch.setattr(creative_sources, "collect", changed_website)

        refreshed = drive(confirmation_job(conversation, world.editor, reply))

        assert_no_production(world.workspace)
        assert refreshed.result["awaiting_confirmation"] is True
        assert refreshed.result["evidence_changed"] == "Since this brief was proposed, the website text changed."
        fresh_reply = Message.objects.get(pk=refreshed.result["message_id"])
        assert fresh_reply.body.startswith("Since this brief was proposed, the website text changed.")
        assert "go ahead again" in fresh_reply.body
        assert len(source_collector) == 2
        assert len(guided_manager.calls) == 1

        confirmed = drive(confirmation_job(conversation, world.editor, fresh_reply))

        brief = StudioBrief.objects.get(pk=confirmed.result["brief_id"])
        assert brief.status == StudioBrief.Status.QUEUED
        assert "A new offer appeared on the website." in brief.notes
        assert len(source_collector) == 2
        assert len(guided_manager.calls) == 1


class TestHumanReference:
    def test_a_person_selected_reference_is_attached_without_model_control(
        self, world, jobs, fake_team, guided_manager, photo
    ):
        picture = photo()
        conversation, _, reply = intake(world, guided_manager, reference_id=str(picture.pk), style_mode="fresh")

        drive(confirmation_job(conversation, world.editor, reply))

        brief = StudioBrief.objects.get(workspace=world.workspace)
        assert brief.source_picture_id == picture.pk
        assert brief.style_lock is False
        assert len(guided_manager.calls) == 1

    def test_a_reference_from_another_workspace_is_rejected(self, world, jobs, guided_manager, photo):
        picture = photo()
        conversation, _, reply = intake(world, guided_manager, reference_id=str(picture.pk))
        other = Workspace.objects.create(organization=world.org, name="Another brand")
        picture.workspace = other
        picture.save(update_fields=["workspace"])

        drive(confirmation_job(conversation, world.editor, reply))

        assert_no_production(world.workspace)
        assert len(guided_manager.calls) == 1


class TestLinkedDraftRevisions:
    @staticmethod
    def ready_confirmed_brief(world, guided_manager, conversation=None):
        conversation, _, reply = intake(world, guided_manager, conversation=conversation)
        confirmation = drive(confirmation_job(conversation, world.editor, reply))
        brief = StudioBrief.objects.get(pk=confirmation.result["brief_id"])
        brief.status = StudioBrief.Status.READY
        brief.stage = StudioBrief.Stage.DONE
        brief.save(update_fields=["status", "stage"])
        return conversation, brief

    def test_a_general_thread_revises_its_one_unresolved_confirmed_draft(self, world, jobs, fake_team, guided_manager):
        conversation, brief = self.ready_confirmed_brief(world, guided_manager)
        guided_manager.action = "revise_copy"
        guided_manager.creative_brief = None
        guided_manager.instructions = "Shorten the caption without changing the facts."

        job = drive(chat.post_message(conversation, world.editor, "Make the caption shorter.").job)

        brief.refresh_from_db()
        assert brief.revision == 2 and brief.status == StudioBrief.Status.QUEUED
        assert "Shorten the caption" in brief.feedback
        assert job.result["brief_id"] == str(brief.pk)
        assert "revise_copy" in guided_manager.calls[-1]["allowed_actions"]
        assert_nothing_approved(world.workspace)

    def test_multiple_unresolved_drafts_require_the_person_to_choose(self, world, jobs, fake_team, guided_manager):
        conversation, first = self.ready_confirmed_brief(world, guided_manager)
        guided_manager.creative_brief = brief_fields(topic="A second post about the site visit")
        _, second = self.ready_confirmed_brief(world, guided_manager, conversation)
        guided_manager.action = "revise_copy"
        guided_manager.creative_brief = None

        job = drive(chat.post_message(conversation, world.editor, "Shorten it.").job)

        first.refresh_from_db()
        second.refresh_from_db()
        assert first.revision == second.revision == 1
        assert first.status == second.status == StudioBrief.Status.READY
        assert not job.result.get("brief_id")
        reply = Message.objects.get(pk=job.result["message_id"])
        assert "which" in reply.body.lower()

    def test_general_thread_cannot_revise_another_requesters_draft(self, world, jobs, fake_team, guided_manager):
        conversation, brief = self.ready_confirmed_brief(world, guided_manager)
        guided_manager.action = "revise_copy"
        guided_manager.creative_brief = None

        drive(chat.post_message(conversation, world.owner, "Shorten the caption.").job)

        brief.refresh_from_db()
        assert brief.revision == 1 and brief.status == StudioBrief.Status.READY
        assert "revise_copy" not in guided_manager.calls[-1]["allowed_actions"]

    def test_a_person_can_select_one_of_two_linked_drafts_for_revision(self, world, jobs, fake_team, guided_manager):
        conversation, first = self.ready_confirmed_brief(world, guided_manager)
        guided_manager.creative_brief = brief_fields(topic="A second post about the site visit")
        _, second = self.ready_confirmed_brief(world, guided_manager, conversation)
        guided_manager.action = "revise_copy"
        guided_manager.creative_brief = None
        guided_manager.instructions = "Shorten only the selected site's caption."
        posted = chat.post_message(conversation, world.owner, "Make this draft shorter.")
        posted.job.input["target_brief_id"] = str(second.pk)
        posted.job.save(update_fields=["input"])

        job = drive(posted.job)

        first.refresh_from_db()
        second.refresh_from_db()
        conversation.refresh_from_db()
        assert first.revision == 1 and first.status == StudioBrief.Status.READY
        assert second.revision == 2 and second.status == StudioBrief.Status.QUEUED
        assert "Shorten only the selected" in second.feedback
        assert job.result["brief_id"] == str(second.pk)
        assert conversation.brief_id is None
        assert_nothing_approved(world.workspace)

    @pytest.mark.parametrize("scope", ["another_thread", "another_workspace"])
    def test_a_forged_revision_selection_cannot_escape_the_current_thread(
        self, world, jobs, fake_team, guided_manager, scope
    ):
        conversation, own_brief = self.ready_confirmed_brief(world, guided_manager)
        foreign_workspace = (
            Workspace.objects.create(organization=world.org, name="Another brand")
            if scope == "another_workspace"
            else world.workspace
        )
        foreign_thread = Conversation.objects.create(
            workspace=foreign_workspace, audience=Conversation.Audience.INTERNAL, title="A separate thread"
        )
        foreign_job = AgencyJob.objects.create(
            workspace=foreign_workspace,
            conversation=foreign_thread,
            requested_by=world.editor,
            kind=AgencyJob.Kind.CHAT,
            status=AgencyJob.Status.DONE,
        )
        foreign_brief = StudioBrief.objects.create(
            workspace=foreign_workspace,
            author=world.editor,
            requested_by=world.editor,
            job=foreign_job,
            origin=StudioBrief.Origin.CHAT,
            idea="A draft from a different thread",
            status=StudioBrief.Status.READY,
        )
        guided_manager.action = "revise_copy"
        guided_manager.creative_brief = None
        posted = chat.post_message(conversation, world.editor, "Revise the selected draft.")
        posted.job.input["target_brief_id"] = str(foreign_brief.pk)
        posted.job.save(update_fields=["input"])
        calls_before = len(guided_manager.calls)

        job = drive(posted.job)

        own_brief.refresh_from_db()
        foreign_brief.refresh_from_db()
        assert own_brief.revision == foreign_brief.revision == 1
        assert own_brief.status == foreign_brief.status == StudioBrief.Status.READY
        assert not job.result.get("brief_id")
        assert len(guided_manager.calls) == calls_before


class TestExistingClientFlow:
    def test_client_new_post_still_creates_an_unapproved_draft_for_the_agency_lead(
        self, world, jobs, fake_team, guided_manager, client_user
    ):
        guided_manager.creative_brief = None
        guided_manager.instructions = "A Diwali greeting for Saturday"
        conversation = chat.general_conversation(world.workspace, audience=Conversation.Audience.CLIENT)

        job = drive(chat.post_message(conversation, client_user, "Can we do a Diwali post?").job)

        brief = StudioBrief.objects.get(workspace=world.workspace)
        assert brief.author_id == world.owner.pk and brief.requested_by_id == client_user.pk
        assert brief.origin == StudioBrief.Origin.CHAT and brief.job_id == job.pk
        assert brief.status == StudioBrief.Status.QUEUED
        assert brief.idea == guided_manager.instructions
        assert not guided_manager.calls[-1].get("guided")
        assert_nothing_approved(world.workspace)


class TestCreativeBriefSchema:
    def test_the_nullable_creative_brief_field_is_required_for_all_chat_answers(self):
        fields = {
            "reply": "An ordinary reply.",
            "action": "answer",
            "instructions": "",
            "needs_human": False,
            "reason": "General question.",
            "routine_instruction": "",
            "routine_cadence": "",
            "routine_weekday": -1,
            "routine_time": "",
        }
        with pytest.raises(ValidationError):
            client_roles.ChatAnswer(**fields)
        assert client_roles.ChatAnswer(**fields, creative_brief=None).creative_brief is None

    @pytest.mark.parametrize("goal", ["approve", "schedule", "publish", "anything"])
    def test_the_model_cannot_introduce_an_unrecognized_goal(self, goal):
        with pytest.raises(ValidationError):
            CreativeBrief(**brief_fields(goal=goal))

    @pytest.mark.parametrize("key", ["source_picture_id", "reference_id", "workspace_id", "requested_by_id"])
    def test_model_output_cannot_choose_database_objects(self, key):
        with pytest.raises(ValidationError):
            CreativeBrief(**brief_fields(), **{key: str(uuid4())})
