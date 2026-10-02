"""Commit an approved blog post into its website's repository and deploy it.

Everything goes through the GitHub REST API with ``BLOG_GITHUB_TOKEN`` — no
git binary, no clone. One publish is:

1. Read the branch head and the current post/index/image files *at that
   commit* (their blob SHAs, and the index's content for Neopolis).
2. Render the post page, the hero JPEG and the blog index.
3. Re-check, against the database, that the post is still the claimed and
   approved revision — the last moment before anything is written.
4. Write the changed files as **one commit** with the Git Data API (blobs ->
   tree -> commit -> fast-forward the branch ref), so the post, its image and
   the index land together. If the branch moved meanwhile, start again from 1.
5. Dispatch the site's deploy workflow and remember when.

A follow-up task (:func:`poll_deploy`) watches the workflow run every ~30 s
for up to ~20 minutes, then fetches the live URL and checks the post's title
is on it before calling the post published.

File paths per site kind are in :func:`site_paths`. For Neopolis anything
committed under ``publish-payload3/`` is deployed by the next workflow run,
scheduled or dispatched — which is why only a claimed, approved revision is
ever committed.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import html
import logging
from dataclasses import dataclass

import requests
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import services
from .models import BlogPost, BlogPostEvent, BlogSite
from .renderers import (
    CardData,
    IndexStructureError,
    PostContent,
    hero_jpeg_bytes,
    render_morespace_index,
    render_post_page,
    update_neopolis_index,
)

logger = logging.getLogger(__name__)

API_ROOT = "https://api.github.com"
REQUEST_TIMEOUT = 20
POLL_INTERVAL_SECONDS = 30
DEPLOY_DEADLINE = dt.timedelta(minutes=20)
VERIFY_RETRIES = 4
# A publish whose tasks have all died is settled by the sweep after this long.
STUCK_AFTER = DEPLOY_DEADLINE + dt.timedelta(minutes=10)
COMMIT_ATTEMPTS = 3

Status = BlogPost.Status
Action = BlogPostEvent.Action


class GitHubError(Exception):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


class RefMovedError(GitHubError):
    """The branch moved between reading it and updating it."""


class ApprovalMovedError(Exception):
    """The post is no longer the claimed, approved revision."""


class PostPathTakenError(Exception):
    pass


# ---------------------------------------------------------------------------
# GitHub REST client
# ---------------------------------------------------------------------------


class GitHubClient:
    def __init__(self, token: str, repo: str, *, session: requests.Session | None = None):
        self.repo = repo
        self.session = session or requests.Session()
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "SM-Manager-Blog-Publisher",
        }

    def _url(self, path: str) -> str:
        return f"{API_ROOT}/repos/{self.repo}{path}"

    def request(self, method: str, path: str, *, ok=(200,), allow_404=False, **kwargs):
        try:
            response = self.session.request(
                method, self._url(path), headers=self.headers, timeout=REQUEST_TIMEOUT, **kwargs
            )
        except requests.RequestException as exc:
            raise GitHubError(f"Couldn't reach GitHub ({exc.__class__.__name__}). Try again in a few minutes.") from exc
        if response.status_code in ok:
            return response
        if allow_404 and response.status_code == 404:
            return None
        raise GitHubError(self._explain(response, method, path), status=response.status_code)

    def _explain(self, response, method: str, path: str) -> str:
        status = response.status_code
        try:
            message = (response.json() or {}).get("message", "")
        except ValueError:
            message = (response.text or "")[:200]
        if status == 401:
            return "GitHub rejected BLOG_GITHUB_TOKEN (401): it has expired or been revoked. Create a new one."
        if status == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
            return "GitHub's API rate limit is used up for this token. Try again in an hour."
        if status in (403, 404) and "/actions/" in path:
            return (
                f"GitHub refused {method} {path} ({status}: {message}). Check that the workflow exists on the "
                f"branch and that the token has Actions read/write on {self.repo}."
            )
        if status in (403, 404):
            return (
                f"GitHub refused access to {self.repo} ({status}: {message}). The token needs Contents read/write "
                f"and Actions read/write on {self.repo}."
            )
        if status == 409:
            return f"The repository {self.repo} is empty or busy ({message})."
        return f"GitHub returned {status} for {method} {path}: {message or 'no details'}."

    # Git data -------------------------------------------------------------

    def branch_head(self, branch: str) -> str:
        return self.request("GET", f"/git/ref/heads/{branch}").json()["object"]["sha"]

    def commit_tree(self, commit_sha: str) -> str:
        return self.request("GET", f"/git/commits/{commit_sha}").json()["tree"]["sha"]

    def get_file(self, path: str, ref: str, *, with_content: bool = False) -> tuple[str, bytes | None] | None:
        """``(blob_sha, content)`` of a file at ``ref``, or ``None`` if it doesn't exist."""
        response = self.request("GET", f"/contents/{path}", params={"ref": ref}, allow_404=True)
        if response is None:
            return None
        data = response.json()
        if isinstance(data, list) or data.get("type") != "file":
            raise GitHubError(f"{path} in {self.repo} is not a file.")
        content = None
        if with_content:
            if data.get("encoding") == "base64" and data.get("content"):
                content = base64.b64decode(data["content"])
            else:  # Files over 1 MB come back without content.
                blob = self.request("GET", f"/git/blobs/{data['sha']}").json()
                content = base64.b64decode(blob["content"])
        return data["sha"], content

    def create_blob(self, content: bytes) -> str:
        body = {"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"}
        return self.request("POST", "/git/blobs", ok=(201,), json=body).json()["sha"]

    def create_tree(self, base_tree: str, entries: list[dict]) -> str:
        return self.request("POST", "/git/trees", ok=(201,), json={"base_tree": base_tree, "tree": entries}).json()[
            "sha"
        ]

    def create_commit(self, message: str, tree: str, parent: str) -> str:
        body = {"message": message, "tree": tree, "parents": [parent]}
        return self.request("POST", "/git/commits", ok=(201,), json=body).json()["sha"]

    def update_ref(self, branch: str, sha: str) -> None:
        try:
            self.request("PATCH", f"/git/refs/heads/{branch}", json={"sha": sha, "force": False})
        except GitHubError as exc:
            if exc.status == 422:
                raise RefMovedError(str(exc), status=422) from exc
            raise

    # Actions --------------------------------------------------------------

    def dispatch_workflow(self, workflow_file: str, ref: str) -> dict:
        response = self.request(
            "POST", f"/actions/workflows/{workflow_file}/dispatches", ok=(200, 204), json={"ref": ref}
        )
        if response.status_code == 200 and response.content:
            try:
                return response.json() or {}
            except ValueError:
                return {}
        return {}

    def dispatch_runs(self, workflow_file: str, branch: str) -> list[dict]:
        params = {"branch": branch, "event": "workflow_dispatch", "per_page": 10}
        data = self.request("GET", f"/actions/workflows/{workflow_file}/runs", params=params).json()
        return data.get("workflow_runs", [])

    def get_run(self, run_id: int) -> dict:
        return self.request("GET", f"/actions/runs/{run_id}").json()


