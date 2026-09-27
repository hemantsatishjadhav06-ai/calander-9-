import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class IntelligenceConfig(AppConfig):
    name = "apps.intelligence"
    label = "intelligence"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.conf import settings

        from apps.common.background import connect_recurring_tasks

        # Only schedule background tasks when the integration is actually
        # enabled. A self-hoster who hasn't configured Intelligence env
        # vars shouldn't see periodic /internal/v1/ calls failing in
        # their logs.
        if not getattr(settings, "INTELLIGENCE_ENABLED", False):
            return

        connect_recurring_tasks(self, self._register_recurring_tasks)

    @staticmethod
    def _register_recurring_tasks(sender, **kwargs):
        """Schedule the recurring reconcile after migrations apply and on worker boot."""
        from apps.common.background import register_recurring_task
        from apps.intelligence.tasks import (
            INTELLIGENCE_RECONCILE_INTERVAL_SECONDS,
            reconcile_intelligence_subscriptions,
        )

        register_recurring_task(
            reconcile_intelligence_subscriptions,
            repeat=INTELLIGENCE_RECONCILE_INTERVAL_SECONDS,
            verbose_name="intelligence_reconcile",
        )
