"""Public marketing pages.

These are the pages a visitor sees before signing in: what the product does,
how it works, which platforms it connects to, the API / MCP surface, and how
to get started. They are plain server-rendered templates with no per-request
database work.

``home`` doubles as the site root. An anonymous visitor gets the landing
page; a signed-in user is handed to ``apps.accounts.views.dashboard`` exactly
as before, so ``LOGIN_REDIRECT_URL = "/"`` and every ``redirect("dashboard")``
in the app keep their behaviour.
"""

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.accounts.views import dashboard

SITE_NAME = "SM Bean"

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
]


def _page(request: HttpRequest, template: str, *, key: str, title: str, description: str, **extra) -> HttpResponse:
    context = {
        "site_name": SITE_NAME,
        "upstream_url": UPSTREAM_URL,
        "page_key": key,
        "page_title": title,
        "meta_description": description,
        "site_url": settings.APP_URL.rstrip("/"),
        "canonical_url": settings.APP_URL.rstrip("/") + request.path,
        "networks": NETWORKS,
        "platforms": PLATFORMS,
        **extra,
    }
    return render(request, template, context)


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
            "Compose once, schedule to 11 networks, run client approvals, answer every comment from one "
            "inbox and measure what worked."
        ),
    )


@require_GET
def features(request: HttpRequest) -> HttpResponse:
    return _page(
        request,
        "marketing/features.html",
        key="features",
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
        title="Supported platforms · SM Bean",
        description=(
            "Facebook, Instagram, LinkedIn, TikTok, YouTube, Pinterest, Threads, Bluesky, Google Business "
            "Profile, Mastodon and DEV.to, each through its official first-party API."
        ),
    )


@require_GET
def developers(request: HttpRequest) -> HttpResponse:
    return _page(
        request,
        "marketing/developers.html",
        key="developers",
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
        title="Get started · SM Bean",
        description=(
            "Create an account on the hosted app, or self-host SM Bean with Docker Compose, Railway, "
            "Render or Heroku. No per-seat, per-channel or per-workspace limits."
        ),
    )
