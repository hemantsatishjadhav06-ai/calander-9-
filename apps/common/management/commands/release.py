"""Everything a deploy must do before the new code takes traffic, as one command.

Railway runs the pre-deploy command without a shell, so
``backup_database --required && migrate && import_legacy_media`` ran only the
backup: ``&&`` and the rest were never interpreted, the step still "passed",
and the new code started against an unmigrated database (QA round 1, BUG-32).
One management command needs no shell and fails as a unit:

1. ``backup_database --required``: no backup, no release.
2. ``migrate --noinput``.
3. ``import_legacy_media`` when ``--legacy-media-url`` is given (best effort).
4. ``setup_brands`` + ``seed_brand_content`` with ``--setup-brands`` (best
   effort, idempotent): the brand workspaces and their test drafts. Drafts only;
   nothing is approved or scheduled.
5. ``live_verify`` with ``--verify`` (never fails the release): a PASS/FAIL
   report of the deployment in the deploy log.
"""

import logging

from django.core.management import call_command
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Pre-deploy: back up the database, migrate, then copy legacy media into storage."

    def add_arguments(self, parser):
        parser.add_argument("--legacy-media-url", default="", help="Old deployment's /media/ URL, if any.")
        parser.add_argument("--skip-backup", action="store_true", help="Only for databases with nothing to lose.")
        parser.add_argument("--setup-brands", action="store_true", help="Ensure brand workspaces and seed drafts.")
        parser.add_argument("--verify", action="store_true", help="Print the live_verify report.")

    def handle(self, *args, legacy_media_url="", skip_backup=False, setup_brands=False, verify=False, **options):
        if not skip_backup:
            call_command("backup_database", required=True, stdout=self.stdout, stderr=self.stderr)
        call_command("migrate", interactive=False, stdout=self.stdout, stderr=self.stderr)
        if legacy_media_url:
            call_command("import_legacy_media", source_url=legacy_media_url, stdout=self.stdout, stderr=self.stderr)
        if setup_brands:
            for name in ("setup_brands", "seed_brand_content"):
                self._best_effort(name)
        if verify:
            self._best_effort("live_verify")
        self.stdout.write(self.style.SUCCESS("Release steps complete."))

    def _best_effort(self, name):
        try:
            call_command(name, stdout=self.stdout, stderr=self.stderr)
        except Exception:
            logger.exception("Release step %s failed; the release continues", name)
            self.stdout.write(f"{name}: FAILED (see the error above); the release continues")
