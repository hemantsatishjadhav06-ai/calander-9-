"""The team thread: people talk to the agency, and the account manager answers.

A :class:`~apps.studio.models.Conversation` belongs to one workspace and is
either *internal* (the agency team only) or *client* (the client reads it in
the portal). It is about the workspace in general or about one item: a brief,
a composer post or a blog article. Each :class:`~apps.studio.models.Message`
is from a person (staff or client), from an agent, or from the system.

Who may write where is decided here, not in the views:

* staff — a member who may create posts and is not a plain client (clients are
  full logins too, with ``approve_posts``) — may write in every thread of the
  workspace, and may leave internal notes, which no client ever sees;
* a client may write only in the client threads of their own workspace.

Who answers:

* a client's message, and a staff member's message in an internal thread,
  queue a ``chat`` job: the account manager answers in the worker and may pass
  the request to the team (``apps.studio.jobtypes.chat``). Nothing chosen by
  the model runs inside a web request;
* a staff member writing in a *client* thread is a person answering the
  client, so the account manager stays out of it (the client is told instead);
* an internal note never gets an answer.

Two limits stop runaway spend before a job is queued: a daily cap on agent
replies per workspace, counted in the database (not the per-process rate-limit
cache), and the monthly budget. Past either, the message is still kept for a
person to read, and the thread says so politely — to a client without a word
about budgets.

Unread counts use the time a person last opened a thread, kept as a workspace
setting per person and thread (no migration, and nothing to clean up when a
thread is deleted beyond a stale key).
"""

from __future__ import annotations

import logging
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import AgencyJob, Conversation, Message, StudioBrief

logger = logging.getLogger(__name__)

#: Agent replies a workspace may ask for in 24 hours, whatever the budget says.
DAILY_REPLY_CAP = 200
#: Earlier messages the account manager reads before the one it answers.
HISTORY_LIMIT = 12
#: Characters of each earlier message the account manager reads.
HISTORY_CHARS = 600
#: Messages a thread panel shows.
SHOWN_MESSAGES = 60
MAX_BODY = 4000
#: The same person hears about new messages in the same thread at most this often.
STAFF_NOTIFY_EVERY = timedelta(minutes=30)
#: A client is told about replies at most this often (the email cap is 6 an hour, shared with approvals).
CLIENT_NOTIFY_EVERY = timedelta(hours=1)
READ_KEY_PREFIX = "thread.read."
#: How the message was asked: from a post card (``change``, ``question``), as a new idea
#: (``create``: the person wants a post made from their words), the one-tap
#: confirmation of a brief card (``confirm_brief``), or a routine's standing instruction
#: running on its schedule (``routine``). The account manager reads it.
REQUEST_KINDS = ("change", "question", "confirm_brief", "create", "routine")
#: Source evidence behind a brief counts as current for this long; after that it is refreshed silently.
SOURCE_MAX_AGE = timedelta(hours=24)
#: A draft the thread keeps an eye on: something is going out, or went wrong going out.
PENDING_DELIVERY = frozenset({"scheduled", "publishing", "failed"})
#: Brief states a person can still stop from the thread (nothing was made yet).
STOPPABLE = (StudioBrief.Status.PLANNED, StudioBrief.Status.QUEUED, StudioBrief.Status.WORKING)

CLIENT_ROLE = "client"


class ChatError(Exception):
    """A person can't post this message here. The text is for them."""


@dataclass(frozen=True)
class Posted:
    """What :func:`post_message` did: the message, the job it queued, and why not (if it didn't)."""

    message: Message
    job: AgencyJob | None = None
    note: str = ""


# ---------------------------------------------------------------------------
# Who may write
# ---------------------------------------------------------------------------


def membership_for(user, workspace):
    from apps.members.models import WorkspaceMembership

    if user is None or not getattr(user, "is_authenticated", False) or workspace is None:
        return None
    return WorkspaceMembership.objects.filter(user=user, workspace=workspace).select_related("custom_role").first()


def is_client_membership(membership) -> bool:
    """A client of the agency (the portal's people), with or without a custom role."""
    return membership is not None and membership.workspace_role == CLIENT_ROLE


def is_staff_membership(membership) -> bool:
    """Someone on the agency side: may create posts, and is not a plain client.

    The same rule as the agency's pages (``views._workspace`` refuses plain
    clients; creating and revising need ``create_posts``).
    """
    if membership is None:
        return False
    plain_client = membership.workspace_role == CLIENT_ROLE and membership.custom_role_id is None
    return not plain_client and bool(membership.effective_permissions.get("create_posts"))


def is_staff(user, workspace) -> bool:
    return is_staff_membership(membership_for(user, workspace))


def web_kind_for_member(membership, conversation: Conversation, *, is_internal: bool = False) -> str:
    """Classify a freshly authorized author without granting clients internal work."""
    from apps.telegram.permissions import internal_member

    if internal_member(membership) and membership.effective_permissions.get("create_posts") is True:
        return Message.AuthorKind.STAFF
    if membership is not None and not internal_member(membership):
        if conversation.audience != Conversation.Audience.CLIENT:
            raise ChatError("This thread is for the agency team only.")
        if is_internal:
            raise ChatError("Only the agency team can leave internal notes.")
        return Message.AuthorKind.CLIENT
    raise ChatError("You can't write in this thread.")


def web_author_kind(conversation, user, *, is_internal=False, locked=False):
    """Check fresh tenant/actor/role before web writes or provider work.

    Web sends and returning workers share workspace -> actor -> conversation
    locking. In particular, a send must not hold its conversation while a
    deferred job foreign-key check waits for another transaction's workspace.
    """
    from django.core.exceptions import PermissionDenied

    from apps.telegram.permissions import current_member

    if user is None or not getattr(user, "pk", None) or not getattr(user, "is_authenticated", False):
        raise ChatError("Your current workspace access is unavailable.")
    try:
        member = current_member(conversation.workspace, user, locked=locked)
    except PermissionDenied:
        raise ChatError("Your current workspace access is unavailable.") from None
    rows = Conversation.objects.select_for_update(of=("self",)) if locked else Conversation.objects.all()
    current = rows.filter(pk=conversation.pk, workspace_id=member.workspace_id).first()
    if current is None or is_private_conversation(current):
        raise ChatError("This conversation is unavailable in the shared workspace.")
    conversation.audience = current.audience
    conversation.brief_id, conversation.post_id, conversation.blog_post_id = (
        current.brief_id,
        current.post_id,
        current.blog_post_id,
    )
    conversation._state.fields_cache.clear()
    conversation.workspace = member.workspace
    return web_kind_for_member(member, conversation, is_internal=is_internal), member


def author_kind_for(user, conversation: Conversation, *, is_internal: bool = False) -> str:
    return web_author_kind(conversation, user, is_internal=is_internal)[0]


