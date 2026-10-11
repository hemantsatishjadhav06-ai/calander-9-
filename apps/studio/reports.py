"""The weekly client report, read side: what the dashboard and the client portal show.

The client reporter (``apps.studio.jobtypes.report``) stores each report in its
job's ``result``. The job row also holds things a client must never see — the
team's timeline, token counts, errors, the job's working state — so nothing
outside the studio reads report jobs directly: :func:`latest_report` and
:func:`recent_reports` copy out only the report's own words and the plain
numbers code counted, cleaned and cut to length.

Nothing here calls a model.
"""

from __future__ import annotations

from typing import Any

from .models import AgencyJob

#: The section kinds a report may have, in the order they are shown.
SECTION_KINDS = ("went_out", "best", "audience", "next")

#: Plain network names for people who aren't marketers.
_NETWORK_NAMES = {
    "linkedin_company": "LinkedIn",
    "linkedin_personal": "LinkedIn",
    "instagram": "Instagram",
    "instagram_login": "Instagram",
    "facebook": "Facebook",
    "x": "X",
    "threads": "Threads",
    "bluesky": "Bluesky",
    "mastodon": "Mastodon",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "pinterest": "Pinterest",
    "google_business": "Google Business",
}


def network_name(platform: str) -> str:
    return _NETWORK_NAMES.get(platform or "", (platform or "").replace("_", " ").title() or "Other")


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def client_safe(job: AgencyJob) -> dict[str, Any] | None:
    """The client-facing part of one finished report job, or None when it holds no report."""
    result = job.result if isinstance(job.result, dict) else {}
    title = _text(result.get("title"), 200)
    if job.kind != AgencyJob.Kind.REPORT or job.status != AgencyJob.Status.DONE or not title:
        return None
    sections = []
    for section in result.get("sections") or []:
        if not isinstance(section, dict) or section.get("kind") not in SECTION_KINDS:
            continue
        heading, body = _text(section.get("heading"), 120), _text(section.get("body"), 1200)
        if heading and body:
            sections.append({"kind": section["kind"], "heading": heading, "body": body})
    raw_period, raw_went_out = result.get("period"), result.get("went_out")
    period: dict[str, Any] = raw_period if isinstance(raw_period, dict) else {}
    went_out: dict[str, Any] = raw_went_out if isinstance(raw_went_out, dict) else {}
    return {
        "id": str(job.pk),
        "title": title,
        "summary": _text(result.get("summary"), 600),
        "sections": sections,
        "period": _text(period.get("label"), 80),
        "went_out": {
            _text(name, 40): int(count)
            for name, count in went_out.items()
            if isinstance(count, int) and not isinstance(count, bool)
        },
        "created_at": job.finished_at or job.created_at,
    }


def _done_reports(workspace):
    return AgencyJob.objects.filter(
        workspace=workspace, kind=AgencyJob.Kind.REPORT, status=AgencyJob.Status.DONE
    ).order_by("-finished_at", "-created_at")


def latest_report(workspace) -> dict[str, Any] | None:
    """This workspace's newest weekly report, safe to show a client; None when there is none yet.

    ``{"id", "title", "summary", "sections": [{"kind", "heading", "body"}], "period",
    "went_out": {network: posts}, "created_at"}`` — the report's words and code-counted
    numbers only: no costs, internal notes, errors or agent details.
    """
    for job in _done_reports(workspace)[:5]:
        report = client_safe(job)
        if report is not None:
            return report
    return None


def recent_reports(workspace, limit: int = 4) -> list[dict[str, Any]]:
    """The newest reports for the agency's own pages (same client-safe shape)."""
    out = []
    for job in _done_reports(workspace)[: limit * 2]:
        report = client_safe(job)
        if report is not None:
            out.append(report)
        if len(out) >= limit:
            break
    return out
