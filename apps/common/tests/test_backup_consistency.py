"""A release backup remains consistent while the application accepts writes."""

import io
import json
import tarfile

import psycopg
import pytest
from django.core.management import call_command
from django.db import connection
from django.utils import timezone

from apps.accounts.models import User


@pytest.mark.django_db(transaction=True)
def test_backup_uses_one_snapshot_during_concurrent_writes(tmp_path, settings, monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("The backup command uses PostgreSQL COPY and snapshot isolation.")

    settings.MEDIA_ROOT = str(tmp_path)
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE z_backup_snapshot_probe (id integer PRIMARY KEY)")
        cursor.execute("INSERT INTO z_backup_snapshot_probe VALUES (1)")

    original_addfile = tarfile.TarFile.addfile
    inserted = False

    def addfile(tar, info, fileobj=None):
        nonlocal inserted
        if info.name == "accounts_user.csv" and not inserted:
            # Another application connection commits after the dump begins.
            with psycopg.connect(**connection.get_connection_params()) as writer:
                writer.execute("INSERT INTO z_backup_snapshot_probe VALUES (2)")
            inserted = True
        return original_addfile(tar, info, fileobj)

    monkeypatch.setattr(tarfile.TarFile, "addfile", addfile)
    try:
        call_command("backup_database", required=True, stdout=io.StringIO())
        assert inserted
        (archive,) = (tmp_path / "backups").iterdir()
        with tarfile.open(archive, "r:gz") as tar:
            manifest = json.load(tar.extractfile("manifest.json"))
            assert manifest["tables"]["z_backup_snapshot_probe"] == 1
            assert tar.extractfile("z_backup_snapshot_probe.csv").read() == b"id\n1\n"
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM z_backup_snapshot_probe")
            assert cursor.fetchone()[0] == 2
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE z_backup_snapshot_probe")


@pytest.mark.django_db(transaction=True)
def test_backup_restore_round_trip_preserves_application_rows(tmp_path, settings):
    if connection.vendor != "postgresql":
        pytest.skip("The backup and restore commands require PostgreSQL.")
    with connection.cursor() as cursor:
        cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        if not cursor.fetchone()[0]:
            pytest.skip("Restore requires a role allowed to disable foreign-key triggers.")
    settings.MEDIA_ROOT = str(tmp_path)
    user = User.objects.create_user(
        email="restore-probe@example.com", name="Before backup", tos_accepted_at=timezone.now()
    )
    call_command("backup_database", required=True, stdout=io.StringIO())
    (archive,) = (tmp_path / "backups").iterdir()
    User.objects.filter(pk=user.pk).update(name="After backup")
    call_command("restore_database", str(archive), yes_wipe_data=True, stdout=io.StringIO())
    user.refresh_from_db()
    assert user.name == "Before backup"
    assert User.objects.filter(email="restore-probe@example.com").count() == 1
