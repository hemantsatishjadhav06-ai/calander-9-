"""Merged releases need an explicit immutable source manifest, not weakened receipts."""

import builtins
import hashlib
import json
import subprocess
from copy import deepcopy
from types import SimpleNamespace
from unittest import mock

import pytest

from tools import generate_release_source_manifest as generator
from tools import telegram_release_inspect as inspector


def fixture_manifest():
    return {
        "record_type": inspector.SOURCE_MANIFEST_TYPE,
        "schema_version": inspector.SOURCE_MANIFEST_VERSION,
        "reviewed_source_commit": "a" * 40,
        "reviewed_source_tree": "b" * 40,
        "source_anchors": {
            path: hashlib.sha256(path.encode()).hexdigest() for path in inspector.CURRENT_SOURCE_ANCHORS
        },
    }


def test_historical_v2_manifest_keeps_its_exact_anchor_contract():
    historical = fixture_manifest()
    historical["schema_version"] = 2
    historical["source_anchors"] = {
        path: hashlib.sha256(path.encode()).hexdigest() for path in inspector.V2_SOURCE_ANCHORS
    }
    assert inspector.validate_source_manifest(historical) is historical
    assert len(historical["source_anchors"]) == 16
    historical["source_anchors"]["apps/telegram/workflow_bridge.py"] = "a" * 64
    with pytest.raises(ValueError, match="runtime source anchors"):
        inspector.validate_source_manifest(historical)


@pytest.mark.django_db
def test_current_transport_schema_is_verified_from_actual_postgresql_metadata():
    from django.db import connection

    assert connection.vendor == "postgresql"
    columns = inspector.workflow_transport_columns(connection)
    assert set(columns) == set(inspector.WORKFLOW_TRANSPORT_COLUMNS)
    assert all(required <= columns[table] for table, required in inspector.WORKFLOW_TRANSPORT_COLUMNS.items())


def test_transport_metadata_ignores_unexpected_tables_and_reads_no_payload():
    db, cursor = metadata_connection(
        [("telegram_channel", "connection_id"), ("telegram_workflow_prompt", "snapshot"), ("private_table", "secret")]
    )
    columns = inspector.workflow_transport_columns(db)
    assert columns["telegram_channel"] == {"connection_id"}
    assert columns["telegram_workflow_prompt"] == {"snapshot"}
    assert columns["telegram_channel_delivery"] == set()
    sql, args = cursor.execute.call_args.args
    assert "information_schema.columns" in sql and "BASE TABLE" in sql
    assert args == list(inspector.WORKFLOW_TRANSPORT_COLUMNS)
    assert "SELECT *" not in sql


@pytest.fixture
def committed_source(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    for path in inspector.CURRENT_SOURCE_ANCHORS:
        file = project / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(f"# reviewed source for {path}\n")
    for args in (
        ["init", "-q"],
        ["config", "user.name", "Release fixture"],
        ["config", "user.email", "fixture@example.com"],
        ["add", "."],
        ["commit", "-q", "-m", "Reviewed fixture source"],
    ):
        subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True)
    commit = subprocess.check_output(["git", "-C", str(project), "rev-parse", "HEAD"]).decode().strip()
    return project, commit


def test_manifest_is_generated_from_immutable_git_blobs(committed_source):
    project, commit = committed_source
    manifest = generator.generate_source_manifest(project, commit)
    path = next(iter(inspector.SOURCE_ANCHORS))
    original_digest = manifest["source_anchors"][path]
    (project / path).write_text("# unreviewed working-tree edit\n")
    regenerated = generator.generate_source_manifest(project, commit)
    assert regenerated == manifest
    assert regenerated["source_anchors"][path] == original_digest
    assert not inspector.source_anchors_match(project, manifest["source_anchors"])


