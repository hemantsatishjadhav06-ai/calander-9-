"""Human callback proofs exercise the canonical gate and publisher boundary."""

from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.approvals import gate, services
from apps.approvals.actor import API, DASHBOARD, PORTAL, TELEGRAM, acting_as
from apps.approvals.models import ApprovalAction
from apps.approvals.test_gate import _pending, _world
from apps.composer.models import PlatformPost, Post, PostMedia
from apps.media_library.models import MediaAsset
from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
from apps.publisher import delivery
from apps.publisher.engine import PublishEngine
from apps.studio.guards import AgentMayNotApproveError, agent_work
from apps.studio.models import AgencyJob, Conversation, Message, StudioBrief
from apps.telegram import actions
from apps.telegram.models import TelegramAction, TelegramChat, TelegramConnection, TelegramUserLink


@pytest.fixture
def world(db):
    ws, owner, editor, client, account = _world()
    for person in (editor, client):
        OrgMembership.objects.create(user=person, organization=ws.organization)
    conn = TelegramConnection.objects.create(
        workspace=ws,
        token="dummy",
        webhook_secret="dummy",
        bot_id=123456,
        bot_username="neopolis_test",
        is_active=True,
        approvals_enabled=True,
        created_by=owner,
    )
    convo = Conversation.objects.create(workspace=ws, audience="internal", created_by=owner)
    chat = TelegramChat.objects.create(
        connection=conn, chat_id=-1008888, chat_type="supergroup", audience="team", conversation=convo
    )
    link = TelegramUserLink.objects.create(connection=conn, user=owner, telegram_user_id=987654)
    when = timezone.now() + timedelta(days=2)
    post = _pending(ws, editor, account, when=when)
    return {
        "ws": ws,
        "owner": owner,
        "editor": editor,
        "client": client,
        "account": account,
        "conn": conn,
        "chat": chat,
        "link": link,
        "post": post,
        "when": when,
    }


def callback(world, kind="approve_schedule", card=None):
    card = card or actions.issue_post_review(world["chat"], world["link"], world["post"])
    for line in card["inline_keyboard"]:
        for button in line:
            nonce = button["callback_data"][len(actions.PREFIX) :]
            if TelegramAction.objects.get(token_digest=actions._digest(nonce)).kind == kind:
                return {
                    "id": "callback-1",
                    "data": button["callback_data"],
                    "from": {"id": world["link"].telegram_user_id, "is_bot": False},
                    "message": {
                        "message_id": 55,
                        "chat": {"id": world["chat"].chat_id},
                        "from": {"id": world["conn"].bot_id, "is_bot": True},
                    },
                }
    raise AssertionError(f"No button for {kind}")


def week_preview(world):
    return {
        "needs_confirmation": True,
        "week_start": "2026-10-19",
        "analysis_token": "signed-analysis",
        "message": "Review this week before preparation.",
        "analysis": {
            "workspace": "Neopolis",
            "week_start": "2026-10-19",
            "week_end": "2026-10-25",
            "timezone": "Asia/Kolkata",
            "requested": 3,
            "existing": 1,
            "additional_needed": 2,
            "accounts": [{"platform": "facebook", "name": "Neopolis Infra", "native_id": "585141221346435"}],
            "sources": {
                "fetched_at": timezone.now().isoformat(),
                "website": {
                    "url": "https://neopolis.example",
                    "status": "ok",
                    "title": "Neopolis",
                    "excerpt": "Current source evidence, not verified commercial claims.",
                },
                "channels": [],
            },
            "budget": {"limit_usd": "100", "recorded_estimated_usd": "25"},
            "blockers": [],
            "warnings": ["Confirm availability with the owner before making promises."],
            "claims": [
                {
                    "category": "location",
                    "claim": "West Hyderabad",
                    "source": "Owner reviewed project source",
                    "verifier": "Agency owner",
                    "verified_at": timezone.now().isoformat(),
                    "valid_until": "2026-10-25",
                }
            ],
            "references": [
                {"description": "Chosen cinematic campaign sample", "note": "Use the brand's type treatment"}
            ],
            "open_slots": [world["when"].isoformat()],
        },
    }