def git_blob_sha(content: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


# ---------------------------------------------------------------------------
# What gets written where
# ---------------------------------------------------------------------------


def site_paths(site: BlogSite, slug: str) -> dict[str, str]:
    if site.kind == BlogSite.Kind.NEOPOLIS_STATIC:
        return {
            "post": f"publish-payload3/blog/{slug}.html",
            "index": "publish-payload3/blog/index.html",
            # The mirror script overlays generated/blog/img/*.jpg only.
            "image": f"generated/blog/img/{slug}-hero.jpg",
        }
    if site.kind == BlogSite.Kind.MORESPACE_STATIC:
        return {"post": f"blog/{slug}.html", "index": "blog/index.html", "image": f"blog/img/{slug}-hero.jpg"}
    raise ValueError(f"Unknown site kind {site.kind!r}")


def published_cards(site: BlogSite, *, exclude_post_id=None) -> list[CardData]:
    """Cards of every post of ``site`` already committed, as they were committed."""
    posts = BlogPost.objects.filter(site=site).exclude(published_card={})
    if exclude_post_id is not None:
        posts = posts.exclude(pk=exclude_post_id)
    cards = []
    for card in posts.values_list("published_card", flat=True):
        try:
            cards.append(CardData.from_dict(card))
        except (KeyError, TypeError, ValueError):
            continue
    return cards


@dataclass
class CommitResult:
    sha: str
    changed_paths: list[str]


def _render_index(site: BlogSite, post: BlogPost, content: PostContent, existing_index: bytes | None) -> bytes:
    if site.kind == BlogSite.Kind.NEOPOLIS_STATIC:
        if existing_index is None:
            raise IndexStructureError(
                f"{site_paths(site, post.slug)['index']} was not found in {site.repo}; the new card has nowhere to go."
            )
        return update_neopolis_index(existing_index.decode("utf-8"), content, origin=site.origin).encode("utf-8")
    cards = published_cards(site, exclude_post_id=post.pk)
    cards.sort(key=lambda c: c.date, reverse=True)
    return render_morespace_index([content.card(), *cards], origin=site.origin).encode("utf-8")


def commit_post(client: GitHubClient, post: BlogPost, content: PostContent, *, guard, message: str) -> CommitResult:
    """Write the post, its hero image and the index as one commit.

    ``guard`` is called immediately before the first write of every attempt
    and must raise if the post may no longer be published.
    """
    site = post.site
    paths = site_paths(site, post.slug)
    page = render_post_page(site, content).encode("utf-8")
    image = hero_jpeg_bytes(post.featured_image) if content.has_image else None

    for _attempt in range(COMMIT_ATTEMPTS):
        head = client.branch_head(site.branch)
        base_tree = client.commit_tree(head)
        existing_post = client.get_file(paths["post"], head)
        existing_index = client.get_file(paths["index"], head, with_content=site.kind == BlogSite.Kind.NEOPOLIS_STATIC)
        existing_image = client.get_file(paths["image"], head) if image is not None else None

        if existing_post is not None and not post.has_been_committed and existing_post[0] != git_blob_sha(page):
            raise PostPathTakenError(
                f"{paths['post']} already exists in {site.repo} and wasn't published from here. "
                "Change the post's address (slug) so it doesn't replace that page."
            )

        files = {
            paths["post"]: page,
            paths["index"]: _render_index(site, post, content, existing_index and existing_index[1]),
        }
        if image is not None:
            files[paths["image"]] = image
        current = {
            paths["post"]: existing_post and existing_post[0],
            paths["index"]: existing_index and existing_index[0],
            paths["image"]: existing_image and existing_image[0],
        }
        changed = {path: data for path, data in files.items() if current.get(path) != git_blob_sha(data)}

        guard()
        if not changed:
            return CommitResult(sha=head, changed_paths=[])

        entries = [
            {"path": path, "mode": "100644", "type": "blob", "sha": client.create_blob(data)}
            for path, data in changed.items()
        ]
        tree = client.create_tree(base_tree, entries)
        commit = client.create_commit(message, tree, head)
        try:
            client.update_ref(site.branch, commit)
        except RefMovedError:
            logger.info(
                "Branch %s of %s moved while publishing blog post %s; retrying", site.branch, site.repo, post.pk
            )
            continue
        return CommitResult(sha=commit, changed_paths=sorted(changed))
    raise GitHubError(f"The {site.branch} branch of {site.repo} kept changing while publishing. Try again shortly.")


def _commit_message(post: BlogPost) -> str:
    approver = post.approved_by.display_name if post.approved_by else "an approver"
    approved_on = post.approved_at.date().isoformat() if post.approved_at else "unknown date"
    return (
        f"Publish blog post: {post.title}\n\n"
        f"Revision {post.approved_revision}, approved by {approver} on {approved_on}.\n"
        f"Published from SM Manager (blog post {post.pk})."
    )


# ---------------------------------------------------------------------------
# Background steps (called from apps.blog.tasks)
# ---------------------------------------------------------------------------


def _load(post_id) -> BlogPost | None:
    return (
        BlogPost.objects.select_related("site", "workspace", "featured_image", "approved_by", "author")
        .filter(pk=post_id)
        .first()
    )


def _commit_url(site: BlogSite, sha: str) -> str:
    return f"https://github.com/{site.repo}/commit/{sha}"


def run_publish(post_id, attempt: int) -> None:
    """Commit and dispatch. Never raises: every outcome is recorded on the post."""
    post = _load(post_id)
    if post is None or post.status != Status.PUBLISHING or post.publish_attempts != attempt:
        logger.info("Blog publish task for %s attempt %s is stale; skipping", post_id, attempt)
        return

    token = services.github_token()
    if not token:
        services.return_to_approved(post, services.TOKEN_MISSING_MESSAGE.format(repo=post.site.repo), attempt=attempt)
        return
    if not services.claim_matches(post, attempt):
        services.stop_stale_publish(post, reason="The post changed after it was approved; nothing was published.")
        return

    def guard():
        fresh = _load(post_id)
        if fresh is None or not services.claim_matches(fresh, attempt):
            raise ApprovalMovedError()

    site = post.site
    client = GitHubClient(token, site.repo)
    content = services.post_content(post)
    try:
        result = commit_post(client, post, content, guard=guard, message=_commit_message(post))
    except ApprovalMovedError:
        services.stop_stale_publish(post, reason="The post changed after it was approved; nothing was published.")
        return
    except (GitHubError, IndexStructureError, PostPathTakenError, ValueError) as exc:
        services.fail_publish(post, str(exc), attempt=attempt)
        return
    except Exception:
        logger.exception("Unexpected error publishing blog post %s", post_id)
        services.fail_publish(
            post, "Something unexpected went wrong while writing to GitHub. Nothing was deployed.", attempt=attempt
        )
        return

    with transaction.atomic():
        BlogPost.objects.filter(pk=post.pk, status=Status.PUBLISHING, publish_attempts=attempt).update(
            commit_sha=result.sha, published_card=content.card().to_dict(), updated_at=timezone.now()
        )
        post.refresh_from_db()
        if result.changed_paths:
            detail = f"{site.repo}@{result.sha[:7]}: " + ", ".join(result.changed_paths)
        else:
            detail = f"{site.repo} already had this revision at {result.sha[:7]}; nothing to commit."
        services.record_event(post, Action.COMMITTED, detail=detail, fingerprint_value=post.approved_fingerprint)

    # Stamped before the call: the run GitHub creates for it is never older.
    dispatched_at = timezone.now()
    try:
        run_info = client.dispatch_workflow(site.workflow_file, site.branch)
    except GitHubError as exc:
        services.fail_publish(
            post,
            f"The post is committed ({result.sha[:7]}) but the {site.workflow_file} workflow couldn't be started: "
            f"{exc} Its next run will deploy the post; or retry to deploy now.",
            action=Action.DEPLOY_FAILED,
            attempt=attempt,
        )
        return

    updates = {"dispatched_at": dispatched_at, "deploy_status": "queued", "updated_at": timezone.now()}
    if run_info.get("workflow_run_id"):
        updates["deploy_run_id"] = int(run_info["workflow_run_id"])
        updates["deploy_run_url"] = run_info.get("html_url") or ""
    BlogPost.objects.filter(pk=post.pk, status=Status.PUBLISHING, publish_attempts=attempt).update(**updates)

    from .tasks import poll_blog_deploy

    poll_blog_deploy(str(post.pk), attempt, schedule=POLL_INTERVAL_SECONDS)


# Allowance for clock skew between this server and GitHub.
RUN_CLOCK_SKEW = dt.timedelta(seconds=10)


def _find_run(client: GitHubClient, post: BlogPost) -> dict | None:
    """The workflow_dispatch run our dispatch created.

    Only runs created after the dispatch count — a retry of an unchanged post
    dispatches on the same commit as the previous, finished run. Among those,
    the earliest one on our commit wins, else the earliest one at all (the
    branch can move between our commit and the dispatch).
    """
    runs = client.dispatch_runs(post.site.workflow_file, post.site.branch)

    def created(run):
        return parse_datetime(run.get("created_at") or "") or dt.datetime.min.replace(tzinfo=dt.UTC)

    recent = [run for run in runs if created(run) >= post.dispatched_at - RUN_CLOCK_SKEW]
    ours = [run for run in recent if run.get("head_sha") == post.commit_sha]
    candidates = ours or recent
    return min(candidates, key=created) if candidates else None


def _title_is_live(url: str, title: str, sha: str) -> tuple[bool, str]:
    try:
        response = requests.get(
            url,
            params={"v": sha[:7]},
            headers={"User-Agent": "SM-Manager-Blog-Publisher", "Cache-Control": "no-cache"},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        return False, f"couldn't be fetched ({exc.__class__.__name__})"
    if response.status_code != 200:
        return False, f"answered HTTP {response.status_code}"
    body = response.text
    if html.escape(title, quote=False) in body or title in body:
        return True, ""
    return False, "loaded but doesn't show the post's title yet"


def run_poll(post_id, attempt: int, verify_tries: int = 0) -> None:
    """Follow the deploy run, then verify the live page. Never raises."""
    from .tasks import poll_blog_deploy

    post = _load(post_id)
    if post is None or post.status != Status.PUBLISHING or post.publish_attempts != attempt or not post.dispatched_at:
        return
    site = post.site
    deadline_passed = timezone.now() > post.dispatched_at + DEPLOY_DEADLINE

    def again(tries=verify_tries):
        if deadline_passed:
            where = f" See {post.deploy_run_url}." if post.deploy_run_url else ""
            services.fail_publish(
                post,
                f"The deploy didn't finish within {int(DEPLOY_DEADLINE.total_seconds() // 60)} minutes.{where} "
                f"The post is committed ({post.commit_sha[:7]}); retry once the workflow is healthy.",
                action=Action.DEPLOY_FAILED,
                attempt=attempt,
            )
            return
        poll_blog_deploy(str(post.pk), attempt, tries, schedule=POLL_INTERVAL_SECONDS)

    token = services.github_token()
    if not token:
        again()
        return
    client = GitHubClient(token, site.repo)
    try:
        run = client.get_run(post.deploy_run_id) if post.deploy_run_id else _find_run(client, post)
    except GitHubError as exc:
        logger.warning("Polling deploy for blog post %s failed: %s", post.pk, exc)
        again()
        return
    if run is None:
        again()
        return

    run_status = run.get("status") or ""
    conclusion = run.get("conclusion") or ""
    BlogPost.objects.filter(pk=post.pk, status=Status.PUBLISHING, publish_attempts=attempt).update(
        deploy_run_id=run.get("id"),
        deploy_run_url=run.get("html_url") or "",
        deploy_status=conclusion or run_status,
        updated_at=timezone.now(),
    )
    post.refresh_from_db()
    if run_status != "completed":
        again()
        return
    if conclusion != "success":
        services.fail_publish(
            post,
            f"The {site.workflow_file} run finished with “{conclusion or 'no result'}”. See {post.deploy_run_url} "
            "for the log. The post is committed, so a retry redeploys the same revision.",
            action=Action.DEPLOY_FAILED,
            attempt=attempt,
        )
        return

    if verify_tries == 0:
        services.record_event(
            post, Action.DEPLOY_SUCCEEDED, detail=post.deploy_run_url, fingerprint_value=post.approved_fingerprint
        )
    url = site.live_url_for(post.slug)
    live, problem = _title_is_live(url, post.title, post.commit_sha)
    if not live:
        if verify_tries + 1 < VERIFY_RETRIES and not deadline_passed:
            poll_blog_deploy(str(post.pk), attempt, verify_tries + 1, schedule=POLL_INTERVAL_SECONDS)
            return
        services.fail_publish(
            post,
            f"The deploy succeeded but {url} {problem}. Check the site and the run at {post.deploy_run_url}.",
            action=Action.PUBLISH_FAILED,
            attempt=attempt,
        )
        return

    now = timezone.now()
    with transaction.atomic():
        updated = BlogPost.objects.filter(pk=post.pk, status=Status.PUBLISHING, publish_attempts=attempt).update(
            status=Status.PUBLISHED,
            published_url=url,
            published_at=post.published_at or now,
            deploy_status="success",
            last_error="",
            updated_at=now,
        )
        if not updated:
            return
        post.refresh_from_db()
        services.record_event(post, Action.VERIFIED, detail=url, fingerprint_value=post.approved_fingerprint)
    services._notify(
        [post.author, post.approved_by],
        "post_published",
        "Blog post is live",
        f'"{post.title}" is live at {url}.',
        post,
    )


def sweep_stuck() -> int:
    """Fail posts whose publish tasks died. Returns how many were settled."""
    cutoff = timezone.now() - STUCK_AFTER
    stuck = BlogPost.objects.filter(status=Status.PUBLISHING, publish_started_at__lt=cutoff)
    settled = 0
    for post in stuck:
        committed = f" Commit {post.commit_sha[:7]} is in {post.site.repo}." if post.commit_sha else ""
        services.fail_publish(
            post,
            f"Publishing stopped without a result (the worker may have restarted).{committed} "
            "Check the deploy run before retrying.",
            attempt=post.publish_attempts,
        )
        settled += 1
    return settled


def commit_link(post: BlogPost) -> str:
    return _commit_url(post.site, post.commit_sha) if post.commit_sha else ""
