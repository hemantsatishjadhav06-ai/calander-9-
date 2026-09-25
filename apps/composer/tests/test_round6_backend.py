"""Pre-launch backend gaps, each pinned by what went wrong before.

- C6: web-side status writes wrote state read earlier over whatever the
  publisher or a client had done since.
- A read-only viewer could upload media, attach and remove media on other
  people's posts, save templates and create tags and categories.
- F10/F11: event and category errors reached the user as raw JSON or a bare
  "Invalid data."; an end date before the start was silently changed.
- M16: a failed invite email still spent the org's daily budget.
- M18: the onboarding checklist ran four queries on every page.
- C11: "Disconnect" promised to keep history and deleted all of it.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals import services as approval_services
from apps.calendar.models import CustomCalendarEvent
from apps.common.models import EmailSendCounter
from apps.composer.models import ContentCategory, PlatformPost, Post
from apps.members import services as member_services
from apps.members.models import Invitation, OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace

WR = WorkspaceMembership.WorkspaceRole


def _user(email):
    user = User.objects.create_user(email=email, password="pw", name="u", tos_accepted_at=timezone.now())
    auto = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto).delete()
    return user


class Base(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")
        self.owner = _user("owner@example.com")
        OrgMembership.objects.create(user=self.owner, organization=self.org, org_role="owner")
        WorkspaceMembership.objects.create(user=self.owner, workspace=self.ws, workspace_role=WR.OWNER)
        self.account = SocialAccount.objects.create(
            workspace=self.ws,
            platform="bluesky",
            account_platform_id="did:1",
            account_name="acct",
            oauth_access_token="tok",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        self.client.force_login(self.owner)

    def _post(self, status=PlatformPost.Status.SCHEDULED):
        when = timezone.now() + timedelta(hours=1)
        post = Post.objects.create(workspace=self.ws, author=self.owner, caption="c", scheduled_at=when)
        pp = PlatformPost.objects.create(post=post, social_account=self.account, status=status, scheduled_at=when)
        return post, pp

    def _member(self, email, role):
        user = _user(email)
        OrgMembership.objects.create(user=user, organization=self.org, org_role="member")
        WorkspaceMembership.objects.create(user=user, workspace=self.ws, workspace_role=role)
        return user


class GuardedWriteTests(Base):
    def test_a_hold_does_not_overwrite_a_claimed_row(self):
        post, pp = self._post()
        stale = PlatformPost.objects.get(pk=pp.pk)  # read as "scheduled"
        PlatformPost.objects.filter(pk=pp.pk).update(status=PlatformPost.Status.PUBLISHING)

        self.assertFalse(approval_services._transition_or_skip(stale, "on_hold"))
        pp.refresh_from_db()
        self.assertEqual(pp.status, PlatformPost.Status.PUBLISHING)

    def test_an_unchanged_row_is_written(self):
        post, pp = self._post()
        fresh = PlatformPost.objects.get(pk=pp.pk)
        self.assertTrue(approval_services._transition_or_skip(fresh, "on_hold"))
        pp.refresh_from_db()
        self.assertEqual(pp.status, PlatformPost.Status.ON_HOLD)

    def test_bulk_unschedule_skips_a_row_the_publisher_claimed(self):
        from apps.calendar.views import _bulk_save_platform_posts

        _, a = self._post()
        _, b = self._post()
        rows = list(PlatformPost.objects.filter(pk__in=[a.pk, b.pk]))
        PlatformPost.objects.filter(pk=b.pk).update(status=PlatformPost.Status.PUBLISHING)
        for row in rows:
            row.transition_to("draft")
        saved = _bulk_save_platform_posts(rows)
        self.assertEqual(saved, {a.pk})
        b.refresh_from_db()
        self.assertEqual(b.status, PlatformPost.Status.PUBLISHING)

    def test_moving_a_scheduled_row_clears_its_retry_backoff(self):
        post, pp = self._post()
        PlatformPost.objects.filter(pk=pp.pk).update(retry_count=1, next_retry_at=timezone.now())
        new_time = (timezone.now() + timedelta(days=7)).replace(microsecond=0)
        response = self.client.post(
            reverse("calendar:reschedule", kwargs={"workspace_id": self.ws.id}),
            {"platform_post_id": str(pp.id), "new_datetime": new_time.isoformat()},
        )
        self.assertIn(response.status_code, (200, 204))
        pp.refresh_from_db()
        self.assertEqual(pp.retry_count, 0)
        self.assertIsNone(pp.next_retry_at)


class ViewerGateTests(Base):
    def test_a_viewer_cannot_touch_composer_write_endpoints(self):
        post, _ = self._post(status=PlatformPost.Status.DRAFT)
        category = ContentCategory.objects.create(workspace=self.ws, name="News", color="#3B82F6")
        viewer = self._member("viewer@example.com", WR.VIEWER)
        self.client.force_login(viewer)
        kw = {"workspace_id": self.ws.id}
        urls = [
            reverse("composer:upload_media", kwargs=kw),
            reverse("composer:thumbnail_upload", kwargs=kw),
            reverse("composer:attach_media", kwargs={**kw, "post_id": post.id}),
            reverse("composer:save_as_template", kwargs={**kw, "post_id": post.id}),
            reverse("composer:tag_create", kwargs=kw),
            reverse("composer:category_create", kwargs=kw),
            reverse("composer:category_edit", kwargs={**kw, "category_id": category.id}),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, {"name": "Hacked", "color": "#000000"}).status_code, 403)
        category.refresh_from_db()
        self.assertEqual(category.name, "News")

    def test_a_contributor_cannot_edit_media_on_someone_elses_post(self):
        post, _ = self._post(status=PlatformPost.Status.DRAFT)
        contributor = self._member("c@example.com", WR.CONTRIBUTOR)
        self.client.force_login(contributor)
        url = reverse("composer:attach_media", kwargs={"workspace_id": self.ws.id, "post_id": post.id})
        self.assertEqual(self.client.post(url, {}).status_code, 403)


class ReadableErrorTests(Base):
    def test_an_htmx_event_error_is_plain_text(self):
        response = self.client.post(
            reverse("calendar:event_create", kwargs={"workspace_id": self.ws.id}),
            {"title": "Launch", "start_date": "2026-10-10", "end_date": "2026-10-01"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response["Content-Type"].split(";")[0], "text/plain")
        self.assertIn("end date is before the start date", response.content.decode())
        self.assertFalse(CustomCalendarEvent.objects.exists(), "the event must not be silently 'fixed' and saved")

    def test_a_bad_date_on_edit_is_reported_not_swallowed(self):
        event = CustomCalendarEvent.objects.create(
            workspace=self.ws,
            title="E",
            start_date=timezone.now().date(),
            end_date=timezone.now().date(),
            created_by=self.owner,
        )
        response = self.client.post(
            reverse("calendar:event_edit", kwargs={"workspace_id": self.ws.id, "event_id": event.id}),
            {"title": "E", "start_date": "tomorrow"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Dates must look like", response.content.decode())

    def test_a_category_error_names_the_field(self):
        response = self.client.post(
            reverse("composer:category_create", kwargs={"workspace_id": self.ws.id}),
            {"name": "", "color": "#3B82F6"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Name:", response.content.decode())


class InviteBudgetRefundTests(Base):
    def test_a_failed_send_does_not_spend_the_daily_budget(self):
        with patch("apps.members.services._send_invite_email", return_value=False):
            member_services.create_invitation(self.org, "new@example.com", "member", [], self.owner, inviter=self.owner)
        self.assertTrue(Invitation.objects.filter(email="new@example.com").exists())
        counter = EmailSendCounter.objects.filter(scope="invite_org_day", key=str(self.org.id)).first()
        self.assertEqual(counter.count if counter else 0, 0)

    def test_a_successful_send_does(self):
        with patch("apps.members.services._send_invite_email", return_value=True):
            member_services.create_invitation(self.org, "new@example.com", "member", [], self.owner, inviter=self.owner)
        counter = EmailSendCounter.objects.get(scope="invite_org_day", key=str(self.org.id))
        self.assertEqual(counter.count, 1)


class ChecklistCacheTests(Base):
    def test_the_checklist_is_not_re_evaluated_on_every_page(self):
        cache.clear()
        url = reverse("calendar:calendar", kwargs={"workspace_id": self.ws.id})
        self.client.get(url)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(url)
        idea_queries = [
            q for q in ctx.captured_queries if 'FROM "composer_idea"' in q["sql"] and "EXISTS" in q["sql"].upper()
        ]
        self.assertEqual(idea_queries, [])
        cache.clear()


class DisconnectKeepsHistoryTests(Base):
    def _disconnect(self):
        with patch("apps.social_accounts.views._get_provider_for_platform", return_value=MagicMock()):
            return self.client.post(
                reverse(
                    "social_accounts:disconnect", kwargs={"workspace_id": self.ws.id, "account_id": self.account.id}
                )
            )

    def test_history_stays_and_scheduled_work_returns_to_draft(self):
        published_post, published = self._post(status=PlatformPost.Status.PUBLISHED)
        scheduled_post, scheduled = self._post()

        self.assertEqual(self._disconnect().status_code, 302)

        self.account.refresh_from_db()
        self.assertEqual(self.account.connection_status, SocialAccount.ConnectionStatus.DISCONNECTED)
        self.assertEqual(self.account.oauth_access_token, "")
        self.assertTrue(PlatformPost.objects.filter(pk=published.pk, status="published").exists())
        scheduled.refresh_from_db()
        self.assertEqual(scheduled.status, PlatformPost.Status.DRAFT)
        self.assertIsNone(scheduled.scheduled_at)

    def test_remove_needs_a_disconnect_first_then_deletes(self):
        _, pp = self._post(status=PlatformPost.Status.PUBLISHED)
        remove = reverse("social_accounts:remove", kwargs={"workspace_id": self.ws.id, "account_id": self.account.id})

        self.client.post(remove)
        self.assertTrue(SocialAccount.objects.filter(pk=self.account.pk).exists())

        self._disconnect()
        self.client.post(remove)
        self.assertFalse(SocialAccount.objects.filter(pk=self.account.pk).exists())
        self.assertFalse(PlatformPost.objects.filter(pk=pp.pk).exists())

    def test_a_viewer_cannot_remove(self):
        self._disconnect()
        viewer = self._member("v@example.com", WR.VIEWER)
        self.client.force_login(viewer)
        remove = reverse("social_accounts:remove", kwargs={"workspace_id": self.ws.id, "account_id": self.account.id})
        self.assertEqual(self.client.post(remove).status_code, 403)
        self.assertTrue(SocialAccount.objects.filter(pk=self.account.pk).exists())
