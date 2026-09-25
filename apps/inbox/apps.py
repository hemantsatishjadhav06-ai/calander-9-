from django.apps import AppConfig


class InboxConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inbox"
    verbose_name = "Inbox"

    def ready(self):
        from django.db.models.signals import post_delete

        from apps.common.background import connect_recurring_tasks
        from apps.members.models import WorkspaceMembership

        connect_recurring_tasks(self, self._register_tasks)
        post_delete.connect(
            self._unassign_removed_member,
            sender=WorkspaceMembership,
            dispatch_uid="inbox.unassign_removed_member",
        )

    @staticmethod
    def _unassign_removed_member(sender, instance, **kwargs):
        """A member removed from a workspace no longer holds any of its messages.

        ``assigned_to`` is a plain user FK, so removing the membership left the
        message assigned to someone who could no longer open it — and it was
        filtered out of every other member's "unassigned" view.
        """
        from apps.inbox.models import InboxMessage

        InboxMessage.objects.filter(workspace_id=instance.workspace_id, assigned_to_id=instance.user_id).update(
            assigned_to=None
        )

    @staticmethod
    def _register_tasks(sender, **kwargs):
        from apps.common.background import register_recurring_task
        from apps.inbox.tasks import INBOX_SYNC_INTERVAL_SECONDS, run_inbox_sync_cycle

        register_recurring_task(
            run_inbox_sync_cycle,
            repeat=INBOX_SYNC_INTERVAL_SECONDS,
            verbose_name="run_inbox_sync_cycle",
        )
