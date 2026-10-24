"""Set up: one checklist in plain words, with live state and one button per row.

``/workspace/<id>/studio/setup/`` is the only page that names a setting or a
service. Everyone on the team sees the same rows in words; organisation
owners and superusers also see the exact names they have to set. The two
actions here change settings only ("Use me as lead", "Turn on autopilot with
sensible defaults"): nothing is approved, scheduled or published, and the
approval gate stays exactly where it is.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import budget, dashboard, images, llm, readiness, trust
from .forms import studio_accounts
from .forms_agency import WEEKDAYS, eligible_leads
from .models import AgencySettings, AgentRun
from .views import _perms, _workspace

#: The weekday and hour the planner runs when autopilot is switched on from here.
DEFAULT_PLAN_WEEKDAY = 4
DEFAULT_PLAN_HOUR = 16
DEFAULT_POSTS_PER_WEEK = 5

ASK_OWNER = "Ask your owner."
#: "Your manager" is the AI account manager everywhere else, so a person with the settings permission is named by it.
SETTINGS_PERSON = "someone who manages this workspace's settings"


def is_owner(user, workspace) -> bool:
    """Someone who may see what exactly has to be set: a superuser or an owner of the organisation."""
    from apps.members.models import OrgMembership

    if getattr(user, "is_superuser", False):
        return True
    return OrgMembership.objects.filter(
        user=user, organization_id=workspace.organization_id, org_role=OrgMembership.OrgRole.OWNER
    ).exists()


def _url(name: str, **kwargs) -> str:
    try:
        return reverse(name, kwargs=kwargs)
    except NoReverseMatch:
        return ""


def _link(label: str, url: str) -> dict[str, str] | None:
    return {"label": label, "url": url, "method": "get"} if url else None


def _post(label: str, url: str, **fields: str) -> dict[str, Any] | None:
    """A one-button POST; ``fields`` travel as hidden inputs (a mode, a return address)."""
    return {"label": label, "url": url, "method": "post", "fields": fields} if url else None


def _row(key, title, state, status, *, action=None, detail="", note="", link=None) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "state": state,  # done | todo | attention
        "status": status,
        "action": action,
        "detail": detail,  # owners only: the exact names to set
        "note": note,
        "link": link,  # optional standalone link under the status (a place to see the result)
    }


def _ai_team_row(owner: bool) -> dict[str, Any]:
    if llm.is_configured():
        return _row("ai_team", "AI team", "done", "Connected. Your team can plan, write and design.")
    provider = llm.provider_name()
    key_name = "OPENROUTER_API_KEY" if provider == "openrouter" else "ANTHROPIC_API_KEY"
    detail = ""
    if owner:
        detail = (
            f"Set STUDIO_PROVIDER (anthropic or openrouter) and {key_name} on the web and worker services."
            if provider not in {"anthropic", "openrouter"}
            else f"Set {key_name} on the web and worker services."
        )
    return _row(
        "ai_team",
        "AI team",
        "todo",
        "Not connected yet. Nothing can be written or planned until it is.",
        detail=detail,
        note="" if owner else ASK_OWNER,
    )


def _pictures_row(owner: bool) -> dict[str, Any]:
    if images.is_configured():
        return _row("pictures", "Pictures", "done", "Pictures are generated for every post.")
    return _row(
        "pictures",
        "Pictures",
        "todo",
        "Not set up. The team uses the photo you send, or the brand background.",
        detail="Set FAL_KEY on the web and worker services." if owner else "",
        note="" if owner else ASK_OWNER,
    )


def _accounts_row(workspace) -> dict[str, Any]:
    accounts = studio_accounts(workspace)
    broken = [a for a in accounts if a.needs_reconnect or not a.account_platform_id]
    if not accounts:
        return _row(
            "accounts",
            "Social accounts",
            "todo",
            "No social account yet. Posts need somewhere to go.",
            action=_link("Connect", _url("social_accounts:connect", workspace_id=workspace.pk)),
        )
    names = ", ".join(sorted({a.get_platform_display() for a in accounts}))
    if broken:
        return _row(
            "accounts",
            "Social accounts",
            "attention",
            f"{len(accounts)} connected ({names}) · {len(broken)} need{'s' if len(broken) == 1 else ''} reconnecting.",
            action=_link("Reconnect", _url("social_accounts:list", workspace_id=workspace.pk)),
        )
    return _row(
        "accounts",
        "Social accounts",
        "done",
        f"{len(accounts)} connected: {names}.",
        action=_link("Manage", _url("social_accounts:list", workspace_id=workspace.pk)),
    )


def _advanced_url(workspace) -> str:
    """The Autopilot page opened on its Advanced section, where the approvers and the budget live."""
    url = _url("studio:autopilot", workspace_id=workspace.pk)
    return url + dashboard.ADVANCED_OPEN if url else ""


def _approvers_row(request, workspace, row: AgencySettings, can_manage: bool) -> dict[str, Any]:
    leads = {user.pk for user, _role in eligible_leads(workspace)}
    eligible = request.user.pk in leads
    autopilot_url = _advanced_url(workspace)
    # A saved lead who left the team or lost the rights is no lead: the row and the button agree on that.
    if row.lead is not None and row.lead_id in leads:
        backup = row.backup.display_name if row.backup is not None else ""
        status = f"Lead: {row.lead.display_name}" + (f" · Backup: {backup}" if backup else " · No backup yet")
        return _row(
            "approvers",
            "Approvers",
            "done",
            status + ".",
            action=_link("Change", autopilot_url) if can_manage else None,
        )
    status = "No lead approver yet. Drafts the team makes on its own carry the lead's name."
    if eligible:
        return _row(
            "approvers",
            "Approvers",
            "todo",
            status,
            action=_post("Use me as lead", _url("studio:setup_lead", workspace_id=workspace.pk)),
        )
    if can_manage:
        return _row("approvers", "Approvers", "todo", status, action=_link("Choose a lead", autopilot_url))
    return _row("approvers", "Approvers", "todo", status, note=f"Ask {SETTINGS_PERSON} to choose one.")


def _weekday_name(index: int) -> str:
    return dict(WEEKDAYS).get(index, "Friday")


def _autopilot_row(workspace, row: AgencySettings, can_manage: bool) -> dict[str, Any]:
    autopilot_url = _url("studio:autopilot", workspace_id=workspace.pk)
    if row.pk and row.autopilot_enabled:
        n = row.posts_per_week
        return _row(
            "autopilot",
            "Autopilot",
            "done",
            f"On · {n} post{'s' if n != 1 else ''} a week, planned every {_weekday_name(row.plan_weekday)} "
            f"at {row.plan_hour:02d}:00. Every post still waits for your approval.",
            action=_link("Change", autopilot_url),
            link=_link("See your team at work", _url("studio:team", workspace_id=workspace.pk)),
        )
    status = "Off. The team only works when someone asks it to."
    if can_manage:
        return _row(
            "autopilot",
            "Autopilot",
            "todo",
            status,
            action=_post("Turn on with sensible defaults", _url("studio:setup_autopilot", workspace_id=workspace.pk)),
            note="5 posts a week on your connected accounts, planned on Fridays at 16:00. You can change it after.",
        )
    return _row("autopilot", "Autopilot", "todo", status, note=f"Ask {SETTINGS_PERSON} to turn it on.")


def _creation_mode_row(workspace, row: AgencySettings, can_manage: bool) -> dict[str, Any]:
    """How a team member's idea starts: after a tap on the brief card, or at once. Always a chosen state."""
    auto = row.creation_mode == AgencySettings.CreationMode.AUTO
    if auto:
        status = (
            "Just go ahead: your manager starts a team member's idea at once, with sensible defaults. "
            "The finished post still waits for your approval."
        )
        other_label, other_mode = "Switch to “Ask me first”", AgencySettings.CreationMode.CONFIRM
    else:
        status = (
            "Ask me first: your manager shows the brief and waits for your tap. "
            "Clients always confirm, whichever you choose."
        )
        other_label, other_mode = "Switch to “Just go ahead”", AgencySettings.CreationMode.AUTO
    action = None
    if can_manage:
        action = _post(
            other_label,
            _url("studio:creation_mode", workspace_id=workspace.pk),
            mode=other_mode,
            next=_url("studio:setup", workspace_id=workspace.pk),
        )
    return _row(
        "creation_mode",
        "Creation mode",
        "done",
        status,
        action=action,
        note="" if can_manage else f"Ask {SETTINGS_PERSON} to change it.",
    )


