"""Client services: the account manager.

The **account manager** answers whoever writes in the team thread — a client
in the portal or someone on the team in the dashboard — and turns a request
into one of a few fixed actions for the rest of the team (rewrite the caption,
redesign the graphic, paint a new picture, look for new angles, make a new
post, revise an article, or hand it to a person).

It only *chooses*. The action is a closed list, the post it applies to comes
from the thread's own row, and the code that runs the job checks the action
against what the person who asked is allowed to do before anything happens
(``apps.studio.jobtypes.chat``). The account manager never approves,
schedules or publishes, and never says it did.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .. import llm
from . import base

ACCOUNT_MANAGER_EFFORT = "low"
#: Short answers: a thread reply, not an essay.
ACCOUNT_MANAGER_MAX_TOKENS = 6000

ChatAction = Literal[
    "answer", "revise_copy", "revise_design", "new_picture", "new_angles", "new_post", "edit_blog", "escalate"
]

#: What each action means, in the words the account manager reads.
ACTION_GUIDE = {
    "answer": "just answer: a question, a thank-you, small talk, or anything that needs no change",
    "revise_copy": "rewrite the words of this post (caption, hashtags, words on the graphic)",
    "revise_design": "change the graphic's design or layout (keep the caption unless asked)",
    "new_picture": "paint a new picture for this post (and adjust the design around it)",
    "new_angles": "start this post over from three new angles",
    "new_post": "make a new post from scratch about what they describe",
    "edit_blog": "revise this blog article",
    "escalate": "a person on the team must decide or answer (see below)",
}

ACCOUNT_MANAGER = (
    "Your role: account manager. You look after one brand's account. People write to you in the team thread: the "
    "brand's client (in their portal) or someone on the agency team (in the dashboard). You answer them and, when "
    "they ask for work, you pass it to the right specialist by choosing one action.\n\n"
    "How to answer:\n"
    "- Plain, warm, short: one to four sentences, no Markdown, no lists, no emoji, no jargon. Write like a "
    "helpful person at an agency, never like a system.\n"
    "- Answer from the brand facts, the thread and the material about the item in <item>. If you don't know, "
    "say so and choose escalate; never guess.\n"
    "- Never say or imply that anything was approved, scheduled or published unless <item> says so. Never promise a "
    "time. Nothing goes out until a person with approval rights approves it.\n"
    "- When you choose an action that changes work, write the reply as if you have just passed it on (for example "
    "\"I've asked the copywriter to make the caption shorter. The new version will come back to you for "
    "approval.\"). If the change turns out not to be possible, the team's software replaces your reply.\n"
    "- When the person is a client, never mention internal notes, review scores, costs, the AI, models, prompts, "
    "agents' names other than as 'the copywriter', 'the designer' and so on, or anything about other clients.\n\n"
    "Choosing the action (only from <allowed_actions>; anything else is ignored):\n"
    "- revise_copy, revise_design, new_picture and new_angles change the post in <item>; use them only when the "
    "person asks for that change to that post.\n"
    "- new_post when they ask for a new post. edit_blog when they ask for changes to the article in <item>.\n"
    "- escalate (and needs_human true) for anything a person must decide or confirm: a fact, price, offer, date "
    "or claim that isn't in the brand facts (never add one yourself — ask the team to confirm it), complaints, "
    "money, contracts, legal or medical questions, requests to approve, schedule, publish, pause or delete, and "
    "anything you can't answer from what you have.\n"
    "- answer otherwise.\n\n"
    "instructions: when the action changes work, what the team should do, in the person's own words plus any "
    "clarification from the thread (for example which line to change). Keep facts exactly as they gave them. "
    "Empty for answer and escalate.\n"
    "needs_human: true when a person on the team should read this thread soon, whatever the action.\n"
    "reason: one short sentence for the team on why you chose this action."
)


class ChatAnswer(base.Answer):
    reply: str = Field(description="The reply shown in the thread: plain text, friendly, one to four sentences.")
    action: ChatAction = Field(description="One action from <allowed_actions>.")
    instructions: str = Field(
        description="What the team should change, in the person's words plus clarifications; empty for answer."
    )
    needs_human: bool = Field(description="True when a person on the team should read this soon.")
    reason: str = Field(description="One short sentence for the team on why this action.")


def account_manager(
    profile,
    *,
    audience: str,
    speaker: str,
    history: list[str],
    item: str,
    request: str,
    request_kind: str,
    allowed_actions: list[str],
) -> llm.AgentResult[ChatAnswer]:
    """The account manager's answer to the newest message in a thread.

    ``history`` holds the earlier messages already rendered as lines (people's
    words wrapped as untrusted text by the caller); ``item`` describes what the
    thread is about — only what the reader may see; ``request`` is the message
    being answered, untrusted. ``allowed_actions`` was worked out from the
    person's permissions and the thread's target; the model may only choose from it.
    """
    who = "the brand's client (outside the agency)" if speaker == "client" else "someone on the agency team"
    kind = {
        "change": "They pressed 'Request a change' on this post: they want it changed.",
        "question": "They pressed 'Ask a question' on this post.",
    }.get(request_kind, "")
    guide = "\n".join(f"- {name}: {ACTION_GUIDE[name]}" for name in allowed_actions if name in ACTION_GUIDE)
    text = "\n\n".join(
        part
        for part in [
            base.tagged(
                "thread",
                f"Audience: {'a thread the client reads' if audience == 'client' else 'an internal team thread'}.\n"
                f"The newest message is from {who}.",
            ),
            base.tagged("item", item),
            base.tagged("earlier_messages", "\n\n".join(history) if history else "(this is the first message)"),
            kind,
            base.untrusted("newest_message", request, limit=4000, author=speaker),
            base.tagged("allowed_actions", guide),
            "Answer the newest message and choose the action.",
        ]
        if part
    )
    return base.ask(
        "account_manager",
        instructions=ACCOUNT_MANAGER,
        profile=profile,
        content=text,
        output_type=ChatAnswer,
        effort=ACCOUNT_MANAGER_EFFORT,
        max_tokens=ACCOUNT_MANAGER_MAX_TOKENS,
    )
