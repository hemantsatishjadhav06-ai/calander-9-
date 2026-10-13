"""Unusable-password clients pair Telegram through their real scoped login link."""

from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.client_portal.models import MagicLinkToken
from apps.client_portal.services import revoke_magic_link
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.telegram import provisioning
from apps.telegram.models import TelegramConnection, TelegramPairing, TelegramUserLink
from apps.workspaces.models import Workspace


class PortalTelegramOnboardingTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Client agency")
        self.workspace = Workspace.objects.create(organization=self.org, name="Client company")
        self.user = User.objects.create_user(email="external-client@example.test", tos_accepted_at=timezone.now())
        self.user.set_unusable_password()
        self.user.save(update_fields=["password"])
        WorkspaceMembership.objects.create(user=self.user, workspace=self.workspace, workspace_role="client")
        self.token = MagicLinkToken.objects.create(user=self.user, workspace=self.workspace)
        self.connection = TelegramConnection.objects.create(
            workspace=self.workspace,
            bot_id=123456,
            bot_username="client_company_bot",
            token="123456:" + "f" * 32,
            webhook_secret="private-webhook-secret",
            is_active=True,
            webhook_status="active",
        )

    def _login(self, browser=None, *, csrf=False):
        browser = browser or self.client
        entry = reverse("client_portal:magic_link_entry", kwargs={"token": self.token.token})
        headers = {}
        if csrf:
            self.assertEqual(browser.get(entry, secure=True).status_code, 200)
            headers = {"HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value, "HTTP_ORIGIN": "https://testserver"}
        response = browser.post(entry, secure=csrf, **headers)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(browser.session["portal_token_id"], str(self.token.id))
        return browser

    def _nonce(self, response):
        self.assertEqual(response.status_code, 200)
        nonce = parse_qs(urlsplit(response.context["pairing_url"]).query)["start"][0]
        self.assertEqual(response.context["pairing_command"], f"/start {nonce}")
        return nonce

    def test_client_without_password_or_org_membership_can_pair_privately(self):
        self.assertFalse(self.user.has_usable_password())
        self.assertFalse(OrgMembership.objects.filter(user=self.user, organization=self.org).exists())
        self._login()
        page = self.client.get(reverse("client_portal:telegram"))
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.context["can_pair"])
        self.assertNotContains(page, self.connection.token)
        self.assertNotContains(page, self.connection.webhook_secret)
        self.assertEqual(page["Cache-Control"], "no-store")
        self.assertEqual(page["Referrer-Policy"], "same-origin")
        self.assertFalse(TelegramPairing.objects.exists())

        with patch("apps.telegram.provisioning.BotAPI") as api:
            response = self.client.post(reverse("client_portal:telegram_pair"))
            nonce = self._nonce(response)
            ticket = TelegramPairing.objects.get()
            self.assertEqual(
                (ticket.connection_id, ticket.user_id, ticket.purpose, ticket.audience),
                (self.connection.id, self.user.id, "user", "private"),
            )
            self.assertEqual(ticket.token_digest, provisioning.digest(nonce))
            self.assertNotEqual(ticket.token_digest, nonce)
            link = provisioning.consume_pairing_message(
                self.connection,
                {
                    "text": f"/start {nonce}",
                    "from": {"id": 9001, "is_bot": False},
                    "chat": {"id": 9001, "type": "private"},
                },
            )
            api.assert_not_called()
        private = self.connection.chats.get()
        self.assertEqual(link.user_id, self.user.id)
        self.assertEqual((private.audience, private.private_user_id), ("private", self.user.id))
        self.assertTrue(private.conversation.is_private)
        self.assertEqual(private.conversation.audience, "client")
        self.assertFalse(OrgMembership.objects.filter(user=self.user, organization=self.org).exists())
        self.assertContains(self.client.get(reverse("client_portal:telegram")), "client_company_bot")

    def test_get_does_not_reissue_or_redisplay_pairing_code(self):
        self._login()
        response = self.client.post(reverse("client_portal:telegram_pair"))
        nonce = self._nonce(response)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        for _ in range(2):
            page = self.client.get(reverse("client_portal:telegram"))
            self.assertNotContains(page, nonce)
            self.assertEqual(page.context["pairing_url"], "")
        self.assertEqual(TelegramPairing.objects.count(), 1)
        self.assertEqual(self.client.get(reverse("client_portal:telegram_pair")).status_code, 405)
        self.assertEqual(self.client.get(reverse("client_portal:telegram_unpair")).status_code, 405)
        self.assertEqual(TelegramPairing.objects.count(), 1)

    def test_join_link_uses_the_bot_identity_rechecked_during_pairing(self):
        self._login()
        issue_pairing = provisioning.issue_pairing

        def rename_before_issue(*args, **kwargs):
            self.connection.bot_username = "fresh_company_bot"
            self.connection.save(update_fields=["bot_username", "updated_at"])
            return issue_pairing(*args, **kwargs)

        with patch("apps.telegram.provisioning.issue_pairing", side_effect=rename_before_issue):
            response = self.client.post(reverse("client_portal:telegram_pair"))
        self._nonce(response)
        self.assertEqual(urlsplit(response.context["pairing_url"]).path, "/fresh_company_bot")

    def test_posted_workspace_user_and_group_scope_cannot_change_pairing_authority(self):
        foreign = Workspace.objects.create(organization=self.org, name="Foreign client company")
        foreign_connection = TelegramConnection.objects.create(
            workspace=foreign,
            bot_id=654321,
            token="654321:" + "g" * 32,
            webhook_secret="other-secret",
            is_active=True,
            webhook_status="active",
        )
        other = User.objects.create_user(email="other-client@example.test", tos_accepted_at=timezone.now())
        self._login()
        response = self.client.post(
            reverse("client_portal:telegram_pair"),
            {
                "workspace_id": str(foreign.id),
                "connection_id": str(foreign_connection.id),
                "user_id": str(other.id),
                "purpose": "chat",
                "audience": "team",
                "group_membership_confirmed": "on",
                "approvals_enabled": "on",
            },
        )
        self._nonce(response)
        ticket = TelegramPairing.objects.get()
        self.assertEqual(
            (ticket.connection_id, ticket.user_id, ticket.purpose, ticket.audience),
            (self.connection.id, self.user.id, "user", "private"),
        )
        self.assertFalse(TelegramPairing.objects.filter(connection=foreign_connection).exists())
        self.connection.refresh_from_db()
        self.assertFalse(self.connection.approvals_enabled)

    def test_unpair_removes_only_this_person_in_the_token_workspace(self):
        other = User.objects.create_user(email="paired-teammate@example.test", tos_accepted_at=timezone.now())
        link = TelegramUserLink.objects.create(connection=self.connection, user=self.user, telegram_user_id=9001)
        other_link = TelegramUserLink.objects.create(connection=self.connection, user=other, telegram_user_id=9002)
        foreign = Workspace.objects.create(organization=self.org, name="Another company")
        foreign_connection = TelegramConnection.objects.create(
            workspace=foreign,
            bot_id=654321,
            token="654321:" + "g" * 32,
            webhook_secret="other-secret",
            is_active=True,
            webhook_status="active",
        )
        foreign_link = TelegramUserLink.objects.create(
            connection=foreign_connection, user=self.user, telegram_user_id=9001
        )
        self._login()
        response = self.client.post(
            reverse("client_portal:telegram_unpair"),
            {
                "user_id": str(other.id),
                "workspace_id": str(foreign.id),
                "connection_id": str(foreign_connection.id),
            },
        )
        self.assertRedirects(response, reverse("client_portal:telegram"))
        link.refresh_from_db()
        other_link.refresh_from_db()
        foreign_link.refresh_from_db()
        self.assertFalse(link.is_active)
        self.assertTrue(other_link.is_active)
        self.assertTrue(foreign_link.is_active)

    def test_login_token_cannot_be_rebound_to_another_client_workspace(self):
        foreign = Workspace.objects.create(organization=self.org, name="Another client company")
        WorkspaceMembership.objects.create(user=self.user, workspace=foreign, workspace_role="client")
        self._login()
        session = self.client.session
        session["portal_workspace_id"] = str(foreign.id)
        session.save()
        response = self.client.post(reverse("client_portal:telegram_pair"))
        self.assertRedirects(response, reverse("client_portal:magic_link_expired") + "?reason=signed_out")
        self.assertFalse(TelegramPairing.objects.exists())

    def test_revoked_token_blocks_get_pair_and_unpair(self):
        self._login()
        link = TelegramUserLink.objects.create(connection=self.connection, user=self.user, telegram_user_id=9001)
        revoke_magic_link(self.token.id, self.workspace)
        for name, method in [("telegram", "get"), ("telegram_pair", "post"), ("telegram_unpair", "post")]:
            response = getattr(self.client, method)(reverse(f"client_portal:{name}"))
            self.assertRedirects(response, reverse("client_portal:magic_link_expired") + "?reason=signed_out")
        self.assertFalse(TelegramPairing.objects.exists())
        link.refresh_from_db()
        self.assertTrue(link.is_active)

    def test_no_staff_controls_or_full_application_access_are_granted(self):
        self._login()
        page = self.client.get(reverse("client_portal:telegram"))
        for name in ("can_manage", "can_pair_group", "managed_form", "chats", "tabs", "deliveries", "updates"):
            self.assertNotIn(name, page.context)
        for name in ("connect", "managed_create", "disconnect"):
            self.assertNotContains(page, reverse(f"telegram:{name}", kwargs={"workspace_id": self.workspace.id}))
        self.assertEqual(
            self.client.get(reverse("telegram:settings", kwargs={"workspace_id": self.workspace.id})).status_code, 403
        )
        self.assertEqual(self.client.post("/portal/telegram/connect/", {"token": "injected"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("accounts:settings")).status_code, 403)

    def test_inactive_bot_explains_blocker_without_issuing_code(self):
        self.connection.is_active = False
        self.connection.save(update_fields=["is_active"])
        self._login()
        page = self.client.get(reverse("client_portal:telegram"))
        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.context["can_pair"])
        response = self.client.post(reverse("client_portal:telegram_pair"))
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Ask your account manager", status_code=400)
        self.assertFalse(TelegramPairing.objects.exists())

    def test_actual_csrf_protection_accepts_same_origin_personal_pairing(self):
        browser = self._login(Client(enforce_csrf_checks=True), csrf=True)
        page = browser.get(reverse("client_portal:telegram"), secure=True)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(browser.post(reverse("client_portal:telegram_pair"), secure=True).status_code, 403)
        self.assertFalse(TelegramPairing.objects.exists())
        headers = {"HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value, "HTTP_ORIGIN": "https://testserver"}
        response = browser.post(reverse("client_portal:telegram_pair"), secure=True, **headers)
        self._nonce(response)
        self.assertEqual(TelegramPairing.objects.count(), 1)
        self.assertEqual(browser.post(reverse("client_portal:telegram_unpair"), secure=True).status_code, 403)
        self.assertEqual(
            browser.post(reverse("client_portal:telegram_unpair"), secure=True, **headers).status_code, 302
        )
