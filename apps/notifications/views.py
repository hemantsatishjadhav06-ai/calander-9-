from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import (
    Channel,
    EventType,
    Notification,
    NotificationPreference,
    QuietHours,
)


def _listed_event_types():
    """The event types a person sees in their preferences and history filter (operator-only ones left out)."""
    from .engine import OPERATOR_ONLY_EVENTS

    return [(value, label) for value, label in EventType.choices if value not in OPERATOR_ONLY_EVENTS]


@login_required
@require_GET
def notification_drawer(request):
    """HTMX partial: renders the 50 most recent notifications for the drawer."""
    return _render_drawer(request)


def _render_drawer(request):
    notifications = Notification.objects.filter(user=request.user, shown_in_app=True).order_by("-created_at")[:50]
    return render(
        request,
        "notifications/partials/drawer.html",
        {
            "notifications": notifications,
        },
    )


@login_required
@require_GET
def notification_list(request):
    """Full notification history page with filtering."""
    context = _history_context(request.user, request.GET)
    if request.htmx:
        return render(request, "notifications/partials/history_list.html", context)
    return render(request, "notifications/history.html", context)


def _history_context(user, params):
    event_type = params.get("event_type", "")
    read_status = params.get("read_status", "")
    if event_type not in EventType.values:
        event_type = ""
    if read_status not in ("read", "unread"):
        read_status = ""

    qs = Notification.objects.filter(user=user, shown_in_app=True).order_by("-created_at", "-id")

    if event_type:
        qs = qs.filter(event_type=event_type)
    if read_status == "read":
        qs = qs.filter(is_read=True)
    elif read_status == "unread":
        qs = qs.filter(is_read=False)

    paginator = Paginator(qs, 30)
    page = paginator.get_page(params.get("page", 1))
    return {
        "notifications": page.object_list,
        "event_types": _listed_event_types(),
        "selected_event_type": event_type,
        "selected_read_status": read_status,
        "page": page.number,
        "has_next": page.has_next(),
        "has_prev": page.has_previous(),
        "total": paginator.count,
    }


