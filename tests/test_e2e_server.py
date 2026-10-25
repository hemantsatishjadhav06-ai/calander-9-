"""The end-to-end server (tests/e2e/server): mounted only where it belongs, nothing leaves the machine.

These run under ``config.settings.test`` like the rest of the suite. The harness views are reached by
pointing ``ROOT_URLCONF`` at the e2e URL conf; they still refuse to answer until ``SETTINGS_MODULE``
also says ``config.settings.e2e``, which the tests that exercise them set explicitly.
"""

from __future__ import annotations

import ast
import json
import os
import pkgutil
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from django.conf import settings as django_settings
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.test import Client

REPO = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO / "tests" / "e2e" / "server"
WORKSPACE_A = "00000000-0000-4000-8000-00000000000a"
WORKSPACE_B = "00000000-0000-4000-8000-00000000000b"
E2E_URLCONF = "tests.e2e.server.urls"
E2E_SETTINGS = "config.settings.e2e"


@pytest.fixture
def e2e_urls(settings):
    """The harness URL conf, with the settings module the views insist on."""
    settings.ROOT_URLCONF = E2E_URLCONF
    settings.SETTINGS_MODULE = E2E_SETTINGS
    return settings


@pytest.fixture
def seeded(db):
    from tests.e2e.server import seed

    return seed.run()


def _post_json(client: Client, path: str, payload: Any, **extra: Any):
    return client.post(path, data=json.dumps(payload), content_type="application/json", **extra)


# ---------------------------------------------------------------------------
# Where the harness is mounted
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_harness_paths_are_404_under_the_test_settings(client):
    assert client.get("/__e2e__/ping").status_code == 404
    assert _post_json(client, "/__e2e__/fixture/session", {"role": "owner"}).status_code == 404
    assert client.get("/__e2e__/probe/refused_network").status_code == 404


@pytest.mark.django_db
def test_harness_views_are_404_unless_the_settings_module_is_e2e(client, settings):
    settings.ROOT_URLCONF = E2E_URLCONF
    settings.SETTINGS_MODULE = "config.settings.test"
    assert client.get("/__e2e__/ping").status_code == 404
    assert _post_json(client, "/__e2e__/fixture/session", {"role": "owner"}).status_code == 404
    assert client.get("/__e2e__/probe/refused_network").status_code == 404


def test_config_never_mounts_the_harness():
    for path in (REPO / "config").rglob("*.py"):
        assert "__e2e__" not in path.read_text(), path
    assert "tests.e2e" not in (REPO / "config" / "urls.py").read_text()


@pytest.mark.django_db
def test_harness_refuses_non_loopback_addresses(client, e2e_urls):
    for address in ("203.0.113.9", "10.0.0.7", "192.168.1.20"):
        assert client.get("/__e2e__/ping", REMOTE_ADDR=address).status_code == 403
        response = _post_json(client, "/__e2e__/fixture/session", {"role": "owner"}, REMOTE_ADDR=address)
        assert response.status_code == 403
        assert client.get("/__e2e__/probe/refused_network", REMOTE_ADDR=address).status_code == 403


@pytest.mark.django_db
def test_harness_refuses_cross_site_requests_and_non_json_fixture_bodies(client, e2e_urls, seeded):
    # A page on another site, open in the developer's browser, can send a blind text/plain or form POST
    # to the loopback server without a preflight; the harness refuses it before any step runs.
    sessions = Session.objects.count()
    body = json.dumps({"role": "owner"})
    assert client.post("/__e2e__/fixture/session", data=body, content_type="text/plain").status_code == 415
    assert client.post("/__e2e__/fixture/session", {"role": "owner"}).status_code == 415
    cross_site: list[dict[str, str]] = [
        {"HTTP_ORIGIN": "https://attacker.example"},
        {"HTTP_ORIGIN": "http://localhost:3000"},
        {"HTTP_ORIGIN": "null"},
        {"HTTP_SEC_FETCH_SITE": "cross-site"},
        {"HTTP_SEC_FETCH_SITE": "same-site"},
    ]
    for headers in cross_site:
        assert _post_json(client, "/__e2e__/fixture/session", {"role": "owner"}, **headers).status_code == 403, headers
        assert client.get("/__e2e__/ping", **headers).status_code == 403, headers
        assert client.get("/__e2e__/probe/refused_network", **headers).status_code == 403, headers
    assert Session.objects.count() == sessions

    # The server's own origin passes, and so does a request with neither header (Playwright's request context).
    same_origin = {"HTTP_ORIGIN": "http://testserver", "HTTP_SEC_FETCH_SITE": "same-origin"}
    assert _post_json(client, "/__e2e__/fixture/session", {"role": "owner"}, **same_origin).status_code == 200
    assert client.get("/__e2e__/ping", HTTP_SEC_FETCH_SITE="none").status_code == 200
    assert _post_json(client, "/__e2e__/fixture/session", {"role": "owner"}).status_code == 200
    assert Session.objects.count() == sessions + 2


@pytest.mark.django_db
def test_the_app_is_still_served_under_the_e2e_url_conf(client, e2e_urls):
    assert client.get("/health/").status_code == 200
    assert client.get("/accounts/login/").status_code == 200


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def test_database_guard_needs_a_name_ending_in_e2e():
    from tests.e2e.server import guard

    for name in ("brightbean_test", "brightbean", "test_brightbean_e2e_copy", "", "e2e", "brightbean_E2E"):
        with pytest.raises(guard.GuardError):
            guard.assert_e2e_database(name)
    for name in ("brightbean_e2e", "brightbean_g3_e2e"):
        guard.assert_e2e_database(name)


