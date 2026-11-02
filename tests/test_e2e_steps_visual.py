"""The e2e steps for the visual specs (tests/e2e/server/steps/visual.py), under ``config.settings.test``.

``tests/e2e/visual/`` photographs screens against committed baselines, so what a page shows must not
move with the real date or with other specs. Two fixtures make that so:

- ``visual_workspace``: a workspace of its own at a fixed id, in its own organisation, with its owner
  and editor, three connected accounts, a brand profile, posts at fixed times in the week of Mon 4 Jan
  2027, briefs and the team thread with every time set by the fixture. Each call puts the same rows
  back and answers the same ids; it never touches the seeded A or B and leaves nobody a "My Workspace".
- ``visual_clock``: ``{"at": <ISO time with its offset>}`` freezes the server's clock (request threads
  and the worker read the same instant) and holds the worker for as long as it is frozen, with the
  worker's check-ins stamped at the instant; ``{}`` puts the real clock, the check-ins and the worker back.

The browser side (``tests/e2e/self/visual-harness.spec.ts``) checks the screenshots; this file pins the
rows, the ids, the clock and the refusals.
"""

from __future__ import annotations

import ast
import json
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from django.test import Client
from django.utils import timezone

REPO = Path(__file__).resolve().parent.parent
WORKSPACE_A = "00000000-0000-4000-8000-00000000000a"
WORKSPACE_B = "00000000-0000-4000-8000-00000000000b"
VISUAL_WORKSPACE = "00000000-0000-4000-8000-0000000000c1"
KOLKATA = ZoneInfo("Asia/Kolkata")
INSTANT = "2027-01-03T09:00:00+05:30"
INSTANT_AT = datetime(2027, 1, 3, 9, 0, tzinfo=KOLKATA)
WEEK_START = datetime(2027, 1, 4, 0, 0, tzinfo=KOLKATA)
WEEK_END = WEEK_START + timedelta(days=7)
#: The recurring tasks whose check-ins Home's health reads (apps.common.background.task_health).
CHECK_INS = (
    "apps.publisher.tasks.run_publish_cycle",
    "apps.studio.tasks.run_agency_cycle",
    "apps.publisher.tasks.confirm_pending_publishes",
)


@pytest.fixture
def e2e_urls(settings):
    settings.ROOT_URLCONF = "tests.e2e.server.urls"
    settings.SETTINGS_MODULE = "config.settings.e2e"
    return settings


@pytest.fixture
def seeded(db):
    from tests.e2e.server import seed

    return seed.run()


@pytest.fixture(autouse=True)
def real_clock_after(monkeypatch):
    """Every test here leaves the process's clock, its check-in snapshot and the worker as it found them.

    The clock is put in place through ``monkeypatch`` first, so the fixture finds it installed and the
    suite's ``django.utils.timezone.now`` is the original again after each test.
    """
    from tests.e2e.server import clock, worker

    clock.install(setter=monkeypatch.setattr)
    yield
    clock.thaw()
    worker.resume()


def _fixture(client: Client, name: str, payload: Any):
    return client.post(f"/__e2e__/fixture/{name}", data=json.dumps(payload), content_type="application/json")


def _signed_in(client: Client, email: str) -> Client:
    session = _fixture(client, "session", {"email": email}).json()
    browser = Client()
    browser.cookies[session["cookie"]["name"]] = session["cookie"]["value"]
    return browser


def _counts(workspace_id: str) -> dict[str, int]:
    """How many rows of each kind belong to one workspace (and to its people)."""
    from apps.calendar.models import Queue
    from apps.composer.models import PlatformPost, Post
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.notifications.models import Notification
    from apps.social_accounts.models import SocialAccount
    from apps.studio.models import AgencySettings, BrandProfile, Conversation, Message, StudioBrief
    from apps.workspaces.models import Workspace

    workspace = Workspace.objects.get(pk=workspace_id)
    people = WorkspaceMembership.objects.filter(workspace=workspace).values_list("user_id", flat=True)
    return {
        "workspaces": Workspace.objects.filter(organization=workspace.organization).count(),
        "org_members": OrgMembership.objects.filter(organization=workspace.organization).count(),
        "members": WorkspaceMembership.objects.filter(workspace=workspace).count(),
        "accounts": SocialAccount.objects.filter(workspace=workspace).count(),
        "queues": Queue.objects.filter(workspace=workspace).count(),
        "profiles": BrandProfile.objects.filter(workspace=workspace).count(),
        "agency": AgencySettings.objects.filter(workspace=workspace).count(),
        "posts": Post.objects.filter(workspace=workspace).count(),
        "platform_posts": PlatformPost.objects.filter(post__workspace=workspace).count(),
        "briefs": StudioBrief.objects.filter(workspace=workspace).count(),
        "conversations": Conversation.objects.filter(workspace=workspace).count(),
        "messages": Message.objects.filter(conversation__workspace=workspace).count(),
        "notifications": Notification.objects.filter(user_id__in=list(people)).count(),
    }


