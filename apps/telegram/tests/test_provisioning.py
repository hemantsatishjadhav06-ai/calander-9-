"""Provision real permission/pairing paths while every Bot API call is mocked."""

from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.db import connection as db
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
from apps.studio.models import Conversation
from apps.telegram import provisioning
from apps.telegram.models import (
    TelegramAction,
    TelegramChat,
    TelegramConnection,
    TelegramDelivery,
    TelegramPairing,
    TelegramUpdate,
    TelegramUserLink,
)
from apps.telegram.permissions import TelegramPermissionDenied, can_manage, current_member, fresh_member
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db
TOKEN = "123456:" + "f" * 32


@pytest.fixture
def hub(organization, org_owner):
    workspace = Workspace.objects.create(
        organization=organization, name="Neopolis Telegram", require_dashboard_approval=True
    )
    WorkspaceMembership.objects.create(workspace=workspace, user=org_owner, workspace_role="owner")
    conn = TelegramConnection.objects.create(
        workspace=workspace,
        token=TOKEN,
        webhook_secret="fake-webhook-secret",
        bot_id=123456,
        bot_username="fake_test_bot",
        is_active=True,
        webhook_status="active",
        created_by=org_owner,
    )
    return workspace, org_owner, conn


@pytest.fixture(autouse=True)
def no_live_bot(monkeypatch):
    api = Mock()
    api.get_me.return_value = {"id": 123456, "is_bot": True, "username": "fake_test_bot"}
    api.get_webhook_info.return_value = {"url": ""}
    api.set_webhook.return_value = True
    api.get_chat_member.side_effect = lambda chat_id, user_id: {"status": "administrator", "user": {"id": user_id}}
    monkeypatch.setattr(provisioning, "BotAPI", Mock(return_value=api))
    monkeypatch.setattr(provisioning, "resolve_public_ip", lambda url: "1.1.1.1")
    return api


@pytest.fixture
def ready(settings):
    settings.TELEGRAM_WEBHOOK_READY = True
    settings.TELEGRAM_WEBHOOK_BASE_URL = "https://smbean.example.com"


def paired(conn, user, numeric=909):
    return TelegramUserLink.objects.create(connection=conn, user=user, telegram_user_id=numeric)


def client_member(workspace, *, facing=False):
    user = User.objects.create_user(
        email="portal-client@example.com", password="test", name="Client", tos_accepted_at=timezone.now()
    )
    role = None
    if facing:
        role = CustomRole.objects.create(
            organization=workspace.organization,
            name="External",
            permissions={
                "client_facing": True,
                "create_posts": True,
                "approve_posts": True,
                "manage_workspace_settings": True,
            },
        )
    WorkspaceMembership.objects.create(
        workspace=workspace, user=user, workspace_role="editor" if facing else "client", custom_role=role
    )
    return user


def group_ticket(conn, user, audience="client"):
    paired(conn, user)
    return provisioning.issue_pairing(conn, user, purpose="chat", audience=audience)


def test_connect_encrypts_and_registers_only_confirmed_public_deployment(hub, ready, no_live_bot):
    workspace, user, conn = hub
    result = provisioning.connect(workspace, user, TOKEN, approvals_enabled=True)
    assert result.is_active and result.approvals_enabled and result.webhook_status == "active"
    no_live_bot.set_webhook.assert_called_once_with(
        "https://smbean.example.com" + reverse("telegram_webhooks:ingress", kwargs={"connection_id": conn.pk}),
        "fake-webhook-secret",
    )
    with db.cursor() as cursor:
        cursor.execute("SELECT token, webhook_secret FROM telegram_connection WHERE id=%s", [conn.pk])
        raw = cursor.fetchone()
    assert TOKEN not in str(raw) and "fake-webhook-secret" not in str(raw)


