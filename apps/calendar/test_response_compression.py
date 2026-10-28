"""Calendar HTML compression must preserve the exact page and its security headers."""

import gzip
import re
from unittest.mock import patch

import pytest
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.shortcuts import render
from django.test import RequestFactory, override_settings
from django.urls import reverse

from apps.members.models import WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


@pytest.fixture
def calendar_page(client, org_owner, organization):
    workspace = Workspace.objects.create(organization=organization, name="Private calendar transport")
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    client.force_login(org_owner)
    return client, reverse("calendar:calendar", kwargs={"workspace_id": workspace.pk})


@pytest.mark.django_db
@override_settings(CSP_REPORT_ONLY=False)
@pytest.mark.parametrize("mode", ["mode=calendar&view=month", "mode=list&tab=approvals"])
def test_calendar_compresses_exact_rendered_page_with_nonce_csrf_and_cookie_vary(calendar_page, mode):
    client, url = calendar_page
    rendered = []

    def capture_render(*args, **kwargs):
        response = render(*args, **kwargs)
        rendered.append(response.content)
        return response

    with patch("apps.calendar.views.render", side_effect=capture_render):
        response = client.get(f"{url}?{mode}", HTTP_ACCEPT_ENCODING="gzip, deflate, br")

    assert response.status_code == 200
    assert response["Content-Encoding"] == "gzip"
    html_bytes = gzip.decompress(response.content)
    assert rendered == [html_bytes]
    assert len(response.content) < len(html_bytes) / 2
    assert response["Content-Length"] == str(len(response.content))
    assert {"cookie", "accept-encoding"} <= {v.strip().lower() for v in response["Vary"].split(",")}
    # Django's default randomized filename padding is retained, without a flaky
    # assertion about two random lengths being different.
    assert response.content[3] & 8
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["X-Frame-Options"] == "DENY"

    html = html_bytes.decode()
    policy = response["Content-Security-Policy"]
    nonce_match = re.search(r"'nonce-([^']+)'", policy)
    assert nonce_match
    nonce = nonce_match.group(1)
    assert f'nonce="{nonce}"' in html
    scripts = next(d for d in policy.split(";") if d.strip().startswith("script-src "))
    assert "'unsafe-inline'" not in scripts
    csrf_match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
    assert csrf_match
    csrf = csrf_match.group(1)

    def check_token(token):
        # Exercise the public request-processing contract, using the token from
        # the decoded page and its real response cookie. The probe never calls
        # an application action or changes any rows.
        request = RequestFactory().post(
            "/csrf-probe/",
            {"csrfmiddlewaretoken": token},
            HTTP_COOKIE=f"csrftoken={client.cookies['csrftoken'].value}",
        )
        middleware = CsrfViewMiddleware(lambda request: HttpResponse())
        middleware.process_request(request)
        return middleware.process_view(request, lambda request: HttpResponse(), (), {})

    assert check_token(csrf) is None
    rejected = check_token("invalid")
    assert rejected is not None
    assert rejected.status_code == 403


@pytest.mark.django_db
def test_calendar_keeps_plain_html_when_browser_does_not_accept_gzip(calendar_page):
    client, url = calendar_page
    response = client.get(f"{url}?mode=calendar&view=month", HTTP_ACCEPT_ENCODING="identity")

    assert response.status_code == 200
    assert "Content-Encoding" not in response
    assert b'data-testid="calendar-shell"' in response.content
    assert {"cookie", "accept-encoding"} <= {v.strip().lower() for v in response["Vary"].split(",")}


@pytest.mark.django_db
def test_calendar_compresses_htmx_fragment_without_turning_it_into_a_full_page(calendar_page):
    client, url = calendar_page
    response = client.get(f"{url}?mode=calendar&view=week", HTTP_ACCEPT_ENCODING="gzip", HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert response["Content-Encoding"] == "gzip"
    html = gzip.decompress(response.content)
    assert b'data-testid="calendar-week-grid"' in html
    assert b"<!DOCTYPE html>" not in html


@pytest.mark.django_db
def test_calendar_compression_does_not_bypass_sign_in_or_workspace_access(calendar_page):
    client, url = calendar_page
    other = Workspace.objects.create(
        organization=Organization.objects.create(name="Other compression organisation"), name="Foreign private calendar"
    )
    forbidden = client.get(reverse("calendar:calendar", kwargs={"workspace_id": other.pk}), HTTP_ACCEPT_ENCODING="gzip")
    assert forbidden.status_code == 403
    forbidden_body = (
        gzip.decompress(forbidden.content) if forbidden.get("Content-Encoding") == "gzip" else forbidden.content
    )
    assert b"Foreign private calendar" not in forbidden_body

    client.logout()
    anonymous = client.get(url, HTTP_ACCEPT_ENCODING="gzip")
    assert anonymous.status_code == 302
    assert anonymous.url.startswith("/accounts/login/?next=")
    anonymous_body = (
        gzip.decompress(anonymous.content) if anonymous.get("Content-Encoding") == "gzip" else anonymous.content
    )
    assert b"Private calendar transport" not in anonymous_body
