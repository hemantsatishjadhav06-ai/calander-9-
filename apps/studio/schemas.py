"""What each agent must answer with.

These models are sent to Claude as the structured-output JSON schema
(``apps.studio.llm.run_agent``) and validate the answer that comes back. Every
field is required and objects forbid extra keys, as structured outputs expect.
Length and count limits live in the descriptions, not as schema constraints
(structured outputs cannot enforce them); the pipeline trims what it uses, and
the graphic designer fits whatever text it is given.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PostFormat = Literal["single_image", "stat", "quote", "tips", "announcement"]
Template = Literal["editorial", "split", "statement", "stat"]
Format = Literal["portrait", "square", "landscape"]
Grade = Literal["natural", "brand_tint", "duotone", "mono"]


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Concept(_Answer):
    title: str = Field(description="Working title for the angle, at most 10 words.")
    hook: str = Field(description="The post's first line exactly as a reader would see it; at most 125 characters.")
    angle: str = Field(description="What the post argues, teaches or shows, in one or two sentences.")
    key_points: list[str] = Field(description="Two to four points the post will make, each one short sentence.")
    post_format: PostFormat = Field(
        description=(
            "single_image: a picture with a headline. stat: built on one number that appears in the facts. "
            "quote: a point of view. tips: a short list or checklist. announcement: news."
        )
    )
    rationale: str = Field(description="Why this angle suits the audience and the goal, in one sentence.")
    recommended: bool = Field(description="True for exactly one concept: the one you would publish.")


class StrategistAnswer(_Answer):
    concepts: list[Concept] = Field(description="Exactly three concepts that differ in angle, not just wording.")


class CopyAnswer(_Answer):
    caption: str = Field(
        description=(
            "The full post text as plain text with line breaks, without hashtags. "
            "Hook first; 700 to 1,300 characters is the target, never above 2,800."
        )
    )
    hashtags: list[str] = Field(description="Three to five hashtags, each starting with #, no spaces.")
    first_comment: str = Field(
        description="A first comment to post under it, usually carrying the link. Empty string when not needed."
    )
    short_caption: str = Field(
        description="A version for short-form networks (X, Threads): at most 260 characters including any link."
    )
    alt_text: str = Field(description="Describes the graphic for screen-reader users, at most 250 characters.")
    headline: str = Field(description="Suggested headline for the graphic, at most 8 words.")
    subheadline: str = Field(description="Suggested supporting line for the graphic, at most 16 words.")
    kicker: str = Field(description="One to three words set above the headline, e.g. the topic. Upper or title case.")
    cta_label: str = Field(description="Call to action on the graphic, at most 5 words. Empty string for none.")
    stat_value: str = Field(
        description="For a stat post: the number exactly as stated in the facts, e.g. '8–14%'. Otherwise ''."
    )
    stat_label: str = Field(description="What the number means, at most 6 words. Empty string when stat_value is.")
    notes: str = Field(description="One sentence for the team: the approach you took, or what you changed.")


class DesignAnswer(_Answer):
    template: Template = Field(description="The layout. Must be the locked template when the style is locked.")
    format: Format = Field(description="The canvas. Must be the locked format when the style is locked.")
    grade: Grade = Field(description="Colour treatment of the picture. Must be the locked grade when locked.")
    use_picture: bool = Field(description="Whether the graphic uses a generated picture.")
    picture_style: str = Field(
        description=(
            "The picture style in one line that can be reused across posts: medium, light, lens, palette, mood. "
            "Keep the locked picture style word for word when the style is locked."
        )
    )
    picture_prompt: str = Field(
        description=(
            "Prompt for the image model when use_picture is true: subject, setting, composition, light, lens and "
            "mood in the brand's picture style, at most 110 words, describing no text of any kind. '' otherwise."
        )
    )
    kicker: str = Field(description="Final kicker for the graphic, one to three words.")
    headline: str = Field(description="Final headline for the graphic, within the template's word limit.")
    subheadline: str = Field(description="Final supporting line, within the template's word limit. May be ''.")
    stat_value: str = Field(description="For the stat template, the number from the facts. Otherwise ''.")
    stat_label: str = Field(description="For the stat template, what the number means. Otherwise ''.")
    cta_label: str = Field(description="Call to action on the graphic, at most 5 words, or ''.")
    overlay_strength: float = Field(
        description="How strongly the scrim darkens the picture behind the type, from 0.3 (light) to 0.9 (heavy)."
    )
    consistency_notes: str = Field(
        description="One or two sentences: what this graphic keeps from the previous post's look, and why."
    )
    design_rationale: str = Field(description="One sentence: why this visual carries this post's message.")


class ReviewCheck(_Answer):
    name: str = Field(description="What was checked, two to four words.")
    passed: bool
    note: str = Field(description="One short sentence; for a failed check, what exactly is wrong.")


class ReviewAnswer(_Answer):
    verdict: Literal["approve", "revise"] = Field(
        description=(
            "revise only for a problem a rewrite or redesign must fix: an unsupported claim, a broken brand or "
            "compliance rule, a weak or misleading hook, garbled or unreadable text, a clear break from the "
            "previous post's look. Otherwise approve."
        )
    )
    score: int = Field(description="Overall quality from 1 to 10.")
    checks: list[ReviewCheck] = Field(description="Five to eight checks covering facts, rules, copy and graphic.")
    risk_flags: list[str] = Field(description="Each statement that the facts or the brief do not support. [] if none.")
    copy_fixes: list[str] = Field(description="Specific instructions for the copywriter. [] if none.")
    design_fixes: list[str] = Field(description="Specific instructions for the art director. [] if none.")
    regenerate_picture: bool = Field(description="True when the picture itself is the problem.")
    summary: str = Field(description="Two sentences for the approver: what the post does and anything to watch.")
