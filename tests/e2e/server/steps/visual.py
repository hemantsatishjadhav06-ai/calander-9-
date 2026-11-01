"""Steps for the visual specs (``tests/e2e/visual/``) and the harness's own check of them
(``tests/e2e/self/visual-harness.spec.ts``); docs/specs/03-rebuild-screens.md D9, plan T10.

A baseline is a photograph compared pixel by pixel, so what a page shows must not move with the real
date, with the worker or with what other specs leave behind.

Fixtures:

- ``visual_workspace`` (``{}``): the visual workspace, put back exactly as it was made, every call.
  Its own organisation "Visual Agency" (Asia/Kolkata) and workspace "Riverside Homes" at the fixed id
  ``…c1``; the owner ``visual-owner@e2e.test`` (the lead) and the editor ``visual-editor@e2e.test``,
  who land there and nowhere else; connected Instagram, LinkedIn company and Facebook accounts with
  their queues; the brand profile; the agency settings (autopilot off, the brief shown first); four
  posts proposed at fixed times in the week of Mon 4 Jan 2027 (``?date=2027-01-04``), two waiting
  for review and two drafts; three briefs (ready, approved, stopped); and the team thread, a
  question and the manager's answer. Every id is fixed and every time is the fixture's own, all
  before :data:`INSTANT`. Each call deletes the organisation (and with it everything above) and the
  two people's notifications, then makes them again, so it answers the same ids and the same rows
  whatever a spec did in between; it never touches the seeded A or B.

  What Home shows of it depends on nothing but the rows: no brief carries a proposed time (Approve &
  schedule would come and go with the clock), nothing finished within a day of the instant ("done
  since yesterday"), and no post falls in the 24 hours after it (the live card's "Next"). So the
  self spec can move the clock 90 days on and expect the same picture. A screen that adds rows here
  keeps to that, or says which of its states depend on the instant.

- ``visual_clock`` (``{"at": "2027-01-03T09:00:00+05:30"}`` sets, ``{}`` clears): freezes the server's
  clock (``clock.py``: ``django.utils.timezone.now`` and every copy of it), so request threads and
  the worker read the same instant. While it is frozen the worker is held between tasks
  (``worker.hold``): a clock moved months away from the real one would make every row of every
  other spec fall due at once (posts would publish, reminders fire, the recurring schedule would be
  pushed past the real date). The three check-ins Home's health reads (``task_health``) are stamped
  at the instant, so the team reads as online on any real date; clearing puts them back as they
  were, thaws the clock and lets the worker go on. Set it before the first page and before
  ``visual_workspace`` (the fixture's rows are then made while nothing else runs), and clear it after
  each test. Answers ``{"frozen", "now"}``; ``at`` needs its UTC offset.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .. import clock, seed, worker
from ..registry import PayloadError, fixture

TIMEZONE = "Asia/Kolkata"
_ZONE = ZoneInfo(TIMEZONE)
#: Where the visual specs freeze the clock: Sun 3 Jan 2027 09:00 in the workspace's time zone, the
#: day before the fixture's week, so nothing in it is due.
INSTANT = "2027-01-03T09:00:00+05:30"
#: The Monday of the fixture's week (the calendar's ``?date=``).
WEEK = "2027-01-04"

ORGANISATION_NAME = "Visual Agency"
WORKSPACE_NAME = "Riverside Homes"


def _id(suffix: str) -> uuid.UUID:
    return uuid.UUID(f"00000000-0000-4000-8000-{suffix:0>12}")


ORGANISATION_ID = _id("c0")
WORKSPACE_ID = _id("c1")

#: key -> (id, email, name, workspace role, organisation role)
PEOPLE: dict[str, tuple[uuid.UUID, str, str, str, str]] = {
    "owner": (_id("c2"), "visual-owner@e2e.test", "Vera Owner", "owner", "owner"),
    "editor": (_id("c3"), "visual-editor@e2e.test", "Viktor Editor", "editor", "member"),
}

#: platform -> (id, account name, handle, platform id)
ACCOUNTS: dict[str, tuple[uuid.UUID, str, str, str]] = {
    "instagram": (_id("c4"), "riversidehomes", "riversidehomes", "visual-ig-17841400000001"),
    "linkedin_company": (_id("c5"), "Riverside Homes", "", "visual-li-org-10001"),
    "facebook": (_id("c6"), "Riverside Homes Page", "", "visual-fb-page-10001"),
}


def _at(day: int, hour: int, minute: int = 0, *, month: int = 1, year: int = 2027) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=_ZONE)


#: When the workspace was set up and its people accepted the terms (fixed, like every time here).
SET_UP = _at(1, 9, 0, month=12, year=2026)

#: The posts: id, the caption, the proposed time (in the week), its channels and their status, and
#: when it was written. The earliest is more than a day after the instant.
POSTS: tuple[dict[str, Any], ...] = (
    {
        "id": _id("d1"),
        "caption": "Open house this Saturday at Riverside: walk through the three-bedroom show home, 10:00 to 17:00.",
        "at": _at(4, 10, 30),
        "channels": (("instagram", "pending_review", _id("d101")),),
        "written": _at(2, 17, 10),
    },
    {
        "id": _id("d2"),
        "caption": "Riverside's second tower reached its top floor this week. Thank you to the 140 people building it.",
        "at": _at(5, 18, 0),
        "channels": (("linkedin_company", "pending_review", _id("d201")),),
        "written": _at(2, 16, 40),
    },
    {
        "id": _id("d3"),
        "caption": "How far is Riverside from the metro? Eight minutes on foot, and the walk is shaded.",
        "at": _at(7, 12, 0),
        "channels": (("facebook", "draft", _id("d301")),),
        "written": _at(31, 11, 5, month=12, year=2026),
    },
    {
        "id": _id("d4"),
        "caption": "Saturday's open house in pictures: the courtyard, the kitchens and the view from the 12th floor.",
        "at": _at(9, 9, 30),
        "channels": (("instagram", "draft", _id("d401")), ("facebook", "draft", _id("d402"))),
        "written": _at(31, 15, 20, month=12, year=2026),
    },
)

#: The briefs: id, idea, status, stage, channels, created and finished (more than a day before the instant).
BRIEFS: tuple[dict[str, Any], ...] = (
    {
        "id": _id("e1"),
        "idea": "Open house this Saturday: the three-bedroom show home",
        "status": "ready",
        "stage": "done",
        "channels": ("instagram",),
        "created": _at(30, 10, 0, month=12, year=2026),
        "finished": _at(30, 10, 22, month=12, year=2026),
        "error": "",
    },
    {
        "id": _id("e2"),
        "idea": "Floor plans for the corner apartments",
        "status": "approved",
        "stage": "done",
        "channels": ("instagram", "facebook"),
        "created": _at(28, 11, 0, month=12, year=2026),
        "finished": _at(28, 11, 25, month=12, year=2026),
        "error": "",
    },
    {
        "id": _id("e3"),
        "idea": "A year of building Riverside, in numbers",
        "status": "failed",
        "stage": "art",
        "channels": ("linkedin_company",),
        "created": _at(29, 15, 0, month=12, year=2026),
        "finished": None,
        "error": "The art director stopped: the picture needs a person's choice.",
    },
)

CONVERSATION_ID = _id("f1")
#: The team thread: id, author ("owner" or the manager), body, time.
MESSAGES: tuple[tuple[uuid.UUID, str, str, datetime], ...] = (
    (_id("f2"), "owner", "Can we tell people about the open house this Saturday?", _at(2, 17, 40)),
    (
        _id("f3"),
        "manager",
        "Yes. The draft for Instagram is waiting for you, and nothing is scheduled until you approve it.",
        _at(2, 17, 41),
    ),
)

#: The recurring tasks whose check-ins Home's health reads (``apps.common.background.task_health``).
CHECK_INS = (
    "apps.publisher.tasks.run_publish_cycle",
    "apps.studio.tasks.run_agency_cycle",
    "apps.publisher.tasks.confirm_pending_publishes",
)
_CHECK_IN_FIELDS = ("last_started_at", "last_success_at", "last_failure_at", "state", "error", "metadata", "updated_at")
#: The check-ins as they were before the clock was frozen: task name -> fields (None: there was no row).
_saved_check_ins: dict[str, dict[str, Any] | None] | None = None


def _iso(value: datetime) -> str:
    return value.astimezone(_ZONE).isoformat()


# ---------------------------------------------------------------------------
# visual_workspace
# ---------------------------------------------------------------------------


def _person(key: str) -> Any:
    """One of the two people, at their fixed id, in no workspace yet (``_make`` adds the visual one)."""
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace

    user_id, email, name, _role, _org_role = PEOPLE[key]
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        user = User.objects.create_user(id=user_id, email=email, password=seed.PASSWORD, name=name)
        # Every new user is given an organisation and "My Workspace" (accounts.signals); not these two.
        given = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
        WorkspaceMembership.objects.filter(user=user).delete()
        OrgMembership.objects.filter(user=user).delete()
        Organization.objects.filter(id__in=given).delete()
    else:
        # Whatever a spec gave them since; the seeded A and B are never touched here.
        seeded = (seed.WORKSPACE_A_ID, seed.WORKSPACE_B_ID)
        seeded_orgs = list(Workspace.objects.filter(pk__in=seeded).values_list("organization_id", flat=True))
        WorkspaceMembership.objects.filter(user=user).exclude(workspace_id__in=seeded).delete()
        OrgMembership.objects.filter(user=user).exclude(organization_id__in=seeded_orgs).delete()
    user.email = email
    user.name = name
    user.is_active = True
    user.tos_accepted_at = SET_UP
    user.last_workspace_id = WORKSPACE_ID
    user.save()
    return user


def _clear() -> None:
    from apps.notifications.models import Notification
    from apps.organizations.models import Organization

    Organization.objects.filter(pk=ORGANISATION_ID).delete()
    Notification.objects.filter(user_id__in=[person[0] for person in PEOPLE.values()]).delete()


def _make() -> dict[str, Any]:
    from apps.calendar.services import create_default_queue_and_slots
    from apps.composer.models import PlatformPost, Post
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.studio.brand_defaults import ensure_profile
    from apps.studio.models import AgencySettings, Conversation, Message, StudioBrief
    from apps.workspaces.models import Workspace

    org = Organization.objects.create(id=ORGANISATION_ID, name=ORGANISATION_NAME, default_timezone=TIMEZONE)
    workspace = Workspace.objects.create(
        id=WORKSPACE_ID,
        organization=org,
        name=WORKSPACE_NAME,
        timezone=TIMEZONE,
        approval_workflow_mode=Workspace.ApprovalWorkflowMode.REQUIRED_INTERNAL,
        require_dashboard_approval=True,
    )
    people = {}
    for key, (_user_id, _email, _name, role, org_role) in PEOPLE.items():
        person = _person(key)
        OrgMembership.objects.create(user=person, organization=org, org_role=org_role)
        WorkspaceMembership.objects.create(user=person, workspace=workspace, workspace_role=role)
        people[key] = person

    accounts = {}
    for platform, (account_id, name, handle, platform_id) in ACCOUNTS.items():
        account = SocialAccount(
            id=account_id,
            workspace=workspace,
            platform=platform,
            account_platform_id=platform_id,
            account_name=name,
            account_handle=handle,
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
            oauth_access_token=f"visual-token-{platform}",
            follower_count=2400,
        )
        # Connected long ago, as in the seed: no first-connect analytics backfill.
        account.__dict__["_skip_analytics_backfill"] = True
        account.save()
        create_default_queue_and_slots(account)
        accounts[platform] = account

    # The set-up rows carry the set-up time, not the moment of this call.
    for model, rows in (
        (Organization, {"pk": org.pk}),
        (Workspace, {"pk": workspace.pk}),
        (OrgMembership, {"organization": org}),
        (WorkspaceMembership, {"workspace": workspace}),
        (SocialAccount, {"workspace": workspace}),
    ):
        fields = {field.name for field in model._meta.concrete_fields}
        model.objects.filter(**rows).update(**{name: SET_UP for name in ("created_at", "updated_at") if name in fields})

    owner = people["owner"]
    profile = ensure_profile(workspace)
    profile.audience = "Young families buying their first home near the river"
    profile.voice = "Warm, plain and specific. No hype."
    profile.default_cta = "Book a visit to the show home"
    profile.save()
    agency, _created = AgencySettings.objects.get_or_create(workspace=workspace)
    agency.lead = owner
    agency.autopilot_enabled = False
    agency.creation_mode = AgencySettings.CreationMode.CONFIRM
    agency.save()
    agency.accounts.set(accounts.values())

    for spec in POSTS:
        post = Post.objects.create(
            id=spec["id"],
            workspace=workspace,
            author=people["editor"],
            caption=spec["caption"],
            proposed_publish_at=spec["at"],
        )
        for platform, status, platform_post_id in spec["channels"]:
            PlatformPost.objects.create(
                id=platform_post_id, post=post, social_account=accounts[platform], status=status
            )
        # auto_now and auto_now_add write the moment of the call; these are the fixture's own.
        PlatformPost.objects.filter(post=post).update(created_at=spec["written"], updated_at=spec["written"])
        Post.objects.filter(pk=post.pk).update(created_at=spec["written"], updated_at=spec["written"])

    for spec in BRIEFS:
        brief = StudioBrief.objects.create(
            id=spec["id"],
            workspace=workspace,
            author=owner,
            requested_by=owner,
            idea=spec["idea"],
            status=spec["status"],
            stage=spec["stage"],
            error=spec["error"],
            started_at=spec["created"],
            finished_at=spec["finished"],
        )
        brief.social_accounts.set([accounts[platform] for platform in spec["channels"]])
        StudioBrief.objects.filter(pk=brief.pk).update(
            created_at=spec["created"], updated_at=spec["finished"] or spec["created"]
        )

    conversation = Conversation.objects.create(
        id=CONVERSATION_ID,
        workspace=workspace,
        audience=Conversation.Audience.INTERNAL,
        created_by=owner,
        last_message_at=MESSAGES[-1][3],
    )
    for message_id, author, body, when in MESSAGES:
        if author == "owner":
            Message.objects.create(
                id=message_id, conversation=conversation, author=owner, author_kind=Message.AuthorKind.STAFF, body=body
            )
        else:
            Message.objects.create(
                id=message_id,
                conversation=conversation,
                author_kind=Message.AuthorKind.AGENT,
                agent="account_manager",
                body=body,
            )
        Message.objects.filter(pk=message_id).update(created_at=when)
    Conversation.objects.filter(pk=conversation.pk).update(created_at=MESSAGES[0][3])

    return {
        "workspace_id": str(workspace.pk),
        "organisation_id": str(org.pk),
        "workspace_name": workspace.name,
        "timezone": TIMEZONE,
        "instant": INSTANT,
        "week": WEEK,
        "users": {key: {"id": str(person.pk), "email": person.email} for key, person in people.items()},
        "accounts": {
            platform: {"id": str(account.pk), "name": account.account_name} for platform, account in accounts.items()
        },
        "posts": [
            {
                "id": str(spec["id"]),
                "at": _iso(spec["at"]),
                "platform_posts": [
                    {"id": str(platform_post_id), "platform": platform, "status": status}
                    for platform, status, platform_post_id in spec["channels"]
                ],
            }
            for spec in POSTS
        ],
        "briefs": [{"id": str(spec["id"]), "status": spec["status"], "title": spec["idea"]} for spec in BRIEFS],
        "conversation": {"id": str(CONVERSATION_ID), "messages": [str(message[0]) for message in MESSAGES]},
    }


@fixture("visual_workspace")
def visual_workspace(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload:
        raise PayloadError("visual_workspace takes no options: send {}.")
    _clear()
    return _make()


# ---------------------------------------------------------------------------
# visual_clock
# ---------------------------------------------------------------------------


def _instant(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PayloadError(f"'at' is an ISO 8601 time with its UTC offset, like {INSTANT!r}.")
    try:
        at = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise PayloadError(f"'at' is an ISO 8601 time with its UTC offset, like {INSTANT!r}; got {value!r}.") from exc
    if at.tzinfo is None or at.utcoffset() is None:
        raise PayloadError(f"'at' needs its UTC offset ({value!r} could be anywhere), like {INSTANT!r}.")
    return at


def _save_check_ins() -> None:
    from apps.common.models import TaskHeartbeat

    global _saved_check_ins
    rows: dict[str, dict[str, Any]] = {
        row["task_name"]: row
        for row in TaskHeartbeat.objects.filter(task_name__in=CHECK_INS).values("task_name", *_CHECK_IN_FIELDS)
    }
    _saved_check_ins = {
        name: ({field: rows[name][field] for field in _CHECK_IN_FIELDS} if name in rows else None) for name in CHECK_INS
    }


def _stamp_check_ins(at: datetime) -> None:
    from apps.common.models import TaskHeartbeat

    for name in CHECK_INS:
        fields = {
            "last_started_at": at,
            "last_success_at": at,
            "last_failure_at": None,
            "state": "ok",
            "error": "",
            "updated_at": at,
        }
        if not TaskHeartbeat.objects.filter(task_name=name).update(**fields):
            TaskHeartbeat.objects.create(task_name=name, **fields)
            TaskHeartbeat.objects.filter(task_name=name).update(updated_at=at)


def _restore_check_ins() -> None:
    from apps.common.models import TaskHeartbeat

    global _saved_check_ins
    if _saved_check_ins is None:
        return
    for name, fields in _saved_check_ins.items():
        if fields is None:
            TaskHeartbeat.objects.filter(task_name=name).delete()
        elif not TaskHeartbeat.objects.filter(task_name=name).update(**fields):
            TaskHeartbeat.objects.create(task_name=name, **fields)
            TaskHeartbeat.objects.filter(task_name=name).update(updated_at=fields["updated_at"])
    _saved_check_ins = None


@fixture("visual_clock")
def visual_clock(payload: dict[str, Any]) -> dict[str, Any]:
    from django.utils import timezone

    if not isinstance(payload, dict):
        raise PayloadError(f'Send {{"at": "{INSTANT}"}} to freeze the clock, or {{}} to clear it.')
    unknown = sorted(set(payload) - {"at"})
    if unknown:
        raise PayloadError(f"Unknown key(s) {', '.join(unknown)}; send 'at' to freeze the clock, or {{}} to clear it.")
    if "at" not in payload:
        clock.thaw()
        _restore_check_ins()
        worker.resume()
        return {"frozen": False, "now": timezone.now().astimezone(UTC).isoformat()}

    at = _instant(payload["at"])
    if clock.frozen() is None:
        # First the worker stops between tasks, then its check-ins are read: nothing writes them after.
        worker.hold()
        _save_check_ins()
    instant = clock.freeze(at)
    _stamp_check_ins(instant)
    return {"frozen": True, "now": timezone.now().isoformat()}
