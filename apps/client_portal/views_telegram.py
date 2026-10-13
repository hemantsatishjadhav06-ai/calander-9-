"""Personal Telegram pairing for a token-scoped client portal session."""

import re
from urllib.parse import urlencode

from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from apps.telegram import provisioning
from apps.telegram.models import TelegramConnection, TelegramUserLink
from apps.telegram.permissions import current_member

from .decorators import portal_auth_required


def _bot_url(username):
    return f"https://t.me/{username}" if re.fullmatch(r"[A-Za-z0-9_]{5,32}", username) else ""


def _context(request):
    # Client accounts can have only a workspace membership. Recheck it using
    # Telegram's current tenant/role rules without deriving any org authority.
    member = current_member(request.portal_workspace, request.user)
    connection = TelegramConnection.objects.filter(workspace=member.workspace).first()
    own_link = (
        TelegramUserLink.objects.filter(connection=connection, user=member.user, is_active=True).first()
        if connection is not None
        else None
    )
    username = connection.bot_username if connection is not None else ""
    bot_url = _bot_url(username)
    return {
        "workspace": member.workspace,
        "connection": connection,
        "own_link": own_link,
        "bot_url": bot_url,
        "can_pair": bool(connection and connection.is_active and connection.webhook_status == "active" and bot_url),
        "pairing_command": "",
        "pairing_url": "",
        "error": "",
    }


def _render(request, context, *, status=200):
    response = render(request, "client_portal/telegram.html", context, status=status)
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "same-origin"
    return response


@portal_auth_required
@require_GET
def telegram_settings(request):
    """Show this client's pairing, without regenerating or redisplaying a code."""
    return _render(request, _context(request))


@portal_auth_required
@require_POST
@ratelimit(key="user", rate="10/m", method="POST", block=True)
def telegram_pair(request):
    """Issue a personal/private code only for the workspace in the login token."""
    context = _context(request)
    if not context["can_pair"]:
        context["error"] = "Your team's Telegram bot is not ready yet. Ask your account manager to connect it."
        return _render(request, context, status=400)
    try:
        ticket, nonce = provisioning.issue_pairing(
            context["connection"], request.user, purpose="user", audience="private"
        )
    except provisioning.ProvisioningError as exc:
        context["error"] = str(exc)
        return _render(request, context, status=400)
    bot_url = _bot_url(ticket.connection.bot_username)
    context.update(
        connection=ticket.connection,
        bot_url=bot_url,
        pairing_command=f"/start {nonce}",
        pairing_url=f"{bot_url}?{urlencode({'start': nonce})}" if bot_url else "",
        expires_at=ticket.expires_at,
    )
    return _render(request, context)


@portal_auth_required
@require_POST
def telegram_unpair(request):
    """Revoke only the current client's identity in their token-bound workspace."""
    context = _context(request)
    if context["connection"] is not None:
        provisioning.unpair(context["connection"], request.user)
    return redirect("client_portal:telegram")
