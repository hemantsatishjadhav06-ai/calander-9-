"""Set up: one checklist in plain words, the Settings hub, Home's status line and the Today card."""

from datetime import datetime, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.composer.models import PlatformPost, Post
from apps.members.models import WorkspaceMembership
from apps.studio import autopilot, dashboard, engine, opendots, readiness
from apps.studio.models import AgencyJob, AgencySettings, StudioBrief
from apps.studio.tests.conftest import make_brief, run_all
from apps.studio.tests.test_chat import assert_nothing_approved
from apps.telegram.models import TelegramConnection, TelegramUserLink
from apps.workspaces.models import Workspace


def _url(name, world, **kwargs):
    return reverse(f"studio:{name}", kwargs={"workspace_id": world.workspace.id, **kwargs})


def _rows(html):
    """The checklist rows of a rendered Set up page, keyed by row, with their state."""
    import re

    return dict(re.findall(r'data-setup-row="([a-z_]+)" data-setup-state="([a-z]+)"', html))


def _page(client, world, name, **kwargs):
    """A rendered page as plain text (apostrophes and the like unescaped)."""
    from html import unescape

    return unescape(client.get(_url(name, world, **kwargs)).content.decode())


def _client_member(world):
    user = world.viewer.__class__.objects.create_user(
        email="client@example.com", password="pw-12345678", name="Client", tos_accepted_at=timezone.now()
    )
    WorkspaceMembership.objects.create(user=user, workspace=world.workspace, workspace_role="client")
    return user


# ---------------------------------------------------------------------------
# The checklist
# ---------------------------------------------------------------------------


class TestSetupPage:
    def test_every_row_has_a_state_and_the_header_counts_them(self, client, world):
        client.force_login(world.owner)

        response = client.get(_url("setup", world))

        assert response.status_code == 200
        html = response.content.decode()
        rows = _rows(html)
        assert set(rows) == {
            "ai_team",
            "pictures",
            "accounts",
            "approvers",
            "autopilot",
            "creation_mode",
            "telegram",
            "email",
            "facts",
            "blog",
            "budget",
        }
        assert rows["ai_team"] == "done" and rows["accounts"] == "done" and rows["budget"] == "done"
        assert rows["pictures"] == "todo" and rows["approvers"] == "todo" and rows["autopilot"] == "todo"
        assert rows["creation_mode"] == "done"
        done = sum(1 for state in rows.values() if state == "done")
        assert f"{done} of 11 steps done" in html
        assert response["Cache-Control"] == "no-store, private"

    def test_states_follow_the_services_in_words(self, client, world, settings):
        settings.ANTHROPIC_API_KEY = ""
        client.force_login(world.owner)

        html = client.get(_url("setup", world)).content.decode()

        assert _rows(html)["ai_team"] == "todo"
        assert "Not connected yet. Nothing can be written or planned until it is." in html
        assert "Off. The team only works when someone asks it to." in html
        assert "No verified facts yet" in html

    def test_owners_see_the_exact_names_and_others_are_told_to_ask(self, client, world, settings):
        settings.ANTHROPIC_API_KEY = ""
        client.force_login(world.owner)
        owner_html = client.get(_url("setup", world)).content.decode()
        assert "ANTHROPIC_API_KEY" in owner_html and "FAL_KEY" in owner_html and "For the owner:" in owner_html

        client.force_login(world.manager)
        manager_html = client.get(_url("setup", world)).content.decode()
        assert "ANTHROPIC_API_KEY" not in manager_html and "FAL_KEY" not in manager_html
        assert "Ask your owner." in manager_html

    def test_a_superuser_counts_as_an_owner(self, client, world):
        world.manager.is_superuser = True
        world.manager.save(update_fields=["is_superuser"])
        client.force_login(world.manager)

        html = client.get(_url("setup", world)).content.decode()

        assert "FAL_KEY" in html

    def test_clients_and_outsiders_are_kept_out(self, client, world):
        client.force_login(_client_member(world))
        assert client.get(_url("setup", world)).status_code == 403
        assert client.get(_url("settings_hub", world)).status_code == 403
        assert client.post(_url("setup_lead", world)).status_code == 403
        assert client.post(_url("setup_autopilot", world)).status_code == 403
        assert not AgencySettings.objects.filter(workspace=world.workspace).exists()

        client.force_login(world.outsider)
        assert client.get(_url("setup", world)).status_code in (403, 404)

    def test_rows_only_read_this_workspace(self, client, world):
        other = Workspace.objects.create(organization=world.org, name="Other")
        WorkspaceMembership.objects.create(user=world.owner, workspace=other, workspace_role="owner")
        AgencySettings.objects.create(workspace=other, autopilot_enabled=True, posts_per_week=9, lead=world.owner)
        client.force_login(world.owner)

        html = client.get(_url("setup", world)).content.decode()

        rows = _rows(html)
        assert rows["autopilot"] == "todo" and rows["approvers"] == "todo"
        assert "9 posts a week" not in html

    def test_telegram_row_states(self, client, world, settings):
        client.force_login(world.owner)
        settings.TELEGRAM_WEBHOOK_READY = False
        html = _page(client, world, "setup")
        assert "The deployment isn't ready for Telegram yet." in html and "TELEGRAM_WEBHOOK_READY" in html

        settings.TELEGRAM_WEBHOOK_READY = True
        settings.TELEGRAM_WEBHOOK_BASE_URL = "https://app.example.com"
        html = _page(client, world, "setup")
        assert "Connect your bot" in html

        connection = TelegramConnection.objects.create(
            workspace=world.workspace,
            bot_id=4321,
            bot_username="neopolis_bot",
            token="local-only-placeholder",
            webhook_secret="local-only-placeholder",
            is_active=True,
            webhook_status="active",
        )
        html = _page(client, world, "setup")
        assert "Pair your phone" in html and "@neopolis_bot" in html

        TelegramUserLink.objects.create(connection=connection, user=world.owner, telegram_user_id=99)
        html = _page(client, world, "setup")
        assert "Listening as @neopolis_bot · you're paired." in html and _rows(html)["telegram"] == "done"

    def test_budget_says_estimated_until_a_provider_reports_a_cost(self, client, world, fake_team):
        client.force_login(world.owner)
        run_all(make_brief(world))

        html = client.get(_url("setup", world)).content.decode()

        assert "(estimated)" in html and "of $150.00 used this month" in html


