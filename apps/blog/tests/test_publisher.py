"""The GitHub flow: which files, in what order, and how the deploy is followed."""

import datetime as dt
import io
from unittest import mock

import pytest
from background_task.models import Task
from django.test import override_settings
from django.utils import timezone
from PIL import Image

from apps.approvals.actor import acting_as
from apps.blog import publisher, services
from apps.blog.models import BlogPost, BlogPostEvent
from apps.blog.tests.conftest import (
    MORESPACE_REPO,
    NEOPOLIS_REPO,
    FakeGitHub,
    FakeResponse,
    approved_post,
)

Status = BlogPost.Status
Action = BlogPostEvent.Action
TOKEN = "github_pat_test"

NEOPOLIS_INDEX = (
    "<!DOCTYPE html><html><head><title>Blog</title>"
    '<script type="application/ld+json">{"@context":"https://schema.org","@type":"ItemList","itemListElement":'
    '[{"@type":"ListItem","position":1,"url":"https://www.neopolisinfra.com/blog/old-post.html","name":"Old post"}]}'
    "</script></head><body>"
    '<div class="hscroll"><a class=\'bcard\' href=\'/blog/old-post\'><div class="bimg"><img src="img/old-post-hero.jpg?v=2" '
    'alt="Old post"></div><div class="bbody"><span class="cat">Buyer Guide</span><h3>Old post</h3><p>Old.</p>'
    '<span class="rt">9 min read</span></div></a></div><p class="hscroll-hint">more</p></body></html>'
)


@pytest.fixture(autouse=True)
def _token():
    with override_settings(BLOG_GITHUB_TOKEN=TOKEN):
        yield


def _claim(world, post):
    with acting_as(world.owner):
        return services.start_publish(post)


def _run_publish(post, fake):
    with mock.patch("apps.blog.publisher.requests.Session", return_value=fake):
        publisher.run_publish(str(post.pk), post.publish_attempts)
    return BlogPost.objects.get(pk=post.pk)


def _run_poll(post, fake, live=None, verify_tries=0):
    live = live or FakeResponse(200, text=f"<h1>{post.title}</h1>")
    with (
        mock.patch("apps.blog.publisher.requests.Session", return_value=fake),
        mock.patch("apps.blog.publisher.requests.get", return_value=live) as get,
    ):
        publisher.run_poll(str(post.pk), post.publish_attempts, verify_tries)
    return BlogPost.objects.get(pk=post.pk), get


def _png(width=2400, height=1350):
    buf = io.BytesIO()
    Image.new("RGBA", (width, height), (200, 30, 30, 255)).save(buf, format="PNG")
    return buf.getvalue()


def test_neopolis_publish_writes_one_commit_with_post_image_and_index(world, image_asset):
    asset = image_asset(_png())
    post = _claim(world, approved_post(world, featured_image=asset, featured_image_alt="Kokapet towers"))
    fake = FakeGitHub(NEOPOLIS_REPO, {"publish-payload3/blog/index.html": NEOPOLIS_INDEX})

    post = _run_publish(post, fake)

    # Read the head and the files at that commit, then blobs -> tree -> commit -> ref, then dispatch.
    assert fake.calls[:5] == [
        ("GET", "/git/ref/heads/main"),
        ("GET", f"/git/commits/{'a' * 40}"),
        ("GET", "/contents/publish-payload3/blog/flats-in-kokapet-2026.html"),
        ("GET", "/contents/publish-payload3/blog/index.html"),
        ("GET", "/contents/generated/blog/img/flats-in-kokapet-2026-hero.jpg"),
    ]
    assert fake.writes() == [
        ("POST", "/git/blobs"),
        ("POST", "/git/blobs"),
        ("POST", "/git/blobs"),
        ("POST", "/git/trees"),
        ("POST", "/git/commits"),
        ("PATCH", "/git/refs/heads/main"),
        ("POST", "/actions/workflows/publish3.yml/dispatches"),
    ]
    tree = next(iter(fake.trees.values()))
    assert tree["base_tree"] == "t" + "a" * 39
    assert sorted(e["path"] for e in tree["tree"]) == [
        "generated/blog/img/flats-in-kokapet-2026-hero.jpg",
        "publish-payload3/blog/flats-in-kokapet-2026.html",
        "publish-payload3/blog/index.html",
    ]
    commit = next(iter(fake.commits.values()))
    assert commit["parents"] == ["a" * 40]
    assert "Publish blog post: Flats in Kokapet 2026" in commit["message"]
    assert fake.dispatches == [("/actions/workflows/publish3.yml/dispatches", {"ref": "main"})]

    page = fake.files["publish-payload3/blog/flats-in-kokapet-2026.html"].decode()
    assert '<link rel="canonical" href="https://www.neopolisinfra.com/blog/flats-in-kokapet-2026">' in page
    index = fake.files["publish-payload3/blog/index.html"].decode()
    assert index.index("/blog/flats-in-kokapet-2026'") < index.index("/blog/old-post'")
    hero = Image.open(io.BytesIO(fake.files["generated/blog/img/flats-in-kokapet-2026-hero.jpg"]))
    assert hero.format == "JPEG" and hero.width == 1600

    assert post.status == Status.PUBLISHING
    assert post.commit_sha == fake.head
    assert post.dispatched_at is not None
    assert post.published_card["slug"] == "flats-in-kokapet-2026"
    assert Action.COMMITTED in post.events.values_list("action", flat=True)
    assert Task.objects.filter(task_name__endswith="poll_blog_deploy").count() == 1


