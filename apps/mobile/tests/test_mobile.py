"""The phone layout and the installable app.

Covers the three phone screens (Today, More, a post's review page), the
phone chrome every signed-in page gets (app bar, bottom tabs, sheets), and the
plumbing that makes the site installable: manifest, service worker, offline
page and the /app/ launch URLs.
"""

import json
import zoneinfo
from datetime import UTC, datetime, time, timedelta

from django.test import RequestFactory, TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.mobile import services
from apps.mobile.context_processors import active_tab, mobile_shell
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


def _user(email):
    user = User.objects.create_user(
        email=email, password="pw-12345678", name=email.split("@")[0], tos_accepted_at=timezone.now()
    )
    auto_orgs = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto_orgs).delete()
    return user


class Base(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Neopolis Group")
        self.ws = Workspace.objects.create(organization=self.org, name="Neopolis", timezone="Asia/Kolkata")
        self.other_ws = Workspace.objects.create(organization=self.org, name="More Space", timezone="Asia/Kolkata")
        self.owner = _user("owner@example.com")
        self.editor = _user("editor@example.com")
        OrgMembership.objects.create(user=self.owner, organization=self.org, org_role="owner")
        OrgMembership.objects.create(user=self.editor, organization=self.org, org_role="member")
        WorkspaceMembership.objects.create(user=self.owner, workspace=self.ws, workspace_role="owner")
        WorkspaceMembership.objects.create(user=self.owner, workspace=self.other_ws, workspace_role="owner")
        WorkspaceMembership.objects.create(user=self.editor, workspace=self.ws, workspace_role="editor")
        self.fb = SocialAccount.objects.create(
            workspace=self.ws,
            platform="facebook",
            account_platform_id="585141221346435",
            account_name="Neopolis Infra",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        self.ig = SocialAccount.objects.create(
            workspace=self.ws,
            platform="instagram",
            account_platform_id="17841400000000000",
            account_name="neopolis_infra",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        self.client.force_login(self.owner)

    def pending(self, *, title="What a landlord's share is", when=None, ws=None, accounts=None):
        ws = ws or self.ws
        post = Post.objects.create(
            workspace=ws, author=self.editor, title=title, caption="Line one\n\nLine two", proposed_publish_at=when
        )
        for account in accounts if accounts is not None else (self.fb, self.ig):
            PlatformPost.objects.create(post=post, social_account=account, status="pending_review")
        return post

    def url(self, name, **kwargs):
        return reverse(name, kwargs={"workspace_id": self.ws.id, **kwargs})


class ActiveTabTests(TestCase):
    def test_each_page_lights_up_the_tab_it_belongs_to(self):
        ws = "00000000-0000-0000-0000-000000000001"
        cases = {
            f"/workspace/{ws}/app/today/": "today",
            f"/workspace/{ws}/app/more/": "more",
            f"/workspace/{ws}/calendar/": "publish",
            f"/workspace/{ws}/compose/": "publish",
            f"/workspace/{ws}/inbox/": "inbox",
            "/notifications/": "more",
            "/accounts/settings/": "more",
        }
        for path, tab in cases.items():
            with self.subTest(path=path):
                self.assertEqual(active_tab(resolve(path)), tab)

    def test_no_match_no_tab(self):
        self.assertEqual(active_tab(None), "")

    def test_anonymous_requests_get_nothing(self):
        request = RequestFactory().get("/")
        from django.contrib.auth.models import AnonymousUser

        request.user = AnonymousUser()
        self.assertEqual(mobile_shell(request), {})


class TodayTests(Base):
    def test_requires_sign_in(self):
        self.client.logout()
        response = self.client.get(self.url("mobile:today"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_non_members_are_refused(self):
        outsider = _user("outsider@example.com")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(self.url("mobile:today")).status_code, 403)

    def test_shows_what_waits_for_approval_with_a_one_tap_approve(self):
        post = self.pending(when=timezone.now() + timedelta(days=1))
        response = self.client.get(self.url("mobile:today"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Needs your approval", html)
        self.assertIn("What a landlord&#x27;s share is", html)
        approve = reverse("approvals:approve", kwargs={"workspace_id": self.ws.id, "post_id": post.id})
        self.assertIn(f'hx-post="{approve}" hx-vals=\'{{"schedule": "1"}}\'', html)
        self.assertIn("Approve &amp; schedule", html)
        # The screen refreshes itself after an approval elsewhere on the page.
        self.assertIn('hx-trigger="approvalAction from:body, m-refresh from:body"', html)

    def test_a_passed_time_is_approved_without_scheduling(self):
        post = self.pending(when=timezone.now() - timedelta(hours=3))
        html = self.client.get(self.url("mobile:today")).content.decode()
        approve = reverse("approvals:approve", kwargs={"workspace_id": self.ws.id, "post_id": post.id})
        self.assertIn(f'hx-post="{approve}"\n                hx-swap="none"', html)
        self.assertNotIn("Approve &amp; schedule", html)
        self.assertIn("proposed time has passed", html)

    def test_editors_see_the_queue_but_no_approve_button(self):
        post = self.pending(when=timezone.now() + timedelta(days=1))
        self.client.force_login(self.editor)
        html = self.client.get(self.url("mobile:today")).content.decode()
        self.assertIn("Waiting for approval", html)
        self.assertIn("Waiting for an approver.", html)
        self.assertNotIn(reverse("approvals:approve", kwargs={"workspace_id": self.ws.id, "post_id": post.id}), html)

    def test_only_this_brands_posts(self):
        self.pending(title="Other brand post", ws=self.other_ws, accounts=[])
        html = self.client.get(self.url("mobile:today")).content.decode()
        self.assertNotIn("Other brand post", html)
        self.assertIn("All caught up", html)

    def test_unread_messages_are_not_mistaken_for_flash_messages(self):
        from apps.inbox.models import InboxMessage

        InboxMessage.objects.create(
            workspace=self.ws,
            social_account=self.fb,
            platform_message_id="m1",
            message_type="comment",
            sender_name="Ravi",
            body="Is the 3BHK available?",
            status="unread",
            received_at=timezone.now(),
        )
        html = self.client.get(self.url("mobile:today")).content.decode()
        self.assertIn("New messages", html)
        self.assertIn("Is the 3BHK available?", html)
        self.assertNotIn('role="status" aria-live="polite" class="rounded-md p-4', html)


class ScheduleTests(Base):
    def test_days_are_the_workspaces_days_not_the_servers(self):
        tz = zoneinfo.ZoneInfo("Asia/Kolkata")
        now = datetime(2026, 10, 3, 17, 0, tzinfo=UTC)  # 22:30 on 3 Oct in Hyderabad
        # 00:30 on 4 Oct in Hyderabad is still 3 Oct in UTC.
        local_tomorrow = datetime.combine(now.astimezone(tz).date() + timedelta(days=1), time(0, 30), tzinfo=tz)
        post = self.pending(when=local_tomorrow)
        groups = services.week_schedule(self.ws, now=now)
        labels = {p.id: g["label"] for g in groups for p in g["posts"]}
        self.assertEqual(labels[post.id], "Tomorrow")

    def test_rejected_posts_are_left_out(self):
        post = self.pending(when=timezone.now() + timedelta(hours=5))
        post.platform_posts.update(status="rejected")
        self.assertEqual(services.week_schedule(self.ws), [])


class BrandSummaryTests(Base):
    def test_platforms_and_pending_count_per_brand(self):
        self.pending(when=timezone.now() + timedelta(days=1))
        self.pending(title="Second", when=timezone.now() + timedelta(days=2))
        rows = {row["workspace"].id: row for row in services.brand_summaries([self.ws, self.other_ws])}
        self.assertEqual(rows[self.ws.id]["platforms"], ["Facebook", "Instagram"])
        self.assertEqual(rows[self.ws.id]["pending"], 2)
        self.assertEqual(rows[self.other_ws.id], {"workspace": self.other_ws, "platforms": [], "pending": 0})

    def test_short_platform_names(self):
        self.assertEqual(
            services.platform_names(["instagram_login", "instagram", "linkedin_company", "x"]),
            ["Instagram", "LinkedIn", "X"],
        )


class MoreTests(Base):
    def test_lists_brands_pages_and_sign_out(self):
        response = self.client.get(self.url("mobile:more"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("More Space", html)
        self.assertIn(reverse("composer:drafts_list", kwargs={"workspace_id": self.ws.id}), html)
        self.assertIn(reverse("members:list"), html)
        self.assertIn(f'action="{reverse("accounts:logout")}"', html)
        self.assertIn("Owner", html)

    def test_organization_pages_only_for_org_admins(self):
        self.assertIn(reverse("api_keys:list"), self.client.get(self.url("mobile:more")).content.decode())
        self.client.force_login(self.editor)
        self.assertNotIn(reverse("api_keys:list"), self.client.get(self.url("mobile:more")).content.decode())


class PostPageTests(Base):
    def test_shows_each_channels_version_and_the_actions(self):
        post = self.pending(when=timezone.now() + timedelta(days=1))
        response = self.client.get(self.url("mobile:post", post_id=post.id))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Review post", html)
        self.assertIn("Neopolis Infra", html)
        self.assertIn("Instagram cannot publish without a photo or video", html)
        self.assertIn(
            reverse("approvals:request_changes", kwargs={"workspace_id": self.ws.id, "post_id": post.id}), html
        )
        self.assertIn(reverse("approvals:reject", kwargs={"workspace_id": self.ws.id, "post_id": post.id}), html)
        self.assertIn("Approving schedules it for", html)

    def test_another_brands_post_is_not_found(self):
        post = self.pending(ws=self.other_ws, accounts=[])
        self.assertEqual(self.client.get(self.url("mobile:post", post_id=post.id)).status_code, 404)

    def test_no_tab_bar_on_the_review_page(self):
        post = self.pending()
        html = self.client.get(self.url("mobile:post", post_id=post.id)).content.decode()
        self.assertNotIn('class="m-tabbar"', html)
        self.assertNotIn("m-has-tabbar", html)


class ShellTests(Base):
    def test_every_signed_in_page_gets_the_phone_chrome(self):
        html = self.client.get(self.url("calendar:calendar")).content.decode()
        self.assertIn('class="m-tabbar"', html)
        self.assertIn('class="m-appbar"', html)
        self.assertIn("m-brand-sheet", html)
        self.assertIn(self.url("mobile:today"), html)
        self.assertIn(f'<link rel="manifest" href="{reverse("pwa_manifest")}">', html)
        self.assertIn("viewport-fit=cover", html)
        self.assertIn("js/pwa.js", html)

    def test_the_composer_gets_the_whole_screen(self):
        html = self.client.get(self.url("composer:compose")).content.decode()
        self.assertNotIn('class="m-tabbar"', html)
        self.assertNotIn('class="m-appbar"', html)

    def test_brand_switcher_counts_what_waits_in_each_brand(self):
        self.pending(when=timezone.now() + timedelta(days=1))
        html = self.client.get(self.url("calendar:calendar")).content.decode()
        self.assertIn("1 to approve", html)
        self.assertIn("Facebook · Instagram", html)


class InstallableAppTests(TestCase):
    def test_manifest(self):
        response = self.client.get(reverse("pwa_manifest"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        data = json.loads(response.content)
        self.assertEqual(data["display"], "standalone")
        self.assertEqual(data["start_url"], "/app/?source=pwa")
        self.assertEqual(data["scope"], "/")
        self.assertTrue(any(i["purpose"] == "maskable" for i in data["icons"]))
        self.assertTrue(any(i["sizes"] == "512x512" for i in data["icons"]))
        self.assertEqual(
            [s["url"] for s in data["shortcuts"]],
            [
                "/app/approvals/?source=shortcut",
                "/app/new-post/?source=shortcut",
                "/app/inbox/?source=shortcut",
            ],
        )

    def test_service_worker_is_served_from_the_root_and_never_stale(self):
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("application/javascript"))
        self.assertEqual(response["Cache-Control"], "no-cache")
        body = response.content.decode()
        self.assertIn("const OFFLINE_URL = '/offline/'", body)
        # Pages are never stored on the phone: only static files are cached.
        self.assertIn("request.mode === 'navigate'", body)
        self.assertIn("url.pathname.startsWith('/static/')", body)

    def test_offline_page_is_self_contained(self):
        response = self.client.get(reverse("pwa_offline"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("You're offline", html)
        self.assertNotIn('<link rel="stylesheet"', html)
        # Its one script carries the nonce the CSP header names.
        nonce = html.split('<script nonce="', 1)[1].split('"', 1)[0]
        policy = response.get("Content-Security-Policy") or response["Content-Security-Policy-Report-Only"]
        self.assertIn(f"'nonce-{nonce}'", policy)


class LaunchTests(Base):
    def test_anonymous_goes_to_sign_in_and_back(self):
        self.client.logout()
        response = self.client.get("/app/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/?next=/app/", response["Location"])

    def test_opens_today_in_the_last_brand(self):
        self.client.get(self.url("calendar:calendar"))  # remembers this brand
        response = self.client.get("/app/?source=pwa")
        self.assertRedirects(response, self.url("mobile:today"), fetch_redirect_response=False)

    def test_shortcuts(self):
        self.client.get(self.url("calendar:calendar"))
        self.assertEqual(
            self.client.get("/app/approvals/")["Location"], self.url("calendar:calendar") + "?mode=list&tab=approvals"
        )
        self.assertEqual(self.client.get("/app/new-post/")["Location"], self.url("composer:compose"))
        self.assertEqual(self.client.get("/app/inbox/")["Location"], self.url("inbox:feed"))
        self.assertEqual(self.client.get("/app/nonsense/").status_code, 404)

    def test_someone_without_a_workspace_lands_on_the_dashboard(self):
        loner = _user("loner@example.com")
        self.client.force_login(loner)
        response = self.client.get("/app/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("dashboard"))
