"""Launch review: who may create an account, and what the public pages promise.

The CEO and CMO reviews both put an invite-only private beta before any public
launch. Signup was open to anyone, with no switch to close it.
"""

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import Invitation, OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


def _signup(client, email):
    return client.post(reverse("account_signup"), {"email": email, "password1": "a-Strong-passw0rd!"})


@override_settings(SIGNUP_MODE="invite_only", SIGNUP_ALLOWLIST=[])
class InviteOnlyTests(TestCase):
    def test_a_stranger_sees_the_invite_only_page_and_no_account_is_made(self):
        page = self.client.get(reverse("account_signup"))
        self.assertContains(page, "invite-only")
        _signup(self.client, "stranger@example.com")
        self.assertFalse(User.objects.filter(email="stranger@example.com").exists())

    def test_an_invitation_link_still_gets_through(self):
        owner = User.objects.create_user(
            email="owner@example.com", password="pw", name="O", tos_accepted_at=timezone.now()
        )
        org = Organization.objects.create(name="Agency")
        Workspace.objects.create(organization=org, name="Client A")
        OrgMembership.objects.get_or_create(user=owner, organization=org, defaults={"org_role": "owner"})
        invitation = Invitation.objects.create(
            organization=org,
            email="new@example.com",
            org_role="member",
            workspace_assignments=[],
            invited_by=owner,
            expires_at=timezone.now() + timezone.timedelta(days=7),
        )
        session = self.client.session
        session["pending_invite_token"] = invitation.token
        session.save()

        _signup(self.client, "new@example.com")

        user = User.objects.get(email="new@example.com")
        self.assertTrue(OrgMembership.objects.filter(user=user, organization=org).exists())

    def test_an_expired_invitation_does_not(self):
        owner = User.objects.create_user(
            email="owner@example.com", password="pw", name="O", tos_accepted_at=timezone.now()
        )
        org = Organization.objects.create(name="Agency")
        invitation = Invitation.objects.create(
            organization=org,
            email="late@example.com",
            org_role="member",
            workspace_assignments=[],
            invited_by=owner,
            expires_at=timezone.now() - timezone.timedelta(days=1),
        )
        session = self.client.session
        session["pending_invite_token"] = invitation.token
        session.save()
        _signup(self.client, "late@example.com")
        self.assertFalse(User.objects.filter(email="late@example.com").exists())

    @override_settings(SIGNUP_ALLOWLIST=["@agency.com", "ana@partner.io"])
    def test_the_allowlist_admits_listed_addresses_and_domains_only(self):
        _signup(self.client, "bo@agency.com")
        self.client.logout()
        _signup(self.client, "ana@partner.io")
        self.client.logout()
        response = _signup(self.client, "eve@elsewhere.com")
        self.assertTrue(User.objects.filter(email="bo@agency.com").exists())
        self.assertTrue(User.objects.filter(email="ana@partner.io").exists())
        self.assertFalse(User.objects.filter(email="eve@elsewhere.com").exists())
        self.assertContains(response, "hasn&#x27;t been invited")

    def test_public_ctas_ask_for_access_instead_of_signup(self):
        landing = self.client.get("/")
        self.assertContains(landing, "Request early access")
        self.assertNotContains(landing, "Get started free")
        self.assertContains(self.client.get(reverse("pricing")), "Request access")


@override_settings(SIGNUP_MODE="open")
class OpenSignupTests(TestCase):
    def test_anyone_can_sign_up_and_ctas_say_so(self):
        _signup(self.client, "anyone@example.com")
        self.assertTrue(User.objects.filter(email="anyone@example.com").exists())
        self.client.logout()
        self.assertContains(self.client.get("/"), "Get started free")


class PublicClaimsTests(TestCase):
    """Claims the CEO and CMO reviews said we cannot stand behind today."""

    def test_no_promise_of_things_that_do_not_exist(self):
        pages = self.client.get("/").content.decode() + self.client.get(reverse("pricing")).content.decode()
        for claim in (
            "export and move your data whenever you like",
            "Daily backups &amp; uptime monitoring",
            "White-label branding &amp; custom domain",
            "Priority support &amp; SLA",
            "publish across 11 platforms",
        ):
            with self.subTest(claim=claim):
                self.assertNotIn(claim, pages)


class ConnectPageCopyTests(TestCase):
    def test_customers_see_coming_soon_not_server_admin_instructions(self):
        user = User.objects.create_user(email="u@example.com", password="pw", name="U", tos_accepted_at=timezone.now())
        auto = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
        WorkspaceMembership.objects.filter(user=user).delete()
        OrgMembership.objects.filter(user=user).delete()
        Organization.objects.filter(id__in=auto).delete()
        org = Organization.objects.create(name="Org")
        ws = Workspace.objects.create(organization=org, name="WS")
        OrgMembership.objects.create(user=user, organization=org, org_role="owner")
        WorkspaceMembership.objects.create(user=user, workspace=ws, workspace_role="owner")
        self.client.force_login(user)
        page = self.client.get(reverse("social_accounts:connect", kwargs={"workspace_id": ws.id}))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "PLATFORM_*")
        self.assertContains(page, "Coming soon")