def test_undeployed_new_bot_stored_inactive_without_webhook(hub, settings, no_live_bot):
    workspace, user, conn = hub
    conn.delete()
    settings.TELEGRAM_WEBHOOK_READY = False
    settings.TELEGRAM_WEBHOOK_BASE_URL = "https://smbean.example.com"
    result = provisioning.connect(workspace, user, TOKEN)
    assert not result.is_active and result.webhook_status == "pending_deployment"
    no_live_bot.set_webhook.assert_not_called()
    with pytest.raises(provisioning.ProvisioningError):
        provisioning.issue_pairing(result, user)


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:8000",
        "https://localhost",
        "https://127.0.0.1",
        "https://10.0.0.5",
        "https://[::1]",
        "https://test.example.com:bad",
        "https://user:pass@test.example.com",
        "https://test.example.com/path",
        "https://test.example.com?x=1",
    ],
)
def test_unsafe_or_non_origin_webhook_never_registered(hub, settings, origin, no_live_bot):
    workspace, user, conn = hub
    conn.delete()
    settings.TELEGRAM_WEBHOOK_READY = True
    settings.TELEGRAM_WEBHOOK_BASE_URL = origin
    result = provisioning.connect(workspace, user, TOKEN)
    assert not result.is_active
    no_live_bot.set_webhook.assert_not_called()


def test_dns_private_webhook_stays_inactive(hub, ready, monkeypatch, no_live_bot):
    workspace, user, conn = hub
    conn.delete()
    monkeypatch.setattr(provisioning, "resolve_public_ip", lambda url: None)
    result = provisioning.connect(workspace, user, TOKEN)
    assert not result.is_active
    no_live_bot.set_webhook.assert_not_called()


def test_foreign_webhook_and_bot_assignment_preserve_working_bot(hub, ready, no_live_bot):
    workspace, user, conn = hub
    no_live_bot.get_webhook_info.return_value = {"url": "https://foreign.example.com/webhook"}
    with pytest.raises(provisioning.ProvisioningError, match="different webhook"):
        provisioning.connect(workspace, user, TOKEN)
    no_live_bot.set_webhook.assert_not_called()
    conn.refresh_from_db()
    assert conn.token == TOKEN and conn.is_active
    other = Workspace.objects.create(organization=workspace.organization, name="Other")
    WorkspaceMembership.objects.create(workspace=other, user=user, workspace_role="owner")
    no_live_bot.get_webhook_info.return_value = {"url": ""}
    with pytest.raises(provisioning.ProvisioningError, match="another workspace"):
        provisioning.connect(other, user, TOKEN)
    no_live_bot.set_webhook.assert_not_called()


def test_failed_webhook_preserves_old_secret_and_active_connection(hub, ready, no_live_bot):
    workspace, user, conn = hub
    no_live_bot.set_webhook.side_effect = RuntimeError(TOKEN + " private provider text")
    with pytest.raises(provisioning.ProvisioningError) as exc:
        provisioning.connect(workspace, user, TOKEN)
    assert TOKEN not in str(exc.value) and "provider text" not in str(exc.value)
    conn.refresh_from_db()
    assert conn.is_active and conn.webhook_secret == "fake-webhook-secret" and conn.webhook_status == "active"


def test_duplicate_setup_reserved_before_external_write(hub, ready, no_live_bot):
    workspace, user, conn = hub
    conn.delete()
    other = Workspace.objects.create(organization=workspace.organization, name="Race competitor")
    WorkspaceMembership.objects.create(workspace=other, user=user, workspace_role="owner")

    def set_webhook(url, secret):
        reservation = TelegramConnection.objects.get(workspace=workspace)
        assert not reservation.is_active and reservation.webhook_status == "setup_in_progress"
        with pytest.raises(provisioning.ProvisioningError, match="another workspace"):
            provisioning.connect(other, user, TOKEN)
        return True

    no_live_bot.set_webhook.side_effect = set_webhook
    result = provisioning.connect(workspace, user, TOKEN)
    assert result.is_active
    assert no_live_bot.set_webhook.call_count == 1


def test_disconnect_mid_setup_cannot_be_reenabled(hub, ready, no_live_bot):
    workspace, user, conn = hub

    def set_webhook(url, secret):
        provisioning.disconnect(TelegramConnection.objects.get(pk=conn.pk), user)
        return True

    no_live_bot.set_webhook.side_effect = set_webhook
    with pytest.raises(provisioning.ProvisioningError, match="changed"):
        provisioning.connect(workspace, user, TOKEN)
    conn.refresh_from_db()
    assert not conn.is_active and not conn.token and not conn.webhook_secret


