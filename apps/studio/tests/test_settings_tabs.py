"""Settings, the last three tabs (spec D5, D6; plan T6): Autopilot, Notifications and Advanced.

Autopilot is the whole autopilot form, unsplit, posting to the Autopilot page's handler. Notifications
links to the person's notification settings and to Telegram, with where each stands; no form moves.
Advanced holds Health (the Set up checklist), the free-form routine form, a Developers link for the
organisation's owners and admins, the danger zone, and, with the ``advanced_settings`` switch on,
Verified facts, Creative memory and Outcomes. A panel that includes Set up answers ``no-store``.
"""

from __future__ import annotations

import re

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.common.tests.test_a11y_sweep import FAINT_TEXT, _Audit
from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
from apps.notifications.models import QuietHours
from apps.studio import readiness
from apps.studio.forms_agency import AgencySettingsForm
from apps.studio.models import AgencySettings, BrandClaim, Routine
from apps.studio.tests.test_autopilot import _form as autopilot_form
from apps.studio.tests.test_verified_claims import _claim_payload, make_claim
from apps.workspaces.models import Workspace

ALL_TABS = ["brand", "accounts", "team", "approvals", "autopilot", "notifications", "advanced"]


def _settings(world, tab: str | None = None, **query) -> str:
    url = reverse("settings:index", kwargs={"workspace_id": world.workspace.id})
    params = ([f"tab={tab}"] if tab else []) + [f"{key}={value}" for key, value in query.items()]
    return f"{url}?{'&'.join(params)}" if params else url


def _url(name, world, **kwargs):
    return reverse(name, kwargs={"workspace_id": world.workspace.id, **kwargs})


def _get(client, user, world, tab=None, **query):
    client.force_login(user)
    return client.get(_settings(world, tab, **query))


def _strip(html: str) -> list[str]:
    return re.findall(r'data-testid="settings-tab-([a-z]+)"', html)


def _form(html: str, action: str) -> str:
    """The form that posts to *action*, with the per-render CSRF token blanked."""
    match = re.search(r'<form[^>]*action="' + re.escape(action) + r'".*?</form>', html, re.S)
    assert match, f"no form posts to {action}"
    return re.sub(r'name="csrfmiddlewaretoken" value="[^"]*"', 'name="csrfmiddlewaretoken" value=""', match.group(0))


def _section(html: str, testid: str) -> str:
    match = re.search(r'data-testid="' + testid + r'".*?(?=data-testid="settings-advanced-|$)', html, re.S)
    assert match, f"no section {testid}"
    return match.group(0)


def _advanced_on(world, on: bool = True):
    row, _ = AgencySettings.objects.get_or_create(workspace=world.workspace)
    AgencySettings.objects.filter(pk=row.pk).update(features={"advanced_settings": on})


def _client_member(world, email="client@example.com"):
    user = world.viewer.__class__.objects.create_user(
        email=email, password="pw-12345678", name="Client", tos_accepted_at=timezone.now()
    )
    OrgMembership.objects.create(user=user, organization=world.org, org_role="member")
    WorkspaceMembership.objects.create(user=user, workspace=world.workspace, workspace_role="client")
    return user


def _org_admin(world):
    user = world.viewer.__class__.objects.create_user(
        email="admin@example.com", password="pw-12345678", name="Admin", tos_accepted_at=timezone.now()
    )
    OrgMembership.objects.create(user=user, organization=world.org, org_role="admin")
    WorkspaceMembership.objects.create(user=user, workspace=world.workspace, workspace_role="manager")
    return user


# --- the strip ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "tabs"),
    [
        ("owner", ALL_TABS),
        ("manager", ALL_TABS),
        ("editor", ["brand", "team", "autopilot", "notifications", "advanced"]),
        ("viewer", ["brand", "team", "notifications", "advanced"]),
    ],
)
def test_the_last_three_tabs_follow_their_pages_checks(client, world, who, tabs):
    html = _get(client, getattr(world, who), world).content.decode()

    assert _strip(html) == tabs
    for key in ("autopilot", "notifications", "advanced"):
        expected = 200 if key in tabs else 403
        assert client.get(_settings(world, key)).status_code == expected, key


