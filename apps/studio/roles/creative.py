"""Creative department: the prompt engineer and the channel editor.

The **prompt engineer** turns the art director's picture direction into the
prompt the image model gets. It works from the brand's house style (written
by the creative memory curator from the best designer's references and the
best-performing posts), the prompts behind the best past pictures, and what
the image model needs to see: subject first, then setting, composition, light,
lens and palette, with calm space where the type will sit and nothing that
reads as text.

The **channel editor** writes the version of a post each network needs. The
copywriter writes for LinkedIn and X; Instagram, Facebook, Google Business,
Threads, Pinterest and TikTok captions read differently (hashtags, length,
links that don't click), so the post going there gets its own text.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .. import llm
from . import base

PROMPT_ENGINEER_EFFORT = "medium"
CHANNEL_EDITOR_EFFORT = "low"

#: Networks the copywriter's own text already fits (LinkedIn) or that use its short version (X).
COPYWRITER_PLATFORMS = frozenset({"linkedin_personal", "linkedin_company", "x", "bluesky", "mastodon"})

PROMPT_ENGINEER = (
    "Your role: prompt engineer for the image model (a FLUX text-to-image model on fal.ai). The art director has "
    "chosen the layout and described the picture. You write the prompt that gets that picture on the first try, "
    "in the brand's house style.\n\n"
    "How to write it:\n"
    "- Lead with the subject in plain words, then the setting, composition and camera position, light and time "
    "of day, lens and depth of field, palette and mood. Concrete nouns beat adjectives.\n"
    "- Match the house style and the reference descriptions you are given: the same kind of light, palette, "
    "distance and mood, so the feed reads as one series. Copy the feel, never a specific earlier image.\n"
    "- Leave calm, uncluttered space where the type sits (described in <type_area>).\n"
    "- Never describe text, letters, numbers, signage, logos, watermarks, UI or captions; never ask for a real "
    "named building, person or brand to be depicted as if it were the real one.\n"
    "- People, if any, are small or seen from behind; no close-up faces, no hands holding things up to camera.\n"
    "- 60 to 120 words, one paragraph, no lists, no quotation marks, no negative-prompt syntax.\n\n"
    "Also give the short style line that should stay the same across the series (picture_style), and say in one "
    "sentence what you took from the references."
)

CHANNEL_EDITOR = (
    "Your role: channel editor. The copywriter wrote the post for LinkedIn. You write the version each other "
    "network in <destinations> needs, saying the same thing with the same facts.\n\n"
    "Per network:\n"
    "- instagram: the hook in the first 125 characters, short lines, a clear call to action; links don't click, "
    "so say 'link in bio' or give the phone number; up to 5 relevant hashtags at the end.\n"
    "- facebook: conversational, 1–3 short paragraphs; a link may stay in the text; 0–2 hashtags.\n"
    "- google_business: an update for people searching locally, 2–4 plain sentences ending with the call to "
    "action; no hashtags; at most 1,400 characters.\n"
    "- threads: under 480 characters, conversational, at most 1 hashtag.\n"
    "- pinterest: a keyword-rich description under 450 characters, no hashtags.\n"
    "- tiktok: a short caption under 300 characters with up to 4 hashtags.\n"
    "- anything else: a plain, short version.\n"
    "No Markdown, no emoji rows. Return one version for each destination you are given, and nothing else."
)


class PromptAnswer(base.Answer):
    prompt: str = Field(description="The image prompt: one paragraph, 60 to 120 words, describing no text of any kind.")
    picture_style: str = Field(
        description="The reusable style line for the series: medium, light, lens, palette, mood."
    )
    references_used: str = Field(description="One sentence: what this prompt takes from the references and best posts.")


class ChannelVersion(base.Answer):
    platform: str = Field(description="The destination's platform key exactly as given in <destinations>.")
    caption: str = Field(description="The full text for that network, hashtags included where the network uses them.")


class ChannelAnswer(base.Answer):
    versions: list[ChannelVersion] = Field(description="One version per destination given.")
    notes: str = Field(description="One sentence for the team on what changed between networks.")


def _type_area(spec: dict[str, Any]) -> str:
    template = spec.get("template", "editorial")
    return {
        "editorial": "The lower third and lower left carry the headline over a dark scrim: keep them calm.",
        "split": "The picture fills the top part only; keep the subject in the upper two thirds.",
        "statement": "The picture sits faint behind bold type: keep it simple, low contrast, few details.",
        "stat": "A strip of picture under a big number: a wide, calm scene with the subject centred.",
    }.get(template, "Keep calm space where the type sits.")


def prompt_engineer(
    profile, spec: dict[str, Any], memory: dict[str, Any], *, reference_images: list[bytes] | None = None
) -> llm.AgentResult[PromptAnswer]:
    """The image prompt for ``spec`` (the art director's design), in the brand's house style.

    ``memory`` is ``apps.studio.memory.prompt_memory(...)``: the house style, the
    descriptions of the best references, and prompts behind the best pictures.
    """
    content: list[dict[str, Any]] = []
    images = reference_images or []
    for image in images[:3]:
        content.append(llm.image_block(image, max_side=768))
    parts = []
    if images:
        parts.append(f"Images 1–{min(len(images), 3)} are the brand's best creatives, for the feel only.")
    parts += [
        base.tagged("direction_from_art_director", spec.get("picture_prompt", "")),
        base.tagged("art_director_style_line", spec.get("picture_style", "")),
        base.tagged("layout", f"{spec.get('template', '')}, {spec.get('format', '')}, grade {spec.get('grade', '')}"),
        base.tagged("type_area", _type_area(spec)),
        base.tagged(
            "house_style", memory.get("house_style", "") or "Not written yet; follow the brand's picture style."
        ),
        base.tagged("best_references", base.bullets(memory.get("references", []))),
        base.tagged("prompts_behind_the_best_pictures", base.bullets(memory.get("prompts", []))),
        "Write the image prompt.",
    ]
    content.append(llm.text_block("\n\n".join(parts)))
    return base.ask(
        "prompt_engineer",
        instructions=PROMPT_ENGINEER,
        profile=profile,
        content=content,
        output_type=PromptAnswer,
        effort=PROMPT_ENGINEER_EFFORT,
    )


def channel_editor(
    profile, post_copy: dict[str, Any], destinations: list[dict[str, str]]
) -> llm.AgentResult[ChannelAnswer]:
    """Per-network versions of the copywriter's post. ``destinations`` is ``[{"platform", "name"}]``."""
    caption = (post_copy.get("caption") or "").strip()
    tags = " ".join(post_copy.get("hashtags") or [])
    listing = "\n".join(f"- {d['platform']}: {d.get('name', '')}" for d in destinations)
    text = "\n\n".join(
        [
            base.tagged("linkedin_post", caption),
            base.tagged("hashtags", tags),
            base.tagged("first_comment", post_copy.get("first_comment", "")),
            base.tagged("destinations", listing),
            "Write the version for each destination.",
        ]
    )
    return base.ask(
        "channel_editor",
        instructions=CHANNEL_EDITOR,
        profile=profile,
        content=text,
        output_type=ChannelAnswer,
        effort=CHANNEL_EDITOR_EFFORT,
    )
