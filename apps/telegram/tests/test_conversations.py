"""Real paired identity, conversation isolation and guided production boundaries."""

from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import PlatformPost, Post
from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.studio import chat, creative_sources, engine, pipeline
from apps.studio.models import AgencyJob, Conversation, Message, StudioBrief
from apps.studio.roles import client as client_roles
from apps.studio.tests.test_guided_chat import GuidedManager
from apps.telegram import actions, conversations, weekly
from apps.telegram.models import TelegramChat, TelegramConnection, TelegramUserLink
from apps.workspaces.models import Workspace


@pytest.fixture
def hub(db, settings, monkeypatch):
    settings.ANTHROPIC_API_KEY = "local-fake-no-api"
    settings.STUDIO_LLM_PROVIDER = "anthropic"
    org = Organization.objects.create(name="Telegram agency")
    ws = Workspace.objects.create(organization=org, name="Neopolis", timezone="Asia/Kolkata")
    users = {}
    for role in ["owner", "editor", "client", "viewer"]:
        user = User.objects.create_user(
            email=f"tg-{role}@example.test", password="not-used", name=role, tos_accepted_at=timezone.now()
        )
        OrgMembership.objects.create(organization=org, user=user, org_role="owner" if role == "owner" else "member")
        WorkspaceMembership.objects.create(workspace=ws, user=user, workspace_role=role)
        users[role] = user
    connection = TelegramConnection.objects.create(
        workspace=ws,
        token="test-fake-token",
        webhook_secret="test-fake-secret",
        bot_id=12345,
        bot_username="fixture_bot",
        is_active=True,
        approvals_enabled=True,
    )
    links = {
        role: TelegramUserLink.objects.create(connection=connection, user=user, telegram_user_id=index)
        for index, (role, user) in enumerate(users.items(), start=101)
    }
    client_thread = Conversation.objects.create(workspace=ws, audience="client", title="Client group")
    team_thread = Conversation.objects.create(workspace=ws, audience="internal", title="Team group")
    client_chat = TelegramChat.objects.create(
        connection=connection, chat_id=-100, chat_type="supergroup", audience="client", conversation=client_thread
    )
    team_chat = TelegramChat.objects.create(
        connection=connection, chat_id=-200, chat_type="group", audience="team", conversation=team_thread
    )
    account = SocialAccount.objects.create(
        workspace=ws,
        platform="linkedin_company",
        account_platform_id="native-page",
        account_name="Neopolis",
        oauth_access_token="fake",
    )
    queued, production = [], []
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: queued.append((job.pk, stage)))
    monkeypatch.setattr(pipeline, "enqueue", lambda brief, stage: production.append((brief.pk, stage)))
    monkeypatch.setattr(chat, "notify_staff_of_client_message", lambda *a, **k: None)
    monkeypatch.setattr(chat, "notify_clients_of_reply", lambda *a, **k: None)
    monkeypatch.setattr(chat, "notify_staff", lambda *a, **k: None)
    monkeypatch.setattr(
        creative_sources,
        "collect",
        lambda *a, **k: {
            "fetched_at": timezone.now().isoformat(),
            "website": {"status": "ready", "url": "https://source.example.test/", "excerpt": "Synthetic reference"},
            "channels": [],
            "notes": [],
        },
    )
    return SimpleNamespace(
        org=org,
        ws=ws,
        users=users,
        links=links,
        connection=connection,
        client_chat=client_chat,
        team_chat=team_chat,
        account=account,
        queued=queued,
        production=production,
    )


def payload(hub, text, *, role="editor", bound=None, **extra):
    bound = bound or hub.client_chat
    message = {
        "message_id": 1,
        "from": {"id": hub.links[role].telegram_user_id, "is_bot": False, "username": "irrelevant"},
        "chat": {"id": bound.chat_id, "type": bound.chat_type},
        "text": text,
        **extra,
    }
    return {"update_id": 99, "message": message}


def send(hub, text, **kwargs):
    return conversations.handle_message(hub.connection, payload(hub, text, **kwargs))


def linked_post(hub, *, bound=None, status="pending_review"):
    bound = bound or hub.client_chat
    job = AgencyJob.objects.create(
        workspace=hub.ws, conversation=bound.conversation, kind="chat", requested_by=hub.users["editor"], status="done"
    )
    post = Post.objects.create(workspace=hub.ws, author=hub.users["editor"], caption="Exact scoped caption")
    pp = PlatformPost.objects.create(post=post, social_account=hub.account, status=status)
    brief = StudioBrief.objects.create(
        workspace=hub.ws,
        author=hub.users["editor"],
        requested_by=hub.users["editor"],
        origin="chat",
        job=job,
        post=post,
        idea="Exact scoped draft",
        status="ready",
    )
    return post, pp, brief


