"""A durable, guided entry point to the existing creative and publishing work.

Ideas are ordinary shared internal threads, not a second task or approval
system. Reading progress never starts work. Starting an idea queues the
canonical account-manager turn; its explicit brief confirmation and the
existing human approval gate still decide what may be created and published.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from django import forms
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from . import budget, chat, creative_brief, dashboard, llm
from .models import AgencyJob, Conversation, Message, StudioBrief

IDEA_ACTION = "workflow_idea"
TELEGRAM_OPT_IN_ACTION = "workflow_telegram_opt_in"
STEP_LABELS = ("Idea & details", "Create a draft", "Review together", "Schedule & publish")


class WorkflowError(Exception):
    """An actionable message for the person controlling this workflow."""


class IdeaForm(forms.Form):
    request_id = forms.UUIDField(widget=forms.HiddenInput)
    idea = forms.CharField(
        label="What would you like to post?",
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "class": "workflow-idea-input",
                "placeholder": "Share an idea, a campaign goal, or a question your customers keep asking…",
            }
        ),
    )
    telegram_updates = forms.BooleanField(
        label="Send questions and draft updates to my paired Telegram account",
        required=False,
        initial=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.setdefault("request_id", uuid.uuid4())


def current_staff(workspace, user, *, locked=False):
    """Recheck actual membership and workspace availability, beyond cached request RBAC."""
    from apps.telegram.permissions import current_member, internal_member

    if not getattr(user, "pk", None):
        raise PermissionDenied("Sign in to continue your guided idea.")
    # One shared workspace -> organization -> actor -> role lock order with
    # the creative worker and task controls prevents competing pause/resume
    # requests from deadlocking a returning agent result.
    member = current_member(workspace, user, locked=locked)
    if (
        not internal_member(member)
        or not chat.is_staff_membership(member)
        or member.effective_permissions.get("create_posts") is not True
    ):
        raise PermissionDenied("Your current workspace permissions do not allow this workflow.")
    return member.workspace, member.user, member


@transaction.atomic
def save_idea(workspace, user, *, request_id, idea, telegram_updates=False):
    """Save without network/model work; a form's one-use ID makes duplicate submits harmless."""
    current, person, _member = current_staff(workspace, user, locked=True)
    try:
        identifier = uuid.UUID(str(request_id))
    except (TypeError, ValueError, AttributeError):
        raise WorkflowError("Refresh this page before saving your idea.") from None
    body = chat.clean_body(idea)
    if len(body) > 2000:
        raise WorkflowError("Keep your idea under 2,000 characters.")
    # The workspace lock serializes duplicate submissions. Returning an
    # existing thread is read-only; no extra conversation lock is needed.
    existing = Conversation.objects.filter(pk=identifier).first()
    if existing is not None:
        original = Message.objects.filter(conversation=existing, action=IDEA_ACTION).first()
        if (
            existing.workspace_id != current.pk
            or existing.created_by_id != person.pk
            or existing.audience != Conversation.Audience.INTERNAL
            or chat.is_private_conversation(existing)
            or original is None
            or original.author_id != person.pk
            or original.author_kind != Message.AuthorKind.STAFF
            or original.is_internal
            or original.body != body
            or existing.messages.filter(action=TELEGRAM_OPT_IN_ACTION, author=person, is_internal=True).exists()
            != (telegram_updates is True)
        ):
            raise WorkflowError("That form was already used. Refresh this page to save a new idea.")
        return existing
    conversation = Conversation.objects.create(
        id=identifier,
        workspace=current,
        audience=Conversation.Audience.INTERNAL,
        title=body[:160],
        created_by=person,
    )
    message = Message.objects.create(
        conversation=conversation,
        author=person,
        author_kind=Message.AuthorKind.STAFF,
        body=body,
        action=IDEA_ACTION,
        action_status=Message.ActionStatus.NEEDS_HUMAN,
    )
    conversation.last_message_at = message.created_at
    conversation.save(update_fields=["last_message_at"])
    if telegram_updates is True:
        Message.objects.create(
            conversation=conversation,
            author=person,
            author_kind=Message.AuthorKind.STAFF,
            is_internal=True,
            body="Send this idea’s questions and draft updates to my paired Telegram account. Replies to those messages may continue this shared workspace idea.",
            action=TELEGRAM_OPT_IN_ACTION,
            action_status=Message.ActionStatus.DONE,
        )
    return conversation


