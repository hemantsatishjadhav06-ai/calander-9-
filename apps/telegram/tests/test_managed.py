"""Managed provisioning needs explicit Telegram consent and fresh tenant authority."""

import json
from datetime import timedelta
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from django.db import connection as db
from django.test import RequestFactory
from django.utils import timezone

from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.telegram import managed, processing, provisioning
from apps.telegram.models import (
    TelegramConnection,
    TelegramDelivery,
    TelegramManagedBotReservation,
    TelegramUpdate,
    TelegramUserLink,
)
from apps.telegram.permissions import TelegramPermissionDenied
from apps.telegram.webhooks import ingress
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db
MANAGER_TOKEN = "123456:" + "m" * 32
CHILD_TOKEN = "654321:" + "c" * 32


@pytest.fixture
def environment(organization, org_owner, settings, monkeypatch):
    settings.TELEGRAM_WEBHOOK_READY = True
    settings.TELEGRAM_WEBHOOK_BASE_URL = "https://smbean.example.com"
    settings.TELEGRAM_MANAGED_BOTS_ENABLED = True
    monkeypatch.setattr(provisioning, "resolve_public_ip", lambda _: "1.1.1.1")
    agency = Workspace.objects.create(organization=organization, name="Agency manager")
    company = Workspace.objects.create(organization=organization, name="Neopolis & partners")
    for workspace in (agency, company):
        WorkspaceMembership.objects.create(workspace=workspace, user=org_owner, workspace_role="owner")
    manager = TelegramConnection.objects.create(
        workspace=agency,
        token=MANAGER_TOKEN,
        webhook_secret="fake-manager-secret",
        bot_id=123456,
        bot_username="agency_manager_bot",
        is_active=True,
        webhook_status="active",
        created_by=org_owner,
    )
    link = TelegramUserLink.objects.create(connection=manager, user=org_owner, telegram_user_id=909)
    chat = provisioning.private_chat(manager, link)
    manager_api = Mock()
    manager_api.get_me.return_value = {
        "id": manager.bot_id,
        "is_bot": True,
        "username": manager.bot_username,
        "can_manage_bots": True,
    }
    manager_api.get_managed_bot_token.return_value = CHILD_TOKEN
    manager_api.get_webhook_info.return_value = {
        "url": provisioning._webhook_url(manager.pk),
        "allowed_updates": ["message", "callback_query", "my_chat_member", "managed_bot"],
    }
    monkeypatch.setattr(managed, "BotAPI", Mock(return_value=manager_api))
    child_api = Mock()
    child_api.get_me.side_effect = lambda: {
        "id": 654321,
        "is_bot": True,
        "username": TelegramManagedBotReservation.objects.get(status="connecting").requested_username,
    }
    child_api.get_webhook_info.return_value = {"url": ""}
    child_api.set_webhook.return_value = True
    monkeypatch.setattr(provisioning, "BotAPI", Mock(return_value=child_api))
    return company, org_owner, manager, link, chat, manager_api, child_api


def reserve(environment):
    company, actor, manager, *_ = environment
    return managed.begin_managed_bot_creation(company, actor, manager.pk)


def event(reservation, *, owner=909, bot_id=654321, username=None):
    return {
        "user": {"id": owner, "is_bot": False},
        "bot": {"id": bot_id, "is_bot": True, "username": username or reservation.requested_username},
    }


def test_request_reserves_official_human_confirmation_link_without_creating_bot(environment):
    company, actor, manager, _, _, manager_api, child_api = environment
    reservation, url = reserve(environment)
    parsed = urlsplit(url)
    assert parsed.netloc == "t.me" and parsed.scheme == "https"
    assert parsed.path == f"/newbot/{manager.bot_username}/{reservation.requested_username}"
    assert parse_qs(parsed.query) == {"name": [company.name]}
    assert len(reservation.requested_username) == 30 and reservation.requested_username.endswith("bot")
    assert reservation.requested_by == actor and reservation.workspace == company
    assert reservation.telegram_owner_id == 909 and reservation.used_at is None
    assert timedelta(minutes=9) < reservation.expires_at - timezone.now() <= timedelta(minutes=10)
    assert not TelegramConnection.objects.filter(workspace=company).exists()
    manager_api.get_managed_bot_token.assert_not_called()
    child_api.set_webhook.assert_not_called()
    assert MANAGER_TOKEN not in url and CHILD_TOKEN not in url


