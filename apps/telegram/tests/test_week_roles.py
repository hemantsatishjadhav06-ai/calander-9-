"""Who may prepare a week from Telegram: the lead, the backup, or an approver who also creates posts."""

import pytest
from django.core.exceptions import PermissionDenied

from apps.members.models import OrgMembership
from apps.studio.models import AgencyJob
from apps.studio.tests.conftest import world  # noqa: F401
from apps.telegram import weekly
from apps.telegram.models import TelegramUserLink
from apps.telegram.tests.test_weekly import MONDAY, hub  # noqa: F401

pytestmark = pytest.mark.django_db


def test_backup_or_approving_creator_may_prepare_without_settings_rights(hub):  # noqa: F811
    people = hub.world
    manager_link = TelegramUserLink.objects.create(connection=hub.conn, user=people.manager, telegram_user_id=880002)
    editor_link = TelegramUserLink.objects.create(connection=hub.conn, user=people.editor, telegram_user_id=880003)
    for person in (people.manager, people.editor):
        OrgMembership.objects.get_or_create(organization=people.org, user=person, defaults={"org_role": "member"})
    # The backup is a manager without manage_workspace_settings: allowed now.
    preview = weekly.queue_week_plan(manager_link, hub.chat, week_start=MONDAY)
    assert preview["needs_confirmation"] is True
    # An editor creates posts but does not approve them: still refused.
    with pytest.raises(PermissionDenied):
        weekly.queue_week_plan(editor_link, hub.chat, week_start=MONDAY)
    assert not AgencyJob.objects.filter(kind="plan").exists()