def test_approval_opt_in_never_weakens_workspace_gate(hub, ready, no_live_bot):
    workspace, user, conn = hub
    workspace.require_dashboard_approval = False
    workspace.save(update_fields=["require_dashboard_approval"])
    with pytest.raises(provisioning.ProvisioningError, match="approval gate"):
        provisioning.connect(workspace, user, TOKEN, approvals_enabled=True)
    no_live_bot.set_webhook.assert_not_called()
    conn.refresh_from_db()
    assert not conn.approvals_enabled and not workspace.require_dashboard_approval


def test_revoked_custom_owner_settings_permission_blocks_bot_and_groups(hub, ready, no_live_bot):
    workspace, user, conn = hub
    member = WorkspaceMembership.objects.get(workspace=workspace, user=user)
    member.custom_role = CustomRole.objects.create(
        organization=workspace.organization, name="Revoked owner", permissions={}
    )
    member.save(update_fields=["custom_role"])
    link = paired(conn, user)
    assert not can_manage(current_member(workspace, user))
    with pytest.raises(TelegramPermissionDenied):
        provisioning.connect(workspace, user, TOKEN)
    with pytest.raises(TelegramPermissionDenied):
        provisioning.issue_pairing(conn, user, purpose="chat", audience="team")
    with pytest.raises(TelegramPermissionDenied):
        fresh_member(link, "approve_posts")
    no_live_bot.get_me.assert_not_called()


def test_pairing_digest_is_one_use_expiring_and_private(hub):
    workspace, user, conn = hub
    ticket, nonce = provisioning.issue_pairing(conn, user)
    assert nonce != ticket.token_digest and ticket.token_digest == provisioning.digest(nonce)
    assert timedelta(minutes=9) < ticket.expires_at - timezone.now() <= timedelta(minutes=10)
    link = provisioning.consume_user_pairing(conn, nonce, 909, "untrusted_username")
    assert link.user == user and link.telegram_user_id == 909
    chat = TelegramChat.objects.get(connection=conn)
    assert chat.private_user == user and chat.chat_id == 909 and chat.conversation.audience == "internal"
    assert chat.conversation.workspace == workspace and chat.conversation.created_by == user
    with pytest.raises(provisioning.ProvisioningError):
        provisioning.consume_user_pairing(conn, nonce, 910)
    _, expired = provisioning.issue_pairing(conn, user)
    TelegramPairing.objects.filter(token_digest=provisioning.digest(expired)).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    with pytest.raises(provisioning.ProvisioningError):
        provisioning.consume_user_pairing(conn, expired, 909)


@pytest.mark.parametrize("facing", [False, True])
def test_ws_only_external_client_can_pair_private_but_never_internal(hub, facing):
    workspace, _, conn = hub
    user = client_member(workspace, facing=facing)
    _, nonce = provisioning.issue_pairing(conn, user)
    link = provisioning.consume_user_pairing(conn, nonce, 808)
    chat = provisioning.private_chat(conn, link)
    assert chat.conversation.audience == "client" and chat.private_user == user
    with pytest.raises(TelegramPermissionDenied):
        provisioning.issue_pairing(conn, user, purpose="chat", audience="team")
    with pytest.raises(TelegramPermissionDenied):
        fresh_member(link, "approve_posts")
    with pytest.raises(TelegramPermissionDenied):
        provisioning.disconnect(conn, user)


def test_removed_internal_org_membership_cannot_consume_or_use_pairing(hub):
    workspace, user, conn = hub
    _, nonce = provisioning.issue_pairing(conn, user)
    link = paired(conn, user)
    OrgMembership.objects.filter(organization=workspace.organization, user=user).delete()
    with pytest.raises(TelegramPermissionDenied):
        provisioning.consume_user_pairing(conn, nonce, 909)
    with pytest.raises(TelegramPermissionDenied):
        fresh_member(link)
    assert TelegramPairing.objects.get(token_digest=provisioning.digest(nonce)).used_at is None