def telegram_member(conversation, user, context, *, locked=False):
    """Recheck the paired speaker and exact bound conversation; IDs alone grant no rights."""
    from django.core.exceptions import PermissionDenied

    from apps.telegram.models import TelegramChat, TelegramUserLink
    from apps.telegram.permissions import fresh_member, internal_member

    if not isinstance(context, dict) or user is None:
        raise ChatError("Pair your Telegram account and conversation again.")
    try:
        chat_id = uuid.UUID(str(context.get("chat_id", "")))
        link_id = uuid.UUID(str(context.get("user_link_id", "")))
    except (ValueError, TypeError, AttributeError):
        raise ChatError("Pair your Telegram account and conversation again.") from None
    link = TelegramUserLink.objects.select_related("connection__workspace", "user").filter(pk=link_id).first()
    if link is None or link.user_id != user.pk:
        raise ChatError("Your Telegram pairing is unavailable.")
    try:
        member = fresh_member(link, locked=locked)
    except PermissionDenied:
        raise ChatError("Your current Telegram workspace access is unavailable.") from None
    if member is None or member.workspace_id != conversation.workspace_id:
        raise ChatError("This Telegram conversation belongs to another workspace.")
    chats = TelegramChat.objects.select_for_update(of=("self",)) if locked else TelegramChat.objects.all()
    current = chats.filter(
        pk=chat_id,
        connection_id=link.connection_id,
        connection__workspace_id=conversation.workspace_id,
        connection__is_active=True,
        conversation_id=conversation.pk,
        is_active=True,
    ).first()
    if current is None:
        raise ChatError("This Telegram conversation is unavailable.")
    threads = Conversation.objects.select_for_update() if locked else Conversation.objects.all()
    thread = threads.filter(pk=conversation.pk, workspace_id=member.workspace_id).first()
    if thread is None or thread.audience != conversation.audience:
        raise ChatError("This Telegram conversation changed; pair it again.")
    if current.audience == TelegramChat.Audience.PRIVATE:
        if current.private_user_id != user.pk or current.chat_type != "private":
            raise ChatError("This private Telegram conversation belongs to another person.")
        if TelegramChat.objects.filter(conversation_id=thread.pk).exclude(pk=current.pk).exists():
            raise ChatError("A private Telegram conversation cannot share group history.")
        if thread.created_by_id != user.pk:
            raise ChatError("This private Telegram history belongs to another person.")
    elif current.audience == TelegramChat.Audience.TEAM:
        if (
            is_private_conversation(thread)
            or thread.audience != Conversation.Audience.INTERNAL
            or not internal_member(member)
        ):
            raise ChatError("This Telegram conversation is for the agency team.")
    elif (
        current.audience != TelegramChat.Audience.CLIENT
        or thread.audience != Conversation.Audience.CLIENT
        or is_private_conversation(thread)
    ):
        raise ChatError("This Telegram conversation has an invalid audience.")
    if not internal_member(member) and thread.audience != Conversation.Audience.CLIENT:
        raise ChatError("This Telegram conversation is for the agency team.")
    return member


def telegram_author_kind(conversation, user, context, *, locked=False):
    from apps.telegram.permissions import internal_member

    member = telegram_member(conversation, user, context, locked=locked)
    if not internal_member(member):
        return Message.AuthorKind.CLIENT, member
    if is_staff_membership(member):
        return Message.AuthorKind.STAFF, member
    raise ChatError("Your role cannot request the agency team from Telegram.")


def _telegram_job_context(context, member):
    """Persist consent epochs while canonical posting owns the actor/pairing locks."""
    from apps.telegram.models import TelegramChat, TelegramUserLink
    from apps.telegram.processing import connection_epoch
    from apps.telegram.provisioning import channel_authority_digest

    link = TelegramUserLink.objects.filter(pk=context["user_link_id"], user=member.user, is_active=True).first()
    current = (
        TelegramChat.objects.select_related("connection")
        .filter(pk=context["chat_id"], connection_id=link.connection_id if link else None, is_active=True)
        .first()
    )
    if link is None or current is None or current.connection.workspace_id != member.workspace_id:
        raise ChatError("Your Telegram pairing changed. Send the request again in the currently paired conversation.")
    return {
        "chat_id": str(current.pk),
        "user_link_id": str(link.pk),
        "binding": {
            "connection_epoch": connection_epoch(current.connection),
            "connection_updated_at": current.connection.updated_at.isoformat(),
            "pairing_epoch": link.updated_at.isoformat(),
            "chat_epoch": current.updated_at.isoformat(),
            "telegram_user_id": link.telegram_user_id,
            "organization_id": str(member.workspace.organization_id),
            "authority_digest": channel_authority_digest(member),
        },
    }


def telegram_job_author_kind(job, conversation, user, *, locked=False):
    """Old queued jobs cannot adopt a repaired identity's current authority."""
    context = (job.input or {}).get("telegram_context")
    if not isinstance(context, dict) or set(context) != {"chat_id", "user_link_id", "binding"}:
        raise ChatError(
            "This queued Telegram request has no current pairing proof. Review saved work and send it again "
            "in the currently paired conversation."
        )
    kind, member = telegram_author_kind(conversation, user, context, locked=locked)
    if context != _telegram_job_context(context, member):
        raise ChatError(
            "The bot, pairing or permissions changed after this Telegram request. Review saved work and send "
            "it again in the currently paired conversation."
        )
    return kind, member


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------


def _private_conversations():
    return Conversation.objects.filter(Q(is_private=True) | Q(telegram_chats__audience="private"))


def is_private_conversation(conversation) -> bool:
    """Privacy follows the persisted thread, including inactive and former bindings."""
    return bool(conversation is not None and _private_conversations().filter(pk=conversation.pk).exists())


def web_conversations(workspace=None):
    """Threads supported by the ordinary dashboard/portal, excluding all private history."""
    rows = Conversation.objects.exclude(pk__in=_private_conversations().values("pk"))
    return rows.filter(workspace=workspace) if workspace is not None else rows


def web_jobs(rows):
    return rows.exclude(conversation_id__in=_private_conversations().values("pk"))


def web_agent_runs(rows):
    return rows.exclude(job__conversation_id__in=_private_conversations().values("pk"))


def _web_lookup(workspace, audience, **target):
    rows = web_conversations(workspace).filter(**_lookup(workspace, audience, **target))
    if not any(target.values()):
        # A Telegram group has its own associated thread, rather than becoming
        # the workspace-wide general thread by being created first.
        rows = rows.filter(telegram_chats__isnull=True)
        # Saved guided ideas have dedicated intake threads before they have
        # a brief. They must never become the workspace-wide general thread.
        rows = rows.exclude(messages__action="workflow_idea")
    return rows


def _lookup(workspace, audience: str, **target) -> dict[str, Any]:
    return {"workspace": workspace, "audience": audience, "brief": None, "post": None, "blog_post": None, **target}


def _get_or_create(workspace, *, audience: str, created_by=None, title: str = "", **target) -> Conversation:
    lookup = _lookup(workspace, audience, **target)
    found = _web_lookup(workspace, audience, **target).order_by("created_at").first()
    if found is not None:
        return found
    from apps.workspaces.models import Workspace

    with transaction.atomic():
        # Two first messages at once must not start two threads: serialise on the workspace row.
        Workspace.objects.select_for_update().filter(pk=workspace.pk).first()
        found = _web_lookup(workspace, audience, **target).order_by("created_at").first()
        if found is not None:
            return found
        return Conversation.objects.create(created_by=created_by, title=title[:200], **lookup)


def _general_title(audience: str) -> str:
    return "Talk to the team" if audience == Conversation.Audience.CLIENT else "Ask the team"


def general_conversation(workspace, *, audience: str = Conversation.Audience.INTERNAL, created_by=None):
    """The workspace's general thread for ``audience`` (created the first time)."""
    return _get_or_create(workspace, audience=audience, created_by=created_by, title=_general_title(audience))


def find_general(workspace, *, audience: str = Conversation.Audience.INTERNAL) -> Conversation | None:
    """The general thread if anyone has written in it yet (reading a page never creates one)."""
    return _web_lookup(workspace, audience).order_by("created_at").first()


