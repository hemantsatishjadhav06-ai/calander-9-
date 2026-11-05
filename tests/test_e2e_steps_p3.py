"""The e2e steps for Phase 3 (tests/e2e/server/steps/p3.py), under ``config.settings.test``.

``dark_ready`` declares pages dark-ready inside the e2e server's process, the way ``fakes.py`` puts
its stand-ins in place: it replaces ``apps.common.screens.DARK_READY``, which
``context_processors.theme_context`` reads on every render, so the next request for a declared page
carries ``data-theme-ready`` on ``<html>``. ``{"add": ["app:url", …]}`` adds pages to the set;
``{"clear": true}`` puts back the registry's own set (the pages the code declares). A browser spec
(``tests/e2e/self/theme.spec.ts``) adds the Account page and clears it after each test. What it
answers and the payloads it refuses are pinned here.

For the New post sheet's spec (``tests/e2e/screens/new-post.spec.ts``): ``workspace_over_budget``
spends this month's allowance of a workspace a test made (never the shared A or B), so the sheet's
Send is refused with the sheet's own sentence and nothing is made; ``new_post_outcome`` reads what
the sheet made in a workspace since a moment (conversations, messages by kind, the thread's jobs,
briefs, ideas and tags). Both are driven here through the real ``studio:create`` as the sheet sends it.
"""

from __future__ import annotations

import html
import json
from typing import Any

import pytest
from django.test import Client

from apps.common import screens

WORKSPACE_A = "00000000-0000-4000-8000-00000000000a"
ACCOUNT = ("accounts", "settings")
HOME = ("studio", "index")


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
def registry_restored(monkeypatch):
    """The step changes the process's registry; every test here leaves it as it found it."""
    monkeypatch.setattr(screens, "DARK_READY", screens.DARK_READY)


def _fixture(client: Client, name: str, payload: Any):
    return client.post(f"/__e2e__/fixture/{name}", data=json.dumps(payload), content_type="application/json")


def _signed_in(client: Client, email: str) -> Client:
    session = _fixture(client, "session", {"email": email}).json()
    browser = Client()
    browser.cookies[session["cookie"]["name"]] = session["cookie"]["value"]
    return browser


def _ready() -> frozenset[screens.Page]:
    """The process's declared pages now (the step replaces the registry's set)."""
    return screens.DARK_READY


def _html_tag(response) -> str:
    html = response.content.decode()
    start = html.index("<html")
    return html[start : html.index(">", start) + 1]


@pytest.mark.django_db
def test_dark_ready_declares_a_page_for_the_next_request(client, e2e_urls, seeded):
    owner = _signed_in(client, seeded["users"]["owner"]["email"])
    assert "data-theme-ready" not in _html_tag(owner.get("/accounts/settings/"))

    answer = _fixture(client, "dark_ready", {"add": ["accounts:settings"]})
    assert answer.status_code == 200, answer.content
    assert answer.json() == {"ready": sorted(f"{a}:{u}" for a, u in screens.DARK_READY)}
    assert ACCOUNT in screens.DARK_READY

    assert " data-theme-ready" in _html_tag(owner.get("/accounts/settings/"))
    # Only the declared page: one neither the step nor the code declares (Approvals of workspace A, light
    # until screen 3; Home and Calendar are the code's own since T22) still renders as it did.
    assert ("approvals", "index") not in screens.DARK_READY
    assert "data-theme-ready" not in _html_tag(owner.get(f"/workspace/{WORKSPACE_A}/approvals/"))