@pytest.mark.parametrize("tab", ["autopilot", "notifications", "advanced"])
def test_a_plain_client_and_an_outsider_are_refused_every_new_tab(client, world, tab):
    assert _get(client, _client_member(world), world, tab).status_code == 403
    assert _get(client, world.outsider, world, tab).status_code in (403, 404)
    client.logout()
    response = client.get(_settings(world, tab))
    assert response.status_code == 302 and response["Location"].startswith(reverse("account_login"))


# --- Autopilot ---------------------------------------------------------------------


def test_the_autopilot_tab_is_the_whole_autopilot_form_posting_to_its_page(client, world):
    client.force_login(world.owner)
    action = _url("studio:autopilot", world)
    old = client.get(action).content.decode()
    html = client.get(_settings(world, "autopilot")).content.decode()

    assert 'data-testid="settings-panel-autopilot"' in html
    form = _form(html, action)
    assert form == _form(old, action)
    # Unsplit: every field of the form travels in this one form, approvers and budget included.
    for name in AgencySettingsForm(workspace=world.workspace).fields:
        assert f'name="{name}"' in form, name
    assert 'id="autopilot-form"' in form and "data-autopilot-advanced>" in form


def test_the_autopilot_tab_opens_advanced_from_a_link(client, world):
    html = _get(client, world.owner, world, "autopilot", open="advanced").content.decode()
    assert "data-autopilot-advanced open>" in html


def test_saving_autopilot_from_the_tab_goes_through_its_page(client, world):
    client.force_login(world.owner)
    action = _url("studio:autopilot", world)
    assert f'action="{action}"' in client.get(_settings(world, "autopilot")).content.decode()

    response = client.post(action, autopilot_form(world, posts_per_week="3"))

    assert response.status_code == 302
    assert response["Location"] == action
    row = AgencySettings.objects.get(workspace=world.workspace)
    assert row.autopilot_enabled and row.posts_per_week == 3


def test_an_editor_reads_autopilot_but_cannot_save_it(client, world):
    html = _get(client, world.editor, world, "autopilot").content.decode()

    assert 'data-testid="settings-panel-autopilot"' in html
    assert "can change autopilot" in html
    assert '<button type="submit" class="ui-btn ui-btn-primary max-sm:w-full">Save</button>' not in html


# --- Notifications -----------------------------------------------------------------


def test_the_notifications_tab_links_to_preferences_and_telegram_with_their_state(client, world):
    response = _get(client, world.viewer, world, "notifications")
    html = response.content.decode()

    assert response.status_code == 200
    assert 'data-testid="settings-panel-notifications"' in html
    preferences = re.search(r'data-testid="settings-notifications-preferences".*?</section>', html, re.S).group(0)
    telegram = re.search(r'data-testid="settings-notifications-telegram".*?</section>', html, re.S).group(0)
    assert f'href="{reverse("notifications:preferences")}"' in preferences
    assert "Quiet hours are off" in preferences and "as they happen" in preferences
    assert f'href="{_url("telegram:settings", world)}"' in telegram
    assert readiness.telegram_state(world.workspace, world.viewer)["label"] in telegram
    # No form moved here, and reading the tab writes nothing.
    assert "<form" not in preferences and "<form" not in telegram
    assert f'action="{reverse("notifications:preferences")}"' not in html
    assert not QuietHours.objects.filter(user=world.viewer).exists()


def test_the_notifications_tab_shows_the_persons_own_quiet_hours_and_digest(client, world):
    QuietHours.objects.create(
        user=world.editor,
        is_enabled=True,
        start_time=timezone.datetime(2026, 1, 1, 22, 0).time(),
        end_time=timezone.datetime(2026, 1, 1, 7, 0).time(),
        timezone="Asia/Kolkata",
        digest_mode=True,
    )
    html = _get(client, world.editor, world, "notifications").content.decode()

    assert "Quiet hours 22:00–07:00 (Asia/Kolkata)" in html
    assert "one daily digest" in html
    # Someone else's settings are their own.
    assert "Quiet hours are off" in _get(client, world.viewer, world, "notifications").content.decode()


