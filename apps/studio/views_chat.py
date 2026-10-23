"""The team thread for the agency's staff, and "Draft replies with the team" for the inbox.

Under ``/workspace/<id>/studio/`` like the rest of the agency, for people who
may create posts and are not plain clients (clients talk to the team in the
portal, ``apps.client_portal.views_team``). Sending a message only stores it
and queues the account manager's turn (``apps.studio.chat.post_message``); the
model's answer, and anything it asks the team to do, happens in the worker.

HTMX requests get the panel or the message list back as a fragment; a plain
form post is redirected to the thread page.
"""

from __future__ import annotations

import uuid

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from apps.members.decorators import require_permission

from . import budget, chat, dashboard, inbox_team, services
from .models import AgencySettings, Conversation, StudioBrief
from .views import _perms, _workspace


def _staff_workspace(request, workspace_id):
    """The workspace, for someone who may use the team thread (create posts, not a plain client)."""
    workspace = _workspace(request, workspace_id)
    if not _perms(request).get("create_posts", False):
        raise PermissionDenied("The team thread is for people who make posts in this workspace.")
    return workspace


def _conversation(workspace, conversation_id) -> Conversation:
    conversation = chat.get_conversation(workspace, conversation_id)
    if conversation is None:
        raise Http404("No such thread.")
    return conversation


def _panel(request, context) -> HttpResponse:
    if context is None:
        raise PermissionDenied("The team thread is for the agency team.")
    return render(request, chat.PANEL_TEMPLATE, {"thread": context})


def _thread_page_url(workspace, conversation=None) -> str:
    url = reverse("studio:thread", kwargs={"workspace_id": workspace.id})
    return f"{url}?c={conversation.pk}" if conversation is not None else url


def _after_send(
    request, workspace, conversation, *, posted=None, error="", body="", brief=None, blog_post=None, full_page=False
):
    if request.htmx:
        context = chat.thread_context(
            request,
            conversation,
            workspace=workspace,
            brief=brief,
            blog_post=blog_post,
            error=error,
            body=body,
            full_page=full_page,
        )
        return _panel(request, context)
    if error:
        messages.error(request, error)
    elif posted is not None and posted.note:
        messages.info(request, posted.note)
    if brief is not None:
        return redirect("studio:detail", workspace_id=workspace.id, brief_id=brief.pk)
    if blog_post is not None:
        return redirect("blog:detail", workspace_id=workspace.id, post_id=blog_post.pk)
    return redirect(_thread_page_url(workspace, conversation))


# ---------------------------------------------------------------------------
# Pages and fragments
# ---------------------------------------------------------------------------


@login_required
@require_GET
def thread_page(request, workspace_id):
    """Every thread of the workspace — the general one, client threads, threads about posts — with one open."""
    workspace = _staff_workspace(request, workspace_id)
    conversations = list(
        chat.web_conversations(workspace)
        .select_related("brief", "post", "blog_post")
        .exclude(last_message_at=None)
        .order_by("-last_message_at")[:60]
    )
    selected = None
    wanted = request.GET.get("c", "")
    if wanted:
        try:
            selected = chat.get_conversation(workspace, uuid.UUID(wanted))
        except ValueError:
            selected = None
        if selected is None:
            raise Http404("No such thread.")
    general = chat.find_general(workspace)
    if selected is None:
        selected = general
    unread = chat.unread_counts(request.user, workspace, conversations, for_client=False)
    panel = chat.thread_context(request, selected, workspace=workspace, full_page=True)
    rows = []
    for conversation in conversations:
        if conversation.audience == Conversation.Audience.CLIENT:
            kind = "Client"
        elif conversation.brief_id or conversation.post_id:
            kind = "Post"
        elif conversation.blog_post_id:
            kind = "Article"
        else:
            kind = "Team"
        rows.append(
            {
                "conversation": conversation,
                "kind": kind,
                "title": conversation.title or chat._general_title(conversation.audience),
                "unread": unread.get(conversation.pk, 0),
                "active": selected is not None and conversation.pk == selected.pk,
                "url": _thread_page_url(workspace, conversation),
            }
        )
    return render(
        request,
        "studio/thread.html",
        {
            "workspace": workspace,
            "rows": rows,
            "thread": panel,
            "general_selected": selected is None or (general is not None and selected.pk == general.pk),
            "general_url": _thread_page_url(workspace),
            "has_general_row": general is not None and any(r["conversation"].pk == general.pk for r in rows),
            "tabs": dashboard.tabs(workspace, "thread", perms=_perms(request)),
            "tzname": workspace.effective_timezone or "UTC",
        },
    )


