"""Activity (spec D4, R4): the Team page at ``/studio/activity/`` plus the routines, and its old addresses.

``studio:team`` names Activity now. ``/studio/team/`` and ``/studio/routines/`` answer a 301 there,
but only after the same checks the pages made before, so someone refused before is still refused,
never redirected.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.members.models import WorkspaceMembership
from apps.studio import routines, team
from apps.studio.models import Routine
from apps.workspaces.models import Workspace

PRESETS = ("Morning briefing", "Monday plan", "Draft replies to new comments")


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()
    yield
    cache.clear()


def _url(name, world, **kwargs):
    return reverse(name, kwargs={"workspace_id": world.workspace.id, **kwargs})


def _client_member(world):
    user = world.viewer.__class__.objects.create_user(
        email="client@example.com", password="pw-12345678", name="Client", tos_accepted_at=timezone.now()
    )
    WorkspaceMembership.objects.create(user=user, workspace=world.workspace, workspace_role="client")
    return user


def _routine(world, user, title):
    return routines.create(
        world.workspace,
        user,
        instruction="Tell me what is waiting.",
        cadence="daily",
        weekday=None,
        time=dt.time(9, 0),
        title=title,
    )


# --- the address ---------------------------------------------------------------


def test_studio_team_names_the_activity_address(world):
    assert _url("studio:team", world) == f"/workspace/{world.workspace.id}/studio/activity/"
    # The board's refresh and the job pages stay where open tabs and sent links expect them.
    assert _url("studio:team_board", world) == f"/workspace/{world.workspace.id}/studio/team/board/"
    assert _url("studio:team_legacy", world) == f"/workspace/{world.workspace.id}/studio/team/"


# --- the page ------------------------------------------------------------------


def test_activity_is_the_live_board_plus_the_routines_for_an_editor(client, world):
    mine = _routine(world, world.editor, "Mornings")
    client.force_login(world.editor)

    response = client.get(_url("studio:team", world))
    html = response.content.decode()

    assert response.status_code == 200
    # Everything the Team page carried: the status line the refresh replaces out of band, the board
    # polling every 5 s, the announcer and the script that drives them, and every agent.
    assert 'id="team-status"' in html
    assert 'id="team-board" data-live-board data-no-error-toast' in html
    assert "hx-trigger=\"every 5s [document.visibilityState === 'visible']\"" in html
    assert _url("studio:team_board", world) in html
    assert 'id="team-live-announce"' in html and "js/live_board.js" in html
    for agent in team.AGENTS:
        assert agent.name in html
    # The routines section: the list with its controls, and the three presets in one tap.
    assert 'id="routines"' in html
    assert "Mornings" in html and _url("studio:routines_run_now", world, routine_id=mine.pk) in html
    for preset in PRESETS:
        assert preset in html
    for key in routines.SUGGESTIONS:
        assert f'name="suggestion" value="{key}"' in html
    assert f'action="{_url("studio:routines_create", world)}"' in html
    # Outside the board, so the refresh every 5 s never wipes it.
    assert html.index('id="team-live-announce"') < html.index('id="routines"')
    assert 'id="routines"' not in client.get(_url("studio:team_board", world)).content.decode()


def test_activity_says_how_to_start_when_there_are_no_routines(client, world):
    client.force_login(world.owner)
    html = client.get(_url("studio:team", world)).content.decode()

    assert 'id="routines"' in html and "No routines yet" in html and "Asia/Kolkata" in html
    for preset in PRESETS:
        assert preset in html


def test_a_viewer_sees_the_board_but_no_routines(client, world):
    _routine(world, world.editor, "Mornings")
    client.force_login(world.viewer)

    response = client.get(_url("studio:team", world))
    html = response.content.decode()

    assert response.status_code == 200 and 'id="team-board"' in html
    assert 'id="routines"' not in html and "Mornings" not in html
    assert f'href="{_url("studio:routines", world)}"' not in html
    assert _url("studio:routines_create", world) not in html
    for preset in PRESETS:
        assert f"Add “{preset}”" not in html


def test_activity_never_shows_another_workspaces_routine(client, world):
    other = Workspace.objects.create(organization=world.org, name="Other", timezone="Asia/Kolkata")
    WorkspaceMembership.objects.create(user=world.owner, workspace=other, workspace_role="owner")
    foreign = routines.create(
        other, world.owner, instruction="Elsewhere.", cadence="daily", weekday=None, time=dt.time(9, 0), title="Theirs"
    )
    client.force_login(world.owner)

    html = client.get(_url("studio:team", world)).content.decode()

    assert str(foreign.pk) not in html and "Theirs" not in html


# --- the old addresses: refuse first, then a 301 --------------------------------


def test_the_old_team_address_moves_to_activity_after_the_same_checks(client, world):
    old = _url("studio:team_legacy", world)

    response = client.get(old)
    assert response.status_code == 302 and "login" in response["Location"]

    client.force_login(_client_member(world))
    assert client.get(old).status_code == 403

    client.force_login(world.outsider)
    assert client.get(old).status_code in (403, 404)

    for person in (world.viewer, world.editor, world.owner):
        client.force_login(person)
        response = client.get(old)
        assert response.status_code == 301, person
        assert response["Location"] == _url("studio:team", world)
    assert client.post(old).status_code == 405


def test_the_routines_page_moves_to_activitys_routines_after_the_same_checks(client, world):
    old = _url("studio:routines", world)

    response = client.get(old)
    assert response.status_code == 302 and "login" in response["Location"]

    for person in (_client_member(world), world.viewer):
        client.force_login(person)
        assert client.get(old).status_code == 403

    client.force_login(world.outsider)
    assert client.get(old).status_code in (403, 404)

    for person in (world.editor, world.owner):
        client.force_login(person)
        response = client.get(old)
        assert response.status_code == 301, person
        assert response["Location"] == _url("studio:team", world) + "#routines"


def test_a_preset_lands_back_on_activitys_routines(client, world):
    client.force_login(world.editor)

    response = client.post(_url("studio:routines_create", world), {"suggestion": "morning"}, follow=True)

    assert response.redirect_chain == [
        (_url("studio:routines", world), 302),
        (_url("studio:team", world) + "#routines", 301),
    ]
    html = response.content.decode()
    assert response.status_code == 200 and "Saved" in html and 'id="routines"' in html
    assert Routine.objects.get().title == "Morning briefing"


def test_a_routine_that_fails_to_save_comes_back_with_the_form(client, world):
    client.force_login(world.editor)

    response = client.post(
        _url("studio:routines_create", world),
        {"instruction": "Say hello.", "cadence": "weekly", "weekday": "2", "time": "25:99", "title": "Hello"},
    )
    html = response.content.decode()

    assert response.status_code == 400 and "time of day" in html
    # The free-form form, with what was typed, and the presets beside it.
    assert 'id="routine-instruction"' in html and "Say hello." in html and 'value="Hello"' in html
    assert '<option value="2" selected>' in html and 'name="cadence"' in html
    for preset in PRESETS:
        assert preset in html
    assert not Routine.objects.exists()
