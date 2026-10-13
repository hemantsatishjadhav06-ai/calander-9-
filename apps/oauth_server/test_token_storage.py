"""Legacy OAuth clients retain their credentials after plaintext redaction."""

import base64
import hashlib
import json
import secrets
import uuid
from datetime import timedelta

import pytest
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, override_settings
from django.utils import timezone
from oauth2_provider.models import AccessToken, Application, Grant, RefreshToken, set_token_value

from apps.accounts.models import User

MIGRATION = ("oauth_server", "0001_redact_token_plaintext")
REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def checksum(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@pytest.fixture
def legacy_tokens(transactional_db):
    cache.delete("agent_api:auth_fail:127.0.0.1")
    MigrationExecutor(connection).migrate([("oauth_server", None)])
    user = User.objects.create_user(email="legacy-oauth@example.test", tos_accepted_at=timezone.now())
    app = Application.objects.create(
        name="Existing MCP client",
        client_type=Application.CLIENT_PUBLIC,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris=REDIRECT,
    )
    raw_access, raw_refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    access = AccessToken.objects.create(
        user=user,
        application=app,
        token=raw_access,
        scope="mcp",
        expires=timezone.now() + timedelta(hours=1),
    )
    refresh = RefreshToken.objects.create(
        user=user,
        application=app,
        token=raw_refresh,
        access_token=access,
        token_family=uuid.uuid4(),
    )
    yield user, app, access, refresh, raw_access, raw_refresh
    # Failed validation tests intentionally leave a corrupt checksum. Remove
    # only this test database's synthetic credentials before restoring its
    # migration state so later tests never inherit an incomplete schema state.
    AccessToken.objects.all().delete()
    RefreshToken.objects.all().delete()
    MigrationExecutor(connection).migrate([MIGRATION])
    cache.delete("agent_api:auth_fail:127.0.0.1")


def migrate():
    MigrationExecutor(connection).migrate([MIGRATION])


def ping(raw_token):
    response = Client().post(
        "/api/v1/mcp/",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
        content_type="application/json",
        secure=True,
        HTTP_AUTHORIZATION=f"Bearer {raw_token}",
    )
    return response.status_code


def rotate(app, raw_refresh):
    return Client().post(
        "/oauth/token/",
        {
            "grant_type": "refresh_token",
            "client_id": app.client_id,
            "refresh_token": raw_refresh,
        },
        secure=True,
    )


def metadata(model):
    fields = [field.attname for field in model._meta.concrete_fields if field.name != "token"]
    return list(model.objects.order_by("pk").values(*fields))


def test_migration_preserves_all_metadata_and_is_idempotent(legacy_tokens):
    user, app, access, refresh, raw_access, raw_refresh = legacy_tokens
    AccessToken.objects.create(
        user=user,
        application=app,
        token=secrets.token_urlsafe(32),
        scope="mcp",
        expires=timezone.now() - timedelta(days=1),
        source_refresh_token=refresh,
    )
    RefreshToken.objects.create(
        user=user,
        application=app,
        token=secrets.token_urlsafe(32),
        token_family=uuid.uuid4(),
        revoked=timezone.now() - timedelta(days=1),
    )
    already_redacted = AccessToken(user=user, application=app, scope="mcp", expires=timezone.now() + timedelta(hours=1))
    set_token_value(already_redacted, secrets.token_urlsafe(32))
    already_redacted.save()
    before_access, before_refresh = metadata(AccessToken), metadata(RefreshToken)
    migrate()
    assert not AccessToken.objects.exclude(token="").exists()
    assert not RefreshToken.objects.exclude(token="").exists()
    assert metadata(AccessToken) == before_access
    assert metadata(RefreshToken) == before_refresh
    assert AccessToken.objects.get(pk=access.pk).token_checksum == checksum(raw_access)
    assert RefreshToken.objects.get(pk=refresh.pk).token_checksum == checksum(raw_refresh)
    MigrationExecutor(connection).migrate([("oauth_server", None)])
    migrate()
    assert metadata(AccessToken) == before_access and metadata(RefreshToken) == before_refresh


@pytest.mark.parametrize("model_name", ["access", "refresh"])
@pytest.mark.parametrize("bad_checksum", ["", "not-a-checksum", "0" * 64])
def test_inconsistent_checksum_refuses_migration_before_erasing_any_tokens(legacy_tokens, model_name, bad_checksum):
    _, _, access, refresh, raw_access, raw_refresh = legacy_tokens
    model, row = (AccessToken, access) if model_name == "access" else (RefreshToken, refresh)
    model.objects.filter(pk=row.pk).update(token_checksum=bad_checksum)
    with pytest.raises(RuntimeError, match="lookup checksum"):
        migrate()
    assert AccessToken.objects.get(pk=access.pk).token == raw_access
    assert RefreshToken.objects.get(pk=refresh.pk).token == raw_refresh


@pytest.mark.parametrize("model_name", ["access", "refresh"])
def test_already_blank_token_with_invalid_checksum_refuses_migration(legacy_tokens, model_name):
    _, _, access, refresh, raw_access, raw_refresh = legacy_tokens
    model, row = (AccessToken, access) if model_name == "access" else (RefreshToken, refresh)
    model.objects.filter(pk=row.pk).update(token="", token_checksum="")
    with pytest.raises(RuntimeError, match="lookup checksum"):
        migrate()
    other_model, other, raw = (
        (RefreshToken, refresh, raw_refresh) if model_name == "access" else (AccessToken, access, raw_access)
    )
    assert other_model.objects.get(pk=other.pk).token == raw


@pytest.mark.parametrize(
    "overrides",
    [
        {"COMPLIANT_BCP_RFC9700_TOKEN_STORAGE": False},
        {"REFRESH_TOKEN_GRACE_PERIOD_SECONDS": 10},
    ],
)
def test_incompatible_storage_configuration_refuses_redaction(legacy_tokens, overrides):
    _, _, access, refresh, raw_access, raw_refresh = legacy_tokens
    with (
        override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, **overrides}),
        pytest.raises(RuntimeError, match="checksum-only storage"),
    ):
        migrate()
    assert AccessToken.objects.get(pk=access.pk).token == raw_access
    assert RefreshToken.objects.get(pk=refresh.pk).token == raw_refresh