def test_verified_human_schedules_exact_two_destinations_and_audits_telegram(world):
    from apps.social_accounts.models import SocialAccount

    account = SocialAccount.objects.create(
        workspace=world["ws"], platform="instagram", account_platform_id="native-instagram", account_name="Neopolis IG"
    )
    PlatformPost.objects.create(
        post=world["post"],
        social_account=account,
        status="pending_review",
        platform_specific_caption="Instagram exact output",
    )
    payload = callback(world)
    result = actions.handle_callback(world["conn"], payload)
    assert result["ok"], result
    rows = world["post"].platform_posts.all()
    assert rows.count() == 2
    for pp in rows:
        assert pp.status == "scheduled"
        assert pp.approved_fingerprint == gate.fingerprint(pp)
        assert pp.approved_by_id == world["owner"].pk
        assert pp.approved_publish_at == world["when"]
        assert gate.publish_blocker(pp) is None
    assert set(
        ApprovalAction.objects.filter(post=world["post"], action="approved").values_list("channel", flat=True)
    ) == {TELEGRAM}
    assert not actions.handle_callback(world["conn"], payload)["ok"]
    assert ApprovalAction.objects.filter(post=world["post"], action="approved").count() == 2


def test_reviewed_time_override_is_the_time_stamped_even_for_approve_only(world):
    new_time = world["when"] + timedelta(hours=3)
    card = actions.issue_post_review(world["chat"], world["link"], world["post"], publish_at=new_time)
    assert actions.handle_callback(world["conn"], callback(world, "approve", card))["ok"]
    pp = world["post"].platform_posts.get()
    assert pp.status == "approved"
    assert pp.approved_publish_at == new_time
    assert pp.scheduled_at is None


def test_legacy_schedule_cannot_stamp_a_time_different_from_review_card(world):
    world["post"].platform_posts.update(scheduled_at=world["when"] - timedelta(hours=1))
    result = actions.handle_callback(world["conn"], callback(world, "approve"))
    assert not result["ok"]
    assert world["post"].platform_posts.get().status == "pending_review"
    assert not ApprovalAction.objects.filter(post=world["post"], action="approved").exists()


def test_canonical_publisher_accepts_telegram_stamp_then_blocks_native_identity_edit(world):
    assert actions.handle_callback(world["conn"], callback(world))["ok"]
    pp = world["post"].platform_posts.get()
    assert gate.publish_blocker(pp) is None
    engine = PublishEngine()
    with (
        patch("apps.publisher.engine.timezone.now", return_value=world["when"] + timedelta(seconds=1)),
        patch.object(engine, "_publish_platform_post") as publish,
    ):
        engine._publish_post_group(world["post"], [pp])
    publish.assert_called_once()
    pp.refresh_from_db()
    assert pp.status == "publishing"
    PlatformPost.objects.filter(pk=pp.pk).update(status="scheduled")
    pp.refresh_from_db()
    world["account"].account_platform_id = "different-native-page"
    world["account"].save(update_fields=["account_platform_id"])
    with (
        patch("apps.publisher.engine.timezone.now", return_value=world["when"] + timedelta(seconds=1)),
        patch.object(engine, "_publish_platform_post") as publish,
    ):
        engine._publish_post_group(world["post"], [pp])
    publish.assert_not_called()
    pp.refresh_from_db()
    assert pp.status == "failed"
    assert gate.publish_blocker(pp)


@pytest.mark.django_db(transaction=True)
def test_concurrent_callback_claim_has_one_decision_and_one_stamp(world):
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections, connections

    payload = callback(world, "approve")

    def consume():
        close_old_connections()
        try:
            return actions.handle_callback(world["conn"], deepcopy(payload))
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(consume) for _ in range(2)]
        outcomes = [future.result(timeout=20) for future in futures]
    assert sum(outcome["ok"] for outcome in outcomes) == 1
    assert ApprovalAction.objects.filter(post=world["post"], action="approved", channel=TELEGRAM).count() == 1
    assert TelegramAction.objects.filter(used_at__isnull=False).count() == 1


