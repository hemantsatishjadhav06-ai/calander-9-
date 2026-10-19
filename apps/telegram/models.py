"""Workspace-scoped Telegram identities, encrypted transport records and one-use proofs."""

import uuid

from django.conf import settings
from django.db import models

from apps.common.encryption import EncryptedJSONField, EncryptedTextField


class TelegramConnection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="telegram_connection"
    )
    token = EncryptedTextField()
    webhook_secret = EncryptedTextField()
    bot_id = models.PositiveBigIntegerField(unique=True)
    bot_username = models.CharField(max_length=100, blank=True, default="")
    is_active = models.BooleanField(default=False)
    approvals_enabled = models.BooleanField(default=False)
    webhook_status = models.CharField(max_length=20, default="disabled")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "telegram_connection"
        constraints = [models.CheckConstraint(condition=models.Q(bot_id__gt=0), name="telegram_bot_id_positive")]


class TelegramChat(models.Model):
    class Audience(models.TextChoices):
        CLIENT = "client", "Client group"
        TEAM = "team", "Internal team group"
        PRIVATE = "private", "Private paired chat"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(TelegramConnection, on_delete=models.CASCADE, related_name="chats")
    chat_id = models.BigIntegerField()
    chat_type = models.CharField(max_length=20)
    audience = models.CharField(max_length=20, choices=Audience.choices)
    private_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    conversation = models.ForeignKey("studio.Conversation", on_delete=models.CASCADE, related_name="telegram_chats")
    is_active = models.BooleanField(default=True)
    title = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "telegram_chat"
        constraints = [
            models.UniqueConstraint(fields=["connection", "chat_id"], name="telegram_chat_connection_unique")
        ]


class TelegramUserLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(TelegramConnection, on_delete=models.CASCADE, related_name="user_links")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="telegram_links")
    telegram_user_id = models.PositiveBigIntegerField()
    telegram_username = models.CharField(max_length=100, blank=True, default="")
    is_active = models.BooleanField(default=True)
    # /mute switches off "the team needs you" messages for this person; the
    # morning briefing and their own replies still arrive.
    notify_needs_you = models.BooleanField(default=True, db_default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "telegram_user_link"
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "telegram_user_id"], name="telegram_identity_connection_unique"
            ),
            models.UniqueConstraint(fields=["connection", "user"], name="telegram_user_connection_unique"),
            models.CheckConstraint(condition=models.Q(telegram_user_id__gt=0), name="telegram_user_id_positive"),
        ]


class TelegramPairing(models.Model):
    class Purpose(models.TextChoices):
        USER = "user", "Pair a person"
        CHAT = "chat", "Pair a group"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(TelegramConnection, on_delete=models.CASCADE, related_name="pairings")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    token_digest = models.CharField(max_length=64, unique=True)
    purpose = models.CharField(max_length=10, choices=Purpose.choices)
    audience = models.CharField(max_length=20, choices=TelegramChat.Audience.choices)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "telegram_pairing"


class TelegramManagedBotReservation(models.Model):
    """One-use consent request; credentials live only in encrypted connections."""

    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting Telegram confirmation"
        CONNECTING = "connecting", "Connecting; inspect before retrying"
        CONNECTED = "connected", "Connected"
        REVIEW_REQUIRED = "review_required", "Setup needs inspection"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manager = models.ForeignKey(TelegramConnection, on_delete=models.CASCADE, related_name="managed_reservations")
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="managed_bot_requests")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    user_link = models.ForeignKey(TelegramUserLink, on_delete=models.CASCADE, related_name="managed_reservations")
    telegram_owner_id = models.PositiveBigIntegerField()
    manager_bot_id = models.PositiveBigIntegerField()
    manager_epoch = models.DateTimeField()
    pairing_epoch = models.DateTimeField()
    requested_username = models.CharField(max_length=32, unique=True)
    requested_name = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    bot_id = models.PositiveBigIntegerField(null=True, blank=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "telegram_managed_bot_reservation"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace"],
                condition=models.Q(status__in=["pending", "connecting"]),
                name="telegram_managed_workspace_inflight",
            ),
            models.CheckConstraint(condition=models.Q(telegram_owner_id__gt=0), name="telegram_managed_owner_positive"),
            models.CheckConstraint(condition=models.Q(manager_bot_id__gt=0), name="telegram_managed_manager_positive"),
            models.CheckConstraint(
                condition=models.Q(bot_id__isnull=True) | models.Q(bot_id__gt=0), name="telegram_managed_child_positive"
            ),
        ]