def test_morespace_publish_uses_blog_paths_and_rebuilds_the_index(world):
    earlier = approved_post(world, site=world.morespace, slug="older-post", title="Older post")
    BlogPost.objects.filter(pk=earlier.pk).update(
        status=Status.PUBLISHED,
        published_card={
            "slug": "older-post",
            "title": "Older post",
            "text": "Earlier.",
            "category": "Insights",
            "has_image": False,
            "revision": 1,
            "date": "2026-09-01",
            "read_minutes": 2,
        },
    )
    post = _claim(world, approved_post(world, site=world.morespace))
    fake = FakeGitHub(MORESPACE_REPO, {})

    post = _run_publish(post, fake)

    assert set(fake.files) == {"blog/flats-in-kokapet-2026.html", "blog/index.html"}
    assert fake.dispatches == [("/actions/workflows/netlify-publish.yml/dispatches", {"ref": "main"})]
    index = fake.files["blog/index.html"].decode()
    assert index.index("blog/flats-in-kokapet-2026.html") < index.index("blog/older-post.html")
    page = fake.files["blog/flats-in-kokapet-2026.html"].decode()
    assert 'href="css/styles.css"' in page and 'src="js/main.js"' in page and '<base href="../">' in page
    assert post.status == Status.PUBLISHING


def test_nothing_is_written_when_the_content_moves_after_the_claim(world):
    post = _claim(world, approved_post(world))
    fake = FakeGitHub(NEOPOLIS_REPO, {"publish-payload3/blog/index.html": NEOPOLIS_INDEX})
    # Something changes the stored content behind the claim (not via the service).
    BlogPost.objects.filter(pk=post.pk).update(body="Unapproved text")

    post = _run_publish(post, fake)

    assert fake.writes() == []
    assert post.status == Status.PENDING_REVIEW
    assert not post.approved_fingerprint
    assert Action.APPROVAL_WITHDRAWN in post.events.values_list("action", flat=True)


def test_guard_runs_immediately_before_the_first_write(world):
    post = _claim(world, approved_post(world))
    fake = FakeGitHub(NEOPOLIS_REPO, {"publish-payload3/blog/index.html": NEOPOLIS_INDEX})
    real_get_file = publisher.GitHubClient.get_file

    def get_file_then_edit(self, path, ref, **kwargs):
        result = real_get_file(self, path, ref, **kwargs)
        if path.endswith("index.html"):  # the last read before writing
            BlogPost.objects.filter(pk=post.pk).update(title="Changed while reading")
        return result

    with mock.patch.object(publisher.GitHubClient, "get_file", get_file_then_edit):
        post = _run_publish(post, fake)

    assert fake.writes() == []
    assert post.status == Status.PENDING_REVIEW


def test_an_existing_page_is_never_overwritten_by_a_new_post(world):
    post = _claim(world, approved_post(world))
    fake = FakeGitHub(
        NEOPOLIS_REPO,
        {
            "publish-payload3/blog/index.html": NEOPOLIS_INDEX,
            "publish-payload3/blog/flats-in-kokapet-2026.html": "<html>hand-written</html>",
        },
    )
    post = _run_publish(post, fake)
    assert fake.writes() == []
    assert post.status == Status.FAILED
    assert "already exists" in post.last_error
    assert fake.files["publish-payload3/blog/flats-in-kokapet-2026.html"] == b"<html>hand-written</html>"


