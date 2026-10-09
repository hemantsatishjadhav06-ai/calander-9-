"""The producer: a small idea through the whole team to a post awaiting approval."""

from datetime import timedelta
from unittest import mock

from django.utils import timezone
from PIL import Image

from apps.blog.ai_images import GeneratedImage, ImageGenerationError
from apps.composer.models import PlatformPost, PostMedia
from apps.notifications.models import Notification
from apps.studio import pipeline
from apps.studio.models import AgentRun, StudioBrief
from apps.studio.tests.conftest import jpeg_bytes, make_brief, run_all


def test_a_small_idea_becomes_a_post_awaiting_approval(world, fake_team):
    brief = run_all(make_brief(world, notes="Mention the documents checklist"))

    assert brief.status == StudioBrief.Status.READY and brief.stage == StudioBrief.Stage.DONE
    assert brief.chosen_concept.title == "The 8–14% gap"  # the strategist's recommendation
    assert brief.concepts.count() == 3

    post = brief.post
    # Plain text, hashtags once at the end, de-duplicated and cleaned.
    assert "**" not in post.caption
    assert post.caption.endswith("#LandlordShare #WestHyderabad #HyderabadRealEstate")
    assert post.caption.count("#LandlordShare") == 1
    assert post.first_comment.startswith("How the share works")
    assert post.tags == ["ai-studio"]
    assert post.proposed_publish_at is not None and post.proposed_publish_at > timezone.now()

    media = PostMedia.objects.get(post=post)
    assert media.media_asset == brief.graphic and media.alt_text.startswith("Navy graphic")
    with Image.open(brief.graphic.file) as graphic:
        assert graphic.size == (1080, 1350)

    pp = PlatformPost.objects.get(post=post)
    assert pp.social_account == world.linkedin and pp.status == "pending_review"
    assert pp.platform_specific_caption is None  # LinkedIn takes the full caption

    agents_run = list(brief.runs.values_list("agent", "status"))
    assert [agent for agent, _status in agents_run] == [
        "strategist",
        "copywriter",
        "art_director",
        "illustrator",
        "designer",
        "reviewer",
        "channel_editor",
        "qa_inspector",
        "scheduler",
        "producer",
    ]
    # Without FAL_KEY the illustrator steps aside and the brand background is used
    # (and the prompt engineer has nothing to write for).
    assert ("illustrator", AgentRun.Status.SKIPPED) in agents_run
    # LinkedIn takes the copywriter's own text, so the channel editor steps aside too.
    assert ("channel_editor", AgentRun.Status.SKIPPED) in agents_run
    assert brief.review_notes["qa"]["total"] >= 5
    assert brief.proposed_publish_at == post.proposed_publish_at
    # Approvers are told; so is the author.
    assert Notification.objects.filter(user=world.owner, title__icontains="submitted").exists()
    assert Notification.objects.filter(user=world.editor, title__icontains="ready for approval").exists()


def test_recent_posts_reach_the_strategist(world, fake_team):
    first = run_all(make_brief(world))
    run_all(make_brief(world, idea="Why title checks matter"))
    recent = fake_team.calls["strategist"][1]["recent"]
    assert recent and recent[0]["text"].startswith("Landlord shares typically")
    assert first.post.caption.startswith("Landlord shares")


def test_the_reviewer_can_send_it_back_once(world, fake_team):
    fake_team.verdicts = ["revise", "revise", "revise"]
    brief = run_all(make_brief(world))

    assert brief.status == StudioBrief.Status.READY
    assert brief.auto_revisions == 1
    copy_calls = fake_team.calls["copywriter"]
    assert len(copy_calls) == 2
    assert copy_calls[1]["fixes"] == ["Remove 'best price'."] and copy_calls[1]["previous"]
    # The second "revise" goes to the approver as notes instead of looping.
    assert len(fake_team.calls["reviewer"]) == 2
    assert brief.review_notes["risk_flags"] == ["'best price' is not in the facts"]
    assert "Check before approving" in brief.post.internal_notes