def test_source_commit_must_exist_and_identify_a_commit(committed_source):
    project, commit = committed_source
    with pytest.raises(ValueError):
        generator.generate_source_manifest(project, "f" * 40)
    tree = generator.git_read(project, "rev-parse", f"{commit}^{{tree}}").decode().strip()
    with pytest.raises(ValueError):
        generator.generate_source_manifest(project, tree)
    with pytest.raises(ValueError):
        generator.generate_source_manifest(project, "HEAD")


def test_generator_rejects_symlink_anchors(committed_source):
    project, _ = committed_source
    path = next(iter(inspector.SOURCE_ANCHORS))
    (project / path).unlink()
    (project / path).symlink_to("outside-review.py")
    subprocess.run(["git", "-C", str(project), "add", path], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "Symlink fixture"], check=True, capture_output=True)
    commit = subprocess.check_output(["git", "-C", str(project), "rev-parse", "HEAD"]).decode().strip()
    with pytest.raises(ValueError):
        generator.generate_source_manifest(project, commit)


@pytest.mark.parametrize(
    "change",
    [
        lambda data: data.update(schema_version=True),
        lambda data: data.update(schema_version=1),
        lambda data: data.update(schema_version=4),
        lambda data: data.update(record_type="another_receipt"),
        lambda data: data.update(reviewed_source_commit="short"),
        lambda data: data.update(reviewed_source_tree="B" * 40),
        lambda data: data.update(source_anchors={}),
        lambda data: data["source_anchors"].pop(next(iter(inspector.SOURCE_ANCHORS))),
        lambda data: data["source_anchors"].update({"../../private.env": "a" * 64}),
        lambda data: data["source_anchors"].update({next(iter(inspector.SOURCE_ANCHORS)): "not-a-sha256"}),
        lambda data: data.update(extra_field="secret-looking-value-must-not-be-logged"),
    ],
)
def test_invalid_or_incomplete_manifests_are_rejected(change):
    manifest = fixture_manifest()
    change(manifest)
    with pytest.raises(ValueError):
        inspector.validate_source_manifest(manifest)


def test_manifest_file_is_bound_to_its_receipt_digest(tmp_path):
    manifest = fixture_manifest()
    file = tmp_path / "source.json"
    raw = json.dumps(manifest, sort_keys=True).encode()
    file.write_bytes(raw)
    loaded, digest = inspector.read_source_manifest(file)
    assert loaded == manifest
    assert digest == hashlib.sha256(raw).hexdigest()
    file.write_bytes(b" " * (64 * 1024 + 1))
    with pytest.raises(ValueError):
        inspector.read_source_manifest(file)


def test_runtime_source_tampering_and_symlinks_are_rejected(committed_source):
    project, commit = committed_source
    manifest = generator.generate_source_manifest(project, commit)
    assert inspector.source_anchors_match(project, manifest["source_anchors"])
    path = next(iter(inspector.SOURCE_ANCHORS))
    original = (project / path).read_bytes()
    alternative = project / "outside.py"
    alternative.write_bytes(original)
    (project / path).unlink()
    (project / path).symlink_to(alternative)
    assert not inspector.source_anchors_match(project, manifest["source_anchors"])


@pytest.mark.parametrize("failure", ["source", "deployment_sha"])
def test_failed_source_gates_stop_before_importing_application(
    committed_source, tmp_path, monkeypatch, capsys, failure
):
    project, commit = committed_source
    manifest = generator.generate_source_manifest(project, commit)
    path = tmp_path / "release-source.json"
    path.write_text(json.dumps(manifest))
    if failure == "source":
        (project / next(iter(inspector.SOURCE_ANCHORS))).write_text("# different application code\n")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", commit if failure == "source" else "c" * 40)
    monkeypatch.setattr(
        "sys.argv", ["inspect", "--project", str(project), "--source-manifest", str(path), "--service", "local"]
    )
    imports = []
    original_import = builtins.__import__

    def inspect_import(name, *args, **kwargs):
        if name == "django":
            imports.append(name)
            raise AssertionError("Unverified source must not be imported")
        return original_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=inspect_import):
        assert inspector.main() == 2
    receipt = json.loads(capsys.readouterr().out)
    assert not imports
    assert receipt["source_manifest_origin"] == "explicit_manifest"
    assert receipt["reviewed_source_commit"] == commit
    assert receipt["expected_deployment_commit"] == commit
    assert receipt["blocked"] == 1
    assert len(receipt["checks"]) == 2
    assert not receipt["production_acceptance"]


