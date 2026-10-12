from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST

from apps.studio import dashboard
from apps.workspaces.models import Workspace

from . import provisioning
from .forms import ConnectForm, PairingForm
from .models import TelegramConnection, TelegramDelivery, TelegramUpdate, TelegramUserLink
from .permissions import can_manage, can_pair_group, current_member, internal_member


def _context(request, workspace_id):
    workspace = get_object_or_404(Workspace, pk=workspace_id)
    member = current_member(workspace, request.user)
    connection = TelegramConnection.objects.filter(workspace=member.workspace).first()
    return {
        "workspace": member.workspace,
        "connection": connection,
        "own_link": TelegramUserLink.objects.filter(connection=connection, user=request.user, is_active=True).first()
        if connection
        else None,
        "can_manage": can_manage(member),
        "can_pair_group": can_pair_group(member),
        "internal": internal_member(member),
        "telegram_client_view": not internal_member(member),
        "tabs": dashboard.tabs(member.workspace, "telegram"),
        "connect_form": ConnectForm(),
        "pair_form": PairingForm(),
        "chats": connection.chats.all() if connection and can_manage(member) else [],
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
            messages.success(request, "Bot configuration saved. Pair each person and group separately before using it.")
            return redirect("telegram:settings", workspace_id=workspace_id)
    context["connect_form"] = form
    return _render(request, context, status=400)


@login_required
@require_POST
def pair(request, workspace_id):
    context = _context(request, workspace_id)
    form = PairingForm(request.POST)
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
            )
            return _render(request, context)
    elif not context["connection"]:
        form.add_error(None, "Ask your workspace owner to connect a bot first.")
    context["pair_form"] = form
    return _render(request, context, status=400)


@login_required
@require_POST
def disconnect(request, workspace_id):
    context = _context(request, workspace_id)
    if context["connection"]:
        provisioning.disconnect(context["connection"], request.user)
    messages.success(
        request, "Telegram is disabled for this workspace. Its saved token and active pairings were cleared."
    )
    return redirect("telegram:settings", workspace_id=workspace_id)


@login_required
@require_POST
def unpair(request, workspace_id):
    context = _context(request, workspace_id)
    if context["connection"]:
        provisioning.unpair(context["connection"], request.user)
    messages.success(request, "Your Telegram identity and private-chat access are disabled.")
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
