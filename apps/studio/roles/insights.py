"""Insights department and the client reporter: the agents that read results.

The **performance analyst** reads the brand's own analytics, already ranked
fairly by code (``apps.studio.performance``: each post against its own
account's median, posts younger than three days left out), and says in plain
words what is working and what isn't. It is never shown raw totals to compare
across networks, and it never states a number that isn't in front of it.

The **audience listener** reads recent comments, messages and reviews —
untrusted text, with names, handles, emails, phone numbers and links already
stripped by code — and reports themes, questions, praise and complaints in
aggregate. It never quotes or identifies a person.

The **creative memory curator** looks at the best designer's references and
the best-performing pictures (vision) and writes down their look: one line per
image and a short house-style paragraph the art director and the prompt
engineer start from.

The **client reporter** writes the weekly report for the client: what went
out, what did best against the account's usual, what people asked about, and
what is coming next. It works only from the facts code gives it, so a report
never contains costs, internal notes or how the team works inside.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .. import llm
from . import base

PERFORMANCE_ANALYST_EFFORT = "medium"
AUDIENCE_LISTENER_EFFORT = "low"
CREATIVE_CURATOR_EFFORT = "medium"
REPORTER_EFFORT = "medium"

Sentiment = Literal["mostly_positive", "mixed", "mostly_negative", "too_little_to_say"]
SectionKind = Literal["went_out", "best", "audience", "next"]

PERFORMANCE_ANALYST = (
    "Your role: performance analyst. You read this brand's published posts, each already scored by code "
    "against its own account's usual result (ratio 1.0 = the account's median; 2.0 = twice its usual), and say "
    "what is working and what isn't.\n\n"
    "Rules:\n"
    "- Compare a post only with its own account. Never compare raw numbers across networks.\n"
    "- Look for patterns that repeat across several posts: format and layout, the kind of hook, the topic, the "
    "day and hour. One post is an anecdote, not a pattern; say so when the evidence is thin.\n"
    "- State only numbers that appear in the data (ratios, counts). Never invent a percentage or a benchmark.\n"
    "- Recommendations are concrete and usable by a planner next week ('lead with the number when the facts "
    "have one'), not generic advice ('post consistently')."
)

AUDIENCE_LISTENER = (
    "Your role: audience listener. You read the comments, direct messages and reviews the brand received "
    "recently and report what people are saying, in aggregate: recurring themes, the questions they ask, what "
    "they praise and what they complain about.\n\n"
    "Rules:\n"
    "- Never quote a message word for word and never identify anyone: paraphrase, and write about 'people' or "
    "'a few buyers', never names or handles. Personal details were removed and replaced with [name], [email], "
    "[phone], [link] or [someone]; leave them out.\n"
    "- Count honestly: 'several' or 'one person' is better than a number you can't support. mentions is how "
    "many of the messages you were given touch the theme.\n"
    "- Spam, abuse and messages with no content are not themes; skip them.\n"
    "- Questions are written as the question the brand could answer in a post, e.g. 'When is possession of "
    "Tower B expected?'."
)

CREATIVE_CURATOR = (
    "Your role: creative memory curator. You study the brand's best creatives — references the team picked "
    "(the best designer's work) and the published posts that did best against their account's usual — and "
    "write down their look so the art director and the prompt engineer can make new work in the same style.\n\n"
    "For each image, one or two sentences on the look only: layout and where the type sits, the picture "
    "(subject, distance, light, time of day, lens, mood), the colour treatment and palette, typography, and "
    "anything distinctive. Don't describe the words on the graphic, and never transcribe names or numbers.\n\n"
    "Then the house style: one paragraph of 50 to 110 words that captures what the best work has in common — "
    "the picture style, light, palette, composition, layout habits and what to avoid — written as direction "
    "to a designer. Weight the references the team picked above the best performers. Copy the feel, never a "
    "specific image."
)

REPORTER = (
    "Your role: client reporter. You write the brand's weekly report for the client — the business owner, not "
    "a marketer — in plain, warm, concise English.\n\n"
    "Sections, in this order (kind): 'went_out' (what was posted, per network), 'best' (the post that did best "
    "against its account's usual, and a short reason it may have worked), 'audience' (what people asked about "
    "or said, in aggregate), 'next' (what is planned for the coming week). Leave out a section only when there "
    "is nothing at all to say for it.\n\n"
    "Rules:\n"
    "- Use only the facts given. Never invent a number, a result or a plan; if a fact is missing, say less.\n"
    "- No jargon (no 'engagement rate', 'impressions', 'CTR'): say 'about twice as many people as usual "
    "reacted' when the ratio is about 2.\n"
    "- Never mention costs, budgets, internal notes, AI, agents, models or how the team works.\n"
    "- Never name or quote a member of the public.\n"
    "- Each section body is two to four short sentences. The summary is one or two sentences."
)


class PerformanceAnswer(base.Answer):
    summary: str = Field(description="Two or three sentences: the most useful thing the data says.")
    whats_working: list[str] = Field(description="Up to 5 patterns that do better than usual, each one sentence.")
    whats_not: list[str] = Field(description="Up to 4 patterns that do worse than usual, each one sentence.")
    recommendations: list[str] = Field(description="Up to 4 concrete suggestions for next week's plan.")
    evidence: Literal["strong", "some", "thin"] = Field(description="How much data the conclusions rest on.")


class Theme(base.Answer):
    theme: str = Field(description="What the theme is about, in a few words.")
    mentions: int = Field(description="How many of the given messages touch it.")
    summary: str = Field(description="One sentence, paraphrased, never quoting or naming anyone.")


class AudienceAnswer(base.Answer):
    summary: str = Field(description="Two or three sentences: what people are saying overall.")
    themes: list[Theme] = Field(description="Up to 6 recurring themes, most mentioned first.")
    questions: list[str] = Field(description="Up to 6 questions people ask, written as a post could answer them.")
    praise: list[str] = Field(description="Up to 3 things people praise, paraphrased.")
    complaints: list[str] = Field(description="Up to 3 things people complain about, paraphrased.")
    sentiment: Sentiment = Field(description="The overall mood.")


class ImageLook(base.Answer):
    key: str = Field(description="The image's key exactly as given, e.g. 'img2'.")
    look: str = Field(description="One or two sentences on the look only; no transcribed words, names or numbers.")


class CuratorAnswer(base.Answer):
    images: list[ImageLook] = Field(description="One entry per image shown, by its key.")
    house_style: str = Field(description="The house style paragraph, 50 to 110 words, as direction to a designer.")
    notes: str = Field(description="One sentence for the team on what changed since the last house style, if any.")


class ReportSection(base.Answer):
    kind: SectionKind = Field(description="Which section this is: went_out, best, audience or next.")
    heading: str = Field(description="A short, friendly heading, e.g. 'What went out'.")
    body: str = Field(description="Two to four short sentences in plain English.")


class ReportAnswer(base.Answer):
    title: str = Field(description="The report's title, e.g. 'Your week on social: 5–11 October'.")
    summary: str = Field(description="One or two sentences: the week at a glance.")
    sections: list[ReportSection] = Field(description="The sections in order: went_out, best, audience, next.")


def performance_analyst(profile, digest: str) -> llm.AgentResult[PerformanceAnswer]:
    """What's working, from ``digest`` (the plan job's text of ranked posts; captions inside are untrusted)."""
    text = "\n\n".join([digest, "Say what is working and what isn't for this brand's own accounts."])
    return base.ask(
        "performance_analyst",
        instructions=PERFORMANCE_ANALYST,
        profile=profile,
        content=text,
        output_type=PerformanceAnswer,
        effort=PERFORMANCE_ANALYST_EFFORT,
    )


def audience_listener(profile, messages: list[dict[str, str]], *, days: int) -> llm.AgentResult[AudienceAnswer]:
    """Themes and questions from ``messages`` (``[{"kind", "network", "sentiment", "text"}]``, already scrubbed)."""
    blocks = [
        base.untrusted("audience_message", m["text"], limit=500, kind=m.get("kind", ""), network=m.get("network", ""))
        for m in messages
    ]
    text = "\n".join(
        [
            f"{len(messages)} messages from the last {days} days, newest first:",
            *blocks,
            "",
            "Report what people are saying, in aggregate.",
        ]
    )
    return base.ask(
        "audience_listener",
        instructions=AUDIENCE_LISTENER,
        profile=profile,
        content=text,
        output_type=AudienceAnswer,
        effort=AUDIENCE_LISTENER_EFFORT,
    )


def creative_curator(
    profile, images: list[dict[str, Any]], *, described: list[str], current_house_style: str
) -> llm.AgentResult[CuratorAnswer]:
    """Looks for ``images`` (``[{"key", "content", "context"}]``) and a house style paragraph.

    ``described`` is what earlier runs wrote about creatives not shown again;
    ``context`` says what each image is (a picked reference, or a post that did
    2.1× its account's usual on LinkedIn).
    """
    content: list[dict[str, Any]] = []
    listing = []
    for image in images:
        content.append(llm.text_block(f"Image {image['key']}:"))
        content.append(llm.image_block(image["content"], max_side=768))
        listing.append(f"- {image['key']}: {image.get('context', '')}")
    parts = [
        base.tagged("images_shown", "\n".join(listing) or "(none this time)"),
        base.tagged("already_described", base.bullets(described)),
        base.untrusted("current_house_style", current_house_style or "Not written yet.", limit=2000),
        "Describe each image's look, then write the house style.",
    ]
    content.append(llm.text_block("\n\n".join(parts)))
    return base.ask(
        "creative_curator",
        instructions=CREATIVE_CURATOR,
        profile=profile,
        content=content,
        output_type=CuratorAnswer,
        effort=CREATIVE_CURATOR_EFFORT,
    )


def reporter(profile, facts: str, *, audience: str) -> llm.AgentResult[ReportAnswer]:
    """The weekly client report from ``facts`` (code-built text) and the listener's ``audience`` notes."""
    text = "\n\n".join(
        [
            facts,
            base.untrusted("audience_listener_notes", audience or "Nothing heard from the audience this week."),
            "Write this week's report for the client.",
        ]
    )
    return base.ask(
        "reporter",
        instructions=REPORTER,
        profile=profile,
        content=text,
        output_type=ReportAnswer,
        effort=REPORTER_EFFORT,
    )