def telegram_deployment_ready() -> bool:
    """The deployment can receive Telegram updates (a public https origin, switched on)."""
    from apps.telegram.state import deployment_ready

    return deployment_ready()


def _telegram_row(request, workspace, owner: bool) -> dict[str, Any]:
    telegram_url = _url("telegram:settings", workspace_id=workspace.pk)
    state = readiness.telegram_state(workspace, request.user)
    if state["state"] == "deployment_needed":
        return _row(
            "telegram",
            "Telegram",
            "todo",
            "The deployment isn't ready for Telegram yet.",
            action=_link("Open Telegram", telegram_url),
            detail="Set TELEGRAM_WEBHOOK_READY=true and TELEGRAM_WEBHOOK_BASE_URL to the public https origin "
            "on the web and worker services."
            if owner
            else "",
            note="" if owner else ASK_OWNER,
        )
    if state["state"] == "setup_needed":
        return _row(
            "telegram",
            "Telegram",
            "todo",
            "Deployment ready. Connect your bot, then pair your phone.",
            action=_link("Connect your bot", telegram_url),
        )
    if state["state"] == "pairing_needed":
        return _row(
            "telegram",
            "Telegram",
            "todo",
            f"Bot connected as {state['bot']}. Pair your phone to talk to your team from Telegram.",
            action=_link("Pair your phone", telegram_url),
        )
    return _row(
        "telegram",
        "Telegram",
        "done",
        f"Listening as {state['bot']} · you're paired.",
        action=_link("Open Telegram", telegram_url),
    )


