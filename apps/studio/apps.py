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
        from apps.studio.tasks import (
            AGENCY_CYCLE_INTERVAL_SECONDS,
            STUCK_SWEEP_INTERVAL_SECONDS,
            run_agency_cycle,
            sweep_stuck_briefs,
        )

        # Each agent's turn is its own one-shot task, queued by the one before
        # it. This sweep only settles a brief whose worker died between turns,
        # which nothing else would notice.
        register_recurring_task(
            sweep_stuck_briefs,
            repeat=STUCK_SWEEP_INTERVAL_SECONDS,
            verbose_name="sweep_stuck_studio_briefs",
        )
        # The agency's heartbeat: due autopilot plans, feeding planned briefs,
        # creative memory, inbox drafts. It only reads the database and queues
        # one-shot tasks, so it stays quick at the recurring tasks' priority.
        register_recurring_task(
            run_agency_cycle,
            repeat=AGENCY_CYCLE_INTERVAL_SECONDS,
            verbose_name="run_agency_cycle",
        )