# ---------------------------------------------------------------------------
# The two actions: settings only
# ---------------------------------------------------------------------------


class TestUseMeAsLead:
    def test_an_eligible_person_becomes_the_lead(self, client, world):
        client.force_login(world.manager)

        response = client.post(_url("setup_lead", world))

        assert response.status_code == 302 and response["Location"] == _url("setup", world)
        assert AgencySettings.objects.get(workspace=world.workspace).lead == world.manager
        assert "Lead: Manager" in client.get(_url("setup", world)).content.decode()

    def test_someone_who_cannot_approve_is_refused(self, client, world):
        client.force_login(world.editor)

        assert client.post(_url("setup_lead", world)).status_code == 403
        assert not AgencySettings.objects.filter(workspace=world.workspace).exists()

    def test_replacing_an_existing_lead_needs_the_settings_permission(self, client, world):
        AgencySettings.objects.create(workspace=world.workspace, lead=world.owner)
        client.force_login(world.manager)
        assert client.post(_url("setup_lead", world)).status_code == 403
        assert AgencySettings.objects.get(workspace=world.workspace).lead == world.owner

        client.force_login(world.owner)
        AgencySettings.objects.filter(workspace=world.workspace).update(lead=world.manager)
        assert client.post(_url("setup_lead", world)).status_code == 302
        assert AgencySettings.objects.get(workspace=world.workspace).lead == world.owner

    def test_a_lead_who_left_the_team_counts_as_no_lead_so_the_button_shown_works(self, client, world):
        """The row and the button agree: a departed lead's name is not a seat another eligible person cannot take."""
        AgencySettings.objects.create(workspace=world.workspace, lead=world.owner)
        WorkspaceMembership.objects.filter(workspace=world.workspace, user=world.owner).delete()
        client.force_login(world.manager)

        html = _page(client, world, "setup")
        assert _rows(html)["approvers"] == "todo" and "Use me as lead" in html

        response = client.post(_url("setup_lead", world))

        assert response.status_code == 302
        assert AgencySettings.objects.get(workspace=world.workspace).lead == world.manager
        assert "Lead: Manager" in _page(client, world, "setup")


