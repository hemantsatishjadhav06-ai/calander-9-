"""Create (or correct) the two brands' BlogSite rows. Safe to run repeatedly.

    python manage.py ensure_blog_sites \\
        --neopolis-workspace <uuid> --morespace-workspace <uuid>

Either flag may be given on its own. Other commands can call
:func:`ensure_blog_sites` directly.
"""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.blog.models import BlogSite
from apps.workspaces.models import Workspace

NEOPOLIS_SITE = {
    "name": "Neopolis Infra website",
    "kind": BlogSite.Kind.NEOPOLIS_STATIC,
    "site_url": "https://www.neopolisinfra.com",
    "repo": "hemantsatishjadhav06-ai/neopolis-site-deploy",
    "branch": "main",
    "workflow_file": "publish3.yml",
    "netlify_site_id": "47e0a5cc-d9d9-428b-a36b-beea806bff6f",
}
MORESPACE_SITE = {
    "name": "More Space website",
    "kind": BlogSite.Kind.MORESPACE_STATIC,
    "site_url": "https://morespace.netlify.app",
    "repo": "hemantsatishjadhav06-ai/morespace-website",
    "branch": "main",
    "workflow_file": "netlify-publish.yml",
    "netlify_site_id": "964e086b-1cf2-47f7-8b78-16909d268319",
}


def _resolve_workspace(value) -> Workspace | None:
    if value in (None, ""):
        return None
    if isinstance(value, Workspace):
        return value
    try:
        return Workspace.objects.get(pk=value)
    except (Workspace.DoesNotExist, ValidationError, ValueError, TypeError) as exc:
        raise ValueError(f"No workspace with id {value!r}.") from exc


def _ensure(workspace: Workspace, spec: dict) -> tuple[BlogSite, str]:
    """Find this workspace's site for ``spec['repo']`` (or of its kind) and make it match ``spec``."""
    site = (
        BlogSite.objects.filter(workspace=workspace, repo=spec["repo"]).first()
        or BlogSite.objects.filter(workspace=workspace, kind=spec["kind"]).order_by("created_at").first()
    )
    if site is None:
        return BlogSite.objects.create(workspace=workspace, is_enabled=True, **spec), "created"
    changed = [name for name, value in spec.items() if getattr(site, name) != value]
    for name in changed:
        setattr(site, name, spec[name])
    if changed:
        site.full_clean()
        site.save(update_fields=[*changed, "updated_at"])
        return site, "updated"
    return site, "unchanged"


def ensure_blog_sites(neopolis_ws=None, morespace_ws=None) -> list[tuple[BlogSite, str]]:
    """Make sure the Neopolis and/or More Space BlogSite rows exist and are correct.

    Accepts Workspace instances or ids. Returns ``[(site, outcome), ...]`` where
    outcome is ``"created"``, ``"updated"`` or ``"unchanged"``.
    ``is_enabled`` is left as it is on existing rows, so a site switched off by
    hand stays off.
    """
    results = []
    with transaction.atomic():
        neopolis = _resolve_workspace(neopolis_ws)
        if neopolis is not None:
            results.append(_ensure(neopolis, NEOPOLIS_SITE))
        morespace = _resolve_workspace(morespace_ws)
        if morespace is not None:
            results.append(_ensure(morespace, MORESPACE_SITE))
    return results


class Command(BaseCommand):
    help = "Create or update the Neopolis and More Space blog sites for the given workspaces (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--neopolis-workspace", help="Workspace id that writes the Neopolis blog.")
        parser.add_argument("--morespace-workspace", help="Workspace id that writes the More Space blog.")

    def handle(self, *args, **options):
        neopolis, morespace = options.get("neopolis_workspace"), options.get("morespace_workspace")
        if not neopolis and not morespace:
            raise CommandError("Give --neopolis-workspace and/or --morespace-workspace.")
        try:
            results = ensure_blog_sites(neopolis, morespace)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        for site, outcome in results:
            self.stdout.write(
                f"{outcome.capitalize()}: {site.name} -> {site.repo} ({site.workflow_file}) in workspace {site.workspace_id}"
            )
