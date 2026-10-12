"""One-use pairing and owner-controlled bot setup, without username authority."""

import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.common.validators import resolve_public_ip
from apps.studio.models import Conversation

from .api import BotAPI
from .models import (
    TelegramAction,
    TelegramChat,
    TelegramConnection,
    TelegramDelivery,
    TelegramPairing,
    TelegramUpdate,
    TelegramUserLink,
)
from .permissions import (
    TelegramPermissionDenied,
    can_manage,
    can_pair_group,
    current_member,
    fresh_member,
    internal_member,
)

PAIRING_TTL = timedelta(minutes=10)


class ProvisioningError(ValueError):
    pass


def digest(nonce):
    return hashlib.sha256(nonce.encode()).hexdigest()


def _owner(workspace, user, *, locked=False, connection=None):
    member = current_member(workspace, user, locked=locked, connection=connection)
    if not can_manage(member):
        raise TelegramPermissionDenied("Only a current workspace owner or settings manager can configure Telegram.")
    return member


def _webhook_url(connection_id):
    base = (getattr(settings, "TELEGRAM_WEBHOOK_BASE_URL", "") or "").rstrip("/")
    try:
        parsed = urlsplit(base)
        port = parsed.port
    except ValueError:
        return None
    if (
        not getattr(settings, "TELEGRAM_WEBHOOK_READY", False)
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        or "." not in parsed.hostname
    ):
        return None
    import ipaddress

    try:
        if not ipaddress.ip_address(parsed.hostname).is_global:
            return None
    except ValueError:
        pass
    if resolve_public_ip(base) is None:
        return None
    return base + reverse("telegram_webhooks:ingress", kwargs={"connection_id": connection_id})


def _finish_setup(connection_id, claim_time, previous, *, failed=False):
    """Restore a failed claim only if no disconnect/new setup superseded it."""
    with transaction.atomic():
        current = TelegramConnection.objects.select_for_update().filter(pk=connection_id).first()
        if current is None or current.updated_at != claim_time:
            return
        if previous and current.workspace_id != previous.workspace_id:
            current.is_active = False
            current.approvals_enabled = False
            current.token = ""
            current.webhook_secret = ""
            current.webhook_status = "setup_failed"
        elif previous:
            for field in (
                "token",
                "webhook_secret",
                "bot_id",
                "bot_username",
                "is_active",
                "approvals_enabled",
                "webhook_status",
            ):
                setattr(current, field, getattr(previous, field))
        elif failed:
            current.is_active = False
            current.approvals_enabled = False
            current.webhook_status = "setup_failed"
        current.save()


