"""Load a backup_database archive into this (migrated) database. Destroys current data.

Run against a database migrated to the commit named in the archive's
manifest.json. Every table in the archive is truncated and reloaded; foreign
keys are not checked during the load (``session_replication_role = replica``)
so tables can go in any order, and sequences are reset afterwards.
"""

import json
import tarfile

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction


class Command(BaseCommand):
    help = "Restore a backup_database archive (local path or storage key). Wipes the tables it contains."

    def add_arguments(self, parser):
        parser.add_argument("archive")
        parser.add_argument("--yes-wipe-data", action="store_true", help="Required: confirms data will be replaced.")

    def handle(self, *args, archive, yes_wipe_data=False, **options):
        if not yes_wipe_data:
            raise CommandError("Refusing to run without --yes-wipe-data.")
        fh = open(archive, "rb") if not default_storage.exists(archive) else default_storage.open(archive, "rb")  # noqa: SIM115
        with fh, tarfile.open(fileobj=fh, mode="r:gz") as tar:
            manifest = json.load(tar.extractfile("manifest.json"))
            tables = list(manifest["tables"])
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                existing = {row[0] for row in cursor.fetchall()}
                missing = [t for t in tables if t not in existing]
                if missing:
                    raise CommandError(
                        f"Migrate to commit {manifest.get('commit') or '?'} first; missing {missing[:5]}"
                    )
                cursor.execute("SET LOCAL session_replication_role = replica")
                cursor.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " CASCADE")
                raw = cursor.cursor
                for table in tables:
                    data = tar.extractfile(f"{table}.csv").read()
                    with raw.copy(f'COPY "{table}" FROM STDIN WITH (FORMAT csv, HEADER true)') as copy:
                        copy.write(data)
                cursor.execute(
                    """
                    SELECT format('SELECT setval(%L, COALESCE((SELECT MAX(%I) FROM %I), 1))',
                                  pg_get_serial_sequence(quote_ident(c.table_name), c.column_name),
                                  c.column_name, c.table_name)
                    FROM information_schema.columns c
                    WHERE c.table_schema = 'public'
                      AND pg_get_serial_sequence(quote_ident(c.table_name), c.column_name) IS NOT NULL
                    """
                )
                for (stmt,) in cursor.fetchall():
                    cursor.execute(stmt)
        self.stdout.write(self.style.SUCCESS(f"Restored {len(tables)} tables from {archive}"))