@pytest.mark.parametrize("command", ["/brief A site visit post", "/brainstorm Better buyer questions"])
def test_staff_explicit_group_request_uses_existing_engine_and_own_identity(hub, command):
    result = send(hub, command)
    job = AgencyJob.objects.get()
    assert result["job_id"] == str(job.pk) and job.requested_by == hub.users["editor"]
    assert job.conversation == hub.client_chat.conversation and job.input["explicit_assistant_request"] is True
    assert Message.objects.get().author_kind == "staff"
    assert not StudioBrief.objects.exists() and not Post.objects.exists()
    assert hub.queued == [(job.pk, "answer")]


def test_staff_casual_client_reply_preserves_existing_silent_assistant_behavior(hub):
    result = send(hub, "Thanks, I'll check the site photograph.")
    assert result["job_id"] == "" and not AgencyJob.objects.exists()
    assert Message.objects.get().author == hub.users["editor"]


@pytest.mark.parametrize("text", ["/brief Create this post", "yes", "approve and publish it now"])
def test_client_inputs_stay_client_requests_without_creative_or_approval_mutations(hub, text):
    result = send(hub, text, role="client")
    job = AgencyJob.objects.get()
    assert result["job_id"] == str(job.pk) and job.requested_by == hub.users["client"]
    assert job.input["explicit_assistant_request"] is False
    assert Message.objects.get().author_kind == "client"
    assert not StudioBrief.objects.exists() and not Post.objects.exists()


def test_custom_client_facing_create_permission_never_changes_client_attribution(hub):
    role = CustomRole.objects.create(
        organization=hub.org,
        name="Customer",
        permissions={"client_facing": True, "create_posts": True, "approve_posts": True},
    )
    WorkspaceMembership.objects.filter(workspace=hub.ws, user=hub.users["editor"]).update(custom_role=role)
    send(hub, "/brief Start an offer")
    assert Message.objects.get().author_kind == "client"
    assert AgencyJob.objects.get().input["explicit_assistant_request"] is False


@pytest.mark.parametrize("mutation", ["connection", "link", "org", "workspace", "archived", "deleting", "user"])
def test_revoked_access_is_checked_before_any_message_or_job(hub, mutation):
    if mutation == "connection":
        TelegramConnection.objects.filter(pk=hub.connection.pk).update(is_active=False)
    elif mutation == "link":
        hub.links["editor"].is_active = False
        hub.links["editor"].save()
    elif mutation == "org":
        OrgMembership.objects.filter(organization=hub.org, user=hub.users["editor"]).delete()
    elif mutation == "workspace":
        WorkspaceMembership.objects.filter(workspace=hub.ws, user=hub.users["editor"]).delete()
    elif mutation == "archived":
        Workspace.objects.filter(pk=hub.ws.pk).update(is_archived=True)
    elif mutation == "deleting":
        Organization.objects.filter(pk=hub.org.pk).update(deletion_requested_at=timezone.now())
    else:
        User.objects.filter(pk=hub.users["editor"].pk).update(is_active=False)
    result = send(hub, "/brief Start")
    assert not Message.objects.exists() and not AgencyJob.objects.exists()
    assert "access" in result["text"]


@pytest.mark.parametrize("bad", ["unknown", "bot", "anonymous", "bool"])
def test_numeric_sender_proof_cannot_be_replaced_by_names_or_anonymous_identity(hub, bad):
    item = payload(hub, "/brief Start")
    if bad == "unknown":
        item["message"]["from"]["id"] = 999
    elif bad == "bot":
        item["message"]["from"]["is_bot"] = True
    elif bad == "anonymous":
        item["message"]["sender_chat"] = {"id": -100}
    else:
        item["message"]["from"]["id"] = True
    result = conversations.handle_message(hub.connection, item)
    assert not Message.objects.exists() and not AgencyJob.objects.exists() and "access" in result["text"]


def test_forwarded_owner_identity_does_not_impersonate_actual_client_sender(hub):
    send(hub, "Please make this post", role="client", forward_from={"id": hub.links["owner"].telegram_user_id})
    assert Message.objects.get().author == hub.users["client"] and Message.objects.get().author_kind == "client"


def test_foreign_bound_conversation_fails_without_tenant_disclosure(hub):
    foreign = Workspace.objects.create(
        organization=Organization.objects.create(name="Other"), name="Private other brand"
    )
    conversation = Conversation.objects.create(workspace=foreign, audience="client")
    TelegramChat.objects.filter(pk=hub.client_chat.pk).update(conversation=conversation)
    result = send(hub, "/status")
    assert "Private other brand" not in result["text"] and "another workspace" in result["text"]
    assert not Message.objects.exists()


