"""A post sent back for changes at the client stage goes back to the team from its post page.

In a two-stage workspace (internal approval, then the client's) the brief counts as approved once
its post reaches the client (``services.sync_status``). When changes are then asked for, every
channel is back in the team's hands (``changes_requested``), so the post page must offer *Send it
back with notes* again, and must not call the post approved. Golden path 6 found the page saying
"Approved" with no way to send it back once the post page had been opened while the client had it.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.approvals import services as approval_services
from apps.approvals.actor import acting_as
from apps.composer.models import PlatformPost
from apps.studio import services
from apps.studio.models import StudioBrief
from apps.studio.tests.conftest import make_brief, run_all


def _url(name, world, **kwargs):
    return reverse(f"studio:{name}", kwargs={"workspace_id": world.workspace.id, **kwargs})


def _statuses(brief):
    return set(PlatformPost.objects.filter(post=brief.post).values_list("status", flat=True))


@pytest.fixture
def with_the_client(world, fake_team, client):
    """A post the owner approved internally, whose post page was opened while the client had it."""
    world.workspace.approval_workflow_mode = "required_internal_and_client"
    world.workspace.require_dashboard_approval = True
    world.workspace.save(update_fields=["approval_workflow_mode", "require_dashboard_approval"])
    brief = run_all(make_brief(world))
    with acting_as(world.owner):
        approval_services.approve_post(brief.post, world.owner, world.workspace)
    assert _statuses(brief) == {"pending_client"}
    client.force_login(world.owner)
    assert client.get(_url("detail", world, brief_id=brief.pk)).status_code == 200
    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.APPROVED
    return brief


def test_changes_asked_at_the_client_stage_put_the_post_back_in_the_teams_hands(
    client, world, fake_team, with_the_client
):
    brief = with_the_client
    with acting_as(world.owner):
        approval_services.request_changes(brief.post, world.owner, world.workspace, "Say Saturday, not weekends.")
    assert _statuses(brief) == {"changes_requested"}

    response = client.get(_url("detail", world, brief_id=brief.pk))

    assert response.status_code == 200
    html = response.content.decode()
    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.READY
    assert _url("request_changes", world, brief_id=brief.pk) in html
    assert "Pick a posting time on the Approvals page" not in html

    response = client.post(_url("request_changes", world, brief_id=brief.pk), {"feedback": "Lead with the visits."})

    assert response.status_code == 302
    brief.refresh_from_db()
    assert (brief.revision, brief.stage, brief.feedback) == (2, "copy", "Lead with the visits.")
    assert all(not pp.approved_fingerprint and pp.approved_by_id is None for pp in brief.post.platform_posts.all())


def test_a_post_the_client_still_has_stays_approved_and_closed(client, world, with_the_client):
    brief = with_the_client

    response = client.get(_url("detail", world, brief_id=brief.pk))

    html = response.content.decode()
    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.APPROVED
    assert _statuses(brief) == {"pending_client"}
    assert _url("request_changes", world, brief_id=brief.pk) not in html


@pytest.mark.parametrize("enforced", [True, False], ids=["dashboard-approval", "no-dashboard-approval"])
def test_an_approved_post_unscheduled_on_the_calendar_keeps_its_approval_and_stays_closed(
    client, world, fake_team, enforced
):
    """Unschedule moves a channel back to draft but keeps its approval: the brief is not sent back."""
    world.workspace.approval_workflow_mode = "required_internal"
    world.workspace.require_dashboard_approval = enforced
    world.workspace.save(update_fields=["approval_workflow_mode", "require_dashboard_approval"])
    brief = run_all(make_brief(world))
    with acting_as(world.owner):
        services.approve(brief, world.owner, publish_at=timezone.now() + timedelta(days=2))
    assert _statuses(brief) == {"scheduled"}
    client.force_login(world.owner)

    response = client.post(
        reverse("calendar:bulk_platform_action", kwargs={"workspace_id": world.workspace.id}),
        {"action": "draft", "platform_post_ids": [str(pp.pk) for pp in brief.post.platform_posts.all()]},
    )

    assert response.status_code == 200
    rows = list(brief.post.platform_posts.all())
    assert {pp.status for pp in rows} == {"draft"}
    if enforced:
        assert all(pp.approved_fingerprint and pp.approved_by_id == world.owner.pk for pp in rows)

    response = client.get(_url("detail", world, brief_id=brief.pk))

    assert response.status_code == 200
    html = response.content.decode()
    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.APPROVED
    assert _url("request_changes", world, brief_id=brief.pk) not in html
    assert not services.can_revise(brief)