@pytest.mark.parametrize(
    "path,value", [("actor", 999), ("chat", -100777), ("bot", 123457), ("bot_actor", True), ("forward", True)]
)
def test_buttons_are_bound_to_person_chat_and_bot(world, path, value):
    payload = callback(world)
    if path == "actor":
        payload["from"]["id"] = value
    elif path == "chat":
        payload["message"]["chat"]["id"] = value
    elif path == "bot":
        payload["message"]["from"]["id"] = value
    elif path == "bot_actor":
        payload["from"]["is_bot"] = value
    else:
        payload["message"]["forward_origin"] = {"type": "user"}
    assert not actions.handle_callback(world["conn"], payload)["ok"]
    assert world["post"].platform_posts.get().status == "pending_review"


@pytest.mark.parametrize("change", ["caption", "native", "time", "alt", "source", "revision", "format"])
def test_any_material_time_or_revision_change_rejects_stale_card(world, change):
    asset = MediaAsset.objects.create(
        workspace=world["ws"],
        organization=world["ws"].organization,
        file="telegram-tests/graphic.png",
        media_type="image",
    )
    attachment = PostMedia.objects.create(post=world["post"], media_asset=asset, alt_text="Reviewed graphic")
    brief = StudioBrief.objects.create(
        workspace=world["ws"],
        author=world["owner"],
        post=world["post"],
        idea="A considered property post",
        status="ready",
    )
    brief.trust_snapshot = actions.trust.capture(brief)
    brief.save(update_fields=["trust_snapshot"])
    payload = callback(world)
    if change == "caption":
        Post.objects.filter(pk=world["post"].pk).update(caption="Different caption")
    elif change == "native":
        type(world["account"]).objects.filter(pk=world["account"].pk).update(account_platform_id="another-page")
    elif change == "time":
        Post.objects.filter(pk=world["post"].pk).update(proposed_publish_at=world["when"] + timedelta(hours=1))
    elif change == "alt":
        PostMedia.objects.filter(pk=attachment.pk).update(alt_text="Changed meaning")
    elif change == "source":
        MediaAsset.objects.filter(pk=asset.pk).update(source="fal.ai")
    elif change == "revision":
        StudioBrief.objects.filter(pk=brief.pk).update(revision=2)
    else:
        world["post"].platform_posts.update(platform_extra={"format": "story"})
    assert not actions.handle_callback(world["conn"], payload)["ok"]
    assert world["post"].platform_posts.get().status == "pending_review"


@pytest.mark.parametrize(
    "change", ["role", "link", "connection", "opt_in", "user", "org", "archive", "private_owner", "client_facing"]
)
def test_current_authority_is_rechecked_at_callback(world, change):
    payload = callback(world)
    if change == "role":
        WorkspaceMembership.objects.filter(user=world["owner"], workspace=world["ws"]).update(workspace_role="viewer")
    elif change == "link":
        TelegramUserLink.objects.filter(pk=world["link"].pk).update(is_active=False)
    elif change == "connection":
        TelegramConnection.objects.filter(pk=world["conn"].pk).update(is_active=False)
    elif change == "opt_in":
        TelegramConnection.objects.filter(pk=world["conn"].pk).update(approvals_enabled=False)
    elif change == "user":
        type(world["owner"]).objects.filter(pk=world["owner"].pk).update(is_active=False)
    elif change == "org":
        OrgMembership.objects.filter(user=world["owner"], organization=world["ws"].organization).delete()
    elif change == "archive":
        type(world["ws"]).objects.filter(pk=world["ws"].pk).update(is_archived=True)
    elif change == "private_owner":
        TelegramChat.objects.filter(pk=world["chat"].pk).update(audience="private", private_user=world["editor"])
    else:
        role = CustomRole.objects.create(
            organization=world["ws"].organization,
            name="Client-facing manager",
            permissions={"client_facing": True, "approve_posts": True, "create_posts": True},
        )
        WorkspaceMembership.objects.filter(user=world["owner"], workspace=world["ws"]).update(custom_role=role)
    assert not actions.handle_callback(world["conn"], payload)["ok"]
    assert world["post"].platform_posts.get().status == "pending_review"


