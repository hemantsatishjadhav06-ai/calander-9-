"""Steps for the layout self-checks (``tests/e2e/self/phone-bar-overlap.spec.ts``).

Fixture (workspace A):

- ``blog_site``: an enabled website for the blog, so the blog's post form renders (without one,
  ``blog:create`` shows "add a website first"). Created once and reused. The blog switch keeps the
  value it had before: its default reads whether an enabled website exists, so the fixture writes
  that earlier value down when the switch was unset, and the navigation other specs see is
  unchanged. Answers ``{"site_id"}``.
"""

from __future__ import annotations

from typing import Any

from .. import seed
from ..registry import fixture


@fixture("blog_site")
def blog_site(payload: dict[str, Any]) -> dict[str, Any]:
    from apps.blog.models import BlogSite
    from apps.common.features import feature_enabled
    from apps.studio.models import AgencySettings
    from apps.workspaces.models import Workspace

    workspace = Workspace.objects.get(pk=seed.WORKSPACE_A_ID)
    blog_was = feature_enabled(workspace, "blog")
    site, _created = BlogSite.objects.get_or_create(
        workspace=workspace,
        repo="e2e-agency/neopolis-site",
        defaults={
            "name": "Neopolis website",
            "kind": BlogSite.Kind.NEOPOLIS_STATIC,
            "site_url": "https://neopolis.example.com",
            "workflow_file": "publish.yml",
            "is_enabled": True,
        },
    )
    if not site.is_enabled:
        site.is_enabled = True
        site.save(update_fields=["is_enabled", "updated_at"])
    agency, _created = AgencySettings.objects.get_or_create(workspace=workspace)
    features = dict(agency.features) if isinstance(agency.features, dict) else {}
    if not isinstance(features.get("blog"), bool):
        features["blog"] = blog_was
        agency.features = features
        agency.save(update_fields=["features"])
    return {"site_id": str(site.pk)}
