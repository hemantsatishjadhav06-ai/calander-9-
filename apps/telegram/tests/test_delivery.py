import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from io import BytesIO
from unittest.mock import Mock

import pytest
from django.core.files.base import ContentFile
from django.db import connection as db_connection
from django.db import connections
from django.utils import timezone
from PIL import Image

from apps.composer.models import PlatformPost, Post
from apps.media_library.models import MediaAsset
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.notifications.models import Notification
from apps.publisher.delivery import delivery_write
from apps.social_accounts.models import SocialAccount
from apps.studio.models import AgencyJob, AutopilotWeek, Conversation, Message, StudioBrief
from apps.telegram import outbox
from apps.telegram.api import TelegramAPIError
from apps.telegram.models import (
    TelegramAction,
    TelegramChat,
    TelegramDelivery,
    TelegramPairing,
    TelegramUpdate,
    TelegramUserLink,
)
from apps.telegram.notifications import mirror_message, notification_event, platform_receipt
from apps.telegram.tests.test_webhooks import authenticated, create_hub

pytestmark = pytest.mark.django_db


@pytest.fixture
def hub(organization, user, monkeypatch):
    return create_hub(organization, user, monkeypatch)


@pytest.fixture
def controlled_api(monkeypatch):
    api = Mock()
    api.call.return_value = {"message_id": 101}
    api.send_photo.return_value = {"message_id": 102}
    monkeypatch.setattr(outbox, "BotAPI", Mock(return_value=api))
    return api


def pair(conn, user, telegram_id=99):
    OrgMembership.objects.get_or_create(
        organization=conn.workspace.organization, user=user, defaults={"org_role": "owner"}
    )
    WorkspaceMembership.objects.get_or_create(workspace=conn.workspace, user=user, defaults={"workspace_role": "owner"})
    return TelegramUserLink.objects.create(connection=conn, user=user, telegram_user_id=telegram_id)


def bind_post(conn, chat, user):
    post = Post.objects.create(
        workspace=conn.workspace, author=user, title="New project update", caption="Customer-facing caption"
    )
    chat.conversation.post = post
    chat.conversation.save(update_fields=["post"])
    return post


def photo(conn):
    buffer = BytesIO()
    Image.new("RGB", (20, 20), "blue").save(buffer, "PNG")
    content = buffer.getvalue()
    return MediaAsset.objects.create(
        workspace=conn.workspace,
        organization=conn.workspace.organization,
        filename="client-graphic.png",
        media_type="image",
        file_size=len(content),
        file=ContentFile(content, name="test-telegram.png"),
        processing_status="completed",
    )


def keyboard():
    return {"inline_keyboard": [[{"text": "Approve exact revision", "callback_data": "tg:a:" + "f" * 32}]]}


def completed_week(conn, chat, user):
    chat.audience = "team"
    chat.save(update_fields=["audience"])
    chat.conversation.audience = "internal"
    chat.conversation.save(update_fields=["audience"])
    job = AgencyJob.objects.create(
        workspace=conn.workspace, conversation=chat.conversation, kind="plan", status="done", requested_by=user
    )
    week = AutopilotWeek.objects.create(
        workspace=conn.workspace, week_start=date(2026, 10, 19), job=job, status="planned"
    )
    StudioBrief.objects.create(
        workspace=conn.workspace, job=job, author=user, idea="Canonical prepared draft", status="ready"
    )
    return week


