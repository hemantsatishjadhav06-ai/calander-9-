"""Quality department, for articles: the fact checker and the editor-in-chief.

The **fact checker** reads every claim in a draft against the brand facts and
compliance rules — the same facts every agent writes from — and returns the
ones they don't support, each with a fix the writer can apply. One pass back
to the writer is allowed; anything still unsupported after that is shown to
the approver instead of being argued over by agents.

The **editor-in-chief** gives the finished draft the read Google's
helpful-content guidance describes: written for people, original, on-voice,
trustworthy (experience, expertise, authority, trust). It may send the draft
back to the writer once.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .. import llm
from . import base

FACT_CHECKER_EFFORT = "medium"
EDITOR_IN_CHIEF_EFFORT = "medium"

FACT_CHECKER = (
    "Your role: fact checker. Check every factual claim in the article against <facts>, <compliance> and the "
    "brief before an editor and a person see it.\n\n"
    "What counts as a claim: any number, price, percentage, size, date, duration, place, name, legal or regulatory "
    "statement, award, client, result, promise or comparison ('the best', 'the cheapest', 'guaranteed'), and any "
    "first-hand experience ('we have helped...'). General, widely known explanations (what a title deed is) are "
    "not claims about the brand and are fine — unless they state a specific legal requirement, fee or deadline as "
    "certain.\n\n"
    "For each claim the facts don't support, that stretches a fact into a promise, or that breaks a compliance "
    "rule: quote it exactly as it appears, say why in a few words, and give a fix the writer can apply (remove "
    "it, soften it to what the facts say, or use the specific fact instead).\n\n"
    "verdict is 'supported' when nothing needs fixing and 'fix' otherwise. Don't comment on style; only facts and "
    "rules."
)

EDITOR_IN_CHIEF = (
    "Your role: editor-in-chief. Give the article its final read before a person approves it. Judge it the way "
    "Google's helpful-content guidance asks: is it written for people, not for search engines?\n\n"
    "Check, in this order:\n"
    "1. helpful: it answers the searcher's question fully and early, and a reader leaves knowing what to do;\n"
    "2. original: it adds something beyond what usually ranks (see the strategist's plan) — specifics, a "
    "checklist, a worked example, local detail;\n"
    "3. on_voice: it sounds like the brand, with no hype, no filler and no machine-sounding phrases;\n"
    "4. people_first: no keyword stuffing, no padding to reach a length, headings that tell the reader something;\n"
    "5. trust: claims rest on the brand's facts, experience is only what the facts say, the brand's expertise "
    "shows, nothing misleads, and the compliance rules are kept;\n"
    "6. structure: an answer-first intro, sections in a sensible order, a clear next step at the end.\n\n"
    "Choose verdict 'revise' only for a problem worth another writing pass (a missing answer, a misleading claim, "
    "a section that doesn't deliver). Taste preferences go in notes_for_approver, not fixes. Write fixes as "
    "specific instructions the writer can act on. Be brief."
)


class UnsupportedClaim(base.Answer):
    claim: str = Field(description="The claim, quoted exactly as it appears in the article.")
    why: str = Field(description="Why the facts don't support it, in a few words.")
    fix: str = Field(description="What the writer should do: remove it, soften it, or use a specific fact.")


class FactCheckAnswer(base.Answer):
    verdict: Literal["supported", "fix"]
    claims_checked: int = Field(description="How many claims you checked.")
    unsupported: list[UnsupportedClaim] = Field(description="Every unsupported claim; empty when supported.")
    summary: str = Field(description="One sentence for the team.")


class EditorCheck(base.Answer):
    name: Literal["helpful", "original", "on_voice", "people_first", "trust", "structure"]
    passed: bool
    note: str = Field(description="One short sentence.")


class EditorAnswer(base.Answer):
    verdict: Literal["approve", "revise"]
    checks: list[EditorCheck] = Field(description="One entry per check, in order.")
    fixes: list[str] = Field(description="Specific instructions for the writer; empty when approving.")
    notes_for_approver: list[str] = Field(description="Things a person should look at; may be empty.")
    summary: str = Field(description="One sentence: the editor's verdict, for the team.")


def _article(article: dict[str, Any]) -> str:
    faq = "\n".join(f"Q: {item.get('q', '')}\nA: {item.get('a', '')}" for item in article.get("faq") or [])
    return base.tagged(
        "article",
        f"Title: {article.get('title', '')}\nExcerpt: {article.get('excerpt', '')}\n\n"
        f"{article.get('body', '')}\n\nFAQ:\n{faq or '(none)'}",
    )


def fact_checker(profile, *, article: dict[str, Any], topic: str, notes: str = "") -> llm.AgentResult[FactCheckAnswer]:
    """Every claim in ``article`` checked against the brand facts and compliance rules."""
    text = "\n\n".join(
        [
            base.tagged("topic", topic),
            base.tagged("notes", notes or "None."),
            _article(article),
            "Check the article's claims.",
        ]
    )
    return base.ask(
        "fact_checker",
        instructions=FACT_CHECKER,
        profile=profile,
        content=text,
        output_type=FactCheckAnswer,
        effort=FACT_CHECKER_EFFORT,
    )


def editor_in_chief(
    profile,
    *,
    article: dict[str, Any],
    topic: str,
    plan: dict[str, Any],
    seo_score: int | None = None,
    open_flags: list[str] | None = None,
) -> llm.AgentResult[EditorAnswer]:
    """The final read: helpful, original, on-voice, people-first, trustworthy."""
    plan_text = (
        f"Focus keyword: {plan.get('focus_keyword', '')}\n"
        f"Search intent: {plan.get('search_intent', '')} — {plan.get('intent_notes', '')}\n"
        f"Angle: {plan.get('angle', '')}\n"
        f"Better than typical results:\n{base.bullets(plan.get('better_than_typical'))}"
    )
    parts = [
        base.tagged("topic", topic),
        base.tagged("strategist_plan", plan_text),
        _article(article),
    ]
    if seo_score is not None:
        parts.append(base.tagged("seo_score", f"{seo_score} of 100 on the automatic checks."))
    if open_flags:
        parts.append(base.tagged("fact_checker_open_flags", base.bullets(open_flags)))
    parts.append("Give your final read.")
    return base.ask(
        "editor_in_chief",
        instructions=EDITOR_IN_CHIEF,
        profile=profile,
        content="\n\n".join(parts),
        output_type=EditorAnswer,
        effort=EDITOR_IN_CHIEF_EFFORT,
    )
