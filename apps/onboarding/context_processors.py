"""Context processor for onboarding checklist popup."""

from apps.onboarding.checklist import get_checklist_items
from apps.onboarding.models import OnboardingChecklist


def onboarding_checklist(request):
    """Inject onboarding checklist data into every template context."""
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return {}

    workspace = getattr(request, "workspace", None)
    if not workspace:
        return {}

    checklist_dismissed = OnboardingChecklist.objects.filter(
        user=request.user, workspace=workspace, is_dismissed=True
    ).exists()

    if checklist_dismissed:
        return {"checklist_dismissed": True, "checklist_items": []}

    checklist_items = _cached_checklist_items(workspace)
    completed_count = sum(1 for item in checklist_items if item["completed"])
    total_count = len(checklist_items)

    # Don't show if all items are complete
    if completed_count == total_count:
        return {"checklist_dismissed": True, "checklist_items": []}

    return {
        "checklist_items": checklist_items,
        "checklist_dismissed": False,
        "checklist_completed_count": completed_count,
        "checklist_total_count": total_count,
    }


# The checklist is evaluated for the sidebar on every authenticated page, and
# each evaluation is four existence queries. Its answers change a handful of
# times in a workspace's life, so a minute's staleness costs nothing.
CHECKLIST_CACHE_SECONDS = 60


def _cached_checklist_items(workspace):
    from django.core.cache import cache

    key = f"onboarding_checklist:{workspace.id}"
    items = cache.get(key)
    if items is None:
        items = get_checklist_items(workspace)
        cache.set(key, items, CHECKLIST_CACHE_SECONDS)
    return items
