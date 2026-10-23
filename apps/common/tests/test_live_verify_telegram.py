"""live_verify says whether this deployment can receive Telegram messages, without calling Telegram."""

from io import StringIO

import pytest

from apps.common.management.commands.live_verify import Command
from apps.telegram import provisioning
from apps.telegram.models import TelegramConnection
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


def _run():
    command = Command()
    command.stdout = StringIO()
    command.results = []
    command.check_telegram()
    return {check: (result, detail) for result, check, detail in command.results}


def test_webhook_is_blocked_until_the_public_origin_is_ready(settings):
    settings.TELEGRAM_WEBHOOK_READY = False
    results = _run()
    assert results["telegram.webhook"][0] == "BLOCKED" and "TELEGRAM_WEBHOOK_READY" in results["telegram.webhook"][1]
    assert results["telegram.connections"] == ("INFO", "no active bot connection")


def test_webhook_and_listening_bots_pass(settings, organization, monkeypatch):
    settings.TELEGRAM_WEBHOOK_READY = True
    settings.TELEGRAM_WEBHOOK_BASE_URL = "https://smbean.example.com"
    monkeypatch.setattr(provisioning, "resolve_public_ip", lambda url: "1.1.1.1")
    workspace = Workspace.objects.create(organization=organization, name="Neopolis")
    TelegramConnection.objects.create(
        workspace=workspace,
        token="123456:" + "f" * 32,
        webhook_secret="s",
        bot_id=123456,
        bot_username="neopolis_bot",
        is_active=True,
        webhook_status="active",
    )
    results = _run()
    assert results["telegram.webhook"] == ("PASS", "public webhook origin ready: https://smbean.example.com")
    assert results["telegram.connections"] == ("PASS", "Neopolis: @neopolis_bot active")
    assert "123456:" not in results["telegram.connections"][1]
    assert not Command._critical("telegram.webhook")
