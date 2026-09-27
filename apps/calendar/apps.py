from django.apps import AppConfig


class CalendarConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.calendar"
    verbose_name = "Content Calendar"

    def ready(self):
        from apps.common.background import connect_recurring_tasks

        connect_recurring_tasks(self, self._register_tasks)

    @staticmethod
    def _register_tasks(sender, **kwargs):
        from apps.calendar.tasks import RECURRENCE_INTERVAL_SECONDS, run_recurrence_cycle
        from apps.common.background import register_recurring_task

        # The composer's "Make recurring" option writes RecurrenceRule rows;
        # nothing consumed them until this was registered.
        register_recurring_task(
            run_recurrence_cycle,
            repeat=RECURRENCE_INTERVAL_SECONDS,
            verbose_name="run_recurrence_cycle",
        )