class TestAutopilotDefaults:
    def test_the_owner_turns_it_on_with_sensible_defaults(self, client, world):
        client.force_login(world.owner)

        response = client.post(_url("setup_autopilot", world), follow=True)

        assert response.status_code == 200
        row = AgencySettings.objects.get(workspace=world.workspace)
        assert row.autopilot_enabled and row.lead == world.owner
        assert row.posts_per_week == 5 and row.plan_weekday == 4 and row.plan_hour == 16
        assert set(row.accounts.all()) == {world.linkedin, world.x}
        assert "Autopilot is on: 5 posts a week, planned every Friday at 16:00" in response.content.decode()
        assert_nothing_approved(world.workspace)
        assert not StudioBrief.objects.exists() and not AgencyJob.objects.exists()

    def test_an_existing_lead_and_posts_per_week_are_kept(self, client, world):
        """The button turns autopilot on; it never quietly makes the presser the lead when one is already chosen."""
        AgencySettings.objects.create(workspace=world.workspace, lead=world.manager, posts_per_week=3)
        client.force_login(world.owner)

        client.post(_url("setup_autopilot", world))

        row = AgencySettings.objects.get(workspace=world.workspace)
        assert row.autopilot_enabled and row.lead == world.manager and row.posts_per_week == 3

    def test_a_saved_lead_who_no_longer_qualifies_is_replaced_by_the_presser(self, client, world):
        AgencySettings.objects.create(workspace=world.workspace, lead=world.editor)  # cannot approve: not eligible
        client.force_login(world.owner)

        client.post(_url("setup_autopilot", world))

        row = AgencySettings.objects.get(workspace=world.workspace)
        assert row.autopilot_enabled and row.lead == world.owner

    def test_only_settings_managers_may_turn_it_on(self, client, world):
        client.force_login(world.manager)

        assert client.post(_url("setup_autopilot", world)).status_code == 403
        assert not AgencySettings.objects.filter(workspace=world.workspace, autopilot_enabled=True).exists()

    def test_it_says_what_is_missing_instead_of_switching_on(self, client, world):
        world.linkedin.delete()
        world.x.delete()
        client.force_login(world.owner)

        response = client.post(_url("setup_autopilot", world), follow=True)

        assert "Still missing: a connected social account." in response.content.decode()
        assert not AgencySettings.objects.get(workspace=world.workspace).autopilot_enabled

    def test_the_page_then_shows_autopilot_as_done(self, client, world):
        client.force_login(world.owner)
        client.post(_url("setup_autopilot", world))

        html = client.get(_url("setup", world)).content.decode()

        assert _rows(html)["autopilot"] == "done" and "On · 5 posts a week, planned every Friday at 16:00" in html


# ---------------------------------------------------------------------------
# Settings hub and the four tabs
# ---------------------------------------------------------------------------


def test_the_settings_hub_links_every_settings_page(client, world):
    client.force_login(world.editor)

    html = client.get(_url("settings_hub", world)).content.decode()

    for key in ("brand", "trust", "memory", "outcomes", "autopilot", "telegram", "budget"):
        assert f'data-settings-card="{key}"' in html
    assert "Open Set up" in html


def test_the_agency_tabs_are_home_routines_team_settings(world):
    tabs = dashboard.tabs(world.workspace, "overview")
    labels = [tab["label"] for tab in tabs]
    assert labels[:1] == ["Home"] and labels[-2:] == ["Team", "Settings"]
    assert "Routines" not in labels or labels[1] == "Routines"  # shown once the Routines page exists
    assert next(tab for tab in tabs if tab["key"] == "overview")["active"]
    for page in ("brand", "trust", "memory", "outcomes", "autopilot", "telegram"):
        active = [tab["key"] for tab in dashboard.tabs(world.workspace, page) if tab["active"]]
        assert active == ["settings"], page
    assert [tab["key"] for tab in dashboard.tabs(world.workspace, "thread") if tab["active"]] == ["overview"]


