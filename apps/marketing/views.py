"""Public marketing pages.

Three pages are linked during the invite-only beta: Home, How it works and
Request invite. Features, Platforms, Developers and Get started keep rendering
for old links and bookmarks, but nothing links to them and they carry
``noindex``; ``/pricing/`` answers 301 to Request invite. The pages are plain
server-rendered templates with no per-request database work, except the
Request invite form's POST.

``home`` doubles as the site root. An anonymous visitor gets the landing
page; a signed-in user is handed to ``apps.accounts.views.dashboard`` exactly
as before, so ``LOGIN_REDIRECT_URL = "/"`` and every ``redirect("dashboard")``
in the app keep their behaviour.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods
from django_ratelimit.decorators import ratelimit

from apps.accounts.models import User
from apps.accounts.views import dashboard
from apps.common.mail import send_or_raise
from apps.common.net import ratelimit_client_ip
from apps.notifications.engine import notify
from apps.notifications.models import EventType

from .forms import RequestInviteForm

logger = logging.getLogger(__name__)

# Per client IP, counted on POST only. Generous enough for an agency's whole
# office behind one address, small enough that a script cannot fill the
# operators' inboxes (each request mails every operator).
REQUEST_INVITE_RATE = "10/h"

# The open-source codebase this product is built on. Shown in the footer
# because the AGPL-3.0 licence asks derived works to keep that notice visible.
UPSTREAM_URL = "https://github.com/brightbeanxyz/brightbean-studio"

# Per-platform capability matrix, mirroring the README's "Supported Platforms"
# table. ``icon`` is the key understood by ``partials/_platform_icon.html``.
PLATFORMS = [
    {
        "name": "Facebook",
        "icon": "facebook",
        "scope": "Pages",
        "publish": True,
        "comments": True,
        "dms": True,
        "insights": True,
    },
    {
        "name": "Instagram",
        "icon": "instagram",
        "scope": "Business & Creator accounts, via Facebook Login",
        "publish": True,
        "comments": True,
        "dms": True,
        "insights": True,
    },
    {
        "name": "Instagram (Direct)",
        "icon": "instagram",
        "scope": "Professional accounts, no Facebook Page required",
        "publish": True,
        "comments": True,
        "dms": True,
        "insights": True,
    },
    {
        "name": "LinkedIn (Personal)",
        "icon": "linkedin",
        "scope": "Personal profiles",
        "publish": True,
        "comments": True,
        "dms": False,
        "insights": True,
    },
    {
        "name": "LinkedIn (Company)",
        "icon": "linkedin",
        "scope": "Company pages",
        "publish": True,
        "comments": True,
        "dms": False,
        "insights": True,
    },
    {
        "name": "TikTok",
        "icon": "tiktok",
        "scope": "Video content",
        "publish": True,
        "comments": False,
        "dms": False,
        "insights": True,
    },
    {
        "name": "YouTube",
        "icon": "youtube",
        "scope": "Videos & Shorts",
        "publish": True,
        "comments": True,
        "dms": False,
        "insights": True,
    },
    {
        "name": "Pinterest",
        "icon": "pinterest",
        "scope": "Pins & boards",
        "publish": True,
        "comments": False,
        "dms": False,
        "insights": True,
    },
    {
        "name": "Threads",
        "icon": "threads",
        "scope": "Text & media",
        "publish": True,
        "comments": True,
        "dms": False,
        "insights": True,
    },
    {
        "name": "Bluesky",
        "icon": "bluesky",
        "scope": "AT Protocol, connects with an app password",
        "publish": True,
        "comments": True,
        "dms": False,
        "insights": False,
    },
    {
        "name": "Google Business Profile",
        "icon": "google_business",
        "scope": "Local posts",
        "publish": True,
        "comments": False,
        "dms": False,
        "insights": True,
    },
    {
        "name": "Mastodon",
        "icon": "mastodon",
        "scope": "Any instance, registers its own app on connect",
        "publish": True,
        "comments": True,
        "dms": False,
        "insights": False,
    },
    {
        "name": "DEV.to",
        "icon": "devto",
        "scope": "Articles, connects with an API key",
        "publish": True,
        "comments": False,
        "dms": False,
        "insights": False,
    },
    {
        # Publish-only on purpose: X's API is pay-per-use, so inbox polling and
        # analytics sync would spend the app owner's credits unattended.
        "name": "X (Twitter)",
        "icon": "x",
        "scope": "Posts only. X's API is pay-per-use, billed to your developer account",
        "publish": True,
        "comments": False,
        "dms": False,
        "insights": False,
    },
]

# Distinct networks for the logo strip on the home page (one entry per icon).
NETWORKS = [
    ("Facebook", "facebook"),
    ("Instagram", "instagram"),
    ("LinkedIn", "linkedin"),
    ("TikTok", "tiktok"),
    ("YouTube", "youtube"),
    ("Pinterest", "pinterest"),
    ("Threads", "threads"),
    ("Bluesky", "bluesky"),
    ("Google Business", "google_business"),
    ("Mastodon", "mastodon"),
    ("DEV.to", "devto"),
    ("X", "x"),
]


def _page(
    request: HttpRequest,
    template: str,
    *,
    key: str,
    title: str,
    description: str,
    noindex: bool = False,
    status: int = 200,
    **extra,
) -> HttpResponse:
    launched = set(getattr(settings, "LAUNCHED_PLATFORMS", []))
    context = {
        "site_name": getattr(settings, "SITE_NAME", "SM Bean"),
        "upstream_url": UPSTREAM_URL,
        "source_url": settings.SOURCE_URL,
        "page_key": key,
        "page_title": title,
        "meta_description": description,
        "site_url": settings.APP_URL.rstrip("/"),
        "canonical_url": settings.APP_URL.rstrip("/") + request.path,
        "networks": NETWORKS,
        # "live" = usable on the hosted app today; the rest ship in the code but
        # wait on the platform approving our developer app (QA round 1, BUG-22).
        "platforms": [{**p, "live": p["icon"] in launched} for p in PLATFORMS],
        # Pages kept for old links but no longer linked ask search engines to drop them.
        "noindex": noindex,
        **extra,
    }
    return render(request, template, context, status=status)


@require_GET
def home(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return dashboard(request)
    return _page(
        request,
        "marketing/home.html",
        key="home",
        title="SM Bean · Plan, approve and publish social content from one calendar",
        description=(
            "SM Bean is a social media management studio for creators, agencies and small teams. "
            "Compose once, schedule to every channel you connect, run client approvals, answer comments "
            "from one inbox and measure what worked."
        ),
    )


@require_GET
def pricing(request: HttpRequest) -> HttpResponse:
    """The beta has no plans to pick: old pricing links land on Request invite.

    The ``pricing`` URL name stays (``{% url 'pricing' %}`` must keep resolving);
    ``templates/pricing.html`` is kept, unused.
    """
    return redirect("marketing:request_invite", permanent=True)


@require_http_methods(["GET", "POST"])
@ratelimit(key=ratelimit_client_ip, rate=REQUEST_INVITE_RATE, method="POST", block=False)
def request_invite(request: HttpRequest) -> HttpResponse:
    """A short form that asks the platform operators for an invitation.

    Each submission makes one ``invite_requested`` notification for every
    active staff user; with none, one email goes to ``SUPPORT_EMAIL``. A filled
    honeypot gets the same thank-you page and nothing is sent. The requester's
    words are untrusted: they are stored and shown escaped, and never reach a
    prompt or Telegram (``apps.telegram.notifications.notification_event`` has
    no branch for this event type).
    """
    form = RequestInviteForm(request.POST if request.method == "POST" else None)
    sent = False
    problem = ""
    status = 200
    if request.method == "POST":
        if getattr(request, "limited", False):
            problem = "too_many"
            status = 429
        elif form.is_bot:
            sent = True
        elif form.is_valid():
            if _pass_on_invite_request(form.cleaned_data):
                sent = True
            else:
                problem = "unavailable"
                status = 503
    return _page(
        request,
        "marketing/request_invite.html",
        key="request_invite",
        title="Request invite · SM Bean",
        description="SM Bean is in a private beta for agencies. Tell us who you are and we will reply by email.",
        status=status,
        form=form,
        sent=sent,
        problem=problem,
    )


def _pass_on_invite_request(data: dict) -> bool:
    """Notify every active operator, else mail the support address. False if nobody could be told."""
    name, agency, email, note = data["name"], data["agency"], data["email"], data.get("note", "")
    title = f"Invite request from {name} ({agency})"
    lines = [f"{name} at {agency} asked for an invite.", f"Email: {email}"]
    if note:
        lines.append(f"Note: {note}")
    body = "\n".join(lines)

    operators = list(User.objects.filter(is_staff=True, is_active=True).order_by("pk"))
    if operators:
        for operator in operators:
            notify(operator, EventType.INVITE_REQUESTED, title, body)
        return True

    support = getattr(settings, "SUPPORT_EMAIL", "")
    if not support:
        logger.error("An invite request arrived but there is no active staff user and no SUPPORT_EMAIL to receive it.")
        return False
    message = EmailMessage(
        subject=" · ".join((title, getattr(settings, "SITE_NAME", "SM Bean"))),
        body=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=[support],
        reply_to=[email],
    )
    try:
        send_or_raise(message)
    except Exception as exc:
        # The class name only: a mail error can quote the message back, and the message is the requester's.
        logger.error("An invite request could not be mailed to the support address (%s).", type(exc).__name__)
        return False
    return True


@require_GET
def features(request: HttpRequest) -> HttpResponse:
    return _page(
        request,
        "marketing/features.html",
        key="features",
        noindex=True,
        title="Features · SM Bean",
        description=(
            "Everything in SM Bean: the composer, calendar and queues, approval workflows, client portal, "
            "unified inbox, analytics, media library, teams and white-label branding."
        ),
    )


@require_GET
def how_it_works(request: HttpRequest) -> HttpResponse:
    return _page(
        request,
        "marketing/how_it_works.html",
        key="how_it_works",
        title="How it works · SM Bean",
        description=(
            "From connecting an account to reading the numbers: how SM Bean plans, approves, schedules, "
            "publishes and monitors content, and what the publishing engine does under the hood."
        ),
    )


@require_GET
def platforms(request: HttpRequest) -> HttpResponse:
    return _page(
        request,
        "marketing/platforms.html",
        key="platforms",
        noindex=True,
        title="Supported platforms · SM Bean",
        description=(
            "Which networks SM Bean publishes to today, which are coming as each platform approves our app, "
            "and what every integration can do through its official first-party API."
        ),
    )


@require_GET
def developers(request: HttpRequest) -> HttpResponse:
    return _page(
        request,
        "marketing/developers.html",
        key="developers",
        noindex=True,
        title="API & MCP for agents · SM Bean",
        description=(
            "A REST API and an MCP server with the same keys, permissions, rate limits and audit log, "
            "so scripts and AI agents can create, schedule and measure posts."
        ),
        api_base_url=settings.APP_URL.rstrip("/") + "/api/v1",
    )


@require_GET
def get_started(request: HttpRequest) -> HttpResponse:
    return _page(
        request,
        "marketing/get_started.html",
        key="get_started",
        noindex=True,
        title="Get started · SM Bean",
        description=(
            "Create an account on the hosted app, or self-host SM Bean with Docker Compose, Railway, "
            "Render or Heroku. No per-seat, per-channel or per-workspace limits."
        ),
    )
