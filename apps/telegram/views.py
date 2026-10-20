import re
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST

from apps.studio import dashboard
from apps.workspaces.models import Workspace

from . import provisioning, state
from .forms import ChannelForm, ConnectForm, ManagedBotCreationForm, PairingForm
from .models import (
    TelegramChannel,
    TelegramChannelDelivery,
    TelegramConnection,
    TelegramDelivery,
    TelegramManagedBotReservation,
    TelegramUpdate,
    TelegramUserLink,
)
from .permissions import can_manage, can_pair_group, current_member, internal_member


def _bot_url(username):
    if isinstance(username, str) and re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        return f"https://t.me/{username}"
    return ""


def _context(request, workspace_id):
    workspace = get_object_or_404(Workspace, pk=workspace_id)
    member = current_member(workspace, request.user)
    connection = TelegramConnection.objects.filter(workspace=member.workspace).first()
    manage = can_manage(member)
    own_link = (
        TelegramUserLink.objects.filter(connection=connection, user=request.user, is_active=True).first()
        if connection
        else None
    )
    chats = list(connection.chats.all()) if connection and manage else []
    managed_enabled = manage and getattr(settings, "TELEGRAM_MANAGED_BOTS_ENABLED", True)
    managers = []
    if managed_enabled and not (connection and connection.is_active):
        from .managed import available_managers

        managers = available_managers(member.workspace, request.user)
    latest_request = (
        TelegramManagedBotReservation.objects.filter(workspace=member.workspace, requested_by=request.user)
        .order_by("-created_at")
        .first()
        if managed_enabled
        else None
    )
    channels = (
        list(
            TelegramChannel.objects.filter(
                connection=connection, organization_id=member.workspace.organization_id
            ).order_by("created_at")
        )
        if connection and manage
        else []
    )
    from .channel_outbox import permitted_channel

    for channel in channels:
        channel.proof_current = permitted_channel(channel)
    channel_pairing_ready = False
    if connection and manage and own_link:
        try:
            provisioning.channel_actor(connection, request.user)
        except (PermissionDenied, provisioning.ProvisioningError):
            pass
        else:
            channel_pairing_ready = True
    # The same two facts the agency's Set up row and Home's status line read (apps.telegram.state).
    deployment_ready = state.deployment_ready()
    bot_state = state.bot_state(connection)
    paired = own_link is not None
    approvals_on = bool(connection and connection.approvals_enabled)
    internal = internal_member(member)
    steps_done = sum([deployment_ready, bot_state == "listening", paired, approvals_on])
    return {
        "workspace": member.workspace,
        "connection": connection,
        "own_link": own_link,
        "bot_url": _bot_url(connection.bot_username) if connection else "",
        "can_manage": manage,
        "can_pair_group": can_pair_group(member),
        "internal": internal,
        "telegram_client_view": not internal,
        "tabs": dashboard.tabs(member.workspace, "telegram"),
        "deployment_ready": deployment_ready,
        "webhook_base": (getattr(settings, "TELEGRAM_WEBHOOK_BASE_URL", "") or "").strip(),
        "webhook_flag": bool(getattr(settings, "TELEGRAM_WEBHOOK_READY", False)),
        "bot_state": bot_state,
        "paired": paired,
        "approvals_on": approvals_on,
        "approval_gate_on": bool(member.workspace.require_dashboard_approval),
        "steps_done": steps_done,
        "steps_total": 4,
        "commands": provisioning.BOT_COMMANDS,
        "connect_form": ConnectForm(
            initial={"approvals_enabled": connection.approvals_enabled if connection else False}
        ),
        "pair_form": PairingForm(),
        "group_pair_form": PairingForm(group=True, auto_id="id_group_%s"),
        "channel_form": ChannelForm(),
        "channels": channels,
        "channel_count": sum(channel.proof_current for channel in channels),
        "channel_pairing_ready": channel_pairing_ready,
        "channel_deliveries": TelegramChannelDelivery.objects.filter(
            channel__connection=connection,
            channel__organization_id=member.workspace.organization_id,
            status__in=["failed", "unknown"],
        ).order_by("-updated_at")[:10]
        if connection and manage
        else [],
        "managed_enabled": managed_enabled,
        "managed_form": ManagedBotCreationForm(managers=managers),
        "managed_managers": managers,
        "managed_latest_request": latest_request,
        "managed_request_expired": bool(
            latest_request and latest_request.status == "pending" and latest_request.expires_at <= timezone.now()
        ),
        "client_group_count": sum(chat.is_active and chat.audience == "client" for chat in chats),
        "team_group_count": sum(chat.is_active and chat.audience == "team" for chat in chats),
        "chats": chats,
        "deliveries": TelegramDelivery.objects.filter(connection=connection, status__in=["failed", "unknown"]).order_by(
            "-updated_at"
        )[:10]
        if connection and can_manage(member)
        else [],
        "updates": TelegramUpdate.objects.filter(connection=connection, status="failed").order_by("-created_at")[:10]
        if connection and can_manage(member)
        else [],
    }