def test_a_failed_agent_stops_the_run_and_retry_resumes_there(world, fake_team):
    from apps.studio import services

    fake_team.fail["art_director"] = "Claude is rate-limiting this account right now."
    brief = run_all(make_brief(world))
    assert brief.status == StudioBrief.Status.FAILED and brief.stage == "art"
    assert "rate-limiting" in brief.error
    assert brief.runs.get(agent="art_director").status == AgentRun.Status.FAILED

    fake_team.fail.clear()
    services.retry(brief)
    brief = run_all(brief)
    assert brief.status == StudioBrief.Status.READY
    assert len(fake_team.calls["strategist"]) == 1  # not redone
    assert len(fake_team.calls["copywriter"]) == 1


def test_an_unexpected_crash_is_reported_not_raised(world, fake_team, monkeypatch):
    monkeypatch.setattr(pipeline.design, "render", mock.Mock(side_effect=RuntimeError("boom")))
    brief = run_all(make_brief(world))
    assert brief.status == StudioBrief.Status.FAILED
    assert "designer hit an unexpected error" in brief.error


def test_a_stale_step_does_not_overwrite_a_newer_revision(world, fake_team):
    brief = make_brief(world)
    pipeline.run_step(str(brief.pk), 1, "strategy")
    StudioBrief.objects.filter(pk=brief.pk).update(revision=2, stage="copy")
    pipeline.run_step(str(brief.pk), 1, "copy")  # the old revision's step
    brief.refresh_from_db()
    assert brief.post_copy == {} and not fake_team.calls["copywriter"]


def test_a_discard_mid_run_stops_the_team(world, fake_team, monkeypatch):
    brief = make_brief(world)
    pipeline.run_step(str(brief.pk), 1, "strategy")

    def discard_then_answer(*args, **kwargs):
        StudioBrief.objects.filter(pk=brief.pk).update(status=StudioBrief.Status.DISCARDED)
        return fake_team.__class__.copywriter(fake_team, *args, **kwargs)

    monkeypatch.setattr(pipeline.agents, "copywriter", discard_then_answer)
    pipeline.run_step(str(brief.pk), 1, "copy")
    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.DISCARDED and brief.post_copy == {}


def test_with_fal_the_illustrator_paints_and_the_designer_uses_it(world, fake_team, settings):
    settings.FAL_KEY = "fal-test"
    picture = jpeg_bytes(1088, 1360, color=(200, 160, 120))
    generated = GeneratedImage(content=picture, content_type="image/jpeg", prompt="p", model="fal-ai/flux/dev")
    with mock.patch("apps.studio.images.ai_images.generate_from_prompt", return_value=generated) as gen:
        brief = run_all(make_brief(world))
    assert brief.picture is not None and brief.picture.source == "fal.ai"
    # The prompt engineer rewrote the art director's direction in the house style;
    # the illustrator sends that, with the series' style line and the no-text rule.
    engineer = fake_team.calls["prompt_engineer"][0]
    assert "Kokapet" in engineer["spec"]["picture_prompt"]
    prompt = gen.call_args.args[0]
    assert prompt.startswith("Warm evening light on contemporary residential towers")
    assert "Style: Warm dusk architectural photography" in prompt and "no text" in prompt.lower()
    assert brief.design_spec["picture_prompt"].startswith("Warm evening light")
    order = list(brief.runs.values_list("agent", flat=True))
    assert order.index("prompt_engineer") == order.index("illustrator") - 1
    # The stat layout's picture strip is wide, so the request is landscape-shaped.
    size = gen.call_args.kwargs["image_size"]
    assert size["width"] > size["height"] and size["width"] % 16 == 0
    assert brief.runs.get(agent="illustrator").status == AgentRun.Status.SUCCEEDED


def test_a_picture_failure_falls_back_to_the_brand_background(world, fake_team, settings):
    settings.FAL_KEY = "fal-test"
    with mock.patch(
        "apps.studio.images.ai_images.generate_from_prompt",
        side_effect=ImageGenerationError("The fal.ai account has no credit left."),
    ):
        brief = run_all(make_brief(world))
    assert brief.status == StudioBrief.Status.READY and brief.picture is None
    run = brief.runs.get(agent="illustrator")
    assert run.status == AgentRun.Status.FAILED and "no credit" in run.error


