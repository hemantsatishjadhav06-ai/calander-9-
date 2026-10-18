"""Broken production configuration must fail before a service takes traffic."""

import pytest
from django.core.checks import Error
from django.test import override_settings

from apps.common.checks import check_production_config


@pytest.fixture(autouse=True)
def production_config():
    with override_settings(
        DEBUG=False,
        APP_URL="https://app.example.com",
        ALLOWED_HOSTS=["app.example.com"],
        ENCRYPTION_KEY_SALT=b"deployment-specific-salt",
        STORAGE_BACKEND="s3",
        AWS_STORAGE_BUCKET_NAME="media-bucket",
        DATABASES={"default": {"ENGINE": "django.db.backends.postgresql"}},
        CACHES={"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": "redis://cache/0"}},
        EMAIL_BACKEND_TYPE="smtp",
        EMAIL_HOST="smtp.example.com",
        SENTRY_DSN="configured",
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
        BB_TRUSTED_PROXIES=("10.0.0.10",),
        WEBHOOK_SECRET="configured",
        SUPPORT_EMAIL="support@example.com",
        ACCOUNT_EMAIL_VERIFICATION="mandatory",
        ADMIN_ALLOWED_IPS=["10.0.0.0/8"],
    ):
        yield


def ids():
    return {check.id for check in check_production_config(None)}


def test_complete_production_config_passes():
    assert check_production_config(None) == []


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://app.example.com",
        "https://localhost",
        "https://127.0.0.1",
        "https://[::1]",
        "https://app.example.com:invalid",
        "https://app.example.com/path",
        "https://app.example.com?redirect=evil",
        "https://app.example.com#fragment",
        "https://username:password@app.example.com",
    ],
)
def test_public_origin_is_required(url):
    with override_settings(APP_URL=url):
        checks = check_production_config(None)
    assert any(check.id == "smbean.E001" and isinstance(check, Error) for check in checks)
    # A rejected URL may contain credentials; it must never be echoed in logs.
    assert all(url not in str(check) for check in checks) if url else True


@pytest.mark.parametrize("url", ["https://app.example.com", "https://app.example.com/", "https://app.example.com:8443"])
def test_valid_public_origins(url):
    with override_settings(APP_URL=url):
        assert "smbean.E001" not in ids()


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"ENCRYPTION_KEY_SALT": None}, "smbean.E002"),
        ({"STORAGE_BACKEND": "typo"}, "smbean.E003"),
        ({"AWS_STORAGE_BUCKET_NAME": ""}, "smbean.E004"),
        ({"EMAIL_BACKEND_TYPE": "typo"}, "smbean.E005"),
        ({"ALLOWED_HOSTS": ["*"]}, "smbean.E006"),
        ({"ALLOWED_HOSTS": []}, "smbean.E006"),
        ({"ALLOWED_HOSTS": ["another.example.com"]}, "smbean.E010"),
        ({"DATABASES": {"default": {"ENGINE": "django.db.backends.sqlite3"}}}, "smbean.E007"),
        ({"CACHES": {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}}, "smbean.E008"),
        ({"CACHES": {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}}, "smbean.E008"),
        ({"BB_TRUSTED_PROXIES": ("not-an-ip",)}, "smbean.E009"),
    ],
)
def test_required_production_config_fails_closed(overrides, expected):
    with override_settings(**overrides):
        assert expected in ids()


def test_local_media_warns_until_a_durable_volume_is_configured():
    with override_settings(STORAGE_BACKEND="local", MEDIA_STORAGE_PERSISTENT=False):
        assert "smbean.W003" in ids()
    with override_settings(STORAGE_BACKEND="local", MEDIA_STORAGE_PERSISTENT=True):
        assert check_production_config(None) == []


def test_optional_operations_are_warnings():
    with override_settings(
        EMAIL_BACKEND_TYPE="console",
        SENTRY_DSN="",
        BB_TRUSTED_PROXIES=(),
        WEBHOOK_SECRET="",
        SUPPORT_EMAIL="",
        ACCOUNT_EMAIL_VERIFICATION="none",
        ADMIN_ALLOWED_IPS=[],
    ):
        checks = check_production_config(None)
    assert checks
    assert not any(isinstance(check, Error) for check in checks)


def test_development_does_not_require_production_services():
    with override_settings(DEBUG=True, APP_URL="http://localhost", ENCRYPTION_KEY_SALT=None):
        assert check_production_config(None) == []
