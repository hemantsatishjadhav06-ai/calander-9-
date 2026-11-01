"""The URL gate: no URL ``docs/PRODUCT_MAP.md`` lists answers 404 or 500 (spec R9, plan T11).

``tests/fixtures/product_map_urls.txt`` freezes every URL name and path the map listed at the start
of Phase 2, before the map was rewritten, so an old link, bookmark or Telegram card keeps being
tested after its page moved. Signed in as the owner of workspace A (the e2e seed, plus a brief, a
job, a post waiting for approval, an article, a thread, a routine, a Telegram bot and a client's
magic link), each entry is resolved and fetched with GET, and may answer only:

* 200;
* 301 or 302, when the redirect chain ends on a page that answers 200, in workspace A, and not on the
  sign-in page (nor on the portal's, except for an entry marked ``portal``);
* 403 or 405 where the fixture marks it as by design (405 only where the view takes POST only).

The sweep runs with every feature switch off and with every one on: a switch hides navigation and
creation, never a page (decision D6). A failure lists every offending entry at once.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from django.conf import settings
from django.shortcuts import resolve_url
from django.test import Client
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

REPOSITORY = Path(__file__).resolve().parent.parent
FIXTURE = REPOSITORY / "tests" / "fixtures" / "product_map_urls.txt"
PRODUCT_MAP = REPOSITORY / "docs" / "PRODUCT_MAP.md"
CODE_MAP = REPOSITORY / "docs" / "specs" / "phase-2-code-map.md"

#: What an entry may get instead of 200 (a redirect to a working page is always accepted).
MARKS = frozenset({"403", "405", "portal", "skip"})
#: ``W`` at the start of a path stands for the prefix every workspace page sits under.
WORKSPACE_PREFIX = "/workspace/<workspace id>"
REDIRECTS = (301, 302)
MAX_HOPS = 5
WORKSPACE_A = "00000000-0000-4000-8000-00000000000a"  # the e2e seed's (tests/e2e/server/seed.py)
WORKSPACE_B = "00000000-0000-4000-8000-00000000000b"

_COMMENT = re.compile(r"(?:^|\s)#")
_PIECE = re.compile(r"(?:<[^>]*>|[^\s<])+")
_KWARG = re.compile(r"(?P<kwarg>\w+)=<(?P<object>[^>]+)>")
_PLACEHOLDER = re.compile(r"<(?P<object>[^>]+)>")
_BACKTICKED = re.compile(r"`([^`\n]+)`")
_URL_NAME = re.compile(r"[a-z_]+:[a-z_]+(?:\?\S*)?")


class FixtureError(ValueError):
    """A line of the fixture this test cannot read."""


@dataclass(frozen=True)
class Entry:
    """One line of the fixture: a URL name (with its kwargs) or a path, its marks and its comment."""

    line: int
    text: str
    kwargs: tuple[tuple[str, str], ...]
    marks: frozenset[str]
    comment: str

    @property
    def is_path(self) -> bool:
        return self.text.startswith(("/", "W/"))

    @property
    def covers(self) -> str:
        """The token of ``PRODUCT_MAP.md`` this entry stands for (a ``W`` path is written there without it)."""
        return self.text[1:] if self.text.startswith("W/") else self.text

    def __str__(self) -> str:
        kwargs = "".join(f" {kwarg}=<{name}>" for kwarg, name in self.kwargs)
        return f"line {self.line}: {self.text}{kwargs}"


def parse_fixture(text: str) -> list[Entry]:
    """The entries of the fixture, in order; a line it cannot read raises ``FixtureError``."""
    entries = []
    for number, raw in enumerate(text.splitlines(), start=1):
        hash_mark = _COMMENT.search(raw)
        body, comment = (raw[: hash_mark.start()], raw[hash_mark.end() :]) if hash_mark else (raw, "")
        pieces = _PIECE.findall(body)
        if not pieces:
            continue
        first, rest = pieces[0], pieces[1:]
        if not first.startswith(("/", "W/")) and not _URL_NAME.fullmatch(first):
            raise FixtureError(f"line {number}: {first!r} is neither a URL name nor a path")
        kwargs: list[tuple[str, str]] = []
        marks: set[str] = set()
        for piece in rest:
            kwarg = _KWARG.fullmatch(piece)
            if kwarg is not None and not first.startswith(("/", "W/")):
                kwargs.append((kwarg["kwarg"], kwarg["object"].strip()))
            elif piece in MARKS:
                marks.add(piece)
            else:
                raise FixtureError(f"line {number}: {piece!r} is neither a kwarg=<object> nor one of {sorted(MARKS)}")
        entries.append(Entry(number, first, tuple(kwargs), frozenset(marks), comment.strip()))
    return entries


def load_entries() -> list[Entry]:
    return parse_fixture(FIXTURE.read_text(encoding="utf-8"))


def map_tokens(text: str) -> set[str]:
    """Every URL name (``app:name``, with its query) and every path (``/…``) written in backticks."""
    found = set()
    for match in _BACKTICKED.finditer(text):
        token = match.group(1).strip()
        if token.startswith("/") or _URL_NAME.fullmatch(token):
            found.add(token)
    return found


def code_map_table_rows(text: str) -> int:
    """How many rows the code map's table of the map's URLs has (AREA productmap, section 1)."""
    start = text.index("## 1. Every URL in `docs/PRODUCT_MAP.md`")
    end = text.index("**Pages the map names only in prose", start)
    return sum(1 for line in text[start:end].splitlines() if re.match(r"\| \d", line))


def _object_key(placeholder: str) -> str:
    """``<brief id>``, ``<brief_id>`` and ``<brief>`` all name the brief."""
    return re.sub(r"[ _]id$", "", placeholder.strip().lower())


def url_for(entry: Entry, objects: Mapping[str, str]) -> str:
    """The path to fetch for ``entry``, with ``objects`` (by key: workspace, brief, …) filled in.

    A URL name is reversed with ``workspace_id`` when its pattern takes one, and must resolve back to
    itself. Raises ``KeyError`` for an object the test does not make and ``NoReverseMatch`` for a name
    or kwargs that do not reverse.
    """
    if entry.is_path:
        path = entry.text.replace("…", "")
        if path.startswith("W/"):
            path = WORKSPACE_PREFIX + path[1:]
        return _PLACEHOLDER.sub(lambda match: objects[_object_key(match["object"])], path)
    name, _mark, query = entry.text.partition("?")
    kwargs = {kwarg: objects[_object_key(key)] for kwarg, key in entry.kwargs}
    try:
        path = reverse(name, kwargs={"workspace_id": objects["workspace"], **kwargs})
    except NoReverseMatch:
        path = reverse(name, kwargs=kwargs)
    resolved = resolve(path).view_name
    if resolved != name:
        raise NoReverseMatch(f"{name} reverses to {path}, which resolves to {resolved}")
    return f"{path}?{query}" if query else path


@dataclass(frozen=True)
class Hop:
    """One response on the way: where it was asked, what it answered, where it pointed."""

    path: str
    status: int
    location: str = ""

    def __str__(self) -> str:
        return f"{self.path} {self.status}"


def fetch(client: Client, path: str) -> list[Hop]:
    """GET ``path`` and follow 301/302 inside the site, at most ``MAX_HOPS`` times and never in a loop."""
    chain: list[Hop] = []
    seen = {path}
    while True:
        response = client.get(path)
        location = response.get("Location", "") if response.status_code in REDIRECTS else ""
        chain.append(Hop(path, response.status_code, location))
        if not location or len(chain) > MAX_HOPS:
            return chain
        target = urlsplit(location)
        if target.netloc and target.netloc != "testserver":
            return chain
        path = target.path + (f"?{target.query}" if target.query else "")
        if path in seen:
            return chain
        seen.add(path)


def judge(entry: Entry, chain: Sequence[Hop], *, workspace_id: str) -> str | None:
    """Why ``chain`` is not an accepted answer for ``entry``, or ``None`` when it is."""
    first, last = chain[0], chain[-1]
    trail = " -> ".join(str(hop) for hop in chain)
    if first.status not in REDIRECTS:
        if first.status == 200:
            return None
        if first.status in (403, 405) and str(first.status) in entry.marks:
            return None
        return f"answered {first.status}"
    if last.status in REDIRECTS:
        if not last.location:
            return f"redirects without a Location: {trail}"
        if urlsplit(last.location).netloc not in ("", "testserver"):
            return f"redirects outside the site, to {last.location}: {trail}"
        return f"redirects in a loop or more than {MAX_HOPS} times: {trail}"
    landed = urlsplit(last.path).path
    if landed == resolve_url(settings.LOGIN_URL):
        return f"sends a signed-in owner to the sign-in page: {trail}"
    if landed == reverse("client_portal:magic_link_expired") and "portal" not in entry.marks:
        return f"sends the owner to the portal's sign-in page: {trail}"
    if last.status != 200:
        return f"redirects to a page that answers {last.status}: {trail}"
    try:
        elsewhere = resolve(landed).kwargs.get("workspace_id")
    except Resolver404:
        elsewhere = None
    if elsewhere is not None and str(elsewhere) != workspace_id:
        return f"redirects into another workspace: {trail}"
    return None


def sweep(client: Client, entries: Iterable[Entry], objects: Mapping[str, str]) -> list[str]:
    """Fetch every entry that is not ``skip`` and return one line per entry that answered wrongly."""
    from tests.e2e.server.steps.g1 import _methods

    failures = []
    for entry in entries:
        if "skip" in entry.marks:
            continue
        try:
            path = url_for(entry, objects)
        except (KeyError, NoReverseMatch, Resolver404) as exc:
            failures.append(f"{entry}: cannot be built ({type(exc).__name__}: {exc})")
            continue
        chain = fetch(client, path)
        problem = judge(entry, chain, workspace_id=objects["workspace"])
        if problem is None and chain[0].status == 405:
            methods = _methods(resolve(urlsplit(path).path).func)
            if methods is None or "GET" in methods:
                problem = f"answered 405, but its view does not refuse GET by design (it takes {methods or 'any'})"
        if problem is None and chain[0].status != 200 and not entry.comment:
            problem = f"answered {chain[0].status}; say why in a comment on its line"
        if problem is not None:
            failures.append(f"{entry} ({path}): {problem}")
    return failures


# ---------------------------------------------------------------------------
# The fixture against the map
# ---------------------------------------------------------------------------


def test_the_fixture_is_not_empty_and_has_a_line_for_every_row_of_the_code_maps_url_table():
    entries = load_entries()

    assert entries, f"{FIXTURE} lists no URL"
    rows = code_map_table_rows(CODE_MAP.read_text(encoding="utf-8"))
    assert rows >= 40, "the code map's URL table was not found where it was"
    assert len(entries) >= rows, f"{len(entries)} entries for the {rows} rows of the code map's URL table"


def test_the_fixture_lists_every_url_name_and_path_in_the_product_map():
    """A URL the map names and the fixture does not is a URL the gate does not test."""
    covered = {entry.covers for entry in load_entries()}

    missing = sorted(map_tokens(PRODUCT_MAP.read_text(encoding="utf-8")) - covered)

    assert not missing, f"docs/PRODUCT_MAP.md lists URLs {FIXTURE.name} does not: " + ", ".join(missing)


def test_the_map_names_the_screens_phase_2_added():
    """Docs (spec R10): the map names Approvals, Settings with each of its tabs, Activity and the public
    site's Request invite, so the test above makes the gate fetch them too. A Settings tab added to
    ``views_settings.TABS`` fails here until the map, and then the fixture, list it."""
    from apps.studio.views_settings import TABS

    wanted = {
        "approvals:index",
        "/approvals/",
        "settings:index",
        "/settings/",
        *(f"/settings/?tab={tab.key}" for tab in TABS),
        "/studio/activity/",
        "marketing:request_invite",
        "/request-invite/",
        "/pricing/",
    }

    missing = sorted(wanted - map_tokens(PRODUCT_MAP.read_text(encoding="utf-8")))

    assert not missing, "docs/PRODUCT_MAP.md does not name " + ", ".join(missing)


def test_every_mark_comes_with_its_reason():
    for entry in load_entries():
        assert len(entry.marks) <= 1, entry
        if entry.marks:
            assert entry.comment, f"{entry} is marked {sorted(entry.marks)} without saying why"


def test_what_is_skipped_is_not_a_url():
    """``skip`` is for the map's notation and Telegram commands only, never for a page that fails."""
    objects = {"workspace": WORKSPACE_A}
    skipped = [entry for entry in load_entries() if "skip" in entry.marks]

    assert {entry.covers for entry in skipped} == {"/workspace/<workspace id>/", "app:name", "/routines", "/mute"}
    for entry in skipped:
        with pytest.raises((NoReverseMatch, Resolver404)):
            resolve(urlsplit(url_for(entry, objects)).path)


