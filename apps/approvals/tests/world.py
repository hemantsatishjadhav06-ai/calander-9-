"""The publishing world the Approvals tests and the screen registry's drift check share.

One workspace that requires internal approval, a member per role (owner, editor, viewer, client),
connected Facebook and LinkedIn pages, and ``post(status, …)`` for a post in any state.

``apps/approvals/tests/test_index.py`` (a test file screens move deliberately, spec D11) and
``apps/common/tests/test_screens.py``'s drift check both build on it, so it lives here rather than
inside either: a change to it changes what both render, and the drift check asserts that the
templates it exists to see (the selects and the status pills) still render from it.
"""

from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


def person(email):
    """A person with no organisation or workspace of their own (sign-up may create one)."""
    user = User.objects.create_user(email=email, password="pw-12345678", tos_accepted_at=timezone.now())
    own = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=own).delete()
    return user


class World:
    def __init__(self):
        self.org = Organization.objects.create(name="Agency")
        self.workspace = Workspace.objects.create(
            organization=self.org,
            name="Neopolis",
            timezone="Asia/Kolkata",
            approval_workflow_mode="required_internal",
            require_dashboard_approval=True,
        )
        self.owner = self._member("owner@example.com", "owner")
        self.editor = self._member("editor@example.com", "editor")
        self.viewer = self._member("viewer@example.com", "viewer")
        self.client_user = self._member("client@example.com", "client")
        self.facebook = self._account("facebook", "Neopolis Facebook")
        self.linkedin = self._account("linkedin_company", "Neopolis LinkedIn")

    def _member(self, email, role):
        user = person(email)
        if role == "owner":
            OrgMembership.objects.create(user=user, organization=self.org, org_role="owner")
        WorkspaceMembership.objects.create(user=user, workspace=self.workspace, workspace_role=role)
        return user

    def _account(self, platform, name):
        return SocialAccount.objects.create(
            workspace=self.workspace,
            platform=platform,
            account_platform_id=f"{platform}-1",
            account_name=name,
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )

    def post(self, status, *, account=None, tags=(), when=None, caption=None):
        post = Post.objects.create(
            workspace=self.workspace,
            author=self.editor,
            caption=caption or f"A post that is {status}",
            tags=list(tags),
            proposed_publish_at=when,
        )
        pp = PlatformPost.objects.create(post=post, social_account=account or self.facebook, status="pending_review")
        # Rows in other states are fixtures, not the result of a decision: skip the gate's save checks.
        PlatformPost.objects.filter(pk=pp.pk).update(status=status)
        return post