def _world(workspace_id: str) -> dict[str, Any]:
    """A workspace's rows as a comparable value: the counts, the names and every post's status and time."""
    from apps.composer.models import PlatformPost
    from apps.studio.models import StudioBrief
    from apps.workspaces.models import Workspace

    workspace = Workspace.objects.select_related("organization").get(pk=workspace_id)
    return {
        "names": (workspace.name, workspace.organization.name, workspace.timezone),
        "counts": _counts(workspace_id),
        "platform_posts": sorted(
            (str(pp.pk), pp.status, pp.scheduled_at, pp.updated_at)
            for pp in PlatformPost.objects.filter(post__workspace=workspace)
        ),
        "briefs": sorted(
            (str(brief.pk), brief.status, brief.updated_at) for brief in StudioBrief.objects.filter(workspace=workspace)
        ),
    }


def _greeting(response) -> str:
    html = response.content.decode()
    # The page title, whatever layout classes sit beside ui-page-title (the title row holds New post).
    match = re.search(r'<h1 class="ui-page-title(?: [^"]*)?"[^>]*>([^<]*)</h1>', html)
    assert match, "Home has its greeting"
    return match.group(1).strip()


# ---------------------------------------------------------------------------
# visual_workspace
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_visual_workspace_makes_its_own_world_at_fixed_ids_and_fixed_times(client, e2e_urls, seeded):
    from apps.composer.models import Post
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.social_accounts.models import SocialAccount
    from apps.studio.models import AgencySettings, BrandProfile, Message, StudioBrief
    from apps.workspaces.models import Workspace

    answer = _fixture(client, "visual_workspace", {})
    assert answer.status_code == 200, answer.content
    world = answer.json()
    assert world["workspace_id"] == VISUAL_WORKSPACE
    assert world["instant"] == INSTANT
    assert world["week"] == "2027-01-04"

    workspace = Workspace.objects.select_related("organization").get(pk=VISUAL_WORKSPACE)
    assert workspace.organization.name == "Visual Agency"
    assert workspace.timezone == workspace.organization.default_timezone == "Asia/Kolkata"
    assert str(workspace.organization_id) == world["organisation_id"]
    assert workspace.require_dashboard_approval is True
    assert workspace.created_at < INSTANT_AT and workspace.organization.created_at < INSTANT_AT

    assert world["users"]["owner"]["email"] == "visual-owner@e2e.test"
    assert world["users"]["editor"]["email"] == "visual-editor@e2e.test"
    assert sorted(
        WorkspaceMembership.objects.filter(workspace=workspace).values_list("user__email", "workspace_role")
    ) == [("visual-editor@e2e.test", "editor"), ("visual-owner@e2e.test", "owner")]
    assert sorted(
        OrgMembership.objects.filter(organization=workspace.organization).values_list("org_role", flat=True)
    ) == [
        "member",
        "owner",
    ]
    for person in world["users"].values():
        # Each lands on the visual workspace, and on no other.
        assert list(
            WorkspaceMembership.objects.filter(user_id=person["id"]).values_list("workspace_id", flat=True)
        ) == [workspace.pk]

    accounts = SocialAccount.objects.filter(workspace=workspace)
    assert sorted(accounts.values_list("platform", flat=True)) == ["facebook", "instagram", "linkedin_company"]
    assert set(accounts.values_list("connection_status", flat=True)) == {"connected"}
    assert sorted(world["accounts"]) == ["facebook", "instagram", "linkedin_company"]
    assert BrandProfile.objects.filter(workspace=workspace).count() == 1
    agency = AgencySettings.objects.get(workspace=workspace)
    assert agency.autopilot_enabled is False
    assert agency.lead is not None and agency.lead.email == "visual-owner@e2e.test"

    # Posts at fixed times in the week of Mon 4 Jan 2027; nothing in it is due before that week, and
    # Home's next 24 hours from the instant hold none of them.
    posts = Post.objects.filter(workspace=workspace)
    assert posts.count() == len(world["posts"]) >= 3
    for post in posts:
        assert post.proposed_publish_at is not None
        assert WEEK_START + timedelta(hours=10) <= post.proposed_publish_at < WEEK_END, post.proposed_publish_at
        assert post.created_at < INSTANT_AT and post.updated_at < INSTANT_AT
        for platform_post in post.platform_posts.all():
            assert platform_post.status in ("draft", "pending_review"), platform_post.status
    assert {pp["status"] for post in world["posts"] for pp in post["platform_posts"]} == {"draft", "pending_review"}

    # Briefs and messages carry the fixture's times, all before the instant, none within a day of it.
    briefs = StudioBrief.objects.filter(workspace=workspace)
    assert sorted(briefs.values_list("status", flat=True)) == ["approved", "failed", "ready"]
    for brief in briefs:
        assert brief.created_at < INSTANT_AT - timedelta(days=1)
        assert brief.proposed_publish_at is None
        if brief.finished_at is not None:
            assert brief.finished_at < INSTANT_AT - timedelta(days=1)
    messages = Message.objects.filter(conversation__workspace=workspace).order_by("created_at")
    assert [message.author_kind for message in messages] == ["staff", "agent"]
    assert all(message.created_at < INSTANT_AT for message in messages)


