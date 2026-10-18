"""Separate saved configuration from observed processing and external launch verification."""

from . import budget, images, llm, trust
from .forms import studio_accounts
from .models import AgencyJob, AgencySettings, StudioBrief


def operational_readiness(workspace) -> dict:
    from apps.common.background import task_health

    settings = AgencySettings.objects.filter(workspace=workspace).first()
    accounts = (
        list(settings.accounts.filter(workspace=workspace))
        if settings and settings.autopilot_enabled
        else studio_accounts(workspace)
    )
    worker = task_health()
    blockers, warnings = [], []
    if not llm.is_configured():
        blockers.append("The AI service needs administrator setup. Contact your workspace lead.")
    if not accounts:
        blockers.append("Choose a connected destination under Settings → Social accounts.")
    account_rows = []
    for account in accounts:
        healthy = not account.needs_reconnect and bool(account.account_platform_id)
        account_rows.append(
            {
                "id": str(account.pk),
                "name": account.account_name or account.account_handle,
                "platform": account.get_platform_display(),
                "healthy": healthy,
                "verification": "Saved connection only — live permissions and identity need a pilot check.",
            }
        )
        if not healthy:
            blockers.append(
                f"Reconnect {account.account_name or account.get_platform_display()} and verify its destination."
            )
    if not budget.can_spend(workspace):
        blockers.append("The estimated monthly AI budget is used. An owner can review it under Autopilot.")
    if workspace.is_archived or workspace.organization.deleted_at is not None:
        blockers.append("This workspace is paused or being deleted.")
    failed = (
        AgencyJob.objects.filter(workspace=workspace, status=AgencyJob.Status.FAILED).count()
        + StudioBrief.objects.filter(workspace=workspace, status=StudioBrief.Status.FAILED).count()
    )
    if failed:
        warnings.append(f"{failed} failed item(s) need an operator to inspect and retry safely.")
    if not all(row["healthy"] for row in worker.values()):
        warnings.append(
            "Successful agency and publishing cycles have not all been observed recently. Check the worker before relying on automatic delivery."
        )
    if not trust.current_claims(workspace).exists():
        warnings.append(
            "Verify current commercial claims under Verified facts before using prices, availability, title or launch promises."
        )
    if not images.is_configured():
        warnings.append(
            "Generated pictures are unavailable. Supply a project photo, or review the explicit brand-background fallback."
        )
    if settings and settings.autopilot_enabled and not settings.backup_id:
        warnings.append("Choose a backup approver for deadline alerts and recovery.")
    return {
        "state": "blocked" if blockers else "needs_verification" if warnings else "processing_observed",
        "title": "Work is blocked"
        if blockers
        else "Configuration saved; checks need attention"
        if warnings
        else "Recent worker processing observed",
        "message": "Provider credits, account permissions, public media access and real delivery are verified through a controlled pilot; this status does not certify them.",
        "blockers": blockers,
        "warnings": warnings,
        "worker": worker,
        "accounts": account_rows,
        "failed_items": failed,
    }