def test_database_host_guard_allows_this_machine_only():
    from tests.e2e.server import guard

    for host in ("localhost", "LOCALHOST", "127.0.0.1", "127.0.0.53", "::1", "", "/var/run/postgresql"):
        guard.assert_local_database_host(host)
    for host in ("db.e2e.invalid", "10.0.0.5", "203.0.113.4", "localhost.e2e.invalid", "localhost,10.0.0.5", None):
        with pytest.raises(guard.GuardError):
            guard.assert_local_database_host(host)


def test_settings_guard_refuses_the_test_settings():
    from tests.e2e.server import guard

    assert django_settings.SETTINGS_MODULE == "config.settings.test"
    assert guard.is_e2e_settings() is False
    with pytest.raises(guard.GuardError):
        guard.assert_e2e_settings()


def test_reset_is_refused_before_any_connection(monkeypatch, settings):
    import psycopg

    from tests.e2e.server import __main__ as server_main
    from tests.e2e.server import guard

    def no_connection(*args, **kwargs):
        raise AssertionError("reset_database connected although a guard should have refused")

    monkeypatch.setattr(psycopg, "connect", no_connection)
    with pytest.raises(guard.GuardError):
        server_main.reset_database()
    # The e2e module but a database whose name does not end in _e2e: still refused.
    settings.SETTINGS_MODULE = E2E_SETTINGS
    assert not settings.DATABASES["default"]["NAME"].endswith("_e2e")
    with pytest.raises(guard.GuardError):
        server_main.reset_database()


@pytest.mark.parametrize(
    ("argv", "stale", "expected"),
    [
        # Values left in the shell by an earlier run (a Lighthouse server on another port) lose to the flags.
        (
            ["--port", "8155"],
            {"E2E_STATIC": "manifest", "E2E_BASE_URL": "http://127.0.0.1:9999"},
            {"E2E_STATIC": "", "E2E_BASE_URL": "http://127.0.0.1:8155"},
        ),
        (
            ["--port", "8155"],
            {"E2E_BASE_URL": "https://staging.e2e.invalid:8155"},
            {"E2E_STATIC": "", "E2E_BASE_URL": "http://127.0.0.1:8155"},
        ),
        # A base URL for this very server (as playwright.config.ts passes it) is kept.
        (
            ["--port", "8155", "--static", "manifest"],
            {"E2E_BASE_URL": "http://localhost:8155"},
            {"E2E_STATIC": "manifest", "E2E_BASE_URL": "http://localhost:8155"},
        ),
    ],
)
def test_server_flags_win_over_a_stale_environment(monkeypatch, capsys, argv, stale, expected):
    import django

    from tests.e2e.server import __main__ as server_main

    for name in ("E2E_PORT", "E2E_STATIC", "E2E_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    for name, value in stale.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(django, "setup", lambda: None)  # these settings are already set up (and not e2e)

    assert server_main.main([*argv, "--no-worker"]) == 2  # refused by the settings guard, after the environment
    assert {name: os.environ.get(name) for name in expected} == expected
    assert os.environ["E2E_PORT"] == "8155"
    assert "config.settings.e2e" in capsys.readouterr().err


def _server_env(**overrides: str) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"DB_NAME", "DJANGO_SETTINGS_MODULE"} and not k.startswith("E2E_")
    }
    env.update(overrides)
    return env


