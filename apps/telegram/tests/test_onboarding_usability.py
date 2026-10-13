from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.members.models import WorkspaceMembership
from apps.telegram import provisioning
from apps.telegram.forms import PairingForm
from apps.telegram.models import TelegramConnection, TelegramPairing
from apps.telegram.tests.test_provisioning import TOKEN, client_member
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


@pytest.fixture
def hub(organization, org_owner):
    workspace = Workspace.objects.create(
        organization=organization, name="Client setup", require_dashboard_approval=True
    )
    WorkspaceMembership.objects.create(workspace=workspace, user=org_owner, workspace_role="owner")
    connection = TelegramConnection.objects.create(
        workspace=workspace,
        token=TOKEN,
        webhook_secret="local-fixture-secret",
        bot_id=123456,
        bot_username="fake_test_bot",
        is_active=True,
        webhook_status="active",
        created_by=org_owner,
    )
    return workspace, org_owner, connection


def test_personal_pairing_has_fresh_one_use_telegram_link(client, hub):
    workspace, user, connection = hub
    client.force_login(user)
    response = client.post(reverse("telegram:pair", args=[workspace.pk]), {"purpose": "user", "audience": "private"})
    assert response.status_code == 200
    nonce = response.context["pairing_command"].split()[1]
    url = urlsplit(response.context["pairing_url"])
    assert url.scheme == "https" and url.netloc == "t.me" and url.path == "/fake_test_bot"
    assert parse_qs(url.query) == {"start": [nonce]}
    assert "Open Telegram and link my account" in response.content.decode()
    assert TOKEN not in response.content.decode() and connection.webhook_secret not in response.content.decode()
    next_response = client.get(reverse("telegram:settings", args=[workspace.pk]))
    assert nonce not in next_response.content.decode()
    ticket = TelegramPairing.objects.get(connection=connection)
    assert ticket.token_digest == provisioning.digest(nonce)


def test_client_gets_simple_personal_link_without_internal_controls(client, hub):
    workspace, _, _ = hub
    user = client_member(workspace)
    client.force_login(user)
    response = client.get(reverse("telegram:settings", args=[workspace.pk]))
    html = response.content.decode()
    assert "Create my personal Telegram link" in html
    assert 'name="purpose" value="user"' in html
    assert 'name="audience" value="private"' in html
    assert "Which group are you linking?" not in html
    assert "Validate and connect bot" not in html
    assert "/week prepare" not in html
    assert "Client sign-off" not in html or "agency" in html


def test_group_setup_excludes_private_audience_and_requires_personal_pairing(client, hub):
    workspace, user, _ = hub
    client.force_login(user)
    response = client.get(reverse("telegram:settings", args=[workspace.pk]))
    field = response.context["group_pair_form"].fields["audience"]
    assert {value for value, _ in field.choices} == {"client", "team"}
    assert "Link your own Telegram account before creating a group code." in response.content.decode()
    assert 'name="purpose" value="chat"' in response.content.decode()


def test_group_code_is_shown_in_group_section_without_private_start_link(client, hub):
    workspace, user, connection = hub
    _, nonce = provisioning.issue_pairing(connection, user)
    provisioning.consume_user_pairing(connection, nonce, 909)
    client.force_login(user)
    response = client.post(
        reverse("telegram:pair", args=[workspace.pk]),
        {"purpose": "chat", "audience": "team", "group_membership_confirmed": "on"},
    )
    assert response.status_code == 200
    assert response.context["pairing_purpose"] == "chat"
    assert "pairing_url" not in response.context
    assert "internal team group" in response.content.decode()
    assert "Open Telegram and link my account" not in response.content.decode()


@pytest.mark.parametrize("audience", ["team", "client"])
def test_invalid_personal_audience_has_visible_error_without_ticket(client, hub, audience):
    workspace, user, connection = hub
    client.force_login(user)
    response = client.post(reverse("telegram:pair", args=[workspace.pk]), {"purpose": "user", "audience": audience})
    assert response.status_code == 400
    assert "Pair your own identity in the bot&#x27;s private chat." in response.content.decode()
    assert not TelegramPairing.objects.filter(connection=connection).exists()


def test_group_permission_choices_and_consent_errors_are_visible(client, hub):
    workspace, user, connection = hub
    client.force_login(user)
    response = client.post(reverse("telegram:pair", args=[workspace.pk]), {"purpose": "chat", "audience": "private"})
    assert response.status_code == 400
    assert 'role="alert"' in response.content.decode()
    assert "Confirm the group membership boundary" in response.content.decode()
    assert not TelegramPairing.objects.filter(connection=connection).exists()


def test_inactive_connection_keeps_pair_button_disabled_with_clear_next_action(client, hub):
    workspace, user, connection = hub
    connection.is_active = False
    connection.save(update_fields=["is_active"])
    client.force_login(user)
    response = client.get(reverse("telegram:settings", args=[workspace.pk]))
    assert "Bot setup needs attention" in response.content.decode()
    assert "Finish the deployed HTTPS connection" in response.content.decode()
    assert 'type="submit" disabled>Create my personal Telegram link' in response.content.decode()


