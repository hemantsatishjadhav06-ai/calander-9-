"""The Studio pages, through the real URL routing, middleware and permissions."""

import zoneinfo
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.composer.models import PlatformPost
from apps.studio.models import BrandProfile, StudioBrief
from apps.studio.tests.conftest import make_brief, run_all


def _url(name, world, **kwargs):
    return reverse(f"studio:{name}", kwargs={"workspace_id": world.workspace.id, **kwargs})


def _as(client, user):
    client.force_login(user)
    return client


def _messages(response):
    return " ".join(str(m) for m in response.context["messages"]) if response.context else ""


@pytest.fixture
def ready(world, fake_team):
    return run_all(make_brief(world, accounts=[world.linkedin, world.x]))


class TestPages:
    def test_the_studio_opens_for_members(self, client, world):
        response = _as(client, world.viewer).get(_url("index", world))

        assert response.status_code == 200
        html = response.content.decode()
        assert "AI Studio" in html and "Waiting for your approval" in html
        # A viewer can look but not brief the team.
        assert response.context["can_create"] is False
        assert BrandProfile.objects.filter(workspace=world.workspace).exists()

    def test_outsiders_are_kept_out(self, client, world):
        response = _as(client, world.outsider).get(_url("index", world))

        assert response.status_code in (403, 404)

    def test_the_page_says_when_claude_is_not_set_up(self, client, world, settings):
        settings.ANTHROPIC_API_KEY = ""

        response = _as(client, world.owner).get(_url("index", world))

        assert response.context["setup"]["claude_ready"] is False
        assert "ANTHROPIC_API_KEY" in response.content.decode()


class TestBriefing:
    def test_an_editor_briefs_the_team(self, client, world, fake_team):
        response = _as(client, world.editor).post(
            _url("create", world),
            {"idea": "Why landlord shares cost less", "accounts": [str(world.linkedin.pk)], "style_lock": "on"},
        )

        brief = StudioBrief.objects.get(workspace=world.workspace)
        assert response.status_code == 302
        assert response["Location"] == _url("detail", world, brief_id=brief.pk)
        assert brief.author == world.editor
        assert list(brief.social_accounts.all()) == [world.linkedin]
        assert fake_team.queued == [(brief.pk, 1, "strategy")]

    def test_an_empty_idea_is_sent_back(self, client, world, fake_team):
        response = _as(client, world.editor).post(
            _url("create", world), {"idea": "  ", "accounts": [str(world.linkedin.pk)]}
        )

        assert response.status_code == 400
        assert not StudioBrief.objects.exists()

    def test_nothing_runs_without_the_key(self, client, world, fake_team, settings):
        settings.ANTHROPIC_API_KEY = ""

        response = _as(client, world.editor).post(
            _url("create", world),
            {"idea": "Why landlord shares cost less", "accounts": [str(world.linkedin.pk)]},
            follow=True,
        )

        assert "ANTHROPIC_API_KEY" in _messages(response)
        assert not StudioBrief.objects.exists()

    def test_viewers_cannot_brief(self, client, world, fake_team):
        response = _as(client, world.viewer).post(_url("create", world), {"idea": "Anything"})

        assert response.status_code == 403
        assert not StudioBrief.objects.exists()


class TestWatchingAndReviewing:
    def test_progress_while_working_then_a_refresh_when_done(self, client, world, fake_team):
        brief = make_brief(world)
        _as(client, world.editor)

        working = client.get(_url("progress", world, brief_id=brief.pk))
        assert working.status_code == 200
        assert "Content strategist" in working.content.decode()

        run_all(brief)
        done = client.get(_url("progress", world, brief_id=brief.pk))
        assert done["HX-Refresh"] == "true"

    def test_the_ready_post_shows_what_goes_out_and_who_may_approve(self, client, world, ready):
        response = _as(client, world.manager).get(_url("detail", world, brief_id=ready.pk))

        assert response.status_code == 200
        html = response.content.decode()
        assert "Landlord shares typically sit 8–14% under comparable resale." in html
        assert response.context["can_approve"] is True
        assert response.context["can_publish_now"] is True
        assert response.context["cost"] is not None

        editor_view = _as(client, world.editor).get(_url("detail", world, brief_id=ready.pk))
        assert editor_view.context["can_approve"] is False
        assert editor_view.context["can_revise"] is True

    def test_another_workspaces_brief_is_not_found(self, client, world, ready):
        from apps.workspaces.models import Workspace

        other = Workspace.objects.create(organization=world.org, name="More Space")
        from apps.members.models import WorkspaceMembership

        WorkspaceMembership.objects.create(user=world.owner, workspace=other, workspace_role="owner")

        response = _as(client, world.owner).get(
            reverse("studio:detail", kwargs={"workspace_id": other.id, "brief_id": ready.pk})
        )

        assert response.status_code == 404


