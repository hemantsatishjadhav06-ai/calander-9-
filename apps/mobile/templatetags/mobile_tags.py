"""Small formatting helpers for the phone screens."""

from datetime import timedelta

from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def short_ago(value, now=None):
    """'now', '5m', '3h', '2d', then a date ('1 Oct') — the way phone lists show age."""
    if not value:
        return ""
    now = now or timezone.now()
    delta = now - value
    if delta < timedelta(minutes=1):
        return "now"
    if delta < timedelta(hours=1):
        return f"{int(delta.total_seconds() // 60)}m"
    if delta < timedelta(days=1):
        return f"{int(delta.total_seconds() // 3600)}h"
    if delta < timedelta(days=7):
        return f"{delta.days}d"
    local = timezone.localtime(value)
    return f"{local.day} {local:%b}"