@pytest.mark.parametrize("tab", ["notifications", "advanced"])
def test_panels_with_telegram_or_set_up_are_never_cached(client, world, tab):
    response = _get(client, world.owner, world, tab)
    assert response["Cache-Control"] == "no-store, private"


def test_the_first_tabs_may_be_cached_as_before(client, world):
    assert "no-store" not in _get(client, world.owner, world, "brand").get("Cache-Control", "")


# --- Advanced: Health, the routine form, Developers, the danger zone ----------------


def test_advanced_health_is_the_set_up_checklist(client, world):
    client.force_login(world.owner)
    setup = client.get(_url("studio:setup", world)).content.decode()
    html = client.get(_settings(world, "advanced")).content.decode()

    health = _section(html, "settings-advanced-health")
    rows = re.findall(r'data-testid="setup-row-([a-z_]+)"', setup)
    assert rows and re.findall(r'data-testid="setup-row-([a-z_]+)"', health) == rows
    assert re.search(r"data-setup-progress>\d+ of \d+ steps done<", health)
    # Readiness copy still says Set up, and its page keeps answering.
    assert f'href="{_url("studio:setup", world)}"' in health and "Open Set up" in health
    assert re.findall(r'data-setup-state="([a-z]+)"', health) == re.findall(r'data-setup-state="([a-z]+)"', setup)


def test_advanced_offers_the_routine_form_to_people_who_may_write_routines(client, world):
    html = _get(client, world.editor, world, "advanced").content.decode()
    form = _section(html, "settings-advanced-routine")
    assert f'action="{_url("studio:routines_create", world)}"' in form
    assert 'name="instruction"' in form and 'name="cadence"' in form and 'name="time"' in form

    viewer = _get(client, world.viewer, world, "advanced").content.decode()
    assert 'data-testid="settings-advanced-routine"' not in viewer
    assert _url("studio:routines_create", world) not in viewer


def test_writing_a_routine_from_advanced_saves_it_through_its_handler(client, world):
    client.force_login(world.editor)
    client.get(_settings(world, "advanced"))
    response = client.post(
        _url("studio:routines_create", world),
        {"instruction": "Draft a market update", "cadence": "weekdays", "weekday": "0", "time": "08:30", "title": ""},
    )
    assert response.status_code == 302
    assert Routine.objects.filter(workspace=world.workspace, instruction="Draft a market update").exists()


def test_developers_is_linked_only_for_the_organisations_owners_and_admins(client, world):
    api_keys = reverse("api_keys:list")
    for user in (world.owner, _org_admin(world)):
        html = _get(client, user, world, "advanced").content.decode()
        assert f'href="{api_keys}"' in _section(html, "settings-advanced-developers"), user.email
        assert client.get(api_keys).status_code == 200
    for user in (world.manager, world.editor, world.viewer):
        html = _get(client, user, world, "advanced").content.decode()
        assert 'data-testid="settings-advanced-developers"' not in html, user.email
        assert f'href="{api_keys}"' not in html, user.email


def test_the_danger_zone_is_the_workspace_pages_and_posts_there(client, world):
    Workspace.objects.create(organization=world.org, name="Second")
    action = _url("workspaces:settings", world)
    for user in (world.owner, world.manager):
        danger = _section(_get(client, user, world, "advanced").content.decode(), "settings-advanced-danger")
        assert f'action="{action}"' in danger and 'value="archive_workspace"' in danger
        assert 'value="delete_workspace"' in danger
    for user in (world.editor, world.viewer):
        html = _get(client, user, world, "advanced").content.decode()
        assert 'data-testid="settings-advanced-danger"' not in html
        assert 'value="delete_workspace"' not in html

    client.force_login(world.owner)
    response = client.post(action, {"action": "archive_workspace"})
    assert response.status_code == 302 and response["Location"] == reverse("organizations:workspaces")
    world.workspace.refresh_from_db()
    assert world.workspace.is_archived


# --- Advanced: the power features behind advanced_settings --------------------------

POWER = ("settings-advanced-facts", "settings-advanced-memory", "settings-advanced-outcomes")


