#!/usr/bin/env python3
"""Read-only release receipt. Run with the deployed app's Python and settings.

No HTTP/model/social calls, no migration execution, no token decryption, no
worker lease acquisition and no writes. PostgreSQL enforces a read-only
transaction. Exit 0 means this limited inspection passed, never a live pilot.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

EXPECTED_COMMIT = "6cb392ff35494a0cb3172c95e654663cfe6dfce9"
DEFAULT_WORKSPACE = "b1cb458c-cfaf-43cf-8e23-f5e18a9717c7"
EXPECTED_ORIGIN = "https://sm-bean-production-eb50.up.railway.app"
# Historical reviewed release. Retained unchanged for its existing receipts.
# A merged release uses --source-manifest generated from its tested Git commit.
# Anchors supplement, not replace, Railway SHA.
SOURCE_ANCHORS = {
    "apps/common/background.py": "0175fbf8495b1032a39d7c431e85e4405a5e1cde0577f897b3dd2ba1e68f0ef9",
    "apps/common/management/commands/run_worker.py": "684bed02ac6619726eed6a7b84bc1e46bd250502bd166fdfbe0fc3f3fa766914",
    "apps/common/management/commands/release.py": "47bd12bc3834dd311e1cfeaa490607f3d1db5d51925c20cb293fd323f8a48c65",
    "apps/studio/migrations/0005_private_transport_history.py": "d5836c8f0ed9746be19962943d6bac500680996b9a1c1c2ffc00eb9ebab8e0e3",
    "apps/telegram/migrations/0001_initial.py": "5481a1d9cbeaa7fbde3721914739192242ba4abc7cd22136b2fa6b0cf0b80613",
    "apps/telegram/tasks.py": "6ce9de5605c77ece343a2ab303d267268c75eed4035c0f396c021f8493ff46de",
    "apps/telegram/weekly.py": "1b22360aba240a7d17f72506124dea625ae5aefeb55769c565f1fc431a113257",
    "apps/telegram/outbox.py": "16194bfa6248040462070aa7f0a2140f737c2464c64ae44bdf8c16161e1f4191",
    "apps/telegram/views.py": "eb02932f8af28af28be30d1961efc6810856dd0a6d8c2e276e7dd49a8fb64c4d",
}
SOURCE_MANIFEST_VERSION = 1
SOURCE_MANIFEST_TYPE = "sm_bean_release_source_manifest"
REQUIRED_MIGRATIONS = [
    ("approvals", "0005_alter_approvalaction_action"),
    ("common", "0003_taskheartbeat"),
    ("composer", "0024_post_delivery_holds"),
    ("media_library", "0006_mediaasset_authenticity_mediaasset_verified_at_and_more"),
    ("media_library", "0007_mediaasset_verified_asset_hash"),
    ("studio", "0004_agencysettings_backup_studiobrief_trust_snapshot_and_more"),
    ("studio", "0005_private_transport_history"),
    ("telegram", "0001_initial"),
]
CURRENT_RELEASE_MIGRATIONS = [*REQUIRED_MIGRATIONS, ("telegram", "0002_telegrammanagedbotreservation")]
MANAGED_RESERVATION_COLUMNS = {
    "id",
    "workspace_id",
    "manager_id",
    "user_link_id",
    "requested_by_id",
    "telegram_owner_id",
    "manager_bot_id",
    "manager_epoch",
    "pairing_epoch",
    "requested_username",
    "requested_name",
    "status",
    "bot_id",
    "expires_at",
    "used_at",
    "completed_at",
    "error",
    "created_at",
}


def validate_source_manifest(data: Any) -> dict:
    """Reject incomplete manifests and any path outside the known source anchors."""
    fields = {"record_type", "schema_version", "reviewed_source_commit", "reviewed_source_tree", "source_anchors"}
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("Source manifest must contain the complete versioned schema")
    if data["record_type"] != SOURCE_MANIFEST_TYPE:
        raise ValueError("Source manifest record type is invalid")
    if type(data["schema_version"]) is not int or data["schema_version"] != SOURCE_MANIFEST_VERSION:
        raise ValueError("Source manifest schema version is unsupported")
    for field in ("reviewed_source_commit", "reviewed_source_tree"):
        if not isinstance(data[field], str) or not re.fullmatch(r"[0-9a-f]{40}", data[field]):
            raise ValueError("Source manifest must name a full lowercase Git commit and tree SHA")
    anchors = data["source_anchors"]
    if not isinstance(anchors, dict) or set(anchors) != set(SOURCE_ANCHORS):
        raise ValueError("Source manifest must cover exactly the required runtime source anchors")
    if any(not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in anchors.values()):
        raise ValueError("Source manifest must contain full lowercase SHA-256 digests")
    return data


def read_source_manifest(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    if len(raw) > 64 * 1024:
        raise ValueError("Source manifest exceeds its size limit")
    data = json.loads(raw)
    return validate_source_manifest(data), hashlib.sha256(raw).hexdigest()


def source_anchors_match(root: Path, anchors: dict[str, str]) -> bool:
    """Do not import application code until its reviewed source is verified."""
    for file, digest in anchors.items():
        candidate = root / file
        if not candidate.is_file() or candidate.is_symlink():
            return False
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
            return False
    return True


def managed_reservation_columns(db_connection: Any) -> set[str]:
    """Inspect metadata only; never query an absent management model table."""
    with db_connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' "
            "AND table_name='telegram_managed_bot_reservation'"
        )
        return {row[0] for row in cursor.fetchall()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    parser.add_argument(
        "--source-manifest",
        type=Path,
        help="Versioned source manifest generated from the final reviewed/tested Git commit; omission selects historical 6cb392f.",
    )
    parser.add_argument(
        "--expected-deployment-commit",
        help="Full verified deployment SHA; defaults to the manifest's reviewed source SHA, or historical 6cb392f.",
    )
    parser.add_argument("--stage", choices=("schema", "runtime"), default="schema")
    parser.add_argument("--service", choices=("sm-bean", "sm-bean-worker", "local"), required=True)
    args = parser.parse_args()
    reviewed_commit = EXPECTED_COMMIT
    reviewed_tree = None
    manifest_sha256 = None
    anchors = SOURCE_ANCHORS
    if args.source_manifest:
        try:
            manifest, manifest_sha256 = read_source_manifest(args.source_manifest)
        except (OSError, ValueError):
            parser.error("--source-manifest must be a readable, valid release source manifest")
        reviewed_commit = manifest["reviewed_source_commit"]
        reviewed_tree = manifest["reviewed_source_tree"]
        anchors = manifest["source_anchors"]
    if args.expected_deployment_commit is None:
        args.expected_deployment_commit = reviewed_commit
    try:
        UUID(args.workspace)
    except ValueError:
        parser.error("--workspace must be a valid workspace UUID")
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_deployment_commit):
        parser.error("--expected-deployment-commit must be a full lowercase Git SHA")
    report = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "service": args.service,
        "stage": args.stage,
        "reviewed_source_commit": reviewed_commit,
        "reviewed_source_tree": reviewed_tree,
        "source_manifest_sha256": manifest_sha256,
        "source_manifest_origin": "explicit_manifest" if args.source_manifest else "embedded_historical",
        "managed_bot_schema_required": bool(args.source_manifest),
        "expected_deployment_commit": args.expected_deployment_commit,
        "workspace_id": args.workspace,
        "target_week_start": "2026-10-19",
        "target_week_end": "2026-10-25",
        "production_acceptance": False,
        "external_calls": False,
        "database_writes": False,
        "checks": [],
        "limits": [
            "Provider presence is saved configuration, not balance, permissions or successful calls.",
            "A stored bot status does not independently verify Telegram's actual webhook.",
            "Lease inspection cannot detect an old baseline worker that never acquired the lease.",
            "Pairing counts do not certify human roles or all passive group viewers.",
            "Native publication, useful graphics and human approval require a separate live pilot.",
            "Both service receipts and Railway reference configuration must be compared by an operator.",
        ],
    }

    def check(name, ok, **detail):
        report["checks"].append({"check": name, "result": "PASS" if ok else "BLOCKED", **detail})

    def finish():
        report["blocked"] = sum(c["result"] == "BLOCKED" for c in report["checks"])
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2 if report["blocked"] else 0

    root = args.project.resolve()
    try:
        anchors_ok = source_anchors_match(root, anchors)
    except OSError:
        anchors_ok = False
    check(
        "source.anchor_files",
        anchors_ok,
        anchor_count=len(anchors),
    )
    observed = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")
    check(
        "source.railway_commit",
        observed == args.expected_deployment_commit,
        observed_commit=observed if re.fullmatch(r"[0-9a-f]{40}", observed) else None,
    )
    if not anchors_ok or observed != args.expected_deployment_commit:
        return finish()
    sys.path.insert(0, str(root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
    try:
        # Never echo setup errors, environment values or credential-bearing URLs.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import django

            django.setup()
        from background_task.models import Task
        from django.conf import settings
        from django.core.exceptions import PermissionDenied
        from django.db import connection, transaction
        from django.db.migrations.executor import MigrationExecutor
        from django.db.migrations.recorder import MigrationRecorder
        from django.utils import timezone as django_timezone

        from apps.approvals.actor import is_internal_approver
        from apps.common.background import _advisory_lock_key, task_health
        from apps.common.models import TaskHeartbeat
        from apps.media_library.models import MediaAsset
        from apps.social_accounts.models import SocialAccount
        from apps.studio import budget, llm, memory, trust
        from apps.studio.forms import STUDIO_PLATFORMS
        from apps.studio.jobtypes.plan import valid_lead
        from apps.studio.models import AgencySettings, AgentRun, BrandProfile
        from apps.telegram.models import TelegramChat, TelegramConnection, TelegramDelivery, TelegramUserLink
        from apps.telegram.permissions import current_member, internal_member
        from apps.workspaces.models import Workspace

        check(
            "config.production_security",
            not settings.DEBUG
            and bool(settings.SESSION_COOKIE_SECURE)
            and bool(settings.CSRF_COOKIE_SECURE)
            and bool(settings.SECURE_PROXY_SSL_HEADER),
        )
        check(
            "config.encryption_present",
            bool(settings.SECRET_KEY) and bool(getattr(settings, "ENCRYPTION_KEY_SALT", None)),
        )
        check("config.openrouter_saved", llm.provider_name() == "openrouter" and llm.is_configured())
        report["checks"].append(
            {
                "check": "config.graphics_key_saved",
                "result": "INFO",
                "configured": bool(getattr(settings, "FAL_KEY", "")),
                "detail": "Check real image credits/access or authentic-photo fallback separately.",
            }
        )
        origin = urlsplit(getattr(settings, "TELEGRAM_WEBHOOK_BASE_URL", ""))
        check(
            "config.telegram_origin",
            origin.scheme == "https"
            and origin.netloc == urlsplit(EXPECTED_ORIGIN).netloc
            and not origin.username
            and not origin.password
            and origin.path in ("", "/")
            and not origin.query
            and not origin.fragment,
        )
        check("db.postgresql", connection.vendor == "postgresql")
        if connection.vendor != "postgresql":
            return finish()
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cursor.execute("SET LOCAL statement_timeout = '10000ms'")
                cursor.execute("SHOW transaction_read_only")
                check("db.enforced_read_only", cursor.fetchone()[0] == "on")
            applied = MigrationRecorder(connection).applied_migrations()
            required = CURRENT_RELEASE_MIGRATIONS if args.source_manifest else REQUIRED_MIGRATIONS
            missing = [f"{app}.{name}" for app, name in required if (app, name) not in applied]
            check("db.cumulative_migrations", not missing, missing=missing)
            executor = MigrationExecutor(connection)
            pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
            check("db.no_pending_migrations", not pending, pending_count=len(pending))
            managed_schema_ok = True
            if args.source_manifest:
                columns = managed_reservation_columns(connection)
                absent_columns = sorted(MANAGED_RESERVATION_COLUMNS - columns)
                managed_schema_ok = not absent_columns
                check(
                    "db.managed_bot_schema",
                    managed_schema_ok,
                    table_present=bool(columns),
                    missing_columns=absent_columns,
                )
            if missing or pending or not managed_schema_ok:
                return finish()
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
                    "AND table_name='studio_conversation' AND column_name='is_private')"
                )
                check("db.private_marker", bool(cursor.fetchone()[0]))
            workspace = Workspace.objects.filter(
                pk=args.workspace,
                is_archived=False,
                organization__deletion_requested_at__isnull=True,
                organization__deleted_at__isnull=True,
            ).first()
            check("workspace.current", workspace is not None)
            if workspace:
                check("workspace.human_approval", workspace.require_dashboard_approval)
                if args.stage == "runtime":
                    check("workspace.timezone_ist", workspace.effective_timezone in ("Asia/Kolkata", "Asia/Calcutta"))
                    profile = BrandProfile.objects.filter(workspace=workspace).first()
                    check("workspace.brand_profile", profile is not None)
                    check("workspace.website_saved", bool(profile and profile.website))
                    config = AgencySettings.objects.filter(workspace=workspace).select_related("lead", "backup").first()
                    check(
                        "workspace.recurring_plan_saved",
                        bool(
                            config
                            and config.autopilot_enabled
                            and config.lead_id
                            and config.backup_id
                            and config.lead_id != config.backup_id
                            and config.pillars
                            and 1 <= config.posts_per_week <= 14
                            and config.accounts.exists()
                            and config.monthly_budget_usd > 0
                        ),
                    )

                    def current_approver(person):
                        if person is None or not is_internal_approver(person, workspace):
                            return False
                        try:
                            return internal_member(current_member(workspace, person))
                        except PermissionDenied:
                            return False

                    if config:
                        lead, _reason = valid_lead(config, workspace)
                        check("workspace.permitted_lead", lead is not None and current_approver(lead))
                        check(
                            "workspace.permitted_backup",
                            bool(
                                config.backup_id
                                and config.backup_id != config.lead_id
                                and current_approver(config.backup)
                            ),
                        )
                        accounts = list(
                            config.accounts.filter(workspace=workspace, platform__in=STUDIO_PLATFORMS)
                            .exclude(
                                connection_status__in=(
                                    SocialAccount.ConnectionStatus.DISCONNECTED,
                                    SocialAccount.ConnectionStatus.ERROR,
                                )
                            )
                            .only("id", "workspace_id", "platform", "connection_status", "account_platform_id")[:15]
                        )
                        check(
                            "workspace.selected_destinations",
                            bool(accounts)
                            and len(accounts) <= 14
                            and all(account.account_platform_id for account in accounts),
                            selected_count=len(accounts),
                        )
                        budget_now = django_timezone.now()
                        budget_rows = list(
                            AgentRun.objects.filter(
                                workspace=workspace,
                                started_at__gte=budget.month_start(workspace, budget_now),
                                started_at__lte=budget_now,
                            ).values_list("pk", flat=True)[:1001]
                        )
                        within_budget_inspection_limit = len(budget_rows) <= 1000
                        check(
                            "workspace.budget_inspection_bounded",
                            within_budget_inspection_limit,
                            inspected_count=len(budget_rows),
                            inspection_limit=1000,
                        )
                        check(
                            "workspace.soft_budget_available",
                            within_budget_inspection_limit and budget.can_spend(workspace),
                        )
                        check("workspace.reference_learning_enabled", config.learn_from_best)
                    claims = trust.current_claims(workspace)
                    week_end = date(2026, 10, 19) + timedelta(days=6)
                    eligible_claims = claims.filter(valid_until__gte=week_end)
                    check(
                        "workspace.claims_through_week",
                        eligible_claims.exists(),
                        current_count=claims.count(),
                        valid_through_week_count=eligible_claims.count(),
                        expire_before_week_end_count=claims.filter(valid_until__lt=week_end).count(),
                    )
                    check("workspace.current_contact_claim", eligible_claims.filter(category="contact").exists())
                    check("workspace.designer_references", bool(memory.references(workspace, limit=1)))
                    candidates = list(
                        MediaAsset.objects.filter(
                            workspace=workspace,
                            organization=workspace.organization,
                            media_type="image",
                            authenticity="verified",
                        ).values_list("id", flat=True)[:100]
                    )
                    report["checks"].append(
                        {
                            "check": "workspace.authentic_photo_candidates",
                            "result": "INFO",
                            "stored_verified_candidates_count": len(candidates),
                            "inspection_limit": 100,
                            "detail": "Metadata only. Human pilot must inspect the actual image/project and current trust.photo_status; file edits or revoked verifiers can invalidate an attestation.",
                        }
                    )
                    bot = (
                        TelegramConnection.objects.filter(workspace=workspace)
                        .only("id", "is_active", "webhook_status", "approvals_enabled")
                        .first()
                    )
                    check("telegram.saved_connection", bool(bot and bot.is_active and bot.webhook_status == "active"))
                    if bot:
                        check("telegram.human_approvals_opted_in", bot.approvals_enabled)
                        active_chats = TelegramChat.objects.filter(connection=bot, is_active=True)
                        audience_counts = {
                            kind: active_chats.filter(audience=kind).count() for kind in ("private", "team", "client")
                        }
                        paired = TelegramUserLink.objects.filter(connection=bot, is_active=True).count()
                        check("telegram.paired_people", paired >= 1, paired_count=paired)
                        internal_count = client_count = 0
                        for link in TelegramUserLink.objects.filter(connection=bot, is_active=True).select_related(
                            "user"
                        )[:100]:
                            try:
                                member = current_member(workspace, link.user)
                            except PermissionDenied:
                                continue
                            if internal_member(member):
                                internal_count += 1
                            else:
                                client_count += 1
                        check("telegram.current_staff_paired", internal_count > 0, count=internal_count)
                        check("telegram.current_client_paired", client_count > 0, count=client_count)
                        if config:
                            check(
                                "telegram.lead_and_backup_paired",
                                bool(
                                    config.lead_id
                                    and config.backup_id
                                    and TelegramUserLink.objects.filter(
                                        connection=bot, is_active=True, user_id=config.lead_id
                                    ).exists()
                                    and TelegramUserLink.objects.filter(
                                        connection=bot, is_active=True, user_id=config.backup_id
                                    ).exists()
                                ),
                            )
                        check("telegram.separate_audiences", all(audience_counts.values()), counts=audience_counts)
                        unknown = TelegramDelivery.objects.filter(connection=bot, status="unknown").count()
                        check("telegram.no_unknown_send_hold", unknown == 0, unknown_count=unknown)
                    check("telegram.webhook_enabled", bool(getattr(settings, "TELEGRAM_WEBHOOK_READY", False)))
            if args.stage == "runtime":
                names = [
                    "apps.publisher.tasks.run_publish_cycle",
                    "apps.studio.tasks.run_agency_cycle",
                    "apps.publisher.tasks.confirm_pending_publishes",
                    "apps.telegram.tasks.run_telegram_cycle",
                ]
                for key, health in task_health().items():
                    check(
                        f"worker.success.{key}",
                        health["healthy"],
                        age_seconds=health["age_seconds"],
                        last_success_at=health["last_success_at"],
                    )
                row = TaskHeartbeat.objects.filter(task_name=names[-1]).first()
                now = django_timezone.now()
                age = (now - row.last_success_at).total_seconds() if row and row.last_success_at else None
                check(
                    "worker.success.telegram",
                    bool(
                        row
                        and row.last_success_at is not None
                        and row.state in ("ok", "working")
                        and age is not None
                        and -30 <= age <= 120
                        and (row.last_failure_at is None or row.last_failure_at < row.last_success_at)
                    ),
                    age_seconds=None if age is None else round(age),
                )
                registered = set(Task.objects.filter(task_name__in=names).values_list("task_name", flat=True))
                check("worker.critical_schedules", all(name in registered for name in names))
                key = _advisory_lock_key("worker-process-singleton") & ((1 << 64) - 1)
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND classid=%s "
                        "AND objid=%s AND objsubid=1 AND granted AND database="
                        "(SELECT oid FROM pg_database WHERE datname=current_database())",
                        [key >> 32, key & ((1 << 32) - 1)],
                    )
                    count = cursor.fetchone()[0]
                check("worker.singleton_lease_observed", count == 1, lease_count=count)
    except Exception as exc:
        check("inspection.exception", False, error_type=type(exc).__name__)
    return finish()


if __name__ == "__main__":
    raise SystemExit(main())