def test_the_routines_tab_is_only_shown_to_people_who_may_open_it(client, world):
    """A viewer reaches Home; the Routines page needs create_posts, so no tab sends them to a refusal."""
    without = [tab["key"] for tab in dashboard.tabs(world.workspace, "overview", perms={"create_posts": False})]
    assert without == ["overview", "team", "settings"]
    assert "routines" in [
        tab["key"] for tab in dashboard.tabs(world.workspace, "overview", perms={"create_posts": True})
    ]

    client.force_login(world.viewer)
    response = client.get(_url("index", world))
    assert response.status_code == 200
    assert _url("routines", world) not in response.content.decode()
    assert client.get(_url("routines", world)).status_code == 403
    for name in ("settings_hub", "team"):
        assert _url(name, world) not in response.content.decode() or client.get(_url(name, world)).status_code == 200

    client.force_login(world.editor)
    assert _url("routines", world) in client.get(_url("index", world)).content.decode()


def test_settings_pages_light_up_the_settings_tab(client, world):
    client.force_login(world.owner)

    html = client.get(_url("autopilot", world)).content.decode()

    assert 'aria-current="page">Settings</a>' in html


# ---------------------------------------------------------------------------
# Home: the status line, the Today card, the checklist card
# ---------------------------------------------------------------------------


