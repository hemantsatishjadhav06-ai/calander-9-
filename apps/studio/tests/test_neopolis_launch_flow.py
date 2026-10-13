"""Neopolis launch rehearsal through real intake, rendering, approval and delivery.

Every external boundary is offline: public website/Meta GETs use MockTransport,
agents return safe owner-supplied site-visit copy, and only the final provider
publish method is stubbed. The service/database/renderer/publisher flow is real.
This does not attest the seeded commercial claims or live channel permissions.
"""

from __future__ import annotations

import json
import socket
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from django.core.serializers.json import DjangoJSONEncoder
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.approvals.actor import API, acting_as
from apps.approvals.models import ApprovalAction
from apps.calendar.services import create_default_queue_and_slots
from apps.composer.models import PlatformPost, Post
from apps.publisher import engine as publisher
from apps.settings_manager.models import WorkspaceSetting
from apps.social_accounts.models import SocialAccount
from apps.studio import agents, budget, chat, creative_sources, engine, reports, services
from apps.studio.brand_defaults import ensure_profile
from apps.studio.creative_brief import CreativeBrief
from apps.studio.models import AgencyJob, AgencySettings, Message, StudioBrief
from apps.studio.roles import client as client_roles
from apps.studio.roles import creative, insights
from apps.studio.schemas import Concept, StrategistAnswer
from apps.studio.tests.conftest import _result, run_all
from apps.studio.tests.test_chat import drive
from apps.studio.tests.test_insights import drive as drive_report
from apps.workspaces.brands import BRAND_KEY
from apps.workspaces.models import Workspace
from providers.facebook import FacebookProvider
from providers.types import PublishResult

pytestmark = pytest.mark.django_db(transaction=True)
_HTTP_CLIENT = httpx.Client
PAGE_ID = "585141221346435"  # docs/LIVE_OPERATIONS.md: Graph Page ID, not the profile URL ID.
SAFE_CAPTION = (
    "Explore your next home in West Hyderabad.\n\n"
    "Contact Neopolis Infra to discuss your needs and arrange a site visit. "
    "Ask the team about current availability before making plans.\n\n"
    "WhatsApp or call +91 95336 86567."
)
UNVERIFIED_IMAGE_NOTE = "Image provenance has not been verified for this project."


def _brief_fields(**changes):
    fields = {
        "topic": "Invite families to arrange a Neopolis site visit",
        "goal": "leads",
        "audience": "Families looking for a home in West Hyderabad",
        "key_message": "Speak to the Neopolis team to discuss a home and arrange a site visit.",
        "call_to_action": "WhatsApp or call +91 95336 86567 to ask about current availability.",
        "channels": ["facebook"],
        "visual_direction": "Use the supplied owner photo with navy and orange brand type, portrait layout.",
        "references": "Use the brand direction and the supplied photo; no invented project render.",
        "constraints": "No discount, price, possession date, guaranteed return, RERA or availability claims.",
    }
    return {**fields, **changes}