def test_role_downgrade_creates_client_private_conversation_without_old_history(hub):
    workspace, user, conn = hub
    link = paired(conn, user)
    old = provisioning.private_chat(conn, link)
    old_conversation = old.conversation_id
    WorkspaceMembership.objects.filter(workspace=workspace, user=user).update(workspace_role="client")
    OrgMembership.objects.filter(organization=workspace.organization, user=user).delete()
    chat = provisioning.private_chat(conn, link)
    assert chat.conversation_id != old_conversation and chat.conversation.audience == "client"
    assert Conversation.objects.get(pk=old_conversation).audience == "internal"


def test_numeric_identity_conflict_and_stolen_group_nonce_do_not_pair(hub):
    workspace, user, conn = hub
    paired(conn, user, 909)
    outsider = client_member(workspace)
    _, nonce = provisioning.issue_pairing(conn, outsider)
    with pytest.raises(provisioning.ProvisioningError, match="already paired"):
        provisioning.consume_user_pairing(conn, nonce, 909)
    _, group_nonce = provisioning.issue_pairing(conn, user, purpose="chat", audience="client")
    paired(conn, outsider, 808)
    with pytest.raises(TelegramPermissionDenied):
        provisioning.consume_chat_pairing(conn, group_nonce, 808, -100, "supergroup")
    assert not TelegramChat.objects.exists()


@pytest.mark.parametrize("status", ["member", "left", "restricted", "kicked"])
def test_group_mapping_requires_real_telegram_administrator(hub, no_live_bot, status):
    _, user, conn = hub
    _, nonce = group_ticket(conn, user)
    no_live_bot.get_chat_member.return_value = {"status": status, "user": {"id": 909}}
    no_live_bot.get_chat_member.side_effect = None
    with pytest.raises(TelegramPermissionDenied):
        provisioning.consume_chat_pairing(conn, nonce, 909, -100, "supergroup", "Agency")
    assert not TelegramChat.objects.exists()
    assert TelegramPairing.objects.get(token_digest=provisioning.digest(nonce)).used_at is None


def test_group_pairing_separates_client_team_and_cannot_switch_old_group_audience(hub):
    workspace, user, conn = hub
    _, nonce = group_ticket(conn, user, "client")
    client = provisioning.consume_chat_pairing(conn, nonce, 909, -100, "supergroup", "Client")
    _, team_nonce = provisioning.issue_pairing(conn, user, purpose="chat", audience="team")
    with pytest.raises(provisioning.ProvisioningError, match="different audience"):
        provisioning.consume_chat_pairing(conn, team_nonce, 909, -100, "supergroup")
    provisioning.deactivate_chat(conn, user, client.pk)
    old_conversation = client.conversation_id
    with pytest.raises(provisioning.ProvisioningError, match="different audience"):
        provisioning.consume_chat_pairing(conn, team_nonce, 909, -100, "supergroup", "Team")
    team = provisioning.consume_chat_pairing(conn, team_nonce, 909, -101, "supergroup", "Team")
    assert team.conversation_id != old_conversation and team.conversation.audience == "internal"
    assert Conversation.objects.get(pk=old_conversation).audience == "client"
    assert team.connection.workspace == workspace


def test_group_admin_check_rechecks_revocation_and_bot_changes(hub, no_live_bot):
    workspace, user, conn = hub
    _, nonce = group_ticket(conn, user)

    def check(chat_id, user_id):
        WorkspaceMembership.objects.filter(workspace=workspace, user=user).update(workspace_role="client")
        return {"status": "creator", "user": {"id": user_id}}

    no_live_bot.get_chat_member.side_effect = check
    with pytest.raises(TelegramPermissionDenied):
        provisioning.consume_chat_pairing(conn, nonce, 909, -100, "supergroup")
    assert not TelegramChat.objects.exists()


def test_foreign_workspace_connection_move_is_rejected(hub, ready, no_live_bot):
    workspace, user, conn = hub
    other = Workspace.objects.create(organization=workspace.organization, name="Foreign workspace")
    WorkspaceMembership.objects.create(workspace=other, user=user, workspace_role="owner")

    def setup(url, secret):
        TelegramConnection.objects.filter(pk=conn.pk).update(workspace=other)
        return True

    no_live_bot.set_webhook.side_effect = setup
    with pytest.raises(TelegramPermissionDenied):
        provisioning.connect(workspace, user, TOKEN)
    conn.refresh_from_db()
    assert not conn.is_active and not conn.token


