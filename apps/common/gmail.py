"""Send mail through the Gmail API over HTTPS.

Railway's Hobby plan blocks outbound SMTP (ports 25/465/587), so the usual
"Gmail + app password" setup cannot leave the container. The Gmail API is
plain HTTPS: exchange a long-lived refresh token for an access token, then
POST each message as base64url-encoded MIME to ``users/me/messages/send``.

This is an inner backend: ``apps.common.mail.BudgetedEmailBackend`` still
decides whether a message may go at all.
"""

from __future__ import annotations

import base64
import json
import logging

import httpx
from django.conf import settings
from django.core.cache import cache
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SCOPES = "openid email https://www.googleapis.com/auth/gmail.send"
_ACCESS_TOKEN_CACHE_KEY = "gmail_api_access_token"


class GmailNotConnectedError(Exception):
    """No refresh token: nobody has connected the sending mailbox yet."""


def client_credentials() -> tuple[str, str]:
    """The OAuth client used for sending: GMAIL_* if set, else the Google sign-in client."""
    client_id = getattr(settings, "GMAIL_CLIENT_ID", "") or getattr(settings, "GOOGLE_AUTH_CLIENT_ID", "")
    secret = getattr(settings, "GMAIL_CLIENT_SECRET", "") or getattr(settings, "GOOGLE_AUTH_CLIENT_SECRET", "")
    return client_id, secret


def refresh_token() -> str:
    token = getattr(settings, "GMAIL_REFRESH_TOKEN", "")
    if token:
        return token
    from .models import OutboundMailbox

    mailbox = OutboundMailbox.objects.order_by("-connected_at").first()
    if mailbox is None:
        raise GmailNotConnectedError("Connect the sending Gmail account at /ops/email/.")
    return mailbox.refresh_token


def access_token(*, force: bool = False) -> str:
    """A valid access token, cached for most of its hour-long life."""
    if not force:
        cached = cache.get(_ACCESS_TOKEN_CACHE_KEY)
        if cached:
            return cached
    client_id, secret = client_credentials()
    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": secret,
            "refresh_token": refresh_token(),
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Gmail token refresh failed ({response.status_code}): {response.text[:300]}")
    payload = response.json()
    token = payload["access_token"]
    cache.set(_ACCESS_TOKEN_CACHE_KEY, token, max(60, int(payload.get("expires_in", 3600)) - 300))
    return token


def exchange_code(code: str, redirect_uri: str) -> tuple[str, str]:
    """Trade an authorization code for (refresh_token, email)."""
    client_id, secret = client_credentials()
    response = httpx.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Google rejected the authorization code ({response.status_code}): {response.text[:300]}")
    payload = response.json()
    if not payload.get("refresh_token"):
        raise RuntimeError(
            "Google returned no refresh token. Remove the app's access in your Google account and retry."
        )
    # The id_token came straight from Google's token endpoint over TLS, so its
    # claims can be read without re-verifying the signature.
    claims_b64 = payload.get("id_token", "..").split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(claims_b64 + "=" * (-len(claims_b64) % 4)) or b"{}")
    return payload["refresh_token"], claims.get("email", "")


class GmailAPIEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        sent = 0
        try:
            token = access_token()
        except Exception:
            logger.exception("Gmail API: could not obtain an access token")
            if not self.fail_silently:
                raise
            return 0
        with httpx.Client(timeout=30) as client:
            for message in email_messages:
                if not message.recipients():
                    continue
                raw = base64.urlsafe_b64encode(message.message().as_bytes()).decode()
                response = client.post(SEND_URL, headers={"Authorization": f"Bearer {token}"}, json={"raw": raw})
                if response.status_code == 401:
                    token = access_token(force=True)
                    response = client.post(SEND_URL, headers={"Authorization": f"Bearer {token}"}, json={"raw": raw})
                if response.status_code >= 400:
                    logger.error("Gmail API send failed (%s): %s", response.status_code, response.text[:500])
                    if not self.fail_silently:
                        raise RuntimeError(f"Gmail API send failed ({response.status_code})")
                    continue
                sent += 1
        return sent
