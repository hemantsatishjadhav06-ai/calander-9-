"""The rules: fingerprints, revisions, who may approve, and when publishing may start."""

import threading

import pytest
from background_task.models import Task
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import override_settings

from apps.approvals.actor import API, DASHBOARD, PORTAL, acting_as
from apps.blog import services
from apps.blog.models import BlogPost, BlogPostEvent
from apps.blog.tests.conftest import approved_post, make_post
from apps.composer.models import PlatformPost, PostMedia
from apps.composer.models import Post as ComposerPost
from apps.social_accounts.models import SocialAccount

Status = BlogPost.Status
Action = BlogPostEvent.Action
TOKEN = "github_pat_test"


def actions(post):
    return list(post.events.order_by("created_at", "id").values_list("action", flat=True))


# ---------------------------------------------------------------------------
# Fingerprint and revision
# ---------------------------------------------------------------------------


def test_fingerprint_is_stable_and_covers_every_published_field(world, image_asset):
    post = make_post(world)
    base = services.fingerprint(post)
    assert base == services.fingerprint(BlogPost.objects.get(pk=post.pk))
    assert len(base) == 64

    changes = {
        "title": "Other title",
        "slug": "other-slug",
        "excerpt": "Other excerpt",
        "body": "Other body",
        "featured_image_alt": "alt",
        "seo_title": "SEO",
        "meta_description": "Meta",
        "category": "Price Guide",
        "faq": [{"q": "Q?", "a": "A."}],
        "site_id": world.morespace.pk,
        "featured_image_id": image_asset().pk,
    }
    for name, value in changes.items():
        copy = BlogPost.objects.get(pk=post.pk)
        setattr(copy, name, value)
        assert services.fingerprint(copy) != base, name


def test_fingerprint_changes_when_the_image_file_is_replaced(world, image_asset):
    asset = image_asset()
    post = make_post(world, featured_image=asset, featured_image_alt="Tower")
    before = services.fingerprint(post)
    asset.file.name = "media_library/assets/replaced.png"
    asset.save(update_fields=["file"])
    assert services.fingerprint(BlogPost.objects.get(pk=post.pk)) != before


def test_saving_content_bumps_the_revision_and_a_no_op_save_does_not(world):
    post = make_post(world)
    assert post.revision == 1
    assert actions(post) == [Action.CREATED]

    post = services.update_content(post, world.editor, title="Flats in Kokapet 2026: prices")
    assert post.revision == 2
    post = services.update_content(post, world.editor, title="Flats in Kokapet 2026: prices")
    assert post.revision == 2
    assert actions(post) == [Action.CREATED, Action.EDITED]
    assert post.events.get(action=Action.EDITED).fingerprint == services.fingerprint(post)


def test_editing_an_approved_post_withdraws_the_approval(world):
    post = approved_post(world)
    assert post.status == Status.APPROVED
    assert post.approved_fingerprint == services.fingerprint(post)

    post = services.update_content(post, world.editor, body=post.body + "\n\nOne more line.")

    assert post.status == Status.PENDING_REVIEW
    assert post.approved_fingerprint == "" and post.approved_by is None and post.approved_revision is None
    assert actions(post)[-2:] == [Action.EDITED, Action.APPROVAL_WITHDRAWN]


def test_editing_a_failed_post_withdraws_its_approval_too(world):
    post = approved_post(world)
    BlogPost.objects.filter(pk=post.pk).update(status=Status.FAILED)
    post = services.update_content(BlogPost.objects.get(pk=post.pk), world.editor, category="Price Guide")
    assert post.status == Status.PENDING_REVIEW
    assert not post.approved_fingerprint


def test_editing_a_published_post_needs_approval_again_and_keeps_its_address(world):
    post = approved_post(world)
    BlogPost.objects.filter(pk=post.pk).update(
        status=Status.PUBLISHED, published_card={"slug": post.slug, "title": post.title}
    )
    post = BlogPost.objects.get(pk=post.pk)
    with pytest.raises(ValidationError):
        services.update_content(post, world.editor, slug="new-address")
    post = services.update_content(post, world.editor, excerpt="Updated excerpt")
    assert post.status == Status.PENDING_REVIEW
    assert not post.approved_fingerprint


def test_cannot_edit_while_publishing(world):
    post = approved_post(world)
    BlogPost.objects.filter(pk=post.pk).update(status=Status.PUBLISHING)
    with pytest.raises(services.BlogWorkflowError):
        services.update_content(BlogPost.objects.get(pk=post.pk), world.editor, title="Sneaky")


def test_slug_is_validated(world):
    with pytest.raises(ValidationError):
        make_post(world, slug="Not A Slug!")
    with pytest.raises(ValidationError):
        make_post(world, slug="index")


