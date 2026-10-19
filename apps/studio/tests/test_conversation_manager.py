"""The conversation as a manager: defaults instead of questions, one tap, "go ahead unless I say stop",
evidence that doesn't nag, queueing instead of refusing, and lighter turns.

The account manager and the source collector are fakes; the chat worker, the
database state and the creative hand-off are real. Nothing here approves,
schedules or publishes, and the tests check that it never does.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.publisher.delivery import delivery_write
from apps.social_accounts.models import SocialAccount
from apps.studio import autopilot, chat, creative_brief, creative_sources, customer_workflow, engine
from apps.studio.brand_defaults import ensure_profile
from apps.studio.forms_agency import AgencySettingsForm
from apps.studio.jobtypes import chat as chat_job
from apps.studio.models import AgencyJob, AgencySettings, Conversation, Message, StudioBrief
from apps.studio.roles import client as client_roles
from apps.studio.tests.conftest import run_all
from apps.studio.tests.test_chat import assert_nothing_approved, drive
from apps.studio.tests.test_guided_chat import (
    GuidedManager,
    assert_no_production,
    brief_fields,
    confirmation_job,
    intake,
)
from apps.studio.tests.test_guided_chat import guided_manager as guided_manager_fixture
from apps.studio.tests.test_guided_chat import jobs as jobs_fixture
from apps.telegram import conversations
from apps.telegram.tests.test_conversations import hub as hub_fixture
from apps.telegram.tests.test_conversations import payload, send

guided_manager = guided_manager_fixture
jobs = jobs_fixture
hub = hub_fixture


@pytest.fixture(autouse=True)
def evidence(monkeypatch):
    """The source collector, faked like test_guided_chat's, recording every read.

    Defined here rather than imported: pytest registers a fixture under the
    name it finds it as, so an imported autouse fixture would run twice under
    two names and the test would hold the wrong list.
    """
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


def _url(name, world, **kwargs):
    return reverse(name, kwargs={"workspace_id": world.workspace.pk, **kwargs})


def _messages_html(client, world, conversation):
    return client.get(_url("studio:thread_messages", world, conversation_id=conversation.pk)).content.decode()


def topic_only(**overrides):
    """What a person's one sentence gives the model: a topic and nothing else."""
    fields = brief_fields(
        goal="",
        audience="",
        key_message="",
        call_to_action="",
        channels=[],
        visual_direction="",
        references="",
        constraints="",
    )
    fields.update(overrides)
    return fields


def auto_mode(workspace):
    row, _created = AgencySettings.objects.get_or_create(workspace=workspace)
    row.creation_mode = AgencySettings.CreationMode.AUTO
    row.save(update_fields=["creation_mode"])
    return row