@pytest.mark.parametrize(
    ("failure", "blocked_check"),
    [
        ("migration", "db.cumulative_migrations"),
        ("access", "db.oauth_plaintext_redacted"),
        ("refresh", "db.oauth_plaintext_redacted"),
        ("storage", "config.oauth_token_storage"),
        ("grace", "config.oauth_token_storage"),
        ("row_visibility", "db.oauth_token_row_visibility"),
        ("schema", "db.oauth_token_schema"),
    ],
)
def test_source_valid_current_receipt_requires_oauth_redaction(
    committed_source, tmp_path, monkeypatch, capsys, failure, blocked_check
):
    from contextlib import nullcontext

    from django.test import override_settings

    project, commit = committed_source
    manifest = generator.generate_source_manifest(project, commit)
    path = tmp_path / "current-source.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", commit)
    monkeypatch.setattr(
        "sys.argv", ["inspect", "--project", str(project), "--source-manifest", str(path), "--service", "local"]
    )
    db, cursor = metadata_connection([], [("on",)])
    db.vendor = "postgresql"
    applied = set(inspector.CURRENT_RELEASE_MIGRATIONS)
    if failure == "migration":
        applied.remove(("oauth_server", "0001_redact_token_plaintext"))
    recorder = mock.Mock()
    recorder.applied_migrations.return_value = applied
    executor = mock.Mock()
    executor.loader.graph.leaf_nodes.return_value = []
    executor.migration_plan.return_value = []
    evidence = {
        "schema_ready": failure != "schema",
        "row_visibility_complete": failure not in ("schema", "row_visibility"),
        "missing_columns": {"access": ["token"]} if failure == "schema" else {},
        "counts": {"access": int(failure == "access"), "refresh": int(failure == "refresh")},
    }
    if failure in ("schema", "row_visibility"):
        evidence["counts"] = None
    with (
        override_settings(
            DEBUG=False,
            SESSION_COOKIE_SECURE=True,
            CSRF_COOKIE_SECURE=True,
            SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
            STUDIO_PROVIDER="openrouter",
            OPENROUTER_API_KEY="fixture",
            TELEGRAM_WEBHOOK_BASE_URL=inspector.EXPECTED_ORIGIN,
            OAUTH2_PROVIDER={
                "COMPLIANT_BCP_RFC9700_TOKEN_STORAGE": failure != "storage",
                "REFRESH_TOKEN_GRACE_PERIOD_SECONDS": int(failure == "grace"),
            },
        ),
        mock.patch("django.db.connection", db),
        mock.patch("django.db.transaction.atomic", side_effect=lambda: nullcontext()),
        mock.patch("django.db.migrations.recorder.MigrationRecorder", return_value=recorder),
        mock.patch("django.db.migrations.executor.MigrationExecutor", return_value=executor),
        mock.patch(
            "tools.telegram_release_inspect.managed_reservation_columns",
            return_value=inspector.MANAGED_RESERVATION_COLUMNS,
        ),
        mock.patch("tools.telegram_release_inspect.oauth_token_storage_evidence", return_value=evidence),
        mock.patch(
            "tools.telegram_release_inspect.workflow_transport_columns",
            return_value=inspector.WORKFLOW_TRANSPORT_COLUMNS,
        ),
        mock.patch(
            "apps.workspaces.models.Workspace.objects.filter", side_effect=AssertionError("Fail before workspace ORM")
        ),
    ):
        assert inspector.main() == 2
    receipt = json.loads(capsys.readouterr().out)
    checks = {row["check"]: row for row in receipt["checks"]}
    assert receipt["source_manifest_schema_version"] == inspector.SOURCE_MANIFEST_VERSION
    assert receipt["oauth_token_storage_required"]
    assert checks["source.anchor_files"]["result"] == "PASS"
    assert checks["source.railway_commit"]["result"] == "PASS"
    assert checks["db.enforced_read_only"]["result"] == "PASS"
    assert checks[blocked_check]["result"] == "BLOCKED"
    assert "workspace.current" not in checks and "inspection.exception" not in checks
    if failure == "migration":
        assert checks["db.cumulative_migrations"]["missing"] == ["oauth_server.0001_redact_token_plaintext"]
    assert ("oauth_server", "0001_redact_token_plaintext") not in inspector.REQUIRED_MIGRATIONS
    assert "SET TRANSACTION READ ONLY" in [call.args[0] for call in cursor.execute.call_args_list]
    assert not receipt["database_writes"] and not receipt["external_calls"]


