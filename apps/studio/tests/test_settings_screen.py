"""Settings (spec D5, R5): one screen at ``/workspace/<id>/settings/`` with a tab per settings page.

Each tab shows its old page's body and applies that page's own permission check: a tab someone may
not use is not in the strip and its ``?tab=`` answers 403. The forms post to the old handlers with
an explicit ``action=``, so saving from a tab gives exactly the old result. Only the active tab is
built. The last three tabs and the old pages' redirects are in ``test_settings_tabs.py`` and
``test_settings_redirects.py``.
"""

from __future__ import annotations

import dataclasses
import re

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.studio.models import BrandProfile
from apps.workspaces.models import Workspace

FIRST_FOUR = ("brand", "accounts", "team", "approvals")
ALL_TABS = [*FIRST_FOUR, "autopilot", "notifications", "advanced"]


def _settings(world, tab: str | None = None) -> str:
    url = reverse("settings:index", kwargs={"workspace_id": world.workspace.id})
    return f"{url}?tab={tab}" if tab else url


def _url(name, world, **kwargs):
    return reverse(name, kwargs={"workspace_id": world.workspace.id, **kwargs})


def _get(client, user, world, tab=None):
    client.force_login(user)
    return client.get(_settings(world, tab))


def _strip(html: str) -> list[str]:
    """The tab keys in the strip, in order."""
    return re.findall(r'data-testid="settings-tab-([a-z]+)"', html)


def _no_csrf(html: str) -> str:
    """*html* with every per-render CSRF token blanked."""
    return re.sub(r'name="csrfmiddlewaretoken" value="[^"]*"', 'name="csrfmiddlewaretoken" value=""', html)


def _form(html: str, action: str) -> str:
    """The form that posts to *action*, with the per-render CSRF token blanked."""
    match = re.search(r'<form[^>]*action="' + re.escape(action) + r'".*?</form>', html, re.S)
    assert match, f"no form posts to {action}"
    return _no_csrf(match.group(0))


def _client_member(world):
    user = world.viewer.__class__.objects.create_user(
        email="client@example.com", password="pw-12345678", name="Client", tos_accepted_at=timezone.now()
    )
    OrgMembership.objects.create(user=user, organization=world.org, org_role="member")
    WorkspaceMembership.objects.create(user=user, workspace=world.workspace, workspace_role="client")
    return user


def _brand_data(profile: BrandProfile, **changes) -> dict[str, str]:
    from apps.studio.forms import BrandProfileForm

    form = BrandProfileForm(instance=profile)
    data = {name: "" if form[name].value() is None else str(form[name].value()) for name in form.fields}
    data.update(changes)
    return data


# --- the address -------------------------------------------------------------------


def test_settings_lives_under_the_workspace_next_to_the_client_admin(client, world):
    ws = world.workspace.id
    assert _settings(world) == f"/workspace/{ws}/settings/"
    # The client admin keeps its address under /settings/clients/ and keeps answering: a GET moves to
    # the Team & clients tab (spec D1), its actions below it stay where they are.
    assert _url("client_portal_admin:client_list", world) == f"/workspace/{ws}/settings/clients/"
    client.force_login(world.owner)
    response = client.get(_url("client_portal_admin:client_list", world))
    assert response.status_code == 301 and response["Location"] == _settings(world, "team")


def test_settings_answers_only_get(client, world):
    client.force_login(world.owner)
    assert client.post(_settings(world)).status_code == 405


# --- who gets in -------------------------------------------------------------------


def test_signed_out_goes_to_log_in(client, world):
    response = client.get(_settings(world))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("account_login"))


def test_a_plain_client_is_refused(client, world):
    response = _get(client, _client_member(world), world)
    assert response.status_code == 403


def test_someone_from_another_workspace_is_refused(client, world):
    other = Organization.objects.create(name="Others")
    theirs = Workspace.objects.create(organization=other, name="Theirs")
    OrgMembership.objects.create(user=world.outsider, organization=other, org_role="owner")
    WorkspaceMembership.objects.create(user=world.outsider, workspace=theirs, workspace_role="owner")

    assert _get(client, world.outsider, world).status_code == 403
    for tab in FIRST_FOUR:
        assert client.get(_settings(world, tab)).status_code == 403


# --- the strip ---------------------------------------------------------------------