def test_a_chosen_photo_is_used_instead_of_painting(world, fake_team, photo, settings):
    settings.FAL_KEY = "fal-test"
    chosen = photo()
    with mock.patch("apps.studio.images.ai_images.generate_from_prompt") as gen:
        brief = run_all(make_brief(world, source_picture=chosen))
    gen.assert_not_called()
    assert brief.picture == chosen
    assert fake_team.calls["art_director"][0]["source_picture"] is not None
    assert brief.design_spec["use_picture"] is True and brief.design_spec["picture_prompt"] == ""


def test_each_destination_gets_text_it_can_take(world, fake_team, monkeypatch):
    personal = world.linkedin.__class__.objects.create(
        workspace=world.workspace,
        platform="linkedin_personal",
        account_platform_id="p1",
        account_name="Hemant",
        oauth_access_token="tok",
    )
    monkeypatch.setattr(
        "apps.publisher.engine._resolve_publish_credentials",
        lambda account: {"_oauth_mode": "oidc"} if account.platform == "linkedin_personal" else {},
    )
    brief = run_all(make_brief(world, accounts=[world.linkedin, world.x, personal]))
    rows = {pp.social_account.platform: pp for pp in brief.post.platform_posts.select_related("social_account")}

    assert rows["linkedin_company"].platform_specific_caption is None
    # X takes no first comment, so the link joins the text — which still fits X's weighted 280.
    x_text = rows["x"].platform_specific_caption
    assert x_text.endswith("https://www.neopolisinfra.com/#/the-share")
    assert world.x.caption_wire_length(x_text) <= world.x.char_limit
    # A personal LinkedIn in OIDC mode can't post first comments: the link moves into the post.
    assert rows["linkedin_personal"].platform_specific_caption.endswith(
        "How the share works: https://www.neopolisinfra.com/#/the-share"
    )
    assert rows["linkedin_personal"].platform_specific_first_comment == ""


def test_a_caption_too_long_for_x_goes_out_as_the_short_version(world, fake_team):
    fake_team.copy = {"caption": "Landlord shares explained.\n\n" + ("A useful paragraph for buyers. " * 20)}
    brief = run_all(make_brief(world, accounts=[world.linkedin, world.x]))
    rows = {pp.social_account.platform: pp for pp in brief.post.platform_posts.select_related("social_account")}
    assert rows["linkedin_company"].platform_specific_caption is None
    assert rows["x"].platform_specific_caption.startswith("Landlord shares: same tower")
    assert rows["x"].platform_specific_first_comment == ""


def test_the_next_graphic_keeps_the_last_posts_look(world, fake_team):
    first = run_all(make_brief(world))
    assert first.design_spec["template"] == "stat"

    # The art director "forgets" the look; the lock puts it back.
    fake_team.design = {"template": "statement", "grade": "mono", "picture_style": "Flat vector illustration"}
    second = run_all(make_brief(world, idea="Why title checks matter"))
    reference = fake_team.calls["art_director"][1]["reference"]
    assert reference.kind == "studio" and reference.brief_id == str(first.pk)
    assert reference.image is not None  # the art director and reviewer see the last graphic
    assert second.design_spec["template"] == "stat"
    assert second.design_spec["grade"] == "brand_tint"
    assert second.design_spec["picture_style"] == "Architectural photograph at blue hour, cool crisp light"
    assert fake_team.calls["reviewer"][1]["reference_image"] is not None


def test_a_fresh_look_is_not_locked(world, fake_team):
    run_all(make_brief(world))
    fake_team.design = {"template": "statement"}
    second = run_all(make_brief(world, idea="Something new", style_lock=False))
    assert fake_team.calls["art_director"][1]["reference"].kind == "free"
    assert second.design_spec["template"] == "statement"


def test_handoff_needs_a_connected_account(world, fake_team):
    world.linkedin.connection_status = "disconnected"
    world.linkedin.save()
    brief = run_all(make_brief(world))
    assert brief.status == StudioBrief.Status.FAILED and "Reconnect" in brief.error


def test_stuck_briefs_are_failed_for_retry(world, fake_team):
    brief = make_brief(world)
    StudioBrief.objects.filter(pk=brief.pk).update(
        status=StudioBrief.Status.WORKING, updated_at=timezone.now() - timedelta(hours=1)
    )
    assert pipeline.sweep_stuck() == 1
    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.FAILED and "Press Retry" in brief.error


