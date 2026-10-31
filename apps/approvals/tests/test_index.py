"""The Approvals screen at ``/workspace/<id>/approvals/`` (spec D3, R3; plan T3).

It is the Calendar list's Approvals tab on a page of its own: the same rows from
the same query, the same refresh endpoint, the same filters and the same
controls for the same person. Approving from it posts to the unchanged
``approvals:*`` endpoints, so the gate applies exactly as it does on the tab.

- An owner sees the rows the tab shows for the same data and the same filters.
- *Approve & schedule* posts to ``approvals:approve``; the gate stamps the
  reviewed content and time for an internal approver and refuses an editor.
- A viewer reads the list without a control, exactly like the tab.
- A plain client is refused (403), like the agency's other screens; a member of
  another workspace is refused; an anonymous visitor is sent to sign in.
- The navigation's Approvals item leads here and is lit here.
- The Calendar's own Approvals tab keeps rendering.
"""

import re
from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from django.conf import settings
from django.test import RequestFactory
from django.urls import resolve, reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals import gate
from apps.approvals.actor import DASHBOARD
from apps.approvals.models import ApprovalAction
from apps.common.navigation import build_nav
from apps.composer.models import PlatformPost, Post
from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace

ROW = re.compile(r'data-testid="approvals-row-([0-9a-f-]{36})"')
TESTID = re.compile(r'data-testid="(approvals-row-[a-z-]+)"')

# Every status the tab lists, and two it leaves out.
LISTED = ("pending_review", "pending_client", "approved", "rejected", "changes_requested", "on_hold")
NOT_LISTED = ("draft", "scheduled")


def _user(email):
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
        user = _user(email)
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


@pytest.fixture
def world(db):
    return World()


def _index(world):
    return reverse("approvals:index", kwargs={"workspace_id": world.workspace.id})


def _tab(world):
    return reverse("calendar:calendar", kwargs={"workspace_id": world.workspace.id})


def _rows(html):
    return ROW.findall(html)


def _get(client, url, query=None):
    response = client.get(url, query or {})
    assert response.status_code == 200, (url, response.status_code)
    return response.content.decode()


def test_the_route_is_the_workspace_and_nothing_else(world):
    url = _index(world)

    assert url == f"/workspace/{world.workspace.id}/approvals/"
    match = resolve(url)
    assert (match.app_name, match.url_name) == ("approvals", "index")
    assert match.kwargs == {"workspace_id": world.workspace.id}  # D2: no other URL part


@pytest.mark.parametrize(
    "query",
    [
        pytest.param({}, id="all"),
        pytest.param({"approval_status": "pending_review"}, id="status"),
        pytest.param({"channel": "linkedin"}, id="channel"),
        pytest.param({"tag": "launch"}, id="tag"),
        pytest.param({"tz": "Europe/London"}, id="timezone"),
    ],
)
def test_an_owner_sees_the_same_rows_as_the_calendar_tab(client, world, query):
    soon = timezone.now() + timedelta(days=1)
    for index, status in enumerate(LISTED + NOT_LISTED):
        world.post(status, when=soon + timedelta(hours=index), tags=["launch"] if index % 2 else [])
    world.post("pending_review", account=world.linkedin, tags=["launch"])
    other = World.__new__(World)
    other.org = Organization.objects.create(name="Other agency")
    other.workspace = Workspace.objects.create(organization=other.org, name="Other")
    other.editor = world.editor
    other.facebook = SocialAccount.objects.create(
        workspace=other.workspace, platform="facebook", account_platform_id="other", account_name="Other"
    )
    other.post("pending_review")
    if query.get("channel") == "linkedin":
        query = {"channel": str(world.linkedin.id)}
    client.force_login(world.owner)

    page = _get(client, _index(world), query)
    tab = _get(client, _tab(world), {"mode": "list", "tab": "approvals", **query})

    assert _rows(tab), "the tab lists something for this data"
    assert _rows(page) == _rows(tab)
    assert TESTID.findall(page) == TESTID.findall(tab)


def test_the_page_includes_the_tab_partial_with_its_refresh_and_filters(client, world):
    from apps.studio.models import AgencySettings

    # The tag filter shows with the templates switch on (off: apps/calendar/test_feature_switches.py).
    AgencySettings.objects.update_or_create(workspace=world.workspace, defaults={"features": {"templates": True}})
    world.post("pending_review")
    client.force_login(world.owner)

    response = client.get(_index(world))

    assert response.status_code == 200
    names = [template.name for template in response.templates]
    assert "approvals/index.html" in names
    assert "calendar/partials/publish_approvals.html" in names
    html = response.content.decode()
    refresh = reverse("calendar:publish_tab_approvals", kwargs={"workspace_id": world.workspace.id})
    assert f'hx-get="{refresh}?approval_status=all"' in html
    assert 'hx-trigger="approvalAction from:body, bulkActionComplete from:body"' in html
    assert html.count('id="tab-content"') == 1
    # The refresh answers with four out-of-band counts; each has one target here.
    for name in ("queue", "drafts", "approvals", "sent"):
        assert html.count(f'id="tabcount-{name}"') == 1, name
    assert html.count('id="bb-toast-host"') == 1  # outside #tab-content
    assert html.index('id="bb-toast-host"') > html.index('data-testid="approvals-list"')
    # The Calendar list's filters, in the Calendar list's Alpine scope.
    assert 'x-data="publishList()"' in html and "function publishList()" in html
    for model in ("selectedChannels", "activeTag", "displayTimezone"):
        assert f'data-testid="ui-select-{model}"' in html, model
    assert '<h1 class="ui-page-title">Approvals</h1>' in html