def _target_kwargs(workspace, target, audience: str) -> tuple[dict[str, Any], str]:
    from apps.blog.models import BlogPost
    from apps.composer.models import Post

    if getattr(target, "workspace_id", None) != workspace.id:
        raise ChatError("That item belongs to another workspace.")
    if isinstance(target, StudioBrief):
        return {"brief": target}, target.title
    if isinstance(target, Post):
        return {"post": target}, target.title or (target.caption or "")[:80]
    if isinstance(target, BlogPost):
        if audience == Conversation.Audience.CLIENT:
            raise ChatError("Blog articles aren't shared with clients in the portal.")
        return {"blog_post": target}, target.title
    raise TypeError(f"Conversations can't be about a {type(target).__name__}")


def conversation_for(workspace, target, *, audience: str, created_by=None) -> Conversation:
    """The thread about ``target`` (a StudioBrief, composer Post or BlogPost) for ``audience``."""
    kwargs, title = _target_kwargs(workspace, target, audience)
    return _get_or_create(workspace, audience=audience, created_by=created_by, title=title, **kwargs)


def find_conversation(workspace, target, *, audience: str) -> Conversation | None:
    """The thread about ``target`` if it exists (no write)."""
    kwargs, _title = _target_kwargs(workspace, target, audience)
    return _web_lookup(workspace, audience, **kwargs).order_by("created_at").first()


def brief_conversation(brief: StudioBrief) -> Conversation | None:
    """The brief's internal thread, if anyone has written in it yet."""
    return (
        web_conversations()
        .filter(
            workspace_id=brief.workspace_id,
            audience=Conversation.Audience.INTERNAL,
            brief=brief,
            post=None,
            blog_post=None,
        )
        .order_by("created_at")
        .first()
    )


def get_conversation(workspace, conversation_id, *, client_only: bool = False) -> Conversation | None:
    """A thread of ``workspace`` by id (only client threads when ``client_only``)."""
    rows = web_conversations(workspace).filter(pk=conversation_id)
    if client_only:
        rows = rows.filter(audience=Conversation.Audience.CLIENT)
    return rows.select_related("workspace", "brief", "post", "blog_post").first()


def visible_messages(conversation: Conversation, *, for_client: bool):
    rows = Message.objects.filter(conversation=conversation).select_related("author", "job")
    if for_client:
        rows = rows.filter(is_internal=False)
    return rows


def recent_messages(conversation: Conversation, *, for_client: bool, limit: int = SHOWN_MESSAGES) -> list[Message]:
    rows = list(visible_messages(conversation, for_client=for_client).order_by("-created_at")[:limit])
    rows.reverse()
    return rows


def has_active_job(conversation: Conversation | None) -> bool:
    if conversation is None:
        return False
    answering = AgencyJob.objects.filter(
        workspace_id=conversation.workspace_id,
        conversation=conversation,
        kind=AgencyJob.Kind.CHAT,
        status__in=AgencyJob.ACTIVE_STATUSES,
    ).exists()
    if answering or conversation.audience != Conversation.Audience.INTERNAL:
        return answering
    return linked_briefs(conversation).filter(status__in=StudioBrief.ACTIVE_STATUSES).exists()


def linked_briefs(conversation: Conversation):
    """Posts created from this exact thread; never rebind the general thread."""
    return (
        StudioBrief.objects.filter(
            workspace_id=conversation.workspace_id,
            origin=StudioBrief.Origin.CHAT,
            job__workspace_id=conversation.workspace_id,
            job__conversation=conversation,
        )
        .select_related("graphic", "post", "job", "chosen_concept")
        .prefetch_related("post__platform_posts__social_account")
    )


def _public_link(value):
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        return (
            value
            if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password
            else ""
        )
    except ValueError:
        return ""


def _source_warnings(sources):
    warnings = []
    website = sources.get("website") or {}
    if not isinstance(website, dict) or website.get("status") != "ready":
        warnings.append("Website evidence is unavailable. Check current brand facts with the owner before continuing.")
    try:
        fetched = parse_datetime(str(sources.get("fetched_at") or ""))
        stale = (
            fetched is None
            or timezone.is_naive(fetched)
            or timezone.now() - fetched > SOURCE_MAX_AGE
            or fetched > timezone.now()
        )
    except (ValueError, TypeError, OverflowError):
        stale = True
    if stale:
        warnings.append(
            "This evidence is more than a day old. It is refreshed when you go ahead; you are asked again only if it changed."
        )
    channels = sources.get("channels") or []
    if isinstance(channels, list) and any(
        isinstance(channel, dict) and channel.get("source") == "stored_history" for channel in channels
    ):
        warnings.append(
            "Some channels use saved publication history, not a fresh account read. Check dates and claims yourself."
        )
    return warnings


def _publication_receipts(brief, viewer=None, *, can_reconcile=None):
    """Readable delivery evidence from exact, same-workspace destinations."""
    from apps.publisher import delivery

    if brief.post_id is None or brief.post.workspace_id != brief.workspace_id:
        return []
    receipts = []
    if can_reconcile is None:
        membership = membership_for(viewer, brief.workspace)
        can_reconcile = is_staff_membership(membership) and bool(membership.effective_permissions.get("approve_posts"))
        if (
            membership is not None
            and membership.custom_role_id
            and membership.custom_role.organization_id != brief.workspace.organization_id
        ):
            can_reconcile = False
    for row in brief.post.platform_posts.all():
        account = row.social_account
        if account.workspace_id != brief.workspace_id:
            continue
        extra = row.platform_extra if isinstance(row.platform_extra, dict) else {}
        state = delivery.state(row)
        kind = state.get("kind", "")
        unknown = kind == "unknown"
        attempted = state.get("destination")
        attempted = attempted if isinstance(attempted, dict) else {}
        changed_destination = bool(
            attempted
            and (
                str(attempted.get("account_id", "")) != str(account.pk)
                or attempted.get("platform") != account.platform
                or str(attempted.get("native_id", "")) != str(account.account_platform_id or "")
            )
        )
        # Compatibility for attempts made before the durable marker was added.
        if row.status == "failed" and any(
            word in (row.publish_error or "").casefold()
            for word in ("outcome unknown", "may already", "may have been", "check the account")
        ):
            unknown = True
        label = (
            "Delivery outcome unknown"
            if unknown
            else "Expired — needs review"
            if kind == "expired"
            else "Recorded after account check"
            if kind == "reconciled"
            else row.get_status_display()
        )
        reconcile_url = absent_url = ""
        if can_reconcile and not changed_destination and state.get("attempt_id") and (unknown or kind == "expired"):
            try:
                absent_url = reverse(
                    "studio:publisher_delivery:checked_absent",
                    kwargs={"workspace_id": brief.workspace_id, "platform_post_id": row.pk},
                )
                if unknown:
                    reconcile_url = reverse(
                        "studio:publisher_delivery:reconcile_existing",
                        kwargs={"workspace_id": brief.workspace_id, "platform_post_id": row.pk},
                    )
            except NoReverseMatch:
                pass
        receipts.append(
            {
                "row": row,
                "account": account,
                "label": label,
                "kind": kind,
                "unknown": unknown,
                "expired": kind == "expired",
                "reconciled": kind == "reconciled",
                "changed_destination": changed_destination,
                "attempt_native_id": attempted.get("native_id", ""),
                "publish_at": row.scheduled_at or brief.post.scheduled_at,
                "time_label": "Scheduled for"
                if row.status == "scheduled" and not unknown
                else "Previous or proposed posting time"
                if row.status in {"draft", "pending_review", "changes_requested", "rejected", "failed"}
                else "Posting time",
                "published_at": row.published_at,
                "native_post_id": row.platform_post_id if row.status == "published" or kind == "reconciled" else "",
                "url": _public_link(extra.get("permalink") or extra.get("post_url") or extra.get("url"))
                if row.status == "published" or kind == "reconciled"
                else "",
                "error": "Check the native account before any further send. An existing post must be reconciled; do not retry blindly."
                if unknown
                else row.publish_error
                if row.status == "failed"
                else "",
                "case_id": state.get("attempt_id", ""),
                "expected_fingerprint": state.get("content_fingerprint", ""),
                "reconcile_url": reconcile_url,
                "absent_url": absent_url,
            }
        )
    return receipts


