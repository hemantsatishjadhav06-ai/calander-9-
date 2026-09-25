"""A client can still pull a post after the team has scheduled it.

``request_hold`` was eligible from ``approved`` only, so the moment the team
put an approved post on the calendar it left the client's reach — "pull it,
it goes out in twenty minutes" had no path. The portal's list and its hold
guard both filtered on ``approved`` too.

A held post lifts back to ``approved``, never straight to ``scheduled``: the
team re-confirms the time. That edge was already deliberate.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals import services
from apps.client_portal.services import generate_magic_link
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.publisher.engine import PublishEngine
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace

WR = WorkspaceMembership.WorkspaceRole


def _user(email):
    user = User.objects.create_user(
        email=email, password="pw", name=email.split("@")[0], tos_accepted_at=timezone.now()
    )
    auto_org_ids = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto_org_ids).delete()
    return user


def _world():
    org = Organization.objects.create(name="Org")
    ws = Workspace.objects.create(organization=org, name="WS")
    manager = _user("manager@example.com")
    client_user = _user("client@example.com")
    OrgMembership.objects.create(user=manager, organization=org, org_role="owner")
    OrgMembership.objects.create(user=client_user, organization=org, org_role="member")
    WorkspaceMembership.objects.create(user=manager, workspace=ws, workspace_role=WR.MANAGER)
    WorkspaceMembership.objects.create(user=client_user, workspace=ws, workspace_role=WR.CLIENT)
    account = SocialAccount.objects.create(
        workspace=ws,
        platform="bluesky",
        account_platform_id="did",
        account_name="a",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    return org, ws, manager, client_user, account


def _scheduled_post(ws, author, account, when=None):
    when = when or (timezone.now() + timedelta(hours=1))
    post = Post.objects.create(workspace=ws, author=author, caption="risky claim", scheduled_at=when)
    PlatformPost.objects.create(
        post=post, social_account=account, status=PlatformPost.Status.SCHEDULED, scheduled_at=when
    )
    return post


class HoldFromScheduledServiceTests(TestCase):
    def setUp(self):
        self.org, self.ws, self.manager, self.client_user, self.account = _world()

    def test_a_scheduled_post_can_be_held_and_resumes_to_approved(self):
        post = _scheduled_post(self.ws, self.manager, self.account)

        services.request_hold(post, self.client_user, self.ws, "Legal wants to check the figures")
        self.assertEqual(post.platform_posts.get().status, "on_hold")

        services.resume_hold(post, self.manager, self.ws)
        # Back to approved for the team to re-schedule — never straight to scheduled.
        self.assertEqual(post.platform_posts.get().status, "approved")

    def test_a_post_the_publisher_has_claimed_is_not_held(self):
        """Lost race, reported honestly: nothing to update rather than a half-cancel."""
        post = _scheduled_post(self.ws, self.manager, self.account)
        PlatformPost.objects.filter(post=post).update(status=PlatformPost.Status.PUBLISHING)

        result = services.request_hold(post, self.client_user, self.ws, "too late?")
        self.assertEqual(result, [])
        self.assertEqual(post.platform_posts.get().status, "publishing")


class HeldPostDoesNotPublishTests(TransactionTestCase):
    """The publisher polls ``scheduled`` rows; a hold placed on a due post must keep it off the wire."""

    def test_publish_cycle_skips_a_post_held_after_scheduling(self):
        org, ws, manager, client_user, account = _world()
        post = _scheduled_post(ws, manager, account, when=timezone.now() - timedelta(minutes=1))
        services.request_hold(post, client_user, ws, "Pull it")

        provider = MagicMock()
        with patch("apps.publisher.engine._provider_and_access_token", return_value=(provider, "tok")):
            PublishEngine().poll_and_publish()

        self.assertFalse(provider.publish_post.called)
        self.assertEqual(post.platform_posts.get().status, "on_hold")


class PortalHoldViewTests(TestCase):
    def setUp(self):
        self.org, self.ws, self.manager, self.client_user, self.account = _world()
        token = generate_magic_link(workspace=self.ws, client_user=self.client_user, created_by=self.manager)
        # GET renders a confirmation page without consuming; POST consumes and opens the session.
        entry = reverse("client_portal:magic_link_entry", kwargs={"token": token.token})
        response = self.client.post(entry)
        assert response.status_code in (200, 302), response.status_code

    def test_the_portal_lets_a_client_hold_a_scheduled_post(self):
        post = _scheduled_post(self.ws, self.manager, self.account)

        response = self.client.post(
            reverse("client_portal:request_hold", kwargs={"post_id": post.id}),
            {"comment": "Hold this, the figures changed"},
        )

        self.assertNotEqual(response.status_code, 404)
        self.assertEqual(post.platform_posts.get().status, "on_hold")

    def test_the_portal_lists_a_scheduled_post_with_a_hold_button(self):
        post = _scheduled_post(self.ws, self.manager, self.account)
        response = self.client.get(reverse("client_portal:approval_queue"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Put on hold")
        self.assertContains(response, reverse("client_portal:request_hold", kwargs={"post_id": post.id}))