def test_malformed_bot_username_cannot_be_used_as_external_pairing_url(client, hub):
    workspace, user, connection = hub
    connection.bot_username = "evil.example/path?start=payload"
    connection.save(update_fields=["bot_username"])
    client.force_login(user)
    response = client.post(reverse("telegram:pair", args=[workspace.pk]), {"purpose": "user", "audience": "private"})
    assert response.status_code == 200
    assert response.context["pairing_url"] == ""
    assert "Open Telegram and link my account" not in response.content.decode()


def test_reconnect_form_preserves_existing_approval_preference(client, hub):
    workspace, user, connection = hub
    connection.approvals_enabled = True
    connection.save(update_fields=["approvals_enabled"])
    client.force_login(user)
    response = client.get(reverse("telegram:settings", args=[workspace.pk]))
    assert response.context["connect_form"]["approvals_enabled"].value() is True


def test_pairing_form_refuses_group_identity_confusion():
    form = PairingForm({"purpose": "chat", "audience": "private", "group_membership_confirmed": "on"}, group=True)
    assert not form.is_valid()
    assert "audience" in form.errors


def test_managed_creation_requires_post_and_current_internal_settings_permission(client, hub):
    workspace, _, _ = hub
    user = client_member(workspace)
    client.force_login(user)
    url = reverse("telegram:managed_create", args=[workspace.pk])
    assert client.get(url).status_code == 405
    with patch("apps.telegram.managed.begin_managed_bot_creation") as begin:
        assert client.post(url, {"manager_connection": "anything"}).status_code == 403
    begin.assert_not_called()


def test_managed_creation_link_is_only_shown_in_fresh_response(client, hub):
    workspace, user, connection = hub
    connection.is_active = False
    connection.save(update_fields=["is_active"])
    client.force_login(user)
    reservation = SimpleNamespace(
        status="pending",
        requested_name=workspace.name,
        expires_at=timezone.now() + timedelta(minutes=10),
        error="",
        get_status_display=lambda: "Awaiting Telegram confirmation",
    )
    creation_url = "https://t.me/newbot/fake_test_bot/random_reserved_bot?name=Client"
    with (
        patch("apps.telegram.managed.available_managers", return_value=[connection]),
        patch("apps.telegram.managed.begin_managed_bot_creation", return_value=(reservation, creation_url)) as begin,
    ):
        response = client.post(
            reverse("telegram:managed_create", args=[workspace.pk]), {"manager_connection": str(connection.pk)}
        )
        assert response.status_code == 200
        begin.assert_called_once_with(workspace, user, str(connection.pk))
        assert "Open Telegram and confirm client bot creation" in response.content.decode()
        assert response.context["managed_creation_url"] == creation_url
        assert TOKEN not in response.content.decode()
        assert "t.me/newbot/" not in client.get(reverse("telegram:settings", args=[workspace.pk])).content.decode()


def test_incapable_manager_error_preserves_botfather_fallback_without_secrets(client, hub):
    from apps.telegram.managed import ManagedBotError

    workspace, user, connection = hub
    connection.is_active = False
    connection.save(update_fields=["is_active"])
    client.force_login(user)
    with (
        patch("apps.telegram.managed.available_managers", return_value=[connection]),
        patch(
            "apps.telegram.managed.begin_managed_bot_creation",
            side_effect=ManagedBotError(
                "This bot cannot create client bots yet. Connect a bot created through @BotFather."
            ),
        ),
    ):
        response = client.post(
            reverse("telegram:managed_create", args=[workspace.pk]), {"manager_connection": str(connection.pk)}
        )
    assert response.status_code == 400
    assert "This bot cannot create client bots yet." in response.content.decode()
    assert "Validate and connect bot" in response.content.decode()
    assert TOKEN not in response.content.decode()


def test_unavailable_manager_cannot_be_selected_by_forging_post(client, hub):
    workspace, user, _ = hub
    client.force_login(user)
    with patch("apps.telegram.managed.begin_managed_bot_creation") as begin:
        response = client.post(
            reverse("telegram:managed_create", args=[workspace.pk]), {"manager_connection": "foreign"}
        )
    assert response.status_code == 400
    begin.assert_not_called()


def test_settings_do_not_probe_telegram_or_models_on_get(client, hub):
    workspace, user, connection = hub
    connection.is_active = False
    connection.save(update_fields=["is_active"])
    client.force_login(user)
    with patch("apps.telegram.managed.BotAPI") as api:
        response = client.get(reverse("telegram:settings", args=[workspace.pk]))
    assert response.status_code == 200
    api.assert_not_called()


def test_managed_creation_flag_hides_new_requests_but_retains_direct_token_setup(client, hub, settings):
    workspace, user, _ = hub
    settings.TELEGRAM_MANAGED_BOTS_ENABLED = False
    client.force_login(user)
    response = client.get(reverse("telegram:settings", args=[workspace.pk]))
    assert "Create this client&#x27;s bot with Telegram confirmation" not in response.content.decode()
    assert "Validate and connect bot" in response.content.decode()
