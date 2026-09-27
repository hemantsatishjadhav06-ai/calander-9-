"""Findings from the CTO launch review, each verified before the fix.

- CSV import let a contributor schedule posts without approval.
- allauth's own login/signup/reset rate limits keyed on the proxy's address:
  ten failed logins from anyone locked everyone out.
- /admin/login/ had no throttle.
- Two new columns would have broken the old code's INSERTs after a rollback.
"""

from django.core.cache import cache
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.adapters import AccountAdapter
from apps.accounts.models import User
from apps.composer.models import PlatformPost
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


def _user(email):
    user = User.objects.create_user(email=email, password="pw", name="u", tos_accepted_at=timezone.now())
    auto = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto).delete()
    return user


class CsvImportApprovalTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")
        self.account = SocialAccount.objects.create(
            workspace=self.ws,
            platform="bluesky",
            account_platform_id="d",
            account_name="a",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )

    def _import_as(self, role):
        user = _user(f"{role}@example.com")
        OrgMembership.objects.create(user=user, organization=self.org, org_role="member")
        WorkspaceMembership.objects.create(user=user, workspace=self.ws, workspace_role=role)
        self.client.force_login(user)
        session = self.client.session
        session[f"csv_import_{self.ws.id}"] = {
            "rows": [["Launch day!", "2030-01-15", "10:00", "bluesky"]],
            "headers": ["caption", "date", "time", "platforms"],
        }
        session[f"csv_mapping_{self.ws.id}"] = {"caption": 0, "date": 1, "time": 2, "platforms": 3}
        session.save()
        self.client.post(reverse("composer:csv_confirm_import", kwargs={"workspace_id": self.ws.id}))
        return set(PlatformPost.objects.filter(post__workspace=self.ws).values_list("status", flat=True))

    def test_a_contributors_dated_rows_go_to_review(self):
        statuses = self._import_as("contributor")
        self.assertEqual(statuses, {"pending_review"})

    def test_a_publisher_still_schedules(self):
        statuses = self._import_as("owner")
        self.assertEqual(statuses, {"scheduled"})


class ClientIpForRateLimitsTests(TestCase):
    @override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",))
    def test_allauth_buckets_by_the_real_client(self):
        request = RequestFactory().post("/accounts/login/")
        request.META["REMOTE_ADDR"] = "10.0.0.1"
        request.META["HTTP_X_FORWARDED_FOR"] = "1.1.1.1, 203.0.113.9"
        self.assertEqual(AccountAdapter(request).get_client_ip(request), "203.0.113.9")


class AdminLoginThrottleTests(TestCase):
    def test_admin_login_is_rate_limited(self):
        cache.clear()
        statuses = [
            self.client.post("/admin/login/", {"username": "x@example.com", "password": "wrong"}).status_code
            for _ in range(12)
        ]
        self.assertIn(429, statuses)
        cache.clear()


class RollbackSafeColumnsTests(TestCase):
    """The previous release's INSERTs don't name the new columns."""

    def test_old_style_inserts_still_work(self):
        user = _user("n@example.com")
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO notifications_notification (id, user_id, event_type, title, body, data, is_read, created_at)"
                " VALUES (gen_random_uuid(), %s, 'post_failed', 't', '', '{}', false, now())",
                [user.id],
            )
            cursor.execute("SELECT shown_in_app FROM notifications_notification WHERE user_id = %s", [user.id])
            self.assertIs(cursor.fetchone()[0], True)
