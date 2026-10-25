"""The world the browser tests start from, built on ``--reset`` into the e2e database.

Organisation "E2E Agency" (Asia/Kolkata) with workspace A, "Neopolis", at a fixed id: internal
approval required, in the dashboard. Its people: an owner (the agency lead and an approver), a
manager (an approver), an editor (staff who writes posts but cannot approve) and a client (portal).
Connected LinkedIn company, Instagram and Facebook accounts, the brand profile, verified facts, the
agency settings (owner as lead, autopilot off, the brief shown first) and one library image.
Workspace B, "Bayside Holdings", at a fixed id in its own organisation with its own owner, for the
isolation paths. Nobody gets the auto-created "My Workspace", and everyone lands on their workspace.

Everything a single test needs beyond this (posts, briefs, a two-stage workspace) is made by that
test's fixtures, so tests do not depend on order. :func:`ids` reads the ids back from the database,
so a server started without ``--reset`` answers ``/__e2e__/ping`` from what is there.
"""

from __future__ import annotations

import io
import uuid
from datetime import timedelta
from typing import Any

WORKSPACE_A_ID = uuid.UUID("00000000-0000-4000-8000-00000000000a")
WORKSPACE_B_ID = uuid.UUID("00000000-0000-4000-8000-00000000000b")
ORGANISATION_A_NAME = "E2E Agency"
ORGANISATION_B_NAME = "Bayside Group"
WORKSPACE_A_NAME = "Neopolis"
WORKSPACE_B_NAME = "Bayside Holdings"
TIMEZONE = "Asia/Kolkata"
#: Every seeded person's password (a fixture credential for a loopback-only test database).
PASSWORD = "e2e-pass-Neopolis-2026"
LIBRARY_ASSET_TITLE = "E2E library photo"

#: key -> (email, name, workspace role, organisation role); the last one belongs to workspace B.
USERS: dict[str, tuple[str, str, str, str]] = {
    "owner": ("owner@e2e.test", "Ana Owner", "owner", "owner"),
    "manager": ("manager@e2e.test", "Maya Manager", "manager", "member"),
    "editor": ("editor@e2e.test", "Eli Editor", "editor", "member"),
    "client": ("client@e2e.test", "Priya Client", "client", "member"),
    "owner_b": ("owner-b@e2e.test", "Bea Bayside", "owner", "owner"),
}

#: platform -> (account name, handle, platform id) on workspace A.
ACCOUNTS: dict[str, tuple[str, str, str]] = {
    "linkedin_company": ("Neopolis Infra", "", "e2e-li-org-98765"),
    "instagram": ("neopolisinfra", "neopolisinfra", "e2e-ig-17841400000000"),
    "facebook": ("Neopolis Infra Page", "", "e2e-fb-page-585141221346"),
}

FACTS = (
    ("general", "Free parking at the Kokapet site office on visit days."),
    ("launch", "Site visits run every Saturday, 10:00 to 17:00."),
    ("contact", "WhatsApp the sales office for the current availability list."),
)


class SeedMissingError(RuntimeError):
    """The e2e database has not been seeded (start the server with --reset)."""


def _person(email: str, name: str) -> Any:
    """A user with the terms accepted and without the organisation every new user is given."""
    from django.utils import timezone

    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.organizations.models import Organization

    user = User.objects.create_user(email=email, password=PASSWORD, name=name, tos_accepted_at=timezone.now())
    auto_orgs = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto_orgs).delete()
    return user


def _library_image(org: Any, workspace: Any, owner: Any) -> Any:
    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image, ImageDraw

    from apps.media_library.services import create_asset
    from apps.media_library.tasks import process_media_asset

    image = Image.new("RGB", (1080, 1350), (30, 37, 51))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 1150, 1080, 1350), fill=(241, 236, 228))
    draw.ellipse((340, 400, 740, 800), fill=(84, 130, 112))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    upload = SimpleUploadedFile("e2e-library-photo.png", buffer.getvalue(), content_type="image/png")
    asset = create_asset(org, workspace, upload, owner, title=LIBRARY_ASSET_TITLE, alt_text="A green circle on navy")
    process_media_asset.now(str(asset.id))
    asset.refresh_from_db()
    return asset


