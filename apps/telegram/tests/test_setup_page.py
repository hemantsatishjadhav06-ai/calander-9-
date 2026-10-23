"""The guided Set up Telegram page and its helpers: command menu, retry webhook, approvals switch, test message."""

import pytest
from django.urls import reverse

from apps.telegram import provisioning
from apps.telegram.models import TelegramConnection, TelegramDelivery
from apps.telegram.permissions import TelegramPermissionDenied
from apps.telegram.tests.test_onboarding_usability import hub  # noqa: F401
from apps.telegram.tests.test_provisioning import TOKEN, client_member, no_live_bot, ready  # noqa: F401
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_background_sends(monkeypatch):
    from apps.telegram import tasks

    monkeypatch.setattr(tasks, "send_delivery", lambda *a, **k: None)


def _pair(connection, user, numeric=909):
    _, nonce = provisioning.issue_pairing(connection, user)
    return provisioning.consume_user_pairing(connection, nonce, numeric)


def test_connect_publishes_the_command_menu_and_a_menu_failure_never_blocks(hub, ready, no_live_bot):  # noqa: F811
    workspace, user, conn = hub
    conn.delete()
    no_live_bot.set_my_commands.side_effect = RuntimeError("menu unavailable")
    saved = provisioning.connect(workspace, user, TOKEN)
    assert saved.is_active and saved.webhook_status == "active"
    assert no_live_bot.set_my_commands.call_args.args[0] == provisioning.BOT_COMMANDS


def test_set_commands_command_publishes_the_menu_for_existing_bots_only(hub, no_live_bot, capsys):  # noqa: F811
    from io import StringIO

    from django.core.management import call_command

    workspace, user, conn = hub
    no_live_bot.set_my_commands.return_value = True
    out = StringIO()
    call_command("telegram_set_commands", stdout=out)
    assert no_live_bot.set_my_commands.call_args.args[0] == provisioning.BOT_COMMANDS
    assert "@fake_test_bot menu published" in out.getvalue() and "1 bot(s) updated" in out.getvalue()
    assert TOKEN not in out.getvalue()
    TelegramConnection.objects.filter(pk=conn.pk).update(is_active=False)
    out = StringIO()
    call_command("telegram_set_commands", stdout=out)
    assert "No active Telegram bot" in out.getvalue() and no_live_bot.set_my_commands.call_count == 1


def test_retry_webhook_activates_a_saved_bot_without_moving_its_epoch(hub, ready, no_live_bot):  # noqa: F811
    workspace, user, conn = hub
    TelegramConnection.objects.filter(pk=conn.pk).update(is_active=False, webhook_status="pending_deployment")
    before = TelegramConnection.objects.get(pk=conn.pk).updated_at
    refreshed = provisioning.refresh_webhook(conn, user)
    assert refreshed.is_active and refreshed.webhook_status == "active" and refreshed.updated_at == before
    url, secret = no_live_bot.set_webhook.call_args.args
    assert url.startswith("https://smbean.example.com/") and str(conn.pk) in url and secret == conn.webhook_secret
    no_live_bot.set_my_commands.assert_called()


def test_retry_webhook_refuses_without_public_origin_or_owner_rights(hub, settings, no_live_bot):  # noqa: F811
    workspace, user, conn = hub
    settings.TELEGRAM_WEBHOOK_READY = False
    with pytest.raises(provisioning.ProvisioningError, match="public address"):
        provisioning.refresh_webhook(conn, user)
    no_live_bot.set_webhook.assert_not_called()
    settings.TELEGRAM_WEBHOOK_READY = True
    settings.TELEGRAM_WEBHOOK_BASE_URL = "https://smbean.example.com"
    with pytest.raises(TelegramPermissionDenied):
        provisioning.refresh_webhook(conn, client_member(workspace))
    no_live_bot.get_me.return_value = {"id": 999, "is_bot": True, "username": "other_bot"}
    with pytest.raises(provisioning.ProvisioningError, match="different bot"):
        provisioning.refresh_webhook(conn, user)
    conn.refresh_from_db()
    assert conn.is_active


def test_approvals_switch_needs_the_gate_and_keeps_the_connection_epoch(hub):  # noqa: F811
    workspace, user, conn = hub
    before = conn.updated_at
    assert provisioning.set_approvals(conn, user, True).approvals_enabled is True
    assert provisioning.set_approvals(conn, user, False).approvals_enabled is False
    assert TelegramConnection.objects.get(pk=conn.pk).updated_at == before
    Workspace.objects.filter(pk=workspace.pk).update(require_dashboard_approval=False)
    with pytest.raises(provisioning.ProvisioningError, match="approval gate"):
        provisioning.set_approvals(conn, user, True)
    with pytest.raises(TelegramPermissionDenied):
        provisioning.set_approvals(conn, client_member(workspace), True)


