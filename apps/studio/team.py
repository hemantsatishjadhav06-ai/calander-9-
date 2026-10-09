"""Who is on the agency team, and what each of them does.

This is the one list of agents. The Agency pages draw the roster and the
timelines from it, the engine labels each ``AgentRun`` with it, and the cost
estimate knows from it which agents paint pictures. Adding an agent means a
row here plus the code that runs it (a role in ``apps.studio.roles`` for a
Claude agent, or a step for a code agent).

``kind`` says what kind of worker it is:

* ``claude`` — one structured Claude call (``apps.studio.llm.run_agent``).
* ``image`` — a picture from fal.ai.
* ``render`` — the Pillow graphic designer.
* ``code`` — plain code: checks, scheduling, hand-off. No model, no cost.

No agent approves, schedules or publishes. The producer hands work to a
person; the scheduler only proposes a time.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Department:
    slug: str
    name: str
    does: str
    #: The avatar colour, a CSS custom property from theme/static_src/src/styles.css.
    colour: str


@dataclass(frozen=True)
class AgentSpec:
    slug: str
    name: str
    department: str
    does: str
    kind: str = "claude"
    #: The jobs this agent works on (``post`` is a StudioBrief; the rest are AgencyJob kinds).
    jobs: tuple[str, ...] = ()

    @property
    def initials(self) -> str:
        words = [w for w in self.name.replace("-", " ").split() if w[:1].isalpha()]
        return "".join(w[0] for w in words[:2]).upper() or self.slug[:2].upper()

    @property
    def is_model(self) -> bool:
        return self.kind == "claude"


DEPARTMENTS: tuple[Department, ...] = (
    Department("client", "Client services", "Talks to you and your clients", "--accent-rose"),
    Department("strategy", "Strategy", "Decides what to say", "--accent-indigo"),
    Department("insights", "Insights", "Learns from results", "--accent-amber"),
    Department("creative", "Creative", "Makes the post", "--primary-bright"),
    Department("quality", "Quality", "Checks before you see it", "--accent-emerald"),
    Department("publishing", "Publishing", "Gets it out, after you approve", "--accent-sky"),
    Department("seo", "Blog & SEO", "Gets you found on Google", "--accent-teal"),
)

AGENTS: tuple[AgentSpec, ...] = (
    # Client services
    AgentSpec(
        "account_manager",
        "Account manager",
        "client",
        "Answers your questions and turns requests into work for the right agent.",
        jobs=("chat",),
    ),
    AgentSpec(
        "reporter",
        "Client reporter",
        "client",
        "Writes the weekly report: what went out, what worked, what's next.",
        jobs=("report",),
    ),
    # Strategy
    AgentSpec("strategist", "Content strategist", "strategy", "Proposes three angles from one idea.", jobs=("post",)),
    AgentSpec(
        "planner",
        "Content planner",
        "strategy",
        "Plans next week's posts for your open slots from what worked and what people ask.",
        jobs=("plan",),
    ),
    AgentSpec(
        "trend_scout",
        "Moments scout",
        "strategy",
        "Finds timely moments for the plan: festivals, seasons, industry dates.",
        jobs=("plan",),
    ),
    # Insights
    AgentSpec(
        "performance_analyst",
        "Performance analyst",
        "insights",
        "Reads your analytics against each account's own average: what worked and what didn't.",
        jobs=("plan", "report", "learn"),
    ),
    AgentSpec(
        "audience_listener",
        "Audience listener",
        "insights",
        "Reads comments, messages and reviews for questions, praise and complaints.",
        jobs=("plan", "inbox", "report"),
    ),
    AgentSpec(
        "creative_curator",
        "Creative memory curator",
        "insights",
        "Studies your best creatives and your designer's references and writes down the house style.",
        jobs=("learn",),
    ),
    # Creative
    AgentSpec(
        "copywriter",
        "Copywriter",
        "creative",
        "Writes the caption, hashtags, first comment and alt text.",
        jobs=("post",),
    ),
    AgentSpec(
        "channel_editor",
        "Channel editor",
        "creative",
        "Writes the version each network needs (Instagram, Facebook, Google Business, Threads).",
        jobs=("post",),
    ),
    AgentSpec(
        "art_director",
        "Art director",
        "creative",
        "Chooses the layout, the words on the graphic and the picture.",
        jobs=("post",),
    ),
    AgentSpec(
        "prompt_engineer",
        "Prompt engineer",
        "creative",
        "Writes the image prompt from the art director's direction and your best past creatives.",
        jobs=("post", "blog"),
    ),
    AgentSpec(
        "illustrator", "Illustrator", "creative", "Paints the picture (fal.ai).", kind="image", jobs=("post", "blog")
    ),
    AgentSpec(
        "designer",
        "Graphic designer",
        "creative",
        "Sets the type, logo and colours over the picture.",
        kind="render",
        jobs=("post", "blog"),
    ),
    # Quality
    AgentSpec(
        "reviewer",
        "Brand reviewer",
        "quality",
        "Checks facts, brand rules, craft and consistency with your last post.",
        jobs=("post",),
    ),
    AgentSpec(
        "qa_inspector",
        "QA inspector",
        "quality",
        "Checks lengths for each network, hashtags, links, alt text and contrast.",
        kind="code",
        jobs=("post",),
    ),
    AgentSpec(
        "fact_checker",
        "Fact checker",
        "quality",
        "Checks every claim in an article against your brand facts.",
        jobs=("blog",),
    ),
    AgentSpec(
        "editor_in_chief",
        "Editor-in-chief",
        "quality",
        "Gives articles a final read: useful, original, on-brand.",
        jobs=("blog",),
    ),
    # Publishing
    AgentSpec(
        "scheduler",
        "Scheduler",
        "publishing",
        "Proposes the best free time from your audience's history. Never schedules on its own.",
        kind="code",
        jobs=("post", "plan"),
    ),
    AgentSpec(
        "producer",
        "Producer",
        "publishing",
        "Puts the post or article together and hands it to you for approval.",
        kind="code",
        jobs=("post", "blog"),
    ),
    AgentSpec(
        "community_manager",
        "Community manager",
        "publishing",
        "Drafts replies to comments and messages for you to send.",
        jobs=("inbox",),
    ),
    AgentSpec(
        "reputation_manager",
        "Reviews manager",
        "publishing",
        "Drafts replies to reviews and flags unhappy ones to a person.",
        jobs=("inbox",),
    ),
    # Blog & SEO
    AgentSpec(
        "seo_strategist",
        "SEO strategist",
        "seo",
        "Picks the keyword, the searcher's intent and the questions to answer.",
        jobs=("blog",),
    ),
    AgentSpec(
        "outline_editor", "Outline editor", "seo", "Plans the headings and structure of the article.", jobs=("blog",)
    ),
    AgentSpec(
        "blog_writer", "Blog writer", "seo", "Writes the article, with links to your other articles.", jobs=("blog",)
    ),
    AgentSpec(
        "seo_editor",
        "SEO editor",
        "seo",
        "Writes the search title and description and fixes what the SEO score flags.",
        jobs=("blog",),
    ),
    AgentSpec("repurposer", "Repurposer", "seo", "Turns an article into posts for your channels.", jobs=("repurpose",)),
    AgentSpec(
        "seo_monitor",
        "SEO monitor",
        "seo",
        "Scores published articles, reads your Google rankings and suggests refreshes.",
        kind="code",
        jobs=("seo",),
    ),
)

BY_SLUG: dict[str, AgentSpec] = {agent.slug: agent for agent in AGENTS}
DEPARTMENTS_BY_SLUG: dict[str, Department] = {d.slug: d for d in DEPARTMENTS}

#: Agents whose successful run is a picture (priced per picture, not per token).
PICTURE_AGENTS = frozenset(a.slug for a in AGENTS if a.kind == "image")


def get(slug: str) -> AgentSpec:
    """The agent with this slug; an unknown slug gets a plain stand-in rather than an error."""
    spec = BY_SLUG.get(slug)
    if spec is not None:
        return spec
    return AgentSpec(slug, slug.replace("_", " ").capitalize(), "creative", "")


def name(slug: str) -> str:
    return get(slug).name


def by_department() -> list[tuple[Department, list[AgentSpec]]]:
    return [(d, [a for a in AGENTS if a.department == d.slug]) for d in DEPARTMENTS]


def for_job(job: str) -> list[AgentSpec]:
    return [a for a in AGENTS if job in a.jobs]
