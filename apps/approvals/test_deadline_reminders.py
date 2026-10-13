"""Approval deadlines notify people; they never approve or schedule content.

The notification engine runs against a local email backend. No model, social
network, browser or external mail provider is used by these tests.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace

import pytest
from background_task.models import Task
from django.db import close_old_connections
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals import tasks
from apps.approvals.apps import ApprovalsConfig
from apps.approvals.models import ApprovalAction, ApprovalReminder
from apps.composer.models import PlatformPost, Post
from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
from apps.notifications.models import Channel, EventType, Notification, NotificationPreference
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.studio.models import AgencySettings, StudioBrief
from apps.workspaces.models import Workspace


def _person(workspace, role, email):
    user = User.objects.create_user(email=email, password="test-password-123", tos_accepted_at=timezone.now())
    if role != "client":
        OrgMembership.objects.create(
            user=user, organization=workspace.organization, org_role="owner" if role == "owner" else "member"
        )
    WorkspaceMembership.objects.create(workspace=workspace, user=user, workspace_role=role)
    return user


@pytest.fixture
def team(db, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    org = Organization.objects.create(name="Agency")
    workspace = Workspace.objects.create(organization=org, name="Brand", timezone="Asia/Kolkata")
    lead = _person(workspace, "manager", "deadline-lead@example.com")
    backup = _person(workspace, "manager", "deadline-backup@example.com")
    owner = _person(workspace, "owner", "deadline-owner@example.com")
    author = _person(workspace, "editor", "deadline-author@example.com")
    client = _person(workspace, "client", "deadline-client@example.com")
    account = SocialAccount.objects.create(
        workspace=workspace, platform="linkedin_company", account_platform_id="deadline-page", account_name="Brand Page"
    )
    agency = AgencySettings.objects.create(workspace=workspace, lead=lead, backup=backup)
    return SimpleNamespace(
        org=org,
        workspace=workspace,
        lead=lead,
        backup=backup,
        owner=owner,
        author=author,
        client=client,
        account=account,
        agency=agency,
    )


def _post(team, *, due_in=timedelta(minutes=45), status="pending_review", old=None):
    post = Post.objects.create(
        workspace=team.workspace,
        author=team.author,
        caption="Saturday's site visit",
        proposed_publish_at=timezone.now() + due_in if due_in is not None else None,
    )
    PlatformPost.objects.create(post=post, social_account=team.account, status=status)
    if old is not None:
        Post.objects.filter(pk=post.pk).update(updated_at=timezone.now() - old)
        post.refresh_from_db()
    return post


def _notices(post):
    return Notification.objects.filter(event_type__in=tasks._ALERT_EVENTS, data__post_id=str(post.pk))


def _tick(monkeypatch, moment):
    monkeypatch.setattr(tasks.timezone, "now", lambda: moment)
    tasks.check_approval_reminders()


class TestDeadlineOwnership:
    def test_lead_receives_one_imminent_review_with_local_time_and_no_state_change(self, team, monkeypatch):
        now = timezone.now()
        post = _post(team)
        _tick(monkeypatch, now)
        _tick(monkeypatch, now + timedelta(minutes=10))

        notice = _notices(post).get()
        assert notice.user_id == team.lead.pk
        assert notice.data["deadline_role"] == "lead"
        assert notice.data["deadline"] == post.proposed_publish_at.isoformat()
        assert reverse("calendar:calendar", kwargs={"workspace_id": team.workspace.pk}) in notice.data["action_url"]
        assert notice.data["action_url"].endswith("?mode=list&tab=approvals")
        assert "Asia/Kolkata" in notice.body
        assert "Nothing is approved or scheduled automatically" in notice.body
        assert ApprovalReminder.objects.get(post=post, stage="review_deadline").reminder_count == 1
        assert post.platform_posts.get().status == "pending_review"
        post.refresh_from_db()
        assert post.scheduled_at is None and not ApprovalAction.objects.filter(post=post).exists()

    def test_backup_is_notified_once_when_the_later_window_opens(self, team, monkeypatch):
        now = timezone.now()
        post = _post(team)
        _tick(monkeypatch, now)
        _tick(monkeypatch, now + timedelta(minutes=20))
        _tick(monkeypatch, now + timedelta(minutes=25))

        assert set(_notices(post).values_list("user_id", flat=True)) == {team.lead.pk, team.backup.pk}
        assert _notices(post).count() == 2
        assert _notices(post).get(user=team.backup).data["deadline_role"] == "backup"
        assert ApprovalReminder.objects.get(post=post, stage="review_deadline").reminder_count == 1
        assert ApprovalReminder.objects.get(post=post, stage="review_backup").reminder_count == 1

    def test_first_check_in_backup_window_reaches_both_people(self, team):
        post = _post(team, due_in=timedelta(minutes=20))
        tasks.check_approval_reminders()
        tasks.check_approval_reminders()
        assert _notices(post).count() == 2
        assert set(_notices(post).values_list("user_id", flat=True)) == {team.lead.pk, team.backup.pk}

    def test_same_person_as_lead_and_backup_gets_one_notice(self, team):
        team.agency.backup = team.lead
        team.agency.save(update_fields=["backup"])
        post = _post(team, due_in=timedelta(minutes=20))
        tasks.check_approval_reminders()
        tasks.check_approval_reminders()
        assert _notices(post).count() == 1 and _notices(post).get().user_id == team.lead.pk

    @pytest.mark.parametrize("invalid", ["inactive", "revoked", "client", "foreign_membership", "foreign_role"])
    def test_invalid_lead_is_never_sent_a_brand_notice(self, team, invalid):
        membership = WorkspaceMembership.objects.get(workspace=team.workspace, user=team.lead)
        if invalid == "inactive":
            User.objects.filter(pk=team.lead.pk).update(is_active=False)
        elif invalid == "revoked":
            membership.workspace_role = "viewer"
            membership.save(update_fields=["workspace_role"])
        elif invalid == "client":
            membership.workspace_role = "client"
            membership.save(update_fields=["workspace_role"])
        elif invalid == "foreign_membership":
            other = Workspace.objects.create(organization=team.org, name="Other")
            membership.workspace = other
            membership.save(update_fields=["workspace"])
        else:
            foreign_org = Organization.objects.create(name="Another agency")
            membership.custom_role = CustomRole.objects.create(
                organization=foreign_org, name="Approver", permissions={"approve_posts": True}
            )
            membership.save(update_fields=["custom_role"])
        post = _post(team)
        tasks.check_approval_reminders()

        assert not _notices(post).filter(user=team.lead).exists()
        assert _notices(post).filter(user=team.owner).exists()
        assert post.platform_posts.get().status == "pending_review"

    def test_backup_permission_is_revalidated_after_the_lead_notice(self, team, monkeypatch):
        now = timezone.now()
        post = _post(team)
        _tick(monkeypatch, now)
        WorkspaceMembership.objects.filter(workspace=team.workspace, user=team.backup).update(workspace_role="viewer")
        _tick(monkeypatch, now + timedelta(minutes=20))
        assert not _notices(post).filter(user=team.backup).exists()
        assert _notices(post).filter(user=team.owner, data__deadline_role="backup").exists()

    def test_revoked_org_access_with_a_dangling_workspace_role_does_not_receive_a_reminder(self, team):
        OrgMembership.objects.filter(user=team.lead, organization=team.org).delete()
        assert WorkspaceMembership.objects.filter(user=team.lead, workspace=team.workspace).exists()
        post = _post(team)
        tasks.check_approval_reminders()
        assert not _notices(post).filter(user=team.lead).exists()
        assert _notices(post).filter(user=team.owner).exists()

    def test_pending_client_notice_coordinates_signoff_without_approving_for_them(self, team):
        post = _post(team, status="pending_client", due_in=timedelta(minutes=20))
        tasks.check_approval_reminders()
        assert _notices(post).count() == 2
        assert all("client approval" in notice.body for notice in _notices(post))
        assert not _notices(post).filter(user=team.client).exists()
        assert post.platform_posts.get().status == "pending_client"
        assert not ApprovalAction.objects.filter(post=post).exists()

    def test_entering_client_approval_gets_its_own_meaningful_lead_notice(self, team, monkeypatch):
        now = timezone.now()
        post = _post(team)
        _tick(monkeypatch, now)
        PlatformPost.objects.filter(post=post).update(status="pending_client")
        _tick(monkeypatch, now + timedelta(minutes=5))
        assert _notices(post).filter(user=team.lead).count() == 2
        assert _notices(post).filter(user=team.lead, data__approval_stage="pending_client").exists()
        assert post.platform_posts.get().status == "pending_client"

    def test_elapsed_deadline_escalates_once_with_an_action_and_never_schedules(self, team):
        post = _post(team, due_in=timedelta(minutes=-5))
        tasks.check_approval_reminders()
        tasks.check_approval_reminders()

        assert _notices(post).count() == 2
        assert set(_notices(post).values_list("event_type", flat=True)) == {EventType.APPROVAL_STALLED}
        assert all("choose a new future time" in notice.body for notice in _notices(post))
        assert ApprovalReminder.objects.get(post=post, stage="review_deadline").escalated
        assert post.platform_posts.get().status == "pending_review"
        assert not ApprovalAction.objects.filter(post=post).exists()


class TestDeadlineSourcesAndIsolation:
    def test_post_proposal_takes_priority_over_a_stale_platform_schedule(self, team):
        post = _post(team, due_in=timedelta(hours=3))
        PlatformPost.objects.filter(post=post).update(scheduled_at=timezone.now() + timedelta(minutes=15))
        tasks.check_approval_reminders()
        assert not _notices(post).exists()

    @pytest.mark.parametrize("source", ["platform", "parent", "brief"])
    def test_saved_publish_time_fallbacks_can_supply_a_review_deadline(self, team, source):
        post = _post(team, due_in=None)
        due = timezone.now() + timedelta(minutes=45)
        if source == "platform":
            PlatformPost.objects.filter(post=post).update(scheduled_at=due)
        elif source == "parent":
            Post.objects.filter(pk=post.pk).update(scheduled_at=due)
        else:
            StudioBrief.objects.create(
                workspace=team.workspace,
                author=team.author,
                idea="The idea",
                post=post,
                proposed_publish_at=due,
                status=StudioBrief.Status.READY,
            )
        tasks.check_approval_reminders()
        assert _notices(post).get().data["deadline"] == due.isoformat()
        assert post.platform_posts.get().status == "pending_review"

    def test_foreign_workspace_brief_cannot_supply_a_deadline(self, team):
        post = _post(team, due_in=None)
        other = Workspace.objects.create(organization=team.org, name="Other")
        StudioBrief.objects.create(
            workspace=other,
            author=team.author,
            idea="Private brief",
            post=post,
            proposed_publish_at=timezone.now() + timedelta(minutes=45),
            status=StudioBrief.Status.READY,
        )
        tasks.check_approval_reminders()
        assert not _notices(post).exists()

    def test_foreign_account_fk_is_not_a_valid_pending_destination(self, team):
        post = _post(team, old=timedelta(days=5))
        other = Workspace.objects.create(organization=team.org, name="Other")
        SocialAccount.objects.filter(pk=team.account.pk).update(workspace=other)
        tasks.check_approval_reminders()
        assert not _notices(post).exists() and not ApprovalReminder.objects.filter(post=post).exists()

    @pytest.mark.parametrize("status", ["draft", "scheduled", "published", "failed", "on_hold", "approved"])
    def test_only_pending_approvals_enter_deadline_reminders(self, team, status):
        post = _post(team, status=status)
        tasks.check_approval_reminders()
        assert not _notices(post).exists() and post.platform_posts.get().status == status

    def test_archived_workspace_does_not_trigger_age_or_deadline_notices(self, team):
        post = _post(team, old=timedelta(days=5))
        Workspace.objects.filter(pk=team.workspace.pk).update(is_archived=True)
        tasks.check_approval_reminders()
        assert not _notices(post).exists()

    @pytest.mark.parametrize("revocation", ["workspace", "organization", "inactive", "permission"])
    def test_permission_revoked_after_candidate_selection_is_checked_before_dispatch(
        self, team, monkeypatch, revocation
    ):
        original = tasks._notify_members

        def revoke_then_send(post, user_ids, **kwargs):
            if kwargs.get("data", {}).get("deadline_role") == "lead":
                if revocation == "organization":
                    OrgMembership.objects.filter(user=team.lead, organization=team.org).delete()
                elif revocation == "inactive":
                    User.objects.filter(pk=team.lead.pk).update(is_active=False)
                elif revocation == "permission":
                    WorkspaceMembership.objects.filter(user=team.lead, workspace=team.workspace).update(
                        workspace_role="viewer"
                    )
                else:
                    WorkspaceMembership.objects.filter(user=team.lead, workspace=team.workspace).delete()
            return original(post, user_ids, **kwargs)

        monkeypatch.setattr(tasks, "_notify_members", revoke_then_send)
        post = _post(team)
        tasks.check_approval_reminders()
        assert not _notices(post).filter(user=team.lead).exists()


class TestReminderCapsAndCompatibility:
    def test_imminent_deadline_replaces_the_age_notice_in_the_same_sweep(self, team):
        post = _post(team, old=timedelta(days=3))
        tasks.check_approval_reminders()
        assert _notices(post).count() == 1
        assert _notices(post).get().data["deadline_role"] == "lead"
        assert not ApprovalReminder.objects.filter(post=post, stage="pending_review").exists()

    def test_an_earlier_age_notice_is_reused_when_the_deadline_becomes_imminent(self, team, monkeypatch):
        now = timezone.now()
        post = _post(team, due_in=timedelta(hours=3), old=timedelta(days=3))
        _tick(monkeypatch, now)
        count = _notices(post).filter(user=team.lead).count()
        _tick(monkeypatch, now + timedelta(hours=2, minutes=15))
        assert count == 1 and _notices(post).filter(user=team.lead).count() == 1
        assert ApprovalReminder.objects.get(post=post, stage="review_deadline").reminder_count == 1

    def test_age_reminders_keep_the_existing_cooldown_then_escalate_once(self, team, monkeypatch):
        now = timezone.now()
        post = _post(team, due_in=None, old=timedelta(days=3))
        _tick(monkeypatch, now)
        _tick(monkeypatch, now + timedelta(hours=1))
        assert _notices(post).filter(user=team.lead).count() == 1
        _tick(monkeypatch, now + timedelta(hours=25))
        _tick(monkeypatch, now + timedelta(hours=26))
        _tick(monkeypatch, now + timedelta(hours=27))
        assert _notices(post).filter(user=team.lead, event_type=EventType.APPROVAL_REMINDER).count() == 2
        assert _notices(post).filter(user=team.lead, event_type=EventType.APPROVAL_STALLED).count() == 1
        assert ApprovalReminder.objects.get(post=post, stage="pending_review").escalated
        assert not _notices(post).filter(user=team.client).exists()

    def test_old_client_reminders_still_go_to_the_clients(self, team):
        post = _post(team, due_in=None, status="pending_client", old=timedelta(days=3))
        tasks.check_approval_reminders()
        notice = _notices(post).get()
        assert notice.user_id == team.client.pk and notice.data["stage"] == "pending_client"
        assert notice.data["action_url"].endswith(reverse("client_portal:approval_queue"))

    def test_daily_cap_is_shared_across_posts_and_retry_sweeps(self, team, settings):
        settings.APPROVAL_ALERTS_PER_USER_DAY = 2
        posts = [_post(team) for _ in range(4)]
        tasks.check_approval_reminders()
        tasks.check_approval_reminders()
        assert Notification.objects.filter(user=team.lead, event_type__in=tasks._ALERT_EVENTS).count() == 2
        assert sum(_notices(post).count() for post in posts) == 2

    def test_capped_lead_remains_eligible_after_backup_has_already_been_notified(self, team, settings, monkeypatch):
        settings.APPROVAL_ALERTS_PER_USER_DAY = 1
        existing = Notification.objects.create(
            user=team.lead, event_type=EventType.APPROVAL_STALLED, title="Prior post"
        )
        now = timezone.now()
        post = _post(team, due_in=timedelta(minutes=20))
        _tick(monkeypatch, now)
        assert _notices(post).get().user_id == team.backup.pk
        assert ApprovalReminder.objects.get(post=post, stage="review_deadline").reminder_count == 0
        assert ApprovalReminder.objects.get(post=post, stage="review_backup").reminder_count == 1
        Notification.objects.filter(pk=existing.pk).update(created_at=now - timedelta(days=2))
        _tick(monkeypatch, now + timedelta(minutes=5))
        assert _notices(post).count() == 2
        assert ApprovalReminder.objects.get(post=post, stage="review_deadline").reminder_count == 1
        assert ApprovalReminder.objects.get(post=post, stage="review_backup").reminder_count == 1

    def test_email_opt_out_is_respected_and_in_app_notice_remains(self, team, mailoutbox):
        NotificationPreference.objects.create(
            user=team.lead, event_type=EventType.APPROVAL_REMINDER, channel=Channel.EMAIL, is_enabled=False
        )
        post = _post(team)
        tasks.check_approval_reminders()
        notice = _notices(post).get()
        assert notice.shown_in_app and list(notice.deliveries.values_list("channel", flat=True)) == [Channel.IN_APP]
        assert not mailoutbox

    def test_no_valid_lead_uses_only_current_owner_or_manager_fallbacks(self, team):
        team.agency.lead = None
        team.agency.backup = None
        team.agency.save(update_fields=["lead", "backup"])
        post = _post(team, due_in=timedelta(minutes=20))
        tasks.check_approval_reminders()
        assert set(_notices(post).values_list("user_id", flat=True)) == {team.owner.pk, team.lead.pk, team.backup.pk}
        assert not _notices(post).filter(user__in=(team.author, team.client)).exists()

    def test_recurring_check_is_frequent_enough_for_the_backup_window(self):
        assert tasks.BACKUP_DEADLINE_WINDOW.total_seconds() / 2 >= tasks.APPROVAL_REMINDER_INTERVAL_SECONDS

    def test_registration_updates_an_existing_hourly_schedule_without_duplicating_it(self, team):
        name = "run_approval_reminders_cycle"
        Task.objects.filter(verbose_name=name).delete()
        tasks.run_approval_reminders_cycle(repeat=3600, verbose_name=name)
        original = Task.objects.get(verbose_name=name)
        ApprovalsConfig._register_tasks(sender=None)
        ApprovalsConfig._register_tasks(sender=None)
        current = Task.objects.get(verbose_name=name)
        assert current.pk == original.pk and current.repeat == tasks.APPROVAL_REMINDER_INTERVAL_SECONDS


@pytest.mark.django_db(transaction=True)
def test_overlapping_sweeps_create_one_notice_per_deadline_role(team, monkeypatch):
    post = _post(team, due_in=timedelta(minutes=20))
    barrier = Barrier(2)
    # No mail is sent from the test threads; persisted notifications still
    # exercise role idempotence, transactions and per-person alert caps.
    from apps.notifications import engine as notification_engine

    monkeypatch.setattr(notification_engine, "_dispatch", lambda delivery: None)

    def run():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            tasks.check_approval_reminders()
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        for future in futures:
            future.result(timeout=20)

    assert _notices(post).count() == 2
    assert set(_notices(post).values_list("user_id", flat=True)) == {team.lead.pk, team.backup.pk}
    assert post.platform_posts.get().status == "pending_review"