def test_advanced_settings_off_hides_facts_memory_and_outcomes(client, world):
    html = _get(client, world.owner, world, "advanced").content.decode()

    for testid in POWER:
        assert f'data-testid="{testid}"' not in html
    assert _url("studio:memory_house_style", world) not in html
    assert _url("studio:outcomes", world) not in html
    # The pages themselves still answer (switches hide; they never refuse).
    for name in ("studio:trust", "studio:memory", "studio:outcomes"):
        assert client.get(_url(name, world)).status_code == 200, name


def test_advanced_settings_on_shows_facts_memory_and_outcomes(client, world):
    _advanced_on(world)
    make_claim(world)
    html = _get(client, world.owner, world, "advanced").content.decode()

    facts = _section(html, "settings-advanced-facts")
    assert f'action="{_url("studio:trust", world)}"' in facts and "Record verification" in facts
    assert "The owner confirmed two units are available" in facts
    memory = _section(html, "settings-advanced-memory")
    assert f'action="{_url("studio:memory_refresh", world)}"' in memory
    assert "Your house style" in memory and "Best-performing posts" in memory
    outcomes = _section(html, "settings-advanced-outcomes")
    assert f'href="{_url("studio:outcomes", world)}"' in outcomes


def test_advanced_settings_on_keeps_each_sections_own_check(client, world):
    _advanced_on(world)
    # A viewer reads verified facts and outcomes (view_analytics) but has no Creative memory (create_posts).
    viewer = _get(client, world.viewer, world, "advanced").content.decode()
    assert 'data-testid="settings-advanced-facts"' in viewer
    assert "Record verification" not in viewer
    assert 'data-testid="settings-advanced-outcomes"' in viewer
    assert 'data-testid="settings-advanced-memory"' not in viewer

    # A client-facing custom role passes the screen's staff check but never reads verified facts.
    facing = world.viewer.__class__.objects.create_user(
        email="facing@example.com", password="pw-12345678", name="Facing", tos_accepted_at=timezone.now()
    )
    OrgMembership.objects.create(user=facing, organization=world.org, org_role="member")
    role = CustomRole.objects.create(
        organization=world.org, name="Customer approver", permissions={"client_facing": True, "approve_posts": True}
    )
    WorkspaceMembership.objects.create(
        user=facing, workspace=world.workspace, workspace_role="client", custom_role=role
    )
    response = _get(client, facing, world, "advanced")
    assert response.status_code == 200
    assert 'data-testid="settings-advanced-facts"' not in response.content.decode()


def test_a_claim_opens_for_review_in_advanced(client, world):
    _advanced_on(world)
    claim = make_claim(world)
    html = _get(client, world.owner, world, "advanced", claim=claim.pk).content.decode()

    facts = _section(html, "settings-advanced-facts")
    assert "Review or renew a claim" in facts
    assert f'name="claim_id" value="{claim.pk}"' in facts
    # The claim's own link stays on this tab.
    tab = _settings(world, "advanced", claim=claim.pk).replace("&", "&amp;")
    assert f'href="{tab}#verified-facts"' in facts


def test_a_foreign_or_malformed_claim_is_refused_in_advanced(client, world):
    _advanced_on(world)
    other = Workspace.objects.create(organization=world.org, name="Other brand")
    foreign = make_claim(world, workspace=other)
    assert _get(client, world.owner, world, "advanced", claim=foreign.pk).status_code == 404
    assert _get(client, world.owner, world, "advanced", claim="not-a-claim").status_code == 400


def test_the_facts_section_hands_its_form_over_as_claim_form_only(world):
    """Advanced has several forms, so the facts form is ``claim_form``; no bare ``form`` is left behind."""
    from django.test import RequestFactory

    from apps.studio.forms_trust import BrandClaimForm
    from apps.studio.views_settings import _facts

    claim = make_claim(world)
    request = RequestFactory().get(_settings(world, "advanced", claim=claim.pk))
    request.user = world.owner
    request.workspace = world.workspace
    request.workspace_membership = WorkspaceMembership.objects.get(user=world.owner, workspace=world.workspace)

    context = _facts(request, world.workspace)

    assert "form" not in context
    assert isinstance(context["claim_form"], BrandClaimForm)
    assert context["claim_form"].instance == claim == context["selected_claim"]


