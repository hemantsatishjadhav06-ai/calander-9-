from django.apps import AppConfig


class StudioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.studio"
    verbose_name = "AI Studio"

    def ready(self):
        from apps.common.background import connect_recurring_tasks

        connect_recurring_tasks(self, self._register_tasks)

    @staticmethod
    def _register_tasks(sender, **kwargs):
        from apps.common.background import register_recurring_task
        from apps.studio.tasks import STUCK_SWEEP_INTERVAL_SECONDS, sweep_stuck_briefs

        # Each agent's turn is its own one-shot task, queued by the one before
        # it. This sweep only settles a brief whose worker died between turns,
        # which nothing else would notice.
        register_recurring_task(
            sweep_stuck_briefs,
            repeat=STUCK_SWEEP_INTERVAL_SECONDS,
            verbose_name="sweep_stuck_studio_briefs",
        )
