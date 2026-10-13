"""Strategy department: the content planner and the moments scout.

The **moments scout** looks at the week being planned and lists the dates that
give a post a reason to exist that week: public holidays and festivals where
the brand's audience lives, seasons, industry dates, the brand's own pillars.
With web search switched on (``STUDIO_WEB_SEARCH``) it first searches, in a
separate free-text turn (:func:`moments_research`), and works from what it
found; without it, it works from what the model knows and says how sure it is.

The **content planner** fills next week's open posting slots. It starts from
the pillars the account owner chose, what the performance analyst says worked
for this brand's own accounts, what the audience listener heard people ask,
and the scout's moments. It never invents facts: an idea is a topic and an
angle, not a claim, and anything that needs a number or a date it doesn't have
is written so the copywriter can work around it.

Neither agent picks a target by itself: the planner chooses accounts and slots
by the short keys it is shown (``a1``, ``s3``), and the plan job maps those
keys back to rows it loaded itself.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import Field

from .. import llm
from . import base

PLANNER_EFFORT = "high"
TREND_SCOUT_EFFORT = "medium"
RESEARCH_EFFORT = "low"

Goal = Literal["awareness", "education", "engagement", "leads", "announcement"]
Confidence = Literal["certain", "likely", "unsure"]

TREND_SCOUT = (
    "Your role: moments scout. You list the dates and moments in the plan window that give this brand a timely "
    "reason to post: public holidays, festivals and observances where its audience lives, seasons and weather, "
    "school and financial calendars, industry events and awareness days, and anything in the brand facts that "
    "falls in the window (a launch, an anniversary).\n\n"
    "Rules:\n"
    "- Only moments that fall inside the window, with the date or date range as you understand it.\n"
    "- Relevance first: a moment is worth listing only if the brand's audience would expect or welcome a post "
    "about it. Five good moments beat fifteen weak ones; an empty list is a fine answer.\n"
    "- Dates of movable festivals and one-off events can be wrong. Mark confidence honestly: 'certain' only for "
    "fixed dates you know, 'likely' when the date is usually right, 'unsure' otherwise. When you were given web "
    "research, prefer what it says and still mark anything it doesn't confirm as 'unsure'.\n"
    "- Never suggest a post that exploits a tragedy, a disaster or a political fight.\n"
    "- angle_idea is one sentence on how this brand could mark the moment without inventing facts."
)

MOMENTS_RESEARCH = (
    "Your role: moments scout, researching on the web. Search for public holidays, festivals, observances, "
    "seasonal events and industry dates that fall in the given window and matter to the brand's audience and "
    "location. Answer in plain text: one line per moment with its date, where it applies, and the source you "
    "found it in. Say plainly when you couldn't confirm a date."
)

PLANNER = (
    "Your role: content planner. You plan next week's social posts for this brand: one idea per open slot you "
    "are asked to fill, each a clear, specific topic the strategist and copywriter can turn into a post.\n\n"
    "Work from, in this order:\n"
    "1. The content pillars the account owner chose. Rotate between them across the week; don't put the same "
    "pillar on two days running unless there are fewer pillars than posts.\n"
    "2. What the performance analyst says works for this brand's own accounts (formats, angles, days).\n"
    "3. What the audience listener heard people ask or complain about: a real question from the audience is "
    "the best idea there is. Answer it with the brand's facts; never quote or name the person.\n"
    "4. The moments scout's dates, where one fits a pillar. Skip moments marked 'unsure' unless the idea "
    "works without the date.\n\n"
    "Rules:\n"
    "- Facts: an idea states only what the brand facts say. Never invent a price, number, date, project, "
    "award, client or result; if an idea needs a fact you don't have, choose another idea or phrase it as a "
    "question the post explores.\n"
    "- No repeats: don't plan anything that repeats the angle of a recent post or brief.\n"
    "- Variety: mix goals and formats across the week (explain, show, answer a question, a point of view, an "
    "announcement only when the facts contain the news).\n"
    "- accounts: the keys of the accounts each idea suits (from <accounts>); give all of them when it suits "
    "every one. slot: the key of the open slot you would use (from <open_slots>), each slot at most once; "
    "an empty string if you have no preference.\n"
    "- idea is one or two sentences, written as a brief to the team (what the post is about and for whom); "
    "angle_notes says how to make it land; why_now names the moment or audience question behind it, or says "
    "'evergreen'.\n"
    "- When articles are asked for, propose blog topics people search for, with a plain focus keyword phrase "
    "people would type into Google. Never claim search volumes."
)


class Moment(base.Answer):
    name: str = Field(description="The moment, e.g. 'Diwali' or 'Start of the monsoon'. At most 80 characters.")
    when: str = Field(description="The date or date range inside the window, e.g. '2026-10-20' or '12–14 Oct'.")
    why_it_matters: str = Field(description="One sentence: why this brand's audience cares.")
    angle_idea: str = Field(description="One sentence: how the brand could mark it without inventing facts.")
    confidence: Confidence = Field(description="How sure you are of the date: certain, likely or unsure.")


class MomentsAnswer(base.Answer):
    moments: list[Moment] = Field(description="Up to 8 moments inside the window, most relevant first. May be empty.")
    notes: str = Field(description="One or two sentences for the planner, including any caveats about the dates.")


class PlanIdea(base.Answer):
    idea: str = Field(description="The post idea as a brief to the team: one or two sentences, no invented facts.")
    pillar: str = Field(description="The content pillar it belongs to, exactly as given in <pillars>, or 'Other'.")
    goal: Goal = Field(description="What the post is for.")
    angle_notes: str = Field(description="One or two sentences on how to make it land: format, hook, what to show.")
    why_now: str = Field(description="The moment or audience question behind it, or 'evergreen'.")
    accounts: list[str] = Field(description="Keys from <accounts> this idea suits, e.g. ['a1', 'a2'].")
    slot: str = Field(description="The key from <open_slots> you would use, e.g. 's3', or '' for no preference.")


class ArticleIdea(base.Answer):
    topic: str = Field(description="The article's working title: a question or need people search for.")
    focus_keyword: str = Field(description="The search phrase it should rank for, 2 to 6 words, lower case.")
    why: str = Field(description="One sentence: who searches for this and why the brand can answer it.")


class PlanAnswer(base.Answer):
    ideas: list[PlanIdea] = Field(description="Exactly the number of post ideas asked for, in the order to publish.")
    articles: list[ArticleIdea] = Field(
        description="Exactly the number of blog article ideas asked for (often zero: then an empty list)."
    )
    notes: str = Field(description="Two or three sentences for the team on the shape of the week.")


def moments_research(profile, *, window_start: date, window_end: date, pillars: list[str], zone: str):
    """A web research turn for the scout (only when ``llm.web_search_enabled()``). Returns ``llm.ResearchResult``."""
    question = "\n\n".join(
        [
            base.tagged("window", f"{window_start:%A %d %B %Y} to {window_end:%A %d %B %Y}"),
            base.tagged("location_and_timezone", zone),
            base.tagged("pillars", base.bullets(pillars)),
            "Find the moments in this window that matter to this brand's audience.",
        ]
    )
    return llm.research(
        agent="trend_scout",
        system=base.system(MOMENTS_RESEARCH, profile),
        question=question,
        effort=RESEARCH_EFFORT,
    )


def trend_scout(
    profile,
    *,
    window_start: date,
    window_end: date,
    pillars: list[str],
    zone: str,
    research: str | None = None,
) -> llm.AgentResult[MomentsAnswer]:
    """Timely moments for the plan window. ``research`` is the web research text, when there is any."""
    parts = [
        base.tagged("window", f"{window_start:%A %d %B %Y} to {window_end:%A %d %B %Y}"),
        base.tagged("location_and_timezone", zone),
        base.tagged("pillars", base.bullets(pillars)),
    ]
    if research:
        parts.append(base.untrusted("web_research", research, limit=8000))
        parts.append("Use the web research above where it is relevant; it may be incomplete.")
    else:
        parts.append(
            "There is no web research this time: work from what you know and mark dates you aren't sure of as 'unsure'."
        )
    parts.append("List the moments for this window.")
    return base.ask(
        "trend_scout",
        instructions=TREND_SCOUT,
        profile=profile,
        content="\n\n".join(parts),
        output_type=MomentsAnswer,
        effort=TREND_SCOUT_EFFORT,
    )


def _lines(rows: list[dict[str, Any]], *keys: str) -> str:
    return "\n".join("- " + " · ".join(str(row.get(key, "")) for key in keys) for row in rows) or "(none)"


def planner(
    profile,
    *,
    posts: int,
    articles: int,
    window_start: date,
    window_end: date,
    pillars: list[str],
    accounts: list[dict[str, str]],
    slots: list[dict[str, str]],
    performance: str,
    audience: str,
    moments: str,
    recent: list[str],
) -> llm.AgentResult[PlanAnswer]:
    """Next week's plan: ``posts`` ideas (and ``articles`` blog topics).

    ``accounts`` and ``slots`` are ``[{"key", "label"}]`` rows the plan job built;
    ``performance``, ``audience`` and ``moments`` are the other agents' notes as text;
    ``recent`` is recent captions and brief ideas, to avoid repeats.
    """
    parts = [
        base.tagged("week", f"{window_start:%A %d %B %Y} to {window_end:%A %d %B %Y}"),
        base.tagged("posts_wanted", str(posts)),
        base.tagged("articles_wanted", str(articles)),
        base.tagged("pillars", base.bullets(pillars) if pillars else "None chosen: use the brand's main themes."),
        base.tagged("accounts", _lines(accounts, "key", "label")),
        base.tagged("open_slots", _lines(slots, "key", "label")),
        base.untrusted("performance_analyst_notes", performance or "No analytics to go on yet."),
        base.untrusted("audience_listener_notes", audience or "Nothing heard from the audience recently."),
        base.untrusted("moments_scout_notes", moments or "No moments found."),
        base.untrusted("recent_posts_and_briefs", base.bullets(recent), limit=8000),
        f"Plan {posts} post idea(s) and {articles} article idea(s) for this week.",
    ]
    return base.ask(
        "planner",
        instructions=PLANNER,
        profile=profile,
        content="\n\n".join(parts),
        output_type=PlanAnswer,
        effort=PLANNER_EFFORT,
    )