def test_expired_callback_and_time_that_becomes_past_are_rejected(world):
    payload = callback(world)
    TelegramAction.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert not actions.handle_callback(world["conn"], payload)["ok"]
    with pytest.raises(actions.TelegramActionError):
        actions.issue_post_review(
            world["chat"], world["link"], world["post"], publish_at=timezone.now() - timedelta(seconds=1)
        )
    with pytest.raises(actions.TelegramActionError):
        actions.issue_post_review(
            world["chat"], world["link"], world["post"], publish_at=timezone.now().replace(tzinfo=None)
        )


@pytest.mark.parametrize("channel", [TELEGRAM, API, PORTAL, "system"])
def test_bare_channel_or_system_cannot_create_internal_stamp(world, channel):
    with acting_as(world["owner"], channel):
        services.approve_post(world["post"], world["owner"], world["ws"])
    assert world["post"].platform_posts.get().status == "pending_review"


def test_agent_cannot_issue_or_consume_human_buttons(world):
    payload = callback(world)
    with agent_work("malicious model approval"):
        with pytest.raises(AgentMayNotApproveError):
            actions.handle_callback(world["conn"], payload)
        with pytest.raises(AgentMayNotApproveError):
            actions.issue_post_review(world["chat"], world["link"], world["post"])
    assert world["post"].platform_posts.get().status == "pending_review"


@pytest.mark.parametrize("kind", ["unknown", "expired"])
def test_unresolved_delivery_cannot_be_approved_through_telegram(world, kind):
    payload = callback(world)
    pp = world["post"].platform_posts.get()
    delivery.mark(pp, kind=kind, reason="Held previous attempt", from_status="pending_review")
    assert not actions.handle_callback(world["conn"], payload)["ok"]
    with pytest.raises(actions.TelegramActionError):
        actions.issue_post_review(world["chat"], world["link"], world["post"])


def test_client_signoff_keeps_original_internal_stamp_and_does_not_schedule(world):
    world["ws"].approval_workflow_mode = "required_internal_and_client"
    world["ws"].save(update_fields=["approval_workflow_mode"])
    result = actions.handle_callback(world["conn"], callback(world))
    assert result["ok"] and "Nothing was scheduled" in result["text"]
    pp = world["post"].platform_posts.get()
    assert pp.status == "pending_client"
    stamp = (pp.approved_by_id, pp.approved_at, pp.approved_fingerprint)
    convo = Conversation.objects.create(workspace=world["ws"], audience="client")
    world["chat"] = TelegramChat.objects.create(
        connection=world["conn"], chat_id=-100999, chat_type="supergroup", audience="client", conversation=convo
    )
    world["link"] = TelegramUserLink.objects.create(
        connection=world["conn"], user=world["client"], telegram_user_id=55555
    )
    assert actions.handle_callback(world["conn"], callback(world, "client_signoff"))["ok"]
    pp.refresh_from_db()
    assert pp.status == "approved" and pp.scheduled_at is None
    assert stamp == (pp.approved_by_id, pp.approved_at, pp.approved_fingerprint)
    assert ApprovalAction.objects.filter(post=world["post"], user=world["client"], channel=TELEGRAM).exists()


def test_no_truncated_or_unseen_multi_graphic_review_gets_buttons(world):
    world["post"].caption = "word " * 900
    world["post"].save(update_fields=["caption"])
    with pytest.raises(actions.TelegramActionError):
        actions.issue_post_review(world["chat"], world["link"], world["post"])
    assert not TelegramAction.objects.exists()


def test_confirm_preparation_is_one_use_and_never_calls_approval_or_publisher(world):
    job = AgencyJob.objects.create(
        workspace=world["ws"],
        kind="chat",
        title="Complete brief",
        requested_by=world["owner"],
        conversation=world["chat"].conversation,
        status="done",
    )
    message = Message.objects.create(
        conversation=world["chat"].conversation,
        author_kind="agent",
        body="Use our reviewed location facts and this photo to create an illustrative draft.",
        job=job,
    )
    job.result = {
        "awaiting_confirmation": True,
        "message_id": str(message.pk),
        "sources": {"facts": "Reviewed evidence"},
    }
    job.save(update_fields=["result"])
    card = actions.issue_brief_confirmation(world["chat"], world["link"], confirmation_message=message)
    payload = callback(world, "prepare", card)
    with (
        patch("apps.studio.chat.post_message") as post_message,
        patch("apps.approvals.services.approve_post") as approve,
    ):
        post_message.return_value.job = object()
        result = actions.handle_callback(world["conn"], payload)
        assert result["ok"]
        assert post_message.call_args.kwargs["kind"] == "confirm_brief"
        assert post_message.call_args.kwargs["facts_confirmed"] is True
        approve.assert_not_called()
    assert not actions.handle_callback(world["conn"], payload)["ok"]
    assert world["post"].platform_posts.get().status == "pending_review"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": "approve"},
        {"from": [], "message": {}},
        {"from": {"id": True}, "message": {"chat": []}, "data": "tg:a:" + "a" * 32},
    ],
)
def test_model_text_and_malformed_payloads_never_authorize(world, payload):
    assert not actions.handle_callback(world["conn"], deepcopy(payload))["ok"]
    assert world["post"].platform_posts.get().status == "pending_review"


