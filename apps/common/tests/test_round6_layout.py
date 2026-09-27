"""Layout-level gaps closed before launch.

- F12: there was no unread-notification indicator anywhere. The sidebar's
  Notifications link now carries a live badge seeded from the server count.
- F6: composer validation errors named no field; they now carry labels.
"""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.notifications.engine import notify
from apps.notifications.models import EventType
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


def _owner():
    user = User.objects.create_user(email="o@example.com", password="pw", name="O", tos_accepted_at=timezone.now())
    auto = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto).delete()
    org = Organization.objects.create(name="Org")
    ws = Workspace.objects.create(organization=org, name="WS")
    OrgMembership.objects.create(user=user, organization=org, org_role="owner")
    WorkspaceMembership.objects.create(user=user, workspace=ws, workspace_role="owner")
    return user, ws


class NotificationBadgeTests(TestCase):
    def setUp(self):
        self.user, self.ws = _owner()
        self.client.force_login(self.user)
        self.page = reverse("calendar:calendar", kwargs={"workspace_id": self.ws.id})

    def test_the_badge_shows_the_unread_count(self):
        for i in range(3):
            notify(user=self.user, event_type=EventType.POST_FAILED, title=f"n{i}")
        html = self.client.get(self.page).content.decode()
        self.assertIn('data-testid="notification-badge"', html)
        self.assertIn("notificationBadge(3)", html)
        self.assertNotIn("__x", html, "Alpine v2 API is gone in Alpine 3")

    def test_no_unread_means_a_hidden_badge(self):
        html = self.client.get(self.page).content.decode()
        self.assertIn("notificationBadge(0)", html)

    def test_the_polling_endpoint_agrees(self):
        notify(user=self.user, event_type=EventType.POST_FAILED, title="n")
        self.assertEqual(self.client.get(reverse("notifications:unread_count")).json()["count"], 1)


class ComposerErrorLabelTests(TestCase):
    def test_form_errors_carry_field_labels(self):
        user, ws = _owner()
        self.client.force_login(user)
        response = self.client.post(
            reverse("composer:save_post", kwargs={"workspace_id": ws.id}),
            {"action": "save_draft", "caption": "x", "scheduled_date": "not-a-date"},
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertIn("error_labels", body)
        for field in body["errors"]:
            if field != "__all__":
                self.assertIn(field, body["error_labels"])