def _delivery_pending(brief) -> bool:
    """Whether the thread should keep an eye on this draft's delivery (statuses only, no receipt work)."""
    if brief.post_id is None or brief.post.workspace_id != brief.workspace_id:
        return False
    return any(row.status in PENDING_DELIVERY for row in brief.post.platform_posts.all())


def _creative_message_context(conversation, messages, viewer, *, selected_draft_id: str = "") -> list:
    """Attach staff-only brief cards and draft previews to the messages; returns the thread's drafts.

    Delivery receipts cost a lookup per channel, so they are worked out only
    for the draft in view (``selected_draft_id``) and for drafts with something
    going out or gone wrong; the others carry an empty list.
    """
    if conversation is None or conversation.audience != Conversation.Audience.INTERNAL:
        return []
    from . import creative_brief

    latest = creative_brief.latest_intake(conversation, viewer)
    answering = AgencyJob.objects.filter(
        workspace_id=conversation.workspace_id,
        conversation=conversation,
        kind=AgencyJob.Kind.CHAT,
        status__in=AgencyJob.ACTIVE_STATUSES,
    ).exists()
    briefs = list(linked_briefs(conversation).order_by("-created_at")[:60])
    if (
        conversation.brief_id
        and conversation.brief.workspace_id == conversation.workspace_id
        and all(item.pk != conversation.brief_id for item in briefs)
    ):
        briefs.append(conversation.brief)
    membership = membership_for(viewer, conversation.workspace)
    can_reconcile = is_staff_membership(membership) and bool(membership.effective_permissions.get("approve_posts"))
    if (
        membership is not None
        and membership.custom_role_id
        and membership.custom_role.organization_id != conversation.workspace.organization_id
    ):
        can_reconcile = False
    for brief in briefs:
        if brief.graphic_id and brief.graphic.workspace_id != conversation.workspace_id:
            brief.graphic = None
        brief.publication_receipts = (
            _publication_receipts(brief, can_reconcile=can_reconcile)
            if str(brief.pk) == str(selected_draft_id or "") or _delivery_pending(brief)
            else []
        )
    by_id = {str(brief.pk): brief for brief in briefs}
    by_job = {brief.job_id: brief for brief in briefs}
    for message in messages:
        if message.author_kind != Message.AuthorKind.AGENT or message.job_id is None:
            continue
        if message.job.workspace_id != conversation.workspace_id or message.job.conversation_id != conversation.pk:
            continue
        result = message.job.result if isinstance(message.job.result, dict) else {}
        intake = result.get("creative_brief")
        if isinstance(intake, dict):
            message.creative_request = intake
            sources = result.get("sources")
            message.creative_sources = sources if isinstance(sources, dict) else {}
            message.source_warnings = _source_warnings(message.creative_sources)
            website = message.creative_sources.get("website") or {}
            source_url = website.get("url", "") if isinstance(website, dict) else ""
            try:
                parsed_url = urlsplit(source_url)
                message.website_source_url = (
                    source_url
                    if parsed_url.scheme in {"http", "https"}
                    and parsed_url.hostname
                    and not parsed_url.username
                    and not parsed_url.password
                    else ""
                )
            except (TypeError, ValueError):
                message.website_source_url = ""
            accounts = result.get("selected_accounts")
            message.creative_accounts = accounts if isinstance(accounts, list) else []
            message.creative_defaults = [
                creative_brief.LABELS[key]
                for key in (result.get("creative_defaults") or [])
                if isinstance(key, str) and key in creative_brief.LABELS
            ]
            message.creative_missing = [
                creative_brief.LABELS[key]
                for key in (result.get("creative_missing") or [])
                if isinstance(key, str) and key in creative_brief.LABELS
            ]
            message.evidence_changed = str(result.get("evidence_changed") or "")
            message.auto_started = result.get("auto_started") is True
            message.queued = result.get("queued") is True
            message.can_confirm_brief = bool(
                latest is not None
                and message.job_id == latest.pk
                and message.job.requested_by_id == viewer.pk
                and result.get("awaiting_confirmation")
                and not answering
                and not creative_brief.missing(intake, required=creative_brief.STAFF_REQUIRED)
            )
        message.created_brief = by_id.get(str(result.get("brief_id") or "")) or by_job.get(message.job_id)
        created = message.created_brief
        message.can_stop_brief = bool(
            created is not None
            and (result.get("auto_started") is True or result.get("queued") is True)
            and created.status in STOPPABLE
            and (message.job.requested_by_id == viewer.pk or can_reconcile)
        )
        message.stop_url = (
            reverse(
                "studio:thread_stop_brief",
                kwargs={
                    "workspace_id": conversation.workspace_id,
                    "conversation_id": conversation.pk,
                    "brief_id": created.pk,
                },
            )
            if message.can_stop_brief
            else ""
        )
    return briefs


def _routine_message_context(conversation, messages, viewer, membership) -> None:
    """Attach the "Routine proposed · Turn on" card to the manager replies that proposed one.

    A reply whose chat job carries ``routine_id`` gets ``message.routine``: the
    routine's words, its schedule, whether it is on, and whether this viewer
    may turn it on (the person who asked for it, or a settings manager).
    """
    if conversation is None or conversation.audience != Conversation.Audience.INTERNAL:
        return
    from . import routines
    from .models import Routine

    wanted: dict[str, list] = {}
    for message in messages:
        message.routine = None
        if message.author_kind != Message.AuthorKind.AGENT or message.job_id is None:
            continue
        if message.job.workspace_id != conversation.workspace_id or message.job.conversation_id != conversation.pk:
            continue
        result = message.job.result if isinstance(message.job.result, dict) else {}
        routine_id = str(result.get("routine_id") or "")
        if routine_id:
            wanted.setdefault(routine_id, []).append(message)
    if not wanted:
        return
    perms = membership.effective_permissions if membership is not None else {}
    workspace_id = conversation.workspace_id
    for routine in Routine.objects.filter(workspace_id=workspace_id, pk__in=list(wanted)).select_related(
        "workspace", "created_by"
    ):
        card = {
            "id": str(routine.pk),
            "title": routine.display_title,
            "instruction": routine.instruction,
            "cadence_words": routines.cadence_words(routine),
            "enabled": routine.enabled,
            "can_change": routines.can_change(routine, viewer, perms),
            "toggle_url": reverse(
                "studio:routines_toggle", kwargs={"workspace_id": workspace_id, "routine_id": routine.pk}
            ),
            "url": reverse("studio:routines", kwargs={"workspace_id": workspace_id}),
        }
        for message in wanted[str(routine.pk)]:
            message.routine = card


def creation_mode(workspace) -> str:
    """How the workspace starts a team member's ideas: ``confirm`` (a tap on the brief card) or ``auto``."""
    from .models import AgencySettings

    mode = AgencySettings.objects.filter(workspace=workspace).values_list("creation_mode", flat=True).first()
    return mode if mode in dict(AgencySettings.CreationMode.choices) else AgencySettings.CreationMode.CONFIRM


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------


def _touch(conversation: Conversation, when: datetime) -> None:
    Conversation.objects.filter(pk=conversation.pk).update(last_message_at=when)
    conversation.last_message_at = when