def test_private_workers_keep_distinct_history_and_cannot_post_as_another_user(hub):
    first = payload(hub, "/brief Private question", role="owner")
    first["message"]["chat"] = {"id": hub.links["owner"].telegram_user_id, "type": "private"}
    second = payload(hub, "/brief Another private question", role="editor")
    second["message"]["chat"] = {"id": hub.links["editor"].telegram_user_id, "type": "private"}
    conversations.handle_message(hub.connection, first)
    conversations.handle_message(hub.connection, second)
    chats = list(TelegramChat.objects.filter(audience="private"))
    assert len(chats) == 2 and chats[0].conversation_id != chats[1].conversation_id
    second["message"]["chat"]["id"] = hub.links["owner"].telegram_user_id
    response = conversations.handle_message(hub.connection, second)
    assert "access" in response["text"] and AgencyJob.objects.count() == 2


def test_private_conversation_cannot_share_group_history(hub):
    private = TelegramChat.objects.create(
        connection=hub.connection,
        chat_id=101,
        chat_type="private",
        audience="private",
        private_user=hub.users["owner"],
        conversation=hub.team_chat.conversation,
    )
    with pytest.raises(chat.ChatError, match="share group history"):
        chat.telegram_member(
            private.conversation,
            hub.users["owner"],
            {"chat_id": str(private.pk), "user_link_id": str(hub.links["owner"].pk)},
        )


def test_help_unknown_and_foreign_bot_commands_never_queue_paid_work(hub):
    assert "/brief" in send(hub, "/help")["text"]
    assert "not supported" in send(hub, "/delete-everything")["text"]
    assert send(hub, "/brief@another_bot Start")["silent"] is True
    assert not AgencyJob.objects.exists() and not Message.objects.exists()


@pytest.mark.parametrize("key", ["voice", "video", "audio", "animation", "video_note"])
def test_unsupported_transcription_is_explained_without_a_job(hub, key):
    response = send(hub, "", **{key: {"file_id": "file"}})
    assert "not available" in response["text"] and not AgencyJob.objects.exists()


def test_status_does_not_pull_private_same_workspace_drafts(hub):
    linked_post(hub)
    linked_post(hub, bound=hub.team_chat)[0].__class__.objects.filter(
        workspace=hub.ws, caption="Exact scoped caption"
    ).exclude(studio_briefs__job__conversation=hub.client_chat.conversation).update(caption="SECRET INTERNAL CAPTION")
    response = send(hub, "/status", role="client")
    assert "Exact scoped draft" in response["text"] and "SECRET" not in response["text"]


def test_review_is_bound_to_thread_and_client_signoff_status(hub, monkeypatch):
    post, _, _ = linked_post(hub, status="pending_client")
    foreign, _, _ = linked_post(hub, bound=hub.team_chat, status="pending_client")
    calls = []
    monkeypatch.setattr(
        actions,
        "issue_post_review",
        lambda *a, **k: (
            calls.append((a, k))
            or {"text": "Exact human card", "inline_keyboard": [[{"text": "Review", "callback_data": "one-use"}]]}
        ),
    )
    assert "No post" in send(hub, f"/post {foreign.pk}", role="client")["text"]
    assert not calls
    response = send(hub, f"/post {post.pk}", role="client")
    assert response["text"] == "Exact human card" and "reply_markup" in response and calls[0][0][2] == post


@pytest.mark.parametrize("when", ["2026-10-20T12:00:00", "not-a-date"])
def test_post_time_requires_an_aware_valid_review_choice(hub, when, monkeypatch):
    post, _, _ = linked_post(hub)
    monkeypatch.setattr(actions, "issue_post_review", lambda *a, **k: pytest.fail("Bad time reached action issue"))
    assert "offset" in send(hub, f"/post {post.pk} {when}")["text"]


def test_week_reads_client_safe_summary_and_client_group_cannot_prepare(hub, monkeypatch):
    calls = []
    monkeypatch.setattr(weekly, "summary_text", lambda *a, **k: calls.append(k) or "Shared permitted plan")
    assert send(hub, "/week", role="owner")["text"] == "Shared permitted plan"
    assert calls == [{"week_start": None, "user": hub.users["owner"], "audience": "client"}]
    assert "private or internal" in send(hub, "/week prepare", role="owner")["text"]
    assert not AgencyJob.objects.exists()


