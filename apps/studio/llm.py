"""Calling Claude for the Studio's agents.

Every agent is one Messages API request that must answer with JSON matching a
Pydantic model (structured outputs, ``output_config.format``), so the
pipeline never parses free text. The request:

* uses ``settings.STUDIO_MODEL`` (default ``claude-opus-5-5``) with its
  thinking left on — it is adaptive and cannot be switched off on that model —
  and an explicit ``effort`` per agent, because the API's default changes from
  model to model;
* opts into Anthropic's server-side fallback (``fallbacks: "default"``, beta
  ``server-side-fallback-2026-07-01``) when ``settings.STUDIO_FALLBACKS`` is on,
  so a safety classifier's false positive on an ordinary marketing brief is
  retried on the recommended model instead of failing the run;
* sends the brand profile as a cached system block, so a revision or the next
  brief in the same workspace re-reads it at the cache price.

Refusals, truncation and schema mismatches are checked before the JSON is
trusted, and every failure becomes a :class:`StudioAgentError` whose message
is written for the person looking at the brief.
"""

from __future__ import annotations

import base64
import io
import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import pydantic
from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
# Room for adaptive thinking as well as the JSON answer; thinking counts
# towards max_tokens even though its text is not returned.
MAX_TOKENS = 16000
#: Longest edge of an image sent to Claude. Enough to judge a graphic's look,
#: legibility and artefacts at about 1,100 input tokens per image.
IMAGE_MAX_SIDE = 1024


#: List prices in US dollars per million tokens (input, output, cache read), as
#: published for each model in October 2026. Only used to show an estimate.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-fable-5-1": (10.0, 50.0, 0.25),
}
#: A rough per-picture price for fal.ai's FLUX models at about 1.2 megapixels.
PICTURE_PRICE = 0.03


#: Long answers (a blog article) stream instead of waiting on one response,
#: so a long generation can't hit an HTTP timeout part-way.
STREAM_ABOVE_TOKENS = MAX_TOKENS
#: Server-side web search, used only by :func:`research` and only when
#: ``STUDIO_WEB_SEARCH`` is on. Search answers carry citations, which can't be
#: combined with structured outputs, so research is its own free-text call and
#: the agent that uses it answers in a second, structured call.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 3}
#: Billed per search on top of tokens.
WEB_SEARCH_PRICE = 0.01


def estimate_cost(runs) -> float | None:
    """Roughly what ``runs`` (AgentRun rows) cost, or None when a model has no known price."""
    from .team import PICTURE_AGENTS

    total = 0.0
    for run in runs:
        if run.agent in PICTURE_AGENTS:
            total += PICTURE_PRICE if run.status == "succeeded" else 0.0
            continue
        if not (run.input_tokens or run.output_tokens):
            continue
        price = PRICES.get(run.model)
        if price is None:
            return None
        total += (run.input_tokens * price[0] + run.output_tokens * price[1] + run.cache_read_tokens * price[2]) / 1e6
        total += WEB_SEARCH_PRICE * int((run.output or {}).get("web_searches", 0) or 0)
    return total


class StudioAgentError(Exception):
    """An agent could not do its turn. The message is for people.

    ``usage`` holds what the failed call still cost — ``(model, input tokens,
    output tokens, cache-read tokens)`` — when Claude answered but the answer
    couldn't be used (a refusal, a cut-off answer, the wrong shape), so the
    spend can be recorded against the budget.
    """

    def __init__(self, message: str, *, usage: tuple[str, int, int, int] | None = None):
        super().__init__(message)
        self.usage = usage


class NotConfiguredError(StudioAgentError):
    pass


@dataclass(frozen=True)
class AgentResult[T: pydantic.BaseModel]:
    output: T
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    duration_ms: int
    fallback_used: bool = False


def is_configured() -> bool:
    return bool((getattr(settings, "ANTHROPIC_API_KEY", "") or "").strip())


def model_id() -> str:
    return (getattr(settings, "STUDIO_MODEL", "") or DEFAULT_MODEL).strip()


def effort_for(default: str) -> str:
    """The agent's own effort level unless ``STUDIO_EFFORT`` overrides every agent."""
    override = (getattr(settings, "STUDIO_EFFORT", "") or "").strip().lower()
    return override if override in EFFORT_LEVELS else default


