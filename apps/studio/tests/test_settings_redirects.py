"""The old settings pages answer a 301 to their Settings tab (spec D1, D5; plan T6).

Each redirect lives inside the old view, after its own login, permission and workspace checks: a
person refused before is refused still (403/404, or the login page when signed out), never sent a
301. Only GET moves; every POST to those addresses keeps its handler. ``?claim=`` and ``?open=``
select something and travel with the redirect. Verified facts and Creative memory move to Advanced
only while the ``advanced_settings`` switch shows them there; otherwise their pages keep rendering, so
the direct links to Verified facts (onboarding, readiness, Set up) keep working (spec D6).
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
from apps.studio.models import AgencySettings, BrandClaim
from apps.studio.tests.test_verified_claims import _claim_payload, make_claim
from apps.workspaces.models import Workspace


def _url(name, world, **kwargs):
    return reverse(name, kwargs={"workspace_id": world.workspace.id, **kwargs})


def _tab(world, tab: str, query: str = "", anchor: str = "") -> str:
    url = reverse("settings:index", kwargs={"workspace_id": world.workspace.id})
    return f"{url}?tab={tab}{query}" + (f"#{anchor}" if anchor else "")


def _advanced_on(world, on: bool = True):
    row, _ = AgencySettings.objects.get_or_create(workspace=world.workspace)
    AgencySettings.objects.filter(pk=row.pk).update(features={"advanced_settings": on})


def _client_member(world):
    user = world.viewer.__class__.objects.create_user(
        email="client@example.com", password="pw-12345678", name="Client", tos_accepted_at=timezone.now()
    )
    OrgMembership.objects.create(user=user, organization=world.org, org_role="member")
    WorkspaceMembership.objects.create(user=user, workspace=world.workspace, workspace_role="client")
    return user


#: (old page, who may open it, the tab it moved to, the section anchor).
MOVED = [
    ("studio:settings_hub", "owner", "brand", ""),
    ("workspaces:settings", "owner", "brand", ""),
    ("social_accounts:list", "manager", "accounts", ""),
    ("client_portal_admin:client_list", "manager", "team", ""),
    ("studio:trust", "viewer", "advanced", "verified-facts"),
    ("studio:memory", "editor", "advanced", "creative-memory"),
]


@pytest.mark.parametrize(("name", "who", "tab", "anchor"), MOVED)
def test_an_old_settings_page_answers_301_to_its_tab(client, world, name, who, tab, anchor):
    _advanced_on(world)
    client.force_login(getattr(world, who))

    response = client.get(_url(name, world))

    assert response.status_code == 301
    assert response["Location"] == _tab(world, tab, anchor=anchor)
    assert client.get(response["Location"]).status_code == 200


@pytest.mark.parametrize(("name", "who", "tab", "anchor"), MOVED)
def test_selecting_query_strings_travel_with_the_redirect(client, world, name, who, tab, anchor):
    _advanced_on(world)
    client.force_login(getattr(world, who))

    response = client.get(_url(name, world) + "?open=advanced&utm=x")

    assert response.status_code == 301
    assert response["Location"] == _tab(world, tab, "&open=advanced", anchor)


def test_a_claim_travels_to_advanced(client, world):
    _advanced_on(world)
    claim = make_claim(world)
    client.force_login(world.owner)

    response = client.get(_url("studio:trust", world) + f"?claim={claim.pk}")

    assert response.status_code == 301
    assert response["Location"] == _tab(world, "advanced", f"&claim={claim.pk}", "verified-facts")
    assert "Review or renew a claim" in client.get(response["Location"]).content.decode()


@pytest.mark.parametrize(("name", "who", "tab", "anchor"), MOVED)
def test_signed_out_still_goes_to_log_in_not_to_the_tab(client, world, name, who, tab, anchor):
    _advanced_on(world)
    response = client.get(_url(name, world))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("account_login"))


@pytest.mark.parametrize(("name", "who", "tab", "anchor"), MOVED)
def test_a_plain_client_is_refused_not_redirected(client, world, name, who, tab, anchor):
    _advanced_on(world)
    client.force_login(_client_member(world))
    assert client.get(_url(name, world)).status_code in (403, 404)


@pytest.mark.parametrize(("name", "who", "tab", "anchor"), MOVED)
def test_someone_from_another_workspace_is_refused_not_redirected(client, world, name, who, tab, anchor):
    _advanced_on(world)
    other = Workspace.objects.create(organization=world.org, name="Other")
    WorkspaceMembership.objects.create(user=world.outsider, workspace=other, workspace_role="owner")
    client.force_login(world.outsider)
    assert client.get(_url(name, world)).status_code in (403, 404)


@pytest.mark.parametrize(
    ("name", "who"),
    [
        ("social_accounts:list", "editor"),  # manage_social_accounts
        ("social_accounts:list", "viewer"),
        ("client_portal_admin:client_list", "editor"),  # a workspace manager
        ("client_portal_admin:client_list", "viewer"),
        ("studio:memory", "viewer"),  # create_posts
    ],
)
def test_staff_the_page_refused_are_refused_still(client, world, name, who):
    _advanced_on(world)
    client.force_login(getattr(world, who))
    assert client.get(_url(name, world)).status_code == 403


def test_a_client_facing_role_is_refused_verified_facts_before_any_redirect(client, world):
    _advanced_on(world)
    user = world.viewer.__class__.objects.create_user(
        email="facing@example.com", password="pw-12345678", name="Facing", tos_accepted_at=timezone.now()
    )
    OrgMembership.objects.create(user=user, organization=world.org, org_role="member")
    role = CustomRole.objects.create(
        organization=world.org, name="Customer approver", permissions={"client_facing": True, "approve_posts": True}
    )
    WorkspaceMembership.objects.create(user=user, workspace=world.workspace, workspace_role="client", custom_role=role)
    client.force_login(user)
    assert client.get(_url("studio:trust", world)).status_code == 403


# --- Verified facts and Creative memory follow the switch ---------------------------


@pytest.mark.parametrize(("name", "who"), [("studio:trust", "owner"), ("studio:memory", "owner")])
def test_with_advanced_settings_off_the_power_pages_keep_rendering(client, world, name, who):
    _advanced_on(world, False)
    client.force_login(getattr(world, who))
    assert client.get(_url(name, world)).status_code == 200
    AgencySettings.objects.filter(workspace=world.workspace).delete()
    assert client.get(_url(name, world)).status_code == 200


# --- POSTs to the moved addresses keep their handlers -------------------------------


def test_saving_the_workspace_name_still_posts_to_the_old_address(client, world):
    client.force_login(world.owner)
    response = client.post(_url("workspaces:settings", world), {"name": "Renamed"})
    assert response.status_code == 302 and response["Location"] == _url("workspaces:settings", world)
    world.workspace.refresh_from_db()
    assert world.workspace.name == "Renamed"
    # The workspace page is now the Brand tab, where the name and logo forms post back to it.
    html = client.get(_tab(world, "brand")).content.decode()
    assert f'action="{_url("workspaces:settings", world)}"' in html and 'value="Renamed"' in html


def test_a_viewer_still_cannot_rename_the_workspace(client, world):
    client.force_login(world.viewer)
    assert client.post(_url("workspaces:settings", world), {"name": "OWNED"}).status_code == 403


def test_the_danger_zone_still_answers_only_owners_and_managers(client, world):
    Workspace.objects.create(organization=world.org, name="Second")
    for user in (world.editor, world.viewer):
        client.force_login(user)
        for action in ("archive_workspace", "unarchive_workspace", "delete_workspace"):
            assert client.post(_url("workspaces:settings", world), {"action": action}).status_code == 403, action
    world.workspace.refresh_from_db()
    assert not world.workspace.is_archived

    client.force_login(world.manager)
    response = client.post(_url("workspaces:settings", world), {"action": "archive_workspace"})
    assert response.status_code == 302 and response["Location"] == reverse("organizations:workspaces")
    world.workspace.refresh_from_db()
    assert world.workspace.is_archived


def test_the_workspace_page_answers_get_with_the_301_and_nothing_else_but_post(client, world):
    """The page itself no longer renders: GET moves, HEAD was never allowed, POST keeps its handler."""
    client.force_login(world.owner)
    assert client.get(_url("workspaces:settings", world)).status_code == 301
    assert client.head(_url("workspaces:settings", world)).status_code == 405
    for method in (client.put, client.delete, client.patch):
        assert method(_url("workspaces:settings", world)).status_code == 405


@pytest.mark.parametrize("on", [True, False])
def test_verifying_a_claim_still_posts_to_verified_facts(client, world, on):
    _advanced_on(world, on)
    client.force_login(world.owner)
    response = client.post(_url("studio:trust", world), _claim_payload(world))
    assert response.status_code == 302 and response["Location"] == _url("studio:trust", world)
    assert BrandClaim.objects.filter(workspace=world.workspace).count() == 1


def test_the_old_pages_that_only_answered_get_still_refuse_post(client, world):
    _advanced_on(world)
    client.force_login(world.owner)
    for name in ("studio:settings_hub", "studio:memory", "client_portal_admin:client_list"):
        assert client.post(_url(name, world)).status_code == 405, name


def test_the_accounts_list_still_answers_a_post_with_its_page(client, world):
    client.force_login(world.manager)
    response = client.post(_url("social_accounts:list", world))
    assert response.status_code == 200
    assert "Neopolis Infra" in response.content.decode()


def test_head_moves_like_get_where_the_page_answered_head(client, world):
    client.force_login(world.manager)
    response = client.head(_url("social_accounts:list", world))
    assert response.status_code == 301
    assert response["Location"] == _tab(world, "accounts")
    # A page that only answered GET still refuses HEAD, as before.
    assert client.head(_url("studio:settings_hub", world)).status_code == 405


def test_the_brand_page_and_set_up_keep_rendering(client, world):
    client.force_login(world.owner)
    for name in ("studio:setup", "studio:brand", "studio:autopilot", "studio:outcomes", "telegram:settings"):
        assert client.get(_url(name, world)).status_code == 200, name
    assert client.get(_url("workspaces:approvals_settings", world)).status_code == 200
    assert client.get(_url("social_accounts:connect", world)).status_code == 200