def _entry(text: str, *marks: str) -> Entry:
    return Entry(1, text, (), frozenset(marks), "why" if marks else "")


@pytest.mark.parametrize(
    ("entry", "chain", "problem"),
    [
        (_entry("studio:index"), [Hop("/x/", 200)], None),
        (_entry("studio:detail"), [Hop("/x/", 404)], "answered 404"),
        (_entry("studio:detail"), [Hop("/x/", 500)], "answered 500"),
        (_entry("studio:create"), [Hop("/x/", 405)], "answered 405"),
        (_entry("studio:create", "405"), [Hop("/x/", 405)], None),
        (_entry("studio:setup"), [Hop("/x/", 403)], "answered 403"),
        (_entry("studio:setup", "403"), [Hop("/x/", 403)], None),
        (_entry("studio:setup", "405"), [Hop("/x/", 403)], "answered 403"),
        (_entry("studio:routines"), [Hop("/a/", 301, "/b/"), Hop("/b/", 200)], None),
        (_entry("studio:routines"), [Hop("/a/", 302, "/b/"), Hop("/b/", 404)], "redirects to a page that answers 404"),
        (_entry("studio:routines"), [Hop("/a/", 301, "/b/"), Hop("/b/", 500)], "redirects to a page that answers 500"),
        (_entry("studio:routines"), [Hop("/a/", 301, "/b/"), Hop("/b/", 403)], "redirects to a page that answers 403"),
        (_entry("studio:routines"), [Hop("/a/", 302, "/a/")], "redirects in a loop"),
        (_entry("studio:routines"), [Hop("/a/", 302, "https://elsewhere.test/")], "redirects outside the site"),
        (_entry("studio:index"), [Hop("/a/", 302, "/accounts/login/"), Hop("/accounts/login/", 200)], "sign-in page"),
        (
            _entry("client_portal:team"),
            [Hop("/portal/team/", 302, "/portal/expired/"), Hop("/portal/expired/?reason=signed_out", 200)],
            "the portal's sign-in page",
        ),
        (
            _entry("client_portal:team", "portal"),
            [Hop("/portal/team/", 302, "/portal/expired/"), Hop("/portal/expired/?reason=signed_out", 200)],
            None,
        ),
        (
            _entry("studio:index"),
            [Hop("/a/", 302, "/b/"), Hop(f"/workspace/{WORKSPACE_B}/studio/", 200)],
            "another workspace",
        ),
        (_entry("studio:index"), [Hop("/a/", 302, "/b/"), Hop(f"/workspace/{WORKSPACE_A}/studio/", 200)], None),
    ],
)
def test_judge_accepts_only_200_a_working_redirect_or_a_documented_refusal(entry, chain, problem):
    """The checker on fake answers: a 404 or a 500, directly or at the end of a redirect, is caught."""
    verdict = judge(entry, chain, workspace_id=WORKSPACE_A)

    if problem is None:
        assert verdict is None
    else:
        assert verdict is not None and problem in verdict, verdict


