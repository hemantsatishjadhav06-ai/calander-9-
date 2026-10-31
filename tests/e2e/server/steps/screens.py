"""Steps for the Phase 2 screens specs (``tests/e2e/screens/``): the navigation, Approvals, Settings,
Activity, the switches and the public pages.

Fixtures:

- ``workspace_member``: a fresh person with any workspace role (``{"role", "workspace_id"?}``,
  workspace A by default), a member of that workspace's organisation who has signed in before and
  lands there. The seed has no viewer, and a test that needs one makes its own.
- ``workspace_switches``: sets switches on a workspace a test made for itself
  (``{"workspace_id", "features": {"<key>": bool}}``), one key or several, leaving the others as
  they were. The seeded workspaces A and B are refused: every spec shares them, so a switch
  turned there would change what other specs see. Answers the switches as ``features_for`` reads them.
- ``unread_notification``: one unread notification for a person (``{"email", "title"?}``), shown in
  the app, as the notifications engine would leave it for its in-app channel, and nothing sent
  anywhere. Answers its id and the person's unread count.
- ``invite_operator``: the platform operator who receives invite requests (an active staff member,
  ``operator@e2e.test``), made once and reused. Without one, a request goes to the support address,
  which the e2e settings leave empty, so the form could only answer that nobody could be told.

Probe:

- ``invite_requests``: what one requester's invite request left for the operators
  (``?email=<the requester's address>``): the active operators, and one entry per notification.
"""

from __future__ import annotations

import uuid
from typing import Any

from .. import seed
from ..registry import PayloadError, fixture, optional_str, probe, require_str

OPERATOR_EMAIL = "operator@e2e.test"
OPERATOR_NAME = "Oona Operator"


def _workspace(payload: dict[str, Any], *, default: uuid.UUID | None = None) -> Any:
    """The workspace named by ``workspace_id`` (or *default*); a bad or unknown id is a PayloadError."""
    from apps.workspaces.models import Workspace

    if default is not None and payload.get("workspace_id") in (None, ""):
        return Workspace.objects.get(pk=default)
    value = require_str(payload, "workspace_id")
    try:
        workspace_id = uuid.UUID(value)
    except ValueError as exc:
        raise PayloadError("'workspace_id' must be a UUID.") from exc
    workspace = Workspace.objects.filter(pk=workspace_id).first()
    if workspace is None:
        raise PayloadError(f"No workspace {workspace_id}.")
    return workspace


@fixture("workspace_member")
def workspace_member(payload: dict[str, Any]) -> dict[str, Any]:
    from apps.members.models import OrgMembership, WorkspaceMembership

    role = require_str(payload, "role")
    roles = WorkspaceMembership.WorkspaceRole.values
    if role not in roles:
        raise PayloadError(f"Unknown role {role!r}; use one of {', '.join(roles)}.")
    workspace = _workspace(payload, default=seed.WORKSPACE_A_ID)
    person = seed._person(f"{role}-{uuid.uuid4().hex[:12]}@e2e.test", f"Sam {role.title()}")
    OrgMembership.objects.create(
        user=person, organization=workspace.organization, org_role=OrgMembership.OrgRole.MEMBER
    )
    WorkspaceMembership.objects.create(user=person, workspace=workspace, workspace_role=role)
    person.last_workspace_id = workspace.pk
    person.save(update_fields=["last_workspace_id"])
    return {"id": str(person.pk), "email": person.email, "role": role, "workspace_id": str(workspace.pk)}


@fixture("workspace_switches")
def workspace_switches(payload: dict[str, Any]) -> dict[str, Any]:
    from django.db import transaction

    from apps.common.features import FEATURE_KEYS, features_for
    from apps.studio.models import AgencySettings

    workspace = _workspace(payload)
    if workspace.pk in (seed.WORKSPACE_A_ID, seed.WORKSPACE_B_ID):
        raise PayloadError("The seeded workspaces are shared by every spec: make a workspace for this test first.")
    wanted = payload.get("features")
    if not isinstance(wanted, dict) or not wanted:
        raise PayloadError("'features' must be an object of switches, like {\"blog\": true}.")
    for key, value in wanted.items():
        if key not in FEATURE_KEYS:
            raise PayloadError(f"Unknown switch {key!r}; use one of {', '.join(FEATURE_KEYS)}.")
        if not isinstance(value, bool):
            raise PayloadError(f"The switch {key!r} must be true or false.")
    with transaction.atomic():
        AgencySettings.objects.get_or_create(workspace=workspace)
        agency = AgencySettings.objects.select_for_update().get(workspace=workspace)
        features = dict(agency.features) if isinstance(agency.features, dict) else {}
        features.update(wanted)
        agency.features = features
        agency.save(update_fields=["features"])
    return {"workspace_id": str(workspace.pk), "features": features_for(workspace)}


@fixture("unread_notification")
def unread_notification(payload: dict[str, Any]) -> dict[str, Any]:
    from apps.accounts.models import User
    from apps.notifications.models import EventType, Notification

    email = require_str(payload, "email")
    title = optional_str(payload, "title") or "E2E: someone joined the team"
    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user is None:
        raise PayloadError(f"No active user with the email {email!r}.")
    # A plain in-app notice: Telegram has no branch for this event type, and nothing is mailed.
    notice = Notification.objects.create(
        user=user, event_type=EventType.TEAM_MEMBER_INVITED, title=title, body="", shown_in_app=True
    )
    unread = Notification.objects.filter(user=user, is_read=False, shown_in_app=True).count()
    return {"id": str(notice.pk), "unread": unread}


@fixture("invite_operator")
def invite_operator(payload: dict[str, Any]) -> dict[str, Any]:
    from apps.accounts.models import User

    if payload:
        raise PayloadError("invite_operator takes no options: send {}.")
    operator = User.objects.filter(email__iexact=OPERATOR_EMAIL).first()
    if operator is None:
        operator = seed._person(OPERATOR_EMAIL, OPERATOR_NAME)
    if not (operator.is_staff and operator.is_active):
        operator.is_staff = True
        operator.is_active = True
        operator.save(update_fields=["is_staff", "is_active"])
    return {"id": str(operator.pk), "email": operator.email}


@probe("invite_requests")
def invite_requests(params: dict[str, Any]) -> dict[str, Any]:
    from apps.accounts.models import User
    from apps.notifications.models import EventType, Notification

    email = require_str(params, "email")
    operators = list(User.objects.filter(is_staff=True, is_active=True).order_by("pk"))
    # The request's body names the requester's address on its own line (marketing.views).
    notices = (
        Notification.objects.filter(
            user__in=operators, event_type=EventType.INVITE_REQUESTED, body__contains=f"Email: {email}\n"
        )
        | Notification.objects.filter(
            user__in=operators, event_type=EventType.INVITE_REQUESTED, body__endswith=f"Email: {email}"
        )
    ).select_related("user")
    return {
        "operators": [operator.email for operator in operators],
        "notifications": [
            {"operator": notice.user.email, "title": notice.title, "is_read": notice.is_read}
            for notice in notices.order_by("created_at", "pk")
        ],
    }