def test_approve_and_schedule_posts_to_the_unchanged_endpoint_and_the_gate_applies(client, world):
    when = timezone.now() + timedelta(days=2)
    post = world.post("pending_review", when=when)
    approve = reverse("approvals:approve", kwargs={"workspace_id": world.workspace.id, "post_id": post.id})

    client.force_login(world.editor)
    html = _get(client, _index(world))
    assert approve not in html  # an editor may not approve: no control, and the endpoint refuses
    assert client.post(approve, {"schedule": "1"}).status_code == 403
    assert post.platform_posts.get().status == "pending_review"

    client.force_login(world.owner)
    html = _get(client, _index(world))
    button = re.search(r'<button[^>]*data-testid="approvals-row-approve-schedule"[^>]*>', html)
    assert button is not None
    assert f'hx-post="{approve}"' in button.group(0)
    assert """hx-vals='{"schedule": "1"}'""" in button.group(0)

    response = client.post(approve, {"schedule": "1"})

    assert response.status_code == 204
    assert "approvalAction" in response.headers["HX-Trigger"]
    pp = post.platform_posts.get()
    assert pp.status == "scheduled"
    assert pp.scheduled_at == when and pp.approved_publish_at == when
    assert pp.approved_by == world.owner
    assert pp.approved_fingerprint == gate.fingerprint(pp)
    action = ApprovalAction.objects.get(action="approved", platform_post=pp)
    assert action.channel == DASHBOARD and action.fingerprint == pp.approved_fingerprint


def test_a_viewer_reads_the_list_without_a_control_exactly_like_the_tab(client, world):
    post = world.post("pending_review")
    client.force_login(world.viewer)

    page = _get(client, _index(world))
    tab = _get(client, _tab(world), {"mode": "list", "tab": "approvals"})

    assert _rows(page) == [str(post.id)]
    assert TESTID.findall(page) == TESTID.findall(tab)
    for control in ("approvals-row-select", "approvals-row-approve", "approvals-row-request-changes"):
        assert f'data-testid="{control}"' not in page, control
    assert reverse("approvals:bulk_action", kwargs={"workspace_id": world.workspace.id}) not in page
    assert reverse("approvals:approve", kwargs={"workspace_id": world.workspace.id, "post_id": post.id}) not in page


def test_a_plain_client_is_refused_like_the_other_agency_screens(client, world):
    world.post("pending_client")
    client.force_login(world.client_user)

    assert client.get(_index(world)).status_code == 403


def test_a_client_with_a_custom_role_is_staff_and_sees_the_list(client, world):
    post = world.post("pending_review")
    role = CustomRole.objects.create(organization=world.org, name="Account lead", permissions={"approve_posts": True})
    WorkspaceMembership.objects.filter(user=world.client_user).update(custom_role=role)
    client.force_login(world.client_user)

    assert _rows(_get(client, _index(world))) == [str(post.id)]


def test_a_member_of_another_workspace_is_refused(client, world):
    world.post("pending_review", caption="Neopolis only")
    stranger = _user("stranger@example.com")
    their_org = Organization.objects.create(name="Their agency")
    theirs = Workspace.objects.create(organization=their_org, name="Theirs")
    OrgMembership.objects.create(user=stranger, organization=their_org, org_role="owner")
    WorkspaceMembership.objects.create(user=stranger, workspace=theirs, workspace_role="owner")
    client.force_login(stranger)

    response = client.get(_index(world))

    assert response.status_code in (403, 404)
    assert b"Neopolis only" not in response.content
    assert client.get(reverse("approvals:index", kwargs={"workspace_id": theirs.id})).status_code == 200


def test_an_anonymous_visitor_is_sent_to_sign_in(client, world):
    response = client.get(_index(world))

    assert response.status_code == 302
    location = urlsplit(response["Location"])
    assert location.path == settings.LOGIN_URL
    assert f"next={_index(world)}" in location.query.replace("%2F", "/")


def test_the_page_only_answers_get(client, world):
    client.force_login(world.owner)

    assert client.post(_index(world)).status_code == 405


def test_the_navigation_points_approvals_here_and_lights_it(world):
    request = RequestFactory().get(_index(world))
    request.user = world.owner
    request.workspace = world.workspace
    request.resolver_match = resolve(request.path_info)

    nav = build_nav(request)

    approvals = next(item for item in nav.items if item.key == "approvals")
    assert approvals.url == _index(world)
    assert nav.active_key == "approvals"


def test_the_calendar_keeps_its_approvals_tab(client, world):
    post = world.post("pending_review")
    client.force_login(world.owner)

    html = _get(client, _tab(world), {"mode": "list", "tab": "approvals"})

    assert 'data-testid="publish-tab-approvals"' in html
    assert _rows(html) == [str(post.id)]