def validate_author(conversation, user, *, locked=False, require_telegram_opt_in=False):
    """A scoped original author for controlled Telegram continuations, never a private-thread alias."""
    workspace, person, member = current_staff(conversation.workspace, user, locked=locked)
    rows = Conversation.objects.select_for_update() if locked else Conversation.objects.all()
    current_thread = rows.filter(pk=conversation.pk, workspace_id=workspace.pk).first()
    if (
        current_thread is None
        or current_thread.audience != Conversation.Audience.INTERNAL
        or chat.is_private_conversation(current_thread)
    ):
        raise PermissionDenied("This guided idea is unavailable in this workspace.")
    messages = Message.objects.select_for_update() if locked else Message.objects.all()
    original = messages.filter(
        conversation=current_thread,
        action=IDEA_ACTION,
        author=person,
        author_kind=Message.AuthorKind.STAFF,
        is_internal=False,
    ).first()
    if original is None or current_thread.created_by_id != person.pk:
        raise PermissionDenied("Only the person who saved this idea can continue its guided brief.")
    if (
        require_telegram_opt_in
        and not messages.filter(
            conversation=current_thread,
            action=TELEGRAM_OPT_IN_ACTION,
            author=person,
            author_kind=Message.AuthorKind.STAFF,
            is_internal=True,
            action_status=Message.ActionStatus.DONE,
        ).exists()
    ):
        raise PermissionDenied("Telegram updates were not enabled for this idea.")
    return workspace, person, member, original


def workflow_threads(workspace):
    """Shared agency threads only; private Telegram history never enters this dashboard."""
    return (
        chat.web_conversations(workspace)
        .filter(audience=Conversation.Audience.INTERNAL, messages__action=IDEA_ACTION)
        .distinct()
    )


@dataclass(frozen=True)
class StartedIdea:
    conversation: Conversation
    job: AgencyJob | None
    note: str
    already_started: bool = False


@transaction.atomic
def start_idea(workspace, user, conversation_id, *, create=None, reference_id="", style_mode=""):
    """Dispatch once, under fresh scope/role locks. Paused and failed jobs keep their review path.

    The saved idea goes to the manager as the person's own words (``kind="create"``);
    ``create`` carries the idea form's structured choices (goal, direction,
    accounts) and ``reference_id`` / ``style_mode`` the photo and look, as
    fields of the brief.
    """
    current, person, _member = current_staff(workspace, user, locked=True)
    conversation = (
        Conversation.objects.select_for_update()
        .filter(pk=conversation_id, workspace_id=current.pk, audience=Conversation.Audience.INTERNAL)
        .first()
    )
    if conversation is None or chat.is_private_conversation(conversation):
        raise WorkflowError("That saved idea is unavailable in this workspace.")
    original = (
        Message.objects.select_for_update()
        .filter(
            conversation=conversation,
            action=IDEA_ACTION,
            author=person,
            author_kind=Message.AuthorKind.STAFF,
            is_internal=False,
        )
        .first()
    )
    if original is None or original.author_id != person.pk or conversation.created_by_id != person.pk:
        raise PermissionDenied("Only the person who saved this idea can start its guided brief.")
    # Any prior attempt is authoritative, including pause/cancellation or a
    # completed intake. A repeated click must not bypass reviewed job controls.
    previous = AgencyJob.objects.filter(workspace=current, conversation=conversation).order_by("created_at").first()
    if previous is not None:
        return StartedIdea(
            conversation, previous, "This idea already has saved work. Open its conversation to continue.", True
        )
    if not llm.is_configured():
        return StartedIdea(
            conversation,
            None,
            "Your idea is saved. The AI service needs administrator setup before guided drafting can start.",
        )
    refusal = chat.reply_refusal(current)
    if refusal:
        return StartedIdea(conversation, None, chat.refusal_text(current, refusal, audience=conversation.audience))
    posted = chat.post_message(
        conversation,
        person,
        original.body,
        kind="create",
        create=create,
        reference_id=reference_id,
        style_mode=style_mode,
    )
    if posted.job is not None:
        original.action_status = Message.ActionStatus.STARTED
        original.job = posted.job
        original.save(update_fields=["action_status", "job"])
    return StartedIdea(
        conversation, posted.job, posted.note or "Your manager is on it. The brief appears here in a moment."
    )


def _thread_url(workspace, conversation):
    return reverse("studio:thread", kwargs={"workspace_id": workspace.pk}) + f"?c={conversation.pk}"


def _steps(number, *, complete=False):
    return [
        {
            "number": index,
            "label": label,
            "state": "complete" if complete or index < number else "current" if index == number else "upcoming",
        }
        for index, label in enumerate(STEP_LABELS, 1)
    ]