class TestHome:
    def test_the_status_line_says_set_up_autopilot_and_telegram(self, client, world, settings):
        client.force_login(world.owner)

        html = client.get(_url("index", world)).content.decode()

        assert "Set-up:" in html and "steps left" in html and "Open Set up" in html
        assert "Autopilot off" in html and "Turn on" in html
        assert "Telegram: not ready on this deployment yet" in html  # the test deployment has no public origin
        settings.TELEGRAM_WEBHOOK_READY = True
        settings.TELEGRAM_WEBHOOK_BASE_URL = "https://app.example.com"
        assert "connect your bot" in client.get(_url("index", world)).content.decode()

        client.post(_url("setup_autopilot", world))
        html = client.get(_url("index", world)).content.decode()
        assert "Autopilot on · 5 a week" in html

    def test_the_status_line_only_links_to_what_this_person_can_do(self, client, world, settings):
        settings.TELEGRAM_WEBHOOK_READY = True
        settings.TELEGRAM_WEBHOOK_BASE_URL = "https://app.example.com"
        telegram_url = reverse("telegram:settings", kwargs={"workspace_id": world.workspace.id})
        client.force_login(world.editor)  # may create posts, manages nothing

        html = _page(client, world, "index")
        line = html.split("data-home-status>")[1].split("</p>")[0]

        assert "Telegram: ask your owner to connect the bot" in line and telegram_url not in line
        assert "Autopilot off" in line and "Turn on" not in line and "Open Set up" in line
        # The parts wrap on a phone; only a part's link stays on one line.
        assert 'class="whitespace-nowrap">' not in line

        settings.TELEGRAM_WEBHOOK_READY = False
        line = _page(client, world, "index").split("data-home-status>")[1].split("</p>")[0]
        assert "Telegram: not ready on this deployment yet" in line and telegram_url not in line
        client.force_login(world.owner)
        line = _page(client, world, "index").split("data-home-status>")[1].split("</p>")[0]
        assert "Telegram: not ready on this deployment yet" in line and "Open Set up" in line

    def test_the_old_guided_page_redirects_home(self, client, world):
        client.force_login(world.editor)

        response = client.get(_url("workflow", world))

        assert response.status_code == 302 and response["Location"] == _url("index", world)

    def test_the_checklist_card_sits_inside_main_on_home_only(self, client, world):
        client.force_login(world.owner)

        home = client.get(_url("index", world)).content.decode()
        assert 'id="onboarding-checklist"' in home
        assert home.index('id="main-content"') < home.index('id="onboarding-checklist"') < home.index("</main>")
        assert "fixed bottom" not in home.split('id="onboarding-checklist"')[1].split("</section>")[0]

        elsewhere = client.get(
            reverse("calendar:calendar", kwargs={"workspace_id": world.workspace.id})
        ).content.decode()
        assert 'id="onboarding-checklist"' not in elsewhere

    def test_the_sidebar_is_short_with_more_behind_a_disclosure(self, client, world):
        client.force_login(world.owner)

        html = client.get(_url("index", world)).content.decode()

        for label in ("Home", "Approvals", "Calendar", "Inbox", "Blog &amp; SEO", "Set up", "More"):
            assert f'<span class="sidebar-nav-label">{label}</span>' in html, label
        assert '<details class="sidebar-more"' in html
        assert "Start a post" not in html and "customer_workflow" not in html
        for name in ("composer:drafts_list", "calendar:queue_list", "composer:csv_upload", "media_library:index"):
            assert reverse(name, kwargs={"workspace_id": world.workspace.id}) in html

    def test_more_opens_itself_only_on_its_own_pages(self, client, world, fake_team):
        """ "detail" and "list" are not "queue_detail" and "drafts_list": a brief page keeps More closed."""
        client.force_login(world.owner)
        brief = make_brief(world)

        for name, kwargs in (("studio:detail", {"brief_id": brief.pk}), ("studio:index", {}), ("blog:list", {})):
            html = client.get(reverse(name, kwargs={"workspace_id": world.workspace.id, **kwargs})).content.decode()
            assert '<details class="sidebar-more" data-sidebar-more>' in html, name
        drafts = client.get(reverse("composer:drafts_list", kwargs={"workspace_id": world.workspace.id}))
        assert '<details class="sidebar-more" data-sidebar-more open>' in drafts.content.decode()

    def test_links_to_approvers_and_budget_open_the_advanced_section(self, client, world):
        AgencySettings.objects.create(workspace=world.workspace, lead=world.manager)
        client.force_login(world.owner)
        advanced = _url("autopilot", world) + "?open=advanced"

        setup = client.get(_url("setup", world)).content.decode()
        assert setup.count(advanced) == 2  # the approvers' Change, and the budget's Change
        hub = client.get(_url("settings_hub", world)).content.decode()
        assert advanced in hub
        closed = client.get(_url("autopilot", world)).content.decode()
        assert "data-autopilot-advanced>" in closed and "data-autopilot-advanced open>" not in closed
        opened = client.get(advanced).content.decode()
        assert "data-autopilot-advanced open>" in opened