def test_an_owner_sees_every_tab_in_order_and_brand_first(client, world):
    response = _get(client, world.owner, world)
    html = response.content.decode()

    assert response.status_code == 200
    assert _strip(html) == ALL_TABS
    assert "Team &amp; clients" in html
    # No tab asked for: the first one this person may use.
    assert 'data-testid="settings-panel-brand"' in html
    assert re.search(r'data-testid="settings-tab-brand"[^>]*aria-current="page"', html) or re.search(
        r'aria-current="page"[^>]*data-testid="settings-tab-brand"', html
    )


def test_an_unknown_tab_falls_back_to_the_first(client, world):
    response = _get(client, world.owner, world, "nope")
    assert response.status_code == 200
    assert 'data-testid="settings-panel-brand"' in response.content.decode()


@pytest.mark.parametrize("tab", FIRST_FOUR)
def test_each_tab_renders_its_panel_for_an_owner(client, world, tab):
    response = _get(client, world.owner, world, tab)
    html = response.content.decode()

    assert response.status_code == 200
    assert f'data-testid="settings-panel-{tab}"' in html
    others = [key for key in FIRST_FOUR if key != tab]
    for key in others:
        assert f'data-testid="settings-panel-{key}"' not in html


def test_a_manager_may_use_the_same_tabs(client, world):
    html = _get(client, world.manager, world).content.decode()
    assert _strip(html) == ALL_TABS
    for tab in ALL_TABS:
        assert client.get(_settings(world, tab)).status_code == 200


@pytest.mark.parametrize("who", ["editor", "viewer"])
def test_tabs_a_person_may_not_use_are_absent_and_refused(client, world, who):
    user = getattr(world, who)
    html = _get(client, user, world).content.decode()

    # Brand (read for staff) and Team & clients (the roster is open to the organisation's members);
    # Autopilot (create_posts), Notifications and Advanced are the last three tabs' own business.
    assert _strip(html)[:2] == ["brand", "team"]
    assert not {"accounts", "approvals"} & set(_strip(html))
    # Accounts needs manage_social_accounts, Approvals an owner or manager: refused by address too.
    assert client.get(_settings(world, "accounts")).status_code == 403
    assert client.get(_settings(world, "approvals")).status_code == 403
    assert client.get(_settings(world, "brand")).status_code == 200
    assert client.get(_settings(world, "team")).status_code == 200


# --- Brand -------------------------------------------------------------------------


def test_the_brand_tab_is_the_brand_page_body_posting_to_the_old_handler(client, world):
    client.force_login(world.owner)
    action = _url("studio:brand", world)
    old = client.get(action).content.decode()
    tab = client.get(_settings(world, "brand")).content.decode()

    # The same form, attribute for attribute, with an explicit action at the brand page's handler.
    assert _form(tab, action) == _form(old, action)
    assert 'data-testid="brand-save"' in tab and 'data-testid="brand-primary-color"' in tab
    for template in ("editorial", "split", "statement", "stat"):
        assert f'data-testid="brand-sample-image-{template}"' in tab


def test_saving_the_brand_colour_from_the_tab_changes_it_like_the_old_page(client, world):
    client.force_login(world.manager)
    client.get(_settings(world, "brand"))
    profile = BrandProfile.objects.get(workspace=world.workspace)
    action = _url("studio:brand", world)
    assert f'action="{action}"' in client.get(_settings(world, "brand")).content.decode()

    response = client.post(action, _brand_data(profile, primary_color="#0a1f44"))

    assert response.status_code == 302
    assert response["Location"] == action
    profile.refresh_from_db()
    assert profile.primary_color == "#0A1F44"


def test_an_editor_reads_the_brand_but_cannot_save_it(client, world):
    html = _get(client, world.editor, world, "brand").content.decode()

    assert 'data-testid="settings-panel-brand"' in html
    assert 'data-testid="brand-save"' not in html
    assert "<fieldset disabled" in html
    assert "Only an owner or manager can change the brand profile." in html
    assert client.post(_url("studio:brand", world), {"brand_name": "X"}).status_code == 403


# --- Accounts ----------------------------------------------------------------------


