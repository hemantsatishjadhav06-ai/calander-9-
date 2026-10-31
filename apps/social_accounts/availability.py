"""Which platforms a workspace may connect, under its ``extra_providers`` switch.

The beta keeps five providers out of new connections until a workspace turns
``extra_providers`` on (docs/specs/02-cut-and-merge.md, D6). Hidden is not
deleted: an account already connected keeps publishing and appearing in the
composer, OAuth callbacks stay open, and a workspace that already has an account
on one of these platforms may still use its connect form and button, because
Bluesky, Mastodon and DEV.to reconnect through that form and a client reconnects
through the connection link page.

Both connect screens ask here: ``social_accounts:connect`` with the request's
switches, and ``onboarding:connection_page`` (no workspace in its URL) with the
link's workspace.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from apps.common.features import features_for

if TYPE_CHECKING:
    from apps.workspaces.models import Workspace

#: The platforms the ``extra_providers`` switch keeps out of new connections.
EXTRA_PROVIDERS = frozenset({"bluesky", "mastodon", "devto", "threads", "tiktok"})


def withheld_platforms(workspace: Workspace, features: Mapping[str, bool] | None = None) -> frozenset[str]:
    """The platforms *workspace* may not connect now.

    Empty when ``extra_providers`` is on. Off, the extra providers less any the
    workspace already has an account on (in any state), so it can reconnect them.
    Pass *features* when the caller has them (``request_features``) to skip a read.
    """
    if features is None:
        features = features_for(workspace)
    if features["extra_providers"]:
        return frozenset()
    from .models import SocialAccount

    existing = set(
        SocialAccount.objects.for_workspace(workspace.id)
        .filter(platform__in=EXTRA_PROVIDERS)
        .values_list("platform", flat=True)
    )
    return EXTRA_PROVIDERS - existing


def unavailable_message(platform: str) -> str:
    """The plain sentence a refused new connection shows."""
    from apps.credentials.models import PlatformCredential

    label = dict(PlatformCredential.Platform.choices).get(platform, platform)
    return f"{label} is not available for new connections in this workspace."
