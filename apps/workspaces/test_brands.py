"""Brand workspaces: setup is idempotent, seeding never approves, the picker
points at the right Page."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.settings_manager.models import WorkspaceSetting
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


def _owner():
    user = User.objects.create_user(email="owner@example.com", password="pw-12345678", tos_accepted_at=timezone.now())
    if not OrgMembership.objects.filter(user=user).exists():
        org = Organization.objects.create(name="Owner Org")
        OrgMembership.objects.create(user=user, organization=org, org_role="owner")
    return user


class SetupBrandsTests(TestCase):
    def setUp(self):
        self.owner = _owner()
        self.org = OrgMembership.objects.get(user=self.owner).organization

    def _run(self, name="setup_brands"):
        out = StringIO()
        call_command(name, approver_email=self.owner.email, stdout=out)
        return out.getvalue()

    def test_creates_both_workspaces_enforced_in_ist(self):
        self._run()
        for name in ("Neopolis", "More Space"):
            ws = Workspace.objects.get(organization=self.org, name=name)
            self.assertTrue(ws.require_dashboard_approval)
            self.assertEqual(ws.timezone, "Asia/Kolkata")
            self.assertEqual(ws.approval_workflow_mode, "required_internal")
            self.assertTrue(
                WorkspaceMembership.objects.filter(user=self.owner, workspace=ws, workspace_role="owner").exists()
            )

    def test_reuses_an_existing_workspace_and_is_idempotent(self):
        existing = Workspace.objects.create(organization=self.org, name="neopolis infra")
        self._run()
        self._run()
        self.assertEqual(Workspace.objects.filter(organization=self.org, name__iexact="neopolis infra").count(), 1)
        self.assertFalse(Workspace.objects.filter(organization=self.org, name="Neopolis").exists())
        existing.refresh_from_db()
        self.assertTrue(existing.require_dashboard_approval)
        self.assertEqual(Workspace.objects.filter(organization=self.org).count(), 3)  # + More Space + default

    def test_seeding_creates_drafts_once_and_never_approves(self):
        with patch("apps.workspaces.management.commands.seed_brand_content.fetch_image", return_value=None):
            self._run("seed_brand_content")
            neopolis = Workspace.objects.get(organization=self.org, name="Neopolis")
            SocialAccount.objects.create(
                workspace=neopolis,
                platform="facebook",
                account_platform_id="585141221346435",
                account_name="Neopolis Infra",
                connection_status="connected",
            )
            self._run("seed_brand_content")
        posts = Post.objects.filter(workspace=neopolis)
        self.assertEqual(posts.count(), 4)
        statuses = {pp.status for post in posts for pp in post.platform_posts.all()}
        self.assertEqual(statuses, {"pending_review"})
        self.assertTrue(all(p.proposed_publish_at for p in posts))
        # A deleted seed draft is not recreated.
        posts.first().delete()
        with patch("apps.workspaces.management.commands.seed_brand_content.fetch_image", return_value=None):
            self._run("seed_brand_content")
        self.assertEqual(Post.objects.filter(workspace=neopolis).count(), 3)


class PickerHintTests(TestCase):
    def test_the_other_brands_page_is_flagged(self):
        owner = _owner()
        call_command("setup_brands", approver_email=owner.email, stdout=StringIO())
        neopolis = Workspace.objects.get(name="Neopolis")
        self.assertTrue(WorkspaceSetting.objects.filter(workspace=neopolis, key="brand.key").exists())
        self.client.force_login(owner)
        session = self.client.session
        session["oauth_page_select"] = {
            "workspace_id": str(neopolis.id),
            "platform": "facebook",
            "pages": [
                {"id": "585141221346435", "name": "Neopolis Infra", "access_token": "t1", "tasks": ["CREATE_CONTENT"]},
                {"id": "1282011328339050", "name": "More Space", "access_token": "t2", "tasks": ["CREATE_CONTENT"]},
            ],
            "tokens": {},
        }
        session.save()
        body = self.client.get(reverse("social_accounts:select_account")).content.decode()
        self.assertIn("This brand's account", body)
        self.assertIn("Belongs to your other brand", body)
