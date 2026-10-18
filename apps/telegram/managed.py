"""Telegram-consented, tenant-bound creation of a dedicated client bot.

Telegram owns the confirmation dialog. SM Bean reserves an unpredictable
username and only accepts its authenticated manager's matching owner event.
There is no server-side arbitrary bot creation or token rotation here.
"""

import re
import secrets
import uuid
from datetime import timedelta
from urllib.parse import quote, urlencode

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from . import provisioning
from .api import BotAPI
from .models import TelegramChat, TelegramConnection, TelegramManagedBotReservation, TelegramUserLink
from .permissions import TelegramPermissionDenied, fresh_member

CONSENT_TTL = timedelta(minutes=10)
USERNAME = re.compile(r"[A-Za-z0-9_]{5,32}")


class ManagedBotError(provisioning.ProvisioningError):
    pass


def _enabled():
    if not getattr(settings, "TELEGRAM_MANAGED_BOTS_ENABLED", True):
        raise ManagedBotError("Client bot creation is disabled. Connect a bot created through @BotFather instead.")


def _paired_manager(manager, actor):
    """Read fresh authority and an explicitly paired private chat; never create one."""
    current = (
        TelegramConnection.objects.select_related("workspace")
        .filter(pk=manager.pk, is_active=True, webhook_status="active")
        .first()
    )
    link = TelegramUserLink.objects.filter(connection=current, user=actor, is_active=True).first()
    if current is None or link is None:
        raise ManagedBotError("Pair your personal Telegram account with an active manager bot first.")
    member = fresh_member(link, "manage_workspace_settings")
    chat = (
        TelegramChat.objects.select_related("conversation")
        .filter(
            connection=current,
            chat_id=link.telegram_user_id,
            chat_type="private",
            audience="private",
            private_user=member.user,
            is_active=True,
        )
        .first()
    )
    if (
        chat is None
        or not chat.conversation.is_private
        or chat.conversation.workspace_id != member.workspace_id
        or chat.conversation.created_by_id != member.user_id
        or chat.conversation.audience != "internal"
    ):
        raise ManagedBotError("Pair your active private manager chat again before creating a client bot.")
    return current, link


def available_managers(workspace, actor):
    """Local choices only: capability is checked live on the explicit POST."""
    member = provisioning._owner(workspace, actor)
    choices = []
    for connection in TelegramConnection.objects.select_related("workspace").filter(
        workspace__organization_id=member.workspace.organization_id,
        is_active=True,
        webhook_status="active",
        user_links__user=member.user,
        user_links__is_active=True,
    ):
        try:
            manager, _ = _paired_manager(connection, member.user)
        except (ManagedBotError, TelegramPermissionDenied):
            continue
        choices.append(manager)
    return choices


def _capable_api(manager):
    try:
        api = BotAPI(manager.token)
        identity = api.get_me()
    except Exception:
        raise ManagedBotError(
            "Telegram could not verify the manager bot. Inspect its connection and try again."
        ) from None
    if (
        not isinstance(identity, dict)
        or identity.get("is_bot") is not True
        or isinstance(identity.get("id"), bool)
        or identity.get("id") != manager.bot_id
        or identity.get("username") != manager.bot_username
        or not isinstance(identity.get("username"), str)
        or not USERNAME.fullmatch(identity["username"])
    ):
        raise ManagedBotError("The manager bot identity changed. Reconnect it before creating a client bot.")
    if identity.get("can_manage_bots") is not True:
        raise ManagedBotError(
            "This bot cannot create client bots yet. Enable bot management in Telegram or connect a bot created through @BotFather."
        )
    return api


def _creation_url(reservation, username):
    return f"https://t.me/newbot/{username}/{reservation.requested_username}?" + urlencode(
        {"name": reservation.requested_name}, quote_via=quote
    )