@pytest.mark.django_db
def test_two_calls_give_the_same_ids_and_rows_whatever_happened_between(client, e2e_urls, seeded):
    from apps.composer.models import PlatformPost
    from apps.notifications.models import EventType, Notification
    from apps.studio.models import StudioBrief

    first = _fixture(client, "visual_workspace", {}).json()
    rows = _world(VISUAL_WORKSPACE)

    # A spec that ran before moved things: a post approved, a brief added, a notice for the owner.
    PlatformPost.objects.filter(post__workspace_id=VISUAL_WORKSPACE, status="pending_review").update(status="approved")
    StudioBrief.objects.create(workspace_id=VISUAL_WORKSPACE, idea="Left behind by another spec", status="ready")
    Notification.objects.create(
        user_id=first["users"]["owner"]["id"], event_type=EventType.TEAM_MEMBER_INVITED, title="Left behind"
    )
    assert _world(VISUAL_WORKSPACE) != rows

    second = _fixture(client, "visual_workspace", {})
    assert second.status_code == 200, second.content
    assert second.json() == first
    assert _world(VISUAL_WORKSPACE) == rows
    assert Notification.objects.filter(user_id=first["users"]["owner"]["id"]).count() == 0


@pytest.mark.django_db
def test_visual_workspace_leaves_a_and_b_alone_and_nobody_a_my_workspace(client, e2e_urls, seeded):
    from apps.members.models import WorkspaceMembership
    from apps.workspaces.models import Workspace

    a, b = _world(WORKSPACE_A), _world(WORKSPACE_B)
    for _ in range(2):
        assert _fixture(client, "visual_workspace", {}).status_code == 200
    assert _world(WORKSPACE_A) == a
    assert _world(WORKSPACE_B) == b
    assert not Workspace.objects.filter(name="My Workspace").exists()
    assert not WorkspaceMembership.objects.filter(
        user__email__in=["visual-owner@e2e.test", "visual-editor@e2e.test"]
    ).exclude(workspace_id=VISUAL_WORKSPACE)


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [{"workspace_id": WORKSPACE_A}, {"reset": True}, []])
def test_visual_workspace_takes_no_options(client, e2e_urls, seeded, payload):
    answer = _fixture(client, "visual_workspace", payload)
    assert answer.status_code == 400, answer.content
    assert answer.json()["error"]


@pytest.mark.django_db
def test_the_visual_owner_reads_home_at_the_instant(client, e2e_urls, seeded):
    world = _fixture(client, "visual_workspace", {}).json()
    assert _fixture(client, "visual_clock", {"at": INSTANT}).status_code == 200
    owner = _signed_in(client, world["users"]["owner"]["email"])
    home = owner.get(f"/workspace/{VISUAL_WORKSPACE}/studio/")
    assert home.status_code == 200
    html = home.content.decode()
    assert _greeting(home) == "Good morning, Vera"
    assert 'data-testid="home-today"' in html
    for title in (brief["title"] for brief in world["briefs"]):
        assert title in html


