import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)

SYNC_INTERVAL_SECONDS = 3600  # hourly


class AnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.analytics"
    verbose_name = "Analytics"

    def ready(self):
        from apps.common.background import connect_recurring_tasks

        from . import signals  # noqa: F401

        # Register the recurring sync after migrate *and* when the worker starts
        # (connect_recurring_tasks), so a schedule django-background-tasks
        # dropped comes back on the next worker boot. The agency's creative
        # memory and plans learn from these numbers, so a lost sync would
        # quietly stop the team learning.
        connect_recurring_tasks(self, self._register_sync_task)

    @staticmethod
    def _register_sync_task(sender, **kwargs):
        """Idempotently register the hourly analytics sync cron."""
        from apps.analytics.tasks import sync_all_account_analytics
        from apps.common.background import register_recurring_task

        register_recurring_task(
            sync_all_account_analytics,
            repeat=SYNC_INTERVAL_SECONDS,
            verbose_name="sync_all_account_analytics",
        )