def test_server_command_refuses_other_settings_modules():
    result = subprocess.run(
        [sys.executable, "-m", "tests.e2e.server", "--reset", "--no-worker"],
        cwd=REPO,
        env=_server_env(DJANGO_SETTINGS_MODULE="config.settings.test"),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0
    assert "config.settings.e2e" in result.stderr


def test_server_command_refuses_a_database_not_named_for_e2e():
    result = subprocess.run(
        [sys.executable, "-m", "tests.e2e.server", "--reset", "--no-worker"],
        cwd=REPO,
        env=_server_env(DJANGO_SETTINGS_MODULE=E2E_SETTINGS, DB_NAME="brightbean_test"),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0
    assert "_e2e" in result.stderr


def test_server_command_refuses_a_database_host_off_this_machine():
    # --reset drops and re-creates the database: never on another machine, whatever DB_HOST says.
    result = subprocess.run(
        [sys.executable, "-m", "tests.e2e.server", "--reset", "--no-worker"],
        cwd=REPO,
        env=_server_env(
            DJANGO_SETTINGS_MODULE=E2E_SETTINGS, DB_NAME="brightbean_hostcheck_e2e", DB_HOST="db.e2e.invalid"
        ),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 2, result.stderr[-2000:]
    assert "db.e2e.invalid" in result.stderr
    assert "Traceback" not in result.stderr


def test_server_command_without_reset_says_so_when_the_database_is_missing():
    missing = f"brightbean_missing_{os.getpid()}_{int(time.time())}_e2e"
    result = subprocess.run(
        [sys.executable, "-m", "tests.e2e.server", "--no-worker"],
        cwd=REPO,
        env=_server_env(DJANGO_SETTINGS_MODULE=E2E_SETTINGS, DB_NAME=missing),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 2, result.stderr[-2000:]
    assert "--reset" in result.stderr
    assert "Traceback" not in result.stderr


# ---------------------------------------------------------------------------
# The settings module
# ---------------------------------------------------------------------------

#: Secret settings ``base`` reads that a developer's ``.env`` or shell may hold; the e2e server has none.
SECRET_SETTINGS = (
    "EMAIL_HOST_PASSWORD",
    "WEBHOOK_SECRET",
    "RESEND_WEBHOOK_SECRET",
    "YOUTUBE_WEBHOOK_SECRET",
    "FACEBOOK_WEBHOOK_VERIFY_TOKEN",
    "INSTAGRAM_LOGIN_WEBHOOK_VERIFY_TOKEN",
    "GMAIL_REFRESH_TOKEN",
    "BLOG_GITHUB_TOKEN",
    "STUDIO_SHARED_SECRET",
)

_SETTINGS_SCRIPT = """
import json
import django

django.setup()
from django.conf import settings
from apps.studio import llm

print(json.dumps({
    "module": settings.SETTINGS_MODULE,
    "debug": settings.DEBUG,
    "csp_report_only": settings.CSP_REPORT_ONLY,
    "ratelimit": settings.RATELIMIT_ENABLE,
    "allowed_hosts": settings.ALLOWED_HOSTS,
    "root_urlconf": settings.ROOT_URLCONF,
    "db_name": settings.DATABASES["default"]["NAME"],
    "storage": settings.STORAGES["default"]["BACKEND"],
    "staticfiles": settings.STORAGES["staticfiles"]["BACKEND"],
    "media_root": str(settings.MEDIA_ROOT),
    "static_root": str(settings.STATIC_ROOT),
    "cache": settings.CACHES["default"]["BACKEND"],
    "mail": settings.EMAIL_INNER_BACKEND,
    "hashers": settings.PASSWORD_HASHERS,
    "heartbeat": settings.PUBLISHER_HEARTBEAT_MAX_AGE,
    "app_url": settings.APP_URL,
    "configured": llm.is_configured(),
    "google": bool(settings.SOCIALACCOUNT_PROVIDERS["google"].get("APP", {}).get("client_id")),
    "x": bool(settings.PLATFORM_CREDENTIALS_FROM_ENV["x"]["client_id"]),
    "facebook_secret": bool(settings.PLATFORM_CREDENTIALS_FROM_ENV["facebook"]["app_secret"]),
    "signup": settings.SIGNUP_MODE,
    "sentry": settings.SENTRY_DSN,
    "intelligence": settings.INTELLIGENCE_ENABLED,
    "agency_max_active_briefs": settings.AGENCY_MAX_ACTIVE_BRIEFS,
    "studio_web_search": settings.STUDIO_WEB_SEARCH,
    "studio_effort": settings.STUDIO_EFFORT,
    "email_sending": settings.EMAIL_SENDING_ENABLED,
    "telegram_managed_bots": settings.TELEGRAM_MANAGED_BOTS_ENABLED,
    "launched_platforms": settings.LAUNCHED_PLATFORMS,
    "secrets": {name: getattr(settings, name, "") for name in __SECRETS__},
}))
""".replace("__SECRETS__", repr(SECRET_SETTINGS))

#: What the e2e settings take from the environment on purpose: the database to use (``DB_*``) and,
#: as in ``test.py``, a ``SECRET_KEY`` and salt when one is set. Everything else ``base`` reads is pinned.
E2E_ENVIRONMENT_KNOBS = frozenset(
    {"DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "SECRET_KEY", "ENCRYPTION_KEY_SALT"}
)

_RECORD_SCRIPT = """
import json

import environ

read = set()
_get_value = environ.Env.get_value


def get_value(self, var, *args, **kwargs):
    read.add(var)
    return _get_value(self, var, *args, **kwargs)


environ.Env.get_value = get_value

import django

django.setup()
from config.settings import e2e

print(json.dumps({"read": sorted(read), "pinned": sorted(e2e.E2E_PINNED_ENVIRONMENT)}))
"""


def _e2e_settings(**env: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-c", _SETTINGS_SCRIPT],
        cwd=REPO,
        env=_server_env(DJANGO_SETTINGS_MODULE=E2E_SETTINGS, **env),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_e2e_settings_are_production_like_and_self_contained():
    values = _e2e_settings()
    assert values["module"] == E2E_SETTINGS
    assert values["debug"] is False
    assert values["csp_report_only"] is False
    assert values["ratelimit"] is True
    assert set(values["allowed_hosts"]) <= {"127.0.0.1", "localhost", "[::1]"}
    assert values["root_urlconf"] == E2E_URLCONF
    assert values["db_name"] == "brightbean_e2e"
    assert values["storage"] == "django.core.files.storage.FileSystemStorage"
    assert values["staticfiles"] == "django.contrib.staticfiles.storage.StaticFilesStorage"
    assert Path(values["media_root"]).is_relative_to(REPO / "e2e_media")
    assert values["cache"] == "django.core.cache.backends.locmem.LocMemCache"
    assert values["mail"] == "django.core.mail.backends.locmem.EmailBackend"
    assert values["hashers"] == ["django.contrib.auth.hashers.MD5PasswordHasher"]
    assert values["heartbeat"] == 30
    assert values["app_url"] == "http://127.0.0.1:8150"
    assert values["configured"] is True
    assert values["google"] is True
    assert values["x"] is True
    assert values["facebook_secret"] is True
    assert values["signup"] == "open"
    assert values["sentry"] == ""
    assert values["intelligence"] is False


def test_e2e_settings_ignore_switches_and_secrets_a_developer_environment_holds():
    # What a developer's .env or exported dev.env may hold; CI has none of it, and the e2e server must
    # behave the same on both, with no secret of the developer's in its settings.
    leaked = "e2e-leak-check-not-a-secret"
    values = _e2e_settings(
        AGENCY_MAX_ACTIVE_BRIEFS="1",
        STUDIO_WEB_SEARCH="true",
        STUDIO_EFFORT="high",
        EMAIL_SENDING_ENABLED="false",
        TELEGRAM_MANAGED_BOTS_ENABLED="false",
        LAUNCHED_PLATFORMS="x",
        EMAIL_BACKEND_TYPE="smtp",
        **{name: leaked for name in SECRET_SETTINGS},
    )
    assert values["agency_max_active_briefs"] == 3
    assert values["studio_web_search"] is False
    assert values["studio_effort"] == ""
    assert values["email_sending"] is True
    assert values["telegram_managed_bots"] is True
    assert values["launched_platforms"] == ["bluesky", "mastodon", "devto"]
    assert values["mail"] == "django.core.mail.backends.locmem.EmailBackend"
    assert values["secrets"] == {name: "" for name in SECRET_SETTINGS}


def test_e2e_settings_pin_every_variable_base_reads():
    result = subprocess.run(
        [sys.executable, "-c", _RECORD_SCRIPT],
        cwd=REPO,
        env=_server_env(DJANGO_SETTINGS_MODULE=E2E_SETTINGS),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    values = json.loads(result.stdout.strip().splitlines()[-1])
    assert len(values["read"]) > 50
    unpinned = set(values["read"]) - set(values["pinned"]) - E2E_ENVIRONMENT_KNOBS
    assert not unpinned, (
        f"base reads these, so a .env could change the e2e server: pin them in config/settings/e2e.py: {sorted(unpinned)}"
    )


def test_e2e_settings_follow_the_environment_the_server_sets():
    values = _e2e_settings(DB_NAME="brightbean_g2_e2e", E2E_BASE_URL="http://127.0.0.1:8162", E2E_STATIC="manifest")
    assert values["db_name"] == "brightbean_g2_e2e"
    assert values["app_url"] == "http://127.0.0.1:8162"
    assert values["staticfiles"] == "whitenoise.storage.CompressedManifestStaticFilesStorage"
    assert Path(values["static_root"]).is_relative_to(REPO / "e2e_media")


# ---------------------------------------------------------------------------
# The seeded world
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_seed_builds_the_world_with_fixed_ids(seeded):
    from apps.media_library.models import MediaAsset
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.studio.models import AgencySettings, BrandClaim, BrandProfile
    from apps.workspaces.models import Workspace
    from tests.e2e.server import seed

    ids = seeded
    assert ids == seed.ids()
    assert ids["workspace_a"] == WORKSPACE_A
    assert ids["workspace_b"] == WORKSPACE_B

    ws_a = Workspace.objects.get(pk=WORKSPACE_A)
    ws_b = Workspace.objects.get(pk=WORKSPACE_B)
    assert ws_a.timezone == "Asia/Kolkata"
    assert ws_a.approval_workflow_mode == "required_internal"
    assert ws_a.require_dashboard_approval is True
    assert ws_a.organization.name == "E2E Agency"
    assert ws_a.organization.default_timezone == "Asia/Kolkata"
    assert ws_b.organization_id != ws_a.organization_id
    assert str(ws_a.organization_id) == ids["organisation_a"]
    assert str(ws_b.organization_id) == ids["organisation_b"]

    # No auto-provisioned "My Workspace" for any seeded person.
    assert not Workspace.objects.filter(name="My Workspace").exists()
    assert not Organization.objects.filter(name="My Organization").exists()

    roles = {"owner": "owner", "manager": "manager", "editor": "editor", "client": "client"}
    for key, role in roles.items():
        user = ids["users"][key]
        membership = WorkspaceMembership.objects.get(user_id=user["id"], workspace=ws_a)
        assert membership.workspace_role == role
        assert user["email"].endswith("@e2e.test")
    owner_b = ids["users"]["owner_b"]
    assert WorkspaceMembership.objects.get(user_id=owner_b["id"], workspace=ws_b).workspace_role == "owner"
    assert not WorkspaceMembership.objects.filter(user_id=owner_b["id"], workspace=ws_a).exists()
    assert OrgMembership.objects.get(user_id=ids["users"]["owner"]["id"], organization=ws_a.organization).org_role == (
        "owner"
    )

    for platform in ("linkedin_company", "instagram", "facebook"):
        account = SocialAccount.objects.get(pk=ids["accounts"][platform]["id"])
        assert account.workspace_id == ws_a.pk
        assert account.platform == platform
        assert account.connection_status == SocialAccount.ConnectionStatus.CONNECTED
        assert account.account_platform_id == ids["accounts"][platform]["platform_id"]

    assert BrandProfile.objects.filter(workspace=ws_a).exists()
    facts = BrandClaim.objects.filter(workspace=ws_a, is_active=True)
    assert facts.count() >= 2
    assert all(fact.verified_by_id is not None and fact.verified_at is not None for fact in facts)

    agency = AgencySettings.objects.get(workspace=ws_a)
    assert str(agency.lead_id) == ids["users"]["owner"]["id"]
    assert agency.autopilot_enabled is False
    assert agency.creation_mode == AgencySettings.CreationMode.CONFIRM

    asset = MediaAsset.objects.get(pk=ids["library_asset"]["id"])
    assert asset.workspace_id == ws_a.pk
    assert asset.media_type == MediaAsset.MediaType.IMAGE
    assert asset.processing_status == MediaAsset.ProcessingStatus.COMPLETED


@pytest.mark.django_db
def test_seeded_people_land_on_their_workspace(seeded):
    from apps.accounts.models import User

    expected = {
        "owner": f"/workspace/{WORKSPACE_A}/studio/",
        "manager": f"/workspace/{WORKSPACE_A}/studio/",
        "editor": f"/workspace/{WORKSPACE_A}/studio/",
        "client": f"/workspace/{WORKSPACE_A}/calendar/",
        "owner_b": f"/workspace/{WORKSPACE_B}/studio/",
    }
    for key, landing in expected.items():
        user = User.objects.get(pk=seeded["users"][key]["id"])
        assert user.tos_accepted_at is not None
        browser = Client()
        browser.force_login(user)
        response = browser.get("/")
        assert response.status_code == 302, key
        assert response["Location"] == landing, key


@pytest.mark.django_db
def test_seed_queues_no_platform_work(seeded):
    from background_task.models import Task

    assert not Task.objects.filter(task_name__contains="backfill_account_analytics").exists()


@pytest.mark.django_db
def test_seed_password_signs_in_through_the_form(seeded):
    response = Client().post(
        "/accounts/login/", {"login": seeded["users"]["owner"]["email"], "password": seeded["password"]}
    )
    assert response.status_code == 302


# ---------------------------------------------------------------------------
# Registry, fixtures and probes
# ---------------------------------------------------------------------------


@pytest.fixture
def scratch_registry(monkeypatch):
    from tests.e2e.server import registry

    registry.load_steps()  # the built-ins register into the real tables, never into this test's copies
    monkeypatch.setattr(registry, "FIXTURES", dict(registry.FIXTURES))
    monkeypatch.setattr(registry, "PROBES", dict(registry.PROBES))
    return registry


@pytest.mark.django_db
def test_registered_fixture_and_probe_are_callable_by_name(client, e2e_urls, scratch_registry):
    registry = scratch_registry

    @registry.fixture("selftest_echo")
    def echo(payload: dict[str, Any]) -> dict[str, Any]:
        if "fail" in payload:
            raise registry.PayloadError("fail was set")
        return {"echo": payload}

    @registry.probe("selftest_params")
    def params(payload: dict[str, Any]) -> dict[str, Any]:
        return {"params": payload}

    response = _post_json(client, "/__e2e__/fixture/selftest_echo", {"a": 1})
    assert response.status_code == 200
    assert response.json() == {"echo": {"a": 1}}

    response = client.get("/__e2e__/probe/selftest_params", {"k": "v", "n": "2"})
    assert response.status_code == 200
    assert response.json() == {"params": {"k": "v", "n": "2"}}

    response = _post_json(client, "/__e2e__/fixture/selftest_echo", {"fail": True})
    assert response.status_code == 400
    assert response.json() == {"error": "fail was set"}

    with pytest.raises(ValueError):
        registry.fixture("selftest_echo")(echo)


@pytest.mark.django_db
def test_unknown_names_bad_bodies_and_wrong_methods(client, e2e_urls):
    assert _post_json(client, "/__e2e__/fixture/no_such_fixture", {}).status_code == 404
    assert client.get("/__e2e__/probe/no_such_probe").status_code == 404

    bad = client.post("/__e2e__/fixture/session", data="{not json", content_type="application/json")
    assert bad.status_code == 400
    assert "error" in bad.json()
    assert _post_json(client, "/__e2e__/fixture/session", [1, 2]).status_code == 400

    assert client.get("/__e2e__/fixture/session").status_code == 405
    assert client.post("/__e2e__/probe/refused_network").status_code == 405
    # An unknown name is a 404 whatever the method; only a known name answers 405 to the wrong one.
    assert client.get("/__e2e__/fixture/no_such_fixture").status_code == 404
    assert client.post("/__e2e__/probe/no_such_probe").status_code == 404


def test_every_step_module_registers_itself():
    import tests.e2e.server.steps as steps_package
    from tests.e2e.server import registry

    names = {info.name for info in pkgutil.iter_modules(steps_package.__path__)}
    assert "core" in names
    for name in names:
        assert f"tests.e2e.server.steps.{name}" in sys.modules
    assert {"session", "reset_login_limits", "set_agent_delay", "magic_link"} <= set(registry.FIXTURES)
    assert "refused_network" in registry.PROBES


def test_no_server_module_runs_code_from_a_string():
    banned_names = {"exec", "eval", "compile", "__import__"}
    banned_attributes = {"exec", "eval"}  # builtins.exec(...), builtins.eval(...)
    paths = list(SERVER_DIR.rglob("*.py"))
    assert len(paths) >= 10
    for path in paths:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    assert func.id not in banned_names, f"{path}:{node.lineno} calls {func.id}"
                if isinstance(func, ast.Attribute):
                    assert func.attr not in banned_attributes, f"{path}:{node.lineno} calls {func.attr}"


# ---------------------------------------------------------------------------
# Built-in steps
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_ping_returns_the_seeded_ids(client, e2e_urls, seeded):
    response = client.get("/__e2e__/ping")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["ids"] == json.loads(json.dumps(seeded))
    assert set(body["ids"]["users"]) == {"owner", "manager", "editor", "client", "owner_b"}
    assert set(body["ids"]["accounts"]) == {"linkedin_company", "instagram", "facebook"}


@pytest.mark.django_db
def test_ping_says_when_the_database_is_not_seeded(client, e2e_urls):
    response = client.get("/__e2e__/ping")
    assert response.status_code == 503
    assert response.json()["ok"] is False


@pytest.mark.django_db
def test_ping_says_when_the_database_is_missing_or_not_migrated(client, e2e_urls, monkeypatch):
    from django.db import OperationalError, ProgrammingError

    from apps.workspaces.models import Workspace
    from tests.e2e.server import seed

    for error in (OperationalError('database "brightbean_e2e" does not exist'), ProgrammingError("no such table")):

        def unavailable(*args: Any, error: Exception = error, **kwargs: Any) -> Any:
            raise error

        monkeypatch.setattr(Workspace.objects, "get", unavailable)
        with pytest.raises(seed.SeedMissingError, match="--reset"):
            seed.ids()
        response = client.get("/__e2e__/ping")
        assert response.status_code == 503, type(error)
        assert response.json()["ok"] is False


@pytest.mark.django_db
def test_session_fixture_signs_each_role_in(client, e2e_urls, seeded):
    landings = {
        "owner": f"/workspace/{WORKSPACE_A}/studio/",
        "manager": f"/workspace/{WORKSPACE_A}/studio/",
        "editor": f"/workspace/{WORKSPACE_A}/studio/",
        "client": f"/workspace/{WORKSPACE_A}/calendar/",
    }
    for role, landing in landings.items():
        response = _post_json(client, "/__e2e__/fixture/session", {"role": role})
        assert response.status_code == 200, response.content
        cookie = response.json()["cookie"]
        assert cookie["name"] == django_settings.SESSION_COOKIE_NAME
        session = Session.objects.get(session_key=cookie["value"])
        assert session.get_decoded()[SESSION_KEY] == seeded["users"][role]["id"]

        browser = Client()
        browser.cookies[cookie["name"]] = cookie["value"]
        first = browser.get("/")
        assert first["Location"] == landing, role
        assert browser.get(landing).status_code == 200, role


@pytest.mark.django_db
def test_session_fixture_by_email_and_refusals(client, e2e_urls, seeded):
    email = seeded["users"]["editor"]["email"]
    response = _post_json(client, "/__e2e__/fixture/session", {"email": email})
    assert response.status_code == 200
    session = Session.objects.get(session_key=response.json()["cookie"]["value"])
    assert session.get_decoded()[SESSION_KEY] == seeded["users"]["editor"]["id"]

    for payload in ({"role": "admiral"}, {"email": "nobody@e2e.test"}, {}, {"role": 3}):
        refused = _post_json(client, "/__e2e__/fixture/session", payload)
        assert refused.status_code == 400, payload
        assert "error" in refused.json()


@pytest.mark.django_db
def test_reset_login_limits_reopens_the_login_form(client, e2e_urls, seeded):
    email = seeded["users"]["owner"]["email"]
    browser = Client()
    statuses = [browser.post("/accounts/login/", {"login": email, "password": "wrong"}).status_code for _ in range(11)]
    assert statuses[-1] == 429

    response = _post_json(client, "/__e2e__/fixture/reset_login_limits", {})
    assert response.status_code == 200
    assert response.json()["cleared"] > 0

    signed_in = browser.post("/accounts/login/", {"login": email, "password": seeded["password"]})
    assert signed_in.status_code == 302


@pytest.mark.django_db
def test_set_agent_delay(client, e2e_urls):
    from tests.e2e.server import fakes

    try:
        response = _post_json(client, "/__e2e__/fixture/set_agent_delay", {"seconds": 1.5})
        assert response.status_code == 200
        assert response.json() == {"seconds": 1.5}
        assert fakes.agent_delay() == 1.5
        for payload in ({"seconds": -1}, {"seconds": "soon"}, {}, {"seconds": 600}):
            assert _post_json(client, "/__e2e__/fixture/set_agent_delay", payload).status_code == 400, payload
    finally:
        fakes.set_agent_delay(0)


@pytest.mark.django_db
def test_magic_link_fixture(client, e2e_urls, seeded):
    from apps.client_portal.models import MagicLinkToken

    payload = {"email": seeded["users"]["client"]["email"], "workspace_id": WORKSPACE_A}
    response = _post_json(client, "/__e2e__/fixture/magic_link", payload)
    assert response.status_code == 200
    url = response.json()["url"]
    match = re.fullmatch(r"/portal/([^/]+)/", url)
    assert match
    token = MagicLinkToken.objects.get(token=match.group(1))
    assert str(token.user_id) == seeded["users"]["client"]["id"]
    assert str(token.workspace_id) == WORKSPACE_A
    assert Client().get(url).status_code == 200

    not_a_client = {"email": seeded["users"]["editor"]["email"], "workspace_id": WORKSPACE_A}
    assert _post_json(client, "/__e2e__/fixture/magic_link", not_a_client).status_code == 400
    assert _post_json(client, "/__e2e__/fixture/magic_link", {"email": payload["email"]}).status_code == 400


@pytest.mark.django_db
def test_refused_network_probe_lists_the_guard_and_the_mock(client, e2e_urls, monkeypatch):
    from tests.e2e.server import mocks, netguard

    mocks.install(setter=monkeypatch.setattr)
    mocks.reset()
    netguard.install(allowed_ports=())
    try:
        with pytest.raises(OSError), socket.socket() as sock:
            sock.connect(("198.51.100.4", 443))
        with pytest.raises(httpx.ConnectError), httpx.Client() as http:
            http.get("https://api.telegram.org/bot123:abc/getMe?token=secret")
    finally:
        netguard.uninstall()

    response = client.get("/__e2e__/probe/refused_network")
    assert response.status_code == 200
    body = response.json()
    assert "198.51.100.4" in body["hosts"]
    assert "api.telegram.org" in body["hosts"]
    assert any(item["host"] == "198.51.100.4" for item in body["refused"])
    assert any(item["host"] == "api.telegram.org" for item in body["unanswered"])
    assert "secret" not in response.content.decode()
    assert "bot123" not in response.content.decode()

    later = client.get("/__e2e__/probe/refused_network", {"since": str(time.time() + 60)}).json()
    assert later["hosts"] == []
    netguard.clear()
    mocks.reset()


# ---------------------------------------------------------------------------
# The socket guard
# ---------------------------------------------------------------------------


@pytest.fixture
def guarded():
    from tests.e2e.server import netguard

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    port = listener.getsockname()[1]
    netguard.clear()
    netguard.install(allowed_ports=(port,))
    try:
        yield netguard, port
    finally:
        netguard.uninstall()
        netguard.clear()
        listener.close()


def test_netguard_refuses_and_records_outside_connections(guarded):
    netguard, _port = guarded
    with pytest.raises(ConnectionRefusedError), socket.socket() as sock:
        sock.connect(("203.0.113.50", 80))
    with socket.socket() as sock:
        assert sock.connect_ex(("203.0.113.51", 80)) != 0
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("api.linkedin.com", 443)
    hosts = [item["host"] for item in netguard.refused()]
    assert hosts == ["203.0.113.50", "203.0.113.51", "api.linkedin.com"]
    assert all(item["port"] in (80, 443) for item in netguard.refused())


def test_netguard_allows_loopback_on_the_allowed_ports_only(guarded):
    netguard, port = guarded
    with socket.create_connection(("127.0.0.1", port), timeout=2):
        pass
    socket.getaddrinfo("localhost", port)
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    other_port = closed.getsockname()[1]
    closed.close()
    with pytest.raises(ConnectionRefusedError), socket.socket() as sock:
        sock.connect(("127.0.0.1", other_port))
    assert [item["port"] for item in netguard.refused()] == [other_port]


def test_netguard_lets_a_named_host_resolve_but_never_connects_off_the_machine(guarded):
    netguard, port = guarded
    netguard.install(allowed_ports=(port,), allowed_hosts=("db.e2e.invalid",))
    for target_port in (port, 6543):
        with pytest.raises(ConnectionRefusedError), socket.socket() as sock:
            sock.connect(("db.e2e.invalid", target_port))
    refused = [(item["kind"], item["host"], item["port"]) for item in netguard.refused()]
    assert refused == [("connect", "db.e2e.invalid", port), ("connect", "db.e2e.invalid", 6543)]


def test_netguard_uninstall_restores_the_socket_module():
    from tests.e2e.server import netguard

    original = (socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo)
    netguard.install(allowed_ports=())
    try:
        assert socket.getaddrinfo is not original[2]
    finally:
        netguard.uninstall()  # never leave the rest of the session behind a guard with no ports
    assert (socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo) == original


# ---------------------------------------------------------------------------
# Provider HTTP mock
# ---------------------------------------------------------------------------


@pytest.fixture
def mocked(monkeypatch):
    from tests.e2e.server import mocks

    mocks.install(setter=monkeypatch.setattr)
    mocks.reset()
    yield mocks
    mocks.reset()


def test_mock_answers_the_x_connection(mocked, settings):
    from providers import get_provider

    provider = get_provider("x", {"client_id": "e2e-x-client-id", "client_secret": "e2e-x-client-secret"})
    tokens = provider.exchange_code("e2e-code", "http://127.0.0.1:8150/social-accounts/callback/x/", "verifier")
    assert tokens.access_token
    profile = provider.get_profile(tokens.access_token)
    assert profile.platform_id == mocked.X_USER["id"]
    assert profile.handle == mocked.X_USER["username"]
    assert mocked.unanswered() == []


def test_mock_answers_a_facebook_comment_reply(mocked):
    from providers import get_provider

    provider = get_provider("facebook", {"app_id": "e2e", "app_secret": "e2e"})
    result = provider.reply_to_comment("page-token", "c-123", "Thank you!")
    assert result.platform_message_id == "e2e-reply-c-123"
    assert mocked.unanswered() == []


def test_mock_refuses_and_records_everything_else(mocked):
    with httpx.Client() as http, pytest.raises(httpx.ConnectError):
        http.get("https://api.linkedin.com/rest/organizationAcls?q=roleAssignee&access_token=abc")
    with pytest.raises(httpx.ConnectError):
        httpx.Client(transport=httpx.HTTPTransport()).get("https://models.e2e.invalid/v1/chat")
    unanswered = mocked.unanswered()
    assert [item["host"] for item in unanswered] == ["api.linkedin.com", "models.e2e.invalid"]
    assert all("?" not in item["url"] and "abc" not in item["url"] for item in unanswered)


@pytest.mark.django_db
def test_google_sign_in_is_answered_by_the_code(client, mocked, settings):
    from urllib.parse import parse_qs, urlparse

    from apps.accounts.models import User

    settings.SOCIALACCOUNT_PROVIDERS = {
        "google": {
            "SCOPE": ["profile", "email"],
            "AUTH_PARAMS": {"access_type": "online"},
            "VERIFIED_EMAIL": True,
            "APP": {"client_id": "e2e-google-client", "secret": "e2e-google-secret"},
        }
    }
    mocked.register_google_profile(
        "e2e-new-user", {"sub": "900001", "email": "new.person@e2e.test", "email_verified": True, "name": "New Person"}
    )

    def sign_in(code: str):
        html = client.get("/accounts/login/").content.decode()
        start = html.index('action="/accounts/google/login/') + len('action="')
        action = html[start : html.index('"', start)].replace("&amp;", "&")
        to_google = client.post(action)
        assert to_google.status_code == 302
        state = parse_qs(urlparse(to_google["Location"]).query)["state"][0]
        return client.get("/accounts/google/login/callback/", {"code": code, "state": state})

    assert sign_in("e2e-new-user").status_code == 302
    assert User.objects.filter(email="new.person@e2e.test").exists()
    client.logout()

    sign_in("unknown-code")
    assert any(item["host"] == "oauth2.googleapis.com" for item in mocked.unanswered())


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@pytest.fixture
def faked(monkeypatch):
    from tests.e2e.server import fakes

    team = fakes.install(setter=monkeypatch.setattr)
    yield fakes, team
    fakes.set_agent_delay(0)


def test_fakes_replace_every_model_path(faked):
    from apps.studio import agents, creative_sources, llm, openrouter, pipeline
    from apps.studio.roles import client as client_roles
    from apps.studio.roles import creative

    fakes, team = faked
    with pytest.raises(fakes.ProviderRefusedError):
        llm.get_client()
    with pytest.raises(fakes.ProviderRefusedError):
        openrouter.get_client()
    with pytest.raises(httpx.ConnectError):
        creative_sources.get_client()
    with pytest.raises(llm.StudioAgentError):
        llm.research(agent="moments", system=[], question="What is on this week?")
    for name in ("strategist", "copywriter", "art_director", "reviewer"):
        assert getattr(agents, name).__module__ == fakes.__name__, name
    for name in ("prompt_engineer", "channel_editor"):
        assert getattr(creative, name).__module__ == fakes.__name__, name
    assert isinstance(client_roles.account_manager, fakes.AccountManager)
    assert creative_sources.collect.__module__ == fakes.__name__
    # Unlike the fake_team fixture, the real queue stays in place for the worker.
    assert pipeline.enqueue.__module__ == "apps.studio.pipeline"
    assert team.calls["strategist"] == []


def test_fake_manager_drafts_a_brief_from_the_request(faked):
    from apps.studio.roles import client as client_roles

    result = client_roles.account_manager(
        None,
        audience="internal",
        speaker="Ana Owner",
        history=[],
        item="",
        request="A post about the open house on Instagram and LinkedIn, mention free parking",
        request_kind="create",
        allowed_actions=["answer", "escalate", "new_post"],
        guided=True,
        available_channels=["instagram", "linkedin_company", "facebook"],
    )
    answer = result.output
    assert answer.action == "new_post"
    assert answer.creative_brief is not None
    assert answer.creative_brief.channels == ["instagram", "linkedin_company"]
    assert answer.creative_brief.key_message == "Free parking"
    assert "open house" in answer.creative_brief.topic.lower()


def test_fake_manager_answers_questions_and_routines(faked):
    from apps.studio.roles import client as client_roles

    common: dict[str, Any] = {
        "audience": "internal",
        "speaker": "Ana",
        "history": [],
        "item": "",
        "allowed_actions": ["answer", "escalate", "new_post", "set_routine"],
    }
    question = client_roles.account_manager(None, request="What is waiting for me?", request_kind="question", **common)
    assert question.output.action == "answer"
    routine = client_roles.account_manager(
        None, request="Every weekday at 8:30 draft a market update", request_kind="question", **common
    )
    assert routine.output.action == "set_routine"
    assert routine.output.routine_cadence == "weekdays"
    assert routine.output.routine_time == "08:30"


def _answer_types() -> list[type]:
    import importlib

    import apps.studio.roles as roles_package
    from apps.studio.roles import base

    for info in pkgutil.iter_modules(roles_package.__path__):
        importlib.import_module(f"apps.studio.roles.{info.name}")
    importlib.import_module("apps.studio.schemas")

    found: list[type] = []
    pending = list(base.Answer.__subclasses__())
    while pending:
        cls = pending.pop()
        found.append(cls)
        pending.extend(cls.__subclasses__())
    return found


def test_generic_agent_answers_every_role_schema(faked):
    from apps.studio import llm

    types = _answer_types()
    assert len(types) > 10
    for output_type in types:
        result = llm.run_agent(agent="any", system=[], content=[], output_type=output_type, effort="low")
        assert isinstance(result.output, output_type), output_type


def test_agent_delay_slows_each_turn(faked):
    from apps.studio import llm
    from apps.studio.roles.client import ChatAnswer

    fakes, _team = faked
    fakes.set_agent_delay(0.2)
    started = time.monotonic()
    llm.run_agent(agent="any", system=[], content=[], output_type=ChatAnswer, effort="low")
    assert time.monotonic() - started >= 0.2


# ---------------------------------------------------------------------------
# The worker
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_worker_drops_the_platform_polls_and_keeps_the_rest():
    from background_task.models import Task

    from apps.common.background import ensure_recurring_tasks
    from tests.e2e.server import worker

    ensure_recurring_tasks()
    assert Task.objects.filter(verbose_name="run_inbox_sync_cycle").exists()
    worker.drop_platform_polls()
    for name in worker.PLATFORM_POLLS:
        assert not Task.objects.filter(verbose_name=name).exists(), name
    assert Task.objects.filter(verbose_name="run_publish_cycle").exists()
    assert Task.objects.filter(verbose_name="run_agency_cycle").exists()


@pytest.mark.django_db(transaction=True)
def test_worker_thread_starts_runs_tasks_and_stops():
    from tests.e2e.server import worker

    stop = threading.Event()
    thread = threading.Thread(target=worker.run_forever, kwargs={"stop": stop}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 30
        while not worker.status()["alive"] and time.monotonic() < deadline:
            time.sleep(0.1)
        assert worker.status()["alive"] is True
        deadline = time.monotonic() + 30
        while worker.status()["ran"] == 0 and time.monotonic() < deadline:
            time.sleep(0.2)
        assert worker.status()["ran"] > 0
    finally:
        stop.set()
        thread.join(timeout=30)
    status = worker.status()
    assert status["alive"] is False
    assert status["error"] == ""
