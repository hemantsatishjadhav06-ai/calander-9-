"""Is the agency ready to work on its own? One line in plain words, with the detail behind it.

The logic separates saved configuration from observed processing. The copy
never names a setting, a worker or a service: the owner's Set up page is the
one place that says what exactly is missing, so every message here points
there.
"""

from __future__ import annotations

from django.urls import NoReverseMatch, reverse

from . import budget, images, llm, trust
from .forms import studio_accounts
from .models import AgencyJob, AgencySettings, StudioBrief

READY_LINE = "Everything is set up. Your team works on its own and asks you only when it needs you."


def _setup_url(workspace) -> str:
    try:
        return reverse("studio:setup", kwargs={"workspace_id": workspace.pk})
    except NoReverseMatch:
        return ""


def telegram_state(workspace, user=None) -> dict:
    """How far Telegram is from listening for this workspace (and this person, when given).

    The one function behind the Set up row, Home's status line and the
    readiness block. ``state`` is one of ``deployment_needed`` (this
    deployment cannot receive updates yet), ``setup_needed`` (no listening
    bot), ``pairing_needed`` (a bot, but not this person's phone), ``ready``,
    or ``connected`` when no person is given. ``deployment_ready`` and
    ``bot_state`` are the two facts ``apps.telegram.state`` reads for the
    guided Telegram page too.
    """
    from apps.telegram import state as telegram
    from apps.telegram.models import TelegramConnection, TelegramUserLink

    connection = (
        TelegramConnection.objects.filter(workspace=workspace, is_active=True)
        .only("id", "is_active", "token", "webhook_status", "bot_username")
        .first()
    )
    deployment_ready = telegram.deployment_ready()
    bot_state = telegram.bot_state(connection)
    listening = bot_state == "listening"
    bot = f"@{connection.bot_username}" if connection and connection.bot_username else "your bot"
    paired = None
    if connection is not None and getattr(user, "pk", None):
        paired = TelegramUserLink.objects.filter(connection=connection, user=user, is_active=True).exists()
    if not deployment_ready:
        state, label = "deployment_needed", "Telegram: not ready on this deployment yet"
    elif not listening:
        state, label = "setup_needed", "Telegram: connect your bot"
    elif paired is None:
        state, label = "connected", f"Telegram: listening as {bot}"
    elif paired:
        state, label = "ready", f"Telegram: listening as {bot} · you're paired"
    else:
        state, label = "pairing_needed", f"Telegram: listening as {bot} · pair your phone"
    return {
        "state": state,
        "label": label,
        "deployment_ready": deployment_ready,
        "bot_state": bot_state,
        "connected": listening,
        "paired": bool(paired),
        "bot": bot if connection else "",
    }


def operational_readiness(workspace, user=None) -> dict:
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
        blockers.append("Your AI team isn't connected yet — open Set up.")
    if not accounts:
        blockers.append("Connect a social account in Set up.")
    account_rows = []
    for account in accounts:
        healthy = not account.needs_reconnect and bool(account.account_platform_id)
        account_rows.append(
            {
                "id": str(account.pk),
                "name": account.account_name or account.account_handle,
                "platform": account.get_platform_display(),
                "healthy": healthy,
            }
        )
        if not healthy:
            blockers.append(f"Reconnect {account.account_name or account.get_platform_display()} in Set up.")
    if not budget.can_spend(workspace):
        blockers.append("This month's AI budget is used up — raise it in Set up.")
    if workspace.is_archived or workspace.organization.deleted_at is not None:
        blockers.append("This workspace is paused or being deleted.")
    failed = (
        AgencyJob.objects.filter(workspace=workspace, status=AgencyJob.Status.FAILED).count()
        + StudioBrief.objects.filter(workspace=workspace, status=StudioBrief.Status.FAILED).count()
    )
    if failed:
        warnings.append(f"{failed} task{'s' if failed != 1 else ''} need{'' if failed != 1 else 's'} your review.")
    if not all(row["healthy"] for row in worker.values()):
        warnings.append("Automatic work hasn't run recently; open Set up to check.")
    if not trust.current_claims(workspace).exists():
        warnings.append("Verify your facts in Set up before the team uses prices, availability or dates.")
    if not images.is_configured():
        warnings.append("Pictures aren't set up yet; send a photo with each idea, or open Set up.")
    if settings and settings.autopilot_enabled and not settings.backup_id:
        warnings.append("Choose a backup approver in Set up.")
    telegram = telegram_state(workspace, user)
    return {
        "state": "blocked" if blockers else "needs_verification" if warnings else "processing_observed",
        "title": "Your team can't work yet"
        if blockers
        else "Set up is nearly done"
        if warnings
        else "Your team is working on its own",
        "line": blockers[0] if blockers else warnings[0] if warnings else READY_LINE,
        "setup_url": _setup_url(workspace),
        "blockers": blockers,
        "warnings": warnings,
        "worker": worker,
        "accounts": account_rows,
        "failed_items": failed,
        "telegram": telegram,
    }
