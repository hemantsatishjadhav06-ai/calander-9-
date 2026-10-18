from datetime import time

import pytest
from django.urls import reverse

from .models import Channel, EventType, Notification, NotificationPreference, QuietHours


@pytest.mark.django_db
class TestNotificationUsability:
    @pytest.mark.parametrize("page", ["bogus", "0", "-1", "999999999999999999999999999999999"])
    def test_history_handles_invalid_page_parameters(self, client, user, page):
        client.force_login(user)
        notification = Notification.objects.create(user=user, event_type=EventType.POST_APPROVED, title="Approved")
        response = client.get(reverse("notifications:list"), {"page": page})
        assert response.status_code == 200
        assert list(response.context["notifications"]) == [notification]
        assert response.context["page"] == 1

    @pytest.mark.parametrize("target", ["notification-drawer-content", "notification-history-list"])
    def test_mark_all_read_refreshes_the_requested_surface(self, client, user, target):
        client.force_login(user)
        notification = Notification.objects.create(user=user, event_type=EventType.POST_APPROVED, title="Approved")
        response = client.post(reverse("notifications:mark_all_read"), HTTP_HX_REQUEST="true", HTTP_HX_TARGET=target)
        assert response.status_code == 200
        assert "Approved" in response.content.decode()
        notification.refresh_from_db()
        assert notification.is_read
        if target == "notification-history-list":
            assert "notifications/partials/history_list.html" in [template.name for template in response.templates]
        else:
            assert "notifications/partials/drawer.html" in [template.name for template in response.templates]

    def test_mark_read_keeps_history_and_preserves_unread_filter(self, client, user):
        client.force_login(user)
        notification = Notification.objects.create(user=user, event_type=EventType.POST_APPROVED, title="Approved")
        url = reverse("notifications:mark_as_read", args=[notification.id])
        response = client.post(url, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="notification-history-list")
        assert "Approved" in response.content.decode()
        assert "Mark read" not in response.content.decode()
        response = client.post(
            url, {"read_status": "unread"}, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="notification-history-list"
        )
        assert "Approved" not in response.content.decode()
        assert "No notifications" in response.content.decode()

    def test_unread_drawer_action_navigates_after_marking_read(self, client, user):
        client.force_login(user)
        notification = Notification.objects.create(
            user=user, event_type=EventType.POST_APPROVED, title="Approved", data={"action_url": "/notifications/"}
        )
        response = client.post(
            reverse("notifications:mark_as_read", args=[notification.id]),
            {"next": "/notifications/"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert response["HX-Redirect"] == "/notifications/"
        notification.refresh_from_db()
        assert notification.is_read

    @pytest.mark.parametrize("destination", ["https://evil.example/", "//evil.example/", "javascript:alert(1)"])
    def test_read_action_rejects_external_redirects(self, client, user, destination):
        client.force_login(user)
        notification = Notification.objects.create(user=user, event_type=EventType.POST_APPROVED, title="Approved")
        response = client.post(
            reverse("notifications:mark_as_read", args=[notification.id]),
            {"next": destination},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert "HX-Redirect" not in response

    def test_time_controls_render_existing_values_in_html_time_format(self, client, user):
        client.force_login(user)
        QuietHours.objects.create(user=user, is_enabled=True, start_time=time(22, 30), end_time=time(7, 0))
        response = client.get(reverse("notifications:preferences"))
        assert 'value="22:30"' in response.content.decode()
        assert 'value="07:00"' in response.content.decode()

    @pytest.mark.parametrize(
        "data",
        [
            {"quiet_hours_start": "25:00"},
            {"quiet_hours_start": "bad"},
            {"quiet_hours_timezone": "Not/AZone"},
            {"quiet_hours_timezone": "../UTC"},
            {"quiet_hours_enabled": "on", "quiet_hours_end": ""},
            {"quiet_hours_enabled": "on", "quiet_hours_start": "07:00", "quiet_hours_end": "07:00"},
        ],
    )
    def test_invalid_preferences_show_errors_without_partial_saves(self, client, user, data):
        client.force_login(user)
        preference = NotificationPreference.objects.create(
            user=user, event_type=EventType.POST_APPROVED, channel=Channel.EMAIL, is_enabled=True
        )
        quiet_hours = QuietHours.objects.create(user=user, timezone="UTC", start_time=time(22), end_time=time(7))
        response = client.post(
            reverse("notifications:preferences"),
            {"quiet_hours_start": "22:00", "quiet_hours_end": "07:00", "quiet_hours_timezone": "UTC", **data},
        )
        assert response.status_code == 400
        assert "Check your quiet hours settings." in response.content.decode()
        preference.refresh_from_db()
        quiet_hours.refresh_from_db()
        assert preference.is_enabled
        assert quiet_hours.timezone == "UTC"
        assert quiet_hours.start_time == time(22)
        assert not quiet_hours.is_enabled

    def test_valid_quiet_hours_save_and_can_be_cleared(self, client, user):
        client.force_login(user)
        response = client.post(
            reverse("notifications:preferences"),
            {
                "quiet_hours_enabled": "on",
                "quiet_hours_start": "22:30",
                "quiet_hours_end": "07:00",
                "quiet_hours_timezone": "Asia/Kolkata",
                "digest_mode": "on",
            },
        )
        assert response.status_code == 302
        quiet_hours = QuietHours.objects.get(user=user)
        assert quiet_hours.start_time == time(22, 30)
        assert quiet_hours.end_time == time(7)
        assert quiet_hours.timezone == "Asia/Kolkata"
        assert quiet_hours.is_enabled and quiet_hours.digest_mode
        response = client.post(reverse("notifications:preferences"), {"quiet_hours_timezone": ""})
        assert response.status_code == 302
        quiet_hours.refresh_from_db()
        assert quiet_hours.start_time is None and quiet_hours.end_time is None
        assert quiet_hours.timezone == "UTC"

    def test_hidden_delivery_notifications_cannot_be_marked_read(self, client, user):
        client.force_login(user)
        notification = Notification.objects.create(
            user=user, event_type=EventType.POST_APPROVED, title="Email only", shown_in_app=False
        )
        client.post(reverse("notifications:mark_as_read", args=[notification.id]))
        notification.refresh_from_db()
        assert not notification.is_read
