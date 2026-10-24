"""Per-workspace feature switches.

The beta hides some features until a workspace needs them (docs/specs/00-cut.md),
and each comes back with one switch in ``AgencySettings.features``, a JSON
object like ``{"queues": true}``. A key left out, or set to anything but a
boolean, takes its default. Everything asks ``feature_enabled`` rather than
reading the field, so a misspelt key fails loudly instead of hiding a feature.

The models are imported inside the functions: ``apps.studio.models`` imports
``apps.common`` at module level.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.workspaces.models import Workspace

FEATURE_KEYS = ("blog", "queues", "templates", "extra_providers", "advanced_settings")


def _blog_default(workspace: Workspace) -> bool:
    """On where the workspace already publishes to an enabled blog website."""
    from apps.blog.models import BlogSite

    return BlogSite.objects.filter(workspace=workspace, is_enabled=True).exists()


# A key missing here starts off.
_DEFAULTS: dict[str, Callable[[Workspace], bool]] = {"blog": _blog_default}


def feature_enabled(workspace: Workspace, key: str) -> bool:
    """Whether *key* is on for *workspace*: its switch when set, else its default."""
    if key not in FEATURE_KEYS:
        raise ValueError(f"Unknown feature {key!r}; expected one of {', '.join(FEATURE_KEYS)}.")
    from apps.studio.models import AgencySettings

    features = AgencySettings.objects.filter(workspace=workspace).values_list("features", flat=True).first()
    value = features.get(key) if isinstance(features, dict) else None
    if isinstance(value, bool):
        return value
    default = _DEFAULTS.get(key)
    return default(workspace) if default else False