@pytest.mark.django_db(transaction=True)
def test_actual_postgresql_counts_expired_and_revoked_plaintext_without_loading_credentials():
    import secrets
    from datetime import timedelta

    from django.db import connection, transaction
    from django.test.utils import CaptureQueriesContext
    from django.utils import timezone
    from oauth2_provider.models import AccessToken, Application, RefreshToken

    from apps.accounts.models import User

    assert connection.vendor == "postgresql"
    assert connection.settings_dict["NAME"].startswith("test_")
    user = User.objects.create_user(email="token-inspector@example.test", tos_accepted_at=timezone.now())
    application = Application.objects.create(
        name="Synthetic release inspector",
        client_type=Application.CLIENT_PUBLIC,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris="https://example.test/callback",
    )
    access = AccessToken.objects.create(
        user=user,
        application=application,
        token=secrets.token_urlsafe(32),
        scope="mcp",
        expires=timezone.now() - timedelta(days=1),
    )
    RefreshToken.objects.create(
        user=user,
        application=application,
        access_token=access,
        token=secrets.token_urlsafe(32),
        revoked=timezone.now() - timedelta(days=1),
    )
    for expected in ({"access": 1, "refresh": 1}, {"access": 0, "refresh": 0}):
        with transaction.atomic(), CaptureQueriesContext(connection) as captured:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
            evidence = inspector.oauth_token_storage_evidence(connection)
        assert evidence["schema_ready"] and evidence["row_visibility_complete"]
        assert evidence["counts"] == expected
        token_table_reads = [row["sql"] for row in captured if 'FROM "public"."oauth2_provider_' in row["sql"]]
        assert len(token_table_reads) == 2
        assert all(row.startswith("SELECT COUNT(*)") for row in token_table_reads)
        if expected["access"]:
            AccessToken.objects.update(token="")
            RefreshToken.objects.update(token="")


def test_current_manifest_rejects_historical_version_and_anchor_set():
    historical = fixture_manifest()
    historical["schema_version"] = 1
    historical["source_anchors"] = deepcopy(inspector.SOURCE_ANCHORS)
    with pytest.raises(ValueError, match="schema version"):
        inspector.validate_source_manifest(historical)
    historical["schema_version"] = inspector.SOURCE_MANIFEST_VERSION
    with pytest.raises(ValueError, match="runtime source anchors"):
        inspector.validate_source_manifest(historical)


@pytest.mark.parametrize("path", sorted(set(inspector.CURRENT_SOURCE_ANCHORS) - set(inspector.SOURCE_ANCHORS)))
def test_current_manifest_detects_security_source_tampering(committed_source, path):
    project, commit = committed_source
    manifest = generator.generate_source_manifest(project, commit)
    assert len(manifest["source_anchors"]) == len(inspector.CURRENT_SOURCE_ANCHORS)
    assert inspector.source_anchors_match(project, manifest["source_anchors"])
    (project / path).write_text("# changed security or managed-bot source\n")
    assert not inspector.source_anchors_match(project, manifest["source_anchors"])