def connect(workspace, user, token, *, approvals_enabled=False):
    import uuid

    member = _owner(workspace, user)
    previous = TelegramConnection.objects.filter(workspace=member.workspace).first()
    connection_id = previous.pk if previous else uuid.uuid4()
    url = _webhook_url(connection_id)
    if approvals_enabled and not member.workspace.require_dashboard_approval:
        raise ProvisioningError("Enable the workspace's exact human approval gate before Telegram approvals.")
    try:
        api = BotAPI(token)
        bot = api.get_me()
        webhook = api.get_webhook_info()
    except Exception:
        raise ProvisioningError("Telegram could not validate this bot. Check the token and try again.") from None
    if (
        not isinstance(bot, dict)
        or bot.get("is_bot") is not True
        or isinstance(bot.get("id"), bool)
        or not isinstance(bot.get("id"), int)
        or bot["id"] <= 0
    ):
        raise ProvisioningError("Telegram did not identify a valid bot.")
    remote_url = webhook.get("url") if isinstance(webhook, dict) else None
    if not isinstance(remote_url, str) or (remote_url and remote_url != url):
        raise ProvisioningError(
            "This bot has a different webhook. Remove it with its existing application before connecting here."
        )
    if previous and previous.bot_id != bot["id"] and previous.is_active:
        raise ProvisioningError("Disable the current bot before replacing it with another bot.")
    if previous and not url:
        raise ProvisioningError(
            "The deployed HTTPS webhook has not been confirmed ready. The saved bot configuration was kept."
        )
    secret = (
        previous.webhook_secret
        if previous and previous.bot_id == bot["id"] and previous.webhook_secret
        else secrets.token_urlsafe(32)
    )
    # Reserve the globally unique bot identity BEFORE an external write. This
    # prevents a competing workspace from redirecting the webhook and then
    # losing the database uniqueness race. No network runs under row locks.
    try:
        with transaction.atomic():
            member = _owner(workspace, user, locked=True, connection=previous)
            current = TelegramConnection.objects.select_for_update().filter(workspace=member.workspace).first()
            if current and (previous is None or current.updated_at != previous.updated_at):
                raise ProvisioningError("Bot configuration changed during setup. Refresh before continuing.")
            if current and current.webhook_status == "setup_in_progress":
                raise ProvisioningError("Bot setup is already in progress. Inspect its outcome before retrying.")
            if TelegramConnection.objects.filter(bot_id=bot["id"]).exclude(workspace=member.workspace).exists():
                raise ProvisioningError("This bot is already assigned to another workspace. Create a separate bot.")
            if approvals_enabled and not member.workspace.require_dashboard_approval:
                raise ProvisioningError("The workspace approval gate changed. Telegram approvals were not enabled.")
            reserved = current or TelegramConnection(
                id=connection_id, workspace=member.workspace, created_by=member.user
            )
            reserved.token = token
            reserved.webhook_secret = secret
            reserved.bot_id = bot["id"]
            reserved.bot_username = str(bot.get("username") or "")[:100]
            reserved.webhook_status = "setup_in_progress" if url else "pending_deployment"
            reserved.save()
            claim_time = reserved.updated_at
    except IntegrityError:
        raise ProvisioningError(
            "This bot or workspace was connected concurrently. Refresh before continuing."
        ) from None
    if url:
        try:
            if api.set_webhook(url, secret) is not True:
                raise ProvisioningError("Telegram did not accept the webhook.")
        except Exception:
            _finish_setup(connection_id, claim_time, previous, failed=True)
            raise ProvisioningError(
                "Webhook setup failed. Check the remote webhook before retrying; the previous saved configuration was kept."
            ) from None
    try:
        with transaction.atomic():
            member = _owner(workspace, user, locked=True, connection=reserved)
            current = TelegramConnection.objects.select_for_update().get(pk=connection_id)
            if current.updated_at != claim_time or current.workspace_id != member.workspace_id:
                raise ProvisioningError(
                    "Bot configuration changed during setup. Inspect its webhook before continuing."
                )
            if approvals_enabled and not member.workspace.require_dashboard_approval:
                raise ProvisioningError("The workspace approval gate changed. Telegram approvals were not enabled.")
            if previous and previous.bot_id != bot["id"]:
                _invalidate_queues(current)
                current.chats.update(is_active=False)
                current.user_links.update(is_active=False)
                current.pairings.filter(used_at__isnull=True).update(used_at=timezone.now())
            current.approvals_enabled = bool(approvals_enabled)
            current.is_active = bool(url)
            current.webhook_status = "active" if url else "pending_deployment"
            current.save()
            return current
    except (TelegramPermissionDenied, ProvisioningError):
        _finish_setup(connection_id, claim_time, previous, failed=True)
        raise


def _invalidate_queues(connection, *, chat=None):
    """Hold unfinished intents durably; in-flight sends may already exist."""
    actions = TelegramAction.objects.filter(chat__connection=connection, used_at__isnull=True)
    if chat is not None:
        actions = actions.filter(chat=chat)
    actions.update(used_at=timezone.now(), result={"ok": False, "reason": "access_revoked"})
    updates = TelegramUpdate.objects.filter(connection=connection, status__in=["pending", "working"])
    if chat is not None:
        # Update bodies are encrypted, so scope by the decrypted authenticated
        # numeric chat. Preserve rows as audit evidence rather than deleting.
        ids = []
        for row in updates.only("id", "payload").iterator(chunk_size=200):
            payload = row.payload if isinstance(row.payload, dict) else {}
            query = payload.get("callback_query") or {}
            message = query.get("message", {}) if isinstance(query, dict) and query else payload.get("message", {})
            if (
                isinstance(message, dict)
                and isinstance(message.get("chat"), dict)
                and message["chat"].get("id") == chat.chat_id
            ):
                ids.append(row.pk)
        updates = updates.filter(pk__in=ids)
    updates.update(
        status="failed",
        error="Telegram access was disabled or its bot changed. Inspect previous work before sending a fresh request.",
    )
    deliveries = TelegramDelivery.objects.filter(connection=connection)
    if chat is not None:
        deliveries = deliveries.filter(chat=chat)
    deliveries.filter(status="pending").update(
        status="failed",
        error="Telegram access was disabled or its bot changed. Request a fresh reply after pairing again.",
        updated_at=timezone.now(),
    )
    deliveries.filter(status="sending").update(
        status="unknown",
        error="Telegram access changed during a send. Inspect the chat before requesting another attempt.",
        updated_at=timezone.now(),
    )