# ---------------------------------------------------------------------------
# A2 Defaults, not questions · A3 The manager speaks
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_a_topic_alone_makes_a_complete_brief_and_the_card_says_what_was_defaulted(
        self, world, jobs, guided_manager
    ):
        profile = ensure_profile(world.workspace)
        profile.audience = "Families buying their first home in West Hyderabad"
        profile.default_cta = "WhatsApp us for the availability list"
        profile.save(update_fields=["audience", "default_cta"])
        guided_manager.creative_brief = topic_only()
        guided_manager.reply = "Got it: a post that explains the landlord's share in plain words."

        conversation, job, reply = intake(world, guided_manager)

        data = job.result["creative_brief"]
        assert job.result["awaiting_confirmation"] is True
        assert data["topic"] == "Explain the landlord's share"
        assert data["goal"] == ""  # the strategist decides
        assert data["audience"] == "Families buying their first home in West Hyderabad"
        assert data["key_message"] == data["topic"]
        assert data["call_to_action"] == "WhatsApp us for the availability list"
        assert set(data["channels"]) == {"linkedin_company", "x"}
        assert data["visual_direction"].startswith(creative_brief.VISUAL_DIRECTION["brand"])
        assert data["references"] == creative_brief.DEFAULT_REFERENCES
        assert job.result["creative_defaults"] == [
            "audience",
            "key_message",
            "call_to_action",
            "channels",
            "visual_direction",
            "references",
        ]
        assert {a["id"] for a in job.result["selected_accounts"]} == {str(world.linkedin.pk), str(world.x.pk)}
        # The reply is the manager's own words; the card carries the fields.
        assert reply.body == guided_manager.reply
        assert "Topic:" not in reply.body and "Audience:" not in reply.body
        assert_no_production(world.workspace)

    def test_a_brand_without_an_audience_or_call_to_action_still_gets_a_complete_brief(
        self, world, jobs, guided_manager
    ):
        profile = ensure_profile(world.workspace)
        profile.audience = ""
        profile.default_cta = ""
        profile.save(update_fields=["audience", "default_cta"])
        guided_manager.creative_brief = topic_only()

        _, job, _ = intake(world, guided_manager)

        data = job.result["creative_brief"]
        assert job.result["awaiting_confirmation"] is True
        assert data["audience"] == creative_brief.DEFAULT_AUDIENCE
        assert data["call_to_action"] == ""  # the copywriter decides
        assert "call_to_action" not in job.result["creative_defaults"]

    def test_the_autopilots_accounts_are_the_default_channels(self, world, jobs, guided_manager):
        row = AgencySettings.objects.create(workspace=world.workspace)
        row.accounts.set([world.x])
        guided_manager.creative_brief = topic_only()

        _, job, _ = intake(world, guided_manager)

        assert job.result["creative_brief"]["channels"] == ["x"]
        assert [a["id"] for a in job.result["selected_accounts"]] == [str(world.x.pk)]

    def test_a_fresh_look_and_the_house_style_shape_the_default_visual_direction(self, world, jobs, guided_manager):
        profile = ensure_profile(world.workspace)
        profile.house_style = "Warm dusk light, calm layouts, no stock-photo smiles."
        profile.save(update_fields=["house_style"])
        guided_manager.creative_brief = topic_only()

        _, job, _ = intake(world, guided_manager, style_mode="fresh")

        direction = job.result["creative_brief"]["visual_direction"]
        assert direction.startswith(creative_brief.VISUAL_DIRECTION["fresh"])
        assert "Warm dusk light" in direction

    def test_what_the_person_said_is_never_overwritten_by_a_default(self, world, jobs, guided_manager):
        guided_manager.creative_brief = topic_only(audience="Architects", call_to_action="Book a tour", channels=["x"])

        _, job, _ = intake(world, guided_manager)

        data = job.result["creative_brief"]
        assert data["audience"] == "Architects" and data["call_to_action"] == "Book a tour"
        assert data["channels"] == ["x"]
        assert job.result["creative_defaults"] == ["key_message", "visual_direction", "references"]

    def test_no_connected_account_means_one_sentence_and_the_card_says_what_is_missing(
        self, client, world, jobs, guided_manager
    ):
        SocialAccount.objects.filter(workspace=world.workspace).delete()
        guided_manager.creative_brief = topic_only()

        conversation, job, reply = intake(world, guided_manager)

        assert job.result["awaiting_confirmation"] is False
        assert job.result["creative_missing"] == ["channels"]
        assert reply.body == "Connect a social account first, then send the idea again."
        client.force_login(world.editor)
        html = _messages_html(client, world, conversation)
        assert "Still needed:" in html and ">Channels</span>" in html
        assert "data-confirm-brief=" not in html
        assert_no_production(world.workspace)

    def test_the_card_shows_the_defaults_as_chips_and_one_go_ahead_button(self, client, world, jobs, guided_manager):
        guided_manager.creative_brief = topic_only()
        conversation, job, reply = intake(world, guided_manager)
        client.force_login(world.editor)

        html = _messages_html(client, world, conversation)

        assert "Defaults you can change:" in html
        for label in ("Audience", "Key message", "Channels", "Visual direction", "References"):
            assert f">{label}</span>" in html
        assert html.count("data-confirm-brief=") == 1
        assert ">Go ahead</button>" in html
        assert '<input type="hidden" name="facts_confirmed" value="1">' in html
        assert 'type="checkbox" name="facts_confirmed"' not in html

    def test_clients_keep_the_full_question_round_without_defaults(self, hub, monkeypatch):
        manager = GuidedManager(creative_brief=topic_only())
        monkeypatch.setattr(client_roles, "account_manager", manager)
        auto_mode(hub.ws)

        send(hub, "/brief Explain landlord shares", role="client")
        job = AgencyJob.objects.get()
        engine.run_step(str(job.pk), job.revision, job.stage)

        job.refresh_from_db()
        assert job.status == "done" and job.result["awaiting_confirmation"] is False
        assert job.result["creative_defaults"] == []
        assert job.result["creative_brief"]["audience"] == ""
        assert "goal" in job.result["creative_missing"] and "audience" in job.result["creative_missing"]
        assert not StudioBrief.objects.exists() and not hub.production
        reply = Message.objects.filter(author_kind="agent").get()
        assert "Before the team creates a draft" in reply.body