@pytest.fixture
def launch(world, fake_team, photo, settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = tmp_path
    settings.APP_URL = "https://manager.example"
    workspace = world.workspace
    workspace.require_dashboard_approval = True
    workspace.approval_workflow_mode = Workspace.ApprovalWorkflowMode.REQUIRED_INTERNAL
    workspace.save(update_fields=["require_dashboard_approval", "approval_workflow_mode"])
    WorkspaceSetting.objects.create(workspace=workspace, key=BRAND_KEY, value="neopolis")
    profile = ensure_profile(workspace)
    assert profile.website == "https://www.neopolisinfra.com"
    account = SocialAccount.objects.create(
        workspace=workspace,
        platform="facebook",
        account_platform_id=PAGE_ID,
        account_name="Neopolis Infra",
        account_handle="neopolisinfra",
        oauth_access_token="OFFLINE-NEOPOLIS-PAGE-TOKEN",
    )
    create_default_queue_and_slots(account)
    agency = AgencySettings.objects.create(
        workspace=workspace,
        autopilot_enabled=True,
        posts_per_week=3,
        pillars=["Site visits", "Buyer questions"],
        monthly_budget_usd=Decimal("25"),
        lead=world.owner,
    )
    agency.accounts.set([account])
    supplied_photo = photo(filename="owner-supplied-site-visit.jpg")
    other = Workspace.objects.create(organization=world.org, name="More Space", timezone="Asia/Kolkata")
    other_account = SocialAccount.objects.create(
        workspace=other,
        platform="facebook",
        account_platform_id="1282011328339050",
        account_name="More Space",
        oauth_access_token="OFFLINE-MORE-SPACE-SECRET",
    )
    foreign_post = Post.objects.create(workspace=other, author=world.owner, caption="MORE-SPACE-PRIVATE-CAMPAIGN")
    PlatformPost.objects.create(
        post=foreign_post,
        social_account=other_account,
        status="published",
        published_at=timezone.now() - timedelta(days=1),
        platform_post_id="foreign-published-id",
    )
    queued = []
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: queued.append((job.pk, stage)))
    source_requests = []
    source_failure = {"enabled": False}

    def respond(request):
        source_requests.append(request)
        if source_failure["enabled"]:
            raise httpx.ConnectError("PRIVATE-UPSTREAM-ERROR")
        if request.headers["Host"] == "www.neopolisinfra.com":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                text="<title>Neopolis Infra</title><p>Contact our team to arrange a site visit in West Hyderabad.</p>",
            )
        assert request.headers["Host"] == "graph.facebook.com"
        assert request.url.path == f"/v25.0/{PAGE_ID}/posts"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": f"{PAGE_ID}_previous", "message": SAFE_CAPTION, "created_time": "2026-10-10T09:00:00+0000"}
                ]
            },
        )

    local_dns = socket.getaddrinfo

    def source_dns(host, port, *args, **kwargs):
        # The real publisher reconnects PostgreSQL in worker threads. Keep
        # that local database resolution intact; only source hosts are fake.
        if host not in {"www.neopolisinfra.com", "graph.facebook.com"}:
            return local_dns(host, port, *args, **kwargs)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port))]

    monkeypatch.setattr("apps.common.validators.socket.getaddrinfo", source_dns)
    monkeypatch.setattr(
        creative_sources,
        "get_client",
        lambda: _HTTP_CLIENT(
            transport=httpx.MockTransport(respond), timeout=8, follow_redirects=False, trust_env=False
        ),
    )
    fake_team.copy.update(
        caption=SAFE_CAPTION,
        hashtags=["#NeopolisInfra", "#WestHyderabad"],
        first_comment="",
        short_caption="Contact Neopolis Infra to arrange a site visit in West Hyderabad.",
        alt_text="Neopolis Infra site-visit invitation in navy and orange over the owner's supplied photo.",
        headline="Find your next home",
        subheadline="Arrange a site visit in West Hyderabad",
        kicker="Site visits",
        cta_label="Speak to Neopolis",
        stat_value="",
        stat_label="",
        notes="Invite contact without making commercial or availability claims.",
    )
    fake_team.design.update(
        template="editorial",
        format="portrait",
        grade="natural",
        headline="Find your next home",
        subheadline="Arrange a site visit in West Hyderabad",
        kicker="Site visits",
        cta_label="Speak to Neopolis",
        stat_value="",
        stat_label="",
    )

    def strategist(brief, profile, recent):
        fake_team.calls["strategist"].append({"brief": brief, "recent": recent})
        return _result(
            StrategistAnswer(
                concepts=[
                    Concept(
                        title=title,
                        hook="Find your next home in West Hyderabad",
                        angle="Invite a conversation with the team.",
                        key_points=["Discuss your needs", "Arrange a site visit"],
                        post_format="single_image",
                        rationale="A clear next step without unsupported commercial claims.",
                        recommended=index == 0,
                    )
                    for index, title in enumerate(
                        ["Arrange a site visit", "Ask your buyer questions", "Discuss your next home"]
                    )
                ]
            )
        )

    def channel_editor(profile, post_copy, destinations):
        fake_team.calls.setdefault("channel_editor", []).append({"destinations": destinations})
        return _result(
            creative.ChannelAnswer(
                versions=[
                    creative.ChannelVersion(platform=item["platform"], caption=post_copy["caption"])
                    for item in destinations
                ],
                notes="Keep the confirmed site-visit message on the selected Neopolis Page.",
            )
        )

    monkeypatch.setattr(agents, "strategist", strategist)
    monkeypatch.setattr(creative, "channel_editor", channel_editor)
    manager = SimpleNamespace(fields=_brief_fields(audience="", call_to_action=""), action="new_post", calls=[])

    def account_manager(profile, **kwargs):
        manager.calls.append(kwargs)
        return _result(
            client_roles.ChatAnswer(
                reply="Please confirm the audience and contact action for this site-visit post.",
                action=manager.action,
                instructions="Shorten the site-visit caption, retaining the confirmed contact details.",
                creative_brief=CreativeBrief(**manager.fields) if manager.fields is not None else None,
                needs_human=False,
                reason="Confirm the human's brief before drafting.",
            )
        )

    monkeypatch.setattr(client_roles, "account_manager", account_manager)
    deliveries = []

    class OfflineFacebook(FacebookProvider):
        def publish_post(self, access_token, content):
            assert access_token == "OFFLINE-NEOPOLIS-PAGE-TOKEN"
            assert self.credentials["page_id"] == PAGE_ID
            # Facebook's native provider fetches hosted media URLs. Keep its
            # real transport contract: the engine must not download images.
            assert not content.media_files and content.media_urls
            assert content.media_urls[0].startswith("https://manager.example/media/")
            assert content.media_alt_texts
            deliveries.append(content)
            return PublishResult(
                platform_post_id=f"{PAGE_ID}_launch-{len(deliveries)}", url="https://facebook.example/launch", extra={}
            )

    def provider_factory(platform, credentials):
        assert platform == "facebook"
        return OfflineFacebook(credentials)

    monkeypatch.setattr(publisher, "get_provider", provider_factory)
    return SimpleNamespace(
        world=world,
        profile=profile,
        account=account,
        other=other,
        photo=supplied_photo,
        team=fake_team,
        manager=manager,
        source_requests=source_requests,
        source_failure=source_failure,
        deliveries=deliveries,
    )


