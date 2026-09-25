"""Health-check readiness tests: 200 only when DB + cache both answer."""

import json
from unittest import mock

import pytest
from django.test import RequestFactory

from apps.accounts.views import health_check


@pytest.mark.django_db
def test_health_ok_when_dependencies_up():
    resp = health_check(RequestFactory().get("/health/"))
    assert resp.status_code == 200
    data = json.loads(resp.content)
    assert data["status"] == "ok"
    assert data["checks"] == {"database": "ok", "cache": "ok"}


@pytest.mark.django_db
def test_health_503_when_cache_down():
    with mock.patch("apps.accounts.views.cache.set", side_effect=RuntimeError("redis down")):
        resp = health_check(RequestFactory().get("/health/"))
    assert resp.status_code == 503
    data = json.loads(resp.content)
    assert data["status"] == "degraded"
    assert data["checks"]["cache"] == "error"


def test_health_503_when_db_down():
    # No django_db marker → touching the cursor raises, exercising the DB branch.
    with mock.patch("apps.accounts.views.connection.cursor", side_effect=RuntimeError("db down")):
        resp = health_check(RequestFactory().get("/health/"))
    assert resp.status_code == 503
    assert json.loads(resp.content)["checks"]["database"] == "error"
