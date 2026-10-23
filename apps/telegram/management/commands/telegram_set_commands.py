"""Publish the bot command menu for connections made before the menu existed."""

from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from apps.telegram.models import TelegramConnection
from apps.telegram.provisioning import register_commands


class Command(BaseCommand):
    help = "Publish the Telegram command menu for every active bot (or one workspace's bot). Sends no messages."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", help="Only this workspace UUID.")

    def handle(self, **options):
        rows = TelegramConnection.objects.filter(is_active=True).select_related("workspace").order_by("created_at")
        if options.get("workspace"):
            try:
                rows = rows.filter(workspace_id=UUID(str(options["workspace"])))
            except (TypeError, ValueError, AttributeError):
                raise CommandError("Supply the exact workspace UUID.") from None
        count = 0
        for connection in rows:
            outcome = register_commands(connection.token)
            count += outcome
            self.stdout.write(
                f"{connection.workspace.name}: @{connection.bot_username or '?'} "
                f"{'menu published' if outcome else 'menu not published; check the token'}"
            )
        if not rows:
            self.stdout.write("No active Telegram bot to update.")
        self.stdout.write(f"telegram_set_commands: {count} bot(s) updated")
