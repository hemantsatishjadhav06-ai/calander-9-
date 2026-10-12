"""Expiring human attestations at prompts, worker, handoff and publication boundaries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals import gate
from apps.composer.models import PlatformPost, Post
from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.publisher import engine as publisher
from apps.studio import guards, pipeline, prompts, trust
from apps.studio.brand_defaults import ensure_profile
from apps.studio.forms_trust import BrandClaimForm
from apps.studio.models import BrandClaim, StudioBrief
from apps.studio.tests.conftest import make_brief, run_all
from apps.workspaces.models import Workspace


def make_claim(world, **changes):
    fields = {
        "workspace": world.workspace,
        "category": "availability",
        "claim": "The owner confirmed two units are available as of the recorded source date.",
        "source_note": "Owner inventory sheet, checked today.",
        "verified_by": world.owner,
        "verified_at": timezone.now(),
        "valid_until": trust.local_date(world.workspace) + timedelta(days=7),
    }
    return BrandClaim.objects.create(**(fields | changes))


def _begin(world, fake_team):
    brief = make_brief(world)
    pipeline.run_step(str(brief.pk), brief.revision, brief.stage)
    brief.refresh_from_db()
    assert brief.stage == StudioBrief.Stage.COPY and len(fake_team.calls["strategist"]) == 1
    return brief


def _invalidate(world, claim, reason):
    if reason == "expiry":
        claim.valid_until = trust.local_date(world.workspace) - timedelta(days=1)
        claim.save(update_fields=["valid_until"])
    elif reason == "changed":
        claim.claim = "The inventory changed after the team prepared its idea."
        claim.save(update_fields=["claim"])
    elif reason == "retired":
        claim.is_active = False
        claim.save(update_fields=["is_active"])
    elif reason == "inactive_verifier":
        User.objects.filter(pk=world.owner.pk).update(is_active=False)
    elif reason == "membership_removed":
        WorkspaceMembership.objects.filter(user=world.owner, workspace=world.workspace).delete()
    elif reason == "org_removed":
        OrgMembership.objects.filter(user=world.owner, organization=world.org).delete()
    elif reason == "client_verifier":
        WorkspaceMembership.objects.filter(user=world.owner, workspace=world.workspace).update(workspace_role="client")
    elif reason == "custom_client_verifier":
        role = CustomRole.objects.create(
            organization=world.org, name="Client with custom approval permission", permissions={"approve_posts": True}
        )
        WorkspaceMembership.objects.filter(user=world.owner, workspace=world.workspace).update(
            workspace_role="client", custom_role=role
        )
    elif reason == "foreign_role":
        other = Organization.objects.create(name="Other agency")
        role = CustomRole.objects.create(
            organization=other, name="Foreign approver", permissions={"approve_posts": True}
        )
        WorkspaceMembership.objects.filter(user=world.owner, workspace=world.workspace).update(custom_role=role)
    else:
        raise AssertionError(reason)


@pytest.mark.parametrize(
    "reason",
    [
        "expiry",
        "changed",
        "retired",
        "inactive_verifier",
        "membership_removed",
        "org_removed",
        "client_verifier",
        "custom_client_verifier",
        "foreign_role",
    ],
)
def test_source_invalidation_stops_next_paid_stage_before_model_work(world, fake_team, reason):
    claim = make_claim(world)
    brief = _begin(world, fake_team)
    assert brief.trust_snapshot["claims"][0]["id"] == str(claim.pk)
    _invalidate(world, claim, reason)
    pipeline.run_step(str(brief.pk), brief.revision, brief.stage)
    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.FAILED
    assert "source" in brief.error.lower() or "claim" in brief.error.lower()
    assert fake_team.calls["copywriter"] == []
    assert not Post.objects.filter(studio_briefs=brief).exists()


def test_expired_claim_cannot_be_handed_off_even_when_pipeline_step_is_called_directly(world, fake_team):
    claim = make_claim(world)
    brief = make_brief(world)
    for _ in range(14):
        brief.refresh_from_db()
        if brief.stage == StudioBrief.Stage.HANDOFF:
            break
        pipeline.run_step(str(brief.pk), brief.revision, brief.stage)
    assert brief.stage == StudioBrief.Stage.HANDOFF
    _invalidate(world, claim, "expiry")
    with pytest.raises(pipeline.StudioError, match="claim|source"):
        pipeline.step_handoff(brief)
    assert not Post.objects.filter(studio_briefs=brief).exists()


@pytest.mark.parametrize("reason", ["expiry", "changed", "membership_removed"])
def test_current_claim_gate_blocks_actual_publisher_claim_before_platform_dispatch(
    world, fake_team, monkeypatch, reason
):
    claim = make_claim(world)
    brief = run_all(make_brief(world))
    channel = PlatformPost.objects.get(post=brief.post)
    PlatformPost.objects.filter(pk=channel.pk).update(
        status="scheduled", scheduled_at=timezone.now() - timedelta(seconds=1)
    )
    channel.refresh_from_db()
    _invalidate(world, claim, reason)
    monkeypatch.setattr(
        publisher.PublishEngine,
        "_publish_platform_post",
        lambda *_args, **_kwargs: pytest.fail("Stale facts reached platform dispatch"),
    )
    assert gate.publish_blocker(channel)
    assert not publisher.PublishEngine()._publish_post_group(brief.post, [channel])
    channel.refresh_from_db()
    assert channel.status != "publishing" and channel.platform_post_id == ""


def test_legacy_facts_and_unattested_claims_are_absent_from_model_fact_context(world):
    profile = ensure_profile(world.workspace)
    profile.facts = "LEGACY-COMMERCIAL: guaranteed title and a secret unpublished discount."
    profile.save(update_fields=["facts"])
    make_claim(world, claim="UNATTESTED-IMPORT", verified_by=None, verified_at=None)
    block = prompts.brand_block(profile)
    assert "LEGACY-COMMERCIAL" not in block and "UNATTESTED-IMPORT" not in block
    assert "unverified" in block.lower()


def test_expiry_uses_kolkata_midnight_instead_of_utc_date(world, monkeypatch):
    boundary = datetime(2026, 10, 31, 18, 30, tzinfo=UTC)
    claim = make_claim(world, verified_at=boundary - timedelta(days=1), valid_until=boundary.date())
    monkeypatch.setattr(trust.timezone, "now", lambda: boundary - timedelta(microseconds=1))
    assert trust.current_claims(world.workspace).filter(pk=claim.pk).exists()
    monkeypatch.setattr(trust.timezone, "now", lambda: boundary)
    assert not trust.current_claims(world.workspace).filter(pk=claim.pk).exists()


@pytest.mark.parametrize("missing", ["verifier", "date", "source", "future_date"])
def test_fake_verification_fields_do_not_establish_current_claim_authority(world, missing):
    changes = {
        "verifier": {"verified_by": None},
        "date": {"verified_at": None},
        "source": {"source_note": "", "source_url": ""},
        "future_date": {"verified_at": timezone.now() + timedelta(days=1)},
    }
    claim = make_claim(world, **changes[missing])
    assert not trust.current_claims(world.workspace).filter(pk=claim.pk).exists()


@pytest.mark.parametrize(
    "bad_snapshot",
    [
        [],
        "not a snapshot",
        {},
        {"revision": 999, "claims": [], "photo": None},
        {"revision": 1},
        {"revision": 1, "claims": None, "photo": None},
        {"revision": 1, "claims": [None], "photo": None},
        {"revision": 1, "claims": [{"id": [], "stamp": "bad"}], "photo": None},
        {"revision": 1, "claims": [], "photo": {"id": "not-a-uuid"}},
        {"revision": 1, "claims": [], "photo": "not-an-object"},
    ],
)
def test_corrupt_snapshot_fails_closed_without_recapturing_or_paying_for_next_stage(world, fake_team, bad_snapshot):
    make_claim(world)
    brief = _begin(world, fake_team)
    StudioBrief.objects.filter(pk=brief.pk).update(trust_snapshot=bad_snapshot)
    pipeline.run_step(str(brief.pk), brief.revision, brief.stage)
    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.FAILED
    assert fake_team.calls["copywriter"] == []


def _claim_payload(world):
    return {
        "category": "availability",
        "claim": "One verified unit remains.",
        "source_note": "Owner inventory document",
        "valid_until": str(trust.local_date(world.workspace) + timedelta(days=1)),
        "confirmed": "on",
    }


@pytest.mark.parametrize("bad", ["unchecked", "no_source", "expired", "credentials"])
def test_claim_form_requires_human_confirmation_source_and_current_expiry(world, bad):
    payload = _claim_payload(world)
    if bad == "unchecked":
        payload.pop("confirmed")
    elif bad == "no_source":
        payload["source_note"] = ""
    elif bad == "expired":
        payload["valid_until"] = str(trust.local_date(world.workspace) - timedelta(days=1))
    else:
        payload["source_url"] = "https://secret-user:secret-key@example.com/source"
    assert not BrandClaimForm(payload, workspace=world.workspace).is_valid()


def test_human_verification_write_records_authenticated_identity_and_exact_source(client, world):
    client.force_login(world.owner)
    response = client.post(reverse("studio:trust", kwargs={"workspace_id": world.workspace.pk}), _claim_payload(world))
    assert response.status_code == 302
    claim = BrandClaim.objects.get(workspace=world.workspace)
    assert claim.verified_by_id == world.owner.pk and claim.verified_at <= timezone.now()
    assert claim.source_note == "Owner inventory document" and claim.is_active


@pytest.mark.parametrize("role", ["viewer", "client", "foreign_role", "client_facing"])
def test_untrusted_verification_actor_cannot_create_claim(client, world, role):
    if role == "viewer":
        user = world.viewer
    else:
        user = User.objects.create_user(
            email=f"{role}@claim.test", password="test-pass", name=role, tos_accepted_at=timezone.now()
        )
        OrgMembership.objects.create(user=user, organization=world.org)
        custom = None
        if role == "foreign_role":
            custom = CustomRole.objects.create(
                organization=Organization.objects.create(name="Other"),
                name="Foreign",
                permissions={"approve_posts": True},
            )
        elif role == "client_facing":
            custom = CustomRole.objects.create(
                organization=world.org,
                name="Customer approver",
                permissions={"client_facing": True, "approve_posts": True},
            )
        WorkspaceMembership.objects.create(
            user=user,
            workspace=world.workspace,
            workspace_role="client" if role in {"client", "client_facing"} else "editor",
            custom_role=custom,
        )
    client.force_login(user)
    response = client.post(reverse("studio:trust", kwargs={"workspace_id": world.workspace.pk}), _claim_payload(world))
    assert response.status_code in {403, 404}
    assert not BrandClaim.objects.filter(workspace=world.workspace).exists()


def test_agent_context_cannot_attest_even_with_a_human_session_cookie(client, world):
    client.force_login(world.owner)
    with guards.agent_work("adversarial fact attestation"), pytest.raises(guards.AgentMayNotApproveError):
        client.post(reverse("studio:trust", kwargs={"workspace_id": world.workspace.pk}), _claim_payload(world))
    assert not BrandClaim.objects.filter(workspace=world.workspace).exists()


@pytest.mark.parametrize("revocation", ["organization", "workspace", "inactive"])
def test_verification_write_rechecks_authority_after_initial_page_permission(client, world, monkeypatch, revocation):
    from apps.studio import views_trust

    client.force_login(world.owner)
    original = views_trust._can_edit_brand

    def change_after_initial_permission(request):
        permitted = original(request)
        if revocation == "organization":
            OrgMembership.objects.filter(user=world.owner, organization=world.org).delete()
        elif revocation == "workspace":
            WorkspaceMembership.objects.filter(user=world.owner, workspace=world.workspace).delete()
        else:
            User.objects.filter(pk=world.owner.pk).update(is_active=False)
        return permitted

    monkeypatch.setattr(views_trust, "_can_edit_brand", change_after_initial_permission)
    response = client.post(reverse("studio:trust", kwargs={"workspace_id": world.workspace.pk}), _claim_payload(world))
    assert response.status_code in {403, 404}
    assert not BrandClaim.objects.filter(workspace=world.workspace).exists()


def test_foreign_claim_edit_cannot_change_another_workspace(client, world):
    other = Workspace.objects.create(organization=world.org, name="Other brand")
    claim = make_claim(world, workspace=other)
    before = claim.claim
    client.force_login(world.owner)
    payload = _claim_payload(world) | {"claim_id": str(claim.pk)}
    response = client.post(reverse("studio:trust", kwargs={"workspace_id": world.workspace.pk}), payload)
    claim.refresh_from_db()
    assert response.status_code == 404 and claim.claim == before


def test_malformed_claim_identifier_is_refused_without_server_error_or_write(client, world):
    client.force_login(world.owner)
    response = client.post(
        reverse("studio:trust", kwargs={"workspace_id": world.workspace.pk}),
        _claim_payload(world) | {"claim_id": "invalid-claim-identifier"},
    )
    assert response.status_code in {400, 404}
    assert not BrandClaim.objects.filter(workspace=world.workspace).exists()


def test_workspace_organization_move_during_permission_check_cannot_authorize_old_tenant_write(
    client, world, monkeypatch
):
    from apps.studio import views_trust

    other = Organization.objects.create(name="New tenant")
    client.force_login(world.owner)
    original = views_trust._can_edit_brand

    def move_after_initial_permission(request):
        permitted = original(request)
        Workspace.objects.filter(pk=world.workspace.pk).update(organization=other)
        return permitted

    monkeypatch.setattr(views_trust, "_can_edit_brand", move_after_initial_permission)
    response = client.post(reverse("studio:trust", kwargs={"workspace_id": world.workspace.pk}), _claim_payload(world))
    assert response.status_code in {403, 404}
    assert not BrandClaim.objects.filter(workspace_id=world.workspace.pk).exists()