def _journey(workspace, user, conversation, *, configured, spend_allowed):
    original = conversation.messages.filter(action=IDEA_ACTION).first()
    jobs = list(AgencyJob.objects.filter(workspace=workspace, conversation=conversation).order_by("-created_at")[:50])
    latest = jobs[0] if jobs else None
    briefs = list(
        chat.linked_briefs(conversation).exclude(status=StudioBrief.Status.DISCARDED).order_by("-created_at")[:20]
    )
    brief = briefs[0] if briefs else None
    thread_url = _thread_url(workspace, conversation)
    state, label, step = "saved", "Idea saved", 1
    action, action_url = "Start the guided brief", thread_url
    events = [
        {
            "label": "Idea saved",
            "created_at": original.created_at if original else conversation.created_at,
            "kind": "idea",
        }
    ]
    can_resume = bool(original and original.author_id == user.pk and not jobs and configured and spend_allowed)
    task = None
    if latest is not None:
        from .opendots import task_record

        task = task_record(latest)
        events.append({"label": "Guided brief requested", "created_at": latest.created_at, "kind": "brief"})
        if task["status"] == "paused":
            state, label = "paused", "Work paused"
            action = "Review and resume the saved task"
            action_url = reverse("studio:job", kwargs={"workspace_id": workspace.pk, "job_id": latest.pk})
        elif latest.status in AgencyJob.ACTIVE_STATUSES:
            state = "working" if latest.status == AgencyJob.Status.WORKING else "queued"
            label = "Preparing your brief" if state == "working" else "Waiting for the worker"
            action = "Open the conversation"
            if (latest.input or {}).get("kind") == "confirm_brief":
                step, label = 2, "Confirmed brief waiting for creation"
        elif latest.status == AgencyJob.Status.FAILED:
            state, label = "failed", "The team needs help"
            action = "Inspect the failed task before retrying"
            action_url = reverse("studio:job", kwargs={"workspace_id": workspace.pk, "job_id": latest.pk})
        elif latest.status == AgencyJob.Status.CANCELLED:
            state, label = "cancelled", "Request stopped"
            action = "Open the saved conversation"
        else:
            intake = creative_brief.latest_intake(conversation, original.author if original else user)
            if intake is not None and (intake.result or {}).get("awaiting_confirmation") is True:
                state, label = "needs_confirmation", "Check the brief before creation"
                action = "Review details and confirm the brief"
            else:
                state, label = "needs_input", "Waiting for your answer"
                action = "Answer the team’s questions"
    if not jobs and not configured:
        state, label = "blocked", "Saved; AI setup needed"
        action = "Open your saved idea"
    elif not jobs and not spend_allowed:
        state, label = "blocked", "Saved; AI budget needs attention"
        action = "Open your saved idea"
    if brief is not None:
        action_url = reverse("studio:detail", kwargs={"workspace_id": workspace.pk, "brief_id": brief.pk})
        rows = (
            list(brief.post.platform_posts.all()) if brief.post_id and brief.post.workspace_id == workspace.pk else []
        )
        statuses = {row.status for row in rows if row.social_account.workspace_id == workspace.pk}
        selected = set(brief.social_accounts.values_list("pk", flat=True))
        all_destinations_valid = (
            bool(rows)
            and bool(selected)
            and {row.social_account_id for row in rows} == selected
            and all(row.social_account.workspace_id == workspace.pk for row in rows)
        )
        publication_confirmed = all_destinations_valid and all(
            row.status == "published" and row.platform_post_id and row.published_at for row in rows
        )
        step = 2
        state, label, action = "working", "Creating your draft", "See the creative team’s progress"
        if brief.status == StudioBrief.Status.PLANNED:
            state, label, action = "planned", "Draft waiting its turn", "Open the planned draft"
        elif brief.status == StudioBrief.Status.FAILED:
            state, label, action = "failed", "Draft needs help", "Inspect the draft before retrying"
        elif brief.status in {StudioBrief.Status.READY, StudioBrief.Status.APPROVED}:
            step, state, label, action = 3, "review", "Your draft needs review", "Review the exact caption and visual"
            if "pending_client" in statuses:
                state, label, action = "client_review", "Waiting for client approval", "View the review status"
            elif "changes_requested" in statuses or "rejected" in statuses:
                label, action = "Changes requested", "Review the requested changes"
            elif "on_hold" in statuses:
                step, state, label, action = 4, "held", "Publishing is on hold", "Review the hold before continuing"
            elif "failed" in statuses:
                step, state, label, action = (
                    4,
                    "failed",
                    "Delivery needs inspection",
                    "Inspect delivery before retrying",
                )
            elif publication_confirmed:
                step, state, label, action = (
                    4,
                    "published",
                    "Published to every selected destination",
                    "See the delivery receipts",
                )
            elif statuses == {"published"}:
                step, state, label, action = (
                    4,
                    "held",
                    "Published status needs receipt verification",
                    "Inspect the saved receipts before treating delivery as complete",
                )
            elif "publishing" in statuses or "published" in statuses:
                step, state, label, action = (
                    4,
                    "delivering",
                    "Delivery is in progress",
                    "See each destination’s delivery status",
                )
            elif all_destinations_valid and statuses == {"scheduled"}:
                step, state, label, action = 4, "scheduled", "Scheduled; waiting for delivery", "View your schedule"
            elif all_destinations_valid and statuses <= {"approved", "scheduled"}:
                step, state, label, action = (
                    4,
                    "needs_schedule",
                    "Approved; schedule needs attention",
                    "Choose a publishing time",
                )
            if rows:
                from . import services

                if services.has_unconfirmed_delivery(brief):
                    step, state, label, action = (
                        4,
                        "held",
                        "Delivery outcome needs checking",
                        "Inspect the destination before retrying",
                    )
        events.append({"label": "Confirmed brief saved", "created_at": brief.created_at, "kind": "draft"})
        if brief.finished_at:
            events.append({"label": "Draft preparation finished", "created_at": brief.finished_at, "kind": "review"})
    return {
        "id": str(conversation.pk),
        "title": conversation.title,
        "current_step": step,
        "steps": _steps(step, complete=state == "published"),
        "state": state,
        "state_label": label,
        "next_action": action,
        "action_url": action_url,
        "action_label": {
            "saved": "Open your idea",
            "blocked": "Open your idea",
            "needs_input": "Answer questions",
            "needs_confirmation": "Check the brief",
            "review": "Review the draft",
            "client_review": "View review status",
            "held": "Inspect delivery",
            "failed": "Inspect the issue",
            "paused": "Review the paused task",
            "scheduled": "View the scheduled post",
            "needs_schedule": "Choose a time",
            "published": "View delivery receipts",
            "delivering": "View delivery status",
        }.get(state, "View the draft" if brief else "Open conversation"),
        "resume_url": reverse(
            "studio:workflow_resume", kwargs={"workspace_id": workspace.pk, "conversation_id": conversation.pk}
        ),
        "can_resume": can_resume,
        "events": events,
        "updated_at": max(
            [conversation.last_message_at or conversation.created_at] + [row.updated_at for row in jobs + briefs]
        ),
        "task": task,
    }