class TestApproving:
    def test_a_manager_publishes_now(self, client, world, ready):
        response = _as(client, world.manager).post(
            _url("approve", world, brief_id=ready.pk), {"mode": "now"}, follow=True
        )

        assert "publishing now" in _messages(response)
        assert set(PlatformPost.objects.filter(post=ready.post).values_list("status", flat=True)) == {"scheduled"}

    def test_a_manager_schedules_it_for_later(self, client, world, ready):
        when = (timezone.now() + timedelta(days=3)).astimezone(zoneinfo.ZoneInfo(world.workspace.effective_timezone))

        response = _as(client, world.manager).post(
            _url("approve", world, brief_id=ready.pk),
            {"mode": "schedule", "date": when.date().isoformat(), "time": when.strftime("%H:%M")},
            follow=True,
        )

        assert "scheduled for" in _messages(response)
        scheduled = PlatformPost.objects.filter(post=ready.post).values_list("scheduled_at", flat=True)
        assert all(abs((at - when).total_seconds()) < 60 for at in scheduled)

    def test_an_editor_cannot_approve(self, client, world, ready):
        response = _as(client, world.editor).post(_url("approve", world, brief_id=ready.pk), {"mode": "now"})

        assert response.status_code == 403
        assert set(PlatformPost.objects.filter(post=ready.post).values_list("status", flat=True)) == {"pending_review"}

    def test_asking_for_changes_sends_it_back_to_the_copywriter(self, client, world, ready, fake_team):
        response = _as(client, world.editor).post(
            _url("request_changes", world, brief_id=ready.pk), {"feedback": "Lead with the site visit"}
        )

        assert response.status_code == 302
        ready.refresh_from_db()
        assert (ready.revision, ready.stage, ready.feedback) == (2, "copy", "Lead with the site visit")

    def test_discarding_drops_the_draft(self, client, world, ready):
        post_id = ready.post_id

        response = _as(client, world.editor).post(_url("discard", world, brief_id=ready.pk))

        assert response["Location"] == _url("index", world)
        assert StudioBrief.objects.get(pk=ready.pk).status == StudioBrief.Status.DISCARDED
        assert not PlatformPost.objects.filter(post_id=post_id).exists()


class TestBrandProfile:
    def test_owners_and_managers_edit_the_brand(self, client, world):
        _as(client, world.manager).get(_url("brand", world))
        profile = BrandProfile.objects.get(workspace=world.workspace)
        data = {
            "brand_name": "Neopolis Infra",
            "about": "Landlord shares in West Hyderabad.",
            "audience": "First-time buyers",
            "voice": "Plain and exact",
            "facts": "Landlord shares typically sit 8–14% under comparable resale.",
            "dos": "",
            "donts": "",
            "compliance": "",
            "default_cta": "WhatsApp +91 95336 86567",
            "website": "https://www.neopolisinfra.com",
            "hashtags": "#LandlordShare #WestHyderabad",
            "primary_color": "#0a1f44",
            "accent_color": "#ff6600",
            "display_font": profile.display_font,
            "wordmark": "NEOPOLIS",
            "domain": "neopolisinfra.com",
            "logo": "",
            "photo_style": "",
            "default_template": "editorial",
            "default_format": "portrait",
            "default_grade": "brand_tint",
        }

        response = client.post(_url("brand", world), data)

        assert response.status_code == 302, response.context["form"].errors if response.context else ""
        profile.refresh_from_db()
        assert profile.primary_color == "#0A1F44"
        assert profile.voice == "Plain and exact"

    def test_editors_can_read_but_not_change_it(self, client, world):
        _as(client, world.editor)

        assert client.get(_url("brand", world)).context["can_edit"] is False
        assert client.post(_url("brand", world), {"brand_name": "X"}).status_code == 403

    @pytest.mark.parametrize("template", ["editorial", "split", "statement", "stat"])
    def test_sample_graphics_render_in_the_brand_look(self, client, world, template):
        response = _as(client, world.viewer).get(_url("brand_sample", world, template=template))

        assert response.status_code == 200
        assert response["Content-Type"] == "image/jpeg"
        assert response.content[:2] == b"\xff\xd8"

    def test_an_unknown_layout_is_refused(self, client, world):
        assert _as(client, world.viewer).get(_url("brand_sample", world, template="nope")).status_code == 403