def test_only_members_who_may_create_can_write_or_submit(world):
    with pytest.raises(PermissionDenied):
        make_post(world, author=world.viewer)
    post = make_post(world)
    with pytest.raises(PermissionDenied):
        services.submit_for_review(post, world.client)
    with pytest.raises(PermissionDenied):
        services.update_content(post, world.viewer, title="x")


# ---------------------------------------------------------------------------
# Who may approve
# ---------------------------------------------------------------------------


def _pending(world):
    post = make_post(world)
    return services.submit_for_review(post, world.editor)


def test_dashboard_approver_can_approve(world):
    post = _pending(world)
    with acting_as(world.owner, DASHBOARD):
        post = services.approve(post, "Looks good")
    assert post.status == Status.APPROVED
    assert post.approved_by == world.owner
    assert post.approved_revision == post.revision
    event = post.events.get(action=Action.APPROVED)
    assert event.user == world.owner and event.detail == "Looks good" and event.fingerprint == post.approved_fingerprint


@pytest.mark.parametrize("channel", [API, PORTAL])
def test_approver_outside_the_dashboard_cannot_approve(world, channel):
    post = _pending(world)
    with acting_as(world.owner, channel), pytest.raises(PermissionDenied):
        services.approve(post)
    assert BlogPost.objects.get(pk=post.pk).status == Status.PENDING_REVIEW


def test_system_actor_cannot_approve(world):
    post = _pending(world)
    with pytest.raises(PermissionDenied):
        services.approve(post)  # no acting_as: the worker / a management command


@pytest.mark.parametrize("role", ["editor", "client", "viewer"])
def test_members_without_internal_approval_rights_cannot_approve(world, role):
    post = _pending(world)
    with acting_as(getattr(world, role), DASHBOARD), pytest.raises(PermissionDenied):
        services.approve(post)


def test_request_changes_is_approver_only_and_needs_a_comment(world):
    post = _pending(world)
    with acting_as(world.editor, DASHBOARD), pytest.raises(PermissionDenied):
        services.request_changes(post, "fix it")
    with acting_as(world.owner, DASHBOARD):
        with pytest.raises(services.BlogWorkflowError):
            services.request_changes(post, "   ")
        post = services.request_changes(post, "Add prices")
    assert post.status == Status.CHANGES_REQUESTED
    assert post.events.get(action=Action.CHANGES_REQUESTED).detail == "Add prices"
    # The author can resubmit.
    assert services.submit_for_review(post, world.editor).status == Status.PENDING_REVIEW


def test_cannot_approve_a_draft_or_submit_an_incomplete_post(world):
    post = make_post(world)
    with acting_as(world.owner), pytest.raises(services.BlogWorkflowError):
        services.approve(post)
    empty = make_post(world, slug="empty", body="")
    with pytest.raises(services.BlogWorkflowError):
        services.submit_for_review(empty, world.editor)


# ---------------------------------------------------------------------------
# Starting a publish
# ---------------------------------------------------------------------------


@override_settings(BLOG_GITHUB_TOKEN=TOKEN)
def test_publish_refused_without_approval(world):
    post = _pending(world)
    with acting_as(world.owner), pytest.raises(services.BlogWorkflowError):
        services.start_publish(post)
    assert BlogPost.objects.get(pk=post.pk).status == Status.PENDING_REVIEW
    assert not Task.objects.filter(task_name__endswith="publish_blog_post").exists()


@override_settings(BLOG_GITHUB_TOKEN=TOKEN)
def test_publish_refused_when_the_approval_is_stale(world, image_asset):
    asset = image_asset()
    post = approved_post(world, featured_image=asset, featured_image_alt="Tower")
    # The image is replaced in the media library after approval: no content
    # save, so no revision bump — only the fingerprint can catch it.
    asset.file.name = "media_library/assets/swapped.png"
    asset.save(update_fields=["file"])

    with acting_as(world.owner), pytest.raises(services.ApprovalStaleError):
        services.start_publish(post)

    post = BlogPost.objects.get(pk=post.pk)
    assert post.status == Status.PENDING_REVIEW
    assert not post.approved_fingerprint
    assert Action.APPROVAL_WITHDRAWN in actions(post)
    assert not Task.objects.filter(task_name__endswith="publish_blog_post").exists()


@override_settings(BLOG_GITHUB_TOKEN="")
def test_publish_refused_without_a_token_and_the_post_stays_approved(world):
    post = approved_post(world)
    with acting_as(world.owner), pytest.raises(services.PublishNotConfiguredError) as excinfo:
        services.start_publish(post)
    assert "BLOG_GITHUB_TOKEN" in str(excinfo.value)
    assert world.neopolis.repo in str(excinfo.value)
    assert BlogPost.objects.get(pk=post.pk).status == Status.APPROVED
    assert not Task.objects.filter(task_name__endswith="publish_blog_post").exists()