# ---------------------------------------------------------------------------
# visual_clock
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_visual_clock_freezes_requests_and_the_worker_and_clearing_restores_the_real_clock(client, e2e_urls, seeded):
    from background_task.models import Task

    from tests.e2e.server import worker

    world = _fixture(client, "visual_workspace", {}).json()
    owner = world["users"]["owner"]["email"]

    answer = _fixture(client, "visual_clock", {"at": INSTANT})
    assert answer.status_code == 200, answer.content
    assert answer.json() == {"frozen": True, "now": "2027-01-03T03:30:00+00:00"}
    assert timezone.now() == INSTANT_AT
    assert timezone.now().tzinfo is UTC
    assert timezone.localdate(timezone=KOLKATA).isoformat() == "2027-01-03"

    # A request reads it: Home greets by the hour of the instant in the workspace's time zone.
    assert _greeting(_signed_in(client, owner).get(f"/workspace/{VISUAL_WORKSPACE}/studio/")) == "Good morning, Vera"

    # The worker is a thread of the server's process, and reads the same instant…
    seen: list[datetime] = []
    thread = threading.Thread(target=lambda: seen.append(timezone.now()), name="e2e-worker")
    thread.start()
    thread.join(timeout=10)
    assert seen == [INSTANT_AT]
    # …so a task falls due by the frozen clock, not the real one…
    task = Task.objects.create(
        task_name="tests.e2e.server.steps.visual.not_a_task",
        task_params="[[], {}]",
        task_hash="visual-clock-probe",
        run_at=INSTANT_AT + timedelta(minutes=1),
    )
    assert task not in Task.objects.find_available()
    # …and is held while the clock is frozen: it acts on nothing that is not now.
    assert worker.status()["paused"] is True

    # Moving the clock on (the self spec's 90 days) moves every reader with it.
    later = _fixture(client, "visual_clock", {"at": "2027-04-03T21:00:00+05:30"})
    assert later.status_code == 200, later.content
    assert timezone.now() == datetime(2027, 4, 3, 21, 0, tzinfo=KOLKATA)
    assert task in Task.objects.find_available()
    owner_again = _signed_in(client, owner)  # a session made at the new instant
    assert _greeting(owner_again.get(f"/workspace/{VISUAL_WORKSPACE}/studio/")) == "Good evening, Vera"
    assert worker.status()["paused"] is True

    cleared = _fixture(client, "visual_clock", {})
    assert cleared.status_code == 200, cleared.content
    assert cleared.json()["frozen"] is False
    real = datetime.now(UTC)
    assert abs((timezone.now() - real).total_seconds()) < 5
    assert abs((datetime.fromisoformat(cleared.json()["now"]) - real).total_seconds()) < 5
    assert worker.status()["paused"] is False
    # Clearing twice is harmless.
    assert _fixture(client, "visual_clock", {}).status_code == 200


@pytest.mark.django_db
def test_visual_clock_stamps_the_check_ins_at_the_instant_and_puts_them_back(client, e2e_urls, seeded):
    from apps.common.background import task_health
    from apps.common.models import TaskHeartbeat

    earlier = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)
    TaskHeartbeat.objects.update_or_create(
        task_name=CHECK_INS[0],
        defaults={"last_started_at": earlier, "last_success_at": earlier, "state": "ok"},
    )
    TaskHeartbeat.objects.filter(task_name__in=CHECK_INS[1:]).delete()
    before = list(TaskHeartbeat.objects.filter(task_name__in=CHECK_INS).values())

    assert _fixture(client, "visual_clock", {"at": INSTANT}).status_code == 200
    rows = {row.task_name: row for row in TaskHeartbeat.objects.filter(task_name__in=CHECK_INS)}
    assert sorted(rows) == sorted(CHECK_INS)
    assert {row.last_success_at for row in rows.values()} == {INSTANT_AT}
    assert all(health["healthy"] for health in task_health().values())

    # Moved on, the check-ins move with it: Home's health reads the same either way.
    assert _fixture(client, "visual_clock", {"at": "2027-04-03T09:00:00+05:30"}).status_code == 200
    assert all(health["healthy"] for health in task_health().values())

    assert _fixture(client, "visual_clock", {}).status_code == 200
    assert list(TaskHeartbeat.objects.filter(task_name__in=CHECK_INS).values()) == before


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"at": "tomorrow"},
        {"at": "2027-01-03T09:00:00"},  # no offset: whose 09:00?
        {"at": 1767411000},
        {"at": ""},
        {"when": INSTANT},
        {"at": INSTANT, "worker": "keep"},
        [],
    ],
)
def test_visual_clock_refuses_a_bad_payload_and_changes_nothing(client, e2e_urls, seeded, payload):
    from tests.e2e.server import clock, worker

    answer = _fixture(client, "visual_clock", payload)
    assert answer.status_code == 400, (payload, answer.content)
    assert answer.json()["error"]
    assert clock.frozen() is None
    assert worker.status()["paused"] is False
    assert abs((timezone.now() - datetime.now(UTC)).total_seconds()) < 5


