"""Verify the running deployment against its real database, storage and accounts.

Runs inside the production container (the release step calls it after
``migrate``) and prints one line per check — PASS, FAIL, BLOCKED (needs the
owner: a credential, a connection, a payment) or INFO — so every deploy log
says what actually works. It never fails the release.

It is safe on production by construction:

* Configuration, storage and worker checks only read, except one throwaway
  object written to and deleted from storage under ``healthchecks/``.
* Account checks make read-only identity calls (``/me``, the Page's own
  fields). Nothing is posted, commented, messaged or liked.
* The approval and publishing checks run end to end — real views through
  Django's test client, the real approval services, the real publish engine —
  on a throwaway organization created inside a transaction that is always
  rolled back. The provider call itself is replaced by a stub, and the engine
  is only ever pointed at that fixture's own row, never at the global publish
  loop, so no real post can be sent.
"""

from __future__ import annotations

import json
import uuid
from concurrent.futures import Future
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone


class _FixtureRollbackError(Exception):
    pass


class Command(BaseCommand):
    help = "Check the live deployment end to end; prints PASS/FAIL/BLOCKED lines. Never publishes anything."

    def add_arguments(self, parser):
        parser.add_argument("--skip-accounts", action="store_true", help="Skip the read-only account API calls.")
        parser.add_argument("--json", action="store_true", help="Also print a JSON summary line.")

    def handle(self, *args, skip_accounts=False, json=False, **options):
        self.results = []
        checks = [
            self.check_config,
            self.check_database,
            self.check_storage,
            self.check_worker,
            self.check_brands,
            self.check_credentials,
            self.check_isolation_and_approval,
        ]
        if not skip_accounts:
            checks.append(self.check_accounts)
        checks.append(self.check_blog)
        for check in checks:
            try:
                check()
            except Exception as exc:  # a broken check is a failed check, not a failed release
                self.record("FAIL", check.__name__, f"check crashed: {type(exc).__name__}: {exc}")
        counts = {k: sum(1 for r in self.results if r[0] == k) for k in ("PASS", "FAIL", "BLOCKED", "INFO")}
        self.stdout.write(
            f"live_verify: summary {counts['PASS']} passed, {counts['FAIL']} failed, "
            f"{counts['BLOCKED']} blocked on the owner, {counts['INFO']} info"
        )
        if json:
            self.stdout.write(
                "live_verify: json " + _json([{"result": r, "check": c, "detail": d} for r, c, d in self.results])
            )

    # ------------------------------------------------------------------

    def record(self, result, check, detail):
        self.results.append((result, check, detail))
        self.stdout.write(f"live_verify: {result:<7} {check}: {detail}")

    # ------------------------------------------------------------------

    def check_config(self):
        app_url = getattr(settings, "APP_URL", "") or ""
        self.record("PASS" if app_url.startswith("https://") else "FAIL", "config.app_url", app_url or "(unset)")
        self.record("PASS" if not settings.DEBUG else "FAIL", "config.debug", f"DEBUG={settings.DEBUG}")
        secure = bool(getattr(settings, "SESSION_COOKIE_SECURE", False)) and bool(
            getattr(settings, "CSRF_COOKIE_SECURE", False)
        )
        self.record("PASS" if secure else "FAIL", "config.secure_cookies", f"session+csrf secure={secure}")
        self.record(
            "PASS" if getattr(settings, "SECURE_PROXY_SSL_HEADER", None) else "FAIL",
            "config.https_behind_proxy",
            str(getattr(settings, "SECURE_PROXY_SSL_HEADER", None)),
        )
        backend = settings.STORAGES["default"]["BACKEND"]
        self.record("PASS" if "s3" in backend.lower() else "FAIL", "config.durable_media", backend)
        callback = f"{app_url.rstrip('/')}/social-accounts/callback/facebook/"
        self.record("INFO", "config.oauth_callbacks", f"Meta redirect URIs must include {callback} and .../instagram/")

    def check_database(self):
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        self.record("PASS" if not pending else "FAIL", "db.migrations", f"{len(pending)} unapplied")
        with connection.cursor() as cur:
            cur.execute("select 1")
        self.record("PASS", "db.connection", connection.vendor)

    def check_storage(self):
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        name = f"healthchecks/live-verify-{uuid.uuid4().hex}.txt"
        saved = default_storage.save(name, ContentFile(b"ok"))
        try:
            with default_storage.open(saved, "rb") as fh:
                ok = fh.read() == b"ok"
        finally:
            default_storage.delete(saved)
        self.record("PASS" if ok else "FAIL", "storage.round_trip", "write/read/delete in media storage")

    def check_worker(self):
        from background_task.models import CompletedTask, Task

        recurring = set(Task.objects.filter(repeat__gt=0).values_list("task_name", flat=True))
        wanted = {n for n in recurring if n.endswith(("run_publish_cycle", "poll_and_publish", "publish_cycle"))}
        self.record(
            "PASS" if recurring else "FAIL",
            "worker.schedules",
            f"{len(recurring)} recurring tasks registered" + (f", publisher: {sorted(wanted)}" if wanted else ""),
        )
        recent = CompletedTask.objects.filter(run_at__gte=timezone.now() - timedelta(minutes=30)).count()
        self.record("PASS" if recent else "FAIL", "worker.heartbeat", f"{recent} tasks completed in the last 30 min")

    def check_brands(self):
        from apps.members.models import WorkspaceMembership
        from apps.settings_manager.models import WorkspaceSetting
        from apps.workspaces.brands import BRAND_KEY, BRANDS
        from apps.workspaces.models import Workspace

        for brand in BRANDS:
            row = WorkspaceSetting.objects.filter(key=BRAND_KEY, value=brand["key"]).select_related("workspace").first()
            if row is None:
                self.record("FAIL", f"brand.{brand['key']}", "no workspace set up (run setup_brands)")
                continue
            ws = row.workspace
            approvers = [
                m
                for m in WorkspaceMembership.objects.filter(workspace=ws).select_related("custom_role")
                if m.effective_permissions.get("approve_posts") and m.workspace_role != "client"
            ]
            ok = ws.require_dashboard_approval and ws.timezone == "Asia/Kolkata" and approvers
            self.record(
                "PASS" if ok else "FAIL",
                f"brand.{brand['key']}",
                f"workspace {ws.id} '{ws.name}', tz={ws.timezone}, enforced approval={ws.require_dashboard_approval}, "
                f"approvers={len(approvers)}",
            )
            base = (getattr(settings, "APP_URL", "") or "").rstrip("/")
            self.record(
                "INFO",
                f"brand.{brand['key']}.links",
                f"approvals {base}/workspace/{ws.id}/calendar/?mode=list&tab=approvals · "
                f"calendar {base}/workspace/{ws.id}/calendar/ · accounts {base}/social-accounts/{ws.id}/connect/",
            )
        others = Workspace.objects.filter(require_dashboard_approval=False, is_archived=False).count()
        self.record("INFO", "brand.other_workspaces", f"{others} other workspace(s) keep their existing approval mode")

    def check_credentials(self):
        env = getattr(settings, "PLATFORM_CREDENTIALS_FROM_ENV", {}) or {}

        def has(platform):
            creds = env.get(platform) or {}
            return bool(creds.get("client_id") or creds.get("app_id")) and bool(
                creds.get("client_secret") or creds.get("app_secret")
            )

        for platform in ("facebook", "instagram", "threads"):
            self.record(
                "PASS" if has(platform) else "BLOCKED",
                f"credentials.{platform}",
                "app id/secret present" if has(platform) else "missing",
            )
        if has("x"):
            self.record("PASS", "credentials.x", "client id/secret present (posting also needs X API credits)")
        else:
            self.record(
                "BLOCKED",
                "credentials.x",
                "no X app: create one at console.x.com (OAuth 2.0, callback "
                f"{(getattr(settings, 'APP_URL', '') or '').rstrip('/')}/social-accounts/callback/x/), add credits "
                "(pay-per-use), then set PLATFORM_X_CLIENT_ID / PLATFORM_X_CLIENT_SECRET",
            )
        base = (getattr(settings, "APP_URL", "") or "").rstrip("/")
        if has("linkedin_company"):
            self.record(
                "PASS",
                "credentials.linkedin_company",
                "client id/secret present (posting as a Page needs the app's Community Management API product)",
            )
        else:
            self.record(
                "BLOCKED",
                "credentials.linkedin_company",
                "no LinkedIn app: create one at developer.linkedin.com tied to a Company Page, get the Community "
                f"Management API product, add the redirect URL {base}/social-accounts/callback/linkedin_company/, "
                "then set PLATFORM_LINKEDIN_COMPANY_CLIENT_ID / PLATFORM_LINKEDIN_COMPANY_CLIENT_SECRET",
            )
        if getattr(settings, "FACEBOOK_WEBHOOK_VERIFY_TOKEN", ""):
            self.record("PASS", "webhooks.meta", f"verify token set; Meta callback {base}/webhooks/facebook/")
        else:
            self.record(
                "BLOCKED",
                "webhooks.meta",
                "FACEBOOK_WEBHOOK_VERIFY_TOKEN unset — comments/DMs arrive by polling only. For real-time, set it and "
                f"subscribe {base}/webhooks/facebook/ in the Meta app (Webhooks → Page and Instagram)",
            )
        token = bool(getattr(settings, "BLOG_GITHUB_TOKEN", ""))
        self.record(
            "PASS" if token else "BLOCKED",
            "credentials.blog_github",
            "present" if token else "BLOG_GITHUB_TOKEN unset — approved blogs cannot publish",
        )

    def check_accounts(self):
        from apps.publisher.engine import _resolve_publish_credentials
        from apps.settings_manager.models import WorkspaceSetting
        from apps.social_accounts.models import SocialAccount
        from apps.workspaces.brands import BRAND_KEY, expected_identifiers
        from providers import get_provider

        brand_ws = {
            row.workspace_id: row.value
            for row in WorkspaceSetting.objects.filter(key=BRAND_KEY).select_related("workspace")
        }
        accounts = list(SocialAccount.objects.filter(workspace_id__in=brand_ws).select_related("workspace"))
        if not accounts:
            self.record(
                "BLOCKED",
                "accounts.connected",
                "no social accounts connected in the brand workspaces — connect them under Settings > Social accounts",
            )
        for brand_key in sorted(set(brand_ws.values())):
            mine = [a for a in accounts if brand_ws[a.workspace_id] == brand_key]
            for platform in ("facebook", "instagram", "x"):
                if not any(
                    a.platform == platform or (platform == "instagram" and a.platform == "instagram_login")
                    for a in mine
                ):
                    self.record("BLOCKED", f"accounts.{brand_key}.{platform}", "not connected")
        for account in accounts:
            label = f"accounts.{brand_ws[account.workspace_id]}.{account.platform}"
            expected = expected_identifiers(account.workspace, account.platform)
            ids = {str(account.account_platform_id).lower(), (account.account_handle or "").lower().lstrip("@")}
            matches = bool(expected & ids) or not expected
            if account.connection_status == SocialAccount.ConnectionStatus.DISCONNECTED:
                self.record("BLOCKED", label, f"{account.account_name} is disconnected — reconnect it")
                continue
            try:
                provider = get_provider(account.platform, _resolve_publish_credentials(account))
                profile = provider.get_profile(account.oauth_access_token)
                live_id = str(profile.platform_id)
                detail = f"'{profile.name}' id={live_id} handle={profile.handle or '-'}"
                link = ""
                if account.platform == "facebook":
                    resp = provider._request(
                        "GET",
                        f"https://graph.facebook.com/v25.0/{live_id}",
                        access_token=account.oauth_access_token,
                        params={"fields": "id,name,link,username"},
                    )
                    link = (resp.json() or {}).get("link", "") or ""
                    detail += f" link={link}"
                    ids.add(live_id.lower())
                    matches = matches or any(e in link.lower() for e in expected)
                ok = live_id == str(account.account_platform_id) and matches
                self.record(
                    "PASS" if ok else "FAIL", label, detail + ("" if matches else " — NOT the expected brand account")
                )
            except Exception as exc:
                self.record(
                    "FAIL",
                    label,
                    f"{account.account_name}: read-only API call failed: {type(exc).__name__}: {exc}"[:400],
                )

    def check_blog(self):
        try:
            from apps.blog.models import BlogSite
        except ImportError:
            self.record("FAIL", "blog.app", "blog app not installed")
            return
        sites = list(BlogSite.objects.all())
        self.record(
            "PASS" if len(sites) >= 2 else "FAIL",
            "blog.sites",
            ", ".join(f"{s.name}->{s.repo}" for s in sites) or "none",
        )
        token = getattr(settings, "BLOG_GITHUB_TOKEN", "")
        if not token:
            return
        import httpx

        for site in sites:
            try:
                resp = httpx.get(
                    f"https://api.github.com/repos/{site.repo}",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                    timeout=15,
                )
                perms = (resp.json() or {}).get("permissions", {}) if resp.status_code == 200 else {}
                ok = resp.status_code == 200 and perms.get("push", False)
                self.record(
                    "PASS" if ok else "FAIL",
                    f"blog.github.{site.repo}",
                    f"HTTP {resp.status_code}, push={perms.get('push')}",
                )
            except Exception as exc:
                self.record("FAIL", f"blog.github.{site.repo}", f"{type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    # End-to-end workflow on a throwaway fixture, always rolled back
    # ------------------------------------------------------------------

    def check_isolation_and_approval(self):
        try:
            # Notifications are delivered inline (email, webhooks); the fixture's
            # throwaway reviewers must not be emailed before the rollback.
            with transaction.atomic(), patch("apps.notifications.engine._dispatch", lambda delivery: None):
                self._workflow_fixture()
                raise _FixtureRollbackError
        except _FixtureRollbackError:
            self.record("INFO", "workflow.rollback", "fixture rolled back; nothing kept")

    def _blog_fixture(self, ws, approver, editor, outsider, client_for, tag):
        try:
            _blog_fixture_checks(self, ws, approver, editor, outsider, client_for, tag)
        except Exception as exc:
            self.record("FAIL", "blog.workflow", f"check crashed: {type(exc).__name__}: {exc}")

    def _workflow_fixture(self):
        from django.test import Client
        from django.urls import reverse

        from apps.accounts.models import User
        from apps.approvals import gate
        from apps.approvals.models import ApprovalAction
        from apps.composer.models import PlatformPost, Post
        from apps.members.models import OrgMembership, WorkspaceMembership
        from apps.organizations.models import Organization
        from apps.publisher.engine import PublishEngine
        from apps.social_accounts.models import SocialAccount
        from apps.workspaces.models import Workspace

        tag = uuid.uuid4().hex[:10]
        host = (getattr(settings, "APP_URL", "") or "https://localhost").split("://", 1)[-1].split("/")[0]

        def user(role):
            u = User.objects.create_user(
                email=f"live-verify-{role}-{tag}@invalid.example",
                password=uuid.uuid4().hex,
                tos_accepted_at=timezone.now(),
            )
            return u

        org = Organization.objects.create(name=f"live-verify {tag}")
        ws_a = Workspace.objects.create(
            organization=org,
            name="Fixture A",
            timezone="Asia/Kolkata",
            approval_workflow_mode="required_internal",
            require_dashboard_approval=True,
        )
        ws_b = Workspace.objects.create(
            organization=org,
            name="Fixture B",
            timezone="Asia/Kolkata",
            approval_workflow_mode="required_internal",
            require_dashboard_approval=True,
        )
        approver, editor, outsider = user("approver"), user("editor"), user("outsider")
        for u in (approver, editor, outsider):
            OrgMembership.objects.get_or_create(user=u, organization=org, defaults={"org_role": "member"})
        WorkspaceMembership.objects.create(user=approver, workspace=ws_a, workspace_role="owner")
        WorkspaceMembership.objects.create(user=editor, workspace=ws_a, workspace_role="editor")
        WorkspaceMembership.objects.create(user=outsider, workspace=ws_b, workspace_role="owner")
        account = SocialAccount.objects.create(
            workspace=ws_a,
            platform="facebook",
            account_platform_id=f"fixture-{tag}",
            account_name="Fixture Page",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )

        def client_for(u):
            c = Client(HTTP_HOST=host, secure=True, HTTP_X_FORWARDED_PROTO="https")
            c.force_login(u)
            return c

        # Isolation: a member of workspace B cannot read A's composer or calendar.
        outsider_client = client_for(outsider)
        codes = [
            outsider_client.get(reverse("composer:compose", kwargs={"workspace_id": ws_a.id})).status_code,
            outsider_client.get(reverse("calendar:calendar", kwargs={"workspace_id": ws_a.id})).status_code,
        ]
        self.record(
            "PASS" if all(c in (403, 404) for c in codes) else "FAIL",
            "isolation.workspace",
            f"outsider got {codes} (want 403/404)",
        )
        login_page = Client(HTTP_HOST=host, secure=True, HTTP_X_FORWARDED_PROTO="https").get(reverse("account_login"))
        self.record("PASS" if login_page.status_code == 200 else "FAIL", "login.page", f"HTTP {login_page.status_code}")

        # Draft → review: an editor's Schedule turns into a review request.
        when = timezone.now() + timedelta(days=2)
        when_local = timezone.localtime(when, timezone.get_fixed_timezone(330))
        editor_client = client_for(editor)
        resp = editor_client.post(
            reverse("composer:save_post", kwargs={"workspace_id": ws_a.id}),
            {
                "caption": f"live-verify fixture {tag}",
                "action": "schedule",
                "selected_accounts": str(account.id),
                "scheduled_date": when_local.strftime("%Y-%m-%d"),
                "scheduled_time": when_local.strftime("%H:%M"),
            },
            HTTP_HX_REQUEST="true",
        )
        post = Post.objects.filter(workspace=ws_a).first()
        pp = post.platform_posts.get() if post else None
        self.record(
            "PASS" if pp is not None and pp.status == "pending_review" else "FAIL",
            "workflow.draft_to_review",
            f"composer HTTP {resp.status_code}, status={pp.status if pp else None}",
        )
        if pp is None:
            return

        # Nobody but the approver in the dashboard can approve; the API cannot schedule unapproved content.
        from apps.approvals.actor import API, acting_as
        from apps.composer.services import transition_platform_post

        try:
            with acting_as(None, API):
                transition_platform_post(PlatformPost.objects.get(pk=pp.pk), "scheduled", scheduled_at=when)
            self.record("FAIL", "gate.api_cannot_schedule_unapproved", "API scheduled unapproved content")
        except gate.ApprovalRequired:
            self.record("PASS", "gate.api_cannot_schedule_unapproved", "refused")
        approve_url = reverse("approvals:approve", kwargs={"workspace_id": ws_a.id, "post_id": post.id})
        editor_client.post(approve_url)
        pp.refresh_from_db()
        self.record(
            "PASS" if pp.status == "pending_review" else "FAIL", "gate.editor_cannot_approve", f"status={pp.status}"
        )
        approver_client = client_for(approver)
        resp = approver_client.post(approve_url)
        pp.refresh_from_db()
        action = ApprovalAction.objects.filter(platform_post=pp, action="approved").first()
        ok = (
            pp.status == "approved"
            and pp.approved_by_id == approver.id
            and action
            and action.fingerprint == pp.approved_fingerprint
        )
        self.record(
            "PASS" if ok else "FAIL",
            "gate.approver_approves_revision",
            f"HTTP {resp.status_code}, status={pp.status}, fingerprint={pp.approved_fingerprint[:12]}…, channel={getattr(action, 'channel', None)}",
        )

        # Approved content schedules at the approved time.
        with acting_as(None, API):
            transition_platform_post(
                PlatformPost.objects.get(pk=pp.pk), "scheduled", scheduled_at=pp.approved_publish_at
            )
        pp.refresh_from_db()
        self.record("PASS" if pp.status == "scheduled" else "FAIL", "gate.schedule_approved", f"status={pp.status}")

        # An edit withdraws the approval (revalidation runs at commit; run it as the commit would).
        Post.objects.filter(pk=post.pk).update(caption=f"edited after approval {tag}")
        withdrawn = gate.revalidate_post(post.pk)
        pp.refresh_from_db()
        self.record(
            "PASS" if withdrawn and pp.status == "pending_review" and not pp.approved_fingerprint else "FAIL",
            "gate.edit_withdraws_approval",
            f"status={pp.status}",
        )

        # Re-approve, make it due, and publish through the real engine with the provider stubbed.
        approver_client.post(approve_url)
        due = timezone.now() - timedelta(seconds=5)
        PlatformPost.objects.filter(pk=pp.pk).update(status="scheduled", scheduled_at=due, approved_publish_at=due)
        Post.objects.filter(pk=post.pk).update(scheduled_at=due)
        calls = []

        def stub(self_engine, platform_post, media_cache=None):
            calls.append(platform_post.pk)
            return {"success": True, "platform_post_id": f"stub-{tag}", "status_code": 200, "response": {}}

        engine = PublishEngine()
        # Inline, on this connection: the fixture exists only inside this
        # uncommitted transaction, which a pool thread's own connection cannot see.
        inline = _InlineExecutor()
        with (
            patch.object(PublishEngine, "_dispatch_to_provider", stub),
            patch("apps.publisher.engine.in_worker_thread", _same_thread),
        ):
            fresh = PlatformPost.objects.select_related("post__workspace", "social_account").get(pk=pp.pk)
            engine._publish_post_group(fresh.post, [fresh], platform_pool=inline)
            again = PlatformPost.objects.select_related("post__workspace", "social_account").get(pk=pp.pk)
            engine._publish_post_group(again.post, [again], platform_pool=inline)  # must not send twice
        pp.refresh_from_db()
        self.record(
            "PASS" if pp.status == "published" and len(calls) == 1 else "FAIL",
            "publish.approved_once",
            f"status={pp.status}, provider calls={len(calls)}",
        )

        # A stale approval is blocked by the engine, before any provider call.
        post2 = Post.objects.create(workspace=ws_a, author=editor, caption=f"stale {tag}", scheduled_at=due)
        pp2 = PlatformPost.objects.create(post=post2, social_account=account, status="draft", scheduled_at=due)
        PlatformPost.objects.filter(pk=pp2.pk).update(
            status="scheduled", approved_fingerprint="0" * 64, approved_publish_at=due
        )
        calls.clear()
        with (
            patch.object(PublishEngine, "_dispatch_to_provider", stub),
            patch("apps.publisher.engine.in_worker_thread", _same_thread),
        ):
            fresh2 = PlatformPost.objects.select_related("post__workspace", "social_account").get(pk=pp2.pk)
            engine._publish_post_group(fresh2.post, [fresh2], platform_pool=inline)
        pp2.refresh_from_db()
        self.record(
            "PASS" if pp2.status == "failed" and not calls else "FAIL",
            "publish.stale_approval_blocked",
            f"status={pp2.status}, provider calls={len(calls)}, error={pp2.publish_error[:80]}",
        )

        self._blog_fixture(ws_a, approver, editor, outsider, client_for, tag)

        # The dashboard pages render for the approver.
        for name, url in (
            ("calendar", reverse("calendar:calendar", kwargs={"workspace_id": ws_a.id})),
            ("composer", reverse("composer:compose", kwargs={"workspace_id": ws_a.id})),
        ):
            code = approver_client.get(url).status_code
            self.record("PASS" if code == 200 else "FAIL", f"dashboard.{name}", f"HTTP {code}")


def _blog_fixture_checks(cmd, ws, approver, editor, outsider, client_for, tag):
    from django.core.exceptions import PermissionDenied
    from django.urls import reverse

    from apps.approvals.actor import API, DASHBOARD, acting_as
    from apps.blog import services as blog
    from apps.blog.models import BlogSite

    site = BlogSite.objects.create(
        workspace=ws,
        name="Fixture site",
        kind="neopolis_static",
        site_url="https://www.neopolisinfra.com",
        repo="hemantsatishjadhav06-ai/neopolis-site-deploy",
        workflow_file="publish3.yml",
    )
    post = blog.create_post(
        workspace=ws, site=site, author=editor, title=f"Fixture {tag}", slug=f"fixture-{tag}", body="Body text."
    )
    blog.submit_for_review(post, editor)

    refused = []
    for user, channel in ((None, "system"), (approver, API), (editor, DASHBOARD)):
        try:
            with acting_as(user, channel):
                blog.approve(post)
            refused.append(False)
        except PermissionDenied:
            refused.append(True)
    post.refresh_from_db()
    cmd.record(
        "PASS" if all(refused) and post.status == "pending_review" else "FAIL",
        "blog.only_dashboard_approver_approves",
        f"refused for system/api/editor={refused}, status={post.status}",
    )

    preview = reverse("blog:preview", kwargs={"workspace_id": ws.id, "post_id": post.id})
    outsider_code = client_for(outsider).get(preview).status_code
    approver_resp = client_for(approver).get(preview)
    private = approver_resp.status_code == 200 and "noindex" in approver_resp.get("X-Robots-Tag", "")
    cmd.record(
        "PASS" if outsider_code in (403, 404) and private else "FAIL",
        "blog.preview_private",
        f"outsider HTTP {outsider_code}; approver HTTP {approver_resp.status_code}, "
        f"X-Robots-Tag={approver_resp.get('X-Robots-Tag', '')!r}",
    )

    with acting_as(approver, DASHBOARD):
        blog.approve(post)
    post.refresh_from_db()
    blog.update_content(post, approver, body="Edited after approval.")
    post.refresh_from_db()
    cmd.record(
        "PASS" if post.status == "pending_review" and not post.approved_fingerprint else "FAIL",
        "blog.edit_withdraws_approval",
        f"status={post.status}",
    )

    with acting_as(approver, DASHBOARD):
        blog.approve(post)
    post.refresh_from_db()
    if blog.github_token():
        cmd.record("INFO", "blog.publish_ready", "token present; approved posts can be published from the dashboard")
    else:
        try:
            with acting_as(approver, DASHBOARD):
                blog.start_publish(post)
            cmd.record("FAIL", "blog.publish_without_token", "started without a token")
        except Exception as exc:
            post.refresh_from_db()
            cmd.record(
                "PASS" if post.status == "approved" else "FAIL",
                "blog.publish_without_token",
                f"refused ({type(exc).__name__}); post stays {post.status}, nothing written to GitHub",
            )


def _json(data):
    return json.dumps(data, default=str, separators=(",", ":"))


def _same_thread(fn, *args, **kwargs):
    return fn(*args, **kwargs)


class _InlineExecutor:
    """Runs submitted work immediately on the calling thread."""

    def submit(self, fn, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:
            future.set_exception(exc)
        return future
