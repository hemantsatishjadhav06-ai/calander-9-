"""Template helpers for the approval-workflow UI."""

from django import template

register = template.Library()

# Presentation metadata per editorial status, from the design system's status table:
# a tone (one of the five status tones), an icon shape and a word. ``dot`` / ``bg`` /
# ``fg`` / ``bd`` are the same tones as literal hex (icon, soft fill, text, hairline
# ring) for any surface that renders without the stylesheet. Kept here so every
# approval surface (publish tab, composer panel, client portal) renders an identical
# badge from one source. Busy states (scheduled, publishing) are info, a person being
# needed is warning, done is success, stopped is danger, nothing happening is neutral.
_NEUTRAL = {"tone": "neutral", "dot": "#656B73", "bg": "#EDEFF2", "fg": "#3E434A", "bd": "#E1E4E8"}
_WARNING = {"tone": "warning", "dot": "#9B5A00", "bg": "#FFF7EB", "fg": "#7F4700", "bd": "#FFDDAE"}
_SUCCESS = {"tone": "success", "dot": "#429E4A", "bg": "#EDFCED", "fg": "#317F38", "bd": "#BCF0BC"}
_INFO = {"tone": "info", "dot": "#035A7B", "bg": "#EFF8FD", "fg": "#044E6B", "bd": "#BEE3F8"}
_DANGER = {"tone": "danger", "dot": "#991618", "bg": "#FFF3F1", "fg": "#7C1213", "bd": "#FFCDC6"}

STATUS_META = {
    "draft": {"label": "Draft", "icon": "dash", **_NEUTRAL},
    "pending_review": {"label": "Pending review", "icon": "clock", **_WARNING},
    "pending_client": {"label": "Pending client", "icon": "clock", **_WARNING},
    "approved": {"label": "Approved", "icon": "check", **_SUCCESS},
    "changes_requested": {"label": "Changes requested", "icon": "return", **_WARNING},
    "rejected": {"label": "Rejected", "icon": "x-octagon", **_DANGER},
    "scheduled": {"label": "Scheduled", "icon": "calendar", **_INFO},
    "publishing": {"label": "Publishing", "icon": "spinner", **_INFO},
    "published": {"label": "Published", "icon": "check", **_SUCCESS},
    "partially_published": {"label": "Partially published", "icon": "alert-triangle", **_WARNING},
    "failed": {"label": "Failed", "icon": "x-octagon", **_DANGER},
    "on_hold": {"label": "Hold requested", "icon": "pause", **_NEUTRAL},
}


@register.inclusion_tag("approvals/partials/_status_badge.html")
def status_badge(status):
    """Render the editorial-status pill (icon + word) for *status*."""
    return {"meta": STATUS_META.get(status, STATUS_META["draft"])}