def _intake(launch):
    world = launch.world
    conversation = chat.general_conversation(world.workspace, created_by=world.editor)
    first = drive(
        chat.post_message(
            conversation,
            world.editor,
            "Create a Facebook post inviting families to a site visit. Ask what you need.",
            reference_id=str(launch.photo.pk),
            style_mode="fresh",
        ).job
    )
    assert first.status == AgencyJob.Status.DONE, first.error
    assert not first.result["awaiting_confirmation"]
    first_reply = Message.objects.get(pk=first.result["message_id"])
    assert 1 <= first_reply.body.count("?") <= 3
    assert not StudioBrief.objects.filter(workspace=world.workspace).exists()
    assert not Post.objects.filter(workspace=world.workspace).exists()
    launch.manager.fields = _brief_fields()
    second = drive(
        chat.post_message(
            conversation,
            world.editor,
            "Families in West Hyderabad; ask them to WhatsApp +91 95336 86567. No price or availability claims.",
        ).job
    )
    assert second.status == AgencyJob.Status.DONE, second.error
    assert second.result["awaiting_confirmation"]
    assert launch.manager.calls[-1]["creative_brief"]["topic"] == first.result["creative_brief"]["topic"]
    assert chat.general_conversation(world.workspace).pk == conversation.pk
    assert len(launch.source_requests) == 2  # one website and one Page read, retained while answering questions
    snapshot = json.dumps(second.result)
    assert "MORE-SPACE-PRIVATE" not in snapshot and "OFFLINE-" not in snapshot
    return conversation, Message.objects.get(pk=second.result["message_id"])


def _confirm(launch, conversation, reply):
    confirmation = drive(
        chat.post_message(
            conversation,
            launch.world.editor,
            "I checked the facts and account. Create the draft for human approval.",
            kind="confirm_brief",
            confirmation_message_id=str(reply.pk),
            facts_confirmed=True,
        ).job
    )
    assert confirmation.status == AgencyJob.Status.DONE, confirmation.error
    return StudioBrief.objects.get(pk=confirmation.result["brief_id"])