def replies_today(workspace) -> int:
    """Agent replies asked for in the last 24 hours.

    Counted as chat jobs (each answers with at most one message), including
    ones still queued or that failed: a burst of messages must hit the cap
    before the replies exist, and a failed call still cost money.
    """
    since = timezone.now() - timedelta(hours=24)
    return AgencyJob.objects.filter(workspace=workspace, kind=AgencyJob.Kind.CHAT, created_at__gte=since).count()


#: The same sentence as Set up and readiness use for this state; the thread shows no other instruction.
SETUP_REFUSAL = (
    "Your message is saved. Your team isn't connected yet — open Set up. You can still write or edit a draft."
)


def reply_refusal(workspace) -> str:
    """Why the account manager cannot answer yet; never queue a doomed provider call."""
    from . import budget, llm

    if replies_today(workspace) >= DAILY_REPLY_CAP:
        return "cap"
    if not budget.can_spend(workspace):
        return "budget"
    if not llm.is_configured():
        return "setup"
    return ""


def refusal_text(workspace, reason: str, *, audience: str) -> str:
    """The polite sentence the thread shows instead of an answer. A client never reads about budgets."""
    from . import budget

    if reason == "setup":
        if audience == Conversation.Audience.CLIENT:
            return "Your message is saved. Your agency is finishing its set-up; a person will reply here."
        return SETUP_REFUSAL
    if audience == Conversation.Audience.CLIENT:
        return "Thanks — your message is with the team. A person will reply here as soon as they can."
    if reason == "budget":
        return budget.over_budget_message(workspace) + " A person can still answer here."
    return (
        f"The account manager has answered {DAILY_REPLY_CAP} messages in the last day, the most it answers. "
        "A person can still answer here, and the account manager is back tomorrow."
    )


def wants_answer(
    conversation: Conversation, author_kind: str, *, is_internal: bool, explicit_assistant_request: bool = False
) -> bool:
    """Whether the account manager answers this message (see the module docstring)."""
    if is_internal or author_kind not in (Message.AuthorKind.CLIENT, Message.AuthorKind.STAFF):
        return False
    if author_kind == Message.AuthorKind.STAFF:
        return conversation.audience == Conversation.Audience.INTERNAL or explicit_assistant_request
    return True


def clean_body(body: str) -> str:
    body = (body or "").strip()
    if not body:
        raise ChatError("Write a message first.")
    if len(body) > MAX_BODY:
        raise ChatError(f"That message is too long. Keep it under {MAX_BODY:,} characters.")
    return body


def _create_extras(workspace, create) -> dict[str, Any]:
    """The idea form's structured choices, checked against this workspace, as brief fields."""
    from .creative_brief import GOALS
    from .forms import studio_accounts

    data = create if isinstance(create, dict) else {}
    goal = str(data.get("goal") or "")
    notes = str(data.get("notes") or "").strip()[:2000]
    allowed = {str(account.pk) for account in studio_accounts(workspace)}
    accounts: list[str] = []
    for item in data.get("accounts") or []:
        pk = str(getattr(item, "pk", item))
        if pk not in allowed:
            raise ChatError("Choose connected accounts of this workspace.")
        if pk not in accounts:
            accounts.append(pk)
    return {"goal": goal if goal in GOALS else "", "notes": notes, "accounts": accounts}


@transaction.atomic
def post_message(
    conversation: Conversation,
    author,
    body: str,
    *,
    is_internal: bool = False,
    kind: str = "",
    confirmation_message_id: str = "",
    facts_confirmed: bool = False,
    reference_id: str = "",
    style_mode: str = "",
    target_brief_id: str = "",
    explicit_assistant_request: bool = False,
    telegram_context: dict | None = None,
    create: dict | None = None,
) -> Posted:
    """Store ``author``'s message and, when it wants one, ask the account manager to answer.

    ``kind`` is one of :data:`REQUEST_KINDS`; the account manager reads it.
    With ``kind="create"`` the body is the person's own idea in their own
    words, and ``create`` may carry the structured choices of the idea form
    (``goal``, ``notes``, ``accounts``), which reach the brief as fields, never
    as sentences in the person's message. Raises :class:`ChatError`.
    """
    from . import engine

    body = clean_body(body)
    if telegram_context is None and is_private_conversation(conversation):
        raise ChatError("Private Telegram conversations remain in their paired private chat.")
    if telegram_context is not None:
        author_kind, _member = telegram_author_kind(conversation, author, telegram_context, locked=True)
        if is_internal:
            raise ChatError("Telegram messages cannot be internal notes.")
    else:
        author_kind, _member = web_author_kind(conversation, author, is_internal=is_internal, locked=True)
    if explicit_assistant_request and (
        author_kind != Message.AuthorKind.STAFF or is_internal or telegram_context is None
    ):
        raise ChatError("Only a currently paired agency team member can ask the assistant here.")
    workspace = conversation.workspace
    guided = author_kind == Message.AuthorKind.STAFF and (
        conversation.audience == Conversation.Audience.INTERNAL or explicit_assistant_request
    )
    extra_input: dict[str, Any] = {}
    if telegram_context is not None:
        extra_input["telegram_context"] = _telegram_job_context(telegram_context, _member)
        extra_input["explicit_assistant_request"] = bool(explicit_assistant_request)
    if kind == "confirm_brief":
        if not guided or is_internal or not facts_confirmed:
            raise ChatError("Check the brief and source facts before confirming a review draft.")
        if reference_id or style_mode or target_brief_id:
            raise ChatError("Send creative changes as a message first, then confirm the updated brief.")
        try:
            confirmation_id = uuid.UUID(str(confirmation_message_id))
        except (TypeError, ValueError):
            raise ChatError("Choose a current brief confirmation in this thread.") from None
        extra_input.update(confirmation_message_id=str(confirmation_id), facts_confirmed=True)
    if kind == "create":
        if not guided or is_internal:
            raise ChatError("Ideas for new posts go in the team's own conversation.")
        extra_input["create"] = _create_extras(workspace, create)
    if target_brief_id:
        if not guided or is_internal:
            raise ChatError("Choose a draft in the agency team thread.")
        try:
            target_id = uuid.UUID(str(target_brief_id))
        except (TypeError, ValueError):
            raise ChatError("Choose a draft created in this thread.") from None
        if not linked_briefs(conversation).filter(pk=target_id).exists():
            raise ChatError("Choose a draft created in this thread.")
        extra_input["target_brief_id"] = str(target_id)
    if reference_id:
        client_reference = telegram_context is not None and author_kind == Message.AuthorKind.CLIENT
        if (not guided and not client_reference) or is_internal:
            raise ChatError("Choose a photo in the agency team thread.")
        if reference_id != "none":
            from apps.media_library.models import MediaAsset

            try:
                asset_id = uuid.UUID(str(reference_id))
            except (TypeError, ValueError):
                raise ChatError("Choose a photo from this workspace's media library.") from None
            if not MediaAsset.objects.filter(
                pk=asset_id, workspace=workspace, media_type=MediaAsset.MediaType.IMAGE
            ).exists():
                raise ChatError("Choose a photo from this workspace's media library.")
            reference_id = str(asset_id)
        extra_input["reference_id"] = reference_id
    if style_mode:
        if not guided or is_internal or style_mode not in {"brand", "fresh"}:
            raise ChatError("Choose the brand look or a fresh layout in the agency team thread.")
        extra_input["style_mode"] = style_mode
    job = None
    note = ""
    with transaction.atomic():
        if telegram_context is not None:
            current_kind, _member = telegram_author_kind(conversation, author, telegram_context, locked=True)
            if current_kind != author_kind:
                raise ChatError("Your Telegram role changed; send the request again.")
        message = Message.objects.create(
            conversation=conversation, author=author, author_kind=author_kind, body=body, is_internal=is_internal
        )
        _touch(conversation, message.created_at)
        if wants_answer(
            conversation, author_kind, is_internal=is_internal, explicit_assistant_request=explicit_assistant_request
        ):
            reason = reply_refusal(workspace)
            if reason:
                note = refusal_text(workspace, reason, audience=conversation.audience)
                post_system_message(conversation, note)
            else:
                job = engine.create(
                    workspace,
                    AgencyJob.Kind.CHAT,
                    title=f"Reply to {message.sender_name}: {body[:120]}",
                    input={"message_id": str(message.pk), "kind": kind if kind in REQUEST_KINDS else "", **extra_input},
                    requested_by=author,
                    conversation=conversation,
                )
    if author_kind == Message.AuthorKind.CLIENT:
        transaction.on_commit(lambda: _safely(notify_staff_of_client_message, conversation, message))
    elif (
        author_kind == Message.AuthorKind.STAFF
        and not is_internal
        and conversation.audience == Conversation.Audience.CLIENT
    ):
        transaction.on_commit(lambda: _safely(notify_clients_of_reply, conversation))
    return Posted(message=message, job=job, note=note)


