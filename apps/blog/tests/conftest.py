import base64
import io
import json
from dataclasses import dataclass

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.approvals.actor import acting_as
from apps.blog import services
from apps.blog.models import BlogSite
from apps.blog.publisher import git_blob_sha
from apps.media_library.models import MediaAsset
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace

NEOPOLIS_REPO = "hemantsatishjadhav06-ai/neopolis-site-deploy"
MORESPACE_REPO = "hemantsatishjadhav06-ai/morespace-website"


@dataclass
class World:
    org: Organization
    workspace: Workspace
    owner: User
    editor: User
    client: User
    viewer: User
    outsider: User
    neopolis: BlogSite
    morespace: BlogSite


def _user(email, name):
    return User.objects.create_user(email=email, password="pw-12345678", name=name, tos_accepted_at=timezone.now())


@pytest.fixture
def world(db):
    org = Organization.objects.create(name="Brands")
    ws = Workspace.objects.create(organization=org, name="Neopolis")
    users = {}
    for role in ("owner", "editor", "client", "viewer"):
        user = _user(f"{role}@example.com", role.title())
        OrgMembership.objects.create(user=user, organization=org, org_role="owner" if role == "owner" else "member")
        WorkspaceMembership.objects.create(user=user, workspace=ws, workspace_role=role)
        users[role] = user
    outsider = _user("outsider@example.com", "Outsider")
    neopolis = BlogSite.objects.create(
        workspace=ws,
        name="Neopolis Infra website",
        kind=BlogSite.Kind.NEOPOLIS_STATIC,
        site_url="https://www.neopolisinfra.com",
        repo=NEOPOLIS_REPO,
        workflow_file="publish3.yml",
        netlify_site_id="47e0a5cc-d9d9-428b-a36b-beea806bff6f",
    )
    morespace = BlogSite.objects.create(
        workspace=ws,
        name="More Space website",
        kind=BlogSite.Kind.MORESPACE_STATIC,
        site_url="https://morespace.netlify.app",
        repo=MORESPACE_REPO,
        workflow_file="netlify-publish.yml",
        netlify_site_id="964e086b-1cf2-47f7-8b78-16909d268319",
    )
    return World(
        org, ws, users["owner"], users["editor"], users["client"], users["viewer"], outsider, neopolis, morespace
    )


