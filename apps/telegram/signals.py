"""Queue mirrors after commit; inbound echoes and rolled-back work never leave."""

import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.composer.models import PlatformPost
from apps.notifications.models import Notification
from apps.studio.models import Message

from .processing import INBOUND_PROCESSING

logger = logging.getLogger(__name__)


def _mirror_safely(handler, object_id):
    from apps.common.background import note_task_failure

    try:
        handler(object_id)
    except Exception:
        # A delivery problem must not unwind a confirmed business mutation or
        # print a provider exception containing private credentials/content.
        note_task_failure("Telegram mirror failed.")
        logger.error("Telegram mirror could not be queued; inspect its worker and delivery status.")


@receiver(post_save, sender=Message, dispatch_uid="telegram_conversation_message")
def conversation_message(sender, instance, created, raw=False, **kwargs):
    if not created or raw or INBOUND_PROCESSING.get():
        return
    from .notifications import mirror_message

    message_id = instance.pk
    transaction.on_commit(lambda: _mirror_safely(mirror_message, message_id))


@receiver(post_save, sender=Notification, dispatch_uid="telegram_notification_event")
def notification_created(sender, instance, created, raw=False, **kwargs):
    if not created or raw:
        return
    from .notifications import notification_event

    notification_id = instance.pk
    transaction.on_commit(lambda: _mirror_safely(notification_event, notification_id))


@receiver(post_save, sender=PlatformPost, dispatch_uid="telegram_platform_delivery_receipt")
def platform_delivery_changed(sender, instance, raw=False, **kwargs):
    if raw:
        return
    from .notifications import platform_receipt

    platform_post_id = instance.pk
    transaction.on_commit(lambda: _mirror_safely(platform_receipt, platform_post_id))