def context(workspace, user, *, form=None):
    """Read-only status for the launchpad and its polling fragment; no prompt or job is created."""
    from apps.telegram.models import TelegramConnection, TelegramUserLink

    from .readiness import operational_readiness

    current, person, member = current_staff(workspace, user)
    configured, spend_allowed = llm.is_configured(), budget.can_spend(current)
    journeys = [
        _journey(current, person, conversation, configured=configured, spend_allowed=spend_allowed)
        for conversation in workflow_threads(current)
        .select_related("workspace")
        .order_by("-last_message_at", "-created_at")[:30]
    ]
    connection = (
        TelegramConnection.objects.filter(workspace=current, is_active=True).only("id", "webhook_status").first()
    )
    paired = bool(
        connection and TelegramUserLink.objects.filter(connection=connection, user=person, is_active=True).exists()
    )
    telegram_ready = bool(connection and connection.webhook_status == "active" and paired)
    return {
        "workspace": current,
        "workflow_form": form or IdeaForm(),
        "journeys": journeys,
        "active": any(row["state"] in {"queued", "working", "delivering"} for row in journeys),
        # Waiting on a person is still a saved workflow. Read-only polling
        # observes later replies from Telegram or another tab without
        # creating reminders, model calls or a claim that a worker is busy.
        "polling": any(row["state"] not in {"blocked", "cancelled", "failed", "published", "held"} for row in journeys),
        "readiness": operational_readiness(current),
        "can_create": bool(member.effective_permissions.get("create_posts")),
        "telegram_url": reverse("telegram:settings", kwargs={"workspace_id": current.pk}),
        "telegram_state": "ready" if telegram_ready else "pairing_needed" if connection else "setup_needed",
        "telegram_label": "Your Telegram account is paired"
        if telegram_ready
        else "Pair your Telegram account"
        if connection
        else "Connect your Telegram bot",
        "telegram_description": "Requests and review updates can use your paired Telegram conversation. Channel delivery needs its own verified destination."
        if telegram_ready
        else "Connect the workspace bot, then pair your own account to receive updates and answer questions.",
        "tabs": dashboard.tabs(current, "workflow"),
        "tzname": current.effective_timezone or "UTC",
        "checked_at": timezone.now(),
    }
