from django.apps import AppConfig


class TelegramConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.telegram"
    verbose_name = "Telegram client hub"

    def ready(self):
        from apps.common.background import connect_recurring_tasks

        from . import signals  # noqa: F401

        connect_recurring_tasks(self, self._register_tasks)

    @staticmethod
    def _register_tasks(sender, **kwargs):
        from apps.common.background import register_recurring_task

        from .tasks import TELEGRAM_SWEEP_SECONDS, run_telegram_cycle

        register_recurring_task(run_telegram_cycle, repeat=TELEGRAM_SWEEP_SECONDS, verbose_name="run_telegram_cycle")