def test_the_fixture_reader_refuses_what_it_cannot_read():
    with pytest.raises(FixtureError, match="neither a URL name nor a path"):
        parse_fixture("studio index")
    with pytest.raises(FixtureError, match="neither a kwarg"):
        parse_fixture("studio:detail 404")
    entries = parse_fixture("W/studio/<brief id>/  # a post\nstudio:job job_id=<job> 405  # why\n\n# only a comment")
    assert [(e.text, e.kwargs, e.marks, e.comment) for e in entries] == [
        ("W/studio/<brief id>/", (), frozenset(), "a post"),
        ("studio:job", (("job_id", "job"),), frozenset({"405"}), "why"),
    ]
    assert entries[0].covers == "/studio/<brief id>/"


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class World:
    owner: Any
    workspace: Any
    objects: dict[str, str]


@pytest.fixture
def world(db) -> World:
    """The e2e seed's workspace A, with one row of each kind a URL in the fixture needs or lists."""
    from django.utils import timezone

    from apps.accounts.models import User
    from apps.blog.models import BlogPost, BlogSite
    from apps.client_portal.services import generate_magic_link
    from apps.composer.models import PlatformPost, Post
    from apps.inbox.models import InboxMessage
    from apps.social_accounts.models import SocialAccount
    from apps.studio.models import AgencyJob, Conversation, Routine, StudioBrief
    from apps.telegram.models import TelegramConnection
    from apps.workspaces.models import Workspace
    from tests.e2e.server import seed

    seed.run()
    workspace = Workspace.objects.get(pk=seed.WORKSPACE_A_ID)
    owner = User.objects.get(email=seed.USERS["owner"][0])
    client = User.objects.get(email=seed.USERS["client"][0])
    account = SocialAccount.objects.filter(workspace=workspace).order_by("platform")[0]
    now = timezone.now()

    post = Post.objects.create(workspace=workspace, author=owner, title="Open day", caption="Open day on Saturday")
    PlatformPost.objects.create(post=post, social_account=account, status=PlatformPost.Status.PENDING_REVIEW)
    brief = StudioBrief.objects.create(
        workspace=workspace, author=owner, idea="Open day", status=StudioBrief.Status.READY, post=post
    )
    job = AgencyJob.objects.create(
        workspace=workspace,
        kind=AgencyJob.Kind.REPORT,
        title="Weekly report",
        status=AgencyJob.Status.DONE,
        requested_by=owner,
        finished_at=now,
    )
    conversation = Conversation.objects.create(workspace=workspace, title="Open day", created_by=owner)
    Routine.objects.create(
        workspace=workspace, created_by=owner, title="Monday plan", instruction="Plan the week", enabled=False
    )
    site = BlogSite.objects.create(
        workspace=workspace,
        name="Neopolis website",
        kind=BlogSite.Kind.NEOPOLIS_STATIC,
        site_url="https://neopolis.e2e.test",
        repo="neopolis/site",
        workflow_file="deploy.yml",
    )
    BlogPost.objects.create(
        workspace=workspace, site=site, author=owner, title="Buying a first home", slug="first-home"
    )
    InboxMessage.objects.create(
        workspace=workspace,
        social_account=account,
        platform_message_id="gate-comment-1",
        sender_name="A customer",
        body="Is parking free on Saturday?",
        received_at=now,
    )
    connection = TelegramConnection.objects.create(
        workspace=workspace,
        token="123456:" + "f" * 32,
        webhook_secret="gate-shared-secret",
        bot_id=123456,
        bot_username="gate_test_bot",
        is_active=True,
        created_by=owner,
    )
    link = generate_magic_link(workspace, client, owner)
    objects = {
        "workspace": str(workspace.pk),
        "brief": str(brief.pk),
        "job": str(job.pk),
        "conversation": str(conversation.pk),
        "token": link.token,
        "connection": str(connection.pk),
    }
    return World(owner=owner, workspace=workspace, objects=objects)


