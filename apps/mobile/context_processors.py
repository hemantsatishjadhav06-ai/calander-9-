"""Template data for the phone layout: which bottom tab is active, and the brand switcher.

The app bar, tab bar and sheets live in ``templates/mobile/partials`` and read
the counts the sidebar already computes (``sidebar_pending_approvals``,
``sidebar_unread_inbox_count``). The one extra lookup, each brand's channels
and approval count for the brand switcher, is lazy: it runs only when a page
actually renders the switcher.
"""

from django.utils.functional import SimpleLazyObject

# Namespaces whose pages belong under each bottom tab. Anything not listed
# (settings, members, notifications, blog, media, accounts, ...) sits under
# "More", the tab that links to it.
PUBLISH_NAMESPACES = {"calendar", "approvals", "composer"}
INBOX_NAMESPACES = {"inbox"}

#: The four tab roots. Every other page is "pushed" on top of one and gets a
#: back button instead of the brand switcher.
TAB_ROOTS = {("mobile", "today"), ("calendar", "calendar"), ("inbox", "feed"), ("mobile", "more")}

#: Full-screen tasks: no tab bar, a back button and a title instead.
TASK_TITLES = {
    ("mobile", "post"): "Post",
}
#: Pages that bring their own header and action bar (the composer): no app
#: bar and no tab bar on phones, so the page has the whole screen.
FULL_SCREEN = {("composer", "compose"), ("composer", "compose_edit")}


def active_tab(resolver_match):
    """Name of the bottom tab to highlight for a resolved URL ('' when none)."""
    if resolver_match is None:
        return ""
    namespace = resolver_match.namespace or ""
    url_name = resolver_match.url_name or ""
    if namespace == "mobile":
        return {"today": "today", "more": "more"}.get(url_name, "")
    if namespace in PUBLISH_NAMESPACES:
        return "publish"
    if namespace in INBOX_NAMESPACES:
        return "inbox"
    return "more"


def mobile_shell(request):
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return {}
    match = getattr(request, "resolver_match", None)
    key = ((match.namespace or ""), (match.url_name or "")) if match else ("", "")
    context = {
        "mobile_tab": active_tab(match),
        "mobile_is_root": key in TAB_ROOTS,
        "mobile_task_title": TASK_TITLES.get(key, ""),
        "mobile_full_screen": key in FULL_SCREEN,
    }
    if getattr(request, "workspace", None) is not None:
        brands = SimpleLazyObject(lambda: _brands(request))
        context["mobile_brands"] = brands
        context["mobile_brand"] = SimpleLazyObject(lambda: _current(request, brands))
    return context


def _brands(request):
    from apps.members.models import WorkspaceMembership

    from .services import brand_summaries

    workspaces = [
        m.workspace
        for m in WorkspaceMembership.objects.filter(user=request.user, workspace__is_archived=False)
        .select_related("workspace")
        .order_by("workspace__name")
    ]
    return brand_summaries(workspaces)


def _current(request, brands):
    for brand in brands:
        if brand["workspace"].id == request.workspace.id:
            return brand
    return {"workspace": request.workspace, "platforms": [], "pending": 0}
