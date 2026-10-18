"""Expiry and human reconciliation stay scoped and never send a second post."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals.actor import API, PORTAL, acting_as
from apps.approvals.models import ApprovalAction
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.publisher import delivery
from apps.publisher.engine import PublishEngine
from apps.settings_manager.models import WorkspaceSetting
from apps.social_accounts.models import SocialAccount
from apps.studio import guards
from apps.workspaces.models import Workspace


@pytest.fixture
def case(db):
    org = Organization.objects.create(name="Neopolis delivery controls")
    ws = Workspace.objects.create(
        organization=org, name="Neopolis", timezone="Asia/Kolkata", require_dashboard_approval=True
    )
    owner = User.objects.create_user(
        email="delivery-owner@example.test", password="local-test-only", name="Owner", tos_accepted_at=timezone.now()
    )
    OrgMembership.objects.create(user=owner, organization=org, org_role="owner")
    member = WorkspaceMembership.objects.create(user=owner, workspace=ws, workspace_role="owner")
    account = SocialAccount.objects.create(
        workspace=ws,
        platform="facebook",
        account_platform_id="585141221346435",
        account_name="Neopolis Infra",
        oauth_access_token="OFFLINE-TOKEN",
    )

    def make(*, age=timedelta(minutes=2), unknown=False):
        when = timezone.now() - age
        post = Post.objects.create(
            workspace=ws,
            author=owner,
            caption="Book a Neopolis site visit",
            scheduled_at=when,
            proposed_publish_at=when,
        )
        pp = PlatformPost.objects.create(post=post, social_account=account, status="pending_review", scheduled_at=when)
        with acting_as(owner):
            pp.transition_to("approved")
            pp.save(update_fields=PlatformPost.TRANSITION_FIELDS)
        PlatformPost.objects.filter(pk=pp.pk).update(status="publishing" if unknown else "scheduled")
        pp.refresh_from_db()
        if unknown:
            with delivery.delivery_write():
                evidence = delivery.snapshot(pp, kind="submitting")
                PlatformPost.objects.filter(pk=pp.pk).update(platform_extra={delivery.STATE_KEY: evidence})
            delivery.mark(pp, kind="unknown", reason="Check the account before another attempt.")
            pp.refresh_from_db()
        return pp

    return SimpleNamespace(org=org, ws=ws, owner=owner, member=member, account=account, make=make)


def form(pp):
    evidence = delivery.state(pp)
    return {
        "confirmed": True,
        "expected_attempt_id": evidence["attempt_id"],
        "expected_fingerprint": evidence["content_fingerprint"],
    }


def existing(case, pp, **changes):
    values = {
        "native_post_id": "900123",
        "url": "https://www.facebook.com/585141221346435/posts/900123",
        **form(pp),
        **changes,
    }
    with acting_as(case.owner):
        return delivery.reconcile_existing(pp.pk, case.ws, case.owner, **values)


def absent(case, pp, **changes):
    values = {"reason": "Inspected the intended account; this post is absent.", **form(pp), **changes}
    with acting_as(case.owner):
        return delivery.checked_absent(pp.pk, case.ws, case.owner, **values)


def test_old_approved_post_is_held_without_a_platform_call(case):
    pp = case.make(age=timedelta(days=3))
    with patch.object(PublishEngine, "_dispatch_to_provider") as send:
        PublishEngine()._publish_post_group(pp.post, [pp])
    send.assert_not_called()
    pp.refresh_from_db()
    assert pp.status == "failed" and delivery.state(pp)["kind"] == "expired"
    assert ApprovalAction.objects.filter(platform_post=pp, action="publish_blocked").exists()
    assert delivery.has_unresolved_holds(pp.post)


def test_workspace_shorter_lateness_is_honored(case):
    WorkspaceSetting.objects.create(workspace=case.ws, key=delivery.LATENESS_KEY, value=60)
    pp = case.make(age=timedelta(minutes=2))
    with patch.object(PublishEngine, "_dispatch_to_provider") as send:
        PublishEngine()._publish_post_group(pp.post, [pp])
    send.assert_not_called()
    assert delivery.state(pp)["kind"] == "expired"


@pytest.mark.parametrize(("value", "expected"), [(0, 60), (10**9, 604800), (True, 86400), ("invalid", 86400)])
def test_invalid_or_extreme_lateness_cannot_disable_safety(case, value, expected):
    WorkspaceSetting.objects.create(workspace=case.ws, key=delivery.LATENESS_KEY, value=value)
    assert delivery.max_lateness_seconds(case.ws) == expected


def test_unknown_marker_holds_even_a_forced_generic_retry(case):
    pp = case.make(unknown=True)
    PlatformPost.objects.filter(pk=pp.pk).update(
        status="scheduled", retry_count=1, next_retry_at=timezone.now() - timedelta(minutes=1)
    )
    with patch.object(PublishEngine, "_dispatch_to_provider") as send:
        PublishEngine().poll_and_publish()
        PublishEngine().poll_and_publish()
    send.assert_not_called()
    pp.refresh_from_db()
    assert pp.status == "failed" and delivery.state(pp)["kind"] == "unknown"


def test_parent_hold_survives_forced_local_marker_removal(case):
    pp = case.make(unknown=True)
    with delivery.delivery_write():
        PlatformPost.objects.filter(pk=pp.pk).update(platform_extra={}, status="scheduled")
    pp.refresh_from_db()
    assert delivery.state(pp)["kind"] == "unknown"
    with patch.object(PublishEngine, "_dispatch_to_provider") as send:
        PublishEngine().poll_and_publish()
    send.assert_not_called()


def test_reconcile_records_human_attestation_and_never_calls_provider(case):
    pp = case.make(unknown=True)
    with patch.object(PublishEngine, "_dispatch_to_provider") as send:
        recorded = existing(case, pp)
        PublishEngine().poll_and_publish()
    send.assert_not_called()
    assert recorded.status == "published" and recorded.platform_post_id == "900123"
    assert delivery.state(recorded)["verification"] == "human_attestation"
    assert not delivery.has_unresolved_holds(recorded.post)
    audit = ApprovalAction.objects.get(platform_post=pp, action="delivery_reconciled")
    assert audit.user_id == case.owner.pk and audit.channel == "dashboard"


def test_checked_absent_returns_for_new_approval_and_cannot_auto_send(case):
    pp = case.make(unknown=True)
    returned = absent(case, pp)
    assert returned.status == "pending_review" and returned.approved_fingerprint == ""
    assert returned.scheduled_at is None and returned.approved_publish_at is None
    assert not delivery.has_unresolved_holds(returned.post)
    assert ApprovalAction.objects.filter(platform_post=pp, action="delivery_checked").exists()
    with pytest.raises(ValueError):
        returned.transition_to("scheduled")


def test_expired_post_can_return_for_review_but_not_be_marked_published(case):
    pp = case.make(age=timedelta(days=2))
    PublishEngine()._publish_post_group(pp.post, [pp])
    pp.refresh_from_db()
    with pytest.raises(delivery.DeliveryActionError, match="expired"):
        existing(case, pp)
    assert absent(case, pp).status == "pending_review"


@pytest.mark.parametrize("role", ["editor", "viewer", "client"])
def test_current_non_approver_roles_cannot_reconcile(case, role):
    pp = case.make(unknown=True)
    WorkspaceMembership.objects.filter(pk=case.member.pk).update(workspace_role=role)
    with pytest.raises(PermissionDenied):
        existing(case, pp)


@pytest.mark.parametrize("channel", [API, PORTAL])
def test_external_channels_cannot_claim_human_reconciliation(case, channel):
    pp = case.make(unknown=True)
    with acting_as(case.owner, channel), pytest.raises(PermissionDenied):
        delivery.reconcile_existing(
            pp.pk,
            case.ws,
            case.owner,
            native_post_id="900123",
            url="https://www.facebook.com/585141221346435/posts/900123",
            **form(pp),
        )


def test_agents_cannot_reconcile_a_post(case):
    pp = case.make(unknown=True)
    with guards.agent_work("test"), pytest.raises(guards.AgentMayNotApproveError):
        existing(case, pp)


def test_deactivated_user_cannot_reconcile(case):
    pp = case.make(unknown=True)
    User.objects.filter(pk=case.owner.pk).update(is_active=False)
    with pytest.raises(PermissionDenied):
        existing(case, pp)


def test_foreign_workspace_does_not_disclose_or_update_delivery(case):
    pp = case.make(unknown=True)
    other = Workspace.objects.create(organization=case.org, name="More Space")
    WorkspaceMembership.objects.create(user=case.owner, workspace=other, workspace_role="owner")
    with acting_as(case.owner), pytest.raises(delivery.DeliveryActionError):
        delivery.reconcile_existing(
            pp.pk,
            other,
            case.owner,
            native_post_id="900123",
            url="https://www.facebook.com/585141221346435/posts/900123",
            **form(pp),
        )
    pp.refresh_from_db()
    assert pp.status == "failed"


@pytest.mark.parametrize("change", ["content", "native", "revision"])
def test_changed_attempt_content_destination_or_revision_cannot_be_reconciled(case, change):
    pp = case.make(unknown=True)
    if change == "content":
        Post.objects.filter(pk=pp.post_id).update(caption="Changed campaign")
    elif change == "native":
        SocialAccount.objects.filter(pk=pp.social_account_id).update(account_platform_id="different-native-account")
    else:
        from apps.composer.models import PostVersion

        PostVersion.objects.create(post=pp.post, version_number=99, snapshot={})
    with pytest.raises(delivery.DeliveryActionError, match="changed"):
        existing(case, pp)


def test_stale_case_form_cannot_reconcile_new_evidence(case):
    pp = case.make(unknown=True)
    with pytest.raises(delivery.DeliveryActionError, match="changed"):
        existing(case, pp, expected_attempt_id="stale-case")


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://evil.example/post/1",
        "https://user:password@www.facebook.com/post/1",
        "https://www.facebook.com/post/1?access_token=private",
        "https://[",
    ],
)
def test_unsafe_or_credential_bearing_post_links_are_rejected(case, url):
    pp = case.make(unknown=True)
    with pytest.raises(delivery.DeliveryActionError):
        existing(case, pp, url=url)


def test_double_reconcile_cannot_create_a_second_audit_decision(case):
    pp = case.make(unknown=True)
    evidence_form = form(pp)
    existing(case, pp)
    with acting_as(case.owner), pytest.raises(delivery.DeliveryActionError, match="resolved"):
        delivery.checked_absent(pp.pk, case.ws, case.owner, reason="Checked but stale decision", **evidence_form)
    assert ApprovalAction.objects.filter(platform_post=pp, action="delivery_reconciled").count() == 1


def test_csrf_protects_the_human_inspection_endpoint(case, client):
    from django.test import Client

    pp = case.make(unknown=True)
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(case.owner)
    endpoint = reverse(
        "studio:publisher_delivery:reconcile_existing", kwargs={"workspace_id": case.ws.pk, "platform_post_id": pp.pk}
    )
    assert (
        browser.post(
            endpoint,
            {
                "confirmed": "1",
                "native_post_id": "900123",
                "url": "https://www.facebook.com/585141221346435/posts/900123",
            },
        ).status_code
        == 403
    )