def test_unpair_preserves_audit_but_blocks_old_identity_and_allows_new(hub):
    _, user, conn = hub
    _, nonce = provisioning.issue_pairing(conn, user)
    link = provisioning.consume_user_pairing(conn, nonce, 909)
    old = TelegramChat.objects.get(connection=conn, chat_id=909)
    provisioning.unpair(conn, user)
    old.refresh_from_db()
    assert not old.is_active
    with pytest.raises(TelegramPermissionDenied):
        fresh_member(link)
    _, nonce = provisioning.issue_pairing(conn, user)
    changed = provisioning.consume_user_pairing(conn, nonce, 808)
    assert changed.telegram_user_id == 808
    assert TelegramChat.objects.get(connection=conn, chat_id=808).private_user == user
    assert TelegramChat.objects.filter(pk=old.pk).exists()


@pytest.mark.parametrize(
    "message",
    [
        {"from": "invalid", "chat": {}},
        {"from": {"id": True}, "chat": {}},
        {"from": {"id": 909}, "chat": {}, "forward_origin": {"type": "user"}},
        {"from": {"id": 909}, "sender_chat": {"id": -100}, "chat": {}},
    ],
)
def test_forwarded_anonymous_and_malformed_pairing_messages_denied(hub, message):
    _, _, conn = hub
    with pytest.raises(TelegramPermissionDenied):
        provisioning.consume_pairing_message(conn, message)


def test_complete_private_command_requires_own_numeric_chat(hub):
    _, user, conn = hub
    _, nonce = provisioning.issue_pairing(conn, user)
    with pytest.raises(provisioning.ProvisioningError):
        provisioning.consume_pairing_message(
            conn, {"from": {"id": 909}, "chat": {"id": 808, "type": "private"}, "text": "/start " + nonce}
        )
    link = provisioning.consume_pairing_message(
        conn, {"from": {"id": 909}, "chat": {"id": 909, "type": "private"}, "text": "/start " + nonce}
    )
    assert link.telegram_user_id == 909


def test_owner_ui_never_echoes_credentials_and_nonce_is_not_reloaded(hub, client, ready, no_live_bot):
    workspace, user, conn = hub
    client.force_login(user)
    settings_url = reverse("telegram:settings", kwargs={"workspace_id": workspace.pk})
    response = client.get(settings_url)
    assert (
        response.status_code == 200
        and TOKEN not in response.content.decode()
        and conn.webhook_secret not in response.content.decode()
    )
    assert response["Cache-Control"] == "no-store"
    assert response["Referrer-Policy"] == "same-origin"
    response = client.post(
        reverse("telegram:pair", kwargs={"workspace_id": workspace.pk}), {"purpose": "user", "audience": "private"}
    )
    assert response.status_code == 200
    nonce = response.context["pairing_command"].split()[1]
    assert nonce in response.content.decode()
    assert nonce not in client.get(settings_url).content.decode()
    no_live_bot.get_me.side_effect = RuntimeError(TOKEN)
    response = client.post(reverse("telegram:connect", kwargs={"workspace_id": workspace.pk}), {"token": TOKEN})
    assert response.status_code == 400 and TOKEN not in response.content.decode()


def test_ws_only_client_can_view_pair_page_but_not_bot_settings_or_group(hub, client):
    workspace, _, conn = hub
    user = client_member(workspace)
    client.force_login(user)
    url = reverse("telegram:settings", kwargs={"workspace_id": workspace.pk})
    response = client.get(url)
    assert response.status_code == 200 and "Validate and connect bot" not in response.content.decode()
    assert (
        client.post(
            reverse("telegram:pair", kwargs={"workspace_id": workspace.pk}), {"purpose": "user", "audience": "private"}
        ).status_code
        == 200
    )
    assert (
        client.post(reverse("telegram:connect", kwargs={"workspace_id": workspace.pk}), {"token": TOKEN}).status_code
        == 403
    )
    assert (
        client.post(
            reverse("telegram:pair", kwargs={"workspace_id": workspace.pk}),
            {"purpose": "chat", "audience": "team", "group_membership_confirmed": "on"},
        ).status_code
        == 403
    )
    assert client.post(reverse("telegram:disconnect", kwargs={"workspace_id": workspace.pk})).status_code == 403
    conn.refresh_from_db()
    assert conn.is_active


