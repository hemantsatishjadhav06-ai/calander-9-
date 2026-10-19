"""The manager's inbox: short messages to each approver's own paired private chat.

Everything the team needs a person for (a draft to approve, a reminder, a
failed delivery, a finished week, a problem) goes through :func:`tell`, which
finds the current approvers, respects their mute switch, quiet hours and a
daily cap, and queues through the encrypted, retried outbox. Nothing here
approves, schedules or publishes; a card only offers the one-use buttons the
person already has on the web.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone

from apps.members.models import WorkspaceMembership
from apps.studio.models import AgencySettings

from .models import TelegramConnection, TelegramDelivery, TelegramUserLink
from .outbox import link_button, link_keyboard, permitted_chat, queue_album, queue_message, queue_photo
from .permissions import internal_member

logger = logging.getLogger(__name__)

#: Proactive messages one person receives per workspace-local day.
DAILY_CAP = 40
#: Workspace-local hours in which only urgent messages go out; the briefing covers the rest.
QUIET_START, QUIET_END = 22, 7
#: Events that may interrupt quiet hours.
URGENT_EVENTS = frozenset({"approval_reminder", "approval_stalled", "delivery_failed"})
PREFIX = "inbox:"
FOOTER = "Nothing publishes without your approval."


def zone_of(workspace):
    try:
        return ZoneInfo(workspace.effective_timezone or "UTC")
    except (ValueError, ZoneInfoNotFoundError):
        return ZoneInfo("UTC")


def connection_for(workspace):
    return TelegramConnection.objects.filter(workspace=workspace, is_active=True).first()


def approvers(workspace, *, include_muted=False):
    """Current approvers with an active pairing: lead and backup first, then internal approvers.

    Returns ``[(user, link), ...]``. Clients never qualify, whatever their custom
    role says; a person who sent ``/mute`` is left out unless ``include_muted``.
    """
    if workspace.is_archived:
        return []
    connection = connection_for(workspace)
    if connection is None:
        return []
    row = AgencySettings.objects.filter(workspace=workspace).only("lead_id", "backup_id").first()
    first = [uid for uid in ((row.lead_id, row.backup_id) if row else ()) if uid]
    eligible: dict = {}
    for membership in (
        WorkspaceMembership.objects.filter(workspace=workspace, user__is_active=True)
        .select_related("user", "custom_role")
        .order_by("user__name", "user__email")
    ):
        if not internal_member(membership):
            continue
        permissions = membership.effective_permissions or {}
        if not permissions.get("approve_posts"):
            continue
        if membership.user_id in first or permissions.get("create_posts"):
            eligible[membership.user_id] = membership.user
    if not eligible:
        return []
    links = TelegramUserLink.objects.filter(connection=connection, user_id__in=list(eligible), is_active=True)
    if not include_muted:
        links = links.filter(notify_needs_you=True)
    by_user = {link.user_id: link for link in links}
    ordered = [uid for uid in first if uid in by_user] + [
        uid for uid in eligible if uid in by_user and uid not in first
    ]
    return [(eligible[uid], by_user[uid]) for uid in ordered]


def is_quiet(workspace, when=None) -> bool:
    local = timezone.localtime(when or timezone.now(), zone_of(workspace))
    return local.hour >= QUIET_START or local.hour < QUIET_END


def sent_today(chat, workspace) -> int:
    """Inbox messages already queued to this chat since local midnight (continuations don't count)."""
    local = timezone.localtime(timezone.now(), zone_of(workspace))
    midnight = datetime.combine(local.date(), datetime.min.time(), tzinfo=local.tzinfo)
    return (
        TelegramDelivery.objects.filter(chat=chat, source_key__startswith=PREFIX, created_at__gte=midnight)
        .exclude(source_key__regex=r":part:[1-9][0-9]*$")
        .count()
    )


def _key(source_key, user_id):
    inner = str(source_key)
    if len(inner) > 100:
        inner = hashlib.sha256(inner.encode()).hexdigest()[:40]
    return f"{PREFIX}{inner}:user:{user_id}"


def post_path(post):
    """The exact page a person approves this post on: its brief page when the team made it, else Approvals."""
    brief_id = (
        post.studio_briefs.filter(workspace_id=post.workspace_id, status__in=["ready", "approved"])
        .order_by("-finished_at", "-created_at")
        .values_list("pk", flat=True)
        .first()
    )
    if brief_id:
        return reverse("studio:detail", kwargs={"workspace_id": post.workspace_id, "brief_id": brief_id})
    return approvals_path(post.workspace_id)


def approvals_path(workspace_id):
    return reverse("calendar:calendar", kwargs={"workspace_id": workspace_id}) + "?mode=list&tab=approvals"


def home_path(workspace_id):
    return reverse("studio:index", kwargs={"workspace_id": workspace_id})


def _private_chat(connection, link):
    from .provisioning import ProvisioningError, private_chat

    try:
        chat = private_chat(connection, link)
    except (PermissionDenied, ProvisioningError):
        return None
    return chat if permitted_chat(chat) else None


def _review_card(chat, link, post):
    """The real one-use review card, or (None, reason) when the card cannot carry this post."""
    from .actions import TelegramActionError, issue_post_review

    try:
        return issue_post_review(chat, link, post), ""
    except TelegramActionError as exc:
        return None, str(exc)


def _post_preview(post, reason):
    attachments = list(post.media_attachments.select_related("media_asset").order_by("position", "id"))
    images = [item.media_asset for item in attachments if item.media_asset.is_image]
    row = post.platform_posts.select_related("social_account").order_by("pk").first()
    caption = (row.effective_caption if row is not None else post.caption) or ""
    lines = [f"Draft ready: {post.title[:100] or 'Your post'}"]
    if caption:
        lines.append(caption[:400] + ("…" if len(caption) > 400 else ""))
    if len(attachments) > len(images):
        lines.append("This post has a video or file; open it to see everything.")
    elif len(images) > 1:
        lines.append(f"{len(images)} pictures.")
    if reason:
        lines.append(reason)
    lines.append(FOOTER)
    album = [str(asset.pk) for asset in images] if 2 <= len(images) <= 4 and len(images) == len(attachments) else []
    return "\n".join(lines), album


def _queue_card(chat, card, key):
    """Picture first, then the text with its buttons, exactly as a requested card is delivered."""
    markup = card.get("reply_markup")
    text = card.get("text", "")
    prerequisites = []
    if card.get("photo_asset_id"):
        photo = queue_photo(chat, card["photo_asset_id"], source_key=f"{key}:photo")
        if photo is not None:
            prerequisites.append(photo.source_key)
        elif markup:
            markup = None
            text += "\nThe review graphic is unavailable. Open SM Bean to review it before acting."
    return queue_message(chat, text, source_key=key, reply_markup=markup, after_source_keys=prerequisites)


def _queue_post(chat, link, post, key, *, fallback_text):
    card, reason = _review_card(chat, link, post)
    if card is not None:
        return _queue_card(chat, card, key)
    text, album = _post_preview(post, reason) if fallback_text is None else (fallback_text, [])
    if album:
        queue_album(chat, album, caption=post.title[:100] or "Your post", source_key=f"{key}:album")
    return queue_message(
        chat, text, source_key=key, reply_markup=link_keyboard(link_button("Open to approve", post_path(post)))
    )


def tell(
    workspace,
    text,
    *,
    source_key,
    event,
    reply_markup=None,
    photo_asset_id=None,
    post=None,
    exclude_user_id=None,
    only_user_id=None,
    include_muted=False,
):
    """Queue one message per current approver into their private chat. Returns people told.

    ``post`` sends that post's review card when the person may act on it from
    Telegram, else a short preview with an "Open to approve" link. Repeats
    with the same ``source_key`` are dropped by the outbox. A card is never
    built while agency work is running; the receipt sweep sends it moments
    later outside that context.
    """
    from apps.studio import guards

    connection = connection_for(workspace)
    if connection is None:
        return 0
    if post is not None and guards.in_agent_work():
        return 0
    quiet = is_quiet(workspace) and event not in URGENT_EVENTS
    told = 0
    for user, link in approvers(workspace, include_muted=include_muted):
        if exclude_user_id is not None and str(user.pk) == str(exclude_user_id):
            continue
        if only_user_id is not None and str(user.pk) != str(only_user_id):
            continue
        chat = _private_chat(connection, link)
        if chat is None or quiet:
            continue
        if sent_today(chat, workspace) >= DAILY_CAP:
            continue
        key = _key(source_key, user.pk)
        try:
            if post is not None:
                rows = _queue_post(chat, link, post, key, fallback_text=text if text else None)
            elif photo_asset_id:
                row = queue_photo(chat, photo_asset_id, caption=text, source_key=key, reply_markup=reply_markup)
                rows = [row] if row else queue_message(chat, text, source_key=key, reply_markup=reply_markup)
            else:
                rows = queue_message(chat, text, source_key=key, reply_markup=reply_markup)
        except PermissionDenied:
            continue
        if rows:
            told += 1
    return told


def recent(chat, *, since: timedelta = timedelta(days=1)) -> int:
    """How many inbox messages a chat received lately; the briefing uses it for its own wording."""
    return TelegramDelivery.objects.filter(
        chat=chat, source_key__startswith=PREFIX, created_at__gte=timezone.now() - since
    ).count()
