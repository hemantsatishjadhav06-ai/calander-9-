"""The one mapping from a Studio brief's status to its tone and icon.

``studio/partials/status_badge.html`` draws the brief's pill from ``brief_status_meta``, and a list row
takes its status border from ``brief_tone`` (``data-tone``, spec D6), so a brief's pill and its row never
disagree. Working and queued are in the team's hands (info); ready waits for a person (warning);
approved happened (success); failed stopped (danger); anything else (discarded) is neutral. The
editorial statuses have their own mapping, ``approval_extras.STATUS_META``.
"""

from django import template

register = template.Library()

#: Per brief status (``StudioBrief.Status``): the tone (one of the five) and the pill's icon
#: (``studio/partials/pill.html``).
BRIEF_STATUS_META: dict[str, dict[str, str]] = {
    "planned": {"tone": "info", "icon": "dots"},
    "queued": {"tone": "info", "icon": "dots"},
    "working": {"tone": "info", "icon": "spinner"},
    "ready": {"tone": "warning", "icon": "clock"},
    "approved": {"tone": "success", "icon": "check"},
    "failed": {"tone": "danger", "icon": "x"},
    "discarded": {"tone": "neutral", "icon": "dash"},
}
_NEUTRAL = {"tone": "neutral", "icon": "dash"}


@register.simple_tag
def brief_status_meta(status):
    """``{"tone", "icon"}`` for a brief's *status*; an unknown or empty status is neutral."""
    return dict(BRIEF_STATUS_META.get(status or "", _NEUTRAL))


@register.filter
def brief_tone(status):
    """The brief status's tone, for a list row's ``data-tone`` status border (spec D6)."""
    return brief_status_meta(status)["tone"]
