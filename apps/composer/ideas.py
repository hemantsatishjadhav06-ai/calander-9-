"""What the New post sheet's idea form offers (Phase 3, screen 1, T18).

*Save it as an idea instead* (``templates/composer/partials/new_post_idea.html``) lets a person pick
the column and, with the ``templates`` switch, the tags. Home and Calendar read them for whoever gets
the sheet (``apps.studio.views.can_start_posts``) and hand them to ``static/js/new-post-sheet.js``
through ``json_script``; ``sidebar_context`` read both on every render, fragments included, until
this moved here.
"""

from __future__ import annotations

from collections.abc import Sequence

from apps.common.features import request_features


def idea_columns(workspace) -> list[dict[str, str]]:
    """The workspace's idea columns in the board's order, ``{"id", "label"}`` each (one query)."""
    from apps.composer.models import IdeaGroup

    rows = IdeaGroup.objects.for_workspace(workspace.id).order_by("position", "created_at").values_list("id", "name")
    return [{"id": str(pk), "label": name} for pk, name in rows]


def idea_tags(workspace) -> list[str]:
    """The workspace's tag names, sorted as Calendar's tag filter and the form's script sort them (one
    query)."""
    from apps.composer.models import Tag

    return sorted(Tag.objects.for_workspace(workspace.id).values_list("name", flat=True))


def idea_form_context(request, workspace, *, tags: Sequence[str] | None = None) -> dict[str, list]:
    """``idea_columns``, and ``idea_tags`` with the ``templates`` switch (none without it: the form shows
    no tags then). A page that has already read the workspace's tag names passes them as *tags*, so the
    form costs no second read (Calendar's tag filter)."""
    context: dict[str, list] = {"idea_columns": idea_columns(workspace), "idea_tags": []}
    if request_features(request).get("templates"):
        context["idea_tags"] = list(tags) if tags is not None else idea_tags(workspace)
    return context
