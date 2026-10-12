"""Manual campaign recording is scoped, human-authorized and repeat-submit safe."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.approvals.actor import API, acting_as
from apps.composer.models import PlatformPost, Post
from apps.members.models import WorkspaceMembership
from apps.studio import outcomes
from apps.studio.guards import AgentMayNotApproveError, agent_work
from apps.studio.models import CampaignOutcome
from apps.workspaces.models import Workspace


def _url(world):
    return reverse("studio:outcomes", kwargs={"workspace_id": world.workspace.pk})


def _data(world, **changes):
    return {
        "campaign_name": "Neopolis site visits",
        "occurred_on": timezone.now().date(),
        "kind": "enquiry",
        "count": 1,
        **changes,
    }


def test_staff_records_a_confirmed_enquiry_once_through_the_dashboard(world, client):
    client.force_login(world.editor)
    page = client.get(_url(world))
    assert page.status_code == 200
    token = page.context["form"].initial["submission_token"]
    data = {**_data(world), "submission_token": token}
    assert client.post(_url(world), data).status_code == 302
    assert client.post(_url(world), data).status_code == 302
    assert CampaignOutcome.objects.count() == 1
    entry = CampaignOutcome.objects.get()
    assert entry.workspace_id == world.workspace.pk and entry.recorded_by_id == world.editor.pk
    page = client.get(_url(world))
    assert page.context["totals"]["enquiry"] == 1
    assert b"no specific post attribution" in page.content


def test_outcome_can_be_attributed_only_to_a_scoped_approved_or_published_post(world, client):
    approved = Post.objects.create(workspace=world.workspace, caption="Approved campaign")
    PlatformPost.objects.create(post=approved, social_account=world.linkedin, status="approved")
    draft = Post.objects.create(workspace=world.workspace, caption="Not reviewed")
    PlatformPost.objects.create(post=draft, social_account=world.linkedin, status="draft")
    other = Workspace.objects.create(organization=world.org, name="More Space")
    foreign = Post.objects.create(workspace=other, caption="FOREIGN-CAMPAIGN")
    PlatformPost.objects.create(
        post=foreign, social_account=world.linkedin, status="published", published_at=timezone.now()
    )
    client.force_login(world.editor)
    page = client.get(_url(world))
    assert "FOREIGN" not in page.content.decode()
    token = page.context["form"].initial["submission_token"]
    for post in [draft, foreign]:
        response = client.post(_url(world), {**_data(world), "submission_token": token, "post": post.pk})
        assert response.status_code == 400
        assert not CampaignOutcome.objects.exists()
    assert client.post(_url(world), {**_data(world), "submission_token": token, "post": approved.pk}).status_code == 302
    assert CampaignOutcome.objects.get().post_id == approved.pk


@pytest.mark.parametrize(
    "changes",
    [
        {"count": 0},
        {"count": -1},
        {"occurred_on": timezone.now().date() + timedelta(days=2)},
        {"kind": "sale-guaranteed"},
    ],
)
def test_invalid_or_future_outcome_is_not_recorded(world, client, changes):
    client.force_login(world.editor)
    token = client.get(_url(world)).context["form"].initial["submission_token"]
    assert client.post(_url(world), {**_data(world, **changes), "submission_token": token}).status_code == 400
    assert not CampaignOutcome.objects.exists()


def test_read_only_staff_can_read_aggregate_results_but_cannot_record(world, client):
    client.force_login(world.viewer)
    assert client.get(_url(world)).status_code == 200
    assert client.post(_url(world), _data(world)).status_code == 403
    assert not CampaignOutcome.objects.exists()


def test_client_and_outsider_cannot_access_staff_campaign_outcomes(world, client):
    buyer = world.owner.__class__.objects.create_user(
        email="buyer-outcomes@example.com", password="pw", name="Buyer", tos_accepted_at=timezone.now()
    )
    WorkspaceMembership.objects.create(workspace=world.workspace, user=buyer, workspace_role="client")
    for user in [buyer, world.outsider]:
        client.force_login(user)
        assert client.get(_url(world)).status_code in {403, 404}
        assert client.post(_url(world), _data(world)).status_code in {403, 404}


def test_worker_agent_and_api_actor_cannot_record_outcomes_even_with_a_valid_token(world):
    token = outcomes.submission_token(world.workspace, world.editor)
    with acting_as(world.editor, API), pytest.raises(ValueError, match="dashboard"):
        outcomes.record(world.workspace, world.editor, token=token, **_data(world))
    with acting_as(world.editor), agent_work("test"), pytest.raises(AgentMayNotApproveError):
        outcomes.record(world.workspace, world.editor, token=token, **_data(world))
    assert not CampaignOutcome.objects.exists()


@pytest.mark.parametrize("revocation", ["membership", "user", "workspace", "post"])
def test_current_authorization_and_post_state_are_rechecked_at_record_time(world, revocation):
    post = Post.objects.create(workspace=world.workspace, caption="Approved")
    pp = PlatformPost.objects.create(post=post, social_account=world.linkedin, status="approved")
    token = outcomes.submission_token(world.workspace, world.editor)
    if revocation == "membership":
        WorkspaceMembership.objects.filter(workspace=world.workspace, user=world.editor).delete()
    elif revocation == "user":
        world.editor.__class__.objects.filter(pk=world.editor.pk).update(is_active=False)
    elif revocation == "workspace":
        Workspace.objects.filter(pk=world.workspace.pk).update(is_archived=True)
    else:
        PlatformPost.objects.filter(pk=pp.pk).update(status="pending_review")
    with acting_as(world.editor), pytest.raises(ValueError):
        outcomes.record(world.workspace, world.editor, token=token, post=post, **_data(world))
    assert not CampaignOutcome.objects.exists()


def test_submission_token_cannot_cross_a_user_or_workspace_or_change_an_existing_entry(world):
    token = outcomes.submission_token(world.workspace, world.editor)
    with acting_as(world.owner), pytest.raises(ValueError, match="another workspace"):
        outcomes.record(world.workspace, world.owner, token=token, **_data(world))
    other = Workspace.objects.create(organization=world.org, name="More Space")
    with acting_as(world.editor), pytest.raises(ValueError, match="another workspace"):
        outcomes.record(other, world.editor, token=token, **_data(world))
    with acting_as(world.editor):
        outcomes.record(world.workspace, world.editor, token=token, **_data(world))
        with pytest.raises(ValueError, match="different values"):
            outcomes.record(world.workspace, world.editor, token=token, **_data(world, count=20))
    assert CampaignOutcome.objects.get().count == 1
