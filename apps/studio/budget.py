"""The agency's monthly spend, and the budget that stops new model work.

Spend is estimated from the timeline: every ``AgentRun`` of the workspace this
calendar month (the workspace's timezone), at list prices, plus pictures and
web searches — including the tokens of calls that failed, which still cost
money. A model with no known price is counted at the highest known price, so
the estimate never under-counts.
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


def _run_cost(run) -> float:
    if run.agent in _picture_agents():
        return llm.PICTURE_PRICE if run.status == AgentRun.Status.SUCCEEDED else 0.0
    if not (run.input_tokens or run.output_tokens or run.cache_read_tokens):
        return 0.0
    price = llm.PRICES.get(run.model) or max(llm.PRICES.values(), key=lambda p: p[1])
    cost = (run.input_tokens * price[0] + run.output_tokens * price[1] + run.cache_read_tokens * price[2]) / 1e6
    return cost + llm.WEB_SEARCH_PRICE * int((run.output or {}).get("web_searches", 0) or 0)


def _picture_agents():
    from .team import PICTURE_AGENTS

    return PICTURE_AGENTS


def month_spend(workspace, now: datetime | None = None) -> Decimal:
    runs = AgentRun.objects.filter(workspace=workspace, started_at__gte=month_start(workspace, now)).only(
        "agent", "status", "model", "input_tokens", "output_tokens", "cache_read_tokens", "output"
    )
    return Decimal(str(round(sum(_run_cost(run) for run in runs), 2)))


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