@login_required
@require_GET
def thread_messages(request, workspace_id, conversation_id):
    """The message list of one thread, polled while the account manager is answering."""
    workspace = _staff_workspace(request, workspace_id)
    conversation = _conversation(workspace, conversation_id)
    context = chat.thread_context(request, conversation, full_page=request.GET.get("full") == "1")
    if context is None:
        raise PermissionDenied("The team thread is for the agency team.")
    return render(request, "studio/partials/thread_messages.html", {"thread": context})


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


def _send(request, workspace, conversation_getter, *, brief=None, blog_post=None):
    body = request.POST.get("body", "")
    is_internal = request.POST.get("is_internal") in ("1", "on", "true")
    full_page = request.POST.get("full") == "1"
    conversation = None
    try:
        chat.clean_body(body)
        conversation = conversation_getter()
        reference_id = request.POST.get("reference_id", "")
        uploaded = request.FILES.get("reference_upload")
        if uploaded is not None:
            if (
                conversation.audience != Conversation.Audience.INTERNAL
                or is_internal
                or request.POST.get("kind") == "confirm_brief"
            ):
                raise chat.ChatError("Attach the photo in a message before confirming your brief.")
            if not _perms(request).get("upload_media", False):
                raise PermissionDenied("You don't have permission to upload media.")
            from apps.media_library.quotas import StorageQuotaExceededError
            from apps.media_library.services import create_asset, upload_rejection_message
            from apps.media_library.tasks import process_media_asset

            try:
                picture = forms.ImageField().clean(uploaded)
                if picture.image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise forms.ValidationError("Use a JPEG, PNG or WebP still photo for this brief.")
                asset = create_asset(
                    workspace.organization,
                    workspace,
                    picture,
                    request.user,
                    title=f"Brief photo: {picture.name}"[:255],
                    source="studio-brief-photo",
                )
            except (StorageQuotaExceededError, forms.ValidationError) as exc:
                raise chat.ChatError(upload_rejection_message(exc)) from None
            process_media_asset(str(asset.pk))
            reference_id = str(asset.pk)
        posted = chat.post_message(
            conversation,
            request.user,
            body,
            is_internal=is_internal,
            kind=request.POST.get("kind", ""),
            confirmation_message_id=request.POST.get("confirmation_message_id", ""),
            facts_confirmed=request.POST.get("facts_confirmed") == "1",
            reference_id=reference_id,
            style_mode=request.POST.get("style_mode", ""),
            target_brief_id=request.POST.get("target_brief_id", ""),
        )
    except chat.ChatError as exc:
        return _after_send(
            request,
            workspace,
            conversation,
            error=str(exc),
            body=body,
            brief=brief,
            blog_post=blog_post,
            full_page=full_page,
        )
    return _after_send(
        request, workspace, conversation, posted=posted, brief=brief, blog_post=blog_post, full_page=full_page
    )


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def thread_send(request, workspace_id, conversation_id):
    workspace = _staff_workspace(request, workspace_id)
    conversation = _conversation(workspace, conversation_id)
    return _send(
        request,
        workspace,
        lambda: conversation,
        brief=conversation.brief if conversation.brief_id else None,
        blog_post=conversation.blog_post if conversation.blog_post_id else None,
    )


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def thread_start(request, workspace_id):
    """The first message in the general thread creates it (reading the home page never does)."""
    workspace = _staff_workspace(request, workspace_id)
    return _send(request, workspace, lambda: chat.general_conversation(workspace, created_by=request.user))


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def brief_thread_send(request, workspace_id, brief_id):
    """A message in a brief's internal thread, created by the first one."""
    workspace = _staff_workspace(request, workspace_id)
    brief = get_object_or_404(StudioBrief, pk=brief_id, workspace=workspace)

    def getter():
        return chat.brief_conversation(brief) or chat.conversation_for(
            workspace, brief, audience=Conversation.Audience.INTERNAL, created_by=request.user
        )

    return _send(request, workspace, getter, brief=brief)


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def blog_thread_send(request, workspace_id, blog_post_id):
    """A message in a blog article's internal thread, created by the first one."""
    from apps.blog.models import BlogPost

    workspace = _staff_workspace(request, workspace_id)
    blog_post = get_object_or_404(BlogPost, pk=blog_post_id, workspace=workspace)

    def getter():
        return chat.conversation_for(
            workspace, blog_post, audience=Conversation.Audience.INTERNAL, created_by=request.user
        )

    return _send(request, workspace, getter, blog_post=blog_post)