@override_settings(BLOG_GITHUB_TOKEN=TOKEN)
def test_only_a_dashboard_approver_can_start_publishing(world):
    post = approved_post(world)
    for user, channel in ((world.owner, API), (world.editor, DASHBOARD), (world.client, DASHBOARD)):
        with acting_as(user, channel), pytest.raises(PermissionDenied):
            services.start_publish(post)
    with pytest.raises(PermissionDenied):
        services.start_publish(post)  # system actor
    assert BlogPost.objects.get(pk=post.pk).status == Status.APPROVED


@override_settings(BLOG_GITHUB_TOKEN=TOKEN)
def test_publish_claim_wins_once(world):
    post = approved_post(world)
    with acting_as(world.owner):
        claimed = services.start_publish(post)
        with pytest.raises(services.PublishConflictError):
            services.start_publish(post)  # double click
    assert claimed.status == Status.PUBLISHING
    assert claimed.publish_attempts == 1
    assert Task.objects.filter(task_name__endswith="publish_blog_post").count() == 1
    assert actions(claimed).count(Action.PUBLISH_STARTED) == 1


@override_settings(BLOG_GITHUB_TOKEN=TOKEN)
def test_retry_from_failed_needs_a_current_approval(world):
    post = approved_post(world)
    BlogPost.objects.filter(pk=post.pk).update(status=Status.FAILED, publish_attempts=1)
    with acting_as(world.owner):
        retried = services.start_publish(BlogPost.objects.get(pk=post.pk))
    assert retried.status == Status.PUBLISHING and retried.publish_attempts == 2

    BlogPost.objects.filter(pk=post.pk).update(status=Status.FAILED, approved_revision=None)
    with acting_as(world.owner), pytest.raises(services.BlogWorkflowError):
        services.start_publish(BlogPost.objects.get(pk=post.pk))


@pytest.mark.django_db(transaction=True)
@override_settings(BLOG_GITHUB_TOKEN=TOKEN)
def test_concurrent_publish_clicks_claim_once(world):
    post = approved_post(world)
    barrier = threading.Barrier(2)
    outcomes = []

    def click():
        try:
            barrier.wait()
            with acting_as(world.owner):
                services.start_publish(BlogPost.objects.get(pk=post.pk))
            outcomes.append("claimed")
        except services.PublishConflictError:
            outcomes.append("conflict")
        finally:
            connection.close()

    threads = [threading.Thread(target=click) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["claimed", "conflict"]
    post = BlogPost.objects.get(pk=post.pk)
    assert post.status == Status.PUBLISHING and post.publish_attempts == 1
    assert Task.objects.filter(task_name__endswith="publish_blog_post").count() == 1


# ---------------------------------------------------------------------------
# Social drafts
# ---------------------------------------------------------------------------


def _account(world, platform, status=SocialAccount.ConnectionStatus.CONNECTED):
    return SocialAccount.objects.create(
        workspace=world.workspace,
        platform=platform,
        account_platform_id=f"id-{platform}-{status}",
        account_name=f"{platform} account",
        connection_status=status,
    )


def test_social_drafts_are_plain_drafts_for_suitable_channels(world, image_asset):
    asset = image_asset()
    post = approved_post(world, featured_image=asset, featured_image_alt="Tower")
    bluesky = _account(world, "bluesky")
    linkedin = _account(world, "linkedin_company", SocialAccount.ConnectionStatus.TOKEN_EXPIRING)
    _account(world, "youtube")  # video only
    _account(world, "facebook", SocialAccount.ConnectionStatus.DISCONNECTED)

    draft = services.create_social_drafts(post, world.editor)

    assert isinstance(draft, ComposerPost)
    assert draft.workspace == world.workspace and draft.author == world.editor
    assert draft.scheduled_at is None
    assert post.title in draft.caption and post.excerpt in draft.caption
    assert "https://www.neopolisinfra.com/blog/flats-in-kokapet-2026" in draft.caption
    pps = list(draft.platform_posts.all())
    assert {pp.social_account_id for pp in pps} == {bluesky.pk, linkedin.pk}
    assert {pp.status for pp in pps} == {PlatformPost.Status.DRAFT}
    assert PostMedia.objects.get(post=draft).media_asset == asset
    assert Action.SOCIAL_DRAFTS_CREATED in actions(post)


def test_social_drafts_without_channels_are_channel_less(world):
    post = approved_post(world)
    draft = services.create_social_drafts(post, world.editor)
    assert draft.platform_posts.count() == 0
    assert draft.status == "draft"


def test_social_drafts_need_an_approved_or_published_post(world):
    post = make_post(world)
    with pytest.raises(services.BlogWorkflowError):
        services.create_social_drafts(post, world.editor)
    approved = approved_post(world, slug="another")
    with pytest.raises(PermissionDenied):
        services.create_social_drafts(approved, world.viewer)
