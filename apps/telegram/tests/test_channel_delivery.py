"""Channel status-only delivery, private provenance and native authority fencing."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.db import connection as db_connection
from django.db import connections
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import PlatformPost, Post
from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
from apps.notifications.models import Notification
from apps.organizations.models import Organization
from apps.publisher.delivery import delivery_write
from apps.social_accounts.models import SocialAccount
from apps.studio.models import AgencyJob, Conversation, Message, StudioBrief
from apps.telegram import channel_outbox, notifications, outbox, provisioning
from apps.telegram.api import TelegramAPIError
from apps.telegram.models import (
    TelegramChannel,
    TelegramChannelDelivery,
    TelegramChat,
    TelegramConnection,
    TelegramDelivery,
    TelegramUserLink,
)
from apps.telegram.tests.test_webhooks import create_hub
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


@pytest.fixture
def hub(organization, user, monkeypatch):
    connection, group = create_hub(organization, user, monkeypatch)
    connection.webhook_status = "active"
    connection.save(update_fields=["webhook_status", "updated_at"])
    OrgMembership.objects.create(organization=organization, user=user, org_role="owner")
    member = WorkspaceMembership.objects.create(workspace=connection.workspace, user=user, workspace_role="owner")
    link = TelegramUserLink.objects.create(connection=connection, user=user, telegram_user_id=777)
    personal = provisioning.private_chat(connection, link)
    channel = TelegramChannel.objects.create(
        connection=connection,
        organization=organization,
        authority_digest=provisioning.channel_authority_digest(member),
        chat_id=-100987654321,
        title="PRIVATE title never leaves",
        username="test_status_feed",
        created_by=user,
        user_link=link,
        telegram_user_id=link.telegram_user_id,
        bot_id=connection.bot_id,
        connection_epoch=connection.updated_at,
        pairing_epoch=link.updated_at,
        visibility_confirmed_at=timezone.now(),
    )
    return connection, group, personal, link, channel


@pytest.fixture
def native(hub, monkeypatch):
    connection, _, _, link, channel = hub
    api = Mock()
    api.get_me.return_value = {"id": connection.bot_id, "is_bot": True, "username": connection.bot_username}
    api.get_chat_member.side_effect = lambda chat_id, user_id: (
        {"user": {"id": user_id, "is_bot": True}, "status": "administrator", "can_post_messages": True}
        if user_id == connection.bot_id
        else {"user": {"id": link.telegram_user_id, "is_bot": False}, "status": "creator"}
    )
    api.call.side_effect = lambda method, params: (
        {"id": channel.chat_id, "type": "channel"}
        if method == "getChat"
        else {"message_id": 44, "chat": {"id": channel.chat_id, "type": "channel"}}
    )
    monkeypatch.setattr(channel_outbox, "BotAPI", Mock(return_value=api))
    return api


def writes(api):
    return [call for call in api.call.call_args_list if call.args[0] == "sendMessage"]


def queued(hub, event="approved", *, post=None):
    if post is None:
        post = getattr(hub[-1], "_canonical_post", None)
        if post is None:
            post = Post.objects.create(workspace=hub[0].workspace, author=hub[3].user)
            hub[-1]._canonical_post = post
    if event == "draft" and not post.studio_briefs.exists():
        completed_brief(hub, post=post)
    if event == "published" and not post.platform_posts.exists():
        account = SocialAccount.objects.create(
            workspace=hub[0].workspace, platform="instagram", account_platform_id="fixture_native"
        )
        platform_post = PlatformPost.objects.create(post=post, social_account=account)
        with delivery_write():
            PlatformPost.objects.filter(pk=platform_post.pk).update(
                status="published", platform_post_id="fixture_confirmed_native_receipt", published_at=timezone.now()
            )
    return channel_outbox.queue_channel_event(hub[-1], event, source_key=f"test:{event}", post=post)


def completed_brief(hub, *, post=None, job=None):
    if post is None:
        post = Post.objects.create(workspace=hub[0].workspace, author=hub[3].user, title="SECRET canonical title")
    return StudioBrief.objects.create(
        workspace=hub[0].workspace,
        author=hub[3].user,
        job=job,
        idea="SECRET brief idea",
        notes="SECRET cost",
        post=post,
        status="ready",
        stage="done",
        finished_at=timezone.now(),
    )


@pytest.mark.parametrize("event", list(channel_outbox.CHANNEL_EVENT_TEXT))
def test_only_fixed_status_text_is_encrypted_deduplicated_and_sent_once(hub, native, event):
    connection, _, _, _, channel = hub
    row = queued(hub, event)
    assert row.pk == queued(hub, event).pk
    assert TelegramChat.objects.filter(connection=connection).count() == 2
    assert TelegramDelivery.objects.count() == 0
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT payload FROM telegram_channel_delivery WHERE id = %s", [row.pk])
        encrypted = cursor.fetchone()[0]
    assert row.payload["text"] not in encrypted and "telegram_user_id" not in encrypted
    assert channel_outbox.send_one(row.pk) == "sent"
    assert channel_outbox.send_one(row.pk) == "skipped"
    assert len(writes(native)) == 1
    params = writes(native)[0].args[1]
    assert params == {
        "chat_id": channel.chat_id,
        "text": channel_outbox.CHANNEL_EVENT_TEXT[event],
        "link_preview_options": {"is_disabled": True},
    }
    assert str(channel.created_by_id) not in params["text"] and channel.title not in params["text"]
    row.refresh_from_db()
    assert row.native_message_id == 44 and row.attempts == 1


@pytest.mark.parametrize("event", ["private caption", "", None, {}, "<b>approved</b>", "APPROVED"])
def test_arbitrary_events_and_freeform_content_cannot_be_queued(hub, event):
    with pytest.raises(ValueError):
        channel_outbox.queue_channel_event(hub[-1], event, source_key="unsafe")
    assert not TelegramChannelDelivery.objects.exists()


def test_channel_status_requires_a_canonical_post_origin(hub):
    with pytest.raises(ValueError, match="canonical post"):
        channel_outbox.queue_channel_event(hub[-1], "approved", source_key="no-origin")
    assert not TelegramChannelDelivery.objects.exists()


def test_published_status_without_actual_platform_receipt_cannot_be_queued(hub):
    post = Post.objects.create(workspace=hub[0].workspace, author=hub[3].user)
    assert channel_outbox.queue_channel_event(hub[-1], "published", source_key="no-native", post=post) is None
    assert not TelegramChannelDelivery.objects.exists()


@pytest.mark.parametrize(
    "mutation",
    ["text", "event", "method", "reply_markup", "photo", "caption", "extra", "origin_workspace", "scope"],
)
def test_tampered_payload_cannot_become_a_conversation_or_media_transport(hub, native, mutation):
    post = Post.objects.create(workspace=hub[0].workspace, title="Do not send", author=hub[3].user)
    row = queued(hub, post=post)
    payload = dict(row.payload)
    if mutation == "origin_workspace":
        payload["_post"] = {"post_id": str(post.pk), "workspace_id": "foreign"}
    elif mutation == "scope":
        payload["_scope"] = {}
    else:
        payload[mutation] = "PRIVATE data callback caption"
    TelegramChannelDelivery.objects.filter(pk=row.pk).update(payload=payload)
    assert channel_outbox.send_one(row.pk) == "failed"
    native.get_me.assert_not_called()
    assert not writes(native)


@pytest.mark.parametrize(
    "mutation",
    [
        "connection_inactive",
        "archived",
        "organization_deleted",
        "user_disabled",
        "membership_removed",
        "organization_member_removed",
        "role_changed",
        "custom_role_still_manager",
        "org_membership_recreated",
        "link_disabled",
        "link_epoch",
        "actor_numeric_id",
        "personal_disabled",
        "personal_not_private",
        "channel_disabled",
        "channel_epoch",
        "connection_epoch",
        "token_rotated_without_epoch",
        "organization_changed",
        "authority_digest",
    ],
)
def test_current_tenant_pairing_owner_and_epoch_are_required_at_send(hub, native, mutation):
    connection, _, personal, link, channel = hub
    row = queued(hub)
    if mutation == "connection_inactive":
        TelegramConnection.objects.filter(pk=connection.pk).update(is_active=False)
    elif mutation == "archived":
        Workspace.objects.filter(pk=connection.workspace_id).update(is_archived=True)
    elif mutation == "organization_deleted":
        Organization.objects.filter(pk=connection.workspace.organization_id).update(
            deletion_requested_at=timezone.now()
        )
    elif mutation == "user_disabled":
        User.objects.filter(pk=link.user_id).update(is_active=False)
    elif mutation == "membership_removed":
        WorkspaceMembership.objects.filter(workspace=connection.workspace, user=link.user).delete()
    elif mutation == "organization_member_removed":
        OrgMembership.objects.filter(organization=connection.workspace.organization, user=link.user).delete()
    elif mutation == "role_changed":
        WorkspaceMembership.objects.filter(workspace=connection.workspace, user=link.user).update(
            workspace_role="admin"
        )
    elif mutation == "custom_role_still_manager":
        role = CustomRole.objects.create(
            organization=connection.workspace.organization,
            name="Still a settings manager",
            permissions={"manage_workspace_settings": True, "create_posts": True},
        )
        WorkspaceMembership.objects.filter(workspace=connection.workspace, user=link.user).update(custom_role=role)
        assert (
            provisioning.channel_actor(connection, link.user)[2].effective_permissions["manage_workspace_settings"]
            is True
        )
    elif mutation == "org_membership_recreated":
        OrgMembership.objects.filter(organization=connection.workspace.organization, user=link.user).delete()
        OrgMembership.objects.create(organization=connection.workspace.organization, user=link.user, org_role="owner")
        assert (
            provisioning.channel_actor(connection, link.user)[2].effective_permissions["manage_workspace_settings"]
            is True
        )
    elif mutation == "link_disabled":
        TelegramUserLink.objects.filter(pk=link.pk).update(is_active=False)
    elif mutation == "link_epoch":
        TelegramUserLink.objects.filter(pk=link.pk).update(updated_at=timezone.now() + timedelta(seconds=1))
    elif mutation == "actor_numeric_id":
        TelegramUserLink.objects.filter(pk=link.pk).update(telegram_user_id=778)
    elif mutation == "personal_disabled":
        TelegramChat.objects.filter(pk=personal.pk).update(is_active=False)
    elif mutation == "personal_not_private":
        Conversation.objects.filter(pk=personal.conversation_id).update(is_private=False)
    elif mutation == "channel_disabled":
        TelegramChannel.objects.filter(pk=channel.pk).update(is_active=False)
    elif mutation == "channel_epoch":
        TelegramChannel.objects.filter(pk=channel.pk).update(updated_at=timezone.now() + timedelta(seconds=1))
    elif mutation == "connection_epoch":
        TelegramConnection.objects.filter(pk=connection.pk).update(updated_at=timezone.now() + timedelta(seconds=1))
    elif mutation == "token_rotated_without_epoch":
        TelegramConnection.objects.filter(pk=connection.pk).update(token="123456:" + "x" * 32)
    elif mutation == "organization_changed":
        other = Organization.objects.create(name="Other client")
        OrgMembership.objects.create(organization=other, user=link.user, org_role="owner")
        Workspace.objects.filter(pk=connection.workspace_id).update(organization=other)
    else:
        TelegramChannel.objects.filter(pk=channel.pk).update(authority_digest="x" * 64)
    assert channel_outbox.send_one(row.pk) == "failed"
    assert not writes(native)


@pytest.mark.parametrize(
    "mutation",
    [
        "bot_id",
        "bot_flag",
        "bot_name",
        "chat_id",
        "chat_type",
        "bot_post",
        "bot_role",
        "actor_role",
        "actor_bot",
        "actor_id",
    ],
)
def test_live_native_bot_channel_and_real_actor_admin_proof_is_required(hub, native, mutation):
    connection, _, _, link, channel = hub
    row = queued(hub)
    if mutation.startswith("bot_") and mutation in {"bot_id", "bot_flag", "bot_name"}:
        identity = dict(native.get_me.return_value)
        identity[{"bot_id": "id", "bot_flag": "is_bot", "bot_name": "username"}[mutation]] = {
            "bot_id": connection.bot_id + 1,
            "bot_flag": False,
            "bot_name": "wrong_bot",
        }[mutation]
        native.get_me.return_value = identity
    elif mutation in {"chat_id", "chat_type"}:
        native.call.side_effect = lambda method, params: {
            "id": channel.chat_id + 1 if mutation == "chat_id" else channel.chat_id,
            "type": "supergroup" if mutation == "chat_type" else "channel",
        }
    else:

        def member(chat_id, user_id):
            if user_id == connection.bot_id:
                return {
                    "user": {"id": user_id, "is_bot": True},
                    "status": "member" if mutation == "bot_role" else "administrator",
                    "can_post_messages": mutation != "bot_post",
                }
            return {
                "user": {"id": link.telegram_user_id + (mutation == "actor_id"), "is_bot": mutation == "actor_bot"},
                "status": "member" if mutation == "actor_role" else "creator",
            }

        native.get_chat_member.side_effect = member
    assert channel_outbox.send_one(row.pk) == "failed"
    assert not writes(native)
    channel.refresh_from_db()
    assert not channel.is_active


def test_revocation_during_native_verification_is_checked_before_send(hub, native):
    row = queued(hub)
    original = native.get_chat_member.side_effect

    def revoke(chat_id, user_id):
        result = original(chat_id, user_id)
        TelegramUserLink.objects.filter(pk=hub[3].pk).update(is_active=False)
        return result

    native.get_chat_member.side_effect = revoke
    assert channel_outbox.send_one(row.pk) == "failed"
    assert not writes(native)


def test_lost_worker_lease_holds_claim_without_native_request(hub, native):
    from apps.common.background import WorkerLeaseLostError, worker_lease_checks

    row = queued(hub)

    def lost():
        raise RuntimeError("lost lease")

    with worker_lease_checks(lost), pytest.raises(WorkerLeaseLostError):
        channel_outbox.send_one(row.pk)
    native.get_me.assert_not_called()
    row.refresh_from_db()
    assert row.status == "sending"
    TelegramChannelDelivery.objects.filter(pk=row.pk).update(claimed_at=timezone.now() - timedelta(minutes=10))
    assert channel_outbox.recover_stale_deliveries() == 1
    assert channel_outbox.send_one(row.pk) == "skipped"


@pytest.mark.parametrize("failure", [TelegramAPIError(kind="transport", ambiguous=True), RuntimeError("PRIVATE token")])
def test_ambiguous_writes_are_held_and_never_replayed(hub, native, failure):
    row = queued(hub)
    original = native.call.side_effect

    def fail(method, params):
        if method == "sendMessage":
            raise failure
        return original(method, params)

    native.call.side_effect = fail
    assert channel_outbox.send_one(row.pk) == "unknown"
    assert channel_outbox.send_one(row.pk) == "skipped"
    row.refresh_from_db()
    assert row.next_attempt_at is None and "PRIVATE" not in row.error
    assert len(writes(native)) == 1


@pytest.mark.parametrize("kind", ["connect", "rate_limited"])
def test_definitive_preconnect_and_rate_limit_retries_are_delayed_and_finite(hub, native, kind):
    row = queued(hub)
    original = native.call.side_effect

    def fail(method, params):
        if method == "sendMessage":
            raise TelegramAPIError(kind=kind, retry_after=15)
        return original(method, params)

    native.call.side_effect = fail
    for attempt in range(channel_outbox.MAX_SEND_ATTEMPTS):
        TelegramChannelDelivery.objects.filter(pk=row.pk).update(next_attempt_at=None)
        assert channel_outbox.send_one(row.pk) == ("pending" if attempt < 3 else "failed")
        if attempt < 3:
            assert channel_outbox.send_one(row.pk) == "skipped"
    assert channel_outbox.send_one(row.pk) == "skipped"
    assert len(writes(native)) == 4


@pytest.mark.parametrize(
    "result", [{}, {"message_id": True}, {"message_id": 44}, {"message_id": 44, "chat": {"id": -1, "type": "channel"}}]
)
def test_unverified_receipts_are_held(hub, native, result):
    row = queued(hub)
    original = native.call.side_effect
    native.call.side_effect = lambda method, params: result if method == "sendMessage" else original(method, params)
    assert channel_outbox.send_one(row.pk) == "unknown"
    assert channel_outbox.send_one(row.pk) == "skipped"


def test_late_native_success_cannot_overwrite_disconnect_hold(hub, native):
    row = queued(hub)
    original = native.call.side_effect

    def disconnect(method, params):
        if method == "sendMessage":
            TelegramChannelDelivery.objects.filter(pk=row.pk).update(status="unknown", error="Held after disconnect")
        return original(method, params)

    native.call.side_effect = disconnect
    assert channel_outbox.send_one(row.pk) == "unknown"
    row.refresh_from_db()
    assert row.status == "unknown" and row.native_message_id is None and row.error == "Held after disconnect"


@pytest.mark.django_db(transaction=True)
def test_concurrent_channel_workers_claim_once_outside_database_transaction(hub, native):
    row = queued(hub)
    entered, release = threading.Event(), threading.Event()
    original = native.call.side_effect

    def blocked(method, params):
        if method == "sendMessage":
            assert not db_connection.in_atomic_block
            entered.set()
            assert release.wait(timeout=10)
        return original(method, params)

    native.call.side_effect = blocked

    def worker():
        try:
            return channel_outbox.send_one(row.pk)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(worker)
        assert entered.wait(timeout=10)
        second = pool.submit(worker)
        try:
            assert second.result(timeout=10) == "skipped"
        finally:
            release.set()
        assert first.result(timeout=10) == "sent"
    assert len(writes(native)) == 1


@pytest.mark.parametrize("origin", ["post_thread", "brief_thread", "job", "legacy_private_chat", "foreign_job"])
def test_any_private_or_inconsistent_post_lineage_prevents_channel_broadcast(hub, origin):
    connection, _, _, link, _ = hub
    post = Post.objects.create(
        workspace=connection.workspace, author=link.user, title="PRIVATE title", caption="PRIVATE caption"
    )
    thread = Conversation.objects.create(
        workspace=connection.workspace,
        audience="internal",
        is_private=origin != "legacy_private_chat",
        created_by=link.user,
    )
    if origin == "post_thread":
        thread.post = post
        thread.save(update_fields=["post"])
    else:
        job = AgencyJob.objects.create(
            workspace=connection.workspace, conversation=thread, kind="chat", requested_by=link.user
        )
        brief = StudioBrief.objects.create(
            workspace=connection.workspace, author=link.user, job=job, idea="PRIVATE idea", post=post
        )
        if origin == "brief_thread":
            thread.brief = brief
            thread.save(update_fields=["brief"])
        elif origin == "legacy_private_chat":
            TelegramChat.objects.create(
                connection=connection,
                chat_id=799,
                chat_type="private",
                audience="private",
                private_user=link.user,
                conversation=thread,
            )
        elif origin == "foreign_job":
            thread.is_private = False
            thread.save(update_fields=["is_private"])
            foreign = Workspace.objects.create(organization=connection.workspace.organization, name="Other client")
            AgencyJob.objects.filter(pk=job.pk).update(workspace=foreign)
    assert not channel_outbox.public_post(post)
    assert queued(hub, post=post) is None
    notice = Notification.objects.create(
        user=link.user, event_type="post_approved", title="PRIVATE notice", data={"post_id": str(post.pk)}
    )
    notifications.notification_event(notice.pk)
    assert not TelegramChannelDelivery.objects.exists()


def test_private_provenance_added_after_queue_prevents_delivery(hub, native):
    connection, _, _, link, _ = hub
    post = Post.objects.create(workspace=connection.workspace, author=link.user)
    row = queued(hub, post=post)
    Conversation.objects.create(workspace=connection.workspace, post=post, is_private=True, created_by=link.user)
    assert channel_outbox.send_one(row.pk) == "failed"
    assert not writes(native)


def test_notification_channels_deduplicate_safe_status_without_changing_conversation_routing(hub):
    connection, group, _, link, channel = hub
    post = Post.objects.create(
        workspace=connection.workspace, author=link.user, title="SECRET title", caption="SECRET caption"
    )
    Conversation.objects.filter(pk=group.conversation_id).update(post=post)
    notice = Notification.objects.create(
        user=link.user,
        event_type="post_approved",
        title="SECRET staff note",
        body="SECRET cost",
        data={"post_id": str(post.pk)},
    )
    assert notifications.notification_event(notice.pk) == 2
    assert notifications.notification_event(notice.pk) == 2
    assert TelegramDelivery.objects.filter(chat=group).count() == 1
    assert TelegramChannelDelivery.objects.filter(channel=channel).count() == 1
    assert TelegramChannelDelivery.objects.get().payload["text"] == channel_outbox.CHANNEL_EVENT_TEXT["approved"]
    assert "SECRET" in TelegramDelivery.objects.get().payload["text"]


def test_raw_messages_ideas_and_private_week_plan_never_broadcast(hub):
    _, group, _, _, _ = hub
    message = Message.objects.create(conversation=group.conversation, author_kind="agent", body="PRIVATE brainstorming")
    assert notifications.mirror_message(message.pk) == 1
    assert not TelegramChannelDelivery.objects.exists()


def test_native_publication_only_emits_safe_fixed_confirmed_status(hub):
    connection, _, _, link, _ = hub
    post = Post.objects.create(
        workspace=connection.workspace, author=link.user, title="SECRET title", caption="SECRET caption"
    )
    account = SocialAccount.objects.create(
        workspace=connection.workspace,
        platform="instagram",
        account_name="SECRET account",
        account_platform_id="SECRET native",
    )
    platform_post = PlatformPost.objects.create(post=post, social_account=account)
    with delivery_write():
        PlatformPost.objects.filter(pk=platform_post.pk).update(status="published", published_at=timezone.now())
    assert notifications.platform_receipt(platform_post.pk) == 0
    with delivery_write():
        PlatformPost.objects.filter(pk=platform_post.pk).update(platform_post_id="SECRET provider receipt")
    assert notifications.platform_receipt(platform_post.pk) == 1
    row = TelegramChannelDelivery.objects.get()
    assert row.payload["text"] == channel_outbox.CHANNEL_EVENT_TEXT["published"]
    assert "SECRET" not in row.payload["text"]


def test_existing_recurring_outbox_drain_includes_channels(hub, native):
    row = queued(hub)
    assert outbox.drain_outbox(limit=1) == {"sent": 1}
    row.refresh_from_db()
    assert row.status == "sent"


def test_completed_canonical_web_draft_notice_queues_fixed_status_without_raw_idea(hub):
    brief = completed_brief(hub)
    notice = Notification.objects.create(
        user=hub[3].user,
        event_type="post_submitted",
        title="SECRET title",
        body="SECRET raw idea and cost",
        data={"post_id": str(brief.post_id), "studio_brief_id": str(brief.pk), "workspace_id": str(brief.workspace_id)},
    )
    # Two fixed channel lines, plus the draft in the paired approver's own manager inbox.
    assert notifications.notification_event(notice.pk) == 3
    assert notifications.notification_event(notice.pk) == 3
    rows = list(TelegramChannelDelivery.objects.order_by("created_at"))
    assert [row.payload["event"] for row in rows] == ["draft", "review"]
    assert all("SECRET" not in row.payload["text"] for row in rows)
    assert rows[0].payload["_post"]["draft_brief_id"] == str(brief.pk)
    assert rows[0].payload["_post"]["draft_revision"] == brief.revision
    inbox_row = TelegramDelivery.objects.get()
    assert inbox_row.chat_id == hub[2].pk and inbox_row.source_key.startswith("inbox:")
    # The approver sees the post itself, never the notification body, the idea or the cost notes.
    text = inbox_row.payload["text"]
    assert "Draft ready" in text and "SECRET raw idea" not in text and "SECRET cost" not in text
    assert "SECRET brief idea" not in text


def test_normal_review_notice_announces_committed_draft_before_review(hub):
    brief = completed_brief(hub)
    notice = Notification.objects.create(
        user=hub[3].user, event_type="post_submitted", title="SECRET raw title", data={"post_id": str(brief.post_id)}
    )
    assert notifications.notification_event(notice.pk) == 3  # draft + review channel lines, one inbox draft
    assert [row.payload["event"] for row in TelegramChannelDelivery.objects.order_by("created_at")] == [
        "draft",
        "review",
    ]
    assert TelegramDelivery.objects.filter(source_key__startswith="inbox:").count() == 1


def test_recurring_draft_sweep_recovers_queryset_handoff_once_per_revision(hub):
    brief = StudioBrief.objects.create(workspace=hub[0].workspace, author=hub[3].user, idea="SECRET unready idea")
    assert notifications.sweep_receipts(limit=1) == 0
    post = Post.objects.create(workspace=hub[0].workspace, author=hub[3].user)
    StudioBrief.objects.filter(pk=brief.pk).update(post=post, status="ready", stage="done", finished_at=timezone.now())
    assert notifications.sweep_receipts(limit=1) == 2  # the channel line and the approver's inbox draft
    assert TelegramChannelDelivery.objects.count() == 1
    notifications.sweep_receipts(limit=1)
    notifications.sweep_receipts(limit=1)
    assert TelegramChannelDelivery.objects.count() == 1
    assert TelegramDelivery.objects.filter(source_key__startswith="inbox:").count() == 1
    StudioBrief.objects.filter(pk=brief.pk).update(revision=2)
    notifications.sweep_receipts(limit=1)
    notifications.sweep_receipts(limit=1)
    assert TelegramChannelDelivery.objects.count() == 2
    assert {row.payload["_post"]["draft_revision"] for row in TelegramChannelDelivery.objects.all()} == {1, 2}
    assert TelegramDelivery.objects.filter(source_key__startswith="inbox:").count() == 2


@pytest.mark.parametrize(
    "mutation", ["working", "stage", "unfinished", "no_post", "private", "foreign", "missing_job_origin"]
)
def test_draft_ready_hook_rejects_unfinished_private_and_unknown_lineage(hub, mutation):
    brief = completed_brief(hub)
    if mutation == "working":
        StudioBrief.objects.filter(pk=brief.pk).update(status="working")
    elif mutation == "stage":
        StudioBrief.objects.filter(pk=brief.pk).update(stage="handoff")
    elif mutation == "unfinished":
        StudioBrief.objects.filter(pk=brief.pk).update(finished_at=None)
    elif mutation == "no_post":
        StudioBrief.objects.filter(pk=brief.pk).update(post=None)
    elif mutation == "private":
        Conversation.objects.create(workspace=brief.workspace, brief=brief, is_private=True)
    elif mutation == "foreign":
        foreign = Workspace.objects.create(organization=brief.workspace.organization, name="Other client")
        StudioBrief.objects.filter(pk=brief.pk).update(workspace=foreign)
    else:
        job = AgencyJob.objects.create(workspace=brief.workspace, kind="chat")
        StudioBrief.objects.filter(pk=brief.pk).update(job=job)
    # Channels and the author's idea thread refuse every one of these. A finished
    # draft that still belongs to this workspace does reach the approver's own
    # inbox, whatever thread asked for it: the post is in the approval queue and
    # the message names the post, never the conversation.
    told = 1 if mutation in {"private", "missing_job_origin"} else 0
    assert notifications.ready_draft(brief.pk) == told
    assert notifications.sweep_receipts(limit=1) == told
    assert not TelegramChannelDelivery.objects.exists()
    assert TelegramDelivery.objects.filter(source_key__startswith="inbox:").count() == told


def test_draft_revision_drift_after_queue_fails_before_send(hub, native):
    brief = completed_brief(hub)
    assert notifications.ready_draft(brief.pk) == 2  # the channel line and the approver's inbox draft
    row = TelegramChannelDelivery.objects.get()
    StudioBrief.objects.filter(pk=brief.pk).update(revision=2)
    assert channel_outbox.send_one(row.pk) == "failed"
    assert not writes(native)


def test_draft_ready_rejects_notice_that_names_another_authors_brief(hub):
    brief = completed_brief(hub)
    other = User.objects.create_user(email="other-author@example.test", password="fake", name="Other")
    notice = Notification.objects.create(
        user=other,
        event_type="post_submitted",
        title="SECRET fake announcement",
        data={"post_id": str(brief.post_id), "studio_brief_id": str(brief.pk)},
    )
    assert notifications.notification_event(notice.pk) == 0
    assert not TelegramChannelDelivery.objects.exists()
