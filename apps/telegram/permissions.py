"""Current identity and workspace authority; Telegram usernames never grant access."""

from django.core.exceptions import PermissionDenied

from apps.accounts.models import User
from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace

from .models import TelegramConnection, TelegramUserLink


class TelegramPermissionDenied(PermissionDenied):
    pass


def internal_member(member) -> bool:
    return bool(
        member is not None
        and member.workspace_role != "client"
        and not (member.custom_role and (member.custom_role.permissions or {}).get("client_facing"))
    )


def can_manage(member) -> bool:
    return internal_member(member) and bool(member.effective_permissions.get("manage_workspace_settings") is True)


def can_pair_group(member) -> bool:
    return internal_member(member) and bool(
        can_manage(member)
        or (
            member.effective_permissions.get("create_posts") is True
            and member.effective_permissions.get("approve_posts") is True
        )
    )


def _query(model, locked):
    return model.objects.select_for_update(of=("self",)) if locked else model.objects.all()


def current_member(workspace, user, *, locked=False, connection=None):
    """Return fresh membership or reject removed, foreign or deleting-tenant access."""
    ws = _query(Workspace, locked).filter(pk=workspace.pk, is_archived=False).first()
    if ws is None:
        raise TelegramPermissionDenied("This workspace is unavailable.")
    org = (
        _query(Organization, locked)
        .filter(pk=ws.organization_id, deletion_requested_at__isnull=True, deleted_at__isnull=True)
        .first()
    )
    person = _query(User, locked).filter(pk=user.pk, is_active=True).first()
    if org is None or person is None:
        raise TelegramPermissionDenied("Your active workspace access is unavailable.")
    if (
        connection is not None
        and _query(TelegramConnection, locked).filter(pk=connection.pk, workspace=ws).first() is None
    ):
        raise TelegramPermissionDenied("This bot connection belongs to another workspace.")
    member = _query(WorkspaceMembership, locked).filter(workspace=ws, user=person).first()
    if member is not None and member.custom_role_id:
        member.custom_role = _query(CustomRole, locked).filter(pk=member.custom_role_id, organization=org).first()
        if member.custom_role is None or not isinstance(member.custom_role.permissions, dict):
            raise TelegramPermissionDenied("Your workspace role is unavailable.")
    org_member = _query(OrgMembership, locked).filter(organization=org, user=person).first()
    if member is None or (org_member is None and internal_member(member)):
        raise TelegramPermissionDenied("Your current workspace membership is required.")
    member.workspace = ws
    member.user = person
    return member


def fresh_member(link, permission=None, *, locked=False):
    """Authenticate a paired numeric identity using current membership and permissions."""
    preliminary = TelegramUserLink.objects.select_related("connection__workspace", "user").filter(pk=link.pk).first()
    if preliminary is None:
        raise TelegramPermissionDenied("Pair your Telegram account again.")
    # Acquire the shared order before link/membership locks.
    ws = _query(Workspace, locked).filter(pk=preliminary.connection.workspace_id, is_archived=False).first()
    if ws is None:
        raise TelegramPermissionDenied("This workspace is unavailable.")
    org = _query(Organization, locked).filter(pk=ws.organization_id).first()
    person = _query(User, locked).filter(pk=preliminary.user_id).first()
    connection = (
        _query(TelegramConnection, locked).filter(pk=preliminary.connection_id, workspace=ws, is_active=True).first()
    )
    current = (
        _query(TelegramUserLink, locked)
        .filter(pk=preliminary.pk, connection=connection, user=person, is_active=True)
        .first()
    )
    if org is None or person is None or connection is None or current is None:
        raise TelegramPermissionDenied("This Telegram pairing is inactive.")
    member = current_member(ws, person, locked=locked)
    if permission and (
        member.effective_permissions.get(permission) is not True
        or (permission in {"approve_posts", "manage_workspace_settings"} and not internal_member(member))
    ):
        raise TelegramPermissionDenied("Your current role does not allow this Telegram action.")
    return member