def run() -> dict[str, Any]:
    """Build the world in an empty e2e database and return :func:`ids`."""
    from django.utils import timezone

    from apps.calendar.services import create_default_queue_and_slots
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.studio.brand_defaults import ensure_profile
    from apps.studio.models import AgencySettings, BrandClaim
    from apps.workspaces.models import Workspace

    if Workspace.objects.filter(pk=WORKSPACE_A_ID).exists():
        return ids()

    now = timezone.now()
    people = {key: _person(email, name) for key, (email, name, _role, _org_role) in USERS.items()}

    org_a = Organization.objects.create(name=ORGANISATION_A_NAME, default_timezone=TIMEZONE)
    org_b = Organization.objects.create(name=ORGANISATION_B_NAME, default_timezone=TIMEZONE)
    ws_a = Workspace.objects.create(
        id=WORKSPACE_A_ID,
        organization=org_a,
        name=WORKSPACE_A_NAME,
        timezone=TIMEZONE,
        approval_workflow_mode=Workspace.ApprovalWorkflowMode.REQUIRED_INTERNAL,
        require_dashboard_approval=True,
    )
    ws_b = Workspace.objects.create(
        id=WORKSPACE_B_ID,
        organization=org_b,
        name=WORKSPACE_B_NAME,
        timezone=TIMEZONE,
        approval_workflow_mode=Workspace.ApprovalWorkflowMode.REQUIRED_INTERNAL,
        require_dashboard_approval=True,
    )
    for key, (_email, _name, role, org_role) in USERS.items():
        org, workspace = (org_b, ws_b) if key == "owner_b" else (org_a, ws_a)
        OrgMembership.objects.create(user=people[key], organization=org, org_role=org_role)
        WorkspaceMembership.objects.create(user=people[key], workspace=workspace, workspace_role=role)
        people[key].last_workspace_id = workspace.pk
        people[key].save(update_fields=["last_workspace_id"])

    accounts = []
    for platform, (name, handle, platform_id) in ACCOUNTS.items():
        account = SocialAccount(
            workspace=ws_a,
            platform=platform,
            account_platform_id=platform_id,
            account_name=name,
            account_handle=handle,
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
            oauth_access_token=f"e2e-token-{platform}",
            follower_count=1500,
        )
        # Seeded as connected long ago: no first-connect analytics backfill (it would only meet the mock).
        account.__dict__["_skip_analytics_backfill"] = True
        account.save()
        create_default_queue_and_slots(account)
        accounts.append(account)

    owner = people["owner"]
    profile = ensure_profile(ws_a)
    profile.audience = "Families buying their first home in West Hyderabad"
    profile.voice = "Warm, plain and specific. No hype."
    profile.default_cta = "WhatsApp the sales office for the availability list"
    profile.save()
    for category, claim in FACTS:
        BrandClaim.objects.create(
            workspace=ws_a,
            category=category,
            claim=claim,
            source_note="Confirmed by the sales office",
            verified_by=owner,
            verified_at=now,
            valid_until=(now + timedelta(days=90)).date(),
        )

    agency, _created = AgencySettings.objects.get_or_create(workspace=ws_a)
    agency.lead = owner
    agency.autopilot_enabled = False
    agency.creation_mode = AgencySettings.CreationMode.CONFIRM
    agency.save()
    agency.accounts.set(accounts)

    _library_image(org_a, ws_a, owner)
    return ids()


def ids() -> dict[str, Any]:
    """The seeded ids, read from the database (``SeedMissingError`` before ``--reset``).

    A database that is missing, or that exists but is not migrated, is the same case as one that is
    not seeded: the answer is ``--reset``, not a traceback (or a 500 from ``/__e2e__/ping``).
    """
    from django.db import DatabaseError

    from apps.accounts.models import User
    from apps.media_library.models import MediaAsset
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace

    try:
        ws_a = Workspace.objects.get(pk=WORKSPACE_A_ID)
        ws_b = Workspace.objects.get(pk=WORKSPACE_B_ID)
        users = {key: User.objects.get(email=email) for key, (email, *_rest) in USERS.items()}
        accounts = {
            platform: SocialAccount.objects.get(workspace=ws_a, platform=platform, account_platform_id=platform_id)
            for platform, (_name, _handle, platform_id) in ACCOUNTS.items()
        }
        asset = MediaAsset.objects.get(workspace=ws_a, title=LIBRARY_ASSET_TITLE)
    except (Workspace.DoesNotExist, User.DoesNotExist, SocialAccount.DoesNotExist, MediaAsset.DoesNotExist) as exc:
        raise SeedMissingError("The e2e database is not seeded: start the server with --reset.") from exc
    except DatabaseError as exc:
        raise SeedMissingError(
            f"The e2e database is missing or not migrated ({type(exc).__name__}): start the server with --reset."
        ) from exc
    return {
        "workspace_a": str(ws_a.pk),
        "workspace_b": str(ws_b.pk),
        "organisation_a": str(ws_a.organization_id),
        "organisation_b": str(ws_b.organization_id),
        "workspace_names": {"a": ws_a.name, "b": ws_b.name},
        "users": {key: {"id": str(user.pk), "email": user.email} for key, user in users.items()},
        "accounts": {
            platform: {"id": str(account.pk), "platform_id": account.account_platform_id, "name": account.account_name}
            for platform, account in accounts.items()
        },
        "library_asset": {"id": str(asset.pk), "title": asset.title},
        "password": PASSWORD,
        "timezone": ws_a.timezone,
    }
