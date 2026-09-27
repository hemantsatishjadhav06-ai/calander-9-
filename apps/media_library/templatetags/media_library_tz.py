"""The timezone media-library dates are shown in.

Upload and version timestamps are stored in UTC and rendered by partials that
reach the page several ways (full page, HTMX swap, include). Resolving the zone
here, from whatever the partial already has in context, keeps every one of
those paths in step without each view having to remember to pass it.
"""

import zoneinfo

from django import template

from apps.common.timezones import canonical_timezone

register = template.Library()


def _valid(name):
    if not name:
        return None
    name = canonical_timezone(str(name))
    try:
        zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return None
    return name


@register.simple_tag(takes_context=True)
def media_display_timezone(context):
    """The workspace's zone; for the org-level shared library, the org default; else UTC."""
    workspace = context.get("workspace")
    if workspace is not None:
        name = _valid(getattr(workspace, "effective_timezone", None))
        if name:
            return name
    request = context.get("request")
    org = getattr(request, "org", None) if request is not None else None
    return _valid(getattr(org, "default_timezone", None)) or "UTC"
