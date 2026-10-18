"""Photo attestations require current authority and follow the exact media used."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals import gate
from apps.composer.models import PlatformPost
from apps.media_library.models import MediaAsset
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.studio import guards, llm, pipeline, style, trust
from apps.studio.agents import art_director as real_art_director
from apps.studio.brand_defaults import ensure_profile
from apps.studio.models import StudioBrief
from apps.studio.tests.conftest import _result, copy_answer, design_answer, jpeg_bytes, make_brief, run_all
from apps.workspaces.models import Workspace


def attest(client, world, asset, *, user=None, project="Owner-identified Project Alpha"):
    client.force_login(user or world.owner)
    response = client.post(
        reverse("studio:trust", kwargs={"workspace_id": world.workspace.pk}),
        {"kind": "photo", "asset_id": str(asset.pk), "project": project, "photo_confirmed": "1"},
    )
    asset.refresh_from_db()
    return response


def test_photo_attestation_records_actual_human_file_and_project_without_claiming_external_truth(client, world, photo):
    asset = photo()
    assert attest(client, world, asset).status_code == 302
    status = trust.photo_status(asset)
    assert status["status"] == "verified" and status["verified_project"] == "Owner-identified Project Alpha"
    assert asset.verified_by_id == world.owner.pk and asset.verified_at <= timezone.now()
    assert asset.verified_asset_hash and "verified" in status["label"].lower()
    assert "independent" not in status["label"].lower()


@pytest.mark.parametrize(
    "source,tags",
    [("fal.ai", []), ("ai-studio", []), ("upload", ["ai"]), ("FAL.AI", []), (" fal.ai ", []), ("upload", ["AI"])],
)
def test_generated_photo_cannot_become_verified_property_evidence(client, world, photo, source, tags):
    asset = photo(source=source, tags=tags)
    response = attest(client, world, asset)
    assert response.status_code == 302
    assert asset.authenticity != "verified"
    status = trust.photo_status(asset)
    assert status["status"] == "illustrative" and status["verified_project"] == ""


@pytest.mark.parametrize("field", ["verifier", "date", "hash", "project", "future_date"])
def test_declared_verified_flag_without_valid_attestation_remains_unknown(world, photo, field):
    asset = photo(
        authenticity="verified", verified_by=world.owner, verified_at=timezone.now(), verified_project="Project Alpha"
    )
    asset.verified_asset_hash = trust.asset_stamp(asset)
    asset.save(update_fields=["verified_asset_hash"])
    if field == "verifier":
        asset.verified_by = None
    elif field == "date":
        asset.verified_at = None
    elif field == "hash":
        asset.verified_asset_hash = ""
    elif field == "project":
        asset.verified_project = ""
    else:
        asset.verified_at = timezone.now() + timedelta(days=1)
    assert trust.photo_status(asset)["status"] == "unknown"


def test_same_path_file_bytes_replaced_after_attestation_cannot_retain_verified_status(client, world, photo):
    asset = photo()
    assert attest(client, world, asset).status_code == 302
    previous_name = asset.file.name
    Path(asset.file.path).write_bytes(jpeg_bytes(color=(190, 20, 50)))
    asset.refresh_from_db()
    assert asset.file.name == previous_name
    assert trust.photo_status(asset)["status"] == "unknown"


@pytest.mark.parametrize("revocation", ["membership", "organization", "inactive", "role"])
def test_removed_photo_verifier_authority_stops_next_stage_and_ready_publication(
    client, world, fake_team, photo, revocation
):
    asset = photo()
    assert attest(client, world, asset).status_code == 302
    brief = run_all(make_brief(world, source_picture=asset))
    channel = PlatformPost.objects.get(post=brief.post)
    if revocation == "membership":
        WorkspaceMembership.objects.filter(user=world.owner, workspace=world.workspace).delete()
    elif revocation == "organization":
        OrgMembership.objects.filter(user=world.owner, organization=world.org).delete()
    elif revocation == "inactive":
        User.objects.filter(pk=world.owner.pk).update(is_active=False)
    else:
        WorkspaceMembership.objects.filter(user=world.owner, workspace=world.workspace).update(workspace_role="viewer")
    assert gate.publish_blocker(channel)
    assert trust.photo_status(MediaAsset.objects.get(pk=asset.pk))["status"] == "unknown"


def test_replacing_attested_photo_asset_with_foreign_organization_stops_paid_stage(client, world, fake_team, photo):
    asset = photo()
    assert attest(client, world, asset).status_code == 302
    brief = make_brief(world, source_picture=asset)
    pipeline.run_step(str(brief.pk), brief.revision, brief.stage)
    brief.refresh_from_db()
    MediaAsset.objects.filter(pk=asset.pk).update(organization=Organization.objects.create(name="Foreign agency"))
    pipeline.run_step(str(brief.pk), brief.revision, brief.stage)
    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.FAILED and fake_team.calls["copywriter"] == []


def test_missing_photo_entry_in_snapshot_cannot_hide_existing_source_photo(world, fake_team, photo):
    asset = photo()
    brief = make_brief(world, source_picture=asset)
    pipeline.run_step(str(brief.pk), brief.revision, brief.stage)
    brief.refresh_from_db()
    forged = {**brief.trust_snapshot, "photo": None}
    StudioBrief.objects.filter(pk=brief.pk).update(trust_snapshot=forged)
    pipeline.run_step(str(brief.pk), brief.revision, brief.stage)
    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.FAILED and fake_team.calls["copywriter"] == []


def test_unverified_generic_photo_is_allowed_with_honest_model_context(world, fake_team, photo, monkeypatch):
    asset = photo()
    assert trust.photo_status(asset)["status"] == "unknown"
    brief = make_brief(world, source_picture=asset)
    profile = ensure_profile(world.workspace)
    # Inspect the actual art-director request, while keeping the HTTP boundary fake.
    captured = {}

    def offline(**kwargs):
        captured.update(kwargs)
        return _result(design_answer())

    monkeypatch.setattr(llm, "run_agent", offline)
    pipeline.run_step(str(brief.pk), brief.revision, brief.stage)
    brief.refresh_from_db()
    concept = brief.chosen_concept
    real_art_director(
        brief,
        profile,
        concept,
        copy_answer().model_dump(),
        style.StyleReference(kind="brand", label="Brand"),
        source_picture=jpeg_bytes(),
    )
    text = "\n".join(block.get("text", "") for block in captured["content"] if block.get("type") == "text")
    assert "unverified" in text.lower() or "illustrative" in text.lower()
    assert "not proof" in text.lower() or "does not establish" in text.lower()


@pytest.mark.parametrize("scope", ["workspace", "organization", "type"])
def test_human_cannot_attest_photo_outside_current_image_scope(client, world, photo, scope):
    asset = photo()
    if scope == "workspace":
        asset.workspace = Workspace.objects.create(organization=world.org, name="Other brand")
    elif scope == "organization":
        asset.organization = Organization.objects.create(name="Other agency")
    else:
        asset.media_type = "video"
    asset.save()
    response = attest(client, world, asset)
    assert response.status_code == 404 and asset.authenticity != "verified"


def test_client_cannot_attest_a_property_photo_even_though_clients_approve_their_posts(client, world, photo):
    asset = photo()
    person = User.objects.create_user(
        email="photo-client@agency.test", password="test-pass", name="Client", tos_accepted_at=timezone.now()
    )
    OrgMembership.objects.create(user=person, organization=world.org)
    WorkspaceMembership.objects.create(user=person, workspace=world.workspace, workspace_role="client")
    assert attest(client, world, asset, user=person).status_code == 403
    assert asset.authenticity != "verified"


def test_worker_cannot_attest_photo_even_with_owner_cookie(client, world, photo):
    asset = photo()
    with guards.agent_work("adversarial photo attestation"), pytest.raises(guards.AgentMayNotApproveError):
        attest(client, world, asset)
    asset.refresh_from_db()
    assert asset.authenticity != "verified"


def test_malformed_photo_identifier_is_refused_without_server_error(client, world):
    client.force_login(world.owner)
    response = client.post(
        reverse("studio:trust", kwargs={"workspace_id": world.workspace.pk}),
        {"kind": "photo", "asset_id": "invalid-photo-identifier", "project": "Alpha", "photo_confirmed": "1"},
    )
    assert response.status_code in {400, 404}