def _render(request, context, status=200):
    response = render(request, "telegram/settings.html", context, status=status)
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "same-origin"
    return response


@login_required
@require_GET
def settings_page(request, workspace_id):
    return _render(request, _context(request, workspace_id))


@login_required
@require_POST
@sensitive_post_parameters("token")
def connect(request, workspace_id):
    context = _context(request, workspace_id)
    if not context["can_manage"]:
        raise PermissionDenied("Only a current workspace settings owner can connect a bot.")
    form = ConnectForm(request.POST)
    if form.is_valid():
        try:
            provisioning.connect(
                context["workspace"],
                request.user,
                form.cleaned_data["token"],
                approvals_enabled=form.cleaned_data["approvals_enabled"],
            )
        except provisioning.ProvisioningError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Bot connected. Next, pair your own account.")
            return redirect("telegram:settings", workspace_id=workspace_id)
    context["connect_form"] = form
    return _render(request, context, status=400)


@login_required
@require_POST
def refresh_webhook(request, workspace_id):
    context = _context(request, workspace_id)
    if not context["can_manage"] or context["connection"] is None:
        raise PermissionDenied("Only a current workspace settings owner can retry the webhook.")
    try:
        provisioning.refresh_webhook(context["connection"], request.user)
    except provisioning.ProvisioningError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "The bot is listening again.")
    return redirect("telegram:settings", workspace_id=workspace_id)


@login_required
@require_POST
def toggle_approvals(request, workspace_id):
    context = _context(request, workspace_id)
    if not context["can_manage"] or context["connection"] is None:
        raise PermissionDenied("Only a current workspace settings owner can change Telegram approvals.")
    enabled = request.POST.get("enabled") == "on"
    try:
        provisioning.set_approvals(context["connection"], request.user, enabled)
    except provisioning.ProvisioningError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            "Approving from Telegram is on." if enabled else "Approving from Telegram is off; cards still arrive.",
        )
    return redirect("telegram:settings", workspace_id=workspace_id)


@login_required
@require_POST
def test_message(request, workspace_id):
    context = _context(request, workspace_id)
    if context["connection"] is None:
        raise PermissionDenied("Connect a bot first.")
    try:
        provisioning.send_test_message(context["connection"], request.user)
    except (provisioning.ProvisioningError, PermissionDenied) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Sent. Check your Telegram chat.")
    return redirect("telegram:settings", workspace_id=workspace_id)


@login_required
@require_POST
def pair(request, workspace_id):
    context = _context(request, workspace_id)
    group = request.POST.get("purpose") == "chat"
    form = PairingForm(request.POST, group=group, auto_id="id_group_%s" if group else "id_%s")
    if form.is_valid() and context["connection"]:
        try:
            ticket, nonce = provisioning.issue_pairing(
                context["connection"],
                request.user,
                purpose=form.cleaned_data["purpose"],
                audience=form.cleaned_data["audience"],
            )
        except provisioning.ProvisioningError as exc:
            form.add_error(None, str(exc))
        else:
            context.update(
                pairing_command=f"/start {nonce}" if ticket.purpose == "user" else f"/pair {nonce}",
                expires_at=ticket.expires_at,
                pairing_seconds=max(0, int((ticket.expires_at - timezone.now()).total_seconds())),
                pairing_purpose=ticket.purpose,
                pairing_audience=ticket.audience,
            )
            if ticket.purpose == "user":
                bot_url = _bot_url(ticket.connection.bot_username)
                context["pairing_url"] = f"{bot_url}?{urlencode({'start': nonce})}" if bot_url else ""
            return _render(request, context)
    elif not context["connection"]:
        form.add_error(None, "Ask your workspace owner to connect a bot first.")
    context["group_pair_form" if group else "pair_form"] = form
    return _render(request, context, status=400)