class TestToday:
    def test_waiting_going_out_done_and_next_run(self, client, world, fake_team):
        from apps.calendar.services import create_default_queue_and_slots

        create_default_queue_and_slots(world.linkedin)
        ready = run_all(make_brief(world))
        post = Post.objects.create(workspace=world.workspace, author=world.editor, title="Out today")
        # Later today in the workspace's time zone, whatever the clock says: "now + 30 minutes"
        # is tomorrow between 23:30 and midnight there.
        now = timezone.now()
        local = now.astimezone(dashboard._zone(world.workspace))
        day_end = datetime.combine(local.date(), datetime.min.time(), tzinfo=local.tzinfo) + timedelta(days=1)
        PlatformPost.objects.create(
            post=post, social_account=world.x, status="scheduled", scheduled_at=now + (day_end - local) / 2
        )
        AgencySettings.objects.create(workspace=world.workspace, autopilot_enabled=True, lead=world.owner)

        today = dashboard.today(world.workspace, world.owner)

        assert [row["brief"] for row in today["waiting"]] == [ready] and today["waiting_count"] == 1
        assert [row["label"] for row in today["going_out"]] == ["Out today"]
        assert today["done"][0]["label"] == f"Draft ready: {ready.title}"
        assert today["next_run"] is not None and not today["quiet"]
        assert today["needs_review"] == []

        client.force_login(world.owner)
        html = client.get(_url("index", world)).content.decode()
        assert "Waiting for you" in html and 'name="mode" value="proposed"' in html
        assert "Going out today" in html and "Done since yesterday" in html and "Next planned run" in html

    def test_a_quiet_day_says_so(self, world):
        today = dashboard.today(world.workspace, world.owner)
        assert today["quiet"] and today["waiting"] == [] and today["next_run"] is None

    def test_paused_failed_and_interrupted_tasks_need_review(self, world, monkeypatch):
        monkeypatch.setattr(engine, "enqueue", lambda job, stage: None)
        failed = engine.create(world.workspace, "report", title="Weekly report", requested_by=world.owner)
        AgencyJob.objects.filter(pk=failed.pk).update(status=AgencyJob.Status.FAILED, error="Boom.")
        interrupted = engine.create(world.workspace, "report", title="Plan", requested_by=world.owner)
        assert "worker" not in engine.INTERRUPTED_ERROR
        AgencyJob.objects.filter(pk=interrupted.pk).update(
            status=AgencyJob.Status.FAILED, error=engine.INTERRUPTED_ERROR
        )
        paused = engine.create(world.workspace, "report", title="Learn", requested_by=world.owner)
        AgencyJob.objects.filter(pk=paused.pk).update(
            status=AgencyJob.Status.CANCELLED, state={"_opendots_control": {"paused": True}}
        )
        stopped = engine.create(world.workspace, "report", title="Stopped", requested_by=world.owner)
        AgencyJob.objects.filter(pk=stopped.pk).update(status=AgencyJob.Status.CANCELLED)

        rows = dashboard.needs_review(world.workspace)

        assert {row["title"] for row in rows} == {"Weekly report", "Plan", "Learn"}
        assert {row["label"] for row in rows} == {
            "Needs your attention",
            "Interrupted — review before retrying",
            "Paused by you",
        }
        assert all(row["url"] for row in rows)

    def test_lists_read_the_task_state_without_the_signed_effect_review(self, world, monkeypatch):
        """Home's rows and the briefing's counts never hash a job's runs and briefs: only the task page does."""
        from apps.studio import briefing

        monkeypatch.setattr(engine, "enqueue", lambda job, stage: None)
        for n in range(3):
            job = engine.create(world.workspace, "report", title=f"Report {n}", requested_by=world.owner)
            AgencyJob.objects.filter(pk=job.pk).update(status=AgencyJob.Status.FAILED, error="Boom.")

        def never(job):
            raise AssertionError("a list computed the effect digest")

        monkeypatch.setattr(opendots, "_effect_digest", never)
        assert len(dashboard.needs_review(world.workspace)) == 3
        assert briefing._task_counts(world.workspace) == {"paused": 0, "failed": 3, "interrupted": 0}
        with pytest.raises(AssertionError):
            opendots.task_record(AgencyJob.objects.first())

    def test_private_telegram_jobs_stay_out_of_the_card(self, world, monkeypatch):
        from apps.studio.models import Conversation

        monkeypatch.setattr(engine, "enqueue", lambda job, stage: None)
        private = Conversation.objects.create(
            workspace=world.workspace, audience="internal", is_private=True, created_by=world.editor
        )
        job = engine.create(world.workspace, "report", title="Private", requested_by=world.editor, conversation=private)
        AgencyJob.objects.filter(pk=job.pk).update(status=AgencyJob.Status.FAILED, error="Boom.")

        assert dashboard.needs_review(world.workspace) == []


# ---------------------------------------------------------------------------
# Readiness copy and the waiting-on-policy task state
# ---------------------------------------------------------------------------


def test_readiness_speaks_plainly_and_points_at_set_up(world, settings):
    settings.ANTHROPIC_API_KEY = ""
    settings.TELEGRAM_WEBHOOK_READY = True  # the deployment is ready; there is just no bot yet
    settings.TELEGRAM_WEBHOOK_BASE_URL = "https://app.example.com"
    world.linkedin.delete()
    world.x.delete()

    state = readiness.operational_readiness(world.workspace, world.owner)

    assert state["blockers"][:2] == [
        "Your AI team isn't connected yet — open Set up.",
        "Connect a social account in Set up.",
    ]
    assert "Automatic work hasn't run recently; open Set up to check." in state["warnings"]
    assert state["line"] == state["blockers"][0] and state["setup_url"] == _url("setup", world)
    assert state["telegram"]["state"] == "setup_needed"
    for text in state["blockers"] + state["warnings"] + [state["title"], state["line"]]:
        for banned in ("API_KEY", "worker", "operator", "lead", "FAL", "administrator"):
            assert banned not in text, text


