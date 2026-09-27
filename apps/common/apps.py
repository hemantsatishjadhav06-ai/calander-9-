from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.common"
    verbose_name = "Common"

    def ready(self):
        # Register deploy-time config checks (python manage.py check --deploy).
        from apps.common import checks  # noqa: F401
        from apps.common.background import connect_recurring_tasks

        connect_recurring_tasks(self, self._register_tasks)

    @staticmethod
    def _register_tasks(sender, **kwargs):
        from apps.common.background import register_recurring_task
        from apps.common.tasks import COUNTER_PURGE_INTERVAL_SECONDS, purge_email_counters

        register_recurring_task(
            purge_email_counters,
            repeat=COUNTER_PURGE_INTERVAL_SECONDS,
            verbose_name="purge_email_counters",
        )
