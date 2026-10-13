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
OPERATION_LABELS = {
    "requested": "Requested briefs",
    "prepared": "Prepared drafts",
    "awaiting_approval": "Awaiting approval",
    "approved": "Approved",
    "scheduled": "Scheduled",
    "published": "Published",
    "failed": "Failed content",
    "blocked": "Held or blocked deliveries",
    "job_failures": "Failed work",
    "paused_weeks": "Paused planning weeks",
}
OUTCOME_LABELS = {"enquiry": "Enquiries", "qualified_enquiry": "Qualified enquiries", "site_visit": "Site visits"}

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
    report = {
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
    # Existing historical reports do not contain these snapshots. Do not turn
    # unavailable history into fabricated zero counts or expose arbitrary JSON.
    raw_operations = result.get("operations")
    if isinstance(raw_operations, dict):
        report["operations"] = {
            key: value
            for key, value in raw_operations.items()
            if key in OPERATION_LABELS and isinstance(value, int) and not isinstance(value, bool) and value >= 0
        }
        report["operation_scope"] = _text(result.get("operation_scope"), 800)
        report["operations_as_of"] = _text(result.get("operations_as_of"), 80)
    if isinstance(result.get("performance_note"), str):
        report["performance_note"] = _text(result["performance_note"], 600)
    raw_backlog = result.get("current_backlog")
    if isinstance(raw_backlog, dict):
        report["current_backlog"] = {
            key: value
            for key, value in raw_backlog.items()
            if key in {"awaiting_approval", "blocked", "failed"}
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
        }
    raw_outcomes = result.get("outcomes")
    if isinstance(raw_outcomes, dict):
        report["outcomes"] = {
            key: value
            for key, value in raw_outcomes.items()
            if key in OUTCOME_LABELS and isinstance(value, int) and not isinstance(value, bool) and value >= 0
        }
        report["outcome_note"] = (
            "Manual campaign event totals; attribution is supplied by the team. They are not unique people or automatic conversion rates."
        )
    return report


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
