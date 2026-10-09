"""The client's side of the team thread: "Talk to the team" and "Ask the team" on a post.

Every view is under ``/portal/`` (so the approval actor is the PORTAL channel)
and behind ``portal_auth_required``; every lookup is scoped to
``request.portal_workspace``, and only *client* threads are reachable from
here. Clients never see internal notes (``chat.recent_messages(for_client=True)``).

"Request a change" on a post waiting for the client's OK does two things, in
this order: the client's own decision is recorded synchronously with the same
service the portal's request-changes button uses (``pending_client`` →
``changes_requested``, in this request, as this person), and then the message
goes to the account manager, whose job routes the revision in the worker. The
model never moves a post between approval states.
"""

from __future__ import annotations

import json
import uuid

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from apps.approvals import services as approval_services
from apps.composer.models import Post
from apps.studio import chat
from apps.studio.models import Conversation

from .decorators import portal_auth_required

CLIENT = Conversation.Audience.CLIENT
#: Posts a client can see in the portal (approvals queue and published list), and so ask about.
VISIBLE_STATUSES = ("pending_client", "approved", "scheduled", "on_hold", "published")


def _ratelimit_key(group, request):
    """The signed-in client (portal sessions are full logins)."""
    return str(request.user.pk) if request.user.is_authenticated else request.META.get("REMOTE_ADDR", "")


def _visible_post(workspace, post_id) -> Post:
    post = get_object_or_404(Post, id=post_id, workspace=workspace)
    if not post.platform_posts.filter(status__in=VISIBLE_STATUSES).exists():
        raise Http404
    return post


def _shown_post(conversation):
    """The post a client thread is about, while the client can still see it (else the thread is just a thread)."""
    if conversation is None or not conversation.post_id:
        return None
    post = conversation.post
    return post if post.platform_posts.filter(status__in=VISIBLE_STATUSES).exists() else None


def _parse_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def thread_context(request, conversation, *, post=None, dom_id="team-thread", error="", body="") -> dict:
    """What ``client_portal/partials/team_thread.html`` needs (the conversation may not exist yet)."""
    workspace = request.portal_workspace
    messages = chat.recent_messages(conversation, for_client=True) if conversation is not None else []
    chat.mark_read(request.user, conversation)
    if post is not None:
        send_url = reverse("client_portal:post_ask", kwargs={"post_id": post.pk})
        pending = post.platform_posts.filter(status="pending_client").exists()
    else:
        send_url = reverse("client_portal:team_send")
        pending = False
    messages_url = ""
    if conversation is not None:
        messages_url = reverse("client_portal:team_messages", kwargs={"conversation_id": conversation.pk})
        if dom_id != "team-thread":
            messages_url += f"?d={dom_id}"
    return {
        "workspace": workspace,
        "conversation": conversation,
        "messages": messages,
        "post": post,
        "post_pending": pending,
        # On a card the card's own buttons ask for the change; on the Talk to the team page the thread does.
        "show_change_button": pending and dom_id == "team-thread",
        "dom_id": dom_id,
        "send_url": send_url,
        "messages_url": messages_url,
        "polling": chat.has_active_job(conversation),
        "viewer_id": request.user.pk,
        "tzname": workspace.effective_timezone or "UTC",
        "error": error,
        "body": body,
    }


def _render_thread(request, context, *, status=200, triggers=None) -> HttpResponse:
    response = render(request, "client_portal/partials/team_thread.html", {"pt": context}, status=status)
    if triggers:
        response["HX-Trigger"] = json.dumps(triggers)
    return response


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@portal_auth_required
@require_GET
def portal_team(request):
    """Every client thread of the workspace — the general one and one per post — with one open."""
    workspace = request.portal_workspace
    conversations = list(
        chat.client_conversations(workspace)
        .exclude(last_message_at=None)
        .select_related("post")
        .order_by("-last_message_at")[:50]
    )
    general = chat.find_general(workspace, audience=CLIENT)
    selected = general
    wanted = _parse_uuid(request.GET.get("c", "")) if request.GET.get("c") else None
    if wanted is not None:
        selected = chat.get_conversation(workspace, wanted, client_only=True)
        if selected is None:
            raise Http404
    unread = chat.unread_counts(request.user, workspace, conversations, for_client=True)
    rows = []
    for conversation in conversations:
        rows.append(
            {
                "conversation": conversation,
                "title": conversation.title or "Talk to the team",
                "is_post": conversation.post_id is not None,
                "unread": unread.get(conversation.pk, 0),
                "active": selected is not None and conversation.pk == selected.pk,
                "url": f"{reverse('client_portal:team')}?c={conversation.pk}",
            }
        )
    post = _shown_post(selected)
    context = thread_context(request, selected, post=post)
    return render(
        request,
        "client_portal/team.html",
        {
            "workspace": workspace,
            "rows": rows,
            "pt": context,
            "general_selected": selected is None or (general is not None and selected.pk == general.pk),
            "has_general_row": general is not None and any(r["conversation"].pk == general.pk for r in rows),
            "tzname": workspace.effective_timezone or "UTC",
        },
    )


