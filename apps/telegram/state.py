"""How far Telegram is from listening, in one place.

The guided Set up page, the readiness line, Home's status line and the
agency's Set up row all read the same two facts from here: whether this
deployment is set to receive updates at a public https address, and what
state a workspace's bot is in. ``apps.studio.readiness.telegram_state`` adds
the person's own pairing on top and is what the pages render.

Neither fact touches the network: whether the public address really resolves
is checked when the webhook is registered (``provisioning._webhook_url``),
and a failed registration shows on the bot's own row.
"""

from __future__ import annotations

from django.conf import settings

from apps.common.checks import public_https_origin


def deployment_ready() -> bool:
    """The switch is on and the public https origin is well formed, so the webhook can be registered."""
    return bool(getattr(settings, "TELEGRAM_WEBHOOK_READY", False)) and public_https_origin(
        getattr(settings, "TELEGRAM_WEBHOOK_BASE_URL", "") or ""
    )


def bot_state(connection) -> str:
    """``missing`` (no bot or no token), ``saved`` (a token, no webhook), ``connecting`` or ``listening``."""
    if connection is None:
        return "missing"
    if connection.is_active and connection.webhook_status == "active":
        return "listening"
    if connection.webhook_status == "setup_in_progress":
        return "connecting"
    return "saved" if connection.token else "missing"
