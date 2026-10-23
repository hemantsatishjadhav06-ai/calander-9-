"""Guided entry, retained creative choices and scoped delivery evidence."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.composer.models import PlatformPost, Post
from apps.organizations.models import Organization
from apps.publisher.delivery import delivery_write
from apps.social_accounts.models import SocialAccount
from apps.studio import chat, engine
from apps.studio.models import AgencyJob, Message, StudioBrief
from apps.studio.tests.test_thread_creative_ui import _complete_intake
from apps.workspaces.models import Workspace


@pytest.fixture
def jobs(monkeypatch):
    queued = []
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: queued.append((job.pk, stage)))
    return queued


def _url(name, world, **kwargs):
    return reverse(f"studio:{name}", kwargs={"workspace_id": world.workspace.pk, **kwargs})


def _thread(world, *, status="pending_review", extra=None):
    conversation = chat.general_conversation(world.workspace)
    job = AgencyJob.objects.create(
        workspace=world.workspace,
        conversation=conversation,
        requested_by=world.editor,
        kind=AgencyJob.Kind.CHAT,
        status=AgencyJob.Status.DONE,
    )
    post = Post.objects.create(workspace=world.workspace, author=world.editor, caption="Owner-reviewed campaign")
    with delivery_write():
        pp = PlatformPost.objects.create(
            post=post, social_account=world.linkedin, status=status, platform_extra=extra or {}
        )
    brief = StudioBrief.objects.create(
        workspace=world.workspace,
        author=world.editor,
        requested_by=world.editor,
        origin=StudioBrief.Origin.CHAT,
        job=job,
        post=post,
        status=StudioBrief.Status.READY,
        idea="Owner-reviewed campaign",
    )
    job.result = {"brief_id": str(brief.pk)}
    job.save(update_fields=["result"])
    Message.objects.create(
        conversation=conversation,
        job=job,
        author_kind=Message.AuthorKind.AGENT,
        agent="account_manager",
        body="Your review draft is ready.",
    )
    return conversation, brief, pp


def _html(client, world, conversation):
    return client.get(_url("thread", world) + f"?c={conversation.pk}").content.decode()


def test_primary_entry_starts_its_own_guided_conversation_without_graphic_work(client, world, jobs):
    general = chat.general_conversation(world.workspace)
    client.force_login(world.editor)
    response = client.post(_url("create", world), {"idea": "Invite families for a site visit"})
    job = AgencyJob.objects.get()
    conversation = job.conversation
    assert response.status_code == 302 and response["Location"] == chat.staff_thread_url(conversation)
    assert conversation.pk != general.pk and conversation.created_by == world.editor
    assert job.kind == AgencyJob.Kind.CHAT and job.input["kind"] == "create"
    trigger = Message.objects.get(pk=job.input["message_id"])
    assert trigger.body == "Invite families for a site visit"  # the person's own words, nothing spliced in
    assert jobs == [(job.pk, "answer")]
    assert not StudioBrief.objects.exists() and not Post.objects.exists()


def test_legacy_entry_choices_are_kept_as_human_brief_inputs_not_immediate_pipeline(client, world, photo, jobs):
    reference = photo()
    client.force_login(world.editor)
    response = client.post(
        _url("create", world),
        {
            "idea": "A site visit campaign",
            "goal": "leads",
            "notes": "Saturday only, no invented prices",
            "accounts": [str(world.linkedin.pk)],
            "source_picture": str(reference.pk),
            "style_lock": "on",
        },
    )
    assert response.status_code == 302
    job = AgencyJob.objects.get()
    text = Message.objects.get(pk=job.input["message_id"]).body
    assert text == "A site visit campaign"  # the choices travel as fields, never as sentences
    assert job.input["create"] == {
        "goal": "leads",
        "notes": "Saturday only, no invented prices",
        "accounts": [str(world.linkedin.pk)],
    }
    assert job.input["reference_id"] == str(reference.pk) and job.input["style_mode"] == "brand"
    assert not StudioBrief.objects.exists()


@pytest.mark.parametrize("field", ["accounts", "source_picture"])
def test_primary_entry_refuses_foreign_or_unknown_choices_before_a_message(client, world, jobs, field):
    client.force_login(world.editor)
    response = client.post(
        _url("create", world),
        {"idea": "Use my choices", field: [str(uuid4())] if field == "accounts" else str(uuid4())},
    )
    assert response.status_code == 400
    assert not Message.objects.exists() and not AgencyJob.objects.exists() and not StudioBrief.objects.exists()


def test_scoped_current_draft_photo_and_style_survive_the_next_send_and_reload(client, world, photo, jobs):
    conversation, brief, _ = _thread(world)
    reference = photo()
    brief.source_picture = reference
    brief.style_lock = False
    brief.save(update_fields=["source_picture", "style_lock"])
    client.force_login(world.editor)
    response = client.post(
        _url("thread_send", world, conversation_id=conversation.pk),
        {"body": "Shorten this draft's caption", "target_brief_id": str(brief.pk)},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    html = _html(client, world, conversation)
    assert f'<option value="{brief.pk}" selected>' in html
    assert f'<option value="{reference.pk}" selected>' in html
    assert 'value="fresh" selected' in html and reference.file.url in html
    assert 'data-current-choice="fresh"' in html


def test_older_selected_photo_is_preserved_beyond_the_recent_library_cutoff(client, world, photo, jobs):
    conversation, brief, _ = _thread(world)
    reference = photo(filename="original-project.jpg")
    for number in range(25):
        photo(filename=f"newer-{number}.jpg")
    brief.source_picture = reference
    brief.save(update_fields=["source_picture"])
    brief.job.input = {"target_brief_id": str(brief.pk)}
    brief.job.save(update_fields=["input"])
    client.force_login(world.editor)
    html = _html(client, world, conversation)
    assert f'<option value="{reference.pk}" selected>' in html and reference.file.url in html


def test_receipt_shows_the_exact_account_scheduled_time_and_keeps_polling(client, world):
    conversation, _, pp = _thread(world, status="scheduled")
    when = timezone.now() + timedelta(days=1)
    pp.scheduled_at = when
    pp.save(update_fields=["scheduled_at"])
    client.force_login(world.editor)
    html = _html(client, world, conversation)
    assert "data-publication-receipt=" in html and world.linkedin.account_name in html
    assert when.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).strftime("%H:%M") in html
    assert "Asia/Kolkata" in html and "Scheduled for" in html
    assert 'hx-trigger="every 30s"' in html


def test_published_receipt_records_native_id_url_and_time_without_polling(client, world):
    conversation, _, pp = _thread(
        world, status="published", extra={"permalink": "https://www.linkedin.com/feed/update/recorded/"}
    )
    pp.platform_post_id = "native-confirmed-123"
    pp.published_at = timezone.now()
    pp.save(update_fields=["platform_post_id", "published_at"])
    client.force_login(world.editor)
    html = _html(client, world, conversation)
    assert "Native post ID: native-confirmed-123" in html and "Recorded delivery:" in html
    assert 'href="https://www.linkedin.com/feed/update/recorded/"' in html
    assert 'hx-trigger="every 30s"' not in html


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "data:text/html,<script>x</script>", "https://secret:password@example.com/post"]
)
def test_provider_post_links_cannot_be_script_or_credential_urls(client, world, url):
    conversation, _, _ = _thread(world, status="published", extra={"permalink": url})
    client.force_login(world.editor)
    html = _html(client, world, conversation)
    assert f'href="{url}"' not in html


@pytest.mark.parametrize("status", ["failed", "scheduled"])
def test_unknown_result_never_looks_like_a_safe_retry_or_confirmed_delivery(client, world, status):
    conversation, _, pp = _thread(
        world,
        status=status,
        extra={"_delivery_state": {"kind": "unknown", "attempt_id": str(uuid4()), "content_fingerprint": "snapshot"}},
    )
    pp.publish_error = "A sensitive raw provider exception must not be shown"
    pp.save(update_fields=["publish_error"])
    client.force_login(world.editor)
    html = _html(client, world, conversation)
    assert "Delivery outcome unknown" in html and "do not retry blindly" in html
    assert "sensitive raw provider" not in html
    assert "Record the existing post" not in html  # Editors cannot make approval decisions.
    assert 'hx-trigger="every 30s"' in html


def test_owner_can_access_scoped_unknown_delivery_decisions(client, world):
    attempt = str(uuid4())
    conversation, _, _ = _thread(
        world,
        status="failed",
        extra={
            "_delivery_state": {"kind": "unknown", "attempt_id": attempt, "content_fingerprint": "content-snapshot"}
        },
    )
    client.force_login(world.owner)
    html = _html(client, world, conversation)
    assert "Record the existing post" in html and "Return for human review" in html
    assert f'name="expected_attempt_id" value="{attempt}"' in html
    assert 'name="expected_fingerprint" value="content-snapshot"' in html
    assert 'name="confirmed" value="1" required' in html


def test_receipt_identifies_original_native_destination_after_a_reconnection(client, world):
    conversation, _, _ = _thread(
        world,
        status="failed",
        extra={
            "_delivery_state": {
                "kind": "unknown",
                "attempt_id": str(uuid4()),
                "content_fingerprint": "snapshot",
                "destination": {
                    "account_id": str(world.linkedin.pk),
                    "platform": world.linkedin.platform,
                    "native_id": "original-page-id",
                },
            }
        },
    )
    client.force_login(world.owner)
    html = _html(client, world, conversation)
    assert (
        "saved destination changed after this attempt" in html
        and "Original native account ID: original-page-id" in html
    )
    assert "Record the existing post" not in html and "Return for human review" not in html


def test_expired_receipt_prompts_review_and_a_future_time(client, world):
    conversation, _, _ = _thread(
        world,
        status="failed",
        extra={"_delivery_state": {"kind": "expired", "attempt_id": str(uuid4()), "content_fingerprint": "snapshot"}},
    )
    client.force_login(world.owner)
    html = _html(client, world, conversation)
    assert "Expired — needs review" in html and "Return expired content for review" in html
    assert "Record the existing post" not in html


def test_foreign_destination_or_post_cannot_leak_a_receipt(client, world):
    conversation, brief, pp = _thread(world, status="published", extra={"permalink": "https://private.example/post"})
    foreign = Workspace.objects.create(organization=Organization.objects.create(name="Other"), name="Other")
    account = SocialAccount.objects.create(
        workspace=foreign, platform="x", account_platform_id="other", account_name="PRIVATE OTHER BRAND"
    )
    pp.social_account = account
    pp.save(update_fields=["social_account"])
    client.force_login(world.editor)
    html = _html(client, world, conversation)
    assert "PRIVATE OTHER BRAND" not in html and "https://private.example/post" not in html
    foreign_post = Post.objects.create(workspace=foreign, author=world.owner, caption="Private other content")
    brief.post = foreign_post
    brief.save(update_fields=["post"])
    assert "data-publication-receipt=" not in _html(client, world, conversation)


def test_unavailable_stale_and_stored_sources_warn_before_the_collapsed_evidence(client, world):
    conversation, brief, _ = _thread(world)
    job = brief.job
    job.result = {
        "creative_brief": _complete_intake(),
        "awaiting_confirmation": True,
        "sources": {
            "fetched_at": (timezone.now() - timedelta(hours=25)).isoformat(),
            "website": {"status": "unavailable"},
            "channels": [{"source": "stored_history", "posts": []}],
        },
    }
    job.save(update_fields=["result"])
    client.force_login(world.editor)
    html = _html(client, world, conversation)
    assert "Website evidence is unavailable" in html and "This evidence is more than a day old" in html
    assert "not a fresh account read" in html
    assert html.index("data-source-warnings") < html.index(
        f'data-thread-details-key="sources-{conversation.messages.get().pk}"'
    )
