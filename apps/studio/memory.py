"""Creative memory: what the team learns from.

Two kinds of creative are remembered as :class:`~apps.studio.models.CreativeInsight` rows:

* **references** — creatives a person picked ("learn from this"): the best
  designer's work, uploaded or chosen from past posts;
* **best performers** — published posts with a picture, scored against their
  own account's other posts (see ``apps.studio.jobtypes.learn``, which keeps
  the rows fresh and has the creative memory curator describe them).

This module is the read side every agent uses. Nothing here calls a model.
"""

from __future__ import annotations

from typing import Any

from .models import CreativeInsight

#: How many references and best performers an agent is shown.
TOP_K = 6


def references(workspace, limit: int = TOP_K) -> list[CreativeInsight]:
    return list(
        CreativeInsight.objects.filter(workspace=workspace, is_reference=True)
        .select_related("media_asset")
        .order_by("-created_at")[:limit]
    )


def best_performers(workspace, limit: int = TOP_K, *, platforms: set[str] | None = None) -> list[CreativeInsight]:
    rows = CreativeInsight.objects.filter(workspace=workspace, score__isnull=False, is_reference=False)
    if platforms:
        rows = rows.filter(platform__in=platforms)
    return list(rows.select_related("media_asset").order_by("-score", "-published_at")[:limit])


def learning_set(workspace, limit: int = TOP_K, *, platforms: set[str] | None = None) -> list[CreativeInsight]:
    """References first, then the best performers, at most ``limit`` in all."""
    picked = references(workspace, limit)
    if len(picked) < limit:
        picked += best_performers(workspace, limit - len(picked), platforms=platforms)
    return picked


def _describe(insight: CreativeInsight) -> str:
    bits = []
    if insight.is_reference:
        bits.append("Reference picked by the team")
    elif insight.ratio:
        bits.append(f"{insight.ratio:.1f}× the account's usual result on {insight.platform or 'its network'}")
    look = (insight.description or "").strip()
    if not look:
        features = insight.features or {}
        look = ", ".join(str(features[key]) for key in ("template", "grade", "picture_style") if features.get(key))
    if look:
        bits.append(look)
    if insight.reference_note:
        bits.append(f"Note: {insight.reference_note}")
    return " — ".join(bits)


def prompt_memory(workspace, *, platforms: set[str] | None = None) -> dict[str, Any]:
    """What the prompt engineer and the art director start from."""
    from .brand_defaults import ensure_profile

    profile = ensure_profile(workspace)
    picked = learning_set(workspace, platforms=platforms)
    prompts = []
    for insight in picked:
        prompt = (insight.features or {}).get("picture_prompt")
        if prompt and prompt not in prompts:
            prompts.append(" ".join(str(prompt).split())[:600])
    return {
        "house_style": (profile.house_style or "").strip(),
        "references": [text for text in (_describe(i) for i in picked) if text],
        "prompts": prompts[:4],
    }


def reference_images(workspace, limit: int = 3, *, platforms: set[str] | None = None) -> list[bytes]:
    """Image bytes of the top references / best performers (for agents that look at them)."""
    from .style import read_asset

    images = []
    for insight in learning_set(workspace, limit * 2, platforms=platforms):
        if insight.media_asset is None:
            continue
        content = read_asset(insight.media_asset)
        if content:
            images.append(content)
        if len(images) >= limit:
            break
    return images


def winning_hooks(workspace, limit: int = 5) -> list[str]:
    """First lines of the best-performing captions, for the strategist and the copywriter."""
    hooks = []
    for insight in best_performers(workspace, limit * 2):
        first = (insight.caption or "").strip().splitlines()[0:1]
        if first and first[0] and first[0] not in hooks:
            ratio = f" ({insight.ratio:.1f}× usual)" if insight.ratio else ""
            hooks.append(f"{first[0][:200]}{ratio}")
        if len(hooks) >= limit:
            break
    return hooks