def test_steps_queue_at_a_lower_priority_than_publishing(world, django_capture_on_commit_callbacks):
    with mock.patch("apps.studio.tasks.run_studio_step") as task, django_capture_on_commit_callbacks(execute=True):
        brief = make_brief(world)
    task.assert_called_once_with(str(brief.pk), 1, "strategy", priority=pipeline.STEP_PRIORITY)
    assert pipeline.STEP_PRIORITY < 0


def test_hashtags_and_captions_are_cleaned():
    assert pipeline.normalise_hashtags(["a b", "#Hyd-Real", "123", "#hyd_real"], ["#Brand"]) == [
        "#ab",
        "#HydReal",
        "#hyd_real",
    ]
    assert pipeline.normalise_hashtags(["One"], ["#Brand", "#Two", "#Three"]) == ["#One", "#Brand", "#Two"]
    assert pipeline.clean_caption("**Bold** line\n\n\n\nNext\n\n#Tag #Two") == "Bold line\n\nNext"


def test_a_failed_prompt_engineer_falls_back_to_the_art_directors_prompt(world, fake_team, settings):
    settings.FAL_KEY = "fal-test"
    fake_team.fail["prompt_engineer"] = "Claude is rate-limiting this account right now."
    picture = jpeg_bytes(1088, 1360)
    generated = GeneratedImage(content=picture, content_type="image/jpeg", prompt="p", model="fal-ai/flux/dev")
    with mock.patch("apps.studio.images.ai_images.generate_from_prompt", return_value=generated) as gen:
        brief = run_all(make_brief(world))

    assert brief.status == StudioBrief.Status.READY
    assert "Kokapet" in gen.call_args.args[0]
    assert brief.runs.get(agent="prompt_engineer").status == AgentRun.Status.FAILED


def test_the_channel_editor_writes_for_networks_the_copywriter_does_not(world, fake_team):
    instagram = world.linkedin.__class__.objects.create(
        workspace=world.workspace,
        platform="instagram",
        account_platform_id="ig-1",
        account_name="@neopolis",
        connection_status="connected",
    )
    brief = run_all(make_brief(world, accounts=[world.linkedin, instagram]))

    assert fake_team.calls["channel_editor"][0]["destinations"] == [{"platform": "instagram", "name": "@neopolis"}]
    assert brief.post_copy["channels"] == {"instagram": "Version for instagram. Link in bio."}
    by_account = {pp.social_account_id: pp for pp in PlatformPost.objects.filter(post=brief.post)}
    assert by_account[instagram.pk].platform_specific_caption == "Version for instagram. Link in bio."
    assert by_account[world.linkedin.pk].platform_specific_caption is None


def test_the_scheduler_gives_each_brief_its_own_slot(world, fake_team):
    from apps.calendar.services import create_default_queue_and_slots

    create_default_queue_and_slots(world.linkedin)
    first = run_all(make_brief(world))
    second = run_all(make_brief(world, idea="Why title checks matter"))

    assert first.proposed_publish_at and second.proposed_publish_at
    assert first.proposed_publish_at != second.proposed_publish_at
    assert first.post.proposed_publish_at == first.proposed_publish_at
    assert "posting slot" in first.runs.get(agent="scheduler").summary


def test_a_stale_step_leaves_no_agent_working(world, fake_team):
    from apps.studio import services

    brief = make_brief(world)
    brief.refresh_from_db()
    pipeline.run_step(str(brief.pk), brief.revision, "strategy")
    brief.refresh_from_db()
    original = fake_team.copywriter

    def copywriter_then_discard(*args, **kwargs):
        services.discard(StudioBrief.objects.get(pk=brief.pk))
        return original(*args, **kwargs)

    fake_team.copywriter = copywriter_then_discard
    from apps.studio import agents

    agents.copywriter = copywriter_then_discard
    pipeline.run_step(str(brief.pk), brief.revision, "copy")

    assert not AgentRun.objects.filter(brief=brief, status=AgentRun.Status.RUNNING).exists()
    assert AgentRun.objects.get(brief=brief, agent="copywriter").status == AgentRun.Status.SKIPPED