def test_a_moved_branch_is_reread_and_retried(world):
    post = _claim(world, approved_post(world))
    fake = FakeGitHub(NEOPOLIS_REPO, {"publish-payload3/blog/index.html": NEOPOLIS_INDEX})
    fake.move_ref_times = 1
    post = _run_publish(post, fake)
    assert [c for c in fake.calls if c[0] == "PATCH"] == [("PATCH", "/git/refs/heads/main")] * 2
    assert fake.calls.count(("GET", "/git/ref/heads/main")) == 2
    assert post.commit_sha == fake.head


def test_index_without_the_card_list_fails_without_writing(world):
    post = _claim(world, approved_post(world))
    fake = FakeGitHub(NEOPOLIS_REPO, {"publish-payload3/blog/index.html": "<html><body>redesigned</body></html>"})
    post = _run_publish(post, fake)
    assert fake.writes() == []
    assert post.status == Status.FAILED
    assert "hscroll" in post.last_error


def test_dispatch_failure_is_reported_with_the_commit(world):
    post = _claim(world, approved_post(world))
    fake = FakeGitHub(NEOPOLIS_REPO, {"publish-payload3/blog/index.html": NEOPOLIS_INDEX})
    fake.dispatch_status = 422
    post = _run_publish(post, fake)
    assert post.status == Status.FAILED
    assert post.commit_sha
    assert post.commit_sha[:7] in post.last_error
    assert Action.DEPLOY_FAILED in post.events.values_list("action", flat=True)


def test_auth_errors_are_readable(world):
    post = _claim(world, approved_post(world))
    fake = mock.Mock()
    fake.request.return_value = FakeResponse(401, {"message": "Bad credentials"})
    post = _run_publish(post, fake)
    assert post.status == Status.FAILED
    assert "BLOG_GITHUB_TOKEN" in post.last_error and "401" in post.last_error


def test_a_token_removed_after_the_click_returns_the_post_to_approved(world):
    post = _claim(world, approved_post(world))
    fake = FakeGitHub(NEOPOLIS_REPO, {})
    with override_settings(BLOG_GITHUB_TOKEN=""):
        post = _run_publish(post, fake)
    assert fake.calls == []
    assert post.status == Status.APPROVED
    assert "BLOG_GITHUB_TOKEN" in post.last_error


def test_republishing_identical_files_skips_the_commit_but_deploys(world):
    post = _claim(world, approved_post(world))
    fake = FakeGitHub(NEOPOLIS_REPO, {"publish-payload3/blog/index.html": NEOPOLIS_INDEX})
    post = _run_publish(post, fake)
    first_head = fake.head
    BlogPost.objects.filter(pk=post.pk).update(status=Status.FAILED)
    post = _claim(world, BlogPost.objects.get(pk=post.pk))
    fake.calls.clear()
    post = _run_publish(post, fake)
    assert [c for c in fake.writes() if c[1] != "/actions/workflows/publish3.yml/dispatches"] == []
    assert post.commit_sha == first_head
    assert len(fake.dispatches) == 2


# ---------------------------------------------------------------------------
# Following the deploy
# ---------------------------------------------------------------------------


def _dispatched(world, fake, **post_overrides):
    post = _claim(world, approved_post(world, **post_overrides))
    return _run_publish(post, fake)


def _run(fake, post, status="completed", conclusion="success", **extra):
    run = {
        "id": 77,
        "html_url": f"https://github.com/{fake.repo}/actions/runs/77",
        "status": status,
        "conclusion": conclusion,
        "head_sha": post.commit_sha,
        "created_at": (post.dispatched_at + dt.timedelta(seconds=3)).isoformat().replace("+00:00", "Z"),
    }
    run.update(extra)
    fake.runs = [run]
    return run


def test_successful_run_and_live_page_publish_the_post(world):
    fake = FakeGitHub(NEOPOLIS_REPO, {"publish-payload3/blog/index.html": NEOPOLIS_INDEX})
    post = _dispatched(world, fake)
    _run(fake, post)

    post, get = _run_poll(post, fake)

    assert post.status == Status.PUBLISHED
    assert post.published_url == "https://www.neopolisinfra.com/blog/flats-in-kokapet-2026"
    assert post.published_at is not None
    assert post.deploy_run_url.endswith("/actions/runs/77")
    assert get.call_args.args[0] == "https://www.neopolisinfra.com/blog/flats-in-kokapet-2026"
    trail = list(post.events.values_list("action", flat=True))
    assert Action.DEPLOY_SUCCEEDED in trail and Action.VERIFIED in trail


def test_morespace_live_check_uses_the_html_url(world):
    fake = FakeGitHub(MORESPACE_REPO, {})
    post = _dispatched(world, fake, site=world.morespace)
    _run(fake, post)
    post, get = _run_poll(post, fake)
    assert post.status == Status.PUBLISHED
    assert get.call_args.args[0] == "https://morespace.netlify.app/blog/flats-in-kokapet-2026.html"


