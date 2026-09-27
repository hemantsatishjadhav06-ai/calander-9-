from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "Accounts"

    def ready(self):
        import apps.accounts.signals  # noqa: F401
        from apps.common.background import connect_recurring_tasks

        connect_recurring_tasks(self, self._register_tasks)

    @staticmethod
    def _register_tasks(sender, **kwargs):
        from apps.accounts.tasks import SESSION_CLEANUP_INTERVAL_SECONDS, clear_expired_sessions
        from apps.common.background import register_recurring_task

        register_recurring_task(
            clear_expired_sessions,
            repeat=SESSION_CLEANUP_INTERVAL_SECONDS,
            verbose_name="clear_expired_sessions",
        )