@login_required
@require_POST
def managed_create(request, workspace_id):
    """Issue a fresh Telegram consent link; the backend verifies manager authority."""
    from .managed import ManagedBotError, begin_managed_bot_creation

    context = _context(request, workspace_id)
    if not context["can_manage"]:
        raise PermissionDenied("Only a current workspace settings manager can create its bot.")
    form = ManagedBotCreationForm(request.POST, managers=context["managed_managers"])
    if form.is_valid():
        try:
            reservation, creation_url = begin_managed_bot_creation(
                context["workspace"], request.user, form.cleaned_data["manager_connection"]
            )
        except ManagedBotError as exc:
            form.add_error(None, str(exc))
        else:
            context.update(
                managed_creation_url=creation_url, managed_latest_request=reservation, managed_request_expired=False
            )
            return _render(request, context)
    context["managed_form"] = form
    return _render(request, context, status=400)


@login_required
@require_POST
def disconnect(request, workspace_id):
    context = _context(request, workspace_id)
    if context["connection"]:
        provisioning.disconnect(context["connection"], request.user)
    messages.success(request, "Telegram is off for this workspace. The saved token and every pairing were cleared.")
    return redirect("telegram:settings", workspace_id=workspace_id)


@login_required
@require_POST
def unpair(request, workspace_id):
    context = _context(request, workspace_id)
    if context["connection"]:
        provisioning.unpair(context["connection"], request.user)
    messages.success(request, "Your Telegram account is unpaired.")
    return redirect("telegram:settings", workspace_id=workspace_id)


@login_required
@require_POST
def deactivate_chat(request, workspace_id, chat_id):
    context = _context(request, workspace_id)
    if not context["can_manage"] or context["connection"] is None:
        raise PermissionDenied("Only a current workspace settings manager can disconnect chats.")
    try:
        provisioning.deactivate_chat(context["connection"], request.user, chat_id)
    except provisioning.ProvisioningError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Chat disabled. Pair it again after checking its audience and membership.")
    return redirect("telegram:settings", workspace_id=workspace_id)


@login_required
@require_POST
def connect_channel(request, workspace_id):
    context = _context(request, workspace_id)
    if not context["can_manage"]:
        raise PermissionDenied("Only a current workspace settings manager can connect a channel.")
    form = ChannelForm(request.POST)
    if form.is_valid() and context["connection"]:
        try:
            provisioning.connect_channel(
                context["connection"],
                request.user,
                form.cleaned_data["channel_reference"],
                visibility_confirmed=form.cleaned_data["visibility_confirmed"],
            )
        except provisioning.ProvisioningError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Channel connected for status updates. Questions and approvals stay in chats.")
            return redirect("telegram:settings", workspace_id=workspace_id)
    elif not context["connection"]:
        form.add_error(None, "Connect the workspace bot and pair your own account first.")
    context["channel_form"] = form
    return _render(request, context, status=400)


@login_required
@require_POST
def disconnect_channel(request, workspace_id, channel_id):
    context = _context(request, workspace_id)
    if not context["can_manage"] or not context["connection"]:
        raise PermissionDenied("Only a current workspace settings manager can disconnect a channel.")
    try:
        provisioning.disconnect_channel(context["connection"], request.user, channel_id)
    except provisioning.ProvisioningError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Channel updates are off. Chats and groups are unchanged.")
    return redirect("telegram:settings", workspace_id=workspace_id)