def _manager_receiver_ready(manager, api):
    try:
        remote = api.get_webhook_info()
    except Exception:
        raise ManagedBotError("Telegram could not inspect the manager webhook. Check its connection first.") from None
    expected = provisioning._webhook_url(manager.pk)
    allowed = remote.get("allowed_updates") if isinstance(remote, dict) else None
    if (
        not expected
        or not isinstance(remote, dict)
        or remote.get("url") != expected
        or (allowed is not None and (not isinstance(allowed, list) or (allowed and "managed_bot" not in allowed)))
    ):
        raise ManagedBotError(
            "Reconnect the manager bot in its workspace so its verified webhook receives managed bot updates."
        )


def begin_managed_bot_creation(workspace, actor, manager_connection_id):
    """Reserve one child username after local authority and live capability checks."""
    _enabled()
    member = provisioning._owner(workspace, actor)
    manager = TelegramConnection.objects.filter(pk=manager_connection_id).first()
    if manager is None or manager.workspace.organization_id != member.workspace.organization_id:
        raise TelegramPermissionDenied("Choose a manager bot from this organization.")
    manager, link = _paired_manager(manager, member.user)
    target = TelegramConnection.objects.filter(workspace=member.workspace).first()
    if target and target.is_active:
        raise ManagedBotError(
            "This company already has an active bot. Disable it explicitly before requesting another."
        )
    if not provisioning._webhook_url(target.pk if target else uuid.uuid4()):
        raise ManagedBotError("Confirm the deployed HTTPS webhook is ready before creating a client bot.")
    api = _capable_api(manager)
    _manager_receiver_ready(manager, api)
    verified_epoch = manager.updated_at
    verified_pairing = link.updated_at
    try:
        with transaction.atomic():
            # Serialize target requests without holding locks during network calls.
            member = provisioning._owner(workspace, actor, locked=True)
            manager, link = _paired_manager(manager, member.user)
            if manager.updated_at != verified_epoch or link.updated_at != verified_pairing:
                raise ManagedBotError("The manager connection changed. Inspect it before requesting a client bot.")
            target = TelegramConnection.objects.filter(workspace=member.workspace).first()
            if target and target.is_active:
                raise ManagedBotError("This company already has an active bot. Disable it explicitly first.")
            now = timezone.now()
            TelegramManagedBotReservation.objects.filter(
                workspace=member.workspace, status="pending", expires_at__lte=now
            ).update(status="cancelled", completed_at=now, error="Telegram confirmation expired.")
            previous = (
                TelegramManagedBotReservation.objects.filter(
                    workspace=member.workspace, status__in=["pending", "connecting", "review_required"]
                )
                .order_by("-created_at")
                .first()
            )
            if previous:
                if (
                    previous.status == "pending"
                    and previous.requested_by_id == member.user_id
                    and previous.manager_id == manager.pk
                    and previous.manager_epoch == manager.updated_at
                    and previous.pairing_epoch == link.updated_at
                    and previous.telegram_owner_id == link.telegram_user_id
                ):
                    return previous, _creation_url(previous, manager.bot_username)
                raise ManagedBotError(
                    "A client bot request already exists. Inspect its outcome before requesting another."
                )
            reservation = TelegramManagedBotReservation.objects.create(
                manager=manager,
                workspace=member.workspace,
                requested_by=member.user,
                user_link=link,
                telegram_owner_id=link.telegram_user_id,
                manager_bot_id=manager.bot_id,
                manager_epoch=manager.updated_at,
                pairing_epoch=link.updated_at,
                requested_username="sm_" + secrets.token_hex(12) + "bot",
                requested_name=(member.workspace.name.strip() or "SM Bean client")[:64],
                expires_at=now + CONSENT_TTL,
            )
            return reservation, _creation_url(reservation, manager.bot_username)
    except IntegrityError:
        raise ManagedBotError(
            "A bot request was made concurrently. Refresh and inspect the existing request."
        ) from None