def disconnect(connection, user):
    with transaction.atomic():
        _owner(connection.workspace, user, locked=True, connection=connection)
        current = TelegramConnection.objects.select_for_update().get(pk=connection.pk)
        current.is_active = False
        current.approvals_enabled = False
        current.webhook_status = "disabled"
        current.token = ""
        current.webhook_secret = ""
        current.save()
        _invalidate_queues(current)
        current.chats.update(is_active=False)
        current.user_links.update(is_active=False)
        current.pairings.filter(used_at__isnull=True).update(used_at=timezone.now())


def issue_pairing(connection, user, *, purpose="user", audience="private"):
    with transaction.atomic():
        member = current_member(connection.workspace, user, locked=True, connection=connection)
        current = TelegramConnection.objects.select_for_update().filter(pk=connection.pk, is_active=True).first()
        if current is None:
            raise ProvisioningError("The bot must have an active deployed webhook before pairing.")
        if purpose not in {"user", "chat"} or audience not in {"client", "team", "private"}:
            raise ProvisioningError("Choose a supported pairing purpose and audience.")
        if purpose == "chat" and (not can_pair_group(member) or audience == "private"):
            raise TelegramPermissionDenied("A paired workspace manager must connect groups.")
        if purpose == "user" and audience != "private":
            raise ProvisioningError("Personal pairing uses a private chat.")
        if (
            purpose == "chat"
            and not TelegramUserLink.objects.filter(connection=current, user=user, is_active=True).exists()
        ):
            raise ProvisioningError("Pair your personal Telegram identity before connecting a group.")
        nonce = secrets.token_urlsafe(24)
        ticket = TelegramPairing.objects.create(
            connection=current,
            user=user,
            token_digest=digest(nonce),
            purpose=purpose,
            audience=audience,
            expires_at=timezone.now() + PAIRING_TTL,
        )
        return ticket, nonce