def test_a_queued_job_held_by_the_autopilot_switch_shows_as_waiting_on_policy(client, world, monkeypatch):
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: None)
    job = engine.create(world.workspace, "report", title="Plan", requested_by=world.editor)
    assert opendots.task_record(job)["status"] == "queued"
    AgencyJob.objects.filter(pk=job.pk).update(error=autopilot.AUTOPILOT_PAUSED)
    job.refresh_from_db()

    record = opendots.task_record(job)

    assert record["status"] == "waiting_policy" and record["label"] == "Paused: autopilot is off"
    assert record["policy_url"] == _url("autopilot", world)
    # The control rules are those of the queued job underneath.
    assert record["can_pause"] and record["can_cancel"] and not record["can_resume"] and not record["can_retry"]
    client.force_login(world.editor)
    html = client.get(_url("job", world, job_id=job.pk)).content.decode()
    assert "data-task-waiting-policy" in html and "open Autopilot" in html


def test_a_queued_job_held_for_the_provider_points_at_set_up_not_autopilot(client, world, monkeypatch):
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: None)
    job = engine.create(world.workspace, "plan", title="Plan", requested_by=world.editor)
    AgencyJob.objects.filter(pk=job.pk).update(error=autopilot.PROVIDER_PAUSED)
    job.refresh_from_db()

    record = opendots.task_record(job)

    assert record["status"] == "waiting_setup" and record["label"] == "Waiting for Set up"
    assert record["policy_url"] == _url("setup", world) and record["policy_link"] == "open Set up"
    assert "autopilot" not in record["label"].lower() and "autopilot" not in record["policy_note"].lower()
    assert record["can_pause"] and record["can_cancel"] and not record["can_resume"]
    client.force_login(world.editor)
    html = client.get(_url("job", world, job_id=job.pk)).content.decode()
    assert "Waiting for Set up" in html and "open Set up" in html and "open Autopilot" not in html


def test_the_pages_pass_the_accessibility_sweep(client, world):
    from apps.common.tests.test_a11y_sweep import FAINT_TEXT, _Audit

    client.force_login(world.owner)
    for name in ("setup", "settings_hub", "index"):
        html = client.get(_url(name, world)).content.decode()
        audit = _Audit()
        audit.feed(html)
        audit.finish()
        assert audit.unnamed_buttons == [] and audit.unnamed_controls == [], name
        faint = [m.group(3) for m in FAINT_TEXT.finditer(html) if m.group(3).strip() not in ("•", "·", "&bull;")]
        assert faint == [], name


# ---------------------------------------------------------------------------
# Integration: creation mode on Set up and Autopilot, one Telegram state helper
# ---------------------------------------------------------------------------


