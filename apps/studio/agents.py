"""The four Claude agents of the creative team.

Each function builds one agent's turn — its instructions and the brand block
as the (cached) system prompt, the brief-specific material as the user message
— and returns the validated answer from :func:`apps.studio.llm.run_agent`.
Images go before the text that refers to them. The pipeline decides when each
agent runs and what happens to its answer; nothing here touches the database.
"""

from __future__ import annotations

from typing import Any

from . import llm, prompts
from .schemas import CopyAnswer, DesignAnswer, ReviewAnswer, StrategistAnswer
from .style import StyleReference

# Effort per agent: strategy is where extra thinking pays off most; the others
# work from a clear angle and a clear spec.
STRATEGIST_EFFORT = "high"
COPYWRITER_EFFORT = "medium"
ART_DIRECTOR_EFFORT = "medium"
REVIEWER_EFFORT = "medium"


def strategist(brief, profile, recent: list[dict[str, str]]) -> llm.AgentResult[StrategistAnswer]:
    text = "\n\n".join(
        [
            prompts.brief_block(brief),
            prompts.recent_posts_block(recent),
            prompts.feedback_block(brief.feedback if brief.revision > 1 else "", [], "reviewer"),
            "Propose three angles for this post.",
        ]
    )
    return llm.run_agent(
        agent="strategist",
        system=prompts.system_blocks(prompts.STRATEGIST, profile),
        content=[llm.text_block(text.strip())],
        output_type=StrategistAnswer,
        effort=STRATEGIST_EFFORT,
    )


def copywriter(
    brief,
    profile,
    concept,
    recent: list[dict[str, str]],
    *,
    previous: dict[str, Any] | None = None,
    feedback: str = "",
    fixes: list[str] | None = None,
) -> llm.AgentResult[CopyAnswer]:
    parts = [prompts.brief_block(brief), prompts.concept_block(concept), prompts.recent_posts_block(recent)]
    if previous:
        parts.append(f"<previous_draft>\n{prompts.copy_block(previous)}\n</previous_draft>")
    guidance = prompts.feedback_block(feedback, fixes or [], "reviewer")
    if guidance:
        parts.append(guidance)
    parts.append(
        "Revise the previous draft: apply the feedback and fixes exactly and keep what nobody criticised."
        if previous and guidance
        else "Write the post for the chosen angle."
    )
    return llm.run_agent(
        agent="copywriter",
        system=prompts.system_blocks(prompts.COPYWRITER, profile),
        content=[llm.text_block("\n\n".join(parts))],
        output_type=CopyAnswer,
        effort=COPYWRITER_EFFORT,
    )


def _style_section(reference: StyleReference) -> str:
    if reference.kind == "studio":
        locked = reference.locked
        return (
            "<style_lock>\nThe look of the previous post is locked; image 1 is that post's graphic. Keep exactly:\n"
            f"template = {locked.get('template', '')}\nformat = {locked.get('format', '')}\n"
            f"grade = {locked.get('grade', '')}\npicture_style = {locked.get('picture_style', '')}\n"
            "Choose the words, the picture's subject and the scrim strength so this post reads as the next one "
            "in the same series.\n</style_lock>"
        )
    if reference.kind == "post":
        palette = ", ".join(reference.palette) or "unknown"
        return (
            "<style_reference>\nImage 1 is the picture of the brand's previous post. Match its look as closely as "
            "the layouts allow: choose the template, format and grade that fit it best and describe its kind of "
            f"picture in picture_style. Its main colours: {palette}.\n</style_reference>"
        )
    defaults = reference.defaults
    if reference.kind == "brand":
        return (
            "<style_defaults>\nThe brand has no previous post with a picture yet; this graphic sets the series' "
            f"look. Start from the defaults unless the angle clearly needs another layout: template = "
            f"{defaults.get('template')}, format = {defaults.get('format')}, grade = {defaults.get('grade')}, "
            f"picture style = {defaults.get('picture_style')}.\n</style_defaults>"
        )
    return (
        "<style_free>\nThe person asked for a fresh look: choose any layout, canvas and treatment that suits the "
        f"post, within the brand's colours and type. Brand defaults for reference: template = "
        f"{defaults.get('template')}, format = {defaults.get('format')}, grade = {defaults.get('grade')}.\n"
        "</style_free>"
    )


def art_director(
    brief,
    profile,
    concept,
    post_copy: dict[str, Any],
    reference: StyleReference,
    *,
    source_picture: bytes | None = None,
    previous: dict[str, Any] | None = None,
    feedback: str = "",
    fixes: list[str] | None = None,
) -> llm.AgentResult[DesignAnswer]:
    content: list[dict[str, Any]] = []
    image_number = 0
    reference_note = ""
    if reference.image is not None and reference.kind in ("studio", "post"):
        content.append(llm.image_block(reference.image))
        image_number += 1
    photo_note = ""
    if source_picture is not None:
        content.append(llm.image_block(source_picture))
        image_number += 1
        photo_note = (
            f"<supplied_photo>\nImage {image_number} is the photo the person chose for this post. Use it: set "
            "use_picture to true and picture_prompt to ''. Describe its look in picture_style.\n</supplied_photo>"
        )
    if reference.image is None and reference.kind in ("studio", "post"):
        reference_note = "(The previous post's image could not be loaded; follow the locked values.)"

    parts = [
        prompts.brief_block(brief),
        prompts.concept_block(concept),
        f"<copy>\n{prompts.copy_block(post_copy)}\n</copy>",
        _style_section(reference) + (f"\n{reference_note}" if reference_note else ""),
    ]
    if photo_note:
        parts.append(photo_note)
    if previous:
        parts.append(f"<previous_design>\n{prompts.design_block(previous)}\n</previous_design>")
    guidance = prompts.feedback_block(feedback, fixes or [], "reviewer")
    if guidance:
        parts.append(guidance)
    parts.append(
        "When the post names a specific project or property, don't depict it as if the picture were that "
        "building — choose a neutral scene (the area's skyline, an interior detail, a moment at home) unless a "
        "photo was supplied."
    )
    parts.append("Design the graphic." if not (previous and guidance) else "Revise the design as asked.")
    content.append(llm.text_block("\n\n".join(parts)))
    return llm.run_agent(
        agent="art_director",
        system=prompts.system_blocks(prompts.ART_DIRECTOR, profile),
        content=content,
        output_type=DesignAnswer,
        effort=ART_DIRECTOR_EFFORT,
    )


def reviewer(
    brief,
    profile,
    post_copy: dict[str, Any],
    spec: dict[str, Any],
    graphic: bytes,
    reference_image: bytes | None = None,
) -> llm.AgentResult[ReviewAnswer]:
    content: list[dict[str, Any]] = [llm.image_block(graphic)]
    images = "Image 1 is the finished graphic."
    if reference_image is not None:
        content.append(llm.image_block(reference_image))
        images += " Image 2 is the previous post's graphic, for the consistency check."
    text = "\n\n".join(
        [
            images,
            prompts.brief_block(brief),
            f"<copy>\n{prompts.copy_block(post_copy)}\n</copy>",
            prompts.design_block(spec),
            "Review the post.",
        ]
    )
    content.append(llm.text_block(text))
    return llm.run_agent(
        agent="reviewer",
        system=prompts.system_blocks(prompts.REVIEWER, profile),
        content=content,
        output_type=ReviewAnswer,
        effort=REVIEWER_EFFORT,
    )