@pytest.mark.django_db
def test_dark_ready_adds_to_the_set_and_clear_puts_back_the_registrys_own(client, e2e_urls, seeded):
    own = screens.DARK_READY

    _fixture(client, "dark_ready", {"add": ["accounts:settings"]})
    answer = _fixture(client, "dark_ready", {"add": ["studio:index"]})
    assert answer.status_code == 200, answer.content
    assert _ready() == own | {ACCOUNT, HOME}
    assert answer.json() == {"ready": sorted({"accounts:settings", "studio:index"} | {f"{a}:{u}" for a, u in own})}

    cleared = _fixture(client, "dark_ready", {"clear": True})
    assert cleared.status_code == 200, cleared.content
    assert _ready() == own
    assert cleared.json() == {"ready": sorted(f"{a}:{u}" for a, u in own)}

    owner = _signed_in(client, seeded["users"]["owner"]["email"])
    assert ("data-theme-ready" in _html_tag(owner.get("/accounts/settings/"))) is (ACCOUNT in own)


@pytest.mark.django_db
def test_dark_ready_clears_before_it_adds(client, e2e_urls, seeded):
    own = screens.DARK_READY
    _fixture(client, "dark_ready", {"add": ["studio:index"]})
    answer = _fixture(client, "dark_ready", {"clear": True, "add": ["accounts:settings"]})
    assert answer.status_code == 200, answer.content
    assert _ready() == own | {ACCOUNT}
    assert answer.json() == {"ready": sorted({"accounts:settings"} | {f"{a}:{u}" for a, u in own})}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        {"add": "accounts:settings"},
        {"add": []},
        {"add": [""]},
        {"add": [7]},
        {"add": ["settings"]},
        {"add": ["accounts:nowhere"]},
        {"add": ["nowhere:settings"]},
        {"add": ["accounts:settings", "accounts:nowhere"]},
        {"clear": "yes"},
        {"clear": False},
        {"clear": True, "remove": ["accounts:settings"]},
    ],
)
def test_dark_ready_refuses_a_bad_payload_and_changes_nothing(client, e2e_urls, seeded, payload):
    before = screens.DARK_READY
    answer = _fixture(client, "dark_ready", payload)
    assert answer.status_code == 400, (payload, answer.content)
    assert answer.json()["error"]
    assert _ready() == before


# ---------------------------------------------------------------------------
# The New post sheet (screen 1, T21): workspace_over_budget and new_post_outcome
# ---------------------------------------------------------------------------

WORKSPACE_B = "00000000-0000-4000-8000-00000000000b"
IDEA = "Tell buyers about the new covered parking"
#: The sheet's own over-budget sentence (apps/studio/views.py ``_ALLOWANCE_USED``).
ALLOWANCE_USED = "This month's allowance for the team is used up. An owner can raise it in Settings → Autopilot."
NOTHING: dict[str, Any] = {
    "conversations": [],
    "messages": {},
    "chat_jobs": [],
    "briefs": [],
    "ideas": [],
    "tags": [],
}


@pytest.fixture
def team_ready(monkeypatch):
    """The team is connected, and a job it is given waits instead of running (no worker here)."""
    from apps.studio import engine, llm

    monkeypatch.setattr(llm, "is_configured", lambda: True)
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: None)


def _outcome(client: Client, **params: Any) -> Any:
    return client.get("/__e2e__/probe/new_post_outcome", params)


def _ask_the_team(browser: Client, workspace_id: str, idea: str = IDEA):
    """What the sheet's Send does: an HTMX POST of the form to ``studio:create``."""
    return browser.post(f"/workspace/{workspace_id}/studio/new/", {"idea": idea}, HTTP_HX_REQUEST="true")


def _hour_ago(*rows: Any) -> None:
    """Move rows' ``created_at`` an hour back, so they were made before a test's ``since``."""
    from datetime import timedelta

    from django.utils import timezone

    for row in rows:
        type(row).objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(hours=1))