# ---------------------------------------------------------------------------
# Stopping work started from the thread, and how ideas start
# ---------------------------------------------------------------------------


@login_required
@require_permission("create_posts")
@require_POST
def thread_stop_brief(request, workspace_id, conversation_id, brief_id):
    """ "Stop" on a brief card: drop a post the manager started from this thread before the draft exists.

    The person who asked for it, or an approver, may stop it. The brief is
    discarded the same way the brief page does it; nothing else changes.
    """
    workspace = _staff_workspace(request, workspace_id)
    conversation = _conversation(workspace, conversation_id)
    brief = chat.linked_briefs(conversation).filter(pk=brief_id, workspace=workspace).first()
    if brief is None:
        raise Http404("No such draft in this thread.")
    if brief.requested_by_id != request.user.pk and not _perms(request).get("approve_posts", False):
        raise PermissionDenied("Only the person who asked for this post, or an approver, can stop it.")
    error = ""
    if brief.status not in chat.STOPPABLE:
        error = "This post is past the point where it can be stopped here. Review it from its page."
    else:
        try:
            services.discard(brief)
        except services.StudioActionError as exc:
            error = str(exc)
        else:
            who = request.user.name or request.user.email
            chat.post_system_message(conversation, f"{who} stopped this post before the draft was made.")
    return _after_send(request, workspace, conversation, error=error, full_page=request.POST.get("full") == "1")


@login_required
@require_permission("manage_workspace_settings")
@require_POST
def creation_mode(request, workspace_id):
    """How a team member's ideas start: after a tap on the brief card, or at once ("go unless I say stop").

    Clients always confirm, and every finished post still waits for approval
    whatever the mode; this only decides whether the team waits for the tap.
    """
    workspace = _staff_workspace(request, workspace_id)
    mode = request.POST.get("mode", "")
    if mode not in dict(AgencySettings.CreationMode.choices):
        raise Http404("No such choice.")
    row, _created = AgencySettings.objects.get_or_create(workspace=workspace)
    if row.creation_mode != mode:
        row.creation_mode = mode
        row.save(update_fields=["creation_mode", "updated_at"])
    messages.success(
        request,
        "From now on your manager goes ahead with the team's ideas. Every finished post still waits for your approval."
        if mode == AgencySettings.CreationMode.AUTO
        else "Your manager now shows you each brief first.",
    )
    back = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        back = _thread_page_url(workspace)
    return redirect(back)


# ---------------------------------------------------------------------------
# Inbox: "Draft replies with the team"
# ---------------------------------------------------------------------------


@login_required
@require_permission("use_inbox")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def inbox_draft(request, workspace_id):
    """Ask the community and reviews managers for reply drafts on the chosen (or newest) inbox messages.

    Drafts only: a person reads, edits and sends each one from the inbox.
    """
    workspace = _staff_workspace(request, workspace_id)
    back = reverse("inbox:feed", kwargs={"workspace_id": workspace.id})
    raw = ",".join(request.POST.getlist("message_ids"))
    ids = [part.strip() for part in raw.split(",") if part.strip()]
    if not budget.can_spend(workspace):
        messages.error(request, budget.over_budget_message(workspace))
        return redirect(back)
    rows = inbox_team.candidates(workspace, ids=ids or None, manual=True)
    if not rows:
        messages.info(
            request,
            "Nothing to draft: the messages you picked already have a reply, or there are no new comments, "
            "messages or reviews waiting.",
        )
        return redirect(back)
    job = inbox_team.queue(workspace, rows, requested_by=request.user, source="manual")
    if job is None:
        messages.info(request, "The team is already drafting replies here. They'll appear on each message shortly.")
        return redirect(back)
    messages.success(
        request,
        f"The community manager is drafting {len(rows)} repl{'y' if len(rows) == 1 else 'ies'}. "
        "They appear on each message as drafts for you to check and send — nothing is sent on its own.",
    )
    return redirect(back)