def email_state() -> dict[str, Any]:
    """Can this instance send email, in words. No network."""
    from apps.common.models import OutboundMailbox

    backend = getattr(django_settings, "EMAIL_BACKEND_TYPE", "") or ""
    if not getattr(django_settings, "EMAIL_SENDING_ENABLED", True):
        return {"ok": False, "status": "Email sending is switched off for now."}
    if backend == "console":
        return {"ok": False, "status": "Email is only written to the log, not sent."}
    if backend == "gmail_api":
        mailbox = OutboundMailbox.objects.order_by("-connected_at").first()
        if mailbox is not None:
            return {"ok": True, "status": f"Sending as {mailbox.email}."}
        if getattr(django_settings, "GMAIL_REFRESH_TOKEN", ""):
            return {"ok": True, "status": "Sending through the connected Gmail account."}
        return {"ok": False, "status": "Gmail isn't connected yet, so invitations and alerts can't be sent."}
    if backend == "smtp":
        host = getattr(django_settings, "EMAIL_HOST", "") or ""
        if host in ("", "localhost", "127.0.0.1"):
            return {"ok": False, "status": "No email server yet, so invitations and alerts can't be sent."}
        return {"ok": True, "status": f"Sending through {host}."}
    return {"ok": False, "status": "Email isn't set up."}


def _email_row(request, owner: bool) -> dict[str, Any]:
    state = email_state()
    action = _link("Email settings", _url("ops_email")) if getattr(request.user, "is_superuser", False) else None
    return _row(
        "email",
        "Email",
        "done" if state["ok"] else "todo",
        state["status"],
        action=action,
        detail="" if state["ok"] or not owner else "Set EMAIL_BACKEND_TYPE (gmail_api or smtp) and its settings.",
        note="" if state["ok"] or owner else ASK_OWNER,
    )


def _facts_row(workspace) -> dict[str, Any]:
    count = trust.current_claims(workspace).count()
    trust_url = _url("studio:trust", workspace_id=workspace.pk)
    if count:
        return _row(
            "facts",
            "Verified facts",
            "done",
            f"{count} fact{'s' if count != 1 else ''} verified. The team only uses these for prices, "
            "availability and dates.",
            action=_link("Review", trust_url),
        )
    return _row(
        "facts",
        "Verified facts",
        "todo",
        "No verified facts yet. Until then the team avoids prices, availability and dates.",
        action=_link("Verify facts", trust_url),
    )


