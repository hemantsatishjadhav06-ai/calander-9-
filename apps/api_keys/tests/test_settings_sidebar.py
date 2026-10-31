"""API keys left the organisation settings sidebar (spec D7, plan T8).

Only the link moved: the pages keep their addresses and their checks (``test_views.py``), and an
organisation's owners and admins reach them from Settings → Advanced → Developers
(``apps/studio/tests/test_settings_tabs.py``). A member, who would only meet a 403 there, no longer
sees a link to it in the sidebar.
"""

from __future__ import annotations

import re

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.members.models import OrgMembership

#: Every page drawn in ``layouts/settings.html``, the organisation settings sidebar.
ORG_SETTINGS_PAGES = (
    "accounts:settings",
    "organizations:settings",
    "organizations:workspaces",
    "organizations:cross_workspace_calendar",
    "members:list",
    "media_library_org:shared_index",
    "api_keys:list",
)


def _user(email: str):
    from apps.accounts.models import User

    # The sign-up signal makes this person the owner of their own organisation.
    return User.objects.create_user(email=email, password="pw-12345678", name="Owner", tos_accepted_at=timezone.now())


def _sidebar(html: str) -> str:
    match = re.search(r'<nav class="sidebar-nav.*?</nav>', html, re.S)
    assert match, "no sidebar on the page"
    return match.group(0)


@pytest.fixture
def owner(db):
    return _user("keys-owner@example.com")


@pytest.mark.django_db
@pytest.mark.parametrize("name", ORG_SETTINGS_PAGES)
def test_the_organisation_settings_sidebar_has_no_api_keys_item(client, owner, name):
    client.force_login(owner)

    response = client.get(reverse(name))

    assert response.status_code == 200
    sidebar = _sidebar(response.content.decode())
    assert reverse("api_keys:list") not in sidebar
    assert "API keys" not in sidebar
    # The rest of the organisation's items stay.
    for kept in ("organizations:settings", "organizations:workspaces", "members:list"):
        assert f'href="{reverse(kept)}"' in sidebar


@pytest.mark.django_db
def test_the_api_keys_page_still_answers_an_owner_at_its_address(client, owner):
    assert reverse("api_keys:list") == "/organizations/api-keys/"
    client.force_login(owner)

    response = client.get(reverse("api_keys:list"))

    assert response.status_code == 200
    assert "API keys</h1>" in response.content.decode()


@pytest.mark.django_db
def test_a_member_is_still_refused_the_api_keys_page(client, owner):
    member = _user("keys-member@example.com")
    org = OrgMembership.objects.get(user=owner).organization
    OrgMembership.objects.filter(user=member).delete()
    OrgMembership.objects.create(user=member, organization=org, org_role=OrgMembership.OrgRole.MEMBER)
    client.force_login(member)

    assert client.get(reverse("api_keys:list")).status_code == 403