class TestCreationMode:
    def test_the_row_switches_the_mode_with_one_tap_and_comes_back(self, client, world):
        client.force_login(world.owner)

        html = _page(client, world, "setup")
        assert _rows(html)["creation_mode"] == "done"
        assert "Ask me first:" in html and "Switch to “Just go ahead”" in html
        assert 'name="mode" value="auto"' in html and f'name="next" value="{_url("setup", world)}"' in html

        response = client.post(_url("creation_mode", world), {"mode": "auto", "next": _url("setup", world)})

        assert response.status_code == 302 and response["Location"] == _url("setup", world)
        assert AgencySettings.objects.get(workspace=world.workspace).creation_mode == "auto"
        html = _page(client, world, "setup")
        assert "Just go ahead:" in html and "Switch to “Ask me first”" in html and 'name="mode" value="confirm"' in html

    def test_the_thread_header_matches_the_mode(self, client, world):
        """Home's conversation header promises a tap only when there is one."""
        client.force_login(world.owner)
        assert "one tap starts it" in _page(client, world, "index")

        client.post(_url("creation_mode", world), {"mode": "auto"})

        home = _page(client, world, "index")
        assert "goes ahead with sensible defaults" in home and "one tap starts it" not in home

    def test_only_settings_managers_get_the_button(self, client, world):
        client.force_login(world.editor)
        html = _page(client, world, "setup")
        assert _rows(html)["creation_mode"] == "done"
        # "Your manager" is the AI manager everywhere on Home; a person with the permission is named as such.
        assert "Switch to" not in html and "Ask someone who manages this workspace's settings to change it." in html
        assert "Ask your manager" not in html
        assert client.post(_url("creation_mode", world), {"mode": "auto"}).status_code == 403
        assert not AgencySettings.objects.filter(workspace=world.workspace, creation_mode="auto").exists()

    def test_the_autopilot_page_shows_and_saves_the_mode(self, client, world):
        from apps.studio.tests.test_autopilot import _form

        client.force_login(world.owner)
        html = client.get(_url("autopilot", world)).content.decode()
        assert "data-creation-mode-field" in html and 'name="creation_mode"' in html
        assert "Go ahead unless I say stop" in html and "Show me the brief first" in html

        response = client.post(_url("autopilot", world), _form(world, creation_mode="auto"))

        assert response.status_code == 302
        assert AgencySettings.objects.get(workspace=world.workspace).creation_mode == "auto"
        # A save without the field keeps the choice.
        client.post(_url("autopilot", world), _form(world))
        assert AgencySettings.objects.get(workspace=world.workspace).creation_mode == "auto"


class TestTelegramState:
    def test_one_helper_feeds_set_up_the_status_line_readiness_and_the_telegram_page(self, client, world, settings):
        from apps.telegram import state as telegram

        settings.TELEGRAM_WEBHOOK_READY = False
        state = readiness.telegram_state(world.workspace, world.owner)
        assert state["state"] == "deployment_needed" and state["deployment_ready"] is False
        assert state["bot_state"] == "missing" and not telegram.deployment_ready()
        client.force_login(world.owner)
        assert _rows(_page(client, world, "setup"))["telegram"] == "todo"
        assert "Telegram: not ready on this deployment yet" in client.get(_url("index", world)).content.decode()

        settings.TELEGRAM_WEBHOOK_READY = True
        settings.TELEGRAM_WEBHOOK_BASE_URL = "https://app.example.com"
        assert readiness.telegram_state(world.workspace, world.owner)["state"] == "setup_needed"
        assert telegram.deployment_ready()
        connection = TelegramConnection.objects.create(
            workspace=world.workspace,
            bot_id=4321,
            bot_username="neopolis_bot",
            token="local-only-placeholder",
            webhook_secret="local-only-placeholder",
            is_active=True,
            webhook_status="active",
        )
        state = readiness.telegram_state(world.workspace, world.owner)
        assert (
            state["state"] == "pairing_needed" and state["bot_state"] == telegram.bot_state(connection) == "listening"
        )
        assert "pair your phone" in client.get(_url("index", world)).content.decode()

        TelegramUserLink.objects.create(connection=connection, user=world.owner, telegram_user_id=99)
        state = readiness.telegram_state(world.workspace, world.owner)
        assert state["state"] == "ready" and state["paired"] and state["label"].endswith("you're paired")
        assert readiness.operational_readiness(world.workspace, world.owner)["telegram"] == state
        assert state["label"] in _page(client, world, "index")
        page = client.get(reverse("telegram:settings", kwargs={"workspace_id": world.workspace.id}))
        assert page.status_code == 200 and page.context["bot_state"] == "listening"
        assert page.context["deployment_ready"] is True and page.context["paired"] is True

        TelegramConnection.objects.filter(pk=connection.pk).update(webhook_status="setup_in_progress")
        assert readiness.telegram_state(world.workspace, world.owner)["bot_state"] == "connecting"
        assert readiness.telegram_state(world.workspace)["state"] == "setup_needed"