def _ready(launch):
    conversation, reply = _intake(launch)
    brief = run_all(_confirm(launch, conversation, reply))
    assert brief.status == StudioBrief.Status.READY, brief.error
    return conversation, brief


def _approve_now(client, launch, brief):
    client.force_login(launch.world.owner)
    response = client.post(
        reverse(
            "studio:approve",
            kwargs={
                "workspace_id": launch.world.workspace.pk,
                "brief_id": brief.pk,
            },
        ),
        {"mode": "now"},
    )
    assert response.status_code == 302
    brief.refresh_from_db()
    pp = brief.post.platform_posts.get()
    assert brief.status == StudioBrief.Status.APPROVED and pp.status == PlatformPost.Status.SCHEDULED
    assert pp.approved_by_id == launch.world.owner.pk and pp.approved_fingerprint
    return pp


def test_neopolis_site_visit_reaches_real_graphic_human_delivery_usage_and_scoped_report(launch, client, monkeypatch):
    conversation, brief = _ready(launch)
    assert brief.source_picture_id == launch.photo.pk and brief.picture_id == launch.photo.pk
    assert brief.style_lock is False and brief.job.conversation_id == conversation.pk
    assert brief.graphic_id and brief.post_id
    with Image.open(brief.graphic.file.path) as image:
        assert image.size == (1080, 1350)
        image.verify()
    pp = brief.post.platform_posts.get()
    assert pp.social_account_id == launch.account.pk and pp.status == "pending_review"
    expected_caption = f"{SAFE_CAPTION}\n\n{UNVERIFIED_IMAGE_NOTE}"
    assert brief.post_copy["visual_note"] == UNVERIFIED_IMAGE_NOTE
    assert pp.effective_caption == expected_caption
    assert not pp.approved_fingerprint and pp.approved_by_id is None
    assert not ApprovalAction.objects.filter(post=brief.post, action="approved").exists()
    assert publisher.PublishEngine().poll_and_publish() == 0 and not launch.deliveries
    with acting_as(launch.world.owner, API), pytest.raises(services.StudioActionError):
        services.approve(brief, launch.world.owner, publish_now=True)
    client.force_login(launch.world.editor)
    assert (
        client.post(
            reverse(
                "studio:approve",
                kwargs={
                    "workspace_id": brief.workspace_id,
                    "brief_id": brief.pk,
                },
            ),
            {"mode": "now"},
        ).status_code
        == 403
    )
    pp = _approve_now(client, launch, brief)
    audit = ApprovalAction.objects.filter(platform_post=pp, action="approved").get()
    assert audit.user_id == launch.world.owner.pk and audit.channel == "dashboard"
    assert audit.fingerprint == pp.approved_fingerprint
    assert publisher.PublishEngine().poll_and_publish() == 1
    pp.refresh_from_db()
    assert pp.status == "published" and pp.platform_post_id.startswith(PAGE_ID), pp.publish_error
    assert len(launch.deliveries) == 1 and launch.deliveries[0].text == expected_caption
    assert publisher.PublishEngine().poll_and_publish() == 0 and len(launch.deliveries) == 1
    assert brief.runs.filter(input_tokens__gt=0, status="succeeded").exists()
    assert budget.month_spend(launch.world.workspace) > 0 and budget.month_spend(launch.other) == 0
    reporter_calls = []

    def reporter(profile, facts, *, audience):
        reporter_calls.append(facts)
        return _result(
            insights.ReportAnswer(
                title="Neopolis launch week",
                summary="One site-visit invitation went out on Facebook.",
                sections=[insights.ReportSection(kind="went_out", heading="What went out", body="One Facebook post.")],
            )
        )

    monkeypatch.setattr(insights, "reporter", reporter)
    job = drive_report(engine.create(launch.world.workspace, "report"))
    assert job.status == AgencyJob.Status.DONE, job.error
    report = reports.latest_report(launch.world.workspace)
    assert report["went_out"] == {"Facebook": 1}
    public_report = json.dumps(report, cls=DjangoJSONEncoder)
    assert "MORE-SPACE-PRIVATE" not in public_report + str(reporter_calls)
    assert "OFFLINE-" not in public_report + str(reporter_calls)
    assert set(report) == {
        "id",
        "title",
        "summary",
        "sections",
        "period",
        "went_out",
        "created_at",
        "operations",
        "operation_scope",
        "operations_as_of",
        "performance_note",
        "outcomes",
        "outcome_note",
        "current_backlog",
    }


