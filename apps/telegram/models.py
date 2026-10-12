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
