"""Dump every table to CSV, tar+gzip it, and store it under backups/ in default storage.

Railway's Hobby plan has no Postgres backups, and pg_dump in the image would
have to match the server's major version exactly. COPY ... TO STDOUT is
version-agnostic and needs nothing but the app's own connection. The archive is
data only: restore by checking out the commit named in manifest.json, running
``migrate`` on an empty database, then ``manage.py restore_database <archive>``.

Runs as the first pre-deploy step so a release never migrates a database it has
not just backed up; ``--required`` makes a failed backup stop the deploy.
"""

import io
import json
import os
import tarfile
import tempfile
from datetime import UTC, datetime

from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Back up all tables (CSV per table) to default storage under backups/."

    def add_arguments(self, parser):
        parser.add_argument("--required", action="store_true", help="Exit non-zero if the backup fails.")

    def handle(self, *args, required=False, **options):
        try:
            name = self._backup()
        except Exception as exc:
            if required:
                raise CommandError(f"Database backup failed: {exc}") from exc
            self.stderr.write(f"Database backup failed (continuing): {exc}")
            return
        self.stdout.write(self.style.SUCCESS(f"Database backed up to {name}"))

    def _backup(self) -> str:
        stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        with connection.cursor() as cursor:
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
            tables = [row[0] for row in cursor.fetchall()]
            raw = cursor.cursor  # psycopg 3 cursor
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                counts = {}
                with tarfile.open(tmp_path, "w:gz") as tar:
                    for table in tables:
                        buf = io.BytesIO()
                        with raw.copy(f'COPY "{table}" TO STDOUT WITH (FORMAT csv, HEADER true)') as copy:
                            for chunk in copy:
                                buf.write(chunk)
                        counts[table] = raw.rowcount
                        self._add(tar, f"{table}.csv", buf.getvalue())
                    manifest = {
                        "created_at": stamp,
                        "commit": os.environ.get("RAILWAY_GIT_COMMIT_SHA", ""),
                        "tables": counts,
                    }
                    self._add(tar, "manifest.json", json.dumps(manifest, indent=1).encode())
                name = f"backups/db-{stamp}.tar.gz"
                with open(tmp_path, "rb") as fh:
                    return default_storage.save(name, File(fh, name=os.path.basename(name)))
            finally:
                os.unlink(tmp_path)

    @staticmethod
    def _add(tar, name, data: bytes):
        info = tarfile.TarInfo(name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