def _ticket(connection, nonce, purpose):
    if not isinstance(nonce, str) or not 20 <= len(nonce) <= 64:
        raise ProvisioningError("This pairing code is invalid or expired.")
    ticket = (
        TelegramPairing.objects.select_for_update()
        .filter(
            connection=connection,
            token_digest=digest(nonce),
            purpose=purpose,
            used_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .first()
    )
    if ticket is None:
        raise ProvisioningError("This pairing code is invalid, expired or already used.")
    return ticket


def private_chat(connection, link, *, reactivate=False):
    member = fresh_member(link)
    if link.connection_id != connection.pk or member.workspace_id != connection.workspace_id:
        raise TelegramPermissionDenied("This private pairing belongs to another bot.")
    with transaction.atomic():
        member = fresh_member(link, locked=True)
        link = TelegramUserLink.objects.get(pk=link.pk, connection=connection, user=member.user, is_active=True)
        audience = Conversation.Audience.INTERNAL if internal_member(member) else Conversation.Audience.CLIENT
        current = (
            TelegramChat.objects.select_for_update()
            .filter(connection=connection, chat_id=link.telegram_user_id)
            .first()
        )
        if current and (current.audience != "private" or current.private_user_id != link.user_id):
            raise ProvisioningError("This Telegram chat belongs to another pairing.")
        if current and (
            current.conversation.workspace_id != member.workspace_id
            or current.conversation.created_by_id != member.user_id
        ):
            raise TelegramPermissionDenied("This private conversation is unavailable in the workspace.")
        if current and not current.is_active and not reactivate:
            raise TelegramPermissionDenied(
                "This private chat is disabled. Pair explicitly again in SM Bean before using it."
            )
        if current and current.conversation.audience == audience and current.is_active:
            return current
        conversation = Conversation.objects.create(
            workspace=member.workspace, audience=audience, title="Telegram private conversation", created_by=member.user
        )
        if current:
            current.conversation = conversation
            current.is_active = True
            current.save(update_fields=["conversation", "is_active", "updated_at"])
            return current
        return TelegramChat.objects.create(
            connection=connection,
            chat_id=link.telegram_user_id,
            chat_type="private",
            audience="private",
            private_user=member.user,
            conversation=conversation,
        )


def consume_user_pairing(connection, nonce, telegram_user_id, telegram_username=""):
    if not isinstance(nonce, str) or not 20 <= len(nonce) <= 64:
        raise ProvisioningError("This pairing code is invalid or expired.")
    if isinstance(telegram_user_id, bool) or not isinstance(telegram_user_id, int) or not 0 < telegram_user_id < 2**63:
        raise ProvisioningError("A numeric Telegram user identity is required.")
    with transaction.atomic():
        candidate = (
            TelegramPairing.objects.filter(connection=connection, token_digest=digest(nonce), purpose="user")
            .select_related("user")
            .first()
        )
        if candidate is None:
            raise ProvisioningError("This pairing code is unavailable.")
        current_member(connection.workspace, candidate.user, locked=True, connection=connection)
        active = TelegramConnection.objects.select_for_update().filter(pk=connection.pk, is_active=True).first()
        if active is None:
            raise ProvisioningError("This bot connection is inactive.")
        ticket = _ticket(active, nonce, "user")
        conflict = (
            TelegramUserLink.objects.filter(connection=active, telegram_user_id=telegram_user_id)
            .exclude(user=ticket.user)
            .exists()
        )
        if conflict:
            raise ProvisioningError("This Telegram identity is already paired to another workspace member.")
        old = TelegramUserLink.objects.filter(connection=active, user=ticket.user).first()
        if old and old.is_active and old.telegram_user_id != telegram_user_id:
            raise ProvisioningError("Disconnect your previous identity before pairing another.")
        link, _ = TelegramUserLink.objects.update_or_create(
            connection=active,
            user=ticket.user,
            defaults={
                "telegram_user_id": telegram_user_id,
                "telegram_username": str(telegram_username or "")[:100],
                "is_active": True,
            },
        )
        ticket.used_at = timezone.now()
        ticket.save(update_fields=["used_at"])
        private_chat(active, link, reactivate=True)
        return link


def consume_chat_pairing(connection, nonce, telegram_user_id, chat_id, chat_type, title=""):
    if (
        not isinstance(nonce, str)
        or not 20 <= len(nonce) <= 64
        or isinstance(telegram_user_id, bool)
        or not isinstance(telegram_user_id, int)
        or not 0 < telegram_user_id < 2**63
    ):
        raise ProvisioningError("A valid pairing code and numeric Telegram identity are required.")
    if (
        chat_type not in {"group", "supergroup"}
        or isinstance(chat_id, bool)
        or not isinstance(chat_id, int)
        or not -(2**63) <= chat_id < 0
    ):
        raise ProvisioningError("Pair a real Telegram group or supergroup.")
    candidate = (
        TelegramPairing.objects.filter(
            connection=connection,
            token_digest=digest(nonce),
            purpose="chat",
            used_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .select_related("user")
        .first()
    )
    link = TelegramUserLink.objects.filter(
        connection=connection, telegram_user_id=telegram_user_id, is_active=True
    ).first()
    if candidate is None or link is None or link.user_id != candidate.user_id or not can_pair_group(fresh_member(link)):
        raise TelegramPermissionDenied("The pairing code must be used by its paired workspace manager.")
    verified_connection = TelegramConnection.objects.get(pk=connection.pk, is_active=True)
    try:
        administrator = BotAPI(verified_connection.token).get_chat_member(chat_id, telegram_user_id)
    except Exception:
        raise ProvisioningError("Telegram could not verify your group administrator membership. Try again.") from None
    if (
        not isinstance(administrator, dict)
        or administrator.get("status") not in {"administrator", "creator"}
        or not isinstance(administrator.get("user"), dict)
        or administrator["user"].get("id") != telegram_user_id
    ):
        raise TelegramPermissionDenied("The paired manager must be a Telegram administrator of this group.")
    with transaction.atomic():
        member = fresh_member(link, locked=True)
        if member.workspace_id != connection.workspace_id:
            raise TelegramPermissionDenied("This bot connection moved to another workspace.")
        if not can_pair_group(member):
            raise TelegramPermissionDenied("Your group-management permission changed.")
        current_connection = TelegramConnection.objects.get(pk=connection.pk, is_active=True)
        if (
            current_connection.workspace_id != member.workspace_id
            or current_connection.bot_id != verified_connection.bot_id
            or current_connection.token != verified_connection.token
        ):
            raise TelegramPermissionDenied("The bot connection changed during group verification.")
        ticket = _ticket(current_connection, nonce, "chat")
        current_identity = TelegramUserLink.objects.filter(
            pk=link.pk, telegram_user_id=telegram_user_id, user=ticket.user, is_active=True
        ).first()
        if current_identity is None:
            raise TelegramPermissionDenied("This pairing identity changed during group verification.")
        current = TelegramChat.objects.select_for_update().filter(connection=connection, chat_id=chat_id).first()
        if current and (current.conversation.workspace_id != member.workspace_id or current.audience == "private"):
            raise TelegramPermissionDenied("This group conversation is unavailable in this workspace.")
        if current and current.audience != ticket.audience:
            raise ProvisioningError(
                "This group already has a different audience. Create a separate Telegram group for the new audience."
            )
        if (
            current
            and current.audience == ticket.audience
            and current.conversation.audience
            == (Conversation.Audience.CLIENT if ticket.audience == "client" else Conversation.Audience.INTERNAL)
        ):
            current.is_active = True
            current.title = str(title)[:255]
            current.save(update_fields=["is_active", "title", "updated_at"])
        else:
            conversation = Conversation.objects.create(
                workspace=member.workspace,
                audience=Conversation.Audience.CLIENT
                if ticket.audience == "client"
                else Conversation.Audience.INTERNAL,
                title="Telegram client group" if ticket.audience == "client" else "Telegram internal team",
                created_by=member.user,
            )
            if current:
                current.audience = ticket.audience
                current.conversation = conversation
                current.is_active = True
                current.title = str(title)[:255]
                current.save()
            else:
                current = TelegramChat.objects.create(
                    connection=connection,
                    chat_id=chat_id,
                    chat_type=chat_type,
                    audience=ticket.audience,
                    conversation=conversation,
                    title=str(title)[:255],
                )
        ticket.used_at = timezone.now()
        ticket.save(update_fields=["used_at"])
        return current


def consume_pairing_message(connection, message):
    if not isinstance(message, dict) or any(
        message.get(key) for key in ("sender_chat", "forward_origin", "forward_from", "forward_from_chat")
    ):
        raise TelegramPermissionDenied("Use your own Telegram identity to pair.")
    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    if (
        not isinstance(sender, dict)
        or not isinstance(chat, dict)
        or sender.get("is_bot")
        or isinstance(sender.get("id"), bool)
        or not isinstance(sender.get("id"), int)
    ):
        raise TelegramPermissionDenied("A human numeric Telegram identity is required.")
    parts = str(message.get("text") or "").split()
    if len(parts) != 2:
        raise ProvisioningError("Send the complete one-use pairing command.")
    command = parts[0].split("@")[0]
    nonce = parts[1].removeprefix("pair_")
    if command == "/start" and chat.get("type") == "private" and chat.get("id") == sender["id"]:
        return consume_user_pairing(connection, nonce, sender["id"], sender.get("username", ""))
    if command == "/pair":
        return consume_chat_pairing(
            connection, nonce, sender["id"], chat.get("id"), chat.get("type"), chat.get("title", "")
        )
    raise ProvisioningError("Pair yourself in the bot's private chat, or use the group pairing command in its group.")


def unpair(connection, user):
    """Revoke only the caller's numeric identity and private-chat access."""
    with transaction.atomic():
        member = current_member(connection.workspace, user, locked=True, connection=connection)
        link = TelegramUserLink.objects.select_for_update().filter(connection=connection, user=member.user).first()
        if link:
            link.is_active = False
            link.save(update_fields=["is_active", "updated_at"])
            TelegramAction.objects.filter(user_link=link, used_at__isnull=True).update(
                used_at=timezone.now(), result={"ok": False, "reason": "identity_unpaired"}
            )
        private_chats = TelegramChat.objects.filter(connection=connection, audience="private", private_user=member.user)
        for chat in private_chats:
            _invalidate_queues(connection, chat=chat)
        private_chats.update(is_active=False)
        TelegramPairing.objects.filter(connection=connection, user=member.user, used_at__isnull=True).update(
            used_at=timezone.now()
        )


def deactivate_chat(connection, user, chat_id):
    with transaction.atomic():
        _owner(connection.workspace, user, locked=True, connection=connection)
        chat = TelegramChat.objects.select_for_update().filter(pk=chat_id, connection=connection).first()
        if chat is None:
            raise ProvisioningError("This chat is unavailable in the workspace.")
        _invalidate_queues(connection, chat=chat)
        chat.is_active = False
        chat.save(update_fields=["is_active", "updated_at"])
        chat.actions.filter(used_at__isnull=True).update(used_at=timezone.now())