def test_stop_cancels_only_callers_own_assistant_jobs_in_this_conversation(hub):
    send(hub, "/brief My question")
    send(hub, "/brief Owners question", role="owner")
    send(hub, "/brief Another group question", bound=hub.team_chat)
    response = send(hub, "/stop")
    assert "Stopped 1" in response["text"]
    assert AgencyJob.objects.filter(status="cancelled").count() == 1
    assert AgencyJob.objects.filter(status="queued").count() == 2


def test_reply_budget_and_caps_use_existing_canonical_policy(hub, monkeypatch):
    monkeypatch.setattr(chat, "reply_refusal", lambda workspace: "budget")
    response = send(hub, "/brief Request", role="client")
    assert not AgencyJob.objects.exists() and Message.objects.filter(author_kind="client").count() == 1
    assert "budget" not in response["text"].lower()


def test_reference_instructions_make_no_pdf_extraction_promise(hub):
    response = send(hub, "/reference")
    assert "does not extract" in response["text"] and not AgencyJob.objects.exists()


def test_overlong_input_is_not_silently_truncated_or_queued(hub):
    response = send(hub, "/brief " + "x" * 4100)
    assert "too long" in response["text"] and not Message.objects.exists() and not AgencyJob.objects.exists()


@pytest.mark.parametrize("role", ["editor", "client"])
def test_real_worker_keeps_guided_client_group_questions_before_any_draft(hub, role, monkeypatch):
    manager = GuidedManager()
    monkeypatch.setattr(client_roles, "account_manager", manager)
    send(hub, "/brief Explain landlord shares", role=role)
    job = AgencyJob.objects.get()
    engine.run_step(str(job.pk), job.revision, job.stage)
    job.refresh_from_db()
    assert job.status == "done" and job.result["creative_brief"]
    assert not StudioBrief.objects.exists() and not hub.production
    assert manager.calls[0]["guided"] is True
    assert job.result["awaiting_confirmation"] is (role == "editor")
    if role == "client":
        assert job.result["client_preparation_requested"] is True
        assert "paired agency lead" in Message.objects.filter(author_kind="agent").get().body


def test_real_preparation_confirmation_requires_paired_staff_and_stays_unapproved(hub, monkeypatch):
    manager = GuidedManager()
    monkeypatch.setattr(client_roles, "account_manager", manager)
    send(hub, "/brief Explain shares")
    job = AgencyJob.objects.get()
    engine.run_step(str(job.pk), job.revision, job.stage)
    source = Message.objects.filter(author_kind="agent").get()
    context = {"chat_id": str(hub.client_chat.pk), "user_link_id": str(hub.links["editor"].pk)}
    posted = chat.post_message(
        hub.client_chat.conversation,
        hub.users["editor"],
        "I checked this exact brief.",
        kind="confirm_brief",
        facts_confirmed=True,
        confirmation_message_id=str(source.pk),
        explicit_assistant_request=True,
        telegram_context=context,
    )
    engine.run_step(str(posted.job.pk), posted.job.revision, posted.job.stage)
    brief = StudioBrief.objects.get()
    assert brief.author == hub.users["editor"] and brief.origin == "chat"
    assert brief.status == "queued" and not Post.objects.exists()
    assert len(hub.production) == 1


def test_revocation_during_model_work_cannot_start_or_save_guided_work(hub, monkeypatch):
    manager = GuidedManager()

    def revoke(profile, **kwargs):
        result = manager(profile, **kwargs)
        TelegramUserLink.objects.filter(pk=hub.links["editor"].pk).update(is_active=False)
        return result

    monkeypatch.setattr(client_roles, "account_manager", revoke)
    send(hub, "/brief Explain shares")
    job = AgencyJob.objects.get()
    engine.run_step(str(job.pk), job.revision, job.stage)
    job.refresh_from_db()
    assert job.status == "done" and "skipped" in job.result
    assert not StudioBrief.objects.exists() and not Message.objects.filter(author_kind="agent").exists()


def test_client_cannot_spoof_explicit_staff_preparation_flag(hub):
    context = {"chat_id": str(hub.client_chat.pk), "user_link_id": str(hub.links["client"].pk)}
    with pytest.raises(chat.ChatError, match="paired agency"):
        chat.post_message(
            hub.client_chat.conversation,
            hub.users["client"],
            "Start",
            explicit_assistant_request=True,
            telegram_context=context,
        )
    assert not Message.objects.exists() and not AgencyJob.objects.exists()


def test_unsigned_service_flag_without_pairing_is_rejected_and_web_defaults_unchanged(hub):
    with pytest.raises(chat.ChatError, match="paired agency"):
        chat.post_message(hub.client_chat.conversation, hub.users["editor"], "Start", explicit_assistant_request=True)
    posted = chat.post_message(hub.client_chat.conversation, hub.users["editor"], "Normal portal reply")
    assert posted.job is None