def test_neopolis_changed_approved_content_requires_a_fresh_human_approval(launch, client):
    conversation, brief = _ready(launch)
    pp = _approve_now(client, launch, brief)
    original_graphic = brief.graphic_id
    pp.platform_specific_caption = pp.effective_caption + "\nAsk us your buyer questions."
    pp.save(update_fields=["platform_specific_caption"])
    pp.refresh_from_db()
    assert pp.status == "pending_review" and not pp.approved_fingerprint
    assert ApprovalAction.objects.filter(platform_post=pp, action="approval_withdrawn").exists()
    assert publisher.PublishEngine().poll_and_publish() == 0 and not launch.deliveries
    launch.manager.action = "revise_copy"
    launch.manager.fields = None
    launch.team.copy["caption"] = "Arrange a site visit with Neopolis Infra. WhatsApp +91 95336 86567."
    # The single linked draft must reopen after approval was withdrawn, while
    # preserving the need for a fresh human approval of the rendered revision.
    changed = drive(
        chat.post_message(
            conversation,
            launch.world.editor,
            "Shorten this draft without adding new claims.",
        ).job
    )
    assert changed.status == AgencyJob.Status.DONE, changed.error
    assert changed.result["brief_id"] == str(brief.pk)
    brief = run_all(brief)
    assert brief.status == "ready" and brief.revision == 2, brief.error
    assert brief.graphic_id != original_graphic
    pp.refresh_from_db()
    assert pp.status == "pending_review" and not pp.approved_fingerprint
    expected_caption = f"{launch.team.copy['caption']}\n\n{UNVERIFIED_IMAGE_NOTE}"
    assert brief.post_copy["visual_note"] == UNVERIFIED_IMAGE_NOTE
    assert pp.effective_caption == expected_caption
    assert publisher.PublishEngine().poll_and_publish() == 0 and not launch.deliveries
    _approve_now(client, launch, brief)
    assert publisher.PublishEngine().poll_and_publish() == 1
    pp.refresh_from_db()
    assert len(launch.deliveries) == 1, pp.publish_error
    assert launch.deliveries[0].text == expected_caption


def test_neopolis_source_failure_and_creative_failure_leave_no_publishable_post(launch):
    launch.source_failure["enabled"] = True
    conversation, reply = _intake(launch)
    snapshot = reply.job.result["sources"]
    assert snapshot["website"]["status"] == "unavailable"
    assert (
        next(item for item in snapshot["channels"] if item["account_id"] == str(launch.account.pk))["source"]
        == "stored_history"
    )
    with pytest.raises(chat.ChatError, match="source facts"):
        chat.post_message(
            conversation,
            launch.world.editor,
            "Create it",
            kind="confirm_brief",
            confirmation_message_id=str(reply.pk),
            facts_confirmed=False,
        )
    assert not StudioBrief.objects.filter(workspace=launch.world.workspace).exists()
    launch.team.fail["copywriter"] = "The configured model provider is temporarily unavailable."
    brief = run_all(_confirm(launch, conversation, reply))
    assert brief.status == "failed" and "temporarily unavailable" in brief.error
    assert not brief.post_id and not Post.objects.filter(workspace=launch.world.workspace).exists()
    assert budget.month_spend(launch.world.workspace) > 0
    assert publisher.PublishEngine().poll_and_publish() == 0 and not launch.deliveries


def test_neopolis_cut_off_graphic_is_held_even_when_model_reviewer_approves(launch):
    launch.team.design["headline"] = "A very long unsupported graphic heading " * 200
    conversation, reply = _intake(launch)
    brief = run_all(_confirm(launch, conversation, reply))
    assert brief.status == "failed", brief.error
    assert "graphic" in brief.error.lower() and not brief.post_id
    assert brief.graphic_id
    assert not Post.objects.filter(workspace=launch.world.workspace).exists()
    assert publisher.PublishEngine().poll_and_publish() == 0 and not launch.deliveries