def test_the_accounts_tab_lists_the_accounts_and_connects_on_the_old_page(client, world):
    client.force_login(world.manager)
    # The accounts page moved here (a GET answers 301); its body is the same partial.
    old = client.get(_url("social_accounts:list", world))
    assert old.status_code == 301 and old["Location"] == _settings(world, "accounts")
    html = client.get(_settings(world, "accounts")).content.decode()

    assert 'data-testid="settings-panel-accounts"' in html
    assert "Neopolis Infra" in html and "neopolisinfra" in html
    assert f'href="{_url("social_accounts:connect", world)}"' in html
    # Each card is the list page's own, with its actions at the old handlers.
    for account in (world.linkedin, world.x):
        assert f'id="account-{account.id}"' in html
        assert _url("social_accounts:disconnect", world, account_id=account.id) in html
    assert 'id="accounts-list"' in html and "We check each connection every 6 hours." in html


def test_the_accounts_tab_offers_the_first_connection_when_there_is_none(client, world):
    world.linkedin.delete()
    world.x.delete()
    html = _get(client, world.owner, world, "accounts").content.decode()

    assert "No accounts connected yet" in html
    assert f'href="{_url("social_accounts:connect", world)}"' in html


# --- Team & clients ----------------------------------------------------------------


def test_team_and_clients_counts_and_links_for_an_owner(client, world):
    _client_member(world)
    html = _get(client, world.owner, world, "team").content.decode()

    members = re.search(r'data-testid="settings-team-members".*?</section>', html, re.S).group(0)
    clients = html[html.index('data-testid="settings-team-clients"') :]
    assert f'href="{reverse("members:list")}"' in members
    # Five people in the organisation (owner, manager, editor, viewer and the client), one client here.
    assert '<span class="ui-badge">5</span>' in members
    # The client admin moved here (its page answers 301 to this tab): its list, invite and actions,
    # each posting to the client admin's own handlers.
    assert 'id="clients-list"' in clients and '<span class="ui-badge">1</span>' in clients
    assert "client@example.com" in clients
    assert reverse("client_portal_admin:invite_client", kwargs={"workspace_id": world.workspace.id}) in clients
    # The team-member invite dialog stays on its own page (the two dialogs listen to every request).
    assert reverse("members:invite") not in html


def test_team_and_clients_shows_an_editor_only_the_roster(client, world):
    html = _get(client, world.editor, world, "team").content.decode()

    assert 'data-testid="settings-team-members"' in html
    assert 'data-testid="settings-team-clients"' not in html
    assert _url("client_portal_admin:client_list", world) not in html


# --- Approvals ---------------------------------------------------------------------


def test_the_approvals_tab_is_the_approvals_settings_form_posting_to_the_old_handler(client, world):
    client.force_login(world.owner)
    action = _url("workspaces:approvals_settings", world)
    old = client.get(action).content.decode()
    html = client.get(_settings(world, "approvals")).content.decode()

    assert 'data-testid="settings-panel-approvals"' in html
    assert _form(html, action) == _form(old, action)
    assert f'href="{reverse("members:list")}"' in html


def test_saving_approvals_from_the_tab_goes_through_the_old_handler(client, world):
    client.force_login(world.owner)
    action = _url("workspaces:approvals_settings", world)
    assert f'action="{action}"' in client.get(_settings(world, "approvals")).content.decode()

    response = client.post(action, {"approval_workflow_mode": "required_internal"})

    assert response.status_code == 302
    assert response["Location"] == action
    world.workspace.refresh_from_db()
    assert world.workspace.approval_workflow_mode == "required_internal"


# --- only the active tab is built --------------------------------------------------


def test_only_the_active_tab_is_built(client, world, monkeypatch):
    from apps.studio import views_settings

    built: list[str] = []

    def recording(tab):
        def build(request, workspace):
            built.append(tab.key)
            return tab.build(request, workspace)

        return build

    monkeypatch.setattr(
        views_settings,
        "TABS",
        tuple(dataclasses.replace(tab, build=recording(tab)) for tab in views_settings.TABS),
    )
    client.force_login(world.owner)

    for tab in FIRST_FOUR:
        built.clear()
        assert client.get(_settings(world, tab)).status_code == 200
        assert built == [tab]
    built.clear()
    client.get(_settings(world))
    assert built == ["brand"]


def test_the_registry_keeps_the_screens_order(world):
    from apps.studio import views_settings

    keys = [tab.key for tab in views_settings.TABS]
    order = ["brand", "accounts", "team", "approvals", "autopilot", "notifications", "advanced"]
    assert keys[:4] == list(FIRST_FOUR)
    assert keys == [key for key in order if key in keys]
    assert all(tab.label and tab.template for tab in views_settings.TABS)