def _blog_row(workspace, owner: bool) -> dict[str, Any]:
    from apps.blog.models import BlogSite

    site = BlogSite.objects.filter(workspace=workspace).select_related("search_console").order_by("name").first()
    if site is None:
        return _row(
            "blog",
            "Blog website",
            "todo",
            "No website connected. Articles need a site to be published on.",
            detail="Connect one from the server with `python manage.py ensure_blog_sites`." if owner else "",
            note="" if owner else ASK_OWNER,
        )
    try:
        console = site.search_console
    except Exception:
        console = None
    if console is None:
        return _row(
            "blog",
            "Blog website",
            "attention",
            f"{site.name} connected · Search Console not connected, so rankings aren't read yet.",
            action=_link(
                "Connect Search Console",
                _url("blog:search_console_connect", workspace_id=workspace.pk, site_id=site.pk),
            ),
        )
    return _row(
        "blog",
        "Blog website",
        "done",
        f"{site.name} connected · Search Console connected.",
        action=_link("Open Blog & SEO", _url("blog:list", workspace_id=workspace.pk)),
    )


def _budget_row(workspace, can_manage: bool) -> dict[str, Any]:
    spend = budget.month_spend(workspace)
    limit = budget.monthly_budget(workspace)
    reported = AgentRun.objects.filter(
        workspace=workspace, started_at__gte=budget.month_start(workspace), output__has_key="provider_cost_usd"
    ).exists()
    qualifier = "" if reported else " (estimated)"
    action = _link("Change", _advanced_url(workspace)) if can_manage else None
    if not budget.can_spend(workspace):
        return _row(
            "budget",
            "Monthly AI budget",
            "attention",
            f"${spend:.2f} of ${limit:.2f} used this month{qualifier}. The team starts no new work until "
            "it is raised or the month turns.",
            action=action,
        )
    return _row(
        "budget",
        "Monthly AI budget",
        "done",
        f"${spend:.2f} of ${limit:.2f} used this month{qualifier}.",
        action=action,
    )


def checklist(request, workspace) -> dict[str, Any]:
    """Every row of the Set up page, with how many are done."""
    owner = is_owner(request.user, workspace)
    can_manage = bool(_perms(request).get("manage_workspace_settings"))
    row = AgencySettings.objects.filter(workspace=workspace).select_related("lead", "backup").first() or AgencySettings(
        workspace=workspace
    )
    rows = [
        _ai_team_row(owner),
        _pictures_row(owner),
        _accounts_row(workspace),
        _approvers_row(request, workspace, row, can_manage),
        _autopilot_row(workspace, row, can_manage),
        _creation_mode_row(workspace, row, can_manage),
        _telegram_row(request, workspace, owner),
        _email_row(request, owner),
        _facts_row(workspace),
        _blog_row(workspace, owner),
        _budget_row(workspace, can_manage),
    ]
    done = sum(1 for r in rows if r["state"] == "done")
    return {"rows": rows, "done": done, "total": len(rows), "left": len(rows) - done, "owner": owner}


def status_line(request, workspace, *, steps_left: int) -> list[dict[str, str]]:
    """The one line under the Home greeting: set-up, autopilot, Telegram.

    Each part may carry a link, and only to something this person can do:
    an editor is not sent to connect a bot they cannot connect.
    """
    parts: list[dict[str, str]] = []
    setup_url = _url("studio:setup", workspace_id=workspace.pk)
    if steps_left:
        parts.append(
            {
                "text": f"Set-up: {steps_left} step{'s' if steps_left != 1 else ''} left",
                "link": "Open Set up",
                "url": setup_url,
            }
        )
    can_manage = bool(_perms(request).get("manage_workspace_settings"))
    row = AgencySettings.objects.filter(workspace=workspace).only("autopilot_enabled", "posts_per_week").first()
    if row is not None and row.autopilot_enabled:
        parts.append({"text": f"Autopilot on · {row.posts_per_week} a week", "link": "", "url": ""})
    elif can_manage:
        parts.append(
            {"text": "Autopilot off", "link": "Turn on", "url": _url("studio:autopilot", workspace_id=workspace.pk)}
        )
    else:
        parts.append({"text": "Autopilot off", "link": "", "url": ""})
    telegram = readiness.telegram_state(workspace, request.user)
    telegram_url = _url("telegram:settings", workspace_id=workspace.pk)
    if telegram["state"] == "ready":
        parts.append({"text": telegram["label"], "link": "", "url": ""})
    elif telegram["state"] == "pairing_needed":
        parts.append(
            {"text": f"Telegram: listening as {telegram['bot']}", "link": "pair your phone", "url": telegram_url}
        )
    elif telegram["state"] == "deployment_needed":
        owner = is_owner(request.user, workspace)
        parts.append(
            {"text": telegram["label"], "link": "Open Set up" if owner else "", "url": setup_url if owner else ""}
        )
    elif can_manage:
        parts.append({"text": "Telegram", "link": "connect your bot", "url": telegram_url})
    else:
        parts.append({"text": "Telegram: ask your owner to connect the bot", "link": "", "url": ""})
    return parts


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@login_required
@require_GET
def setup(request, workspace_id):
    workspace = _workspace(request, workspace_id)
    progress = checklist(request, workspace)
    response = render(
        request,
        "studio/setup.html",
        {
            "workspace": workspace,
            "checked_at": timezone.now(),
            "tzname": workspace.effective_timezone or "UTC",
            **progress,
        },
    )
    response["Cache-Control"] = "no-store, private"
    return response