def test_ready_brief_command_issues_exact_one_use_card_without_another_model_job(hub, monkeypatch):
    manager = GuidedManager()
    monkeypatch.setattr(client_roles, "account_manager", manager)
    send(hub, "/brief Explain shares")
    job = AgencyJob.objects.get()
    engine.run_step(str(job.pk), job.revision, job.stage)
    response = send(hub, "/brief")
    assert "reply_markup" in response and response["reply_markup"]["inline_keyboard"][0][0]["text"] == "Go ahead"
    assert AgencyJob.objects.count() == 1
    assert "Send /brief" in Message.objects.filter(author_kind="agent").get().body


def test_brief_card_request_during_active_reply_does_not_reconfirm_stale_summary_or_pay_again(hub):
    send(hub, "/brief Collect my answers")
    response = send(hub, "/brief")
    assert "still answering" in response["text"] and "reply_markup" not in response
    assert AgencyJob.objects.count() == 1


def test_paired_lead_checks_exact_client_supplied_photo_in_group_without_impersonation(hub):
    from apps.media_library.models import MediaAsset

    photo = MediaAsset.objects.create(
        workspace=hub.ws,
        organization=hub.org,
        uploaded_by=hub.users["client"],
        filename="client-site.jpg",
        media_type="image",
        file_size=10,
    )
    context = {"chat_id": str(hub.client_chat.pk), "user_link_id": str(hub.links["client"].pk)}
    client_request = chat.post_message(
        hub.client_chat.conversation,
        hub.users["client"],
        "Use this site photo",
        telegram_context=context,
        reference_id=str(photo.pk),
    )
    client_request.job.status = "done"
    client_request.job.save(update_fields=["status"])
    send(hub, "/brief", role="owner")
    lead_job = AgencyJob.objects.get(requested_by=hub.users["owner"])
    assert lead_job.input["reference_id"] == str(photo.pk)
    assert lead_job.requested_by == hub.users["owner"] and not StudioBrief.objects.exists()
    assert Message.objects.get(pk=client_request.message.pk).author_kind == "client"


def test_custom_client_facing_model_new_post_cannot_create_a_lead_draft(hub, monkeypatch):
    role = CustomRole.objects.create(
        organization=hub.org,
        name="Customer with unusual grants",
        permissions={"client_facing": True, "create_posts": True},
    )
    WorkspaceMembership.objects.filter(workspace=hub.ws, user=hub.users["editor"]).update(custom_role=role)
    monkeypatch.setattr(client_roles, "account_manager", GuidedManager())
    send(hub, "/brief Create a campaign")
    job = AgencyJob.objects.get()
    engine.run_step(str(job.pk), job.revision, job.stage)
    job.refresh_from_db()
    assert job.result["client_preparation_requested"] is True and job.result["awaiting_confirmation"] is False
    assert not StudioBrief.objects.exists() and not hub.production


def test_role_downgrade_during_model_does_not_finish_staff_intake(hub, monkeypatch):
    manager = GuidedManager()

    def downgrade(profile, **kwargs):
        result = manager(profile, **kwargs)
        WorkspaceMembership.objects.filter(workspace=hub.ws, user=hub.users["editor"]).update(workspace_role="client")
        return result

    monkeypatch.setattr(client_roles, "account_manager", downgrade)
    send(hub, "/brief Create a campaign")
    job = AgencyJob.objects.get()
    engine.run_step(str(job.pk), job.revision, job.stage)
    job.refresh_from_db()
    assert job.result.get("skipped") and not Message.objects.filter(author_kind="agent").exists()
    assert not StudioBrief.objects.exists()


def test_week_blockers_are_shown_to_internal_operator_without_a_confirm_button(hub, monkeypatch):
    monkeypatch.setattr(
        weekly,
        "queue_week_plan",
        lambda *a, **k: {
            "needs_confirmation": False,
            "message": "Weekly work is blocked.",
            "analysis": {"blockers": ["Choose a current lead and correct brand destinations."]},
        },
    )
    response = send(hub, "/week prepare", role="owner", bound=hub.team_chat)
    assert "Weekly work is blocked" in response["text"]
    assert "Choose a current lead" in response["text"] and "reply_markup" not in response


def test_safe_review_permission_error_explains_human_next_action(hub):
    post, _, _ = linked_post(hub)
    response = send(hub, f"/post {post.pk}")
    assert "approve" in response["text"].lower() or "approval" in response["text"].lower()
    assert "reply_markup" not in response