def test_semantic_dedup_plain_text_length_and_encrypted_storage(hub, controlled_api):
    _, chat = hub
    rows = outbox.queue_message(chat, "<b>client & safe</b> " + "🙂" * 3000, source_key="event:1")
    assert len(rows) == 2
    assert [row.pk for row in outbox.queue_message(chat, "different retry payload", source_key="event:1")] == [
        rows[0].pk
    ]
    assert all(len(row.payload["text"].encode("utf-16-le")) // 2 <= 4096 for row in rows)
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT payload FROM telegram_delivery WHERE id = %s", [rows[0].pk])
        assert "client & safe" not in cursor.fetchone()[0]
    assert outbox.send_one(rows[1].pk) == "skipped"
    assert outbox.send_one(rows[0].pk) == "sent"
    assert outbox.send_one(rows[1].pk) == "sent"
    assert outbox.send_one(rows[0].pk) == "skipped"
    assert controlled_api.call.call_count == 2
    assert all("parse_mode" not in call.args[1] for call in controlled_api.call.call_args_list)
    rows[0].refresh_from_db()
    assert rows[0].native_message_id == 101


def test_unknown_and_stale_sends_are_held_without_duplicates(hub, controlled_api):
    _, chat = hub
    row = outbox.queue_message(chat, "Important review", source_key="event:unknown")[0]
    controlled_api.call.side_effect = TelegramAPIError(kind="transport", ambiguous=True)
    assert outbox.send_one(row.pk) == "unknown"
    assert outbox.send_one(row.pk) == "skipped"
    row.refresh_from_db()
    assert row.status == "unknown" and row.next_attempt_at is None
    stale = TelegramDelivery.objects.create(
        connection=chat.connection,
        chat=chat,
        source_key="event:stale",
        status="sending",
        claimed_at=timezone.now() - timedelta(hours=1),
        payload={"method": "sendMessage", "text": "Never replay"},
    )
    assert outbox.recover_stale_deliveries(limit=1) == 1
    assert outbox.send_one(stale.pk) == "skipped"
    assert controlled_api.call.call_count == 1


def test_rate_limit_retry_is_delayed_bounded_and_then_sent(hub, controlled_api):
    _, chat = hub
    row = outbox.queue_message(chat, "Receipt", source_key="rate:1")[0]
    controlled_api.call.side_effect = TelegramAPIError(kind="rate_limited", retry_after=100000)
    before = timezone.now()
    assert outbox.send_one(row.pk) == "pending"
    row.refresh_from_db()
    assert row.attempts == 1 and row.next_attempt_at >= before + timedelta(seconds=100000)
    assert outbox.send_one(row.pk) == "skipped"
    TelegramDelivery.objects.filter(pk=row.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
    controlled_api.call.side_effect = None
    assert outbox.send_one(row.pk) == "sent"
    row.refresh_from_db()
    assert row.attempts == 2 and row.next_attempt_at is None


def test_lost_worker_lease_prevents_external_telegram_send(hub, controlled_api):
    from apps.common.background import WorkerLeaseLostError, worker_lease_checks

    _, chat = hub
    row = outbox.queue_message(chat, "Do not send from an old worker", source_key="lease:lost")[0]

    def lost_lease():
        raise RuntimeError("worker session lost")

    with worker_lease_checks(lost_lease), pytest.raises(WorkerLeaseLostError):
        outbox.send_one(row.pk)
    controlled_api.call.assert_not_called()
    row.refresh_from_db()
    assert row.status == "sending"
    TelegramDelivery.objects.filter(pk=row.pk).update(claimed_at=timezone.now() - timedelta(minutes=10))
    assert outbox.recover_stale_deliveries() == 1
    assert outbox.send_one(row.pk) == "skipped"
    row.refresh_from_db()
    assert row.status == "unknown"


@pytest.mark.parametrize("kind", ["forbidden", "chat_migrated"])
def test_403_or_migration_disables_chat_and_requires_fresh_binding(hub, controlled_api, kind):
    conn, chat = hub
    first = outbox.queue_message(chat, "First", source_key="disable:1")[0]
    second = outbox.queue_message(chat, "Second", source_key="disable:2")[0]
    in_flight = outbox.queue_message(chat, "Already in flight", source_key="disable:in-flight")[0]
    TelegramDelivery.objects.filter(pk=in_flight.pk).update(status="sending", claimed_at=timezone.now())
    controlled_api.call.side_effect = TelegramAPIError(kind=kind, migrate_to_chat_id=-987)
    assert outbox.send_one(first.pk) == "failed"
    chat.refresh_from_db()
    first.refresh_from_db()
    second.refresh_from_db()
    in_flight.refresh_from_db()
    assert not chat.is_active and first.status == second.status == "failed"
    assert in_flight.status == "unknown"
    assert not TelegramChat.objects.filter(connection=conn, chat_id=-987).exists()
    assert not outbox.queue_message(chat, "More", source_key="disable:3")


def test_missing_receipt_is_unknown_and_no_token_in_safe_error(hub, controlled_api):
    _, chat = hub
    row = outbox.queue_message(chat, "Receipt", source_key="missing:1")[0]
    controlled_api.call.return_value = {"ok": True}
    assert outbox.send_one(row.pk) == "unknown"
    row.refresh_from_db()
    assert "receipt" in row.error
    assert chat.connection.token not in row.error


def test_revoked_private_user_and_foreign_conversation_never_send(hub, user, controlled_api):
    conn, group = hub
    link = pair(conn, user)
    conversation = Conversation.objects.create(workspace=conn.workspace, audience="internal", created_by=user)
    chat = TelegramChat.objects.create(
        connection=conn,
        conversation=conversation,
        chat_id=99,
        chat_type="private",
        audience="private",
        private_user=user,
    )
    row = outbox.queue_message(chat, "Private worker discussion", source_key="private:1")[0]
    link.is_active = False
    link.save(update_fields=["is_active"])
    assert outbox.send_one(row.pk) == "failed"
    group.conversation.audience = "internal"
    group.conversation.save(update_fields=["audience"])
    assert not outbox.queue_message(group, "Internal conversation", source_key="private:2")
    controlled_api.call.assert_not_called()


def test_private_client_receives_visible_reply_but_never_internal_notes(
    hub, user, controlled_api, django_capture_on_commit_callbacks
):
    conn, _ = hub
    pair(conn, user)
    WorkspaceMembership.objects.filter(workspace=conn.workspace, user=user).update(workspace_role="client")
    conversation = Conversation.objects.create(workspace=conn.workspace, audience="client", created_by=user)
    chat = TelegramChat.objects.create(
        connection=conn,
        conversation=conversation,
        chat_id=99,
        chat_type="private",
        audience="private",
        private_user=user,
    )
    with django_capture_on_commit_callbacks(execute=True):
        Message.objects.create(
            conversation=conversation, author_kind="staff", body="The client-visible draft is ready."
        )
        Message.objects.create(
            conversation=conversation, author_kind="staff", body="Private cost token note", is_internal=True
        )
    rows = list(TelegramDelivery.objects.filter(chat=chat))
    assert len(rows) == 1 and "client-visible" in rows[0].payload["text"]
    assert outbox.send_one(rows[0].pk) == "sent"
    conversation.audience = "internal"
    conversation.save(update_fields=["audience"])
    assert not outbox.queue_message(
        chat, "Client role cannot read internal thread", source_key="private-client:internal"
    )


def test_old_internal_reply_cannot_cross_private_role_downgrade_rebinding(hub, user, controlled_api):
    conn, _ = hub
    pair(conn, user)
    internal = Conversation.objects.create(workspace=conn.workspace, audience="internal", created_by=user)
    chat = TelegramChat.objects.create(
        connection=conn, conversation=internal, chat_id=99, chat_type="private", audience="private", private_user=user
    )
    row = outbox.queue_message(chat, "Sensitive internal worker discussion", source_key="private:old-scope")[0]
    WorkspaceMembership.objects.filter(workspace=conn.workspace, user=user).update(workspace_role="client")
    client_thread = Conversation.objects.create(workspace=conn.workspace, audience="client", created_by=user)
    TelegramChat.objects.filter(pk=chat.pk).update(conversation=client_thread)
    assert outbox.send_one(row.pk) == "failed"
    row.refresh_from_db()
    assert "audience changed" in row.error
    controlled_api.call.assert_not_called()


def test_review_photo_and_full_text_must_arrive_before_callback_buttons(hub, controlled_api):
    conn, chat = hub
    asset = photo(conn)
    rows = outbox.queue_response(
        conn,
        authenticated(conn, {"update_id": 10, "message": {"chat": {"id": chat.chat_id}}}),
        {"text": "a" * 5000, "photo_asset_id": str(asset.pk), "reply_markup": keyboard()},
    )
    assert len(rows) == 3 and rows[0].kind == "photo"
    assert "reply_markup" not in rows[0].payload and "reply_markup" not in rows[1].payload
    assert outbox.send_one(rows[2].pk) == "skipped"
    assert outbox.send_one(rows[1].pk) == "skipped"
    assert outbox.send_one(rows[0].pk) == "sent"
    assert outbox.send_one(rows[1].pk) == "sent"
    assert outbox.send_one(rows[2].pk) == "sent"
    assert controlled_api.send_photo.call_args.args[1].startswith(b"\x89PNG")
    assert "reply_markup" not in controlled_api.call.call_args_list[0].args[1]
    assert controlled_api.call.call_args_list[1].args[1]["reply_markup"] == keyboard()
    asset.file.delete(save=False)


def test_unknown_review_segment_prevents_any_final_approval_button(hub, controlled_api):
    _, chat = hub
    rows = outbox.queue_message(chat, "a" * 5000, source_key="review:held", reply_markup=keyboard())
    controlled_api.call.side_effect = TelegramAPIError(kind="transport", ambiguous=True)
    assert outbox.send_one(rows[0].pk) == "unknown"
    assert outbox.send_one(rows[1].pk) == "skipped"
    rows[1].refresh_from_db()
    assert rows[1].status == "failed" and "earlier review" in rows[1].error
    assert controlled_api.call.call_count == 1


@pytest.mark.parametrize(
    "markup",
    [
        {"inline_keyboard": [[{"text": "Unsafe link", "url": "https://example.com"}]]},
        {"inline_keyboard": [[{"text": "Approve by raw ID", "callback_data": "approve:raw-post-id"}]]},
        {"inline_keyboard": [[{"text": "Too long", "callback_data": "tg:a:" + "x" * 100}]]},
    ],
)
def test_only_bounded_opaque_action_callbacks_can_be_queued(hub, markup):
    _, chat = hub
    with pytest.raises(ValueError):
        outbox.queue_message(chat, "Review", source_key="unsafe:keyboard", reply_markup=markup)
    assert not TelegramDelivery.objects.exists()


def test_clear_preconnect_failure_has_finite_retry_budget(hub, controlled_api):
    _, chat = hub
    row = outbox.queue_message(chat, "Retry safely", source_key="connect:bounded")[0]
    controlled_api.call.side_effect = TelegramAPIError(kind="connect", ambiguous=False)
    for attempt in range(outbox.MAX_SEND_ATTEMPTS):
        TelegramDelivery.objects.filter(pk=row.pk).update(next_attempt_at=None)
        assert outbox.send_one(row.pk) == ("pending" if attempt < outbox.MAX_SEND_ATTEMPTS - 1 else "failed")
    assert outbox.send_one(row.pk) == "skipped"
    assert controlled_api.call.call_count == outbox.MAX_SEND_ATTEMPTS


def test_queued_delivery_cannot_revive_after_same_bot_reconnect(hub, controlled_api):
    conn, chat = hub
    row = outbox.queue_message(chat, "Old queued reply", source_key="old:same-bot-epoch")[0]
    conn.webhook_secret = "new-secret-after-reconnect"
    conn.save(update_fields=["webhook_secret"])
    assert outbox.send_one(row.pk) == "failed"
    row.refresh_from_db()
    assert "conversation or audience changed" in row.error
    controlled_api.call.assert_not_called()


def test_inflight_disconnect_hold_cannot_be_overwritten_by_late_api_success(hub, controlled_api):
    _, chat = hub
    row = outbox.queue_message(chat, "May already be in flight", source_key="late:success")[0]

    def send(method, params):
        TelegramDelivery.objects.filter(pk=row.pk).update(
            status="unknown", error="Connection disabled while delivery was in flight. Inspect Telegram."
        )
        return {"message_id": 222}

    controlled_api.call.side_effect = send
    assert outbox.send_one(row.pk) == "unknown"
    row.refresh_from_db()
    assert row.status == "unknown" and "Connection disabled" in row.error and row.native_message_id is None


def test_foreign_media_and_changed_tenant_are_rejected_before_transport(hub, user, controlled_api):
    from apps.workspaces.models import Workspace

    conn, chat = hub
    asset = photo(conn)
    foreign = Workspace.objects.create(organization=conn.workspace.organization, name="Other client")
    MediaAsset.objects.filter(pk=asset.pk).update(workspace=foreign)
    assert outbox.queue_photo(chat, asset.pk, source_key="foreign:photo") is None
    row = outbox.queue_message(chat, "Queued before archiving", source_key="archived:message")[0]
    Workspace.objects.filter(pk=conn.workspace_id).update(is_archived=True)
    assert outbox.send_one(row.pk) == "failed"
    controlled_api.call.assert_not_called()
    controlled_api.send_photo.assert_not_called()
    asset.file.delete(save=False)


def test_photo_transport_ambiguity_is_held_and_safe_error_has_no_provider_url(hub, controlled_api):
    conn, chat = hub
    asset = photo(conn)
    row = outbox.queue_photo(chat, asset.pk, source_key="ambiguous:photo")
    controlled_api.send_photo.side_effect = TelegramAPIError(
        "https://api.telegram.org/botFAKE_TOKEN/upload", kind="transport", ambiguous=True
    )
    assert outbox.send_one(row.pk) == "unknown"
    assert outbox.send_one(row.pk) == "skipped"
    row.refresh_from_db()
    assert "FAKE_TOKEN" not in row.error and "https:" not in row.error
    asset.file.delete(save=False)


@pytest.mark.parametrize("change", ["revoked_verifier", "generated_raw_verified"])
def test_photo_caption_rechecks_current_attestation_and_generatedness(hub, user, controlled_api, change):
    from apps.studio import trust

    conn, chat = hub
    pair(conn, user)
    asset = photo(conn)
    asset.authenticity = "verified"
    asset.verified_by = user
    asset.verified_at = timezone.now()
    asset.verified_project = "Attested project"
    asset.verified_asset_hash = trust.asset_stamp(asset)
    asset.save(update_fields=["authenticity", "verified_by", "verified_at", "verified_project", "verified_asset_hash"])
    assert trust.photo_status(asset)["status"] == "verified"
    row = outbox.queue_photo(chat, asset.pk, source_key="photo:current-attestation")
    if change == "revoked_verifier":
        WorkspaceMembership.objects.filter(workspace=conn.workspace, user=user).delete()
    else:
        asset.source = "fal.ai"
        asset.verified_asset_hash = trust.asset_stamp(asset)
        asset.save(update_fields=["source", "verified_asset_hash"])
    assert outbox.send_one(row.pk) == "sent"
    caption = controlled_api.send_photo.call_args.kwargs["caption"]
    assert "Attested project" not in caption and "verified photo:" not in caption.lower()
    assert caption.startswith("Unverified photo" if change == "revoked_verifier" else "Illustrative image")
    asset.file.delete(save=False)


def test_historical_private_conversation_cannot_be_rebound_to_any_group(hub):
    _, chat = hub
    Conversation.objects.filter(pk=chat.conversation_id).update(is_private=True)
    assert not outbox.queue_message(chat, "Private client history", source_key="private-history:client")
    TelegramChat.objects.filter(pk=chat.pk).update(audience="team")
    Conversation.objects.filter(pk=chat.conversation_id).update(audience="internal")
    assert not outbox.queue_message(chat, "Private worker history", source_key="private-history:team")


def test_async_replies_only_mirror_exact_visible_thread(hub, user, django_capture_on_commit_callbacks):
    conn, chat = hub
    other = Conversation.objects.create(workspace=conn.workspace, audience="client", created_by=user)
    with django_capture_on_commit_callbacks(execute=True):
        Message.objects.create(
            conversation=other, author_kind="agent", agent="account_manager", body="Unrelated client reply"
        )
        Message.objects.create(
            conversation=chat.conversation,
            author_kind="staff",
            author=user,
            body="private cost/token note",
            is_internal=True,
        )
        Message.objects.create(conversation=chat.conversation, author_kind="system", body="Provider usage 100 tokens")
        message = Message.objects.create(
            conversation=chat.conversation,
            author_kind="agent",
            agent="account_manager",
            body="The draft is ready for your feedback.",
        )
    assert TelegramDelivery.objects.count() == 1
    assert "draft is ready" in TelegramDelivery.objects.get().payload["text"]
    assert mirror_message(message.pk) == 1
    assert TelegramDelivery.objects.count() == 1


def test_per_user_event_notices_deduplicate_and_never_forward_staff_body(hub, user, django_capture_on_commit_callbacks):
    from apps.accounts.models import User

    conn, chat = hub
    pair(conn, user)
    another = User.objects.create_user(email="second-telegram@example.com", name="Second", password="fake")
    pair(conn, another, telegram_id=100)
    post = bind_post(conn, chat, user)
    with django_capture_on_commit_callbacks(execute=True):
        first = Notification.objects.create(
            user=user,
            event_type="post_approved",
            title="Staff title secret",
            body="Private cost $100 token SECRET",
            data={"post_id": str(post.pk), "workspace_id": str(conn.workspace_id)},
        )
        Notification.objects.create(
            user=another,
            event_type="post_approved",
            title="Other staff title",
            body="Private cost $100",
            data={"post_id": str(post.pk), "workspace_id": str(conn.workspace_id)},
        )
    assert TelegramDelivery.objects.count() == 1
    text = TelegramDelivery.objects.get().payload["text"]
    assert "approved" in text and "Private" not in text and "SECRET" not in text and "Staff title" not in text
    assert notification_event(first.pk) == 1
    assert TelegramDelivery.objects.count() == 1


def test_per_account_publication_receipts_require_native_confirmation(hub, user, django_capture_on_commit_callbacks):
    conn, chat = hub
    post = bind_post(conn, chat, user)
    account = SocialAccount.objects.create(
        workspace=conn.workspace,
        platform="instagram",
        account_name="Client Instagram",
        account_platform_id="fake-ig",
        oauth_access_token="fake",
    )
    pp = PlatformPost.objects.create(post=post, social_account=account)
    with delivery_write():
        PlatformPost.objects.filter(pk=pp.pk).update(
            status="published", platform_post_id="", published_at=timezone.now()
        )
    assert platform_receipt(pp.pk) == 0
    with delivery_write():
        PlatformPost.objects.filter(pk=pp.pk).update(platform_post_id="native-receipt-111")
    assert platform_receipt(pp.pk) == 1
    assert platform_receipt(pp.pk) == 1
    assert TelegramDelivery.objects.count() == 1
    text = TelegramDelivery.objects.get().payload["text"]
    assert "Client Instagram" in text and "native-receipt-111" in text


def test_generated_post_receipt_routes_to_canonical_originating_job_conversation(hub, user):
    conn, chat = hub
    post = Post.objects.create(workspace=conn.workspace, author=user, title="Draft from this thread")
    job = AgencyJob.objects.create(
        workspace=conn.workspace, conversation=chat.conversation, kind="chat", requested_by=user, status="done"
    )
    StudioBrief.objects.create(
        workspace=conn.workspace, author=user, job=job, idea="This group requested the draft", post=post, origin="chat"
    )
    account = SocialAccount.objects.create(
        workspace=conn.workspace,
        platform="instagram",
        account_name="Brand account",
        account_platform_id="origin-ig",
        oauth_access_token="fake",
    )
    pp = PlatformPost.objects.create(post=post, social_account=account)
    with delivery_write():
        PlatformPost.objects.filter(pk=pp.pk).update(
            status="published", platform_post_id="origin-receipt", published_at=timezone.now()
        )
    assert platform_receipt(pp.pk) == 1
    assert TelegramDelivery.objects.filter(chat=chat).count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_senders_claim_once_and_transport_runs_outside_db_lock(hub, controlled_api):
    _, chat = hub
    row = outbox.queue_message(chat, "One send", source_key="concurrent:send")[0]
    entered, release = threading.Event(), threading.Event()

    def send(method, params):
        assert not db_connection.in_atomic_block
        entered.set()
        assert release.wait(timeout=10)
        return {"message_id": 888}

    controlled_api.call.side_effect = send

    def work():
        try:
            return outbox.send_one(row.pk)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(work)
        assert entered.wait(timeout=10)
        second = pool.submit(work)
        try:
            assert second.result(timeout=10) == "skipped"
        finally:
            release.set()
        assert first.result(timeout=10) == "sent"
    assert controlled_api.call.call_count == 1
    row.refresh_from_db()
    assert row.native_message_id == 888 and row.attempts == 1


def test_bounded_retention_clears_transient_content_without_losing_unknown_receipts_or_audit_identity(hub, user):
    from apps.telegram.tasks import cleanup_transient_records

    conn, chat = hub
    link = pair(conn, user)
    old = timezone.now() - timedelta(days=40)
    unknown = TelegramDelivery.objects.create(
        connection=conn,
        chat=chat,
        source_key="held:retention",
        status="unknown",
        payload={"method": "sendMessage", "text": "Expired private text"},
        native_message_id=123,
        error="Inspect the outcome before resending.",
    )
    TelegramDelivery.objects.filter(pk=unknown.pk).update(updated_at=old)
    update = TelegramUpdate.objects.create(
        connection=conn, update_id=88, status="processed", payload={"private": "expired update text"}
    )
    TelegramUpdate.objects.filter(pk=update.pk).update(created_at=old)
    pending = TelegramUpdate.objects.create(
        connection=conn, update_id=89, status="pending", payload={"private": "unfinished task text"}
    )
    TelegramUpdate.objects.filter(pk=pending.pk).update(created_at=old)
    action = TelegramAction.objects.create(
        chat=chat,
        user_link=link,
        kind="approve",
        token_digest="e" * 64,
        snapshot={"caption": "expired review"},
        expires_at=old,
        used_at=old,
        result={"ok": True, "post_id": "canonical-audit-reference"},
    )
    pairing = TelegramPairing.objects.create(
        connection=conn, user=user, token_digest="d" * 64, purpose="user", audience="private", expires_at=old
    )
    assert cleanup_transient_records(limit=1) == 4
    unknown.refresh_from_db()
    update.refresh_from_db()
    pending.refresh_from_db()
    action.refresh_from_db()
    assert unknown.payload == {} and unknown.status == "unknown" and unknown.native_message_id == 123
    assert unknown.source_key == "held:retention" and "Inspect" in unknown.error
    assert update.payload == {} and pending.payload != {}
    assert action.snapshot == {} and action.result["post_id"] == "canonical-audit-reference" and action.used_at == old
    assert not TelegramPairing.objects.filter(pk=pairing.pk).exists()
    assert cleanup_transient_records(limit=1) == 0


def test_week_completion_mirrors_only_exact_internal_thread_and_deduplicates_per_user_notices(
    hub, user, django_capture_on_commit_callbacks, monkeypatch
):
    from apps.accounts.models import User
    from apps.telegram import inbox

    monkeypatch.setattr(inbox, "is_quiet", lambda *a, **k: False)
    conn, chat = hub
    pair(conn, user)
    second = User.objects.create_user(email="weekly-approver@example.com", name="Approver", password="fake")
    pair(conn, second, telegram_id=100)
    week = completed_week(conn, chat, user)
    unrelated = Conversation.objects.create(workspace=conn.workspace, audience="internal", created_by=user)
    TelegramChat.objects.create(
        connection=conn, conversation=unrelated, chat_id=-888, chat_type="supergroup", audience="team"
    )
    with django_capture_on_commit_callbacks(execute=True):
        for recipient in (user, second):
            Notification.objects.create(
                user=recipient,
                event_type="autopilot_planned",
                title="SECRET staff title",
                body="Private AI cost $100 and SECRET token",
                data={"week_id": str(week.pk), "workspace_id": str(conn.workspace_id)},
            )
    rows = list(TelegramDelivery.objects.all())
    # One message in the requesting team thread, plus one inbox line per paired approver, each told once.
    group_rows = [row for row in rows if row.chat_id == chat.pk]
    inbox_rows = [row for row in rows if row.source_key.startswith("inbox:")]
    assert len(rows) == 3 and len(group_rows) == 1 and len(inbox_rows) == 2
    assert {row.chat.private_user_id for row in inbox_rows} == {user.pk, second.pk}
    text = group_rows[0].payload["text"]
    assert "2026-10-19" in text and "human review: 1" in text and "/week" in text
    for row in rows:
        body = row.payload["text"]
        assert "SECRET" not in body and "$100" not in body and "AI cost" not in body
    assert all("Next week is planned" in row.payload["text"] for row in inbox_rows)


@pytest.mark.parametrize(
    "change", ["workspace", "job_workspace", "client_group", "client_role", "revoked", "unfinished"]
)
def test_week_notice_rejects_wrong_scope_client_recipient_and_unfinished_plan(hub, user, change):
    from apps.workspaces.models import Workspace

    conn, chat = hub
    link = pair(conn, user)
    week = completed_week(conn, chat, user)
    data = {"week_id": str(week.pk), "workspace_id": str(conn.workspace_id)}
    if change in {"workspace", "job_workspace"}:
        foreign = Workspace.objects.create(organization=conn.workspace.organization, name="Unrelated weekly client")
        if change == "workspace":
            data["workspace_id"] = str(foreign.pk)
        else:
            AgencyJob.objects.filter(pk=week.job_id).update(workspace=foreign)
    elif change == "client_group":
        TelegramChat.objects.filter(pk=chat.pk).update(audience="client")
        Conversation.objects.filter(pk=chat.conversation_id).update(audience="client")
    elif change == "client_role":
        WorkspaceMembership.objects.filter(user=user, workspace=conn.workspace).update(workspace_role="client")
    elif change == "revoked":
        TelegramUserLink.objects.filter(pk=link.pk).update(is_active=False)
    else:
        AgencyJob.objects.filter(pk=week.job_id).update(status="working")
    notice = Notification.objects.create(
        user=user, event_type="autopilot_planned", title="Do not disclose", body="Private cost", data=data
    )
    assert notification_event(notice.pk) == 0
    assert not TelegramDelivery.objects.exists()
