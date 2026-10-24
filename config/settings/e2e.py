"""Settings for the end-to-end server only (``python -m tests.e2e.server``); never deployed.

Built on ``base``, not ``development``: DEBUG off, the CSP enforced, rate limits on, so the browser
meets what production sends. Its own database (``DB_NAME``, default ``brightbean_e2e``), local-memory
cache and mail, and local storage under the gitignored ``e2e_media/``.

Every credential is a placeholder. The server process answers every model turn with fakes, answers
the few platform calls the browser paths make with a mock transport, and refuses every other
connection (see ``tests/e2e/server``). No ``.env`` or ``dev.env`` is needed: what ``base`` reads from
the environment is pinned below before it is read (``base`` loads ``.env`` without overwriting), and
the credential settings are blanked again afterwards.
"""

import os

os.environ.setdefault("SECRET_KEY", "e2e-secret-key-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY_SALT", "e2e-salt-not-for-production")

E2E_PORT = int(os.environ.get("E2E_PORT", "8150"))
E2E_BASE_URL = (os.environ.get("E2E_BASE_URL") or f"http://127.0.0.1:{E2E_PORT}").rstrip("/")
_PLACEHOLDER = "e2e-placeholder-not-a-credential"

# The Facebook app secret signs inbox webhooks; the browser paths sign their test webhook with it.
E2E_FACEBOOK_APP_SECRET = "e2e-facebook-app-secret"

os.environ.update(
    {
        "DEBUG": "false",
        "APP_URL": E2E_BASE_URL,
        "MCP_PUBLIC_BASE_URL": E2E_BASE_URL,
        "MCP_OAUTH_ISSUER_URL": E2E_BASE_URL,
        "ALLOWED_HOSTS": "127.0.0.1,localhost",
        "CSRF_TRUSTED_ORIGINS": "",
        "BB_TRUSTED_PROXIES": "",
        "REDIS_URL": "",
        "SENTRY_DSN": "",
        "STORAGE_BACKEND": "local",
        "EMAIL_BACKEND_TYPE": "console",
        "ACCOUNT_EMAIL_VERIFICATION": "none",
        "SIGNUP_MODE": "open",
        "SIGNUP_ALLOWLIST": "",
        # The adapter's default provider with a placeholder key: readiness reads green, and the server
        # replaces every model turn with a fake before it can be sent.
        "STUDIO_PROVIDER": "",
        "STUDIO_MODEL": "",
        "ANTHROPIC_API_KEY": _PLACEHOLDER,
        "OPENROUTER_API_KEY": "",
        "FAL_KEY": "",
        # Google sign-in shows its button; the server answers the exchange by the authorization code.
        "GOOGLE_AUTH_CLIENT_ID": "e2e-google-client-id",
        "GOOGLE_AUTH_CLIENT_SECRET": _PLACEHOLDER,
        # X can be connected (the mock answers the token and the profile); Meta signs webhooks.
        "PLATFORM_X_CLIENT_ID": "e2e-x-client-id",
        "PLATFORM_X_CLIENT_SECRET": _PLACEHOLDER,
        "PLATFORM_FACEBOOK_APP_ID": "e2e-facebook-app-id",
        "PLATFORM_FACEBOOK_APP_SECRET": E2E_FACEBOOK_APP_SECRET,
        "INTELLIGENCE_INTERNAL_URL": "",
        "INTELLIGENCE_PUBLIC_URL": "",
        "STUDIO_DEPLOYMENT_ID": "",
        "STUDIO_SHARED_SECRET": "",
        "STUDIO_BASE_URL": "",
    }
)

from .base import *  # noqa: E402, F401, F403
from .base import BASE_DIR, PLATFORM_CREDENTIALS_FROM_ENV, env  # noqa: E402

DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]"]
CSRF_TRUSTED_ORIGINS = []
BB_TRUSTED_PROXIES = ()
ADMIN_ALLOWED_IPS = []
CSP_REPORT_ONLY = False
RATELIMIT_ENABLE = True
SIGNUP_MODE = "open"
SIGNUP_ALLOWLIST = []
APP_URL = E2E_BASE_URL
MCP_PUBLIC_BASE_URL = E2E_BASE_URL
MCP_OAUTH_ISSUER_URL = E2E_BASE_URL
INTELLIGENCE_ENABLED = False
SENTRY_DSN = ""

# The harness views are mounted here and nowhere else; the app's own URL conf is included unchanged.
ROOT_URLCONF = "tests.e2e.server.urls"

# The Set up and Home health lines read the worker's heartbeat; the in-process worker beats often.
PUBLISHER_HEARTBEAT_MAX_AGE = 30

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# One process (web and worker share the fakes), so a local-memory cache is shared by everything.
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "e2e"},
    "filmstrip": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "e2e-filmstrip",
        "OPTIONS": {"MAX_ENTRIES": 32, "CULL_FREQUENCY": 2},
    },
}

E2E_ROOT = BASE_DIR / "e2e_media"
STORAGE_BACKEND = "local"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
MEDIA_ROOT = E2E_ROOT / "media"
MEDIA_URL = "/media/"
SERVE_MEDIA = True
STATIC_ROOT = E2E_ROOT / "static"
if os.environ.get("E2E_STATIC", "") == "manifest":
    # What production serves (collectstatic, hashed names, gzip): the transfer sizes Lighthouse reads.
    STORAGES["staticfiles"] = {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}

# Mail stays in memory, through the same budget wrapper production uses, with no caps.
EMAIL_INNER_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
EMAIL_DAILY_SEND_LIMIT = -1
EMAIL_RECIPIENT_HOURLY_LIMIT = -1
EMAIL_RECIPIENT_DAILY_LIMIT = -1

# Credentials a developer's environment might hold never reach this process's settings.
ANTHROPIC_API_KEY = _PLACEHOLDER
OPENROUTER_API_KEY = ""
STUDIO_PROVIDER = ""
STUDIO_MODEL = ""
FAL_KEY = ""
BLOG_GITHUB_TOKEN = ""
GSC_CLIENT_ID = ""
GSC_CLIENT_SECRET = ""
GMAIL_CLIENT_ID = ""
GMAIL_CLIENT_SECRET = ""
GMAIL_REFRESH_TOKEN = ""
UNSPLASH_ACCESS_KEY = ""
INDEXNOW_KEY = ""
TELEGRAM_WEBHOOK_BASE_URL = ""
TELEGRAM_WEBHOOK_READY = False
PLATFORM_CREDENTIALS_FROM_ENV = {
    platform: {key: "" for key in values} for platform, values in PLATFORM_CREDENTIALS_FROM_ENV.items()
}
PLATFORM_CREDENTIALS_FROM_ENV["x"] = {"client_id": "e2e-x-client-id", "client_secret": _PLACEHOLDER}
_E2E_META = {"app_id": "e2e-facebook-app-id", "app_secret": E2E_FACEBOOK_APP_SECRET, "config_id": ""}
PLATFORM_CREDENTIALS_FROM_ENV["facebook"] = _E2E_META
PLATFORM_CREDENTIALS_FROM_ENV["instagram"] = _E2E_META
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "VERIFIED_EMAIL": True,
        "APP": {"client_id": "e2e-google-client-id", "secret": _PLACEHOLDER},
    },
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", default="brightbean_e2e"),
        "USER": env("DB_USER", default="postgres"),
        "PASSWORD": env("DB_PASSWORD", default="postgres"),
        "HOST": env("DB_HOST", default="localhost"),
        "PORT": env.int("DB_PORT", default=5432),
        # runserver serves each request on a new thread: close each connection when its request ends.
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"connect_timeout": 5},
    },
}

# Errors and the harness's own lines go to the console the server was started from.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        # runserver's access log: refusals (4xx) and errors only, so a failing test's lines stand out.
        "django.server": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "tests.e2e": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
