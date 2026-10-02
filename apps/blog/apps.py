from django.apps import AppConfig


class BlogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.blog"
    verbose_name = "Blog"

    def ready(self):
        from apps.common.background import connect_recurring_tasks

        connect_recurring_tasks(self, self._register_tasks)

    @staticmethod
    def _register_tasks(sender, **kwargs):
        from apps.blog.tasks import STUCK_SWEEP_INTERVAL_SECONDS, sweep_stuck_blog_publishes
        from apps.common.background import register_recurring_task

        # Publishing itself runs as one-shot tasks (publish, then poll the
        # deploy). This sweep only settles a post left in ``publishing`` by a
        # worker that died between the two, which nothing else would recover.
        register_recurring_task(
            sweep_stuck_blog_publishes,
            repeat=STUCK_SWEEP_INTERVAL_SECONDS,
            verbose_name="sweep_stuck_blog_publishes",
        )
