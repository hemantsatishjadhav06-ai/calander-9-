"""Deterministic stand-ins for every model turn in the e2e server process.

* The creative team is the suite's own ``FakeTeam`` (``apps/studio/tests/conftest.py``), imported,
  not copied. Unlike the ``fake_team`` fixture, ``pipeline.enqueue`` is left alone: the real queue
  and the in-process worker run every stage.
* The account manager is :class:`AccountManager`, a rule-based reader of the request that answers
  the same ``ChatAnswer`` schema as the suite's ``GuidedManager``: a new post (with the channels and
  the key message the person named), a routine, a change to the post in the thread, or a plain answer.
* Any other agent turn (planner, reporter, inbox drafts, blog, …) gets a schema-valid answer built
  from its Pydantic output type, so no path a test did not anticipate can reach a provider.
* The source collector returns fixed evidence (the shape of ``test_guided_chat.source_collector``).
* The model clients, the second provider's client, web research and the source fetcher refuse.

Each turn sleeps :func:`agent_delay` seconds first (0 by default), so a test can watch the team work.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import types
import typing
from collections import deque
from collections.abc import Callable
from typing import Any, Literal, get_args, get_origin

import httpx
import pydantic
from django.utils import timezone

logger = logging.getLogger("tests.e2e.fakes")

Setter = Callable[[Any, str, Any], None]

MAX_DELAY = 60.0
#: The model label written on the AgentRun rows the fakes produce.
FAKE_MODEL = "e2e-fake"

_lock = threading.Lock()
_state: dict[str, float] = {"delay": 0.0}
_calls: deque[dict[str, Any]] = deque(maxlen=500)


class ProviderRefusedError(RuntimeError):
    """A model or provider client was asked for in the e2e server; every turn there must be faked."""


def set_agent_delay(seconds: float) -> None:
    value = float(seconds)
    if not 0 <= value <= MAX_DELAY:
        raise ValueError(f"The agent delay must be between 0 and {MAX_DELAY:g} seconds.")
    _state["delay"] = value


def agent_delay() -> float:
    return _state["delay"]


def calls() -> list[dict[str, Any]]:
    with _lock:
        return list(_calls)


def _record(kind: str, agent: str, **extra: Any) -> None:
    with _lock:
        _calls.append({"kind": kind, "agent": agent, "at": time.time(), **extra})


def _pause() -> None:
    delay = _state["delay"]
    if delay > 0:
        time.sleep(delay)


def _result(output: pydantic.BaseModel) -> Any:
    from apps.studio import llm

    return llm.AgentResult(
        output=output,
        model=FAKE_MODEL,
        input_tokens=300,
        output_tokens=120,
        cache_read_tokens=0,
        duration_ms=20,
    )


# ---------------------------------------------------------------------------
# Schema-valid answers for any agent
# ---------------------------------------------------------------------------

_CONSTRAINT_NAMES = ("min_length", "max_length", "ge", "gt", "le", "lt")


def _constraints(info: Any) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for meta in getattr(info, "metadata", None) or []:
        for name in _CONSTRAINT_NAMES:
            value = getattr(meta, name, None)
            if value is not None:
                found[name] = value
    return found


def _text_for(name: str, cons: dict[str, Any]) -> str:
    lowered = name.lower()
    if lowered.endswith("time") or lowered == "when":
        text = "10:30"
    elif "date" in lowered:
        text = timezone.localdate().isoformat()
    elif "url" in lowered or "link" in lowered:
        text = "https://www.example.com/"
    elif "slug" in lowered:
        text = "e2e-open-house"
    elif "hashtag" in lowered or lowered.startswith("tag"):
        text = "OpenHouse"
    elif "title" in lowered or "headline" in lowered:
        text = "Open house this Saturday"
    else:
        text = f"Deterministic e2e text for {name.replace('_', ' ')}."
    minimum = int(cons.get("min_length") or 0)
    while len(text) < minimum:
        text += " More detail for the team."
    if cons.get("max_length") is not None:
        text = text[: int(cons["max_length"])]
    return text


def _number(cons: dict[str, Any], *, integer: bool) -> float:
    low = cons["ge"] if "ge" in cons else (cons["gt"] + (1 if integer else 0.01) if "gt" in cons else None)
    high = cons["le"] if "le" in cons else (cons["lt"] - (1 if integer else 0.01) if "lt" in cons else None)
    value = 1.0
    if low is not None and value < low:
        value = float(low)
    if high is not None and value > high:
        value = float(high)
    return value


def _value(annotation: Any, name: str, cons: dict[str, Any], depth: int) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if annotation is type(None):
        return None
    if origin is typing.Annotated:
        return _value(args[0], name, cons, depth)
    if origin in (typing.Union, types.UnionType):
        options = [arg for arg in args if arg is not type(None)]
        return _value(options[0], name, cons, depth) if options else None
    if origin is Literal:
        options = [arg for arg in args if arg not in ("", None)]
        return options[0] if options else args[0]
    if isinstance(annotation, type) and issubclass(annotation, pydantic.BaseModel):
        return _fields(annotation, depth + 1)
    if origin in (list, tuple, set, frozenset) or annotation in (list, tuple, set, frozenset):
        inner = args[0] if args else str
        count = max(int(cons.get("min_length") or 0), 1 if depth < 3 else 0)
        if cons.get("max_length") is not None:
            count = min(count, int(cons["max_length"]))
        return [_value(inner, f"{name}_{index}", {}, depth + 1) for index in range(count)]
    if origin is dict or annotation is dict:
        return {}
    if annotation is bool:
        return False
    if annotation is int:
        return int(_number(cons, integer=True))
    if annotation is float:
        return _number(cons, integer=False)
    if annotation is str or annotation is Any:
        return _text_for(name, cons)
    return None


def _fields(model: type[pydantic.BaseModel], depth: int) -> dict[str, Any]:
    return {name: _value(info.annotation, name, _constraints(info), depth) for name, info in model.model_fields.items()}


def build_answer[T: pydantic.BaseModel](model: type[T]) -> T:
    """A valid instance of ``model`` built from its annotations and constraints alone."""
    return model.model_validate(_fields(model, 0))


def generic_run_agent[T: pydantic.BaseModel](
    *,
    agent: str,
    system: list[dict[str, Any]],
    content: list[dict[str, Any]],
    output_type: type[T],
    effort: str,
    max_tokens: int | None = None,
) -> Any:
    from apps.studio import llm

    _record("generic", agent, schema=output_type.__name__)
    _pause()
    try:
        output = build_answer(output_type)
    except pydantic.ValidationError as exc:
        logger.warning("e2e: no fake answer for %s as %s: %s", agent, output_type.__name__, exc)
        raise llm.StudioAgentError(f"The e2e fake could not answer as {output_type.__name__}.") from exc
    return _result(output)


# ---------------------------------------------------------------------------
# The account manager
# ---------------------------------------------------------------------------

_ROUTINE = re.compile(
    r"\bevery\s+(?P<when>weekdays?|day|morning|evening|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"\b.*?\bat\s+(?P<hour>\d{1,2})(?:[:.](?P<minute>\d{2}))?\s*(?P<ampm>am|pm)?",
    re.IGNORECASE,
)
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_PLATFORM_WORDS = {
    "instagram": "instagram",
    "linkedin": "linkedin_company",
    "facebook": "facebook",
    "twitter": "x",
    "x": "x",
}
_POST_WORDS = re.compile(r"\b(post|reel|carousel|story)\b", re.IGNORECASE)


def _topic(text: str) -> str:
    topic = re.sub(
        r"^(please\s+)?(can we\s+)?(do\s+|make\s+|write\s+)?(a\s+|an\s+)?(post|reel|carousel|story)\s+(about|on|for)\s+",
        "",
        text.strip(),
        flags=re.IGNORECASE,
    )
    topic = re.split(r"\s+(?:on|for)\s+(?:instagram|linkedin|facebook|x)\b", topic, maxsplit=1, flags=re.IGNORECASE)[0]
    topic = re.split(r",?\s*\bmention\b", topic, maxsplit=1, flags=re.IGNORECASE)[0]
    topic = topic.strip(" .,!")
    return (topic[:1].upper() + topic[1:])[:160] or "A new post"


def _channels(text: str, available: list[str]) -> list[str]:
    words = set(re.findall(r"[a-z]+", text.lower()))
    wanted = {platform for word, platform in _PLATFORM_WORDS.items() if word in words}
    chosen: list[str] = []
    for choice in available:
        if choice.split(":", 1)[0] in wanted and choice not in chosen:
            chosen.append(choice)
    return chosen


class AccountManager:
    """Reads the request like a careful account manager and answers as ``ChatAnswer``."""

    def __call__(
        self,
        profile: Any,
        *,
        audience: str,
        speaker: str,
        history: list[str],
        item: str,
        request: str,
        request_kind: str,
        allowed_actions: list[str],
        guided: bool = False,
        creative_brief: dict[str, Any] | None = None,
        sources: dict[str, Any] | None = None,
        available_channels: list[str] | None = None,
    ) -> Any:
        from apps.studio.creative_brief import CreativeBrief
        from apps.studio.roles import client as client_roles

        _record("manager", "account_manager", request_kind=request_kind, allowed=list(allowed_actions))
        _pause()
        text = " ".join((request or "").split())
        allowed = set(allowed_actions)
        fields: dict[str, Any] = {
            "reply": "Thanks. The team has it and will reply here; nothing changes until you approve it.",
            "action": "answer",
            "instructions": "",
            "needs_human": False,
            "reason": "A question that needs no change.",
            "creative_brief": None,
            "routine_instruction": "",
            "routine_cadence": "",
            "routine_weekday": -1,
            "routine_time": "",
        }
        routine = _ROUTINE.search(text)
        if request_kind == "routine":
            fields.update(
                reply="Here is the check you asked for: nothing needs a decision from you right now.",
                reason="Ran the standing instruction.",
            )
        elif routine and "set_routine" in allowed:
            when = routine.group("when").lower()
            hour = int(routine.group("hour"))
            minute = int(routine.group("minute") or 0)
            if (routine.group("ampm") or "").lower() == "pm" and hour < 12:
                hour += 12
            cadence, weekday = ("weekdays", -1) if when.startswith("weekday") else ("daily", -1)
            if when in _DAYS:
                cadence, weekday = "weekly", _DAYS.index(when)
            instruction = text[routine.end() :].strip(" ,.") or text
            fields.update(
                action="set_routine",
                reply=f"I can do that: {instruction}. Turn it on below and I'll start.",
                reason="A standing instruction on a schedule.",
                routine_instruction=instruction[:300],
                routine_cadence=cadence,
                routine_weekday=weekday,
                routine_time=f"{hour:02d}:{minute:02d}",
            )
        elif request_kind == "change" and "revise_copy" in allowed:
            fields.update(
                action="revise_copy",
                instructions=text,
                reply="I've asked the copywriter to make that change. The new version will come back to you.",
                reason="They asked for a change to this post.",
            )
        elif (
            "new_post" in allowed and (request_kind == "create" or _POST_WORDS.search(text)) and not text.endswith("?")
        ):
            match = re.search(r"\bmention\s+(.+)$", text, flags=re.IGNORECASE)
            key_message = match.group(1).strip(" .") if match else ""
            key_message = key_message[:1].upper() + key_message[1:]
            topic = _topic(text)
            brief = CreativeBrief(
                topic=topic,
                goal="",
                audience="",
                key_message=key_message,
                call_to_action="",
                channels=_channels(text, list(available_channels or [])),
                visual_direction="",
                references="",
                constraints="",
            )
            fields.update(
                action="new_post",
                instructions=text,
                creative_brief=brief,
                reply=f"Here's the brief for {topic[:1].lower() + topic[1:]}. Check it, then tell the team to go ahead.",
                reason="A new post request.",
            )
        return _result(client_roles.ChatAnswer(**fields))


def fake_collect(workspace: Any, profile: Any, accounts: Any) -> dict[str, Any]:
    accounts = list(accounts)
    return {
        "fetched_at": timezone.now().isoformat(),
        "website": {
            "status": "ready",
            "url": "https://www.example.com/",
            "text": "Source statement: confirm this before using it as a brand fact.",
        },
        "channels": [
            {
                "account_id": str(account.pk),
                "platform": account.platform,
                "account_name": account.account_name,
                "posts": [{"caption": "A previous published caption."}],
            }
            for account in accounts
        ],
        "notes": ["Website and captions are source evidence requiring human confirmation."],
    }


# ---------------------------------------------------------------------------
# Installing them
# ---------------------------------------------------------------------------


def _turn(fn: Callable[..., Any], agent: str) -> Callable[..., Any]:
    def turn(*args: Any, **kwargs: Any) -> Any:
        _record("team", agent)
        _pause()
        return fn(*args, **kwargs)

    turn.__name__ = agent
    turn.__qualname__ = agent
    return turn


def _refuse_provider(*_args: Any, **_kwargs: Any) -> Any:
    raise ProviderRefusedError("e2e: a model client was requested; every turn in the e2e server is faked.")


def _refuse_sources(*_args: Any, **_kwargs: Any) -> Any:
    raise httpx.ConnectError("e2e: source networking is off; the source collector is faked.")


def _no_research(**_kwargs: Any) -> Any:
    from apps.studio import llm

    raise llm.StudioAgentError("Web research is off in this environment. Use supplied, verified brand facts.")


def install(setter: Setter = setattr) -> Any:
    """Put the fakes in place and return the ``FakeTeam``. Tests pass ``monkeypatch.setattr``."""
    from apps.studio import agents, creative_sources, llm, openrouter
    from apps.studio.roles import client as client_roles
    from apps.studio.roles import creative
    from apps.studio.tests.conftest import FakeTeam

    team = FakeTeam()
    for name in ("strategist", "copywriter", "art_director", "reviewer"):
        setter(agents, name, _turn(getattr(team, name), name))
    for name in ("prompt_engineer", "channel_editor"):
        setter(creative, name, _turn(getattr(team, name), name))
    setter(client_roles, "account_manager", AccountManager())
    setter(creative_sources, "collect", fake_collect)
    setter(creative_sources, "get_client", _refuse_sources)
    setter(llm, "run_agent", generic_run_agent)
    setter(llm, "get_client", _refuse_provider)
    setter(llm, "research", _no_research)
    setter(openrouter, "run_agent", generic_run_agent)
    setter(openrouter, "get_client", _refuse_provider)
    return team