@login_required
@require_POST
def mark_as_read(request, notification_id):
    """Mark a single notification as read."""
    Notification.objects.filter(id=notification_id, user=request.user, is_read=False, shown_in_app=True).update(
        is_read=True, read_at=timezone.now()
    )

    destination = request.POST.get("next", "")
    if destination and url_has_allowed_host_and_scheme(
        destination, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        if request.htmx:
            response = JsonResponse({"ok": True})
            response["HX-Redirect"] = destination
            return response
        return redirect(destination)

    if request.htmx:
        if request.headers.get("HX-Target") == "notification-history-list":
            return render(
                request, "notifications/partials/history_list.html", _history_context(request.user, request.POST)
            )
        return render(request, "notifications/partials/empty.html")
    return JsonResponse({"ok": True})


@login_required
@require_POST
def mark_all_read(request):
    """Mark all notifications as read."""
    Notification.objects.filter(user=request.user, is_read=False, shown_in_app=True).update(
        is_read=True, read_at=timezone.now()
    )

    if request.htmx:
        if request.headers.get("HX-Target") == "notification-history-list":
            return render(
                request, "notifications/partials/history_list.html", _history_context(request.user, request.POST)
            )
        return _render_drawer(request)
    return JsonResponse({"ok": True})


@login_required
@require_GET
def unread_count(request):
    """JSON endpoint for polling unread badge count."""
    count = Notification.objects.filter(user=request.user, is_read=False, shown_in_app=True).count()
    return JsonResponse({"count": count})


@login_required
@require_http_methods(["GET", "POST"])
def preferences(request):
    """Notification preferences page - per event type / channel toggles + quiet hours."""
    quiet_hours, _ = QuietHours.objects.get_or_create(user=request.user)
    quiet_form = QuietHoursForm(request.POST if request.method == "POST" else None, instance=quiet_hours)
    if request.method == "POST" and quiet_form.is_valid():
        return _save_preferences(request, quiet_form)

    # Build preference matrix: event_type → channel → enabled
    prefs = NotificationPreference.objects.filter(user=request.user)
    pref_map = {}
    for p in prefs:
        pref_map[(p.event_type, p.channel)] = p.is_enabled

    from .engine import DEFAULT_CHANNELS

    matrix = []
    for event_value, event_label in _listed_event_types():
        channel_toggles = []
        for ch_value, ch_label in Channel.choices:
            if request.method == "POST":
                enabled = f"pref_{event_value}_{ch_value}" in request.POST
            elif (event_value, ch_value) in pref_map:
                enabled = pref_map[(event_value, ch_value)]
            else:
                enabled = DEFAULT_CHANNELS.get(event_value, {}).get(ch_value, False)
            channel_toggles.append(
                {
                    "channel": ch_value,
                    "label": ch_label,
                    "field_name": f"pref_{event_value}_{ch_value}",
                    "enabled": enabled,
                }
            )
        matrix.append(
            {
                "event_type": event_value,
                "event_label": event_label,
                "channel_toggles": channel_toggles,
            }
        )

    context = {
        "matrix": matrix,
        "channel_choices": Channel.choices,
        "quiet_hours": quiet_hours,
        "quiet_form": quiet_form,
    }
    return render(request, "notifications/preferences.html", context, status=400 if quiet_form.is_bound else 200)


class QuietHoursForm(forms.ModelForm):
    quiet_hours_enabled = forms.BooleanField(required=False)
    quiet_hours_start = forms.TimeField(required=False, input_formats=["%H:%M", "%H:%M:%S"])
    quiet_hours_end = forms.TimeField(required=False, input_formats=["%H:%M", "%H:%M:%S"])
    quiet_hours_timezone = forms.CharField(max_length=50, required=False)

    class Meta:
        model = QuietHours
        fields = ["digest_mode"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.update(
            quiet_hours_enabled=self.instance.is_enabled,
            quiet_hours_start=self.instance.start_time.strftime("%H:%M") if self.instance.start_time else "",
            quiet_hours_end=self.instance.end_time.strftime("%H:%M") if self.instance.end_time else "",
            quiet_hours_timezone=self.instance.timezone,
        )

    def clean_quiet_hours_timezone(self):
        value = self.cleaned_data["quiet_hours_timezone"].strip() or "UTC"
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise forms.ValidationError("Enter a valid timezone, such as UTC or America/New_York.") from exc
        return value

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("quiet_hours_enabled"):
            for field in ("quiet_hours_start", "quiet_hours_end"):
                if not cleaned.get(field) and field not in self.errors:
                    self.add_error(field, "Set both start and end times to enable quiet hours.")
            if cleaned.get("quiet_hours_start") == cleaned.get("quiet_hours_end") and isinstance(
                cleaned.get("quiet_hours_start"), time
            ):
                self.add_error("quiet_hours_end", "End time must differ from start time.")
        return cleaned


@transaction.atomic
def _save_preferences(request, quiet_form):
    """Handle POST from preferences form."""
    user = request.user

    # Save channel toggles
    for event_value, _ in _listed_event_types():
        for ch_value, _ in Channel.choices:
            field_name = f"pref_{event_value}_{ch_value}"
            is_enabled = field_name in request.POST

            NotificationPreference.objects.update_or_create(
                user=user,
                event_type=event_value,
                channel=ch_value,
                defaults={"is_enabled": is_enabled},
            )

    # Save quiet hours
    quiet_hours = quiet_form.save(commit=False)
    quiet_hours.is_enabled = quiet_form.cleaned_data["quiet_hours_enabled"]
    quiet_hours.start_time = quiet_form.cleaned_data["quiet_hours_start"]
    quiet_hours.end_time = quiet_form.cleaned_data["quiet_hours_end"]
    quiet_hours.timezone = quiet_form.cleaned_data["quiet_hours_timezone"]
    quiet_hours.save()

    messages.success(request, "Notification preferences saved.")

    return redirect("notifications:preferences")