@pytest.mark.parametrize("where", ["page", "advanced"])
def test_verified_facts_and_advanced_open_a_claim_by_one_rule(client, world, where):
    """``?claim=`` is read once for both: a claim of this workspace opens, another's is 404, a malformed
    one 400. The page renders with the switch off; Advanced shows the section with it on."""
    _advanced_on(world, where == "advanced")
    claim = make_claim(world)
    foreign = make_claim(world, workspace=Workspace.objects.create(organization=world.org, name="Other brand"))
    client.force_login(world.owner)

    def opened(value):
        if where == "advanced":
            return client.get(_settings(world, "advanced", claim=value))
        return client.get(_url("studio:trust", world) + f"?claim={value}")

    response = opened(claim.pk)
    assert response.status_code == 200
    html = response.content.decode()
    assert "Review or renew a claim" in html and f'name="claim_id" value="{claim.pk}"' in html
    assert opened(foreign.pk).status_code == 404
    assert opened("not-a-claim").status_code == 400


def _custom_member(world, email, workspace_role, permissions):
    user = world.viewer.__class__.objects.create_user(
        email=email, password="pw-12345678", name=email.split("@")[0], tos_accepted_at=timezone.now()
    )
    OrgMembership.objects.create(user=user, organization=world.org, org_role="member")
    role = CustomRole.objects.create(organization=world.org, name=email, permissions=permissions)
    WorkspaceMembership.objects.create(
        user=user, workspace=world.workspace, workspace_role=workspace_role, custom_role=role
    )
    return user


@pytest.mark.parametrize(
    ("who", "reads_outcomes"),
    [
        ("owner", True),
        ("manager", True),
        ("editor", True),  # records outcomes (create_posts)
        ("viewer", True),  # reads them (view_analytics)
        ("approver", False),  # a custom role with neither
        ("facing", False),  # a client-facing custom role on a client membership
    ],
)
def test_the_outcomes_link_shows_exactly_when_the_outcomes_page_lets_the_person_in(client, world, who, reads_outcomes):
    _advanced_on(world)
    user = {
        "approver": lambda: _custom_member(world, "approver@example.com", "viewer", {"approve_posts": True}),
        "facing": lambda: _custom_member(
            world, "facing@example.com", "client", {"client_facing": True, "approve_posts": True}
        ),
    }.get(who, lambda: getattr(world, who))()

    html = _get(client, user, world, "advanced").content.decode()

    assert ('data-testid="settings-advanced-outcomes"' in html) is reads_outcomes
    assert client.get(_url("studio:outcomes", world)).status_code == (200 if reads_outcomes else 403)


def test_verifying_a_claim_from_advanced_goes_through_its_page(client, world):
    _advanced_on(world)
    client.force_login(world.owner)
    action = _url("studio:trust", world)
    assert f'action="{action}"' in client.get(_settings(world, "advanced")).content.decode()

    response = client.post(action, _claim_payload(world))

    assert response.status_code == 302 and response["Location"] == action
    assert BrandClaim.objects.filter(workspace=world.workspace, claim="One verified unit remains.").exists()


# --- accessibility -----------------------------------------------------------------


@pytest.mark.parametrize("tab", ["brand", "team", "autopilot", "notifications", "advanced"])
def test_the_new_and_grown_tabs_pass_the_accessibility_sweep(client, world, tab):
    """The three new tabs, and Brand and Team & clients, which gained the pages that moved into them."""
    _advanced_on(world)
    make_claim(world)
    _client_member(world)
    html = _get(client, world.owner, world, tab).content.decode()

    audit = _Audit()
    audit.feed(html)
    audit.finish()
    assert audit.unnamed_buttons == [] and audit.unnamed_controls == []
    faint = [m.group(3) for m in FAINT_TEXT.finditer(html) if m.group(3).strip() not in ("•", "·", "&bull;")]
    assert faint == []
    ids = re.findall(r'\sid="([^"]+)"', html)
    assert sorted({i for i in ids if ids.count(i) > 1}) == []