def _reservation_authority(reservation):
    _enabled()
    member = provisioning._owner(reservation.workspace, reservation.requested_by)
    manager, link = _paired_manager(reservation.manager, member.user)
    if (
        manager.workspace.organization_id != member.workspace.organization_id
        or manager.bot_id != reservation.manager_bot_id
        or manager.updated_at != reservation.manager_epoch
        or link.pk != reservation.user_link_id
        or link.updated_at != reservation.pairing_epoch
        or link.telegram_user_id != reservation.telegram_owner_id
        or timezone.now() >= reservation.expires_at
    ):
        raise TelegramPermissionDenied("The bot request expired or its manager pairing changed.")
    target = TelegramConnection.objects.filter(workspace=member.workspace).first()
    if target and target.is_active and target.bot_id != reservation.bot_id:
        raise ManagedBotError("Another bot is already active for this company.")
    return manager, member


def _valid_event(event):
    if not isinstance(event, dict):
        return None
    owner, bot = event.get("user"), event.get("bot")
    if not isinstance(owner, dict) or not isinstance(bot, dict):
        return None
    for identity in (owner, bot):
        numeric = identity.get("id")
        if isinstance(numeric, bool) or not isinstance(numeric, int) or not 0 < numeric < 2**63:
            return None
    username = bot.get("username")
    if owner.get("is_bot") is not False or bot.get("is_bot") is not True or not isinstance(username, str):
        return None
    if not USERNAME.fullmatch(username):
        return None
    return owner["id"], bot["id"], username


def process_managed_bot_update(connection, event):
    """Consume only an authenticated manager's matching, fresh consent event.

    The ingress authenticates the manager connection and deduplicates update
    ids. This second durable claim prevents separate or replayed events from
    configuring a workspace twice. Any interrupted write needs inspection.
    """
    identity = _valid_event(event)
    if identity is None:
        return {"status": "ignored"}
    owner_id, bot_id, username = identity
    with transaction.atomic():
        reservation = (
            TelegramManagedBotReservation.objects.select_for_update(of=("self",))
            .select_related("workspace", "manager__workspace", "requested_by")
            .filter(
                manager=connection,
                requested_username__iexact=username,
                telegram_owner_id=owner_id,
                used_at__isnull=True,
                status="pending",
                expires_at__gt=timezone.now(),
            )
            .first()
        )
        if reservation is None:
            return {"status": "ignored"}
        try:
            _reservation_authority(reservation)
        except (ManagedBotError, TelegramPermissionDenied):
            return {"status": "ignored"}
        reservation.bot_id = bot_id
        reservation.used_at = timezone.now()
        reservation.status = "connecting"
        reservation.save(update_fields=["bot_id", "used_at", "status"])
    try:
        manager, member = _reservation_authority(reservation)
        if not getattr(settings, "TELEGRAM_WEBHOOK_READY", False):
            raise ManagedBotError("The deployed webhook is not ready.")
        api = _capable_api(manager)
        _reservation_authority(reservation)
        # A read-only retrieval of Telegram's existing child token. Never log,
        # render, rotate or save it outside the encrypted connection model.
        token = api.get_managed_bot_token(bot_id)

        def authority_check():
            current = TelegramManagedBotReservation.objects.filter(pk=reservation.pk, status="connecting").first()
            if current is None or current.bot_id != bot_id:
                raise ManagedBotError("This bot request was cancelled or changed during setup.")
            _reservation_authority(current)

        authority_check()
        connected = provisioning.connect(
            member.workspace,
            member.user,
            token,
            authority_check=authority_check,
            expected_bot_id=bot_id,
            expected_bot_username=username,
        )
        if not connected.is_active or connected.bot_id != bot_id or connected.bot_username.lower() != username.lower():
            raise ManagedBotError("The child bot connection needs inspection.")
    except Exception:
        # Do not repeat setWebhook automatically after an unconfirmed outcome.
        TelegramManagedBotReservation.objects.filter(pk=reservation.pk, status="connecting").update(
            status="review_required",
            completed_at=timezone.now(),
            error="Setup could not be confirmed. Inspect the child bot webhook and company connection before retrying.",
        )
        return {"status": "review_required"}
    TelegramManagedBotReservation.objects.filter(pk=reservation.pk, status="connecting").update(
        status="connected", completed_at=timezone.now(), error=""
    )
    return {"status": "connected"}