@pytest.mark.django_db
def test_new_post_outcome_reads_what_ask_the_team_made_since_the_moment_given(client, e2e_urls, seeded, team_ready):
    import time

    made = _fixture(client, "team_workspace", {}).json()
    workspace = made["workspace_id"]
    since = time.time()
    assert _outcome(client, workspace_id=workspace, since=since).json() == NOTHING

    editor = _signed_in(client, made["users"]["editor"]["email"])
    sent = _ask_the_team(editor, workspace)
    assert sent.status_code == 204, sent.content

    state = _outcome(client, workspace_id=workspace, since=since).json()
    assert [row["created_by"] for row in state["conversations"]] == [made["users"]["editor"]["email"]]
    assert state["conversations"][0]["audience"] == "internal"
    # The saved idea, and the person's own words posted to the manager as a request of kind create.
    assert state["messages"] == {"workflow_idea": 1, "create": 1}
    assert [(job["kind"], job["status"]) for job in state["chat_jobs"]] == [("create", "queued")]
    assert state["chat_jobs"][0]["conversation_id"] == state["conversations"][0]["id"]
    assert state["briefs"] == [] and state["ideas"] == [] and state["tags"] == []

    # Nothing of it is another workspace's, and nothing of it was made before an hour ago.
    assert _outcome(client, workspace_id=WORKSPACE_A, since=since).json() == NOTHING
    later = time.time() + 3600
    assert _outcome(client, workspace_id=workspace, since=later).json() == NOTHING


@pytest.mark.django_db
def test_new_post_outcome_reads_ideas_tags_and_briefs_and_the_answers_of_the_manager(client, e2e_urls, seeded):
    import time

    from apps.accounts.models import User
    from apps.composer.models import Idea, IdeaGroup, Tag
    from apps.studio import chat
    from apps.studio.models import AgencyJob, Message, StudioBrief
    from apps.workspaces.models import Workspace

    made = _fixture(client, "team_workspace", {}).json()
    workspace = Workspace.objects.get(pk=made["workspace_id"])
    owner = User.objects.get(email=made["users"]["owner"]["email"])
    column = IdeaGroup.objects.create(workspace=workspace, name="This week", position=0)
    old_idea = Idea.objects.create(workspace=workspace, author=owner, title="Before", group=column)
    old_tag = Tag.objects.create(workspace=workspace, name="old")
    _hour_ago(old_idea, old_tag)
    since = time.time()

    idea = Idea.objects.create(
        workspace=workspace, author=owner, title="Open house", description="Sunday", group=column, tags=["launch"]
    )
    Tag.objects.create(workspace=workspace, name="launch")
    conversation = chat.general_conversation(workspace, created_by=owner)
    asked = Message.objects.create(conversation=conversation, author=owner, author_kind="staff", body="A question")
    AgencyJob.objects.create(
        workspace=workspace,
        kind=AgencyJob.Kind.CHAT,
        status=AgencyJob.Status.DONE,
        conversation=conversation,
        input={"message_id": str(asked.pk), "kind": "question"},
    )
    Message.objects.create(conversation=conversation, author_kind="agent", body="An answer")
    Message.objects.create(conversation=conversation, author_kind="system", body="A note")
    # Not a chat job: the probe lists the thread's jobs only.
    AgencyJob.objects.create(workspace=workspace, kind=AgencyJob.Kind.PLAN, status=AgencyJob.Status.DONE)
    brief = StudioBrief.objects.create(
        workspace=workspace, requested_by=owner, idea="Open house", status=StudioBrief.Status.QUEUED
    )

    state = _outcome(client, workspace_id=str(workspace.pk), since=since).json()

    assert state["ideas"] == [
        {
            "id": str(idea.pk),
            "title": "Open house",
            "description": "Sunday",
            "group": "This week",
            "tags": ["launch"],
            "author": owner.email,
        }
    ]
    assert state["tags"] == ["launch"]
    assert state["messages"] == {"question": 1, "agent": 1, "system": 1}
    assert [(job["kind"], job["status"]) for job in state["chat_jobs"]] == [("question", "done")]
    assert state["briefs"] == [{"id": str(brief.pk), "status": "queued", "origin": brief.origin}]
    # Without since, everything the workspace holds.
    everything = _outcome(client, workspace_id=str(workspace.pk)).json()
    assert [row["title"] for row in everything["ideas"]] == ["Before", "Open house"]
    assert everything["tags"] == ["launch", "old"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "params",
    [{}, {"workspace_id": "nope"}, {"workspace_id": WORKSPACE_A, "since": "soon"}],
)
def test_new_post_outcome_refuses_bad_parameters(client, e2e_urls, seeded, params):
    answer = _outcome(client, **params)
    assert answer.status_code == 400, answer.content
    assert answer.json()["error"]


