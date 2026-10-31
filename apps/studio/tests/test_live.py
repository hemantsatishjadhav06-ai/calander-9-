"""The live team view (apps.studio.live and the Team tab): what it counts, draws and refuses to show."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.common.models import TaskHeartbeat
from apps.composer.models import PlatformPost, Post
from apps.members.models import WorkspaceMembership
from apps.studio import autopilot, dashboard, engine, live, team
from apps.studio.models import AgencyJob, AgencySettings, AgentRun, Conversation, Routine, StudioBrief
from apps.workspaces.models import Workspace

TASKS = (
    "apps.publisher.tasks.run_publish_cycle",
    "apps.studio.tasks.run_agency_cycle",
    "apps.publisher.tasks.confirm_pending_publishes",
)


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()
    yield
    cache.clear()


def _url(name, world, **kwargs):
    return reverse(name, kwargs={"workspace_id": world.workspace.id, **kwargs})


def _brief(workspace, **fields):
    fields.setdefault("idea", "Saturday site visit, free parking")
    return StudioBrief.objects.create(workspace=workspace, **fields)


def _job(workspace, kind, **fields):
    return AgencyJob.objects.create(workspace=workspace, kind=kind, **fields)


def _run(agent, *, brief=None, job=None, started_at=None, status=AgentRun.Status.SUCCEEDED, summary=""):
    return AgentRun.objects.create(
        brief=brief,
        job=job,
        agent=agent,
        status=status,
        summary=summary,
        started_at=started_at or timezone.now(),
    )


def _agent(snapshot, slug):
    for department in snapshot["departments"]:
        for agent in department["agents"]:
            if agent["slug"] == slug:
                return agent
    raise AssertionError(slug)


def _beat(now, *, ages=(5, 5, 5)):
    for name, age in zip(TASKS, ages, strict=True):
        TaskHeartbeat.objects.update_or_create(
            task_name=name,
            defaults={"state": "ok", "last_success_at": now - timedelta(seconds=age), "last_started_at": now},
        )


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------


def test_an_idle_team(world):
    snap = live.snapshot(world.workspace, now=timezone.now())

    assert snap["counts"] == {
        "working": 0,
        "queued": 0,
        "done_today": 0,
        "needs_you": 0,
        "approvals": 0,
        "stopped_tasks": 0,
        "posts_ready_24h": 0,
    }
    assert snap["tracks"] == [] and snap["busiest"] is None
    assert snap["agents"] == {"working": 0, "stopped": 0, "idle": len(team.AGENTS)}
    assert snap["idle_text"].startswith("Nothing is running right now.")
    assert snap["activity"]["total"] == 0 and len(snap["activity"]["hours"]) == 24
    assert snap["upcoming"]["events"] == [] and snap["recent"] == [] and snap["receipt"] is None
    assert [d["name"] for d in snap["departments"]] == [d.name for d in team.DEPARTMENTS]


def test_a_brief_mid_pipeline_shows_the_working_step_and_agent(world):
    now = timezone.now()
    brief = _brief(
        world.workspace,
        status=StudioBrief.Status.WORKING,
        stage=StudioBrief.Stage.COPY,
        started_at=now - timedelta(minutes=4),
    )
    brief.social_accounts.add(world.linkedin)
    _run("strategist", brief=brief, started_at=now - timedelta(minutes=3), summary="Proposed three angles.")
    _run("copywriter", brief=brief, started_at=now - timedelta(seconds=40), status=AgentRun.Status.RUNNING)

    snap = live.snapshot(world.workspace, now=now)

    (track,) = snap["tracks"]
    assert track["kind"] == "post" and track["status"] == "working"
    assert [(s["label"], s["state"]) for s in track["stages"]] == [
        ("Brief", "done"),
        ("Angles", "done"),
        ("Copy", "working"),
        ("Design", "waiting"),
        ("Check", "waiting"),
        ("For you", "waiting"),
    ]
    assert track["agent"]["slug"] == "copywriter"
    assert track["doing"] == "Copywriter is writing the caption"
    assert track["step_text"] == "Step 3 of 6: Copy, working"
    assert track["elapsed_text"] == "4 min"
    assert track["platforms"] == [world.linkedin.get_platform_display()]
    assert track["url"] == _url("studio:detail", world, brief_id=brief.id)
    assert snap["counts"]["working"] == 1 and snap["busiest"]["key"] == track["key"]
    assert _agent(snap, "copywriter")["state"] == "working"
    assert _agent(snap, "strategist")["state"] == "idle"
    assert _agent(snap, "strategist")["last_text"] == "Proposed three angles."
    assert snap["agents"]["working"] == 1


def test_the_picture_stage_names_whoever_is_mid_turn(world):
    now = timezone.now()
    brief = _brief(world.workspace, status=StudioBrief.Status.WORKING, stage=StudioBrief.Stage.PICTURE)
    first = live.snapshot(world.workspace, now=now)["tracks"][0]
    assert first["agent"]["slug"] == "prompt_engineer" and first["current_label"] == "Design"

    _run("illustrator", brief=brief, started_at=now - timedelta(seconds=10), status=AgentRun.Status.RUNNING)
    second = live.snapshot(world.workspace, now=now)["tracks"][0]
    assert second["agent"]["slug"] == "illustrator" and second["doing"] == "Illustrator is painting the picture"


def test_a_queued_brief_waits_its_turn(world):
    _brief(world.workspace, status=StudioBrief.Status.QUEUED, stage=StudioBrief.Stage.STRATEGY)

    snap = live.snapshot(world.workspace, now=timezone.now())

    (track,) = snap["tracks"]
    assert track["status"] == "queued" and track["status_word"] == "Queued"
    assert [s["state"] for s in track["stages"]] == ["done", "waiting", "waiting", "waiting", "waiting", "waiting"]
    assert "Waiting its turn" in track["doing"]
    assert snap["counts"]["queued"] == 1 and snap["counts"]["working"] == 0


def test_jobs_of_other_kinds_use_their_own_stages(world):
    now = timezone.now()
    article = _job(
        world.workspace,
        "blog",
        title="Kokapet buyer's guide",
        status=AgencyJob.Status.WORKING,
        stage="write",
        started_at=now - timedelta(minutes=12),
    )
    _run("blog_writer", job=article, started_at=now - timedelta(minutes=1), status=AgentRun.Status.RUNNING)
    _job(world.workspace, "plan", title="Monday plan", status=AgencyJob.Status.QUEUED)
    _job(world.workspace, "report", status=AgencyJob.Status.QUEUED, error=autopilot.AUTOPILOT_PAUSED)

    snap = live.snapshot(world.workspace, now=now)
    by_kind = {track["kind"]: track for track in snap["tracks"]}

    blog = by_kind["blog"]
    assert blog["status"] == "working" and blog["title"] == "Kokapet buyer's guide"
    assert [s["label"] for s in blog["stages"]][:3] == ["Research", "Outline", "Writing"]
    assert [s["state"] for s in blog["stages"]][:4] == ["done", "done", "working", "waiting"]
    assert blog["agent"]["slug"] == "blog_writer" and blog["long"] is True
    assert blog["url"] == _url("studio:job", world, job_id=article.id)

    plan = by_kind["plan"]
    assert plan["status"] == "queued" and plan["stages"][0] == {"label": "Read results", "state": "waiting"}

    report = by_kind["report"]
    assert report["status"] == "paused" and report["status_word"] == "Paused: autopilot is off"
    assert report["policy_url"] == _url("studio:autopilot", world)
    assert snap["counts"]["working"] == 1 and snap["counts"]["queued"] == 2
    assert snap["tracks"][0]["kind"] == "blog"  # working first


def test_failed_paused_and_interrupted_tasks_count_in_needs_you(world):
    now = timezone.now()
    _job(world.workspace, "report", status=AgencyJob.Status.FAILED, error="Boom.")
    _job(world.workspace, "plan", status=AgencyJob.Status.FAILED, error=f"It {engine.INTERRUPTED_MARKER}.")
    _job(
        world.workspace,
        "learn",
        status=AgencyJob.Status.CANCELLED,
        state={"_opendots_control": {"paused": True}},
    )
    _job(world.workspace, "seo", status=AgencyJob.Status.CANCELLED)  # stopped by a person: nothing to look at
    old = _job(world.workspace, "report", status=AgencyJob.Status.FAILED, error="Long ago.")
    AgencyJob.objects.filter(pk=old.pk).update(updated_at=now - timedelta(days=live.NEEDS_YOU_DAYS + 1))
    _brief(world.workspace, status=StudioBrief.Status.FAILED, error="The picture did not load.")
    post = Post.objects.create(workspace=world.workspace, caption="Same tower. A fairer number.")
    PlatformPost.objects.create(post=post, social_account=world.linkedin, status="pending_review")
    PlatformPost.objects.create(post=post, social_account=world.x, status="pending_review")

    snap = live.snapshot(world.workspace, now=now)

    assert snap["counts"]["approvals"] == 1  # one post, two networks
    assert snap["counts"]["stopped_tasks"] == 4  # failed, interrupted, paused, the failed brief
    assert snap["counts"]["needs_you"] == 5
    words = {row["word"] for row in snap["recent"]}
    assert {"Failed", "Interrupted", "Paused", "Cancelled"} <= words


def test_an_agent_whose_last_turn_failed_shows_stopped(world):
    now = timezone.now()
    job = _job(world.workspace, "report", status=AgencyJob.Status.FAILED, error="Boom.")
    _run("reporter", job=job, started_at=now - timedelta(hours=1), status=AgentRun.Status.FAILED)
    _run("planner", job=job, started_at=now - timedelta(hours=30), status=AgentRun.Status.FAILED)

    snap = live.snapshot(world.workspace, now=now)

    assert _agent(snap, "reporter")["state"] == "stopped"
    assert _agent(snap, "reporter")["last_url"] == _url("studio:job", world, job_id=job.id)
    assert _agent(snap, "planner")["state"] == "idle"  # a failure over a day old has aged out
    assert snap["agents"]["stopped"] == 1


# ---------------------------------------------------------------------------
# Worker health
# ---------------------------------------------------------------------------


def test_worker_health_online_delayed_offline(world):
    now = timezone.now()
    assert live.snapshot(world.workspace, now=now)["health"]["state"] == "offline"
    assert live.snapshot(world.workspace, now=now)["health"]["detail"] == "no check-in yet"

    _beat(now, ages=(12, 30, 40))
    health = live.snapshot(world.workspace, now=now)["health"]
    assert health["state"] == "online" and health["label"] == "Online"
    assert health["detail"] == "checked 12 s ago" and health["sentence"] == ""

    _beat(now, ages=(400, 30, 40))  # publishing is late, the rest checked in
    health = live.snapshot(world.workspace, now=now)["health"]
    assert health["state"] == "delayed" and health["label"] == "Running late"
    assert "worker" not in health["sentence"].lower()

    _beat(now, ages=(7200, 7200, 7200))
    health = live.snapshot(world.workspace, now=now)["health"]
    assert health["state"] == "offline" and health["detail"] == "last check-in 2 h ago"
    assert "Set up" in health["sentence"] and "worker" not in health["sentence"].lower()


# ---------------------------------------------------------------------------
# The last 24 hours, in workspace time
# ---------------------------------------------------------------------------


def _hours(snapshot):
    return snapshot["activity"]["hours"]


def test_hour_buckets_follow_a_half_hour_zone(world):
    # Asia/Kolkata is UTC+5:30: local hours start at half past the UTC hour.
    now = datetime(2026, 10, 23, 10, 45, tzinfo=UTC)  # 16:15 in Hyderabad
    job = _job(world.workspace, "report")
    _run("reporter", job=job, started_at=datetime(2026, 10, 23, 10, 35, tzinfo=UTC))  # 16:05 local
    _run("reporter", job=job, started_at=datetime(2026, 10, 23, 10, 25, tzinfo=UTC))  # 15:55 local
    _run("reporter", job=job, started_at=datetime(2026, 10, 23, 10, 20, tzinfo=UTC), status=AgentRun.Status.FAILED)

    hours = _hours(live.snapshot(world.workspace, now=now))

    assert hours[-1]["label"] == "16:00" and hours[-1]["is_now"] and hours[-1]["total"] == 1
    assert hours[-2]["label"] == "15:00" and hours[-2]["total"] == 2 and hours[-2]["failed"] == 1
    assert hours[0]["label"] == "17:00"  # yesterday's 17:00, 23 hours earlier


def test_hour_buckets_cross_midnight_and_the_autumn_clock_change(world):
    Workspace.objects.filter(pk=world.workspace.pk).update(timezone="Europe/London")
    world.workspace.refresh_from_db()
    # 25 Oct 2026: London goes from 02:00 BST back to 01:00 GMT (at 01:00 UTC).
    now = datetime(2026, 10, 25, 6, 30, tzinfo=UTC)  # 06:30 GMT
    job = _job(world.workspace, "report")
    _run("reporter", job=job, started_at=datetime(2026, 10, 24, 23, 40, tzinfo=UTC))  # 00:40 BST, after midnight
    _run("reporter", job=job, started_at=datetime(2026, 10, 25, 0, 15, tzinfo=UTC))  # 01:15 BST
    _run("reporter", job=job, started_at=datetime(2026, 10, 25, 1, 15, tzinfo=UTC))  # 01:15 GMT, an hour later

    hours = _hours(live.snapshot(world.workspace, now=now))
    labels = [hour["label"] for hour in hours]

    assert len(hours) == 24 and labels[-1] == "06:00"
    assert labels.count("01:00") == 2  # the repeated hour is two real hours, two bars
    assert [hour["total"] for hour in hours if hour["label"] == "01:00"] == [1, 1]
    assert next(hour for hour in hours if hour["label"] == "00:00")["total"] == 1
    assert hours[0]["label"] == "08:00"  # 23 real hours before 06:00 GMT is 08:00 BST yesterday


def test_hour_buckets_skip_the_missing_spring_hour(world):
    Workspace.objects.filter(pk=world.workspace.pk).update(timezone="Europe/London")
    world.workspace.refresh_from_db()
    now = datetime(2026, 3, 29, 6, 30, tzinfo=UTC)  # 07:30 BST; 01:00-02:00 GMT never happened

    labels = [hour["label"] for hour in _hours(live.snapshot(world.workspace, now=now))]

    assert "01:00" not in labels and labels[labels.index("00:00") + 1] == "02:00"
    assert labels[-1] == "07:00"


def test_the_chart_summary_and_scale(world):
    now = timezone.now()
    job = _job(world.workspace, "report")
    for minutes in (5, 6, 7):
        _run("reporter", job=job, started_at=now - timedelta(minutes=minutes))

    activity = live.snapshot(world.workspace, now=now)["activity"]

    assert activity["total"] == 3 and activity["peak"] >= 1 and activity["scale"] >= activity["peak"]
    assert activity["summary"].startswith("Turns your team took each hour, last 24 hours. Busiest at")
    assert [tick["label"] for tick in activity["axis"]][-1] == "Now"


# ---------------------------------------------------------------------------
# The next 24 hours
# ---------------------------------------------------------------------------


def test_upcoming_routines_autopilot_posts_approvals_and_queued_work(world, monkeypatch):
    now = timezone.now()
    Routine.objects.create(
        workspace=world.workspace, title="Evening check", next_run_at=now + timedelta(hours=2), enabled=True
    )
    Routine.objects.create(workspace=world.workspace, title="Off", next_run_at=now + timedelta(hours=3), enabled=False)
    Routine.objects.create(workspace=world.workspace, title="Later", next_run_at=now + timedelta(hours=30))
    local = now.astimezone(live._zone(world.workspace))
    plan_at = local + timedelta(hours=5)
    AgencySettings.objects.create(
        workspace=world.workspace, autopilot_enabled=True, plan_weekday=plan_at.weekday(), plan_hour=plan_at.hour
    )
    monkeypatch.setattr(autopilot, "local_now", lambda workspace, now=None: local)
    post = Post.objects.create(workspace=world.workspace, title="Clubhouse reel")
    PlatformPost.objects.create(
        post=post, social_account=world.linkedin, status="scheduled", scheduled_at=now + timedelta(hours=8)
    )
    _brief(world.workspace, status=StudioBrief.Status.READY, proposed_publish_at=now + timedelta(hours=10))
    _brief(world.workspace, status=StudioBrief.Status.QUEUED)

    upcoming = live.snapshot(world.workspace, now=now)["upcoming"]
    events = {(event["kind"], event["title"]) for event in upcoming["events"]}

    assert ("routine", "Evening check") in events and ("routine", "Plan next week") in events
    assert ("post", "Clubhouse reel") in events
    assert any(kind == "approve" and title.startswith("Approve by ") for kind, title in events)
    assert ("queued", "1 queued") in events
    assert not any(title in ("Off", "Later") for _kind, title in events)
    assert set(upcoming["kinds"]) == {"routine", "post", "approve", "queued"}
    post_event = next(event for event in upcoming["events"] if event["kind"] == "post")
    assert world.linkedin.get_platform_display() in post_event["caption"]
    assert all(1.5 <= event["pct"] <= 100 for event in upcoming["events"])
    assert upcoming["ticks"][0]["label"] == "Now"
    assert sum(cluster["count"] for cluster in upcoming["clusters"]) == len(upcoming["events"])


# ---------------------------------------------------------------------------
# The latest post's receipt
# ---------------------------------------------------------------------------


def _team_post(world, brief_status, *rows, post_at=None):
    """A team brief whose post has one channel per (account, status, fields) row."""
    post = Post.objects.create(workspace=world.workspace, title="Clubhouse reel", scheduled_at=post_at)
    for account, status, fields in rows:
        PlatformPost.objects.create(post=post, social_account=account, status=status, **fields)
    _brief(world.workspace, status=brief_status, post=post, finished_at=timezone.now() - timedelta(hours=1))
    return post


def _label(world, when, now):
    zone = live._zone(world.workspace)
    return live._day_label(when.astimezone(zone), now.astimezone(zone))


def test_the_receipt_counts_an_approval_the_gate_did_not_stamp(world):
    # Without dashboard approval (the default) the gate records no approver, yet the post was approved.
    assert not world.workspace.require_dashboard_approval
    now = timezone.now()
    at = now + timedelta(hours=20)
    post = _team_post(world, StudioBrief.Status.APPROVED, (world.linkedin, "scheduled", {"scheduled_at": at}))

    steps = live.snapshot(world.workspace, now=now)["receipt"]["steps"]

    assert steps[1] == {"state": "done", "text": "Approved", "meta": ""}
    assert steps[2] == {
        "state": "current",
        "text": f"Scheduled for {world.linkedin.get_platform_display()}",
        "meta": _label(world, at, now),
    }
    assert steps[3] == {"state": "pending", "text": "Published", "meta": "Pending"}

    PlatformPost.objects.filter(post=post).update(status="published", published_at=at)
    steps = live.snapshot(world.workspace, now=now)["receipt"]["steps"]
    assert steps[1]["text"] == "Approved" and steps[3]["state"] == "done"
    assert not any(step["state"] == "needs-you" for step in steps)


def test_the_receipt_waits_for_the_client_after_the_internal_approval(world):
    Workspace.objects.filter(pk=world.workspace.pk).update(
        require_dashboard_approval=True,
        approval_workflow_mode=Workspace.ApprovalWorkflowMode.REQUIRED_INTERNAL_AND_CLIENT,
    )
    now = timezone.now()
    approved = {"approved_by": world.manager, "approved_at": now - timedelta(minutes=30)}
    post = _team_post(world, StudioBrief.Status.APPROVED, (world.linkedin, "pending_client", approved))

    steps = live.snapshot(world.workspace, now=now)["receipt"]["steps"]

    assert steps[1] == {"state": "needs-you", "text": "Waiting for the client", "meta": ""}
    assert steps[2]["state"] == "pending"

    # The client signs off and the team schedules it: the approver's name and time come back.
    at = now + timedelta(hours=3)
    PlatformPost.objects.filter(post=post).update(status="scheduled", scheduled_at=at)
    steps = live.snapshot(world.workspace, now=now)["receipt"]["steps"]
    assert steps[1] == {
        "state": "done",
        "text": "Approved by Manager",
        "meta": _label(world, approved["approved_at"], now),
    }


def test_coming_up_and_the_receipt_fall_back_to_the_posts_time(world):
    # A scheduled channel with no time of its own goes out at the post's time (the publisher's Coalesce).
    now = timezone.now()
    at = now + timedelta(hours=2)
    _team_post(world, StudioBrief.Status.APPROVED, (world.linkedin, "scheduled", {}), post_at=at)
    early = Post.objects.create(workspace=world.workspace, title="Site visit", scheduled_at=now + timedelta(hours=9))
    PlatformPost.objects.create(
        post=early, social_account=world.x, status="scheduled", scheduled_at=now + timedelta(hours=1)
    )
    late = Post.objects.create(workspace=world.workspace, title="Moved out", scheduled_at=now + timedelta(hours=3))
    PlatformPost.objects.create(
        post=late, social_account=world.x, status="scheduled", scheduled_at=now + timedelta(hours=30)
    )

    snap = live.snapshot(world.workspace, now=now)

    posts = [event for event in snap["upcoming"]["events"] if event["kind"] == "post"]
    assert [event["title"] for event in posts] == ["Site visit", "Clubhouse reel"]  # the channel's own time wins
    assert posts[1]["time_text"] == _label(world, at, now)
    assert snap["idle_text"] == f"Nothing is running right now. Next: Site visit, {posts[0]['time_text']}."
    assert snap["receipt"]["steps"][2] == {
        "state": "current",
        "text": f"Scheduled for {world.linkedin.get_platform_display()}",
        "meta": _label(world, at, now),
    }


def test_the_receipt_waits_for_you_while_the_post_is_in_review(world):
    _team_post(world, StudioBrief.Status.READY, (world.linkedin, "pending_review", {}))

    steps = live.snapshot(world.workspace, now=timezone.now())["receipt"]["steps"]

    assert steps[1] == {"state": "needs-you", "text": "Waiting for your approval", "meta": ""}


def test_the_receipt_drops_an_approval_that_was_withdrawn_or_sent_back(world):
    # The brief stays APPROVED when an edit withdraws the approval or the client asks for changes;
    # only the channels say what holds now.
    post = _team_post(world, StudioBrief.Status.APPROVED, (world.linkedin, "pending_review", {}))

    steps = live.snapshot(world.workspace, now=timezone.now())["receipt"]["steps"]
    assert steps[1] == {"state": "needs-you", "text": "Waiting for your approval", "meta": ""}

    PlatformPost.objects.filter(post=post).update(status="changes_requested")
    steps = live.snapshot(world.workspace, now=timezone.now())["receipt"]["steps"]
    assert steps[1] == {"state": "current", "text": "Changes requested", "meta": ""}
    assert not any(step["text"].startswith("Approved") for step in steps)


# ---------------------------------------------------------------------------
# Isolation and privacy
# ---------------------------------------------------------------------------


def test_another_workspaces_work_never_shows(world):
    now = timezone.now()
    other = Workspace.objects.create(organization=world.org, name="Other", timezone="Asia/Kolkata")
    brief = _brief(other, status=StudioBrief.Status.WORKING, stage=StudioBrief.Stage.COPY)
    _run("copywriter", brief=brief, status=AgentRun.Status.RUNNING, started_at=now - timedelta(seconds=5))
    _job(other, "report", status=AgencyJob.Status.FAILED, error="Boom.")
    Routine.objects.create(workspace=other, title="Theirs", next_run_at=now + timedelta(hours=1))

    snap = live.snapshot(world.workspace, now=now)

    assert snap["tracks"] == [] and snap["counts"]["working"] == 0 and snap["counts"]["needs_you"] == 0
    assert snap["activity"]["total"] == 0 and snap["upcoming"]["events"] == []
    assert _agent(snap, "copywriter")["state"] == "idle"


def test_private_telegram_jobs_and_their_turns_stay_out(world):
    now = timezone.now()
    private = Conversation.objects.create(workspace=world.workspace, is_private=True)
    job = _job(world.workspace, "chat", status=AgencyJob.Status.WORKING, stage="answer", conversation=private)
    _run("account_manager", job=job, status=AgentRun.Status.RUNNING, started_at=now - timedelta(seconds=5))
    _job(world.workspace, "report", status=AgencyJob.Status.FAILED, error="Boom.", conversation=private)

    snap = live.snapshot(world.workspace, now=now)

    assert snap["tracks"] == [] and snap["counts"]["working"] == 0 and snap["counts"]["needs_you"] == 0
    assert snap["activity"]["total"] == 0 and snap["recent"] == []
    assert _agent(snap, "account_manager")["state"] == "idle"


# ---------------------------------------------------------------------------
# The pages
# ---------------------------------------------------------------------------


def test_the_team_tab_is_the_live_view(client, world):
    brief = _brief(world.workspace, status=StudioBrief.Status.WORKING, stage=StudioBrief.Stage.COPY)
    _run("copywriter", brief=brief, status=AgentRun.Status.RUNNING)
    client.force_login(world.owner)

    html = client.get(_url("studio:team", world)).content.decode()

    assert "hx-trigger=\"every 5s [document.visibilityState === 'visible']\"" in html
    assert _url("studio:team_board", world) in html and "js/live_board.js" in html
    for heading in ("Working now", "Recently finished", "Last 24 hours", "Next 24 hours", "Your team"):
        assert heading in html
    assert 'aria-current="step"' in html and "Copywriter is writing the caption" in html
    assert "Show as table" in html and 'role="img"' in html
    assert 'id="team-live-announce"' in html and 'aria-live="polite"' in html
    for agent in team.AGENTS:
        assert agent.name in html
    board = client.get(_url("studio:team_board", world)).content.decode().lower()
    for banned in ("fal.ai", "anthropic", "openrouter", "claude", "worker", "token", "assistant", "operator"):
        assert banned not in board, banned


def test_the_board_partial_refreshes_with_get_only(client, world):
    client.force_login(world.editor)
    url = _url("studio:team_board", world)

    response = client.get(url, HTTP_HX_REQUEST="true")
    html = response.content.decode()
    assert response.status_code == 200 and response["Cache-Control"] == "no-store"
    assert "data-board-digest=" in html and 'id="team-status" class="mt-1.5" hx-swap-oob="true"' in html
    assert "<html" not in html and "live_board.js" not in html

    strip = client.get(url + "?part=strip").content.decode()
    assert "Right now" in strip and "Open Team" in strip and "data-live-strip" in strip

    assert client.post(url).status_code == 405


SECRET_ROUTINE = "Push the Diwali price drop to the VIP list"


def _plans(world, monkeypatch, now):
    """A routine, the autopilot plan and a scheduled post, all in the next 24 hours."""
    Routine.objects.create(workspace=world.workspace, instruction=SECRET_ROUTINE, next_run_at=now + timedelta(hours=2))
    local = now.astimezone(live._zone(world.workspace))
    plan_at = local + timedelta(hours=5)
    AgencySettings.objects.create(
        workspace=world.workspace, autopilot_enabled=True, plan_weekday=plan_at.weekday(), plan_hour=plan_at.hour
    )
    monkeypatch.setattr(autopilot, "local_now", lambda workspace, now=None: local)
    post = Post.objects.create(workspace=world.workspace, title="Clubhouse reel")
    PlatformPost.objects.create(
        post=post, social_account=world.linkedin, status="scheduled", scheduled_at=now + timedelta(hours=8)
    )
    return post


def test_viewers_see_no_routine_text_and_no_links_that_refuse_them(client, world, monkeypatch):
    # The Routines, Autopilot and composer pages need create_posts; the snapshot is shared by the workspace.
    assert not WorkspaceMembership.objects.get(user=world.viewer, workspace=world.workspace).effective_permissions[
        "create_posts"
    ]
    post = _plans(world, monkeypatch, timezone.now())
    _job(world.workspace, "report", status=AgencyJob.Status.QUEUED, error=autopilot.AUTOPILOT_PAUSED)
    closed = [
        f'href="{_url("studio:routines", world)}"',
        f'href="{_url("studio:autopilot", world)}"',
        f'href="{_url("composer:compose_edit", world, post_id=post.id)}"',
    ]
    board = _url("studio:team_board", world)

    client.force_login(world.owner)
    owner = client.get(board).content.decode()
    assert SECRET_ROUTINE in owner and all(link in owner for link in closed)

    client.force_login(world.viewer)
    for url in (_url("studio:team", world), board):
        html = client.get(url).content.decode()
        assert SECRET_ROUTINE not in html, url
        assert not any(link in html for link in closed), url
        # They still see that something is planned, and when.
        assert "Clubhouse reel" in html and "Plan next week" in html and "Routine" in html, url
        assert "once autopilot is on" in html, url

    client.force_login(world.owner)
    assert SECRET_ROUTINE in client.get(board).content.decode()


def test_the_idle_line_names_no_routine_to_viewers(client, world, rf):
    from apps.studio import views

    Routine.objects.create(
        workspace=world.workspace, instruction=SECRET_ROUTINE, next_run_at=timezone.now() + timedelta(hours=2)
    )
    client.force_login(world.viewer)

    for url in (_url("studio:team", world), _url("studio:team_board", world) + "?part=strip"):
        html = client.get(url).content.decode()
        assert SECRET_ROUTINE not in html and "Next: Routine, " in html, url

    # Home's card, for someone who approves the team's work but does not direct it.
    request = rf.get("/")
    request.workspace_membership = WorkspaceMembership.objects.get(user=world.editor, workspace=world.workspace)
    approver = views._live_strip(request, world.workspace, {"create_posts": False, "approve_posts": True})
    assert SECRET_ROUTINE not in approver["idle_text"]
    assert SECRET_ROUTINE in views._live_strip(request, world.workspace, {"create_posts": True})["idle_text"]


def test_clients_get_a_403_and_viewers_may_watch(client, world):
    viewer = client
    viewer.force_login(world.viewer)
    assert viewer.get(_url("studio:team", world)).status_code == 200
    assert viewer.get(_url("studio:team_board", world)).status_code == 200

    client_user = world.viewer.__class__.objects.create_user(
        email="client@example.com", password="pw-12345678", name="Client", tos_accepted_at=timezone.now()
    )
    WorkspaceMembership.objects.create(user=client_user, workspace=world.workspace, workspace_role="client")
    client.force_login(client_user)
    assert client.get(_url("studio:team", world)).status_code == 403
    assert client.get(_url("studio:team_board", world)).status_code == 403
    assert client.get(_url("studio:team_board", world) + "?part=strip").status_code == 403

    client.force_login(world.outsider)
    assert client.get(_url("studio:team_board", world)).status_code in (302, 403, 404)

    client.logout()
    response = client.get(_url("studio:team_board", world))
    assert response.status_code == 302 and "login" in response["Location"]


def test_the_team_tab_shows_for_staff_who_create_or_approve(world):
    approver_only = {"create_posts": False, "approve_posts": True}
    for perms in (
        WorkspaceMembership.objects.get(user=world.editor, workspace=world.workspace).effective_permissions,
        approver_only,
        WorkspaceMembership.objects.get(user=world.viewer, workspace=world.workspace).effective_permissions,
    ):
        keys = [tab["key"] for tab in dashboard.tabs(world.workspace, "team", perms=perms)]
        assert "team" in keys
        assert [tab["key"] for tab in dashboard.tabs(world.workspace, "team", perms=perms) if tab["active"]] == ["team"]


# ---------------------------------------------------------------------------
# Cost: bounded queries, a short cache, a stable digest
# ---------------------------------------------------------------------------


def _busy(world, n):
    now = timezone.now()
    for index in range(n):
        brief = _brief(world.workspace, status=StudioBrief.Status.WORKING, stage=StudioBrief.Stage.COPY)
        brief.social_accounts.add(world.linkedin)
        _run("copywriter", brief=brief, status=AgentRun.Status.RUNNING, started_at=now - timedelta(seconds=index))
        job = _job(world.workspace, "blog", status=AgencyJob.Status.WORKING, stage="write")
        _run("blog_writer", job=job, started_at=now - timedelta(hours=index % 20), summary="Wrote a section.")
        _job(world.workspace, "report", status=AgencyJob.Status.FAILED, error="Boom.")
        _brief(world.workspace, status=StudioBrief.Status.READY, finished_at=now - timedelta(minutes=index))
        Routine.objects.create(workspace=world.workspace, title=f"R{index}", next_run_at=now + timedelta(hours=index))


def test_the_snapshot_runs_a_fixed_number_of_queries(world):
    _busy(world, 2)
    with CaptureQueriesContext(connection) as small:
        live.snapshot(world.workspace, now=timezone.now())
    _busy(world, 6)
    with CaptureQueriesContext(connection) as large:
        live.snapshot(world.workspace, now=timezone.now())

    assert len(large) == len(small), "the snapshot's queries grow with the rows (an N+1)"
    assert len(large) <= 22


def test_the_roster_reads_only_todays_turns(world, monkeypatch):
    now = datetime(2026, 10, 23, 10, 45, tzinfo=UTC)  # 16:15 in Hyderabad
    job = _job(world.workspace, "report")
    _run("reporter", job=job, started_at=now - timedelta(days=3), summary="Wrote last week's report.")
    _run("copywriter", job=job, started_at=now - timedelta(minutes=2))
    _run("copywriter", job=job, started_at=now - timedelta(minutes=1))

    with CaptureQueriesContext(connection) as queries:
        snap = live.snapshot(world.workspace, now=now)

    # The per-agent count is bounded to today where it reads, so it never scans the whole history.
    (grouped,) = [
        query["sql"] for query in queries if "studio_agent_run" in query["sql"] and "GROUP BY" in query["sql"]
    ]
    assert '"studio_agent_run"."started_at" >=' in grouped.split(" FROM ", 1)[1]
    assert _agent(snap, "copywriter")["turns_today"] == 2
    reporter = _agent(snap, "reporter")
    assert reporter["turns_today"] == 0 and reporter["last_text"] == "Wrote last week's report."
    assert "turns_total" not in reporter

    # Older than the latest turns read and nothing today: never "Not needed yet." for an agent that has worked.
    monkeypatch.setattr(live, "LATEST_TURNS", 2)
    reporter = _agent(live.snapshot(world.workspace, now=now), "reporter")
    assert reporter["last_text"] == "No turns today." and reporter["last_ago"] == ""


def test_the_cache_outlives_the_team_tabs_refresh(client, world):
    # Shorter, and even one open tab would miss it and build a fresh snapshot on every refresh.
    client.force_login(world.owner)
    html = client.get(_url("studio:team", world)).content.decode()
    match = re.search(r'id="team-board"[^>]*hx-trigger="every (\d+)s ', html)
    assert match is not None
    assert int(match.group(1)) < live.CACHE_SECONDS


def test_the_snapshot_is_cached_briefly_per_workspace(world, django_assert_num_queries):
    first = live.snapshot(world.workspace)
    with django_assert_num_queries(0):
        assert live.snapshot(world.workspace)["digest"] == first["digest"]
    live.forget(world.workspace)
    _brief(world.workspace, status=StudioBrief.Status.QUEUED)
    assert live.snapshot(world.workspace)["digest"] != first["digest"]


def test_the_refresh_stays_within_its_query_budget(client, world):
    _busy(world, 3)
    client.force_login(world.owner)
    client.get(_url("studio:team_board", world))  # warm the session and the middleware caches
    cache.clear()
    with CaptureQueriesContext(connection) as fresh:
        assert client.get(_url("studio:team_board", world)).status_code == 200
    with CaptureQueriesContext(connection) as cached:
        assert client.get(_url("studio:team_board", world)).status_code == 200

    # The snapshot plus the request's own session, user and membership lookups; no sidebar queries.
    assert len(fresh) <= 30
    assert len(cached) <= len(fresh) - 15


# ---------------------------------------------------------------------------
# Home's "Right now" card, and the links into the Team tab
# ---------------------------------------------------------------------------


def test_home_shows_the_right_now_card_under_today_to_staff(client, world):
    brief = _brief(world.workspace, status=StudioBrief.Status.WORKING, stage=StudioBrief.Stage.COPY)
    _run("copywriter", brief=brief, status=AgentRun.Status.RUNNING)

    for user in (world.owner, world.editor):
        cache.clear()
        client.force_login(user)
        response = client.get(_url("studio:index", world))
        html = response.content.decode()

        assert response.status_code == 200
        assert html.count("data-live-strip") == 1 and "Right now" in html and "Open Team" in html
        assert f'href="{_url("studio:team", world)}"' in html
        assert f"{_url('studio:team_board', world)}?part=strip" in html and "js/live_board.js" in html
        assert "Saturday site visit, free parking" in html and 'aria-current="step"' in html
        # Under Today, in the same column, before the first-steps card and the conversation.
        assert html.index("data-home-today") < html.index("data-live-strip") < html.index("data-home-thread")


def test_home_leaves_the_card_out_for_viewers_without_the_permission(client, world):
    client.force_login(world.viewer)
    response = client.get(_url("studio:index", world))
    html = response.content.decode()

    assert response.status_code == 200
    assert "data-live-strip" not in html and "Right now" not in html
    # The Team tab itself stays open to them.
    assert client.get(_url("studio:team", world)).status_code == 200


def test_the_home_card_follows_create_or_approve(world, rf):
    from apps.studio import views

    membership = WorkspaceMembership.objects.get(user=world.editor, workspace=world.workspace)
    request = rf.get("/")
    request.workspace_membership = membership

    assert views._live_strip(request, world.workspace, {"create_posts": True})["team_url"]
    assert views._live_strip(request, world.workspace, {"create_posts": False, "approve_posts": True}) is not None
    assert views._live_strip(request, world.workspace, {"create_posts": False, "approve_posts": False}) is None

    client_user = world.viewer.__class__.objects.create_user(
        email="client-home@example.com", password="pw-12345678", name="Client", tos_accepted_at=timezone.now()
    )
    request.workspace_membership = WorkspaceMembership.objects.create(
        user=client_user, workspace=world.workspace, workspace_role="client"
    )
    assert views._live_strip(request, world.workspace, {"approve_posts": True}) is None


def test_a_failing_snapshot_never_breaks_home(client, world, monkeypatch):
    def boom(workspace, **kwargs):
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr(live, "snapshot", boom)
    client.force_login(world.owner)
    response = client.get(_url("studio:index", world))

    assert response.status_code == 200 and "data-live-strip" not in response.content.decode()


def test_a_failing_snapshot_answers_the_refresh_with_nothing_to_swap(client, world, monkeypatch):
    def boom(workspace, **kwargs):
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr(live, "snapshot", boom)
    client.force_login(world.owner)
    for suffix in ("", "?part=strip"):
        response = client.get(_url("studio:team_board", world) + suffix)
        # 204: htmx swaps nothing and raises no error toast; the next refresh tries again.
        assert response.status_code == 204 and response.content == b"", suffix
        assert response["Cache-Control"] == "no-store"


def test_the_live_boards_never_raise_the_error_toast(client, world):
    client.force_login(world.owner)
    team_html = client.get(_url("studio:team", world)).content.decode()
    assert 'id="team-board" data-live-board data-no-error-toast' in team_html
    strip = client.get(_url("studio:team_board", world) + "?part=strip").content.decode()
    assert 'id="live-strip" data-live-strip data-no-error-toast' in strip
    # The hour chart's arrow keys are read out through a live region outside the role="img" chart.
    assert "data-chart-live" in team_html


def test_the_home_card_adds_no_queries_once_the_snapshot_is_cached(client, world, monkeypatch):
    from apps.studio import views

    _busy(world, 3)
    monkeypatch.setattr(live, "CACHE_SECONDS", 300)  # the test must not race the real few-second lifetime
    client.force_login(world.owner)
    url = _url("studio:index", world)
    client.get(url)  # warm the session, the middleware and the snapshot caches
    client.get(url)

    with CaptureQueriesContext(connection) as cached:
        assert "data-live-strip" in client.get(url).content.decode()
    cache.delete(f"{live.CACHE_PREFIX}{world.workspace.pk}")
    with CaptureQueriesContext(connection) as cold:
        assert "data-live-strip" in client.get(url).content.decode()
    original = views._live_strip
    monkeypatch.setattr(views, "_live_strip", lambda *args: None)
    with CaptureQueriesContext(connection) as without:
        assert "data-live-strip" not in client.get(url).content.decode()
    monkeypatch.setattr(views, "_live_strip", original)

    assert len(cached) <= len(without) + 2, "a cached snapshot should cost Home next to nothing"
    assert len(cold) <= len(without) + 22, "an uncached snapshot stays within its fixed budget"


def test_home_links_a_running_routine_to_the_team_tab(client, world):
    Routine.objects.create(
        workspace=world.workspace,
        title="Morning plan",
        instruction="Plan the day.",
        created_by=world.owner,
        status=Routine.Status.RUNNING,
        next_run_at=timezone.now() + timedelta(hours=2),
    )
    Routine.objects.create(
        workspace=world.workspace,
        title="Evening check",
        instruction="Check the day.",
        created_by=world.owner,
        next_run_at=timezone.now() + timedelta(hours=8),
    )
    client.force_login(world.owner)

    # The Routines page moved into the Team tab (Activity) in Phase 2; Home's rows keep the link.
    html = client.get(_url("studio:index", world)).content.decode()

    assert html.count("data-routine-team-link") == 1
    assert f'href="{_url("studio:team", world)}" class="ui-link' in html and "See it on Team" in html

    # On the Team tab the rows sit on the page that shows the work, so none links to itself.
    team_html = client.get(_url("studio:team", world)).content.decode()
    assert "Morning plan" in team_html and "data-routine-team-link" not in team_html


def test_set_up_links_autopilot_to_the_team_tab_once_it_is_on(client, world):
    client.force_login(world.owner)
    html = client.get(_url("studio:setup", world)).content.decode()
    assert 'data-setup-link="autopilot"' not in html

    AgencySettings.objects.create(workspace=world.workspace, autopilot_enabled=True, lead=world.owner)
    html = client.get(_url("studio:setup", world)).content.decode()
    assert 'data-setup-link="autopilot"' in html and "See your team at work" in html
    assert f'href="{_url("studio:team", world)}"' in html


def test_the_roster_names_no_vendor():
    for agent in team.AGENTS:
        lowered = agent.does.lower()
        for banned in ("fal.ai", "fal ", "anthropic", "openrouter", "claude", "openai"):
            assert banned not in lowered, (agent.slug, banned)
