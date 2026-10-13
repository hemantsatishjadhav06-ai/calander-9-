"""One-shot work plus a durable recurring fallback for interrupted queue inserts."""

from datetime import timedelta

from background_task import background
from django.conf import settings
from django.db import transaction
from django.db.models.functions import Length
from django.utils import timezone

from apps.common.background import keep_schedule, note_task_failure

TELEGRAM_SWEEP_SECONDS = 30
TELEGRAM_BATCH_SIZE = 25


@background(schedule=0)
def process_update(update_id):
    from .processing import process_one

    process_one(update_id)


@background(schedule=0)
def send_delivery(delivery_id):
    from .outbox import send_one

    send_one(delivery_id)


@background(schedule=0)
@keep_schedule
def run_telegram_cycle():
    from .notifications import sweep_receipts
    from .outbox import drain_outbox
    from .processing import drain_updates

    outcomes = drain_updates(limit=TELEGRAM_BATCH_SIZE)
    sweep_receipts(limit=TELEGRAM_BATCH_SIZE)
    deliveries = drain_outbox(limit=TELEGRAM_BATCH_SIZE)
    cleanup_transient_records(limit=TELEGRAM_BATCH_SIZE)
    if outcomes.get("failed", 0) or deliveries.get("failed", 0) or deliveries.get("unknown", 0):
        note_task_failure("Telegram work requires inspection.")


def _retention_days(name, default):
    return min(365, max(1, int(getattr(settings, name, default))))


def cleanup_transient_records(*, limit=25):
    """Bounded retention without deleting canonical approval/audit records.

    Defaults: update content 7 days; delivery content/action review snapshots
    30 days; expired pairing proofs 1 day. Settings use respectively
    TELEGRAM_UPDATE_RETENTION_DAYS, TELEGRAM_DELIVERY_RETENTION_DAYS,
    TELEGRAM_ACTION_RETENTION_DAYS and TELEGRAM_PAIRING_RETENTION_DAYS.
    Held delivery statuses, semantic keys, actors and native receipts remain.
    """
    from .models import TelegramAction, TelegramDelivery, TelegramPairing, TelegramUpdate

    now, cap = timezone.now(), min(100, max(1, limit))
    count = 0
    for model, date_field, states, setting, default in (
        (TelegramUpdate, "created_at", ["processed", "failed"], "TELEGRAM_UPDATE_RETENTION_DAYS", 7),
        (TelegramDelivery, "updated_at", ["sent", "failed", "unknown"], "TELEGRAM_DELIVERY_RETENTION_DAYS", 30),
    ):
        with transaction.atomic():
            # The shared EncryptedJSONField stores AES-GCM base64: an empty
            # dict uses 40 bytes. SQL length skips already-cleared records;
            # encrypted equality lookups cannot match randomized ciphertext.
            ids = list(
                model.objects.select_for_update(skip_locked=True)
                .filter(
                    status__in=states, **{f"{date_field}__lt": now - timedelta(days=_retention_days(setting, default))}
                )
                .annotate(_payload_size=Length("payload"))
                .filter(_payload_size__gt=40)
                .order_by(date_field)
                .values_list("pk", flat=True)[:cap]
            )
            count += model.objects.filter(pk__in=ids).update(payload={})
    with transaction.atomic():
        action_ids = list(
            TelegramAction.objects.select_for_update(skip_locked=True)
            .filter(expires_at__lt=now - timedelta(days=_retention_days("TELEGRAM_ACTION_RETENTION_DAYS", 30)))
            .exclude(snapshot={})
            .order_by("expires_at")
            .values_list("pk", flat=True)[:cap]
        )
        count += TelegramAction.objects.filter(pk__in=action_ids).update(snapshot={})
        pairing_ids = list(
            TelegramPairing.objects.select_for_update(skip_locked=True)
            .filter(expires_at__lt=now - timedelta(days=_retention_days("TELEGRAM_PAIRING_RETENTION_DAYS", 1)))
            .order_by("expires_at")
            .values_list("pk", flat=True)[:cap]
        )
        removed, _ = TelegramPairing.objects.filter(pk__in=pairing_ids).delete()
        count += removed
    return count