@pytest.mark.parametrize("part", ["nonce", "sender", "chat", "bot"])
def test_canonical_gate_rechecks_proof_even_if_dispatcher_is_bypassed(world, part):
    from django.db import transaction

    from apps.approvals.actor import acting_as_telegram

    payload = callback(world, "approve")
    nonce = payload["data"][len(actions.PREFIX) :]
    action = TelegramAction.objects.get(token_digest=actions._digest(nonce))
    proof = {
        "nonce": nonce,
        "telegram_user_id": world["link"].telegram_user_id,
        "chat_id": world["chat"].chat_id,
        "bot_id": world["conn"].bot_id,
    }
    if part == "nonce":
        proof["nonce"] = "forged"
    elif part == "sender":
        proof["telegram_user_id"] = 123
    elif part == "chat":
        proof["chat_id"] = -123
    else:
        proof["bot_id"] = 123
    with transaction.atomic(), acting_as_telegram(action, **proof):
        services.approve_post(world["post"], world["owner"], world["ws"])
    assert world["post"].platform_posts.get().status == "pending_review"


def test_week_confirmation_keeps_large_signed_analysis_out_of_callback_data(world):
    preview = week_preview(world)
    preview["analysis_token"] = "signed-analysis-" + "long" * 500
    card = actions.issue_week_confirmation(world["chat"], world["link"], preview)
    # The first card is a short summary: volume, cost, what to check, the footer.
    for summary in ("2 new", "1 already planned", "3 wanted", "25 of 100 USD", "Nothing publishes"):
        assert summary in card["text"]
    assert "585141221346435" not in card["text"]
    labels = [button["text"] for row in card["inline_keyboard"] for button in row]
    assert labels == ["Confirm analysis & prepare week", "Show evidence"]
    # The complete evidence sits behind its own one-use button, never in callback data.
    evidence_payload = callback(world, "week_evidence", card)
    assert len(evidence_payload["data"].encode()) < 64
    shown = actions.handle_callback(world["conn"], evidence_payload)
    assert shown["ok"]
    for evidence in (
        "585141221346435",
        "West Hyderabad",
        "Agency owner",
        "Current source evidence",
        "Chosen cinematic campaign",
        "requested 3",
        "25 USD",
    ):
        assert evidence in shown["text"]
    assert not actions.handle_callback(world["conn"], evidence_payload)["ok"]  # one use
    payload = callback(world, "week_plan", card)
    assert len(payload["data"].encode()) < 64
    with (
        patch(
            "apps.telegram.weekly.queue_week_plan",
            return_value={"started": True, "message": "Preparation queued; no post was approved or scheduled."},
        ) as queue,
        patch("apps.approvals.services.approve_post") as approve,
    ):
        assert actions.handle_callback(world["conn"], payload)["ok"]
        assert queue.call_args.kwargs["analysis_token"] == preview["analysis_token"]
        assert queue.call_args.kwargs["confirmed"] is True
        approve.assert_not_called()
    assert world["post"].platform_posts.get().status == "pending_review"


def test_week_source_change_has_safe_fresh_preview_refusal(world):
    preview = week_preview(world)
    payload = callback(world, "week_plan", actions.issue_week_confirmation(world["chat"], world["link"], preview))
    with patch(
        "apps.telegram.weekly.queue_week_plan",
        side_effect=ValueError("Sources changed. Request a fresh weekly preview."),
    ):
        result = actions.handle_callback(world["conn"], payload)
    assert not result["ok"] and "fresh weekly preview" in result["text"]