@login_required
@require_GET
def settings_hub(request, workspace_id):
    workspace = _workspace(request, workspace_id)
    return render(
        request,
        "studio/settings_hub.html",
        {
            "workspace": workspace,
            "cards": dashboard.settings_cards(workspace),
            "tabs": dashboard.tabs(workspace, "settings", perms=_perms(request)),
            "setup_url": _url("studio:setup", workspace_id=workspace.pk),
        },
    )


# ---------------------------------------------------------------------------
# Actions (settings only; nothing is approved, scheduled or published here)
# ---------------------------------------------------------------------------


def _back(workspace):
    return redirect("studio:setup", workspace_id=workspace.pk)


@login_required
@require_POST
def use_me_as_lead(request, workspace_id):
    """Make the person the lead approver, when they may carry the team's drafts in their name."""
    workspace = _workspace(request, workspace_id)
    leads = {user.pk for user, _role in eligible_leads(workspace)}
    if request.user.pk not in leads:
        raise PermissionDenied("Only someone who creates and approves posts here can be the lead.")
    row, _created = AgencySettings.objects.get_or_create(workspace=workspace)
    # The same rule as the Set up row: a saved lead who is no longer eligible counts as no lead.
    current_lead = row.lead_id if row.lead_id in leads else None
    if current_lead and current_lead != request.user.pk and not _perms(request).get("manage_workspace_settings"):
        raise PermissionDenied(f"Someone else is the lead. Only {SETTINGS_PERSON} can change it.")
    row.lead = request.user
    row.save(update_fields=["lead", "updated_at"])
    messages.success(request, "You are the lead approver. Drafts the team makes on its own carry your name.")
    return _back(workspace)


@login_required
@require_POST
def autopilot_defaults(request, workspace_id):
    """Switch autopilot on with sensible defaults, or say exactly what is still missing."""
    workspace = _workspace(request, workspace_id)
    if not _perms(request).get("manage_workspace_settings"):
        raise PermissionDenied(f"Only {SETTINGS_PERSON} can turn autopilot on.")
    row, _created = AgencySettings.objects.get_or_create(workspace=workspace)
    leads = {user.pk for user, _role in eligible_leads(workspace)}
    # The lead stays whoever was chosen, as long as they still qualify; the presser only fills an empty seat.
    lead_id = row.lead_id if row.lead_id in leads else request.user.pk if request.user.pk in leads else None
    accounts = [a for a in studio_accounts(workspace) if not a.needs_reconnect and a.account_platform_id]
    missing = []
    if lead_id is None:
        missing.append("a lead approver (someone who creates and approves posts)")
    if not accounts:
        missing.append("a connected social account")
    if missing:
        messages.error(request, "Autopilot stays off. Still missing: " + " and ".join(missing) + ".")
        return _back(workspace)
    row.lead_id = lead_id
    row.autopilot_enabled = True
    row.posts_per_week = row.posts_per_week or DEFAULT_POSTS_PER_WEEK
    row.plan_weekday = DEFAULT_PLAN_WEEKDAY
    row.plan_hour = DEFAULT_PLAN_HOUR
    row.save(update_fields=["lead", "autopilot_enabled", "posts_per_week", "plan_weekday", "plan_hour", "updated_at"])
    row.accounts.set(accounts)
    messages.success(
        request,
        f"Autopilot is on: {row.posts_per_week} posts a week, planned every "
        f"{_weekday_name(row.plan_weekday)} at {row.plan_hour:02d}:00. Every post still waits for your approval.",
    )
    return _back(workspace)
