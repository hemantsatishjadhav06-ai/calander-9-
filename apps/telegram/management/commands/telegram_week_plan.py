"""Inspect a real workspace; an explicit paired human may queue SM Bean planning."""

import json
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from apps.telegram.models import TelegramChat, TelegramUserLink
from apps.telegram.weekly import queue_week_plan, summary, summary_text
from apps.workspaces.models import Workspace


class Command(BaseCommand):
    help = "Preview a workspace week, or prepare/confirm its canonical SM Bean AI plan. Never approves or schedules."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True, help="Exact workspace UUID; no fixture or name fallback.")
        parser.add_argument("--actor-email", required=True, help="Current workspace member's email.")
        parser.add_argument("--week-start", help="Monday YYYY-MM-DD; defaults to next week in workspace time.")
        parser.add_argument("--chat-id", type=int, help="Already paired Telegram team/private numeric chat ID.")
        parser.add_argument(
            "--prepare", action="store_true", help="Collect bounded evidence and return a review token."
        )
        parser.add_argument(
            "--queue", action="store_true", help="Confirm reviewed preparation; requires --analysis-token."
        )
        parser.add_argument("--analysis-token", default="", help="Unexpired token from a separate --prepare review.")
        parser.add_argument("--json", action="store_true", help="Print structured summary/review/result.")

    def handle(self, **options):
        if options["prepare"] and options["queue"]:
            raise CommandError("Choose --prepare or --queue so the source review remains a separate human action.")
        try:
            workspace_id = UUID(str(options["workspace"]))
        except (TypeError, ValueError, AttributeError):
            raise CommandError("Supply the exact workspace UUID; names and malformed IDs are not accepted.") from None
        workspace = Workspace.objects.filter(pk=workspace_id).first()
        user = get_user_model().objects.filter(email__iexact=options["actor_email"], is_active=True).first()
        if workspace is None or user is None:
            raise CommandError("The exact workspace and active member must exist in this database.")
        try:
            if not options["prepare"] and not options["queue"]:
                data = summary(workspace, week_start=options["week_start"], user=user)
                output = (
                    json.dumps(data, indent=2)
                    if options["json"]
                    else summary_text(workspace, week_start=options["week_start"], user=user)
                )
            else:
                if options["chat_id"] is None:
                    raise CommandError("Source preparation/queueing requires an already paired team/private --chat-id.")
                if options["queue"] and not options["analysis_token"]:
                    raise CommandError(
                        "Review a separate --prepare result, then supply its --analysis-token to --queue."
                    )
                link = TelegramUserLink.objects.filter(
                    connection__workspace=workspace, user=user, is_active=True
                ).first()
                chat = TelegramChat.objects.filter(
                    connection__workspace=workspace, chat_id=options["chat_id"], is_active=True
                ).first()
                if link is None or chat is None:
                    raise CommandError("Pair the current member and team/private chat before requesting a plan.")
                data = queue_week_plan(
                    link,
                    chat,
                    week_start=options["week_start"],
                    confirmed=options["queue"],
                    analysis_token=options["analysis_token"],
                )
                output = json.dumps(data, indent=2)
        except (ValueError, PermissionDenied) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(output)
