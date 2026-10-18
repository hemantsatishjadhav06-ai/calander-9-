from django.apps import AppConfig

from apps.common.background import connect_recurring_tasks, register_recurring_task


class SocialAccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.social_accounts"
    verbose_name = "Social Accounts"

    def ready(self):
        connect_recurring_tasks(self, self._register_health_check_task)

    @staticmethod
    def _register_health_check_task(sender, **kwargs):
        """Register the recurring health-check task after migrations are applied."""
        from apps.social_accounts.tasks import schedule_all_health_checks

        register_recurring_task(
            schedule_all_health_checks,
            repeat=6 * 3600,
            verbose_name="schedule_all_health_checks",
        )