def test_generator_requires_committed_oauth_migration(committed_source):
    project, _commit = committed_source
    path = "apps/oauth_server/migrations/0001_redact_token_plaintext.py"
    (project / path).unlink()
    subprocess.run(["git", "-C", str(project), "add", path], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(project), "commit", "-qm", "Incomplete release fixture"], check=True, capture_output=True
    )
    commit = subprocess.check_output(["git", "-C", str(project), "rev-parse", "HEAD"]).decode().strip()
    with pytest.raises(ValueError, match="missing a regular runtime anchor"):
        generator.generate_source_manifest(project, commit)


def test_historical_mode_cannot_certify_a_new_deployment_sha(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["inspect", "--expected-deployment-commit", "c" * 40, "--service", "local"])
    with pytest.raises(SystemExit) as error:
        inspector.main()
    assert error.value.code == 2
    assert "requires a current --source-manifest" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("storage", "grace", "expected"),
    [
        (True, 0, True),
        (False, 0, False),
        (1, 0, False),
        ("true", 0, False),
        (True, False, False),
        (True, 0.0, False),
        (True, 1, False),
        (True, "0", False),
    ],
)
def test_oauth_storage_settings_require_exact_safe_values(storage, grace, expected):
    config = SimpleNamespace(
        COMPLIANT_BCP_RFC9700_TOKEN_STORAGE=storage,
        REFRESH_TOKEN_GRACE_PERIOD_SECONDS=grace,
    )
    assert inspector.oauth_storage_config_ready(config) is expected


def oauth_metadata_rows():
    return [
        (table, column, "BASE TABLE")
        for table in inspector.OAUTH_TOKEN_TABLES.values()
        for column in ("token", "token_checksum")
    ]


def metadata_connection(rows, responses=()):
    cursor = mock.MagicMock()
    cursor.fetchall.return_value = rows
    cursor.fetchone.side_effect = responses
    db = mock.Mock()
    db.cursor.return_value.__enter__ = mock.Mock(return_value=cursor)
    db.cursor.return_value.__exit__ = mock.Mock(return_value=False)
    return db, cursor


@pytest.mark.parametrize("failure", ["missing_table", "missing_token", "missing_checksum", "view"])
def test_oauth_plaintext_counts_require_real_complete_token_tables(failure):
    rows = oauth_metadata_rows()
    access = inspector.OAUTH_TOKEN_TABLES["access"]
    if failure == "missing_table":
        rows = [row for row in rows if row[0] != access]
    elif failure == "view":
        rows = [(table, column, "VIEW" if table == access else kind) for table, column, kind in rows]
    else:
        absent = "token" if failure == "missing_token" else "token_checksum"
        rows = [row for row in rows if row[:2] != (access, absent)]
    db, cursor = metadata_connection(rows)
    evidence = inspector.oauth_token_storage_evidence(db)
    assert not evidence["schema_ready"]
    assert evidence["counts"] is None
    assert evidence["missing_columns"]["access"]
    assert len(cursor.execute.call_args_list) == 1


@pytest.mark.parametrize("policies", [(True, False), (False, True)])
def test_oauth_counts_cannot_hide_plaintext_behind_row_policies(policies):
    db, cursor = metadata_connection(oauth_metadata_rows(), [policies])
    evidence = inspector.oauth_token_storage_evidence(db)
    assert evidence["schema_ready"]
    assert not evidence["row_visibility_complete"]
    assert evidence["counts"] is None
    assert not any("COUNT" in call.args[0] for call in cursor.execute.call_args_list)


