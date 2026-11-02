"""Render runs the app; https://sm-bean.netlify.app is the address people use.

Netlify proxies every request to the Render web service and, as a proxy to another host must, sends
that service's own name as ``Host`` (``sm-bean-web.onrender.com``). It sends no ``X-Forwarded-Host``
and strips one a client sends, so ``USE_X_FORWARDED_HOST`` has nothing to read. Render's health
check also calls ``/health/`` under that name.

Three things follow. The platform's hostname must be allowed and trusted for CSRF (Render sets it as
``RENDER_EXTERNAL_HOSTNAME`` at runtime). A request under that name must be answered as the public
host, or every absolute URL the app builds from the request — OAuth redirect URIs, onboarding links,
the sitemap — would point at ``*.onrender.com``, where the visitor's session cookie does not exist.
And none of that may let a client choose the host: the mapping only ever yields ``APP_URL``'s host.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.exceptions import DisallowedHost
from django.http import HttpResponse
from django.test import Client, RequestFactory, override_settings

from apps.common.middleware import FrontDoorHostMiddleware

REPO = Path(__file__).resolve().parents[3]
PUBLIC = "sm-bean.netlify.app"
PLATFORM = "sm-bean-web.onrender.com"

_SETTINGS_SCRIPT = """
import json
import config.settings.production as s
print(json.dumps({
    "allowed_hosts": s.ALLOWED_HOSTS,
    "csrf_trusted_origins": s.CSRF_TRUSTED_ORIGINS,
    "platform_hostnames": list(s.PLATFORM_HOSTNAMES),
    "media_storage": s.STORAGES["default"]["BACKEND"],
    "middleware": s.MIDDLEWARE,
}))
"""


def production_settings(**env: str) -> dict:
    """Import the production settings in a clean process with exactly this environment."""
    environment = {
        "PATH": "/usr/bin:/bin",
        "SECRET_KEY": "s" * 50,
        "ENCRYPTION_KEY_SALT": "e" * 32,
        "DATABASE_URL": "postgres://u:p@localhost:5432/db",
        "APP_URL": f"https://{PUBLIC}",
        "ALLOWED_HOSTS": PUBLIC,
        "CSRF_TRUSTED_ORIGINS": f"https://{PUBLIC}",
        "RENDER_EXTERNAL_HOSTNAME": "",
        "STORAGE_BACKEND": "local",
        "S3_BUCKET_NAME": "",
        "MEDIA_STORAGE_PENDING": "false",
        "SENTRY_DSN": "",
        **env,
    }
    result = subprocess.run(
        [sys.executable, "-c", _SETTINGS_SCRIPT], cwd=REPO, env=environment, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


# --- settings -------------------------------------------------------------------------------------


def test_on_render_the_platform_hostname_is_allowed_and_trusted():
    values = production_settings(RENDER_EXTERNAL_HOSTNAME=PLATFORM)
    assert values["allowed_hosts"] == [PUBLIC, PLATFORM]
    assert values["csrf_trusted_origins"] == [f"https://{PUBLIC}", f"https://{PLATFORM}"]
    assert values["platform_hostnames"] == [PLATFORM]


def test_off_render_nothing_is_added():
    values = production_settings()
    assert values["allowed_hosts"] == [PUBLIC]
    assert values["csrf_trusted_origins"] == [f"https://{PUBLIC}"]
    assert values["platform_hostnames"] == []


def test_a_hostname_already_listed_is_not_listed_twice():
    values = production_settings(
        RENDER_EXTERNAL_HOSTNAME=PLATFORM,
        ALLOWED_HOSTS=f"{PUBLIC},{PLATFORM}",
        CSRF_TRUSTED_ORIGINS=f"https://{PUBLIC},https://{PLATFORM}",
    )
    assert values["allowed_hosts"] == [PUBLIC, PLATFORM]
    assert values["csrf_trusted_origins"] == [f"https://{PUBLIC}", f"https://{PLATFORM}"]


def test_the_host_is_settled_before_anything_reads_it():
    """SecurityMiddleware's https redirect and CSRF both read the host; the mapping must come first."""
    assert production_settings()["middleware"][0] == "apps.common.middleware.FrontDoorHostMiddleware"


# --- the middleware -------------------------------------------------------------------------------


def through_middleware(host: str, path: str = "/") -> dict:
    seen: dict = {}

    def view(request):
        from apps.social_accounts.oauth_aliases import redirect_uri_from_request
        from apps.social_accounts.views import _build_redirect_uri

        seen["host"] = request.get_host()
        seen["absolute"] = request.build_absolute_uri("/accounts/login/")
        seen["oauth_redirect_uri"] = _build_redirect_uri(request, "facebook")
        seen["callback_redirect_uri"] = redirect_uri_from_request(request)
        return HttpResponse()

    request = RequestFactory().get(path, HTTP_HOST=host, secure=True)
    FrontDoorHostMiddleware(view)(request)
    return seen


