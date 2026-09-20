"""Deployment-config system checks.

These surface the "silent" production misconfigurations that made the live
deployment appear healthy while core features were broken — the app boots
green, then publishing/connect/email fail at request time. They are registered
as *deploy* checks, so they only run under ``python manage.py check --deploy``
(and never during normal dev/test ``check`` or ``runserver``), and each is
gated on ``not DEBUG`` so ``--deploy`` in a dev shell stays quiet.

Run before/after shipping:  python manage.py check --deploy
"""

from django.conf import settings
from django.core.checks import Tags, register
from django.core.checks import Warning as CheckWarning


@register(Tags.security, deploy=True)
def check_production_config(app_configs, **kwargs):
    if settings.DEBUG:
        return []

    errors = []
    app_url = (getattr(settings, "APP_URL", "") or "").lower()
    if "localhost" in app_url or "127.0.0.1" in app_url or not app_url:
        errors.append(
            CheckWarning(
                "APP_URL is unset or still points at localhost.",
                hint=(
                    "Absolute URLs (email/invite/portal links, the media URLs handed to "
                    "Instagram/Facebook/Threads/Pinterest/Google, OAuth issuer) are built "
                    "from APP_URL. Set APP_URL to your public https origin."
                ),
                id="smbean.W001",
            )
        )

    if not getattr(settings, "ENCRYPTION_KEY_SALT", None):
        errors.append(
            CheckWarning(
                "ENCRYPTION_KEY_SALT is not set.",
                hint=(
                    "Connecting a social account (token encryption) and minting an API key "
                    "raise ValueError without it — every connect/API-key request will 500. "
                    "Set a random value BEFORE any account is connected and never change it."
                ),
                id="smbean.W002",
            )
        )

    if str(getattr(settings, "STORAGE_BACKEND", "local")).lower() != "s3":
        errors.append(
            CheckWarning(
                "STORAGE_BACKEND is 'local' in production.",
                hint=(
                    "Uploaded media lives on the container's ephemeral disk (lost on every "
                    "redeploy) and localhost media URLs are unfetchable by the social "
                    "platforms. Set STORAGE_BACKEND=s3 with the S3_* variables."
                ),
                id="smbean.W003",
            )
        )

    if getattr(settings, "EMAIL_BACKEND_TYPE", "") == "smtp" and getattr(settings, "EMAIL_HOST", "") in (
        "",
        "localhost",
        "127.0.0.1",
    ):
        errors.append(
            CheckWarning(
                "EMAIL_HOST is localhost while EMAIL_BACKEND_TYPE=smtp.",
                hint=(
                    "Team invites, client-portal magic links, password resets and "
                    "notification emails will silently fail. Configure a transactional "
                    "email provider (EMAIL_HOST/PORT/USER/PASSWORD, DEFAULT_FROM_EMAIL)."
                ),
                id="smbean.W004",
            )
        )

    if not getattr(settings, "SENTRY_DSN", ""):
        errors.append(
            CheckWarning(
                "SENTRY_DSN is not set: no error monitoring in production.",
                hint="Set SENTRY_DSN to capture runtime errors.",
                id="smbean.W005",
            )
        )

    return errors