def post_agent_message(
    conversation: Conversation,
    body: str,
    *,
    job: AgencyJob | None = None,
    action: str = "",
    action_status: str = "",
    agent: str = "account_manager",
    is_internal: bool = False,
) -> Message:
    message = Message.objects.create(
        conversation=conversation,
        author_kind=Message.AuthorKind.AGENT,
        agent=agent,
        body=body.strip()[:MAX_BODY] or "…",
        action=action[:30],
        action_status=action_status,
        job=job,
        is_internal=is_internal,
    )
    _touch(conversation, message.created_at)
    return message


def post_system_message(
    conversation: Conversation, body: str, *, job: AgencyJob | None = None, is_internal: bool = False
) -> Message:
    message = Message.objects.create(
        conversation=conversation,
        author_kind=Message.AuthorKind.SYSTEM,
        body=body.strip()[:MAX_BODY],
        job=job,
        is_internal=is_internal,
    )
    _touch(conversation, message.created_at)
    return message


def post_failure_note(job, message: str) -> None:
    """Called by the engine when a chat job fails: tell the people in the thread a person will follow up.

    A client thread gets a plain sentence only; the reason (which can name
    server settings) goes in an internal note the client never sees.
    """
    conversation = Conversation.objects.filter(pk=job.conversation_id, workspace_id=job.workspace_id).first()
    if conversation is None:
        return
    post_system_message(
        conversation,
        "Sorry — the team couldn't answer this one automatically. A person will follow up here.",
        job=job,
    )
    if message:
        post_system_message(conversation, f"Why the account manager stopped: {message}", job=job, is_internal=True)
    _safely(
        notify_staff,
        conversation,
        title="The account manager couldn't answer a message",
        body=f"In “{conversation.title or 'the team thread'}”. {message}"[:500],
        kind="needs_person",
    )


# ---------------------------------------------------------------------------
# Unread counts
# ---------------------------------------------------------------------------


def _read_key(user_id, conversation_id) -> str:
    return f"{READ_KEY_PREFIX}{user_id}.{conversation_id}"