@pytest.mark.parametrize("kind,status", [("reject", "rejected"), ("changes", "changes_requested")])
def test_review_feedback_is_audited_without_approval_or_schedule(world, kind, status):
    result = actions.handle_callback(world["conn"], callback(world, kind))
    assert result["ok"]
    pp = world["post"].platform_posts.get()
    assert pp.status == status and not pp.approved_fingerprint and pp.scheduled_at is None
    assert ApprovalAction.objects.filter(post=world["post"], user=world["owner"], channel=TELEGRAM).exists()


@pytest.mark.parametrize(
    "extra",
    [
        {"privacy": "public"},
        {"link": "https://example.com/destination"},
        {"board_id": "other-board"},
        {"post_type": "story"},
    ],
)
def test_hidden_platform_input_cannot_receive_an_approval_button(world, extra):
    world["post"].platform_posts.update(platform_extra=extra)
    with pytest.raises(actions.TelegramActionError):
        actions.issue_post_review(world["chat"], world["link"], world["post"])
    assert not TelegramAction.objects.exists()


def test_media_override_needs_full_smbean_review(world):
    asset = MediaAsset.objects.create(
        workspace=world["ws"],
        organization=world["ws"].organization,
        file="telegram-tests/graphic.png",
        media_type="image",
    )
    PostMedia.objects.create(
        post=world["post"], media_asset=asset, platform_overrides={"facebook": {"crop": "different view"}}
    )
    with pytest.raises(actions.TelegramActionError):
        actions.issue_post_review(world["chat"], world["link"], world["post"])
    assert not TelegramAction.objects.exists()


@pytest.mark.parametrize("case", ["custom_client_facing", "custom_client_base", "inactive"])
def test_dashboard_internal_gate_rejects_external_custom_roles_and_freshly_inactive_users(world, case):
    if case == "inactive":
        type(world["owner"]).objects.filter(pk=world["owner"].pk).update(is_active=False)
    else:
        role = CustomRole.objects.create(
            organization=world["ws"].organization,
            name="External approver",
            permissions={"approve_posts": True, "client_facing": case == "custom_client_facing"},
        )
        WorkspaceMembership.objects.filter(user=world["owner"], workspace=world["ws"]).update(
            custom_role=role, workspace_role="client" if case == "custom_client_base" else "manager"
        )
    with acting_as(world["owner"], DASHBOARD):
        services.approve_post(world["post"], world["owner"], world["ws"])
    assert world["post"].platform_posts.get().status == "pending_review"


@pytest.mark.parametrize("part", ["connection", "link", "conversation", "audience"])
def test_pairing_epochs_and_originating_conversation_never_revive_old_review(world, part):
    payload = callback(world)
    if part == "connection":
        world["conn"].is_active = False
        world["conn"].save(update_fields=["is_active", "updated_at"])
        world["conn"].is_active = True
        world["conn"].save(update_fields=["is_active", "updated_at"])
    elif part == "link":
        world["link"].is_active = False
        world["link"].save(update_fields=["is_active", "updated_at"])
        world["link"].is_active = True
        world["link"].save(update_fields=["is_active", "updated_at"])
    elif part == "conversation":
        new_thread = Conversation.objects.create(workspace=world["ws"], audience="internal")
        TelegramChat.objects.filter(pk=world["chat"].pk).update(conversation=new_thread)
    else:
        world["chat"].conversation.audience = "client"
        world["chat"].conversation.save(update_fields=["audience"])
        TelegramChat.objects.filter(pk=world["chat"].pk).update(audience="client")
    assert not actions.handle_callback(world["conn"], payload)["ok"]
    assert world["post"].platform_posts.get().status == "pending_review"


def test_oversized_weekly_evidence_cannot_receive_confirmation_button(world):
    preview = week_preview(world)
    preview["analysis"]["claims"][0]["claim"] = "unseen fact " * 500
    with pytest.raises(ValueError, match="too long"):
        actions.issue_week_confirmation(world["chat"], world["link"], preview)
    assert not TelegramAction.objects.exists()
