"""The e2e steps for Phase 3 (tests/e2e/server/steps/p3.py), under ``config.settings.test``.

``dark_ready`` declares pages dark-ready inside the e2e server's process, the way ``fakes.py`` puts
its stand-ins in place: it replaces ``apps.common.screens.DARK_READY``, which
``context_processors.theme_context`` reads on every render, so the next request for a declared page
carries ``data-theme-ready`` on ``<html>``. ``{"add": ["app:url", …]}`` adds pages to the set;
``{"clear": true}`` puts back the registry's own set (the pages the code declares). A browser spec
(``tests/e2e/self/theme.spec.ts``) adds the Account page and clears it after each test. What it
answers and the payloads it refuses are pinned here.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client

from apps.common import screens

WORKSPACE_A = "00000000-0000-4000-8000-00000000000a"
ACCOUNT = ("accounts", "settings")
HOME = ("studio", "index")


@pytest.fixture
def e2e_urls(settings):
    settings.ROOT_URLCONF = "tests.e2e.server.urls"
    settings.SETTINGS_MODULE = "config.settings.e2e"
    return settings


@pytest.fixture
def seeded(db):
    from tests.e2e.server import seed

    return seed.run()


@pytest.fixture(autouse=True)
def registry_restored(monkeypatch):
    """The step changes the process's registry; every test here leaves it as it found it."""
    monkeypatch.setattr(screens, "DARK_READY", screens.DARK_READY)


def _fixture(client: Client, name: str, payload: Any):
    return client.post(f"/__e2e__/fixture/{name}", data=json.dumps(payload), content_type="application/json")


def _signed_in(client: Client, email: str) -> Client:
    session = _fixture(client, "session", {"email": email}).json()
    browser = Client()
    browser.cookies[session["cookie"]["name"]] = session["cookie"]["value"]
    return browser


def _ready() -> frozenset[screens.Page]:
    """The process's declared pages now (the step replaces the registry's set)."""
    return screens.DARK_READY


def _html_tag(response) -> str:
    html = response.content.decode()
    start = html.index("<html")
    return html[start : html.index(">", start) + 1]


@pytest.mark.django_db
def test_dark_ready_declares_a_page_for_the_next_request(client, e2e_urls, seeded):
    owner = _signed_in(client, seeded["users"]["owner"]["email"])
    assert "data-theme-ready" not in _html_tag(owner.get("/accounts/settings/"))

    answer = _fixture(client, "dark_ready", {"add": ["accounts:settings"]})
    assert answer.status_code == 200, answer.content
    assert answer.json() == {"ready": sorted(f"{a}:{u}" for a, u in screens.DARK_READY)}
    assert ACCOUNT in screens.DARK_READY

    assert " data-theme-ready" in _html_tag(owner.get("/accounts/settings/"))
    # Only the declared page: Home of workspace A still renders as it did.
    assert "data-theme-ready" not in _html_tag(owner.get(f"/workspace/{WORKSPACE_A}/studio/"))


@pytest.mark.django_db
def test_dark_ready_adds_to_the_set_and_clear_puts_back_the_registrys_own(client, e2e_urls, seeded):
    own = screens.DARK_READY

    _fixture(client, "dark_ready", {"add": ["accounts:settings"]})
    answer = _fixture(client, "dark_ready", {"add": ["studio:index"]})
    assert answer.status_code == 200, answer.content
    assert _ready() == own | {ACCOUNT, HOME}
    assert answer.json() == {"ready": sorted({"accounts:settings", "studio:index"} | {f"{a}:{u}" for a, u in own})}

    cleared = _fixture(client, "dark_ready", {"clear": True})
    assert cleared.status_code == 200, cleared.content
    assert _ready() == own
    assert cleared.json() == {"ready": sorted(f"{a}:{u}" for a, u in own)}

    owner = _signed_in(client, seeded["users"]["owner"]["email"])
    assert ("data-theme-ready" in _html_tag(owner.get("/accounts/settings/"))) is (ACCOUNT in own)


@pytest.mark.django_db
def test_dark_ready_clears_before_it_adds(client, e2e_urls, seeded):
    own = screens.DARK_READY
    _fixture(client, "dark_ready", {"add": ["studio:index"]})
    answer = _fixture(client, "dark_ready", {"clear": True, "add": ["accounts:settings"]})
    assert answer.status_code == 200, answer.content
    assert _ready() == own | {ACCOUNT}
    assert answer.json() == {"ready": sorted({"accounts:settings"} | {f"{a}:{u}" for a, u in own})}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        {"add": "accounts:settings"},
        {"add": []},
        {"add": [""]},
        {"add": [7]},
        {"add": ["settings"]},
        {"add": ["accounts:nowhere"]},
        {"add": ["nowhere:settings"]},
        {"add": ["accounts:settings", "accounts:nowhere"]},
        {"clear": "yes"},
        {"clear": False},
        {"clear": True, "remove": ["accounts:settings"]},
    ],
)
def test_dark_ready_refuses_a_bad_payload_and_changes_nothing(client, e2e_urls, seeded, payload):
    before = screens.DARK_READY
    answer = _fixture(client, "dark_ready", payload)
    assert answer.status_code == 400, (payload, answer.content)
    assert answer.json()["error"]
    assert _ready() == before
