"""The agency's links to Approvals lead to the Approvals screen (spec D3).

``approvals:index`` (``/workspace/<id>/approvals/``) is where the sidebar, the
phone bar and Home send people. The other ways in from the agency go there too:
Home's "Open approvals" under the waiting list, the live board's "N to approve",
the onboarding checklist's "Review your first draft" and the version history's
back link. Someone the screen refuses (a plain client, who approves in the
portal) keeps the Calendar's Approvals tab, which still renders. Links already
sent by Telegram and email are left alone (test_inbox, test_briefing,
test_deadline_reminders).
"""

from __future__ import annotations

import re

from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.onboarding.checklist import get_checklist_items
from apps.studio import live
from apps.studio.models import StudioBrief


def _url(name, world, **kwargs):
    return reverse(name, kwargs={"workspace_id": world.workspace.id, **kwargs})


def _old_tab(world) -> str:
    return _url("calendar:calendar", world) + "?mode=list&tab=approvals"


def _plain_client(world) -> User:
    user = User.objects.create_user(
        email="client@example.com", password="pw-12345678", name="Client", tos_accepted_at=timezone.now()
    )
    OrgMembership.objects.create(user=user, organization=world.org, org_role="member")
    WorkspaceMembership.objects.create(user=user, workspace=world.workspace, workspace_role="client")
    return user


def test_homes_open_approvals_leads_to_the_approvals_screen(client, world):
    for index in range(4):  # Home lists three; the fourth makes "and 1 more · Open approvals"
        StudioBrief.objects.create(
            workspace=world.workspace, author=world.editor, idea=f"Ready draft {index}", status="ready"
        )
    client.force_login(world.owner)

    html = client.get(_url("studio:index", world)).content.decode()

    link = re.search(r'<a [^>]*href="([^"]*)"[^>]*>Open approvals</a>', html)
    assert link, "Home shows the Open approvals link with four drafts waiting"
    assert link.group(1) == _url("approvals:index", world)


def test_the_live_boards_approvals_link_leads_to_the_approvals_screen(world):
    assert live.snapshot(world.workspace)["approvals_url"] == _url("approvals:index", world)


def test_the_onboarding_checklists_review_step_leads_to_the_approvals_screen(world):
    items = {item["key"]: item for item in get_checklist_items(world.workspace)}

    assert items["review_draft"]["url"] == _url("approvals:index", world)
    # The published step still opens the Calendar's Sent list.
    assert items["published_post"]["url"] == _url("calendar:calendar", world) + "?mode=list&tab=sent"


def test_version_historys_back_link_leads_staff_to_the_approvals_screen_and_a_client_to_the_tab(client, world):
    post = Post.objects.create(workspace=world.workspace, author=world.editor, caption="A post with a history")
    history = _url("approvals:version_diff", world, post_id=post.pk)
    back = re.compile(r'<a aria-label="Back to approvals" href="([^"]*)"')

    for user in (world.owner, world.viewer):
        client.force_login(user)
        response = client.get(history)
        assert response.status_code == 200
        assert back.search(response.content.decode()).group(1) == _url("approvals:index", world), user.email

    # A plain client may read the history but not the Approvals screen: their link stays on the tab.
    client.force_login(_plain_client(world))
    response = client.get(history)
    assert response.status_code == 200
    assert back.search(response.content.decode()).group(1) == _old_tab(world).replace("&", "&amp;")
    assert client.get(_url("approvals:index", world)).status_code == 403
