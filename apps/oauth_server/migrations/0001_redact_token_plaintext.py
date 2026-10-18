"""Redact reusable OAuth credentials while retaining their indexed lookups.

DOT's access/refresh checksum migrations are prerequisites. No identities,
relationships, expiry, scope or revocation state are changed. Old and new
DOT 3.4.1 processes can still resolve the client-held tokens by checksum.
Rollback cannot restore plaintext, and does not need to for authentication.
"""

import hashlib
import hmac
import re

from django.db import migrations
from oauth2_provider.settings import oauth2_settings

_CHECKSUM = re.compile(r"[0-9a-f]{64}")


def redact_token_plaintext(apps, schema_editor):
    database = schema_editor.connection.alias
    models = [apps.get_model("oauth2_provider", name) for name in ("AccessToken", "RefreshToken")]
    if (
        not oauth2_settings.COMPLIANT_BCP_RFC9700_TOKEN_STORAGE
        or oauth2_settings.REFRESH_TOKEN_GRACE_PERIOD_SECONDS != 0
    ):
        raise RuntimeError("OAuth token redaction requires checksum-only storage and a zero refresh grace period.")
    if any(model._meta.swapped for model in models):
        raise RuntimeError("OAuth token redaction requires the standard DOT token models.")
    if schema_editor.connection.vendor == "postgresql":
        # Stop issuer/revocation writes during verification and redaction;
        # existing bearer lookups remain readable. Release the lock at commit.
        tables = ", ".join(schema_editor.connection.ops.quote_name(model._meta.db_table) for model in models)
        schema_editor.execute(f"LOCK TABLE {tables} IN SHARE ROW EXCLUSIVE MODE")
    # Verify both tables before clearing anything, even on a backend whose DDL
    # cannot be rolled back. A missing/incorrect lookup must not become a lost
    # credential after its sole remaining plaintext is erased.
    for model in models:
        for row in model.objects.using(database).only("pk", "token", "token_checksum").iterator(chunk_size=1000):
            checksum = row.token_checksum
            if not isinstance(checksum, str) or not _CHECKSUM.fullmatch(checksum):
                raise RuntimeError("OAuth token redaction refused an invalid lookup checksum. No credentials were erased.")
            if row.token and not hmac.compare_digest(checksum, hashlib.sha256(row.token.encode("utf-8")).hexdigest()):
                raise RuntimeError("OAuth token redaction refused an inconsistent lookup checksum. No credentials were erased.")
    # A queryset update avoids TokenChecksumField.pre_save: hashing the blank
    # column would invalidate every existing bearer. Preserve all other fields.
    for model in models:
        model.objects.using(database).exclude(token="").update(token="")


class Migration(migrations.Migration):
    dependencies = [
        # 0015 depends on 0012 (access checksum) and removes the refresh token
        # plaintext uniqueness constraint, so multiple redacted rows are valid.
        ("oauth2_provider", "0015_refreshtoken_token_checksum"),
    ]

    operations = [migrations.RunPython(redact_token_plaintext, migrations.RunPython.noop)]