@lru_cache(maxsize=4)
def _client(api_key: str, timeout: float):
    import anthropic

    # The SDK retries connection errors, 408, 409, 429 and 5xx twice with
    # backoff on its own; anything still failing after that is reported.
    return anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=2)


def get_client():
    return _client(settings.ANTHROPIC_API_KEY.strip(), float(getattr(settings, "STUDIO_TIMEOUT", 300.0)))


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def image_block(content: bytes, *, max_side: int = IMAGE_MAX_SIDE) -> dict[str, Any]:
    """A base64 JPEG image block, downscaled so its long edge is at most ``max_side``."""
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(content)) as opened:
        image = ImageOps.exif_transpose(opened)
        if image.mode != "RGB":
            image = image.convert("RGB")
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=85)
    data = base64.standard_b64encode(out.getvalue()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def _explain_api_error(exc: Exception) -> str:
    import anthropic

    model = model_id()
    if isinstance(exc, anthropic.AuthenticationError):
        return "Claude rejected ANTHROPIC_API_KEY: it is wrong or has been revoked. Ask your admin to check it."
    if isinstance(exc, anthropic.PermissionDeniedError):
        return f"This Anthropic API key isn't allowed to use {model}. Check the key's workspace, or STUDIO_MODEL."
    if isinstance(exc, anthropic.NotFoundError):
        return f"The Anthropic API doesn't know the model {model!r}. Check STUDIO_MODEL."
    if isinstance(exc, anthropic.RateLimitError):
        return "Claude is rate-limiting this account right now. Wait a minute, then press Retry."
    if isinstance(exc, anthropic.BadRequestError):
        message = getattr(exc, "message", "") or str(exc)
        return f"Claude refused the request: {message[:300]}"
    if isinstance(exc, anthropic.APITimeoutError):
        return "Claude took too long to answer. Press Retry; if it keeps happening, raise STUDIO_TIMEOUT."
    if isinstance(exc, anthropic.APIConnectionError):
        return "Couldn't reach the Anthropic API. Check the server's network, then press Retry."
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code >= 500:
            return f"Claude is having trouble (HTTP {exc.status_code}). Press Retry in a minute."
        return f"The Anthropic API returned HTTP {exc.status_code}: {(getattr(exc, 'message', '') or '')[:300]}"
    return f"Calling Claude failed ({exc.__class__.__name__})."


def _usage(response) -> tuple[int, int, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0, 0
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    input_tokens += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    return input_tokens, int(getattr(usage, "output_tokens", 0) or 0), cache_read


def _fallback_used(response) -> bool:
    iterations = getattr(getattr(response, "usage", None), "iterations", None) or []
    return any(getattr(entry, "type", "") == "fallback_message" for entry in iterations)


def web_search_enabled() -> bool:
    return bool(getattr(settings, "STUDIO_WEB_SEARCH", False))


def run_agent[T: pydantic.BaseModel](
    *,
    agent: str,
    system: list[dict[str, Any]],
    content: list[dict[str, Any]],
    output_type: type[T],
    effort: str,
    max_tokens: int = MAX_TOKENS,
) -> AgentResult[T]:
    """Ask Claude for one agent's turn and return its validated answer.

    ``system`` is the agent's instructions followed by the brand block (the
    last block carries the cache breakpoint); ``content`` is this turn's user
    message — text and image blocks. ``max_tokens`` above the usual ceiling
    streams the response.
    """
    if not is_configured():
        raise NotConfiguredError(
            "The AI Studio needs ANTHROPIC_API_KEY on the SM Bean web and worker services "
            "(an API key from console.anthropic.com). Ask your admin to add it."
        )
    import anthropic

    request: dict[str, Any] = {
        "model": model_id(),
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": content}],
        "output_config": {
            "effort": effort_for(effort),
            "format": {"type": "json_schema", "schema": anthropic.transform_schema(output_type)},
        },
    }
    if getattr(settings, "STUDIO_FALLBACKS", True):
        request["betas"] = [FALLBACK_BETA]
        request["fallbacks"] = "default"
    started = time.monotonic()
    try:
        messages = get_client().beta.messages
        if max_tokens > STREAM_ABOVE_TOKENS:
            with messages.stream(**request) as stream:
                response = stream.get_final_message()
        else:
            response = messages.create(**request)
    except anthropic.APIError as exc:
        logger.warning("Studio %s: Claude call failed: %s", agent, exc)
        raise StudioAgentError(_explain_api_error(exc)) from exc
    duration_ms = int((time.monotonic() - started) * 1000)
    request_id = getattr(response, "_request_id", None)
    input_tokens, output_tokens, cache_read = _usage(response)
    spent = (str(getattr(response, "model", "") or model_id()), input_tokens, output_tokens, cache_read)

    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        logger.warning("Studio %s: Claude declined (category=%s, request=%s)", agent, category, request_id)
        raise StudioAgentError(
            "Claude declined this request"
            + (f" (its safety check flagged it as {category})" if category else "")
            + ". Rephrase the idea or the notes, then press Retry.",
            usage=spent,
        )
    if response.stop_reason == "max_tokens":
        raise StudioAgentError("Claude's answer was cut off before it finished. Press Retry.", usage=spent)

    text = next((block.text for block in response.content if getattr(block, "type", "") == "text"), "")
    try:
        output = output_type.model_validate_json(text)
    except pydantic.ValidationError as exc:
        logger.warning(
            "Studio %s: answer did not match %s (request=%s): %s", agent, output_type.__name__, request_id, exc
        )
        raise StudioAgentError("Claude's answer wasn't in the expected shape. Press Retry.", usage=spent) from exc

    return AgentResult(
        output=output,
        model=str(getattr(response, "model", "") or model_id()),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        duration_ms=duration_ms,
        fallback_used=_fallback_used(response),
    )


@dataclass(frozen=True)
class ResearchResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    web_searches: int
    duration_ms: int


#: How many times a paused search turn is resumed before giving up.
MAX_RESEARCH_CONTINUATIONS = 3


def research(*, agent: str, system: list[dict[str, Any]], question: str, effort: str = "low") -> ResearchResult:
    """A free-text web research turn (server-side web search), for an agent to use afterwards.

    Only call it when :func:`web_search_enabled`. Raises :class:`StudioAgentError`.
    A long search can pause its turn (``stop_reason == "pause_turn"``); the turn is
    resumed by sending the assistant's content back, a few times at most.
    """
    if not is_configured():
        raise NotConfiguredError("Web research needs ANTHROPIC_API_KEY.")
    import anthropic

    messages: list[dict[str, Any]] = [{"role": "user", "content": [text_block(question)]}]
    request: dict[str, Any] = {
        "model": model_id(),
        "max_tokens": 8000,
        "system": system,
        "tools": [WEB_SEARCH_TOOL],
        "output_config": {"effort": effort_for(effort)},
    }
    totals = [0, 0, 0, 0]
    texts: list[str] = []
    assistant_so_far: list[Any] = []
    model = model_id()
    started = time.monotonic()
    for _attempt in range(MAX_RESEARCH_CONTINUATIONS + 1):
        try:
            response = get_client().messages.create(**request, messages=messages)
        except anthropic.APIError as exc:
            logger.warning("Studio %s: research call failed: %s", agent, exc)
            raise StudioAgentError(_explain_api_error(exc)) from exc
        model = str(getattr(response, "model", "") or model)
        used = _usage(response)
        totals[0] += used[0]
        totals[1] += used[1]
        totals[2] += used[2]
        server = getattr(getattr(response, "usage", None), "server_tool_use", None)
        totals[3] += int(getattr(server, "web_search_requests", 0) or 0)
        texts += [block.text for block in response.content if getattr(block, "type", "") == "text"]
        if response.stop_reason != "pause_turn":
            break
        # Resume the paused turn: the question, then everything the assistant has said so far.
        assistant_so_far = [*assistant_so_far, *response.content]
        messages = [messages[0], {"role": "assistant", "content": assistant_so_far}]
    if response.stop_reason == "refusal":
        raise StudioAgentError("Claude declined the research request.", usage=(model, totals[0], totals[1], totals[2]))
    return ResearchResult(
        text="\n".join(t.strip() for t in texts if t.strip()),
        model=model,
        input_tokens=totals[0],
        output_tokens=totals[1],
        cache_read_tokens=totals[2],
        web_searches=totals[3],
        duration_ms=int((time.monotonic() - started) * 1000),
    )