@pytest.mark.parametrize("counts", [(0, 0), (2, 0), (0, 3), (2, 3)])
def test_oauth_inspection_returns_counts_and_never_token_values(counts):
    db, cursor = metadata_connection(oauth_metadata_rows(), [(False, False), (counts[0],), (counts[1],)])
    evidence = inspector.oauth_token_storage_evidence(db)
    assert evidence["schema_ready"] and evidence["row_visibility_complete"]
    assert evidence["counts"] == dict(zip(("access", "refresh"), counts, strict=True))
    statements = [call for call in cursor.execute.call_args_list if "COUNT" in call.args[0]]
    assert len(statements) == 2
    for statement in statements:
        assert statement.args[0].startswith('SELECT COUNT(*) FROM "public".')
        assert 'WHERE "token" IS DISTINCT FROM %s' in statement.args[0]
        assert statement.args[1] == [""]
        assert "expires" not in statement.args[0] and "revoked" not in statement.args[0]


def test_generator_preserves_existing_artifacts(committed_source, tmp_path, monkeypatch, capsys):
    project, commit = committed_source
    path = tmp_path / "existing.json"
    path.write_text("historical receipt")
    monkeypatch.setattr(
        "sys.argv", ["generate", "--project", str(project), "--source-commit", commit, "--output", str(path)]
    )
    with pytest.raises(SystemExit) as error:
        generator.main()
    assert error.value.code == 2
    assert path.read_text() == "historical receipt"
    assert "Cannot generate manifest" in capsys.readouterr().err


def test_invalid_manifest_never_echoes_contents(tmp_path, monkeypatch, capsys):
    path = tmp_path / "source.json"
    manifest = fixture_manifest()
    manifest["unexpected_secret"] = "must-not-appear-in-output"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr("sys.argv", ["inspect", "--source-manifest", str(path), "--service", "local"])
    with pytest.raises(SystemExit) as error:
        inspector.main()
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "must-not-appear-in-output" not in captured.err + captured.out


def test_legacy_receipt_keeps_original_commit_and_embedded_anchors(monkeypatch, tmp_path, capsys):
    original = deepcopy(inspector.SOURCE_ANCHORS)
    monkeypatch.setattr("sys.argv", ["inspect", "--project", str(tmp_path), "--service", "local"])
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    assert inspector.main() == 2
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["reviewed_source_commit"] == "6cb392ff35494a0cb3172c95e654663cfe6dfce9"
    assert receipt["expected_deployment_commit"] == receipt["reviewed_source_commit"]
    assert receipt["source_manifest_origin"] == "embedded_historical"
    assert receipt["source_manifest_sha256"] is None
    assert original == inspector.SOURCE_ANCHORS
    assert len(original) == 9


@pytest.mark.parametrize("sha", ["", "HEAD", "A" * 40])
def test_explicit_deployment_sha_must_be_complete_lowercase(sha, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["inspect", "--expected-deployment-commit", sha, "--service", "local"])
    with pytest.raises(SystemExit) as error:
        inspector.main()
    assert error.value.code == 2
    assert "full lowercase Git SHA" in capsys.readouterr().err