front_door = override_settings(
    APP_URL=f"https://{PUBLIC}", PLATFORM_HOSTNAMES=(PLATFORM,), ALLOWED_HOSTS=[PUBLIC, PLATFORM]
)


@front_door
def test_a_request_under_the_platform_hostname_is_answered_as_the_public_host():
    seen = through_middleware(PLATFORM, "/social-accounts/callback/facebook/")
    assert seen["host"] == PUBLIC
    assert seen["absolute"] == f"https://{PUBLIC}/accounts/login/"
    # The redirect URI registered at Meta, LinkedIn, Google and the rest is on the public address.
    assert seen["oauth_redirect_uri"] == f"https://{PUBLIC}/social-accounts/callback/facebook/"
    assert seen["callback_redirect_uri"] == f"https://{PUBLIC}/social-accounts/callback/facebook/"


@front_door
@pytest.mark.parametrize("host", [f"{PLATFORM}:443", PLATFORM.upper()])
def test_the_platform_hostname_matches_whatever_its_case_or_port(host):
    assert through_middleware(host)["host"] == PUBLIC


@front_door
def test_the_public_host_is_left_alone():
    assert through_middleware(PUBLIC)["host"] == PUBLIC


@override_settings(
    APP_URL=f"https://{PUBLIC}", PLATFORM_HOSTNAMES=(PLATFORM,), ALLOWED_HOSTS=[PUBLIC, PLATFORM, "other.example.com"]
)
def test_another_allowed_host_is_left_alone():
    assert through_middleware("other.example.com")["host"] == "other.example.com"


@front_door
def test_a_client_cannot_steer_the_host():
    """Only the platform's own name is mapped, and only ever to APP_URL's host."""
    request = RequestFactory().get("/", HTTP_HOST="evil.example.com", secure=True)

    def view(request):
        with pytest.raises(DisallowedHost):
            request.get_host()
        return HttpResponse()

    FrontDoorHostMiddleware(view)(request)
    assert request.META["HTTP_HOST"] == "evil.example.com"


@override_settings(APP_URL=f"https://{PUBLIC}", PLATFORM_HOSTNAMES=(), ALLOWED_HOSTS=[PUBLIC, PLATFORM])
def test_off_the_platform_nothing_is_mapped():
    assert through_middleware(PLATFORM)["host"] == PLATFORM


@override_settings(APP_URL="", PLATFORM_HOSTNAMES=(PLATFORM,), ALLOWED_HOSTS=[PLATFORM])
def test_without_a_public_address_nothing_is_mapped():
    assert through_middleware(PLATFORM)["host"] == PLATFORM


# --- the whole stack ------------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    APP_URL=f"https://{PUBLIC}",
    PLATFORM_HOSTNAMES=(PLATFORM,),
    ALLOWED_HOSTS=[PUBLIC, PLATFORM],
    CSRF_TRUSTED_ORIGINS=[f"https://{PUBLIC}", f"https://{PLATFORM}"],
)
def test_absolute_urls_behind_the_front_door_name_the_public_address():
    response = Client(HTTP_HOST=PLATFORM).get("/robots.txt", secure=True)
    assert response.status_code == 200
    assert f"Sitemap: https://{PUBLIC}/sitemap.xml" in response.content.decode()


@pytest.mark.django_db
@override_settings(
    APP_URL=f"https://{PUBLIC}",
    PLATFORM_HOSTNAMES=(PLATFORM,),
    ALLOWED_HOSTS=[PUBLIC, PLATFORM],
    CSRF_TRUSTED_ORIGINS=[f"https://{PUBLIC}", f"https://{PLATFORM}"],
)
@pytest.mark.parametrize(("origin", "passes"), [(f"https://{PUBLIC}", True), ("https://evil.example.com", False)])
def test_a_form_posted_through_the_front_door_passes_csrf_and_a_foreign_one_does_not(origin, passes):
    client = Client(enforce_csrf_checks=True, HTTP_HOST=PLATFORM)
    client.get("/accounts/login/", secure=True)
    token = client.cookies["csrftoken"].value
    response = client.post(
        "/accounts/login/",
        {"login": "nobody@example.com", "password": "not-the-password", "csrfmiddlewaretoken": token},
        secure=True,
        HTTP_ORIGIN=origin,
    )
    assert (response.status_code != 403) is passes


@pytest.mark.django_db
@override_settings(APP_URL=f"https://{PUBLIC}", PLATFORM_HOSTNAMES=(PLATFORM,), ALLOWED_HOSTS=[PUBLIC, PLATFORM])
def test_the_platforms_health_check_is_answered():
    """Render calls /health/ with its own hostname as Host and expects a 2xx or 3xx within five seconds."""
    response = Client(HTTP_HOST=PLATFORM).get("/health/")
    assert response.status_code == 200
