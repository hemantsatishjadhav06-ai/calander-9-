"""Publishing department: the community manager and the reviews manager.

Both draft replies a person sends — never the agents. The **community
manager** answers comments, mentions and direct messages; the **reviews
manager** answers reviews and flags the unhappy ones (one or two stars, anger,
a complaint that needs action) so a person sees them first.

Everything they read was written by the public, so every message goes to the
model as untrusted text. Each message is given a short reference (``m1``,
``m2``…); an answer can only point at one of those references, and the job
maps it back to the message it gave — a reply can never land on a message the
model wasn't shown.
"""

from __future__ import annotations

from pydantic import Field

from .. import llm
from . import base

COMMUNITY_MANAGER_EFFORT = "low"
REPUTATION_MANAGER_EFFORT = "low"
REPLIES_MAX_TOKENS = 12000

_REPLY_RULES = (
    "How to write a reply:\n"
    "- In the brand's voice, short and human: one to three sentences, no hashtags, no Markdown, at most one "
    "emoji and only if the brand's voice uses them.\n"
    "- Answer the person's actual point. Thank them when it fits, without gushing.\n"
    "- State only facts from the brand facts. If they ask something the facts don't answer (a price, "
    "availability, a date), invite them to get in touch using the contact details in the brand facts, or say the "
    "team will follow up — never invent an answer.\n"
    "- Never argue, never blame the customer, never share private details in public, never promise refunds, "
    "compensation or outcomes.\n"
    "- Write in the language the person wrote in.\n"
    "- Spam, abuse or messages that need no reply: set skip to true and leave the reply empty.\n"
    "These are drafts: a person reads, edits and sends each one."
)

COMMUNITY_MANAGER = (
    "Your role: community manager. You draft replies to comments, mentions and direct messages the brand "
    "received. Each message in <messages> has a reference like m1; answer each one by its reference.\n\n"
    + _REPLY_RULES
    + "\n\nSet needs_person to true when the message is a complaint, a safety or legal issue, a sales enquiry worth "
    "a call, or anything a person should handle themselves."
)

REPUTATION_MANAGER = (
    "Your role: reviews manager. You draft replies to the brand's public reviews. Each review in <reviews> has a "
    "reference like m1 and, when known, its star rating; answer each one by its reference.\n\n"
    + _REPLY_RULES
    + "\n\nFor reviews:\n"
    "- Thank happy reviewers specifically for what they mentioned.\n"
    "- For unhappy ones: acknowledge, apologise for the experience without admitting fault on specifics, and "
    "invite them to continue privately using the contact details in the brand facts.\n"
    "- Set urgent to true for one- or two-star reviews, angry reviews, and any review that mentions safety, "
    "fraud, legal action or a problem someone must fix — a person sees those first."
)


class DraftReply(base.Answer):
    ref: str = Field(description="The message's reference exactly as given, e.g. m1.")
    reply: str = Field(description="The draft reply; empty when skip is true.")
    skip: bool = Field(description="True for spam, abuse or messages that need no reply.")
    needs_person: bool = Field(description="True when a person should handle this one themselves.")
    reason: str = Field(description="A few words for the team: why skipped or why a person should look.")


class CommunityAnswer(base.Answer):
    replies: list[DraftReply] = Field(description="One entry per message given, by reference.")
    notes: str = Field(description="One sentence for the team: what people are saying overall.")


class ReviewReply(base.Answer):
    ref: str = Field(description="The review's reference exactly as given, e.g. m1.")
    reply: str = Field(description="The draft reply; empty when skip is true.")
    skip: bool = Field(description="True for spam or reviews that need no reply.")
    urgent: bool = Field(description="True for 1–2 stars, anger, or anything a person must deal with.")
    reason: str = Field(description="A few words for the team on why it is urgent or skipped.")


class ReviewsAnswer(base.Answer):
    replies: list[ReviewReply] = Field(description="One entry per review given, by reference.")
    notes: str = Field(description="One sentence for the team: what reviewers are saying overall.")


def _listing(items: list[dict]) -> str:
    """Each message as a short header (trusted: from our database) and its text (untrusted)."""
    blocks = []
    for item in items:
        header = f"{item['ref']} · {item['kind']} on {item['platform']}"
        if item.get("rating"):
            header += f" · {item['rating']} star(s)"
        if item.get("age"):
            header += f" · {item['age']}"
        parts = [header, base.untrusted("public_message", item["body"], limit=1500, sender=item.get("sender", ""))]
        if item.get("post_caption"):
            parts.append(base.untrusted("our_post_it_replies_to", item["post_caption"], limit=600))
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks)


def community_manager(profile, messages: list[dict]) -> llm.AgentResult[CommunityAnswer]:
    """Draft replies to comments, mentions and messages.

    ``messages`` is ``[{"ref", "kind", "platform", "sender", "body", "age", "post_caption"}]``.
    """
    text = "\n\n".join(
        [base.tagged("messages", _listing(messages)), "Draft a reply for each message, by its reference."]
    )
    return base.ask(
        "community_manager",
        instructions=COMMUNITY_MANAGER,
        profile=profile,
        content=text,
        output_type=CommunityAnswer,
        effort=COMMUNITY_MANAGER_EFFORT,
        max_tokens=REPLIES_MAX_TOKENS,
    )


def reputation_manager(profile, reviews: list[dict]) -> llm.AgentResult[ReviewsAnswer]:
    """Draft replies to reviews and flag the urgent ones. Same item shape as :func:`community_manager`, plus ``rating``."""
    text = "\n\n".join([base.tagged("reviews", _listing(reviews)), "Draft a reply for each review, by its reference."])
    return base.ask(
        "reputation_manager",
        instructions=REPUTATION_MANAGER,
        profile=profile,
        content=text,
        output_type=ReviewsAnswer,
        effort=REPUTATION_MANAGER_EFFORT,
        max_tokens=REPLIES_MAX_TOKENS,
    )