def test_same_pending_request_is_reused_and_expired_request_gets_new_username(environment):
    old, old_url = reserve(environment)
    again, again_url = reserve(environment)
    assert old.pk == again.pk and old_url == again_url
    TelegramManagedBotReservation.objects.filter(pk=old.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    new, _ = reserve(environment)
    old.refresh_from_db()
    assert old.status == "cancelled" and new.requested_username != old.requested_username


@pytest.mark.parametrize("capability", [False, None, "true", 1])
def test_incapable_manager_offers_botfather_fallback_without_reservation(environment, capability):
    environment[5].get_me.return_value["can_manage_bots"] = capability
    with pytest.raises(managed.ManagedBotError, match="BotFather"):
        reserve(environment)
    assert not TelegramManagedBotReservation.objects.exists()
    environment[5].get_managed_bot_token.assert_not_called()
    environment[6].set_webhook.assert_not_called()


def test_feature_disabled_and_unready_webhook_make_no_network_calls(environment, settings):
    settings.TELEGRAM_MANAGED_BOTS_ENABLED = False
    with pytest.raises(managed.ManagedBotError, match="disabled"):
        reserve(environment)
    settings.TELEGRAM_MANAGED_BOTS_ENABLED = True
    settings.TELEGRAM_WEBHOOK_READY = False
    with pytest.raises(managed.ManagedBotError, match="HTTPS webhook"):
        reserve(environment)
    environment[5].get_me.assert_not_called()


@pytest.mark.parametrize("missing", ["link", "chat", "manager", "manager_role", "target_role", "organization"])
def test_request_requires_current_settings_authority_and_active_private_pairing(environment, missing):
    company, actor, manager, link, chat, manager_api, _ = environment
    if missing == "link":
        TelegramUserLink.objects.filter(pk=link.pk).update(is_active=False)
    elif missing == "chat":
        manager.chats.filter(pk=chat.pk).update(is_active=False)
    elif missing == "manager":
        TelegramConnection.objects.filter(pk=manager.pk).update(is_active=False)
    elif missing == "manager_role":
        WorkspaceMembership.objects.filter(workspace=manager.workspace, user=actor).update(workspace_role="client")
    elif missing == "target_role":
        WorkspaceMembership.objects.filter(workspace=company, user=actor).update(workspace_role="client")
    else:
        OrgMembership.objects.filter(organization=company.organization, user=actor).delete()
    with pytest.raises((managed.ManagedBotError, TelegramPermissionDenied)):
        reserve(environment)
    manager_api.get_me.assert_not_called()
    assert not TelegramManagedBotReservation.objects.exists()


def test_foreign_organization_manager_is_unavailable_even_with_memberships(environment):
    company, actor, manager, *_ = environment
    other = Organization.objects.create(name="Other tenant")
    company.organization = other
    company.save(update_fields=["organization"])
    OrgMembership.objects.create(organization=other, user=actor, org_role="owner")
    assert managed.available_managers(company, actor) == []
    with pytest.raises(TelegramPermissionDenied, match="organization"):
        reserve(environment)


def test_available_managers_is_read_only_and_excludes_unpaired_or_foreign_chats(environment):
    company, actor, manager, _, chat, api, _ = environment
    assert managed.available_managers(company, actor) == [manager]
    chat.conversation.is_private = False
    chat.conversation.save(update_fields=["is_private"])
    assert managed.available_managers(company, actor) == []
    api.get_me.assert_not_called()


def test_active_company_bot_cannot_be_silently_replaced(environment):
    company = environment[0]
    TelegramConnection.objects.create(workspace=company, token=CHILD_TOKEN, bot_id=654321, is_active=True)
    with pytest.raises(managed.ManagedBotError, match="already has an active bot"):
        reserve(environment)
    environment[5].get_me.assert_not_called()


def test_authenticated_matching_event_connects_once_and_encrypts_child_token(environment):
    company, _, manager, _, _, manager_api, child_api = environment
    reservation, _ = reserve(environment)
    update = event(reservation)
    assert managed.process_managed_bot_update(manager, update) == {"status": "connected"}
    connected = TelegramConnection.objects.get(workspace=company)
    assert connected.is_active and connected.bot_id == 654321 and connected.token == CHILD_TOKEN
    assert connected.bot_username == reservation.requested_username
    assert not connected.approvals_enabled  # The approval gate is separately explicit.
    reservation.refresh_from_db()
    assert reservation.status == "connected" and reservation.used_at and reservation.completed_at
    with db.cursor() as cursor:
        cursor.execute("SELECT token FROM telegram_connection WHERE bot_id = %s", [654321])
        stored = cursor.fetchone()[0]
    assert stored != CHILD_TOKEN and CHILD_TOKEN not in stored
    assert managed.process_managed_bot_update(manager, update) == {"status": "ignored"}
    manager_api.get_managed_bot_token.assert_called_once_with(654321)
    child_api.set_webhook.assert_called_once()


@pytest.mark.parametrize(
    "change",
    [
        "foreign_owner",
        "foreign_username",
        "foreign_manager",
        "expired",
        "revoked",
        "repaired",
        "renamed_manager",
        "removed_actor",
        "role_removed",
        "private_chat_disabled",
    ],
)
def test_foreign_stale_deauthorized_and_replayed_events_cannot_configure_company(environment, change):
    company, actor, manager, link, chat, manager_api, child_api = environment
    reservation, _ = reserve(environment)
    update = event(reservation)
    receiver = manager
    if change == "foreign_owner":
        update["user"]["id"] = 910
    elif change == "foreign_username":
        update["bot"]["username"] = "unrequested_company_bot"
    elif change == "foreign_manager":
        receiver = TelegramConnection.objects.create(workspace=company, token=CHILD_TOKEN, bot_id=654321)
    elif change == "expired":
        TelegramManagedBotReservation.objects.filter(pk=reservation.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
    elif change == "revoked":
        TelegramConnection.objects.filter(pk=manager.pk).update(is_active=False)
    elif change == "repaired":
        link.save()  # Pairing epoch changes even when the numeric owner stays the same.
    elif change == "renamed_manager":
        manager.bot_username = "changed_manager_bot"
        manager.save()
    elif change == "removed_actor":
        actor.is_active = False
        actor.save(update_fields=["is_active"])
    elif change == "role_removed":
        WorkspaceMembership.objects.filter(workspace=company, user=actor).update(workspace_role="client")
    else:
        manager.chats.filter(pk=chat.pk).update(is_active=False)
    assert managed.process_managed_bot_update(receiver, update) == {"status": "ignored"}
    manager_api.get_managed_bot_token.assert_not_called()
    child_api.set_webhook.assert_not_called()
    assert not TelegramConnection.objects.filter(workspace=company, is_active=True).exists()


@pytest.mark.parametrize("numeric", [True, 0, -1, 2**63, "909", None])
def test_malformed_numeric_owner_event_is_ignored(environment, numeric):
    reservation, _ = reserve(environment)
    assert managed.process_managed_bot_update(environment[2], event(reservation, owner=numeric)) == {
        "status": "ignored"
    }
    environment[5].get_managed_bot_token.assert_not_called()


def test_deauthorization_during_token_retrieval_blocks_child_setup(environment):
    company, actor, manager, _, _, api, child_api = environment
    reservation, _ = reserve(environment)

    def token(_):
        WorkspaceMembership.objects.filter(workspace=manager.workspace, user=actor).update(workspace_role="client")
        return CHILD_TOKEN

    api.get_managed_bot_token.side_effect = token
    assert managed.process_managed_bot_update(manager, event(reservation)) == {"status": "review_required"}
    assert not TelegramConnection.objects.filter(workspace=company).exists()
    child_api.get_me.assert_not_called()
    child_api.set_webhook.assert_not_called()


def test_deauthorization_during_child_identity_read_blocks_webhook_write(environment):
    company, actor, manager, _, _, _, child_api = environment
    reservation, _ = reserve(environment)

    def identity():
        TelegramUserLink.objects.filter(connection=manager, user=actor).update(is_active=False)
        return {"id": 654321, "is_bot": True, "username": reservation.requested_username}

    child_api.get_me.side_effect = identity
    assert managed.process_managed_bot_update(manager, event(reservation)) == {"status": "review_required"}
    assert not TelegramConnection.objects.filter(workspace=company).exists()
    child_api.set_webhook.assert_not_called()


def test_child_username_mismatch_never_configures_webhook(environment):
    company, _, manager, _, _, _, child_api = environment
    reservation, _ = reserve(environment)
    child_api.get_me.side_effect = None
    child_api.get_me.return_value = {"id": 654321, "is_bot": True, "username": "unrequested_company_bot"}
    assert managed.process_managed_bot_update(manager, event(reservation)) == {"status": "review_required"}
    assert not TelegramConnection.objects.filter(workspace=company).exists()
    child_api.set_webhook.assert_not_called()


def test_unknown_webhook_write_outcome_is_held_without_blind_event_retry(environment):
    company, _, manager, _, _, api, child_api = environment
    reservation, _ = reserve(environment)
    child_api.set_webhook.side_effect = RuntimeError(CHILD_TOKEN)
    assert managed.process_managed_bot_update(manager, event(reservation)) == {"status": "review_required"}
    assert managed.process_managed_bot_update(manager, event(reservation)) == {"status": "ignored"}
    child_api.set_webhook.assert_called_once()
    api.get_managed_bot_token.assert_called_once()
    reservation.refresh_from_db()
    assert CHILD_TOKEN not in reservation.error and MANAGER_TOKEN not in reservation.error
    assert not TelegramConnection.objects.filter(workspace=company, is_active=True).exists()
    with pytest.raises(managed.ManagedBotError, match="Inspect its outcome"):
        reserve(environment)


def test_manager_permission_revocation_after_webhook_write_blocks_activation(environment):
    company, actor, manager, _, _, _, child_api = environment
    reservation, _ = reserve(environment)

    def webhook(*_):
        WorkspaceMembership.objects.filter(workspace=manager.workspace, user=actor).update(workspace_role="client")
        return True

    child_api.set_webhook.side_effect = webhook
    assert managed.process_managed_bot_update(manager, event(reservation)) == {"status": "review_required"}
    assert not TelegramConnection.objects.filter(workspace=company, is_active=True).exists()


def test_unresolved_claim_cannot_be_reissued_after_expiry(environment):
    reservation, _ = reserve(environment)
    TelegramManagedBotReservation.objects.filter(pk=reservation.pk).update(
        status="connecting", used_at=timezone.now(), expires_at=timezone.now() - timedelta(seconds=1)
    )
    with pytest.raises(managed.ManagedBotError, match="Inspect its outcome"):
        reserve(environment)
    assert TelegramManagedBotReservation.objects.count() == 1


def test_authenticated_ingress_worker_and_connection_flow_consumes_once_without_echoing_token(environment):
    company, _, manager, _, _, manager_api, child_api = environment
    reservation, _ = reserve(environment)
    body = {"update_id": 700, "managed_bot": {**event(reservation), "token": CHILD_TOKEN}}
    request = RequestFactory().post(
        "/webhooks/telegram/",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=manager.webhook_secret,
    )
    assert ingress(request, manager.pk).status_code == 200
    row = TelegramUpdate.objects.get(connection=manager, update_id=700)
    assert "token" not in row.payload["managed_bot"] and CHILD_TOKEN not in json.dumps(row.payload)
    assert processing.process_one(row.pk) == "processed"
    assert TelegramConnection.objects.get(workspace=company).is_active
    row.refresh_from_db()
    assert row.status == "processed"
    assert processing.process_one(row.pk) == "skipped"
    assert not TelegramDelivery.objects.exists()
    manager_api.get_managed_bot_token.assert_called_once_with(654321)
    child_api.set_webhook.assert_called_once()


def test_unauthenticated_ingress_never_reaches_managed_setup(environment):
    reservation, _ = reserve(environment)
    request = RequestFactory().post(
        "/webhooks/telegram/",
        data=json.dumps({"update_id": 701, "managed_bot": event(reservation)}),
        content_type="application/json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="foreign-manager-secret",
    )
    assert ingress(request, environment[2].pk).status_code == 403
    assert not TelegramUpdate.objects.exists()
    environment[5].get_managed_bot_token.assert_not_called()
    environment[6].set_webhook.assert_not_called()


def test_bot_reserved_by_another_workspace_cannot_redirect_its_webhook(environment):
    company, actor, manager, _, _, _, child_api = environment
    reservation, _ = reserve(environment)
    foreign = Workspace.objects.create(organization=company.organization, name="Other company")
    WorkspaceMembership.objects.create(workspace=foreign, user=actor, workspace_role="owner")
    original = TelegramConnection.objects.create(
        workspace=foreign, bot_id=654321, token=CHILD_TOKEN, is_active=True, webhook_secret="original-secret"
    )
    assert managed.process_managed_bot_update(manager, event(reservation)) == {"status": "review_required"}
    assert not TelegramConnection.objects.filter(workspace=company).exists()
    original.refresh_from_db()
    assert original.is_active and original.webhook_secret == "original-secret"
    child_api.set_webhook.assert_not_called()


def test_authority_revoked_during_manager_capability_read_never_fetches_child_credential(environment):
    _, actor, manager, _, _, api, child_api = environment
    reservation, _ = reserve(environment)
    original = api.get_me.return_value

    def identity():
        TelegramUserLink.objects.filter(connection=manager, user=actor).update(is_active=False)
        return original

    api.get_me.side_effect = identity
    assert managed.process_managed_bot_update(manager, event(reservation)) == {"status": "review_required"}
    api.get_managed_bot_token.assert_not_called()
    child_api.set_webhook.assert_not_called()


@pytest.mark.parametrize("receiver", ["different_url", "old_subscription", "malformed_subscription"])
def test_old_or_foreign_manager_receiver_requires_explicit_reconnect_before_creation(environment, receiver):
    api = environment[5]
    if receiver == "different_url":
        api.get_webhook_info.return_value["url"] = "https://foreign.example.com/receiver"
    elif receiver == "old_subscription":
        api.get_webhook_info.return_value["allowed_updates"] = ["message", "callback_query"]
    else:
        api.get_webhook_info.return_value["allowed_updates"] = "managed_bot"
    with pytest.raises(managed.ManagedBotError, match="Reconnect the manager"):
        reserve(environment)
    assert not TelegramManagedBotReservation.objects.exists()
    api.get_managed_bot_token.assert_not_called()