def test_verified_merge_sha_is_separate_from_reviewed_source(committed_source, tmp_path, monkeypatch, capsys):
    project, commit = committed_source
    manifest = generator.generate_source_manifest(project, commit)
    path = tmp_path / "source.json"
    path.write_text(json.dumps(manifest))
    merge_sha = "c" * 40
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", merge_sha)
    monkeypatch.setattr(
        "sys.argv",
        [
            "inspect",
            "--project",
            str(project),
            "--source-manifest",
            str(path),
            "--expected-deployment-commit",
            merge_sha,
            "--service",
            "local",
        ],
    )
    original_import = builtins.__import__
    application = mock.Mock()
    application.setup.side_effect = RuntimeError("Controlled test: no application or database inspection")

    def inspect_import(name, *args, **kwargs):
        return application if name == "django" else original_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=inspect_import):
        assert inspector.main() == 2
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["reviewed_source_commit"] == commit
    assert receipt["expected_deployment_commit"] == merge_sha
    assert receipt["source_manifest_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert {check["result"] for check in receipt["checks"][:2]} == {"PASS"}
    application.setup.assert_called_once()
    assert receipt["checks"][-1]["check"] == "inspection.exception"
    assert not receipt["production_acceptance"]


@pytest.mark.parametrize("scenario", ["unapplied", "missing_table", "partial_table"])
def test_source_valid_current_receipt_requires_managed_bot_migration_and_schema(
    committed_source, tmp_path, monkeypatch, capsys, scenario
):
    from contextlib import nullcontext

    from django.test import override_settings

    project, commit = committed_source
    manifest = generator.generate_source_manifest(project, commit)
    path = tmp_path / "current-source.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", commit)
    monkeypatch.setattr(
        "sys.argv", ["inspect", "--project", str(project), "--source-manifest", str(path), "--service", "local"]
    )
    cursor = mock.MagicMock()
    cursor.fetchone.return_value = ("on",)
    cursor.fetchall.return_value = [("id",)] if scenario == "partial_table" else []
    db = mock.Mock(vendor="postgresql")
    db.cursor.return_value.__enter__ = mock.Mock(return_value=cursor)
    db.cursor.return_value.__exit__ = mock.Mock(return_value=False)
    applied = set(inspector.CURRENT_RELEASE_MIGRATIONS)
    if scenario == "unapplied":
        applied.remove(("telegram", "0002_telegrammanagedbotreservation"))
    recorder = mock.Mock()
    recorder.applied_migrations.return_value = applied
    executor = mock.Mock()
    executor.loader.graph.leaf_nodes.return_value = []
    executor.migration_plan.return_value = []
    with (
        override_settings(
            DEBUG=False,
            SESSION_COOKIE_SECURE=True,
            CSRF_COOKIE_SECURE=True,
            SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
            STUDIO_PROVIDER="openrouter",
            OPENROUTER_API_KEY="fixture",
            TELEGRAM_WEBHOOK_BASE_URL=inspector.EXPECTED_ORIGIN,
        ),
        mock.patch("django.db.connection", db),
        mock.patch("django.db.transaction.atomic", side_effect=lambda: nullcontext()),
        mock.patch("django.db.migrations.recorder.MigrationRecorder", return_value=recorder),
        mock.patch("django.db.migrations.executor.MigrationExecutor", return_value=executor),
        mock.patch(
            "tools.telegram_release_inspect.oauth_token_storage_evidence",
            return_value={
                "schema_ready": True,
                "row_visibility_complete": True,
                "missing_columns": {},
                "counts": {"access": 0, "refresh": 0},
            },
        ),
    ):
        assert inspector.main() == 2
    receipt = json.loads(capsys.readouterr().out)
    checks = {row["check"]: row for row in receipt["checks"]}
    assert receipt["managed_bot_schema_required"]
    assert checks["source.anchor_files"]["result"] == "PASS"
    assert checks["source.railway_commit"]["result"] == "PASS"
    assert checks["db.enforced_read_only"]["result"] == "PASS"
    assert checks["db.no_pending_migrations"]["result"] == "PASS"
    assert checks["db.managed_bot_schema"]["result"] == "BLOCKED"
    assert checks["db.managed_bot_schema"]["table_present"] == (scenario == "partial_table")
    assert "workspace_id" in checks["db.managed_bot_schema"]["missing_columns"]
    if scenario == "unapplied":
        assert checks["db.cumulative_migrations"]["result"] == "BLOCKED"
        assert checks["db.cumulative_migrations"]["missing"] == ["telegram.0002_telegrammanagedbotreservation"]
    else:
        assert checks["db.cumulative_migrations"]["result"] == "PASS"
    assert "workspace.current" not in checks
    sql = [call.args[0] for call in cursor.execute.call_args_list]
    assert "SET TRANSACTION READ ONLY" in sql
    assert any("information_schema.columns" in query for query in sql)
    assert ("telegram", "0002_telegrammanagedbotreservation") not in inspector.REQUIRED_MIGRATIONS
    assert not receipt["production_acceptance"]