class TelegramChannel(models.Model):
    """A channel broadcasts status; it never owns a conversation or review card."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(TelegramConnection, on_delete=models.CASCADE, related_name="broadcast_channels")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    chat_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=32, blank=True, default="")
    title = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    user_link = models.ForeignKey(
        TelegramUserLink, on_delete=models.SET_NULL, null=True, related_name="broadcast_channels"
    )
    telegram_user_id = models.PositiveBigIntegerField()
    bot_id = models.PositiveBigIntegerField()
    connection_epoch = models.DateTimeField()
    pairing_epoch = models.DateTimeField()
    authority_digest = models.CharField(max_length=64)
    visibility_confirmed_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "telegram_channel"
        constraints = [
            models.CheckConstraint(condition=models.Q(chat_id__lt=0), name="telegram_channel_id_negative"),
            models.CheckConstraint(condition=models.Q(telegram_user_id__gt=0), name="telegram_channel_actor_positive"),
            models.CheckConstraint(condition=models.Q(bot_id__gt=0), name="telegram_channel_bot_positive"),
        ]


class TelegramChannelDelivery(models.Model):
    """Encrypted one-way status intents kept separate from private chat replies."""

    class Status(models.TextChoices):
        PENDING = "pending", "Queued"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        UNKNOWN = "unknown", "Outcome unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(TelegramChannel, on_delete=models.CASCADE, related_name="deliveries")
    source_key = models.CharField(max_length=200)
    payload = EncryptedJSONField(default=dict)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    native_message_id = models.BigIntegerField(null=True, blank=True)
    error = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "telegram_channel_delivery"
        constraints = [
            models.UniqueConstraint(fields=["channel", "source_key"], name="telegram_channel_delivery_source_unique")
        ]


class TelegramUpdate(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Queued"
        WORKING = "working", "Processing"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(TelegramConnection, on_delete=models.CASCADE, related_name="updates")
    update_id = models.BigIntegerField()
    payload = EncryptedJSONField(default=dict)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    claimed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=500, blank=True, default="")
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "telegram_update"
        constraints = [
            models.UniqueConstraint(fields=["connection", "update_id"], name="telegram_update_connection_unique")
        ]


class TelegramAction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat = models.ForeignKey(TelegramChat, on_delete=models.CASCADE, related_name="actions")
    user_link = models.ForeignKey(TelegramUserLink, on_delete=models.CASCADE, related_name="actions")
    post = models.ForeignKey(
        "composer.Post", on_delete=models.CASCADE, null=True, blank=True, related_name="telegram_actions"
    )
    brief = models.ForeignKey(
        "studio.StudioBrief", on_delete=models.CASCADE, null=True, blank=True, related_name="telegram_actions"
    )
    kind = models.CharField(max_length=30)
    token_digest = models.CharField(max_length=64, unique=True)
    snapshot = models.JSONField(default=dict)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "telegram_action"


class TelegramDelivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Queued"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        UNKNOWN = "unknown", "Outcome unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(TelegramConnection, on_delete=models.CASCADE, related_name="deliveries")
    chat = models.ForeignKey(TelegramChat, on_delete=models.CASCADE, related_name="deliveries")
    source_key = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, default="message")
    payload = EncryptedJSONField(default=dict)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    native_message_id = models.BigIntegerField(null=True, blank=True)
    error = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "telegram_delivery"
        constraints = [models.UniqueConstraint(fields=["chat", "source_key"], name="telegram_delivery_source_unique")]


class TelegramWorkflowPrompt(models.Model):
    """A one-use, author-only reply route; never binds web history to a private chat."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey("studio.Conversation", on_delete=models.CASCADE, related_name="telegram_prompts")
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="+")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    user_link = models.ForeignKey(
        TelegramUserLink, on_delete=models.SET_NULL, null=True, related_name="workflow_prompts"
    )
    chat = models.ForeignKey(TelegramChat, on_delete=models.CASCADE, related_name="workflow_prompts")
    source_message = models.ForeignKey("studio.Message", on_delete=models.CASCADE, null=True, related_name="+")
    source_job = models.ForeignKey("studio.AgencyJob", on_delete=models.CASCADE, null=True, related_name="+")
    source_key = models.CharField(max_length=200, unique=True)
    delivery = models.OneToOneField(
        TelegramDelivery, on_delete=models.CASCADE, null=True, related_name="workflow_prompt"
    )
    snapshot = EncryptedJSONField(default=dict)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    response_message = models.OneToOneField("studio.Message", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "telegram_workflow_prompt"
