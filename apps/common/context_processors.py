"""Context processors for sidebar and global template data."""

from django.conf import settings
from django.utils.functional import SimpleLazyObject

from apps.common import navigation
from apps.common.features import features_for, request_features


def branding(request):
    """Site name, support email, and legal URLs for every template.

    SUPPORT_EMAIL is deliberately NOT defaulted to DEFAULT_FROM_EMAIL: that is a
    no-reply sender, not a support channel, and falling back to it made every
    ``{% if SUPPORT_EMAIL %}`` guard true while pointing users at a black hole.
    Unset means unset, so templates can degrade honestly.
    """
    return {
        "SITE_NAME": getattr(settings, "SITE_NAME", "SM Bean"),
        "SUPPORT_EMAIL": getattr(settings, "SUPPORT_EMAIL", ""),
        "LEGAL_TERMS_URL": getattr(settings, "LEGAL_TERMS_URL", "/terms/"),
        "LEGAL_PRIVACY_URL": getattr(settings, "LEGAL_PRIVACY_URL", "/privacy/"),
        "SOURCE_URL": getattr(settings, "SOURCE_URL", ""),
        "LEGAL_ENTITY": getattr(settings, "LEGAL_ENTITY_NAME", "") or getattr(settings, "SITE_NAME", "SM Bean"),
        "LEGAL_UPDATED": getattr(settings, "LEGAL_UPDATED", ""),
        "LEGAL_PAGES_REVIEWED": getattr(settings, "LEGAL_PAGES_REVIEWED", False),
        # Public CTAs say "Get started" only when anyone can actually sign up.
        "SIGNUP_OPEN": getattr(settings, "SIGNUP_MODE", "invite_only") == "open",
        **_platform_availability(),
    }


def _platform_availability():
    """Display names of the platforms that are live, and of those coming soon.

    Instagram (Direct) and the two LinkedIn flavours collapse to one public name
    each: a visitor picks a network, not an OAuth variant.
    """
    from apps.credentials.models import PlatformCredential

    launched = set(getattr(settings, "LAUNCHED_PLATFORMS", []))
    live, soon = [], []
    for value, label in PlatformCredential.Platform.choices:
        name = {"instagram_login": "Instagram", "google_business": "Google Business"}.get(value, label)
        name = "LinkedIn" if value.startswith("linkedin") else name
        bucket = live if value in launched else soon
        if name not in live and name not in soon:
            bucket.append(name)
        elif name in soon and bucket is live:
            soon.remove(name)
            live.append(name)
    return {"LIVE_PLATFORM_NAMES": live, "COMING_SOON_PLATFORM_NAMES": soon}


def sidebar_context(request):
    """Inject sidebar data into every template context.

    Provides:
        sidebar_workspaces: list of workspace objects the user belongs to
        sidebar_unread_inbox_count, sidebar_pending_approvals: the badges
        sidebar_idea_columns, sidebar_idea_tags: the quick-create idea modal
        features: the current workspace's switches (``features_for``), read
            once per request and only when a template asks; every default,
            without a lookup, when there is no workspace
        nav, nav_palette: the navigation (``navigation.build_nav``) and the
            command palette's destinations (``navigation.build_palette``), built
            from these values when a template first reads them, so a page builds
            them once and an HTMX fragment, which never reads them, never does
    """
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return {}

    from apps.members.models import WorkspaceMembership
    from apps.social_accounts.models import AnalyticsPlatformConfig

    analytics_enabled_platforms = AnalyticsPlatformConfig.enabled_platforms()

    # User's workspaces (non-archived)
    workspace_memberships = (
        WorkspaceMembership.objects.filter(
            user=request.user,
            workspace__is_archived=False,
        )
        .select_related("workspace")
        .order_by("workspace__name")
    )
    sidebar_workspaces = [wm.workspace for wm in workspace_memberships]

    workspace = getattr(request, "workspace", None)

    # Unread inbox count for sidebar badge
    sidebar_unread_inbox_count = 0
    if workspace:
        from apps.inbox.models import InboxMessage

        sidebar_unread_inbox_count = (
            InboxMessage.objects.for_workspace(workspace.id).filter(status=InboxMessage.Status.UNREAD).count()
        )

    # Pending approval count for badge
    sidebar_pending_approvals = 0
    if workspace:
        from apps.composer.models import PlatformPost

        sidebar_pending_approvals = (
            PlatformPost.objects.filter(
                post__workspace_id=workspace.id,
                status__in=["pending_review", "pending_client"],
            )
            .values("post_id")
            .distinct()
            .count()
        )

    # Idea columns and tags for the quick-create modal in the sidebar
    sidebar_idea_columns = []
    sidebar_idea_tags = []
    if workspace:
        from apps.composer.models import IdeaGroup, Tag

        groups = IdeaGroup.objects.for_workspace(workspace.id).order_by("position", "created_at")
        sidebar_idea_columns = [{"id": str(g.id), "label": g.name} for g in groups] if groups.exists() else []
        sidebar_idea_tags = list(Tag.objects.for_workspace(workspace.id).values_list("name", flat=True))

    # Workspace creation permission (org owners and admins only)
    can_create_workspace = False
    org_membership = getattr(request, "org_membership", None)
    if org_membership and org_membership.org_role in ("owner", "admin"):
        can_create_workspace = True

    # Lazy: this runs on every render, HTMX fragments included, and most of
    # them never look at a switch.
    features = SimpleLazyObject(lambda: request_features(request)) if workspace else features_for(None)

    values = {
        "features": features,
        "sidebar_workspaces": sidebar_workspaces,
        "can_create_workspace": can_create_workspace,
        "sidebar_unread_inbox_count": sidebar_unread_inbox_count,
        "sidebar_pending_approvals": sidebar_pending_approvals,
        "sidebar_idea_columns": sidebar_idea_columns,
        "sidebar_idea_tags": sidebar_idea_tags,
        "analytics_enabled_platforms": analytics_enabled_platforms,
    }
    nav = SimpleLazyObject(lambda: navigation.build_nav(request, values))
    values["nav"] = nav
    values["nav_palette"] = SimpleLazyObject(lambda: navigation.build_palette(request, nav))
    return values