def png_bytes(width=2400, height=1200, mode="RGBA"):
    buf = io.BytesIO()
    color = (10, 120, 200, 128) if mode == "RGBA" else (10, 120, 200)
    Image.new(mode, (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def image_asset(world):
    def make(data=None, filename="hero.png"):
        data = data if data is not None else png_bytes()
        asset = MediaAsset.objects.create(
            organization=world.org,
            workspace=world.workspace,
            uploaded_by=world.owner,
            filename=filename,
            media_type=MediaAsset.MediaType.IMAGE,
            file_size=len(data),
        )
        asset.file.save(filename, ContentFile(data), save=True)
        return asset

    return make


def make_post(world, site=None, author=None, **overrides):
    fields = {
        "title": "Flats in Kokapet 2026",
        "slug": "flats-in-kokapet-2026",
        "excerpt": "Prices, projects and the landlord-share saving.",
        "body": "## Why Kokapet\n\nIt is **booming**.\n\n- Close to the Financial District\n- New towers",
        "category": "Area Guide",
        "faq": [{"q": "Is Kokapet a good investment?", "a": "For most buyers, yes."}],
        # The plain hero keeps these fixtures about the publishing flow itself;
        # the designed cover has its own tests (test_covers.py).
        "cover_style": "plain",
    }
    fields.update(overrides)
    return services.create_post(
        workspace=world.workspace, site=site or world.neopolis, author=author or world.editor, **fields
    )


def approved_post(world, **overrides):
    post = make_post(world, **overrides)
    services.submit_for_review(post, world.editor)
    with acting_as(world.owner):
        return services.approve(post)


# ---------------------------------------------------------------------------
# A fake GitHub REST API good enough for the Git Data + Actions calls we make.
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code, payload=None, text=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        if text is not None:
            self.text = text
        else:
            self.text = "" if payload is None else json.dumps(payload)
        self.content = self.text.encode()

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload


class FakeGitHub:
    """Routes ``session.request`` calls for one repository."""

    def __init__(self, repo, files=None, *, branch="main"):
        self.repo = repo
        self.branch = branch
        self.files = {
            path: (data if isinstance(data, bytes) else data.encode()) for path, data in (files or {}).items()
        }
        self.head = "a" * 40
        self.calls = []
        self.blobs = {}
        self.trees = {}
        self.commits = {}
        self.runs = []
        self.dispatches = []
        self.move_ref_times = 0  # make update_ref fail with 422 this many times
        self.dispatch_status = 204
        self._counter = 0

    def _next(self, prefix):
        self._counter += 1
        return f"{prefix}{self._counter:0>38}"[:40]

    def request(self, method, url, headers=None, timeout=None, params=None, json=None, **kwargs):
        prefix = f"https://api.github.com/repos/{self.repo}"
        assert url.startswith(prefix), url
        assert headers["Authorization"].startswith("Bearer ")
        path = url[len(prefix) :]
        self.calls.append((method, path))

        if method == "GET" and path == f"/git/ref/heads/{self.branch}":
            return FakeResponse(200, {"object": {"sha": self.head}})
        if method == "GET" and path.startswith("/git/commits/"):
            return FakeResponse(200, {"sha": path.rsplit("/", 1)[1], "tree": {"sha": "t" + path.rsplit("/", 1)[1][1:]}})
        if method == "GET" and path.startswith("/contents/"):
            file_path = path[len("/contents/") :]
            if file_path not in self.files:
                return FakeResponse(404, {"message": "Not Found"})
            data = self.files[file_path]
            return FakeResponse(
                200,
                {
                    "type": "file",
                    "path": file_path,
                    "sha": git_blob_sha(data),
                    "encoding": "base64",
                    "content": base64.encodebytes(data).decode(),
                },
            )
        if method == "POST" and path == "/git/blobs":
            data = base64.b64decode(json["content"])
            sha = git_blob_sha(data)
            self.blobs[sha] = data
            return FakeResponse(201, {"sha": sha})
        if method == "POST" and path == "/git/trees":
            sha = self._next("t")
            self.trees[sha] = json
            return FakeResponse(201, {"sha": sha})
        if method == "POST" and path == "/git/commits":
            sha = self._next("c")
            self.commits[sha] = json
            return FakeResponse(201, {"sha": sha})
        if method == "PATCH" and path == f"/git/refs/heads/{self.branch}":
            if self.move_ref_times:
                self.move_ref_times -= 1
                self.head = self._next("m")
                return FakeResponse(422, {"message": "Update is not a fast forward"})
            commit = self.commits[json["sha"]]
            assert commit["parents"] == [self.head]
            for entry in self.trees[commit["tree"]]["tree"]:
                self.files[entry["path"]] = self.blobs[entry["sha"]]
            self.head = json["sha"]
            return FakeResponse(200, {"object": {"sha": self.head}})
        if method == "POST" and path.endswith("/dispatches"):
            self.dispatches.append((path, json))
            if self.dispatch_status != 204:
                return FakeResponse(
                    self.dispatch_status, {"message": "Workflow does not have 'workflow_dispatch' trigger"}
                )
            return FakeResponse(204)
        if method == "GET" and path.endswith("/runs") and "/actions/workflows/" in path:
            return FakeResponse(200, {"total_count": len(self.runs), "workflow_runs": self.runs})
        if method == "GET" and path.startswith("/actions/runs/"):
            run_id = int(path.rsplit("/", 1)[1])
            return FakeResponse(200, next(r for r in self.runs if r["id"] == run_id))
        raise AssertionError(f"Unexpected GitHub call {method} {path}")

    def writes(self):
        return [(m, p) for m, p in self.calls if m in ("POST", "PATCH")]