def test_disconnect_clears_only_own_workspace_and_invalidates_all_pairings(hub):
    workspace, user, conn = hub
    _, nonce = provisioning.issue_pairing(conn, user)
    link = provisioning.consume_user_pairing(conn, nonce, 909)
    _, unused = provisioning.issue_pairing(conn, user)
    other = Workspace.objects.create(organization=workspace.organization, name="Other active client")
    remote = TelegramConnection.objects.create(
        workspace=other, token="987654:" + "x" * 32, webhook_secret="other-fake-secret", bot_id=987654, is_active=True
    )
    provisioning.disconnect(conn, user)
    conn.refresh_from_db()
    remote.refresh_from_db()
    assert not conn.token and not conn.webhook_secret and not conn.is_active and not conn.approvals_enabled
    assert remote.is_active and remote.token
    assert not conn.chats.filter(is_active=True).exists()
    assert not conn.user_links.filter(is_active=True).exists()
    assert TelegramPairing.objects.get(token_digest=provisioning.digest(unused)).used_at is not None
    with pytest.raises(TelegramPermissionDenied):
        fresh_member(link)


@pytest.mark.parametrize("numeric", [True, 0, -1, 2**63, 2**100])
def test_numeric_identity_outside_database_bounds_rejected_without_consuming(hub, numeric):
    _, user, conn = hub
    _, nonce = provisioning.issue_pairing(conn, user)
    with pytest.raises(provisioning.ProvisioningError):
        provisioning.consume_user_pairing(conn, nonce, numeric)
    assert TelegramPairing.objects.get(token_digest=provisioning.digest(nonce)).used_at is None


def test_malformed_custom_role_cannot_grant_authority(hub):
    workspace, user, conn = hub
    member = WorkspaceMembership.objects.get(workspace=workspace, user=user)
    member.custom_role = CustomRole.objects.create(
        organization=workspace.organization, name="Invalid role", permissions=["manage_workspace_settings"]
    )
    member.save(update_fields=["custom_role"])
    with pytest.raises(TelegramPermissionDenied):
        provisioning.issue_pairing(conn, user)


def test_same_origin_form_submission_passes_real_csrf_checks(hub, no_live_bot):
    workspace, user, _ = hub
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(user)
    page = browser.get(reverse("telegram:settings", kwargs={"workspace_id": workspace.pk}))
    assert page["Referrer-Policy"] == "same-origin"
    token = browser.cookies["csrftoken"].value
    url = reverse("telegram:connect", kwargs={"workspace_id": workspace.pk})
    # An invalid credential should reach form validation, rather than be
    # rejected by CSRF middleware as the previous no-referrer browser POST was.
    result = browser.post(url, {"csrfmiddlewaretoken": token, "token": "invalid"}, HTTP_ORIGIN="http://testserver")
    assert result.status_code == 400 and "Enter the complete bot token" in result.content.decode()
    assert browser.post(url, {"csrfmiddlewaretoken": token, "token": "invalid"}, HTTP_ORIGIN="null").status_code == 403
    no_live_bot.get_me.assert_not_called()


def test_disabled_private_chat_never_reactivates_from_ordinary_message(hub):
    _, user, conn = hub
    link = paired(conn, user)
    chat = provisioning.private_chat(conn, link)
    original = chat.conversation_id
    provisioning.deactivate_chat(conn, user, chat.pk)
    with pytest.raises(TelegramPermissionDenied, match="disabled"):
        provisioning.private_chat(conn, link)
    chat.refresh_from_db()
    assert not chat.is_active and chat.conversation_id == original
    # An authenticated, fresh one-use pairing is an explicit new permission.
    _, nonce = provisioning.issue_pairing(conn, user)
    provisioning.consume_user_pairing(conn, nonce, 909)
    chat.refresh_from_db()
    assert chat.is_active and chat.conversation_id != original


