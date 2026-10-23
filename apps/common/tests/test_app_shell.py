"""The app shell scrolls inside <main>; the window must not scroll past it.

Neither scroller was positioned, so every absolutely placed element in a page
(each ``sr-only`` label, the Team page's live region) took the window as its
containing block. Below the fold they stretched the document: on the Team
page the window scrolled 2,000px past the shell into blank canvas. Both
scrollers are now the containing block for what they hold.
"""

import re

import pytest


@pytest.mark.django_db
def test_the_shell_scrollers_contain_absolutely_placed_content(client, org_owner, user, organization):
    from apps.members.models import WorkspaceMembership
    from apps.workspaces.models import Workspace

    workspace = Workspace.objects.create(name="Shell WS", organization=organization)
    WorkspaceMembership.objects.create(user=user, workspace=workspace, workspace_role="owner")
    client.force_login(user)

    html = client.get("/notifications/", follow=True).content.decode()

    main = re.search(r'<main id="main-content"[^>]*class="([^"]*)"', html)
    assert main, "the app shell is rendered"
    assert "overflow-y-auto" in main.group(1).split() and "relative" in main.group(1).split()
    scrollers = re.findall(r'<div class="([^"]*\boverflow-y-auto\b[^"]*\boverflow-x-hidden\b[^"]*)"', html)
    assert scrollers, "the content scroller is rendered"
    assert all("relative" in classes.split() for classes in scrollers)
