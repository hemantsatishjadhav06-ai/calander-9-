"""The agency's monthly spend, and the budget that stops new model work.

Spend is estimated from the timeline: every ``AgentRun`` of the workspace this
calendar month (the workspace's timezone), using valid provider-reported cost
when available, otherwise listed token prices plus pictures and web searches.
Failed calls are included. An unpriced model uses the highest known rate for
each token component; this fallback is an estimate, not an upper bound on an
arbitrary model's price. In-flight calls and unreported charges are not known.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime
from decimal import Decimal

from django.utils import timezone

from . import llm
from .models import AgentRun

#: Used when no settings row exists yet.
DEFAULT_BUDGET = Decimal("150")


def month_start(workspace, now: datetime | None = None) -> datetime:
    try:
        zone = zoneinfo.ZoneInfo(workspace.effective_timezone or "UTC")
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        zone = zoneinfo.ZoneInfo("UTC")
    local = (now or timezone.now()).astimezone(zone)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _run_cost(run) -> Decimal:
    return llm.cost_for_run(run, unknown_model_fallback=True) or Decimal(0)


def month_spend(workspace, now: datetime | None = None) -> Decimal:
    as_of = now or timezone.now()
    runs = AgentRun.objects.filter(
        workspace=workspace, started_at__gte=month_start(workspace, as_of), started_at__lte=as_of
    ).only("agent", "status", "model", "input_tokens", "output_tokens", "cache_read_tokens", "output")
    # Display code can round to cents. Budget decisions retain sub-cent spend.
    return sum((_run_cost(run) for run in runs), Decimal(0))


def monthly_budget(workspace) -> Decimal:
    from .models import AgencySettings

    settings_row = AgencySettings.objects.filter(workspace=workspace).only("monthly_budget_usd").first()
    return settings_row.monthly_budget_usd if settings_row else DEFAULT_BUDGET


def remaining(workspace) -> Decimal:
    return monthly_budget(workspace) - month_spend(workspace)


def can_spend(workspace) -> bool:
    """False once this month's estimated spend has reached the budget."""
    return remaining(workspace) > 0


def over_budget_message(workspace) -> str:
    return (
        f"The team has used this month's AI budget (${monthly_budget(workspace)}). "
        "An owner can raise it under Agency → Autopilot, or it resets on the 1st."
    )