def test_disconnect_holds_old_inbound_and_outbound_audit_rows(hub, ready):
    workspace, user, conn = hub
    link = paired(conn, user)
    chat = provisioning.private_chat(conn, link)
    pending = TelegramUpdate.objects.create(
        connection=conn, update_id=101, payload={"update_id": 101}, status="pending"
    )
    working = TelegramUpdate.objects.create(
        connection=conn, update_id=102, payload={"update_id": 102}, status="working", claimed_at=timezone.now()
    )
    queued = TelegramDelivery.objects.create(
        connection=conn, chat=chat, source_key="old:pending", payload={"text": "old reply"}
    )
    sending = TelegramDelivery.objects.create(
        connection=conn,
        chat=chat,
        source_key="old:sending",
        payload={"text": "send may exist"},
        status="sending",
        claimed_at=timezone.now(),
    )
    old_secret = conn.webhook_secret
    provisioning.disconnect(conn, user)
    for row in (pending, working, queued, sending):
        row.refresh_from_db()
    assert pending.status == working.status == queued.status == "failed"
    assert sending.status == "unknown" and "Inspect" in sending.error
    restored = provisioning.connect(workspace, user, TOKEN)
    assert restored.is_active and restored.webhook_secret != old_secret
    assert TelegramUpdate.objects.count() == 2 and TelegramDelivery.objects.count() == 2
    assert not TelegramUpdate.objects.filter(status="pending").exists()
    assert not TelegramDelivery.objects.filter(status="pending").exists()


def test_chat_deactivation_only_invalidates_that_numeric_chats_queue(hub):
    _, user, conn = hub
    link = paired(conn, user)
    chat = provisioning.private_chat(conn, link)
    own = TelegramUpdate.objects.create(connection=conn, update_id=201, payload={"message": {"chat": {"id": 909}}})
    other = TelegramUpdate.objects.create(connection=conn, update_id=202, payload={"message": {"chat": {"id": -100}}})
    own_delivery = TelegramDelivery.objects.create(
        connection=conn, chat=chat, source_key="private:old", payload={"text": "reply"}
    )
    provisioning.deactivate_chat(conn, user, chat.pk)
    own.refresh_from_db()
    other.refresh_from_db()
    own_delivery.refresh_from_db()
    assert own.status == own_delivery.status == "failed"
    assert other.status == "pending"


def test_unpair_invalidates_original_cards_in_private_and_group_chats(hub):
    _, user, conn = hub
    link = paired(conn, user)
    private = provisioning.private_chat(conn, link)
    conversation = Conversation.objects.create(workspace=conn.workspace, audience="internal")
    group = TelegramChat.objects.create(
        connection=conn, chat_id=-100909, chat_type="supergroup", audience="team", conversation=conversation
    )
    cards = [
        TelegramAction.objects.create(
            chat=chat,
            user_link=link,
            kind="prepare",
            token_digest=str(index) * 64,
            expires_at=timezone.now() + timedelta(minutes=10),
            snapshot={"local": "fixture"},
        )
        for index, chat in enumerate((private, group), start=1)
    ]
    provisioning.unpair(conn, user)
    for card in cards:
        card.refresh_from_db()
        assert card.used_at and card.result == {"ok": False, "reason": "identity_unpaired"}
    group.refresh_from_db()
    assert group.is_active


def test_disconnect_invalidates_all_unconsumed_action_proofs(hub):
    _, user, conn = hub
    link = paired(conn, user)
    private = provisioning.private_chat(conn, link)
    card = TelegramAction.objects.create(
        chat=private,
        user_link=link,
        kind="approve",
        token_digest="f" * 64,
        expires_at=timezone.now() + timedelta(minutes=10),
        snapshot={"local": "fixture"},
    )
    provisioning.disconnect(conn, user)
    card.refresh_from_db()
    assert card.used_at and card.result == {"ok": False, "reason": "access_revoked"}
