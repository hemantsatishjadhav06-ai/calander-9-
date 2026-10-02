"""Create or reuse one workspace per brand, ready for live use. Idempotent.

For each brand in :data:`apps.workspaces.brands.BRANDS`:

* reuse a workspace in the approver's organization whose name matches the
  brand (case-insensitive), or create one;
* set the editorial timezone to Asia/Kolkata, require internal approval, and
  require dashboard approval (``Workspace.require_dashboard_approval``) so
  nothing in the workspace publishes without the approver signing off on the
  exact revision;
* make the approver an owner of the workspace (owners hold ``approve_posts``);
* record the brand's expected Facebook Page, Instagram and X accounts.

Existing content, members and connections are never removed. Run it as often
as you like; it prints what it changed.

The approver is ``--approver-email``, else ``BRAND_APPROVER_EMAIL``, else
``DJANGO_SUPERUSER_EMAIL``, else the oldest superuser.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.settings_manager.models import WorkspaceSetting
from apps.workspaces.brands import BRAND_KEY, BRANDS, EXPECTED_ACCOUNTS_KEY
from apps.workspaces.models import Workspace


def mask_email(email: str) -> str:
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "?"
    return f"{local[:1]}{'*' * max(len(local) - 1, 1)}@{domain}"


def resolve_approver(email=None):
    user_model = get_user_model()
    for candidate in (email, os.environ.get("BRAND_APPROVER_EMAIL"), os.environ.get("DJANGO_SUPERUSER_EMAIL")):
        if candidate:
            user = user_model.objects.filter(email__iexact=candidate.strip()).first()
            if user:
                return user
    return user_model.objects.filter(is_superuser=True, is_active=True).order_by("created_at").first()


def resolve_org(user):
    memberships = OrgMembership.objects.filter(user=user).select_related("organization")
    if user.last_workspace_id:
        current = memberships.filter(organization__workspaces__id=user.last_workspace_id).first()
        if current:
            return current.organization
    owned = memberships.filter(org_role=OrgMembership.OrgRole.OWNER).order_by("invited_at").first()
    if owned:
        return owned.organization
    first = memberships.order_by("invited_at").first()
    return first.organization if first else None


def find_brand_workspace(org, brand):
    names = {n.lower() for n in [brand["name"], *brand["match_names"]]}
    for ws in Workspace.objects.filter(organization=org, is_archived=False).order_by("created_at"):
        if ws.name.strip().lower() in names:
            return ws
    return None


def ensure_brand_workspaces(approver, *, log=print):
    """Create/reuse the brand workspaces for *approver*'s org. Returns {brand_key: workspace}."""
    org = resolve_org(approver)
    if org is None:
        org = Organization.objects.create(name="Neopolis Group", default_timezone="Asia/Kolkata")
        OrgMembership.objects.create(user=approver, organization=org, org_role=OrgMembership.OrgRole.OWNER)
        log(f"created organization {org.name} ({org.id})")
    result = {}
    for brand in BRANDS:
        with transaction.atomic():
            ws = find_brand_workspace(org, brand)
            created = ws is None
            if created:
                ws = Workspace.objects.create(organization=org, name=brand["name"])
            changes = []
            desired = {
                "timezone": brand["timezone"],
                "approval_workflow_mode": Workspace.ApprovalWorkflowMode.REQUIRED_INTERNAL,
                "require_dashboard_approval": True,
            }
            if not ws.description:
                desired["description"] = brand["description"]
            if not ws.primary_color and brand.get("primary_color"):
                desired["primary_color"] = brand["primary_color"]
            if not ws.secondary_color and brand.get("secondary_color"):
                desired["secondary_color"] = brand["secondary_color"]
            # Two-stage (internal + client) workspaces keep their client stage.
            if ws.approval_workflow_mode == Workspace.ApprovalWorkflowMode.REQUIRED_INTERNAL_AND_CLIENT:
                desired.pop("approval_workflow_mode")
            for field, value in desired.items():
                if getattr(ws, field) != value:
                    setattr(ws, field, value)
                    changes.append(field)
            if changes:
                ws.save(update_fields=[*changes, "updated_at"])

            membership, made = WorkspaceMembership.objects.get_or_create(
                user=approver,
                workspace=ws,
                defaults={"workspace_role": WorkspaceMembership.WorkspaceRole.OWNER},
            )
            if not made and membership.workspace_role != WorkspaceMembership.WorkspaceRole.OWNER:
                membership.workspace_role = WorkspaceMembership.WorkspaceRole.OWNER
                membership.custom_role = None
                membership.save(update_fields=["workspace_role", "custom_role"])
                changes.append("approver role → owner")
            elif made:
                changes.append("approver added as owner")

            WorkspaceSetting.objects.update_or_create(
                workspace=ws, key=EXPECTED_ACCOUNTS_KEY, defaults={"value": brand["expected_accounts"]}
            )
            WorkspaceSetting.objects.update_or_create(workspace=ws, key=BRAND_KEY, defaults={"value": brand["key"]})
        verb = "created" if created else "reused"
        log(f"{brand['name']}: {verb} workspace {ws.id} — {', '.join(changes) or 'already set up'}")
        result[brand["key"]] = ws
    return result


class Command(BaseCommand):
    help = "Create or reuse the Neopolis and More Space workspaces with enforced dashboard approval."

    def add_arguments(self, parser):
        parser.add_argument("--approver-email", default=None)

    def handle(self, *args, approver_email=None, **options):
        approver = resolve_approver(approver_email)
        if approver is None:
            raise CommandError("No approver: pass --approver-email or set BRAND_APPROVER_EMAIL.")
        self.stdout.write(f"setup_brands: approver {mask_email(approver.email)}")
        workspaces = ensure_brand_workspaces(approver, log=lambda m: self.stdout.write(f"setup_brands: {m}"))
        try:
            from apps.blog.services import ensure_blog_sites
        except ImportError:
            ensure_blog_sites = None
        if ensure_blog_sites is not None:
            ensure_blog_sites(workspaces["neopolis"], workspaces["morespace"])
            self.stdout.write("setup_brands: blog sites ensured")
        self.stdout.write(self.style.SUCCESS("setup_brands: done"))
