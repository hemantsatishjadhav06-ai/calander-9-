"""Per-workspace feature switches.

The beta hides some features until a workspace needs them (docs/specs/00-cut.md),
and each comes back with one switch in ``AgencySettings.features``, a JSON
object like ``{"queues": true}``. A key left out, or set to anything but a
boolean, takes its default. Everything asks ``feature_enabled`` (one key) or
``features_for`` (every key) rather than reading the field, so a misspelt key
fails loudly instead of hiding a feature. A request reads them once, through
``request_features``; templates get the same answer as ``features``.

The models are imported inside the functions: ``apps.studio.models`` imports
``apps.common`` at module level.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.workspaces.models import Workspace

FEATURE_KEYS = ("blog", "queues", "templates", "extra_providers", "advanced_settings")


def _blog_default(workspace: Workspace | None) -> bool:
    """On where the workspace already publishes to an enabled blog website."""
    if workspace is None:
        return False
    from apps.blog.models import BlogSite

    return BlogSite.objects.filter(workspace=workspace, is_enabled=True).exists()


# A key missing here starts off.
_DEFAULTS: dict[str, Callable[[Workspace | None], bool]] = {"blog": _blog_default}


def _stored(workspace: Workspace | None) -> Mapping[str, Any]:
    """The workspace's switches as stored: one query, and none without a workspace.

    No settings row, or a value that is not an object, reads as no switches set.
    Nothing is created.
    """
    if workspace is None:
        return {}
    from apps.studio.models import AgencySettings

    features = AgencySettings.objects.filter(workspace=workspace).values_list("features", flat=True).first()
    return features if isinstance(features, dict) else {}


def _resolve(stored: Mapping[str, Any], workspace: Workspace | None, key: str) -> bool:
    """*key*'s switch when it is a boolean, else its default."""
    value = stored.get(key)
    if isinstance(value, bool):
        return value
    default = _DEFAULTS.get(key)
    return default(workspace) if default else False


def feature_enabled(workspace: Workspace | None, key: str) -> bool:
    """Whether *key* is on for *workspace*: its switch when set, else its default."""
    if key not in FEATURE_KEYS:
        raise ValueError(f"Unknown feature {key!r}; expected one of {', '.join(FEATURE_KEYS)}.")
    return _resolve(_stored(workspace), workspace, key)


def features_for(workspace: Workspace | None) -> dict[str, bool]:
    """Every key in ``FEATURE_KEYS`` for *workspace*, under ``feature_enabled``'s rules.

    One query for the switches, plus one for the blog default only when the blog
    switch is not set. Without a workspace: every default, and no query.
    """
    stored = _stored(workspace)
    return {key: _resolve(stored, workspace, key) for key in FEATURE_KEYS}


def request_features(request) -> dict[str, bool]:
    """``features_for(request.workspace)``, read once per request.

    The answer is kept on the request with the workspace it was read for, so a
    request that moves to another workspace reads that one. Treat it as read-only.
    """
    workspace = getattr(request, "workspace", None)
    workspace_id = workspace.pk if workspace is not None else None
    cached = getattr(request, "_features", None)
    if cached is not None and cached[0] == workspace_id:
        return cached[1]
    features = features_for(workspace)
    request._features = (workspace_id, features)
    return features