def test_a_running_deploy_is_polled_again(world):
    fake = FakeGitHub(NEOPOLIS_REPO, {"publish-payload3/blog/index.html": NEOPOLIS_INDEX})
    post = _dispatched(world, fake)
    _run(fake, post, status="in_progress", conclusion=None)
    before = Task.objects.filter(task_name__endswith="poll_blog_deploy").count()
    post, _get = _run_poll(post, fake)
    assert post.status == Status.PUBLISHING
    assert post.deploy_status == "in_progress"
    assert Task.objects.filter(task_name__endswith="poll_blog_deploy").count() == before + 1


def test_a_failed_run_fails_the_post_with_the_run_link(world):
    fake = FakeGitHub(NEOPOLIS_REPO, {"publish-payload3/blog/index.html": NEOPOLIS_INDEX})
    post = _dispatched(world, fake)
    _run(fake, post, conclusion="failure")
    post, _get = _run_poll(post, fake)
    assert post.status == Status.FAILED
    assert "failure" in post.last_error and post.deploy_run_url in post.last_error
    assert Action.DEPLOY_FAILED in post.events.values_list("action", flat=True)
    assert post.approval_is_current  # a retry is allowed


def test_a_live_page_without_the_post_is_not_called_published(world):
    fake = FakeGitHub(NEOPOLIS_REPO, {"publish-payload3/blog/index.html": NEOPOLIS_INDEX})
    post = _dispatched(world, fake)
    _run(fake, post)
    missing = FakeResponse(404, text="Not found")
    post, _get = _run_poll(post, fake, live=missing, verify_tries=publisher.VERIFY_RETRIES - 1)
    assert post.status == Status.FAILED
    assert "HTTP 404" in post.last_error


def test_the_deploy_deadline_fails_the_post(world):
    fake = FakeGitHub(NEOPOLIS_REPO, {"publish-payload3/blog/index.html": NEOPOLIS_INDEX})
    post = _dispatched(world, fake)
    BlogPost.objects.filter(pk=post.pk).update(dispatched_at=timezone.now() - dt.timedelta(minutes=25))
    post = BlogPost.objects.get(pk=post.pk)
    fake.runs = []
    post, _get = _run_poll(post, fake)
    assert post.status == Status.FAILED
    assert "didn't finish" in post.last_error


def test_sweep_settles_a_publish_whose_worker_died(world):
    post = _claim(world, approved_post(world))
    BlogPost.objects.filter(pk=post.pk).update(publish_started_at=timezone.now() - dt.timedelta(hours=1))
    assert publisher.sweep_stuck() == 1
    post = BlogPost.objects.get(pk=post.pk)
    assert post.status == Status.FAILED
    assert "stopped without a result" in post.last_error


def test_stale_tasks_do_nothing(world):
    post = _claim(world, approved_post(world))
    fake = FakeGitHub(NEOPOLIS_REPO, {})
    with mock.patch("apps.blog.publisher.requests.Session", return_value=fake):
        publisher.run_publish(str(post.pk), post.publish_attempts + 5)
    assert fake.calls == []
    assert BlogPost.objects.get(pk=post.pk).status == Status.PUBLISHING


def test_run_lookup_ignores_an_earlier_run_on_the_same_commit(world):
    fake = FakeGitHub(NEOPOLIS_REPO, {"publish-payload3/blog/index.html": NEOPOLIS_INDEX})
    post = _dispatched(world, fake)
    stamp = post.dispatched_at

    def iso(when):
        return when.isoformat().replace("+00:00", "Z")

    old = {"id": 1, "head_sha": post.commit_sha, "created_at": iso(stamp - dt.timedelta(minutes=1))}
    other = {"id": 2, "head_sha": "f" * 40, "created_at": iso(stamp + dt.timedelta(seconds=1))}
    ours = {"id": 3, "head_sha": post.commit_sha, "created_at": iso(stamp + dt.timedelta(seconds=2))}
    client = publisher.GitHubClient(TOKEN, NEOPOLIS_REPO, session=fake)

    fake.runs = [ours, other, old]
    assert publisher._find_run(client, post)["id"] == 3
    fake.runs = [other, old]  # the branch moved before the dispatch: the first run after it
    assert publisher._find_run(client, post)["id"] == 2
    fake.runs = [old]  # a retry of an unchanged post must not latch onto the last run
    assert publisher._find_run(client, post) is None