class TestManagerReply:
    def test_a_reply_claiming_work_started_is_replaced_while_the_card_waits(self, world, jobs, guided_manager):
        guided_manager.reply = "On it — I've started drafting this and it will be ready soon."

        _, job, reply = intake(world, guided_manager)

        assert job.result["awaiting_confirmation"] is True
        assert reply.body == chat_job.GO_AHEAD_REPLY
        assert_no_production(world.workspace)

    def test_long_replies_are_trimmed_to_four_sentences(self, world, jobs, guided_manager):
        guided_manager.reply = "One. Two! Three? Four. Five. Six."

        _, _, reply = intake(world, guided_manager)

        assert reply.body == "One. Two! Three? Four."

    def test_an_empty_reply_becomes_the_go_ahead_sentence(self, world, jobs, guided_manager):
        guided_manager.reply = "   "

        _, _, reply = intake(world, guided_manager)

        assert reply.body == chat_job.GO_AHEAD_REPLY

    def test_the_account_manager_is_told_about_the_card_and_the_create_request(self, world, monkeypatch):
        captured = {}
        monkeypatch.setattr(client_roles.base, "ask", lambda *args, **kwargs: captured.update(kwargs))

        client_roles.account_manager(
            ensure_profile(world.workspace),
            audience="internal",
            speaker="staff",
            history=[],
            item="The workspace in general.",
            request="A post about the new parking",
            request_kind="create",
            allowed_actions=["answer", "new_post"],
            guided=True,
            creative_brief={},
            sources={},
            available_channels=["linkedin_company"],
        )

        assert "They want a post made from this idea" in captured["content"]
        assert "do not repeat the fields in your reply" in captured["instructions"]
        assert "at most, one short question" in captured["instructions"]


# ---------------------------------------------------------------------------
# A1 One way in
# ---------------------------------------------------------------------------


class TestOneWayIn:
    def test_the_form_sends_the_persons_own_words_and_its_choices_as_fields(
        self, client, world, photo, jobs, guided_manager
    ):
        picture = photo()
        guided_manager.creative_brief = topic_only(topic="Our new covered parking")
        client.force_login(world.editor)

        response = client.post(
            _url("studio:create", world),
            {
                "idea": "Tell buyers about the new covered parking",
                "notes": "Mention it is free for residents",
                "goal": "awareness",
                "accounts": [world.x.pk],
                "source_picture": str(picture.pk),
                "style_lock": "on",
            },
        )

        assert response.status_code == 302
        job = AgencyJob.objects.get(kind=AgencyJob.Kind.CHAT)
        trigger = Message.objects.get(pk=job.input["message_id"])
        assert trigger.body == "Tell buyers about the new covered parking"
        assert job.input["kind"] == "create"
        assert job.input["create"] == {
            "goal": "awareness",
            "notes": "Mention it is free for residents",
            "accounts": [str(world.x.pk)],
        }
        assert job.input["reference_id"] == str(picture.pk) and job.input["style_mode"] == "brand"
        conversation = Conversation.objects.get(pk=job.conversation_id)
        assert response["Location"].endswith(f"?c={conversation.pk}")
        assert conversation.messages.filter(action=customer_workflow.IDEA_ACTION).exists()
        assert chat.find_general(world.workspace) is None  # its own conversation, not the general thread

        drive(job)

        job.refresh_from_db()
        call = guided_manager.calls[0]
        assert call["request_kind"] == "create"
        assert call["creative_brief"]["goal"] == "awareness" and call["creative_brief"]["channels"] == ["x"]
        data = job.result["creative_brief"]
        assert data["goal"] == "awareness"
        assert "Mention it is free for residents" in data["constraints"]
        assert data["channels"] == ["x"]
        assert data["references"].startswith("Use the selected reference")
        assert job.result["awaiting_confirmation"] is True
        assert_no_production(world.workspace)

    def test_a_saved_idea_starts_in_the_persons_own_words(self, world, jobs, guided_manager):
        conversation = customer_workflow.save_idea(
            world.workspace, world.editor, request_id=__import__("uuid").uuid4(), idea="A Diwali greeting"
        )

        started = customer_workflow.start_idea(world.workspace, world.editor, conversation.pk)

        trigger = Message.objects.get(pk=started.job.input["message_id"])
        assert trigger.body == "A Diwali greeting"
        assert started.job.input["kind"] == "create" and started.job.input["create"] == {
            "goal": "",
            "notes": "",
            "accounts": [],
        }

    def test_create_extras_are_checked_against_this_workspace(self, world, jobs):
        foreign = SocialAccount.objects.create(
            workspace=__import__("apps.workspaces.models", fromlist=["Workspace"]).Workspace.objects.create(
                organization=world.org, name="Other"
            ),
            platform="x",
            account_platform_id="999",
            account_name="other",
        )
        conversation = chat.general_conversation(world.workspace)
        with pytest.raises(chat.ChatError, match="connected accounts of this workspace"):
            chat.post_message(conversation, world.editor, "Idea", kind="create", create={"accounts": [foreign.pk]})
        assert not AgencyJob.objects.exists()

    def test_clients_cannot_send_the_create_kind(self, world, jobs):
        client = User.objects.create_user(email="c@example.com", password="pw-12345678", name="C")
        WorkspaceMembership.objects.create(user=client, workspace=world.workspace, workspace_role="client")
        conversation = chat.general_conversation(world.workspace, audience=Conversation.Audience.CLIENT)
        with pytest.raises(chat.ChatError, match="team's own conversation"):
            chat.post_message(conversation, client, "Idea", kind="create")