def test_test_message_goes_to_the_persons_own_private_chat_only(hub):  # noqa: F811
    workspace, user, conn = hub
    with pytest.raises(provisioning.ProvisioningError, match="Pair"):
        provisioning.send_test_message(conn, user)
    _pair(conn, user)
    rows = provisioning.send_test_message(conn, user)
    assert len(rows) == 1 and rows[0].chat.private_user_id == user.pk and rows[0].chat.chat_id == 909
    assert "This chat works" in rows[0].payload["text"] and TOKEN not in rows[0].payload["text"]


def test_owner_sees_the_five_rows_with_state_in_words_and_progress(client, hub):  # noqa: F811
    workspace, user, connection = hub
    client.force_login(user)
    html = client.get(reverse("telegram:settings", args=[workspace.pk])).content.decode()
    for heading in ("Deployment ready", "Bot connected", "You are paired", "Approvals from Telegram", "Advanced"):
        assert heading in html
    assert "1 of 4 done" in html  # the bot listens; deployment, pairing and approvals are not done yet
    assert "Not ready. Set <code>TELEGRAM_WEBHOOK_BASE_URL</code>" in html
    assert "Listening as <strong>@fake_test_bot</strong>" in html
    assert "What you can say" in html and "/mute" in html
    assert "does not approve, schedule or send" not in html


def test_the_exact_names_to_set_are_for_owners_only_as_on_set_up(client, hub, settings):  # noqa: F811
    """A settings manager who is not an owner reads "Ask your owner" here too, never the two names."""
    from django.utils import timezone

    from apps.accounts.models import User
    from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership

    workspace, owner, connection = hub
    settings.TELEGRAM_WEBHOOK_READY = False
    manager = User.objects.create_user(
        email="settings-manager@example.test", password="not-used", name="Settings", tos_accepted_at=timezone.now()
    )
    role = CustomRole.objects.create(
        organization=workspace.organization,
        name="Settings manager",
        permissions={"manage_workspace_settings": True, "create_posts": True, "approve_posts": True},
    )
    OrgMembership.objects.create(organization=workspace.organization, user=manager, org_role="member")
    WorkspaceMembership.objects.create(workspace=workspace, user=manager, workspace_role="manager", custom_role=role)
    url = reverse("telegram:settings", args=[workspace.pk])

    client.force_login(manager)
    html = client.get(url).content.decode()
    assert "Not ready yet. Ask your owner." in html
    assert "TELEGRAM_WEBHOOK_BASE_URL" not in html and "TELEGRAM_WEBHOOK_READY" not in html
    assert "Retry webhook" in html  # they still manage the bot itself

    client.force_login(owner)
    html = client.get(url).content.decode()
    assert "Not ready. Set <code>TELEGRAM_WEBHOOK_BASE_URL</code>" in html


def test_approvals_toggle_and_test_message_are_one_post_each(client, hub):  # noqa: F811
    workspace, user, connection = hub
    client.force_login(user)
    toggle = reverse("telegram:toggle_approvals", args=[workspace.pk])
    assert client.post(toggle, {"enabled": "on"}).status_code == 302
    connection.refresh_from_db()
    assert connection.approvals_enabled is True
    html = client.get(reverse("telegram:settings", args=[workspace.pk])).content.decode()
    assert "On. Approve, reject or ask for changes from the card" in html and "2 of 4 done" in html
    assert client.post(toggle, {}).status_code == 302
    connection.refresh_from_db()
    assert connection.approvals_enabled is False
    _pair(connection, user)
    assert client.post(reverse("telegram:test_message", args=[workspace.pk])).status_code == 302
    assert TelegramDelivery.objects.filter(chat__private_user=user).count() == 1
    html = client.get(reverse("telegram:settings", args=[workspace.pk])).content.decode()
    assert "Send me a test message" in html and "Paired" in html


def test_clients_cannot_change_approvals_or_retry_the_webhook(client, hub):  # noqa: F811
    workspace, _, connection = hub
    client.force_login(client_member(workspace))
    assert client.post(reverse("telegram:toggle_approvals", args=[workspace.pk]), {"enabled": "on"}).status_code == 403
    assert client.post(reverse("telegram:refresh_webhook", args=[workspace.pk])).status_code == 403
    connection.refresh_from_db()
    assert connection.approvals_enabled is False


def test_managed_bot_creation_is_hidden_unless_a_manager_bot_exists(client, hub):  # noqa: F811
    workspace, user, connection = hub
    connection.is_active = False
    connection.save(update_fields=["is_active"])
    client.force_login(user)
    html = client.get(reverse("telegram:settings", args=[workspace.pk])).content.decode()
    assert "Create this client&#x27;s bot with Telegram confirmation" not in html
    assert "Validate and connect bot" in html


def test_paired_authors_get_telegram_updates_on_by_default(hub):  # noqa: F811
    from apps.studio import customer_workflow

    workspace, user, connection = hub
    assert customer_workflow.context(workspace, user)["workflow_form"]["telegram_updates"].value() is False
    _pair(connection, user)
    assert customer_workflow.context(workspace, user)["workflow_form"]["telegram_updates"].value() is True
