"""Every sidebar link has a name, also when the desktop sidebar is collapsed.

The collapsed sidebar (60px, base.html and styles.css ``.sidebar-collapsed``) hides each
link's label and badge with ``display: none``, which takes them out of the accessibility
tree. Approvals always carried its name in an ``aria-label`` ("Approvals, 2 waiting"); the
other places and the Settings gear now do the same, with their count where they show one,
so a screen reader names Home, Activity, Blog and Settings in either state.
"""

from types import SimpleNamespace

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.common.features import FEATURE_KEYS
from apps.composer.models import PlatformPost, Post
from apps.inbox.models import InboxMessage
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import AnalyticsPlatformConfig, SocialAccount
from apps.studio.models import AgencySettings
from apps.workspaces.models import Workspace

LABELS = {
    "home": "Home",
    "approvals": "Approvals",
    "calendar": "Calendar",
    "inbox": "Inbox",
    "analytics": "Analytics",
    "activity": "Activity",
    "blog": "Blog",
    "settings": "Settings",
}


@pytest.fixture
def owner_world(db):
    org = Organization.objects.create(name="Org")
    ws = Workspace.objects.create(organization=org, name="WS")
    owner = User.objects.create_user(email="owner@example.com", password="pw", tos_accepted_at=timezone.now())
    OrgMembership.objects.update_or_create(user=owner, organization=org, defaults={"org_role": "owner"})
    WorkspaceMembership.objects.create(user=owner, workspace=ws, workspace_role="owner")
    AnalyticsPlatformConfig.objects.update(is_enabled=True)
    features = {key: False for key in FEATURE_KEYS}
    features["blog"] = True
    AgencySettings.objects.update_or_create(workspace=ws, defaults={"features": features})
    account = SocialAccount.objects.create(
        workspace=ws,
        platform="linkedin_company",
        account_platform_id="li-1",
        account_name="Li",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    return SimpleNamespace(ws=ws, owner=owner, account=account)


def _tag(html: str, marker: str) -> str:
    at = html.index(marker)
    return html[html.rindex("<", 0, at) : html.index(">", at) + 1]


def _sidebar_tags(client, world) -> dict[str, str]:
    client.force_login(world.owner)
    html = client.get(reverse("calendar:calendar", kwargs={"workspace_id": world.ws.id})).content.decode()
    assert "{#" not in html and "#}" not in html  # a template comment never leaks into the page
    sidebar = html[html.index('id="app-sidebar"') : html.index("</aside>")]
    keys = [key for key in LABELS if f'data-testid="nav-{key}"' in sidebar]
    return {key: _tag(sidebar, f'data-testid="nav-{key}"') for key in keys}


def test_every_sidebar_link_is_named_like_approvals(client, owner_world):
    tags = _sidebar_tags(client, owner_world)

    assert list(tags) == list(LABELS)  # every place (Analytics and Blog on) and the gear
    for key, tag in tags.items():
        assert f'aria-label="{LABELS[key]}"' in tag, key


def test_a_count_is_part_of_the_name(client, owner_world):
    for index in range(2):
        post = Post.objects.create(workspace=owner_world.ws, author=owner_world.owner, caption=f"waiting {index}")
        PlatformPost.objects.create(post=post, social_account=owner_world.account, status="pending_review")
    for index in range(3):
        InboxMessage.objects.create(
            workspace=owner_world.ws,
            social_account=owner_world.account,
            platform_message_id=f"unread-{index}",
            sender_name="Ada",
            body="Hello?",
            received_at=timezone.now(),
        )

    tags = _sidebar_tags(client, owner_world)

    assert 'aria-label="Approvals, 2 waiting"' in tags["approvals"]
    assert 'aria-label="Inbox, 3 unread"' in tags["inbox"]
    assert 'aria-label="Home"' in tags["home"] and 'aria-label="Settings"' in tags["settings"]
