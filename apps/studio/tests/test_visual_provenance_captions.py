"""Rendered image provenance is in the exact captions reviewed and handed off."""

from __future__ import annotations

from copy import deepcopy

import pytest
from django.urls import reverse

from apps.blog.ai_images import GeneratedImage
from apps.composer.models import PlatformPost
from apps.social_accounts.models import SocialAccount
from apps.studio import agents, chat, images, pipeline, qa
from apps.studio.models import AgencyJob, Message, StudioBrief
from apps.studio.roles import creative
from apps.studio.tests.conftest import _result, jpeg_bytes, make_brief, run_all
from apps.studio.tests.test_photo_provenance import attest

GENERATED = "AI-generated illustrative image."
UNVERIFIED = "Image provenance has not been verified for this project."


def _reviews(monkeypatch, fake_team):
    captured = []

    def reviewer(brief, profile, post_copy, spec, graphic, reference_image=None):
        captured.append(deepcopy(post_copy["_publication_payload"]))
        return fake_team.reviewer(brief, profile, post_copy, spec, graphic, reference_image)

    monkeypatch.setattr(agents, "reviewer", reviewer)
    return captured


def _fake_generation(monkeypatch, settings):
    settings.FAL_KEY = "test-no-paid-image-call"
    image = GeneratedImage(content=jpeg_bytes(), content_type="image/jpeg", prompt="Offline image", model="mock")
    monkeypatch.setattr(images.ai_images, "generate_from_prompt", lambda *_args, **_kwargs: image)


@pytest.mark.parametrize(
    "kind,note",
    [("generated", GENERATED), ("unverified", UNVERIFIED), ("verified", ""), ("none", ""), ("render_fallback", "")],
)
def test_disclosure_follows_actual_used_image_before_review_and_human_approval(
    client, world, fake_team, photo, monkeypatch, settings, kind, note
):
    source = None
    if kind == "generated":
        _fake_generation(monkeypatch, settings)
    elif kind in {"unverified", "verified", "render_fallback"}:
        source = photo(data=b"Unreadable picture" if kind == "render_fallback" else jpeg_bytes())
        if kind == "verified":
            assert attest(client, world, source).status_code == 302
    reviewed = _reviews(monkeypatch, fake_team)
    brief = run_all(make_brief(world, source_picture=source))

    assert brief.status == StudioBrief.Status.READY and brief.post_copy["visual_note"] == note
    row = PlatformPost.objects.get(post=brief.post)
    assert row.status == "pending_review" and row.approved_by_id is None and row.scheduled_at is None
    assert reviewed[-1][0]["caption"] == row.effective_caption == brief.post.caption
    if note:
        assert row.effective_caption.count(note) == 1
    else:
        assert GENERATED not in row.effective_caption and UNVERIFIED not in row.effective_caption
    if kind == "generated":
        assert brief.picture.source == "fal.ai"


@pytest.mark.parametrize("platform,path", [("x", "short"), ("threads", "short"), ("threads", "channel")])
def test_short_and_channel_variants_keep_disclosure_in_qa_and_persisted_caption(
    world, fake_team, photo, monkeypatch, platform, path
):
    account = (
        world.x
        if platform == "x"
        else SocialAccount.objects.create(
            workspace=world.workspace, platform=platform, account_platform_id="offline-thread", account_name="Threads"
        )
    )
    source = photo()
    short = "Contact the team for a site visit."
    fake_team.copy = {"caption": "A detailed introduction to the project. " * 40, "short_caption": short}
    if platform == "threads":
        caption = "A long channel introduction. " * 40 if path == "short" else "A short Threads introduction."
        monkeypatch.setattr(
            creative,
            "channel_editor",
            lambda *_args, **_kwargs: _result(
                creative.ChannelAnswer(
                    versions=[creative.ChannelVersion(platform=platform, caption=caption)], notes="Offline"
                )
            ),
        )
    reviewed = _reviews(monkeypatch, fake_team)
    brief = run_all(make_brief(world, source_picture=source, accounts=[account]))
    assert brief.status == StudioBrief.Status.READY
    row = PlatformPost.objects.get(post=brief.post)
    assert row.effective_caption.count(UNVERIFIED) == 1
    assert reviewed[-1][0]["caption"] == row.effective_caption
    assert account.caption_wire_length(row.effective_caption) <= account.char_limit
    assert (short if path == "short" else caption) in row.effective_caption


def test_model_repeated_disclosures_are_normalized_to_one_actual_image_label(world, fake_team, photo, monkeypatch):
    source = photo()
    duplicate = f"Explore the property.\n\n{UNVERIFIED}\n\n{UNVERIFIED.upper()}\n\n{GENERATED}"
    fake_team.copy = {"caption": duplicate}
    reviewed = _reviews(monkeypatch, fake_team)
    brief = run_all(make_brief(world, source_picture=source))
    caption = PlatformPost.objects.get(post=brief.post).effective_caption
    assert caption.count(UNVERIFIED) == 1 and GENERATED not in caption
    assert reviewed[-1][0]["caption"] == caption


def test_visual_label_change_invalidates_exact_final_review_fingerprint(world, fake_team, photo):
    brief = run_all(make_brief(world, source_picture=photo()))
    graphic, payload, original = pipeline._publication_material(brief, list(brief.social_accounts.all()))
    assert original == brief.review_notes["publication_review"]["fingerprint"]
    unlabeled = deepcopy(payload)
    unlabeled[0]["caption"] = unlabeled[0]["caption"].replace(UNVERIFIED, "").strip()
    assert qa.publication_fingerprint(unlabeled, brief.design_spec, graphic, brief.revision) != original
    assert not pipeline._review_is_clear(
        brief.review_notes["publication_review"],
        qa.publication_fingerprint(unlabeled, brief.design_spec, graphic, brief.revision),
    )


def test_source_picture_not_used_by_design_does_not_add_a_visual_disclosure(world, fake_team, photo):
    fake_team.design = {"use_picture": False}
    brief = run_all(make_brief(world))
    assert brief.picture_id is None and brief.post_copy["visual_note"] == ""
    assert GENERATED not in brief.post.caption and UNVERIFIED not in brief.post.caption


def test_authenticated_approval_preview_and_thread_show_generated_disclosure(
    client, world, fake_team, monkeypatch, settings
):
    _fake_generation(monkeypatch, settings)
    conversation = chat.general_conversation(world.workspace, created_by=world.editor)
    job = AgencyJob.objects.create(
        workspace=world.workspace,
        conversation=conversation,
        requested_by=world.editor,
        kind=AgencyJob.Kind.CHAT,
        status=AgencyJob.Status.DONE,
    )
    brief = run_all(make_brief(world, origin=StudioBrief.Origin.CHAT, job=job, requested_by=world.editor))
    job.result = {"brief_id": str(brief.pk), "action": "new_post"}
    job.save(update_fields=["result"])
    chat.post_agent_message(
        conversation,
        "The draft is ready for human review.",
        job=job,
        action="new_post",
        action_status=Message.ActionStatus.STARTED,
    )
    client.force_login(world.editor)
    detail = client.get(reverse("studio:detail", kwargs={"workspace_id": world.workspace.pk, "brief_id": brief.pk}))
    thread = client.get(
        reverse(
            "studio:thread_messages", kwargs={"workspace_id": world.workspace.pk, "conversation_id": conversation.pk}
        )
    )
    assert detail.status_code == thread.status_code == 200
    assert GENERATED in detail.content.decode() and GENERATED in thread.content.decode()