@pytest.mark.django_db(transaction=True)
def test_the_running_worker_is_held_while_the_clock_is_frozen_and_released_after(e2e_urls):
    from tests.e2e.server import worker
    from tests.e2e.server.steps import visual

    stop = threading.Event()
    thread = threading.Thread(target=worker.run_forever, kwargs={"stop": stop}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 30
        while worker.status()["ran"] == 0 and time.monotonic() < deadline:
            time.sleep(0.1)
        assert worker.status()["ran"] > 0, worker.status()

        visual.visual_clock({"at": INSTANT})
        assert worker.status()["holding"] is True  # between tasks, and staying there
        ran = worker.status()["ran"]
        time.sleep(1.5)
        assert worker.status()["ran"] == ran

        visual.visual_clock({})
        deadline = time.monotonic() + 30
        while worker.status()["ran"] == ran and time.monotonic() < deadline:
            time.sleep(0.1)
        assert worker.status()["ran"] > ran
    finally:
        visual.visual_clock({})
        stop.set()
        thread.join(timeout=30)
    assert worker.status()["error"] == ""


def test_the_clock_reaches_every_module_that_imported_now_by_name():
    """``from django.utils.timezone import now`` copies the function; the clock lists and patches each copy."""
    import importlib

    from tests.e2e.server import clock

    found = set()
    for root in ("apps", "config", "providers", "tests/e2e"):  # what the e2e server's process loads
        for path in (REPO / root).rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "django.utils.timezone":
                    module = ".".join(path.relative_to(REPO).with_suffix("").parts)
                    found |= {(module, alias.asname or "now") for alias in node.names if alias.name == "now"}
    assert found <= set(clock.NOW_IMPORTERS), sorted(found - set(clock.NOW_IMPORTERS))

    clock.freeze(INSTANT_AT)
    for module_name, attribute in clock.NOW_IMPORTERS:
        copy = getattr(importlib.import_module(module_name), attribute)
        assert copy() == INSTANT_AT, (module_name, attribute)


# ---------------------------------------------------------------------------
# What the baselines mask
# ---------------------------------------------------------------------------

#: Every element marked ``data-visual-dynamic``: what prints the real date or a time relative to it.
MARKED = {
    "templates/studio/index.html": 3,  # the greeting, today's date, Recent work's "… ago"
    "templates/studio/partials/thread_messages.html": 4,  # each message's time
    "templates/notifications/partials/drawer.html": 1,  # the shell's notifications drawer: "… ago"
}


def test_only_the_time_printing_elements_are_marked_for_masking():
    found = {}
    for path in (REPO / "templates").rglob("*.html"):
        count = path.read_text().count("data-visual-dynamic")
        if count:
            found[str(path.relative_to(REPO))] = count
    assert found == MARKED
    index = (REPO / "templates/studio/index.html").read_text().splitlines()
    marked = [line for line in index if "data-visual-dynamic" in line]
    assert any("{{ greeting }}" in line for line in marked)
    assert any('{% now "D j M" %}' in line for line in marked)
    assert any("|timesince" in line for line in marked)
    messages = (REPO / "templates/studio/partials/thread_messages.html").read_text()
    assert len(re.findall(r"<time data-visual-dynamic datetime=", messages)) == 4