def _switch_everything(workspace: Any, on: bool) -> None:
    from apps.common.features import FEATURE_KEYS, features_for
    from apps.studio.models import AgencySettings

    AgencySettings.objects.filter(workspace=workspace).update(features=dict.fromkeys(FEATURE_KEYS, on))
    assert set(features_for(workspace).values()) == {on}


@pytest.mark.django_db
@pytest.mark.parametrize("switches_on", [False, True], ids=["switches-off", "switches-on"])
def test_every_url_in_the_map_answers_the_owner(world, switches_on):
    _switch_everything(world.workspace, switches_on)
    client = Client(raise_request_exception=False)
    client.force_login(world.owner)

    failures = sweep(client, load_entries(), world.objects)

    assert not failures, "URLs from docs/PRODUCT_MAP.md that answer wrongly:\n" + "\n".join(failures)


@pytest.mark.django_db
def test_portal_entries_answer_a_client_signed_in_through_the_magic_link(world):
    """What the owner is sent away from, the client the map means sees: each ``portal`` entry is 200."""
    client = Client(raise_request_exception=False)
    link = reverse("client_portal:magic_link_entry", kwargs={"token": world.objects["token"]})
    assert client.get(link).status_code == 200
    assert client.post(link)["Location"] == reverse("client_portal:dashboard")
    portal = [entry for entry in load_entries() if "portal" in entry.marks]

    answers = {str(item): fetch(client, url_for(item, world.objects)) for item in portal}

    assert len(portal) >= 8
    wrong = {
        item: [str(hop) for hop in chain] for item, chain in answers.items() if len(chain) > 1 or chain[0].status != 200
    }
    assert not wrong, wrong