# ---------------------------------------------------------------------------
# A4 One tap, and "go unless I say stop"
# ---------------------------------------------------------------------------


class TestOneTap:
    def test_go_ahead_from_the_card_starts_the_team_and_nothing_is_approved(
        self, client, world, jobs, fake_team, guided_manager
    ):
        guided_manager.creative_brief = topic_only()
        conversation, job, reply = intake(world, guided_manager)
        client.force_login(world.editor)

        response = client.post(
            _url("studio:thread_send", world, conversation_id=conversation.pk),
            {
                "kind": "confirm_brief",
                "confirmation_message_id": str(reply.pk),
                "body": "Go ahead with this brief.",
                "facts_confirmed": "1",
            },
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 200
        confirmation = AgencyJob.objects.get(input__kind="confirm_brief")
        assert confirmation.input["facts_confirmed"] is True
        drive(confirmation)
        brief = StudioBrief.objects.get(workspace=world.workspace)
        assert brief.status == StudioBrief.Status.QUEUED and brief.goal == ""
        assert "Audience: " in brief.notes
        assert Message.objects.get(pk=confirmation.result["message_id"]).body == chat_job.STARTED_REPLY
        assert_nothing_approved(world.workspace)

    def test_the_card_offers_next_time_just_go_ahead_only_to_settings_managers(
        self, client, world, jobs, guided_manager
    ):
        guided_manager.creative_brief = topic_only()
        conversation, _, _ = intake(world, guided_manager, requester=world.owner)
        client.force_login(world.owner)
        assert 'data-creation-mode="auto"' in _messages_html(client, world, conversation)

        intake(world, guided_manager, requester=world.editor, conversation=conversation)
        client.force_login(world.editor)
        html = _messages_html(client, world, conversation)
        assert "data-confirm-brief=" in html and 'data-creation-mode="auto"' not in html


class TestAutoMode:
    def test_auto_mode_starts_the_brief_at_once_and_the_post_still_waits_for_approval(
        self, world, jobs, fake_team, guided_manager
    ):
        auto_mode(world.workspace)
        guided_manager.creative_brief = topic_only()
        guided_manager.reply = "Got it, a landlord's share explainer."

        conversation, job, reply = intake(world, guided_manager)

        brief = StudioBrief.objects.get(workspace=world.workspace)
        assert brief.status == StudioBrief.Status.QUEUED and brief.origin == StudioBrief.Origin.CHAT
        assert brief.requested_by == world.editor and brief.author == world.editor and brief.job_id == job.pk
        assert set(brief.social_accounts.all()) == {world.linkedin, world.x}
        assert job.result["auto_started"] is True and job.result["awaiting_confirmation"] is False
        assert job.result["brief_id"] == str(brief.pk)
        assert reply.action_status == Message.ActionStatus.STARTED
        assert reply.body == (
            "On it — a post about Explain the landlord's share for LinkedIn (Company Page) and X (Twitter). "
            "It comes back here for your approval."
        )
        assert fake_team.queued == [(brief.pk, 1, "strategy")]

        run_all(brief)

        assert brief.status == StudioBrief.Status.READY
        assert set(PlatformPost.objects.filter(post=brief.post).values_list("status", flat=True)) == {"pending_review"}
        assert_nothing_approved(world.workspace)

    def test_auto_mode_only_follows_a_new_post_action(self, world, jobs, fake_team, guided_manager):
        auto_mode(world.workspace)
        guided_manager.action = "answer"
        guided_manager.creative_brief = topic_only()

        _, job, _ = intake(world, guided_manager, body="Could we do something on landlord shares?")

        assert job.result["awaiting_confirmation"] is True and not job.result.get("auto_started")
        assert_no_production(world.workspace)

    def test_auto_mode_waits_for_the_tap_when_something_is_missing(self, world, jobs, fake_team, guided_manager):
        auto_mode(world.workspace)
        SocialAccount.objects.filter(workspace=world.workspace).delete()
        guided_manager.creative_brief = topic_only()

        _, job, reply = intake(world, guided_manager)

        assert job.result["awaiting_confirmation"] is False and not job.result.get("auto_started")
        assert reply.body == "Connect a social account first, then send the idea again."
        assert_no_production(world.workspace)

    def test_the_card_shows_started_and_stop_and_stop_discards_the_brief(
        self, client, world, jobs, fake_team, guided_manager
    ):
        auto_mode(world.workspace)
        guided_manager.creative_brief = topic_only()
        conversation, job, _ = intake(world, guided_manager)
        brief = StudioBrief.objects.get(workspace=world.workspace)
        client.force_login(world.editor)

        html = _messages_html(client, world, conversation)
        assert f'data-brief-started="{brief.pk}"' in html and ">See progress</a>" in html and "Started" in html
        assert f'data-stop-brief="{brief.pk}"' in html and "data-confirm-brief=" not in html
        stop_url = _url("studio:thread_stop_brief", world, conversation_id=conversation.pk, brief_id=brief.pk)
        assert stop_url in html

        response = client.post(stop_url, {}, HTTP_HX_REQUEST="true")

        assert response.status_code == 200
        brief.refresh_from_db()
        assert brief.status == StudioBrief.Status.DISCARDED
        page = response.content.decode()
        assert "stopped this post before the draft was made." in page
        assert f'data-stop-brief="{brief.pk}"' not in page and "Stopped" in page
        assert_nothing_approved(world.workspace)

    def test_only_the_requester_or_an_approver_can_stop(self, client, world, jobs, fake_team, guided_manager):
        auto_mode(world.workspace)
        guided_manager.creative_brief = topic_only()
        conversation, _, _ = intake(world, guided_manager)
        brief = StudioBrief.objects.get(workspace=world.workspace)
        other = User.objects.create_user(
            email="e2@example.com", password="pw-12345678", name="Second editor", tos_accepted_at=timezone.now()
        )
        OrgMembership.objects.create(user=other, organization=world.org, org_role="member")
        WorkspaceMembership.objects.create(user=other, workspace=world.workspace, workspace_role="editor")
        stop_url = _url("studio:thread_stop_brief", world, conversation_id=conversation.pk, brief_id=brief.pk)

        client.force_login(other)
        assert client.post(stop_url, {}).status_code == 403
        brief.refresh_from_db()
        assert brief.status == StudioBrief.Status.QUEUED

        client.force_login(world.owner)
        assert client.post(stop_url, {}).status_code == 302
        brief.refresh_from_db()
        assert brief.status == StudioBrief.Status.DISCARDED

    def test_a_brief_from_another_thread_cannot_be_stopped_through_this_one(
        self, client, world, jobs, fake_team, guided_manager
    ):
        auto_mode(world.workspace)
        guided_manager.creative_brief = topic_only()
        _, _, _ = intake(world, guided_manager)
        brief = StudioBrief.objects.get(workspace=world.workspace)
        other_thread = Conversation.objects.create(
            workspace=world.workspace, audience=Conversation.Audience.INTERNAL, title="Elsewhere"
        )
        client.force_login(world.editor)

        response = client.post(
            _url("studio:thread_stop_brief", world, conversation_id=other_thread.pk, brief_id=brief.pk), {}
        )

        assert response.status_code == 404
        brief.refresh_from_db()
        assert brief.status == StudioBrief.Status.QUEUED

    def test_switching_the_mode_needs_workspace_settings_rights(self, client, world):
        url = _url("studio:creation_mode", world)
        client.force_login(world.editor)
        assert client.post(url, {"mode": "auto"}).status_code == 403
        assert chat.creation_mode(world.workspace) == "confirm"

        client.force_login(world.owner)
        response = client.post(url, {"mode": "auto", "next": "https://evil.example/"})
        assert response.status_code == 302 and response["Location"] == _url("studio:thread", world)
        assert chat.creation_mode(world.workspace) == "auto"

        response = client.post(url, {"mode": "confirm", "next": _url("studio:thread", world) + "?c=x"})
        assert response["Location"] == _url("studio:thread", world) + "?c=x"
        assert chat.creation_mode(world.workspace) == "confirm"
        assert client.post(url, {"mode": "whatever"}).status_code == 404

    def test_the_settings_form_keeps_the_saved_mode_when_the_field_is_absent(self, world):
        row = auto_mode(world.workspace)
        form = AgencySettingsForm(
            {
                "posts_per_week": "5",
                "plan_weekday": "4",
                "plan_hour": "16",
                "blog_posts_per_month": "0",
                "monthly_budget_usd": "150",
            },
            instance=row,
            workspace=world.workspace,
        )

        assert form.is_valid(), form.errors
        assert form.cleaned_data["creation_mode"] == "auto"
        assert "creation_mode" in form.fields

    def test_a_private_telegram_chat_of_a_team_member_goes_ahead_in_auto_mode(self, hub, monkeypatch):
        auto_mode(hub.ws)
        manager = GuidedManager(creative_brief=topic_only())
        monkeypatch.setattr(client_roles, "account_manager", manager)
        message = payload(hub, "/brief Explain landlord shares", role="editor")
        message["message"]["chat"] = {"id": hub.links["editor"].telegram_user_id, "type": "private"}

        conversations.handle_message(hub.connection, message)
        job = AgencyJob.objects.get()
        engine.run_step(str(job.pk), job.revision, job.stage)

        job.refresh_from_db()
        assert job.status == "done" and job.result["auto_started"] is True
        brief = StudioBrief.objects.get()
        assert brief.status == "queued" and brief.author == hub.users["editor"] and not Post.objects.exists()
        assert hub.production == [(brief.pk, "strategy")]
        assert Message.objects.filter(author_kind="agent").get().body.startswith("On it — ")
        private = Conversation.objects.get(pk=job.conversation_id)
        assert private.is_private and chat.is_private_conversation(private)
        assert not chat.web_jobs(AgencyJob.objects.all()).exists()  # private history never reaches the dashboard

    def test_a_telegram_team_group_still_waits_for_the_tap_in_auto_mode(self, hub, monkeypatch):
        auto_mode(hub.ws)
        manager = GuidedManager(creative_brief=topic_only())
        monkeypatch.setattr(client_roles, "account_manager", manager)

        send(hub, "/brief Explain landlord shares", role="editor", bound=hub.team_chat)
        job = AgencyJob.objects.get()
        engine.run_step(str(job.pk), job.revision, job.stage)

        job.refresh_from_db()
        assert job.result["awaiting_confirmation"] is True and not job.result.get("auto_started")
        assert not StudioBrief.objects.exists() and not hub.production
        assert "Send /brief" in Message.objects.filter(author_kind="agent").get().body


# ---------------------------------------------------------------------------
# A5 Evidence that doesn't nag
# ---------------------------------------------------------------------------


class TestEvidence:
    @staticmethod
    def _age(intake_job, hours):
        result = intake_job.result
        result["sources"]["fetched_at"] = (timezone.now() - timedelta(hours=hours)).isoformat()
        AgencyJob.objects.filter(pk=intake_job.pk).update(result=result)

    def test_evidence_from_this_morning_is_not_read_again(self, world, jobs, fake_team, guided_manager, evidence):
        conversation, intake_job, reply = intake(world, guided_manager)
        self._age(intake_job, hours=6)

        confirmed = drive(confirmation_job(conversation, world.editor, reply))

        assert StudioBrief.objects.get(pk=confirmed.result["brief_id"]).status == StudioBrief.Status.QUEUED
        assert len(evidence) == 1

    def test_day_old_unchanged_evidence_is_refreshed_silently(self, world, jobs, fake_team, guided_manager, evidence):
        conversation, intake_job, reply = intake(world, guided_manager)
        self._age(intake_job, hours=25)

        confirmed = drive(confirmation_job(conversation, world.editor, reply))

        brief = StudioBrief.objects.get(pk=confirmed.result["brief_id"])
        assert brief.status == StudioBrief.Status.QUEUED
        assert len(evidence) == 2
        refreshed_at = confirmed.result["sources"]["fetched_at"]
        assert timezone.now() - timezone.datetime.fromisoformat(refreshed_at) < timedelta(minutes=5)
        assert not confirmed.result.get("evidence_changed")

    def test_digest_tracks_the_text_a_person_checks_and_nothing_else(self):
        sources = {
            "fetched_at": "2026-10-18T08:00:00+00:00",
            "website": {"excerpt": "Premium homes.", "status": "ready"},
            "channels": [{"account_id": "1", "posts": [{"caption": "Site visit Saturday", "published_at": "x"}]}],
            "notes": ["a"],
        }
        same = {**sources, "fetched_at": "2026-10-19T08:00:00+00:00", "notes": ["b"]}
        changed_site = {**sources, "website": {"excerpt": "New offer!", "status": "ready"}}
        changed_posts = {
            **sources,
            "channels": [{"account_id": "1", "account_name": "Page", "posts": [{"caption": "Different"}]}],
        }

        assert creative_sources.digest(sources) == creative_sources.digest(same)
        assert creative_sources.digest(sources) != creative_sources.digest(changed_site)
        assert (
            creative_sources.changes(sources, changed_site)
            == "Since this brief was proposed, the website text changed."
        )
        assert (
            creative_sources.changes(sources, changed_posts)
            == "Since this brief was proposed, recent posts on Page changed."
        )
        assert creative_sources.changes(sources, same) == ""
        assert creative_sources.digest(None) == creative_sources.digest({})

    def test_each_refusal_says_why_in_one_sentence(self, world, jobs, guided_manager):
        conversation, _, reply = intake(world, guided_manager)

        later = chat.post_message(conversation, world.editor, "Actually, make it about parking.")
        assert later.job.status == AgencyJob.Status.QUEUED
        blocked = drive(confirmation_job(conversation, world.editor, reply))
        assert Message.objects.get(pk=blocked.result["message_id"]).body == chat_job.NEWER_MESSAGE

        guided_manager.creative_brief = brief_fields(topic="Parking")
        drive(later.job)
        blocked = drive(confirmation_job(conversation, world.editor, reply))
        assert Message.objects.get(pk=blocked.result["message_id"]).body == chat_job.NEWER_BRIEF

        unconfirmed = drive(confirmation_job(conversation, world.editor, reply, facts_confirmed=False))
        assert Message.objects.get(pk=unconfirmed.result["message_id"]).body == chat_job.NOT_YOURS

        forged = type("Reference", (), {"pk": "not-a-uuid"})()
        bad = drive(confirmation_job(conversation, world.editor, forged))
        assert Message.objects.get(pk=bad.result["message_id"]).body == chat_job.NOT_CURRENT
        assert_no_production(world.workspace)

    def test_the_first_turn_always_collects_evidence_for_an_empty_brief(self, world, jobs, guided_manager, evidence):
        guided_manager.action = "answer"
        guided_manager.creative_brief = None

        intake(world, guided_manager, body="When is the weekly report?")

        assert len(evidence) == 1


# ---------------------------------------------------------------------------
# A6 Faster turns · A7 Queue, don't refuse
# ---------------------------------------------------------------------------


class TestLighterTurns:
    def test_the_manager_reads_twelve_messages_of_six_hundred_characters(self, world):
        conversation = chat.general_conversation(world.workspace, created_by=world.editor)
        for number in range(15):
            Message.objects.create(
                conversation=conversation,
                author=world.editor,
                author_kind=Message.AuthorKind.STAFF,
                body=f"m{number:02d} " + "x" * 1000,
            )
        trigger = Message.objects.create(
            conversation=conversation, author=world.editor, author_kind=Message.AuthorKind.STAFF, body="Now?"
        )

        lines = chat_job.history(conversation, trigger, for_client=False)

        assert len(lines) == 12
        assert "m03 " in lines[0] and "m14 " in lines[-1] and not any("m02 " in line for line in lines)
        assert all("x" * 596 in line and "x" * 597 not in line for line in lines)

    def test_receipts_are_worked_out_only_for_the_draft_in_view_and_pending_deliveries(
        self, client, world, jobs, monkeypatch
    ):
        conversation = chat.general_conversation(world.workspace)
        briefs = {}
        for name, status in (("finished", "pending_review"), ("going_out", "scheduled"), ("in_view", "pending_review")):
            job = AgencyJob.objects.create(
                workspace=world.workspace,
                conversation=conversation,
                requested_by=world.editor,
                kind=AgencyJob.Kind.CHAT,
                status=AgencyJob.Status.DONE,
            )
            post = Post.objects.create(workspace=world.workspace, author=world.editor, caption=name)
            with delivery_write():
                PlatformPost.objects.create(post=post, social_account=world.linkedin, status=status)
            briefs[name] = StudioBrief.objects.create(
                workspace=world.workspace,
                author=world.editor,
                requested_by=world.editor,
                origin=StudioBrief.Origin.CHAT,
                job=job,
                post=post,
                status=StudioBrief.Status.READY,
                idea=name,
            )
            job.result = {"brief_id": str(briefs[name].pk)}
            job.save(update_fields=["result"])
            Message.objects.create(conversation=conversation, job=job, author_kind=Message.AuthorKind.AGENT, body=name)
        seen = []
        original = chat._publication_receipts
        monkeypatch.setattr(
            chat,
            "_publication_receipts",
            lambda brief, *args, **kwargs: seen.append(brief.pk) or original(brief, *args, **kwargs),
        )
        client.force_login(world.editor)

        html = _messages_html(client, world, conversation)

        assert set(seen) == {briefs["going_out"].pk, briefs["in_view"].pk}
        assert f'data-publication-receipt="{briefs["going_out"].pk}"' in html
        assert f'data-publication-receipt="{briefs["finished"].pk}"' not in html
        assert 'hx-trigger="every 30s"' in html

    def test_the_thread_polls_every_three_seconds_while_the_manager_works(self, client, world, jobs):
        conversation = chat.general_conversation(world.workspace)
        posted = chat.post_message(conversation, world.editor, "A post about parking")
        assert posted.job is not None
        client.force_login(world.editor)

        html = _messages_html(client, world, conversation)

        assert 'hx-trigger="every 3s"' in html and "Your manager is writing a reply" in html


class TestQueue:
    def test_the_feeder_starts_waiting_chat_briefs_when_a_slot_frees(self, world, jobs, fake_team, guided_manager):
        auto_mode(world.workspace)
        guided_manager.creative_brief = topic_only()
        conversation, first, _ = intake(world, guided_manager)
        guided_manager.creative_brief = topic_only(topic="A second post")
        _, second, _ = intake(world, guided_manager, conversation=conversation, body="A second post")
        guided_manager.creative_brief = topic_only(topic="A third post")
        _, third, reply = intake(world, guided_manager, conversation=conversation, body="A third post")

        waiting = StudioBrief.objects.get(pk=third.result["brief_id"])
        assert waiting.status == StudioBrief.Status.PLANNED and third.result["queued"] is True
        assert reply.body == chat_job.QUEUED_REPLY and reply.action_status == Message.ActionStatus.STARTED
        assert len(fake_team.queued) == 2
        assert autopilot.feed_planned_briefs() == 0  # the team is full

        StudioBrief.objects.filter(pk__in=[first.result["brief_id"], second.result["brief_id"]]).update(
            status=StudioBrief.Status.READY
        )

        assert autopilot.feed_planned_briefs() == 1
        waiting.refresh_from_db()
        assert waiting.status == StudioBrief.Status.QUEUED and len(fake_team.queued) == 3
        assert_nothing_approved(world.workspace)

    def test_a_waiting_brief_can_be_stopped_from_its_card(self, client, world, jobs, fake_team, guided_manager):
        auto_mode(world.workspace)
        for number in range(2):
            StudioBrief.objects.create(
                workspace=world.workspace,
                author=world.editor,
                requested_by=world.editor,
                origin=StudioBrief.Origin.CHAT,
                idea=f"Busy {number}",
                status=StudioBrief.Status.WORKING,
            )
        guided_manager.creative_brief = topic_only()
        conversation, job, _ = intake(world, guided_manager)
        waiting = StudioBrief.objects.get(pk=job.result["brief_id"])
        assert waiting.status == StudioBrief.Status.PLANNED
        client.force_login(world.editor)

        html = _messages_html(client, world, conversation)
        assert "Queued" in html and f'data-stop-brief="{waiting.pk}"' in html
        client.post(_url("studio:thread_stop_brief", world, conversation_id=conversation.pk, brief_id=waiting.pk), {})

        waiting.refresh_from_db()
        assert waiting.status == StudioBrief.Status.DISCARDED
        assert autopilot.feed_planned_briefs() == 0
