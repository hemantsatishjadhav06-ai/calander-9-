"""Upgrade legacy mapped/orphaned private histories without breaking old inserts."""

import uuid

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_private_history_backfill_and_previous_release_insert_compatibility():
    previous = [
        ("studio", "0004_agencysettings_backup_studiobrief_trust_snapshot_and_more"),
        ("telegram", "0001_initial"),
    ]
    target = [("studio", "0005_private_transport_history")]
    executor = MigrationExecutor(connection)
    final = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate(previous)
        state = executor.loader.project_state(previous).apps
        org = state.get_model("organizations", "Organization").objects.create(name="Legacy privacy upgrade")
        workspace = state.get_model("workspaces", "Workspace").objects.create(organization=org, name="Legacy client")
        legacy = state.get_model("studio", "Conversation")
        mapped = legacy.objects.create(workspace=workspace, audience="internal", title="Arbitrary private title")
        orphan = legacy.objects.create(workspace=workspace, audience="client", title="Telegram private conversation")
        shared = legacy.objects.create(workspace=workspace, audience="internal", title="Ask the team")
        bot = state.get_model("telegram", "TelegramConnection").objects.create(
            workspace=workspace,
            bot_id=7654321,
            bot_username="fixture_bot",
            token="invented",
            webhook_secret="invented",
        )
        state.get_model("telegram", "TelegramChat").objects.create(
            connection=bot,
            chat_id=123456,
            chat_type="private",
            audience="private",
            conversation=mapped,
        )
        executor = MigrationExecutor(connection)
        executor.migrate(target)
        upgraded = executor.loader.project_state(target).apps.get_model("studio", "Conversation")
        assert upgraded.objects.get(pk=mapped.pk).is_private
        assert upgraded.objects.get(pk=orphan.pk).is_private
        assert not upgraded.objects.get(pk=shared.pk).is_private
        # The previous release omits the new column; db_default allows its
        # normal shared insert while the rolling deployment drains that code.
        old_writer = legacy.objects.create(
            id=uuid.uuid4(), workspace=workspace, audience="internal", title="Old writer"
        )
        assert not upgraded.objects.get(pk=old_writer.pk).is_private
    finally:
        MigrationExecutor(connection).migrate(final)