@portal_auth_required
@require_GET
def portal_team_messages(request, conversation_id):
    """One client thread's messages, polled while the account manager is answering."""
    workspace = request.portal_workspace
    conversation = chat.get_conversation(workspace, conversation_id, client_only=True)
    if conversation is None:
        raise Http404
    # The card's own container id, or the Talk to the team page's: nothing else is echoed back.
    card_id = f"post-thread-{conversation.post_id}" if conversation.post_id else ""
    dom_id = card_id if card_id and request.GET.get("d") == card_id else "team-thread"
    context = thread_context(request, conversation, post=conversation.post, dom_id=dom_id)
    return render(request, "client_portal/partials/team_messages.html", {"pt": context})


@portal_auth_required
@require_GET
def portal_post_thread(request, post_id):
    """The thread about one post, shown on its approval card (loaded when the card opens)."""
    workspace = request.portal_workspace
    post = _visible_post(workspace, post_id)
    conversation = chat.find_conversation(workspace, post, audience=CLIENT)
    return _render_thread(request, thread_context(request, conversation, post=post, dom_id=f"post-thread-{post.pk}"))


def portal_team_unread(request):
    """The nav badge: unread replies across the client's threads (empty for anyone without a portal session)."""
    if request.method != "GET":
        return HttpResponse(status=405)
    if not request.user.is_authenticated or not request.session.get("is_portal_session"):
        return HttpResponse(status=204)
    from apps.members.models import WorkspaceMembership
    from apps.workspaces.models import Workspace

    workspace = Workspace.objects.filter(id=request.session.get("portal_workspace_id")).first()
    if workspace is None or not WorkspaceMembership.objects.filter(user=request.user, workspace=workspace).exists():
        return HttpResponse(status=204)
    count = chat.portal_unread_total(request.user, workspace)
    return render(request, "client_portal/partials/team_badge.html", {"count": count})


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


@portal_auth_required
@ratelimit(key=_ratelimit_key, rate="10/m", method="POST", block=True)
@require_POST
def portal_team_send(request):
    """A message in the general client thread (created by the first one) or in another client thread."""
    workspace = request.portal_workspace
    body = request.POST.get("body", "")
    conversation = None
    if request.POST.get("c"):
        wanted = _parse_uuid(request.POST["c"])
        conversation = chat.get_conversation(workspace, wanted, client_only=True) if wanted else None
        if conversation is None:
            raise Http404
    post = _shown_post(conversation)
    try:
        chat.clean_body(body)
        if conversation is None:
            conversation = chat.general_conversation(workspace, audience=CLIENT, created_by=request.user)
        chat.post_message(conversation, request.user, body, kind="question" if post is not None else "")
    except chat.ChatError as exc:
        if request.htmx:
            return _render_thread(request, thread_context(request, conversation, post=post, error=str(exc), body=body))
        return HttpResponse(str(exc), status=400)
    if request.htmx:
        return _render_thread(request, thread_context(request, conversation, post=post))
    return redirect(f"{reverse('client_portal:team')}?c={conversation.pk}")


@portal_auth_required
@ratelimit(key=_ratelimit_key, rate="10/m", method="POST", block=True)
@require_POST
def portal_post_ask(request, post_id):
    """Ask the team about a post, or request a change to it (Figma: client approvals card)."""
    workspace = request.portal_workspace
    post = _visible_post(workspace, post_id)
    kind = "change" if request.POST.get("kind") == "change" else "question"
    body = request.POST.get("body") or request.POST.get("comment") or ""
    dom_id = f"post-thread-{post.pk}"
    if request.POST.get("d") == "team-thread":
        dom_id = "team-thread"
    conversation = chat.find_conversation(workspace, post, audience=CLIENT)

    def refuse(message):
        if request.htmx:
            context = thread_context(request, conversation, post=post, dom_id=dom_id, error=message, body=body)
            return _render_thread(request, context)
        return HttpResponse(message, status=400)

    try:
        chat.clean_body(body)
        conversation = conversation or chat.conversation_for(workspace, post, audience=CLIENT, created_by=request.user)
        chat.author_kind_for(request.user, conversation)
    except chat.ChatError as exc:
        return refuse(str(exc))

    moved = False
    if kind == "change" and post.platform_posts.filter(status="pending_client").exists():
        # The client's decision, in their own request: the same service as the portal's
        # request-changes button. The account manager then routes the revision.
        try:
            moved = bool(approval_services.request_changes(post, request.user, workspace, body.strip()))
        except ValueError as exc:
            return refuse(str(exc))

    try:
        chat.post_message(conversation, request.user, body, kind=kind)
    except chat.ChatError as exc:
        return refuse(str(exc))

    if kind == "change":
        toast = {
            "tone": "info",
            "title": "Sent to the team",
            "body": "Your account manager is passing it on. The new version comes back to you for approval.",
        }
    else:
        toast = {"tone": "success", "title": "Message sent", "body": "Your account manager will reply here shortly."}
    triggers: dict = {"showToast": toast}
    if moved:
        triggers["portalAction"] = {"postId": str(post.id), "action": "changes_requested"}
    if request.htmx:
        return _render_thread(
            request, thread_context(request, conversation, post=post, dom_id=dom_id), triggers=triggers
        )
    return redirect(f"{reverse('client_portal:team')}?c={conversation.pk}")