def _parse(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def mark_read(user, conversation: Conversation | None) -> None:
    """Remember that ``user`` has seen ``conversation`` up to now (a write only when something is new)."""
    from apps.settings_manager.models import WorkspaceSetting

    if conversation is None or user is None or not getattr(user, "is_authenticated", False):
        return
    if is_private_conversation(conversation):
        return
    key = _read_key(user.pk, conversation.pk)
    current = WorkspaceSetting.objects.filter(workspace_id=conversation.workspace_id, key=key).first()
    seen = _parse(current.value) if current is not None else None
    if seen is not None and (conversation.last_message_at is None or conversation.last_message_at <= seen):
        return
    # Up to the newest message the page showed, not "now": a reply that lands while the
    # page renders still counts as unread.
    upto = conversation.last_message_at or timezone.now()
    WorkspaceSetting.objects.update_or_create(
        workspace_id=conversation.workspace_id, key=key, defaults={"value": upto.isoformat()}
    )


def _read_marks(user, workspace) -> dict[str, datetime]:
    from apps.settings_manager.models import WorkspaceSetting

    prefix = f"{READ_KEY_PREFIX}{user.pk}."
    marks = {}
    for key, value in WorkspaceSetting.objects.filter(workspace=workspace, key__startswith=prefix).values_list(
        "key", "value"
    ):
        seen = _parse(value)
        if seen is not None:
            marks[key[len(prefix) :]] = seen
    return marks


def unread_counts(user, workspace, conversations, *, for_client: bool) -> dict[Any, int]:
    """Messages from others since ``user`` last opened each thread: ``{conversation_id: count}``."""
    if user is None or not getattr(user, "is_authenticated", False):
        return {}
    marks = _read_marks(user, workspace)
    condition = Q()
    visible_ids = set(web_conversations(workspace).values_list("pk", flat=True))
    for conversation in conversations:
        if conversation.pk not in visible_ids:
            continue
        if conversation.last_message_at is None:
            continue
        mark = marks.get(str(conversation.pk))
        if mark is not None and conversation.last_message_at <= mark:
            continue
        condition |= (
            Q(conversation_id=conversation.pk, created_at__gt=mark) if mark else Q(conversation_id=conversation.pk)
        )
    if not condition:
        return {}
    rows = Message.objects.filter(condition, conversation__workspace=workspace).exclude(author=user)
    if for_client:
        rows = rows.filter(is_internal=False)
    return {row["conversation_id"]: row["n"] for row in rows.values("conversation_id").annotate(n=Count("id"))}


def client_conversations(workspace):
    return web_conversations(workspace).filter(audience=Conversation.Audience.CLIENT)


def portal_unread_total(user, workspace) -> int:
    """Unread messages for a client across their workspace's client threads (the portal's nav badge)."""
    conversations = list(
        client_conversations(workspace)
        .exclude(last_message_at=None)
        .only("id", "workspace_id", "last_message_at")
        .order_by("-last_message_at")[:100]
    )
    return sum(unread_counts(user, workspace, conversations, for_client=True).values())


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


def _safely(fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except Exception:
        logger.exception("Team thread: %s failed", getattr(fn, "__name__", fn))


def absolute_url(path: str) -> str:
    return (getattr(settings, "APP_URL", "") or "http://localhost:8000").rstrip("/") + path


def staff_thread_url(conversation: Conversation) -> str:
    url = reverse("studio:thread", kwargs={"workspace_id": conversation.workspace_id})
    return f"{url}?c={conversation.pk}"


def portal_thread_url(conversation: Conversation) -> str:
    return f"{reverse('client_portal:team')}?c={conversation.pk}"


def staff_recipients(workspace) -> list:
    """The agency people who hear about client messages: internal approvers, and the agency lead."""
    from apps.members.models import WorkspaceMembership

    from .models import AgencySettings

    people = []
    for membership in WorkspaceMembership.objects.filter(workspace=workspace).select_related("user", "custom_role"):
        if not membership.user.is_active:
            continue
        if membership.workspace_role == CLIENT_ROLE and membership.custom_role_id is None:
            continue
        perms = membership.effective_permissions
        if perms.get("approve_posts") and perms.get("create_posts"):
            people.append(membership.user)
    row = AgencySettings.objects.filter(workspace=workspace).select_related("lead").first()
    if row is not None and row.lead is not None and row.lead not in people and is_staff(row.lead, workspace):
        people.append(row.lead)
    return people


def _recently_told(user, *, since: timedelta, conversation: Conversation | None = None, kind: str = "") -> bool:
    from apps.notifications.models import EventType, Notification

    rows = Notification.objects.filter(
        user=user, event_type=EventType.TEAM_MESSAGE, created_at__gte=timezone.now() - since
    )
    if conversation is not None:
        rows = rows.filter(data__conversation_id=str(conversation.pk))
    if kind:
        rows = rows.filter(data__kind=kind)
    return rows.exists()


def notify_staff(conversation: Conversation, *, title: str, body: str, exclude=None, kind: str = "message") -> int:
    """Tell the agency people about this thread (in the app; email follows their preferences), throttled.

    At most one notice of each ``kind`` per person per thread every half hour:
    a run of client messages is one notice, but "this needs a person" is never
    hidden behind the "new message" notice sent a minute before.
    """
    from apps.notifications.engine import notify
    from apps.notifications.models import EventType

    if is_private_conversation(conversation):
        return 0
    told = 0
    for user in staff_recipients(conversation.workspace):
        if user == exclude or _recently_told(user, since=STAFF_NOTIFY_EVERY, conversation=conversation, kind=kind):
            continue
        notify(
            user=user,
            event_type=EventType.TEAM_MESSAGE,
            title=title,
            body=body,
            data={
                "workspace_id": str(conversation.workspace_id),
                "conversation_id": str(conversation.pk),
                "kind": kind,
                "action_url": absolute_url(staff_thread_url(conversation)),
            },
        )
        told += 1
    return told


def notify_staff_of_client_message(conversation: Conversation, message: Message) -> int:
    if is_private_conversation(conversation):
        return 0
    return notify_staff(
        conversation,
        title=f"{message.sender_name} wrote in the team thread",
        body=f"“{message.body[:160]}” — in {conversation.title or 'the team thread'}.",
    )


def notify_clients_of_reply(conversation: Conversation, *, only=None) -> int:
    """Tell the clients who wrote in this thread (or just ``only``) that the team answered.

    At most one notice an hour per client across all threads, so replies never
    use up the per-recipient email allowance that approval requests rely on;
    the portal's unread badge shows the rest.
    """
    from apps.members.models import WorkspaceMembership
    from apps.notifications.engine import notify
    from apps.notifications.models import EventType

    if conversation.audience != Conversation.Audience.CLIENT or is_private_conversation(conversation):
        return 0
    if only is not None:
        author_ids = {only.pk}
    else:
        author_ids = set(
            Message.objects.filter(conversation=conversation, author_kind=Message.AuthorKind.CLIENT)
            .exclude(author__isnull=True)
            .values_list("author_id", flat=True)
        )
    told = 0
    for membership in WorkspaceMembership.objects.filter(
        workspace_id=conversation.workspace_id, user_id__in=author_ids, workspace_role=CLIENT_ROLE
    ).select_related("user", "workspace"):
        user = membership.user
        if not user.is_active or _recently_told(user, since=CLIENT_NOTIFY_EVERY):
            continue
        notify(
            user=user,
            event_type=EventType.TEAM_MESSAGE,
            title=f"The {membership.workspace.name} team replied",
            body="There's a new reply to your message. Open your portal to read it.",
            data={
                "workspace_id": str(conversation.workspace_id),
                "conversation_id": str(conversation.pk),
                "action_url": absolute_url(portal_thread_url(conversation)),
            },
        )
        told += 1
    return told


# ---------------------------------------------------------------------------
# The staff thread panel (studio/partials/thread.html)
# ---------------------------------------------------------------------------

PANEL_TEMPLATE = "studio/partials/thread.html"


def dom_id(conversation: Conversation | None = None, *, brief: StudioBrief | None = None, blog_post=None) -> str:
    """A stable element id for a thread panel, the same before and after its first message."""
    internal = conversation is None or conversation.audience == Conversation.Audience.INTERNAL
    blog_id = blog_post.pk if blog_post is not None else (conversation.blog_post_id if conversation else None)
    if blog_id and internal:
        return f"thread-blog-{blog_id}"
    brief_id = brief.pk if brief is not None else (conversation.brief_id if conversation is not None else None)
    if brief_id and (conversation is None or conversation.audience == Conversation.Audience.INTERNAL):
        return f"thread-brief-{brief_id}"
    if conversation is None:
        return "thread-home"
    if (
        conversation.audience == Conversation.Audience.INTERNAL
        and not conversation.telegram_chats.exists()
        and not (conversation.post_id or conversation.blog_post_id)
    ):
        return "thread-home"
    return f"thread-{conversation.pk}"


def thread_context(
    request,
    conversation: Conversation | None,
    *,
    workspace=None,
    brief: StudioBrief | None = None,
    blog_post=None,
    error: str = "",
    body: str = "",
    full_page: bool = False,
) -> dict[str, Any] | None:
    """What ``studio/partials/thread.html`` needs, for the signed-in staff member, or None for anyone else.

    Pass the conversation; or ``None`` with ``brief`` (or ``blog_post``) for
    an item whose internal thread has no messages yet, or with ``workspace``
    for the general thread (the first message creates any of them). Reading
    never creates a thread; it marks it read for the viewer.
    """
    if is_private_conversation(conversation):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied("Private Telegram conversations remain in their paired private chat.")
    if conversation is not None:
        workspace = conversation.workspace
    elif brief is not None:
        workspace = brief.workspace
        conversation = brief_conversation(brief)
    elif blog_post is not None:
        workspace = blog_post.workspace
        conversation = find_conversation(workspace, blog_post, audience=Conversation.Audience.INTERNAL)
    if workspace is None:
        raise ValueError("thread_context needs a conversation, a brief or a workspace")
    membership = getattr(request, "workspace_membership", None)
    if membership is None or membership.workspace_id != workspace.pk:
        membership = membership_for(request.user, workspace)
    if not is_staff_membership(membership):
        return None

    messages = recent_messages(conversation, for_client=False) if conversation is not None else []
    workspace_id = workspace.pk
    messages_url = ""
    if conversation is not None:
        send_url = reverse(
            "studio:thread_send", kwargs={"workspace_id": workspace_id, "conversation_id": conversation.pk}
        )
        messages_url = reverse(
            "studio:thread_messages", kwargs={"workspace_id": workspace_id, "conversation_id": conversation.pk}
        )
    elif brief is not None:
        send_url = reverse("studio:brief_thread_send", kwargs={"workspace_id": workspace_id, "brief_id": brief.pk})
    elif blog_post is not None:
        send_url = reverse(
            "studio:blog_thread_send", kwargs={"workspace_id": workspace_id, "blog_post_id": blog_post.pk}
        )
    else:
        send_url = reverse("studio:thread_start", kwargs={"workspace_id": workspace_id})

    is_client_thread = conversation is not None and conversation.audience == Conversation.Audience.CLIENT
    about_brief = brief is not None or (conversation is not None and conversation.brief_id is not None)
    about_article = blog_post is not None or (conversation is not None and conversation.blog_post_id is not None)
    if is_client_thread:
        title = "With the client"
        subtitle = "Your client reads everything here except internal notes. The account manager answers them."
        placeholder = "Reply to the client…"
        internal_label = "Internal note — the client never sees it"
    elif about_brief:
        title, subtitle = "Ask for changes", "Tell the team in your words — the account manager routes it."
        placeholder = "e.g. Shorter caption, mention parking"
        internal_label = "Note for the team only — no reply from the account manager"
    elif about_article:
        title = "Ask for changes"
        subtitle = "Say what to change in this article — the account manager passes it to the writers."
        placeholder = "e.g. Add an FAQ about stamp duty"
        internal_label = "Note for the team only — no reply from the account manager"
    else:
        from .models import AgencySettings

        title = "Create with the team"
        # The header matches the workspace's creation mode: a tap, or the manager going ahead by itself.
        if creation_mode(workspace) == AgencySettings.CreationMode.AUTO:
            subtitle = "Say what you want to post. Your manager goes ahead with sensible defaults; you can stop it for a minute."
        else:
            subtitle = "Say what you want to post. Your manager proposes the brief; one tap starts it."
        placeholder = "e.g. A LinkedIn post inviting families to Saturday's site visit"
        internal_label = "Note for the team only — no reply from the account manager"
    named = conversation.title if conversation is not None and conversation.title != title else ""
    if named and (is_client_thread or full_page) and not about_brief and not about_article:
        subtitle = f"{named} · {subtitle}"
    thread_url = reverse("studio:thread", kwargs={"workspace_id": workspace_id})
    if conversation is not None:
        thread_url += f"?c={conversation.pk}"
    guided_creation = not is_client_thread and not about_article
    reference_choices = []
    if guided_creation:
        from apps.media_library.models import MediaAsset

        reference_choices = list(
            MediaAsset.objects.filter(workspace=workspace, media_type=MediaAsset.MediaType.IMAGE)
            .exclude(source__in=["ai-studio", "fal.ai"])
            .exclude(tags__contains=["ai"])
            .select_related("verified_by")
            .order_by("-created_at")[:24]
        )
    draft_choices = (
        list(linked_briefs(conversation).order_by("-created_at")[:30])
        if guided_creation and conversation is not None
        else []
    )
    latest_job = (
        AgencyJob.objects.filter(
            workspace=workspace, conversation=conversation, requested_by=request.user, kind=AgencyJob.Kind.CHAT
        )
        .order_by("-created_at")
        .first()
        if conversation is not None
        else None
    )
    latest_input = latest_job.input if latest_job is not None and isinstance(latest_job.input, dict) else {}
    latest_result = latest_job.result if latest_job is not None and isinstance(latest_job.result, dict) else {}
    selected_draft_id = request.POST.get(
        "target_brief_id", latest_input.get("target_brief_id", latest_result.get("brief_id", ""))
    )
    selected_draft = next((draft for draft in draft_choices if str(draft.pk) == selected_draft_id), None)
    if selected_draft is None:
        selected_draft_id = ""
        about = brief or (conversation.brief if conversation is not None and conversation.brief_id else None)
        if about is not None and about.workspace_id == workspace.pk:
            selected_draft = about
    # The cards and previews, with delivery receipts only for the draft in view and drafts still going out.
    drafts = _creative_message_context(
        conversation,
        messages,
        request.user,
        selected_draft_id=str(selected_draft.pk) if selected_draft is not None else "",
    )
    _routine_message_context(conversation, messages, request.user, membership)
    mark_read(request.user, conversation)
    selected_reference_id = (
        request.POST.get("reference_id")
        or latest_input.get("reference_id")
        or latest_result.get("reference_id")
        or (str(selected_draft.source_picture_id) if selected_draft and selected_draft.source_picture_id else "")
    )
    selected_style_mode = (
        request.POST.get("style_mode")
        or latest_input.get("style_mode")
        or latest_result.get("style_mode")
        or ("brand" if selected_draft and selected_draft.style_lock else "fresh" if selected_draft else "")
    )
    selected_reference = next((asset for asset in reference_choices if str(asset.pk) == selected_reference_id), None)
    if selected_reference is None and selected_reference_id not in {"", "none"} and guided_creation:
        with suppress(TypeError, ValueError):
            selected_reference = (
                MediaAsset.objects.filter(
                    pk=uuid.UUID(str(selected_reference_id)), workspace=workspace, media_type=MediaAsset.MediaType.IMAGE
                )
                .exclude(source__in=["ai-studio", "fal.ai"])
                .exclude(tags__contains=["ai"])
                .select_related("verified_by")
                .first()
            )
        if selected_reference is not None:
            reference_choices.append(selected_reference)
    if selected_reference_id not in {"", "none"} and selected_reference is None:
        selected_reference_id = ""
    from . import trust

    for asset in reference_choices:
        cast(Any, asset).provenance = trust.photo_status(asset)
    delivery_pending = any(
        receipt["row"].status in {"scheduled", "publishing"} or receipt["unknown"]
        for draft in drafts
        for receipt in draft.publication_receipts
    )
    if selected_draft is not None and all(draft.pk != selected_draft.pk for draft in drafts):
        delivery_pending = delivery_pending or any(
            receipt["row"].status in {"scheduled", "publishing"} or receipt["unknown"]
            for receipt in _publication_receipts(selected_draft)
        )
    working = has_active_job(conversation)
    # The panel on Home polls with ``?home=1`` so a card's "Turn on" returns to Home, not the thread page.
    home_panel = request.GET.get("home") == "1"
    if home_panel and messages_url:
        messages_url += "?home=1"
    return {
        "template": PANEL_TEMPLATE,
        "workspace": workspace,
        "conversation": conversation,
        "messages": messages,
        "dom_id": dom_id(conversation, brief=brief, blog_post=blog_post),
        "send_url": send_url,
        "messages_url": messages_url,
        "home_panel": home_panel,
        "home_url": reverse("studio:index", kwargs={"workspace_id": workspace_id}),
        "polling": working or delivery_pending,
        "poll_interval": "every 3s" if working else "every 30s",
        "creation_mode": creation_mode(workspace),
        "can_set_creation_mode": bool(membership.effective_permissions.get("manage_workspace_settings")),
        "creation_mode_url": reverse("studio:creation_mode", kwargs={"workspace_id": workspace_id}),
        "thread_key": f"{workspace.pk}:{dom_id(conversation, brief=brief, blog_post=blog_post)}",
        "can_post": True,
        "can_post_internal": True,
        "internal_label": internal_label,
        "is_client_thread": is_client_thread,
        "guided_creation": guided_creation,
        "reference_choices": reference_choices,
        "draft_choices": draft_choices,
        "selected_draft_id": selected_draft_id,
        "selected_reference_id": selected_reference_id,
        "selected_reference": selected_reference,
        "selected_style_mode": selected_style_mode,
        "can_upload_reference": guided_creation and bool(membership.effective_permissions.get("upload_media")),
        "title": title,
        "subtitle": subtitle,
        "placeholder": placeholder,
        "viewer_id": getattr(request.user, "pk", None),
        "tzname": workspace.effective_timezone or "UTC",
        "thread_url": thread_url,
        "full_page": full_page,
        "error": error,
        "body": body,
    }


def home_thread_context(request, workspace) -> dict[str, Any] | None:
    """The agency home's conversation panel: the workspace's general internal thread."""
    context = thread_context(request, find_general(workspace), workspace=workspace)
    if context is not None:
        context["home_panel"] = True
        if context["messages_url"] and "home=1" not in context["messages_url"]:
            context["messages_url"] += "?home=1"
    return context


def brief_thread_context(request, brief: StudioBrief) -> dict[str, Any] | None:
    """The brief page's "Ask for changes" panel: the brief's internal thread."""
    return thread_context(request, None, brief=brief)


def blog_thread_context(request, blog_post) -> dict[str, Any] | None:
    """An "Ask for changes" panel for a blog article's page: the article's internal thread.

    Include it like the others: ``{% include thread.template with thread=thread %}``.
    """
    return thread_context(request, None, blog_post=blog_post)