@pytest.mark.django_db
def test_new_post_outcome_refuses_an_unknown_workspace(client, e2e_urls, seeded):
    import uuid

    assert _outcome(client, workspace_id=str(uuid.uuid4())).status_code == 400


@pytest.mark.django_db
def test_workspace_over_budget_spends_the_month_so_the_sheet_refuses_and_makes_nothing(
    client, e2e_urls, seeded, team_ready
):
    import time

    from apps.studio import budget
    from apps.studio.models import AgentRun
    from apps.workspaces.models import Workspace

    made = _fixture(client, "team_workspace", {}).json()
    workspace = Workspace.objects.get(pk=made["workspace_id"])
    assert budget.can_spend(workspace)

    answer = _fixture(client, "workspace_over_budget", {"workspace_id": made["workspace_id"]})

    assert answer.status_code == 200, answer.content
    spent = answer.json()
    assert spent == {
        "workspace_id": made["workspace_id"],
        "budget": str(budget.monthly_budget(workspace)),
        "spent": str(budget.month_spend(workspace)),
        "can_spend": False,
    }
    # The month is spent the way the team spends it: a run of this month whose cost reaches the budget.
    assert budget.month_spend(workspace) >= budget.monthly_budget(workspace) > 0
    assert not budget.can_spend(workspace)
    assert AgentRun.objects.filter(workspace=workspace).count() == 1

    since = time.time()
    editor = _signed_in(client, made["users"]["editor"]["email"])
    refused = _ask_the_team(editor, made["workspace_id"])
    assert refused.status_code == 400
    # The sentence alone, as the sheet's error line shows it (the answer is escaped HTML text).
    assert html.unescape(refused.content.decode()).strip() == ALLOWANCE_USED
    assert _outcome(client, workspace_id=made["workspace_id"], since=since).json() == NOTHING

    # Again: still spent, and no second run.
    again = _fixture(client, "workspace_over_budget", {"workspace_id": made["workspace_id"]})
    assert again.status_code == 200 and again.json()["can_spend"] is False
    assert AgentRun.objects.filter(workspace=workspace).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("seeded_workspace", [WORKSPACE_A, WORKSPACE_B])
def test_workspace_over_budget_never_touches_the_seeded_workspaces(client, e2e_urls, seeded, seeded_workspace):
    from apps.studio import budget
    from apps.studio.models import AgentRun
    from apps.workspaces.models import Workspace

    workspace = Workspace.objects.get(pk=seeded_workspace)
    runs = AgentRun.objects.filter(workspace=workspace).count()
    answer = _fixture(client, "workspace_over_budget", {"workspace_id": seeded_workspace})
    assert answer.status_code == 400
    assert "make a workspace" in answer.json()["error"]
    assert budget.can_spend(workspace)
    assert AgentRun.objects.filter(workspace=workspace).count() == runs


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [{}, {"workspace_id": "nope"}, {"workspace_id": "", "budget": 1}])
def test_workspace_over_budget_refuses_a_bad_payload(client, e2e_urls, seeded, payload):
    assert _fixture(client, "workspace_over_budget", payload).status_code == 400


@pytest.mark.django_db
def test_workspace_over_budget_refuses_unknown_keys_and_an_unknown_workspace(client, e2e_urls, seeded):
    import uuid

    from apps.studio import budget
    from apps.workspaces.models import Workspace

    made = _fixture(client, "team_workspace", {}).json()
    extra = _fixture(client, "workspace_over_budget", {"workspace_id": made["workspace_id"], "amount": 5})
    assert extra.status_code == 400
    assert budget.can_spend(Workspace.objects.get(pk=made["workspace_id"]))
    assert _fixture(client, "workspace_over_budget", {"workspace_id": str(uuid.uuid4())}).status_code == 400