def test_existing_client_bearer_refresh_rotation_and_replay_work_after_redaction(legacy_tokens):
    _, app, _, refresh, raw_access, raw_refresh = legacy_tokens
    assert ping(raw_access) == 200
    family = refresh.token_family
    migrate()
    assert ping(raw_access) == 200
    response = rotate(app, raw_refresh)
    assert response.status_code == 200
    data = response.json()
    new_access, new_refresh = data["access_token"], data["refresh_token"]
    assert new_access and new_refresh and new_refresh != raw_refresh
    assert ping(new_access) == 200
    current = RefreshToken.objects.get(token_checksum=checksum(new_refresh), revoked__isnull=True)
    assert current.token == "" and current.access_token.token == "" and current.token_family == family
    old = RefreshToken.objects.get(pk=refresh.pk)
    assert old.token == "" and old.token_checksum == checksum(raw_refresh) and old.revoked is not None
    replay = rotate(app, raw_refresh)
    assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
    assert ping(new_access) == 401
    assert not RefreshToken.objects.filter(token_family=family, revoked__isnull=True).exists()


def test_legacy_token_revocation_uses_checksum_without_revealing_or_reissuing_token(legacy_tokens):
    _, app, _, refresh, raw_access, raw_refresh = legacy_tokens
    migrate()
    response = Client().post(
        "/oauth/revoke_token/",
        {
            "client_id": app.client_id,
            "token": raw_access,
            "token_type_hint": "access_token",
        },
        secure=True,
    )
    assert response.status_code == 200
    assert ping(raw_access) == 401
    refresh.refresh_from_db()
    assert refresh.revoked is not None and refresh.token == "" and refresh.token_checksum == checksum(raw_refresh)
    assert rotate(app, raw_refresh).status_code == 400


def test_other_client_cannot_revoke_redacted_legacy_bearer(legacy_tokens):
    _, _, _, _, raw_access, _ = legacy_tokens
    other = Application.objects.create(
        name="Different MCP client",
        client_type=Application.CLIENT_PUBLIC,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris=REDIRECT,
    )
    migrate()
    response = Client().post(
        "/oauth/revoke_token/",
        {
            "client_id": other.client_id,
            "token": raw_access,
            "token_type_hint": "access_token",
        },
        secure=True,
    )
    assert response.status_code == 200 and ping(raw_access) == 200


def test_new_authorization_code_tokens_are_redacted_but_returned_to_the_client(legacy_tokens):
    user, app, _, _, _, _ = legacy_tokens
    migrate()
    verifier, code = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    Grant.objects.create(
        user=user,
        application=app,
        code=code,
        scope="mcp",
        expires=timezone.now() + timedelta(minutes=5),
        redirect_uri=REDIRECT,
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    response = Client().post(
        "/oauth/token/",
        {
            "grant_type": "authorization_code",
            "client_id": app.client_id,
            "code": code,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
        },
        secure=True,
    )
    assert response.status_code == 200
    data = response.json()
    access = AccessToken.objects.get(token_checksum=checksum(data["access_token"]))
    refresh = RefreshToken.objects.get(token_checksum=checksum(data["refresh_token"]), revoked__isnull=True)
    assert access.token == refresh.token == ""
    assert ping(data["access_token"]) == 200
