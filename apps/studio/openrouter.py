"""OpenRouter's OpenAI-compatible chat API for validated Studio turns.

The endpoint is fixed, redirects are refused, TLS verification stays enabled,
and credentials/prompt/provider error bodies never appear in error messages.
Tests replace ``get_client`` with an httpx MockTransport; no paid call is
needed to exercise this adapter.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from collections.abc import Callable, Iterator
from functools import lru_cache
from typing import Any

import httpx
import pydantic
from django.conf import settings

from apps.common.background import check_worker_lease

from . import llm

logger = logging.getLogger(__name__)
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
MAX_RETRIES = 2
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
# Usage must fit the ledger's PostgreSQL PositiveIntegerField. Impossible
# provider counters are unusable metadata; a valid USD report remains usable.
MAX_USAGE_TOKENS = 2_147_483_647


@lru_cache(maxsize=1)
def get_client() -> httpx.Client:
    return httpx.Client(follow_redirects=False)


def _tokens(value: Any) -> int:
    try:
        count = int(value or 0)
        return count if 0 <= count <= MAX_USAGE_TOKENS else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def _usage(response: dict) -> tuple[str, int, int, int]:
    usage = response.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    details = usage.get("prompt_tokens_details") or {}
    if not isinstance(details, dict):
        details = {}
    prompt = _tokens(usage.get("prompt_tokens"))
    cached = min(prompt, _tokens(details.get("cached_tokens")))
    written = min(prompt - cached, _tokens(details.get("cache_write_tokens")))
    # Prompt tokens include reads and writes. Count writes at the same
    # conservative 1.25x input weight used by the direct Anthropic adapter.
    fresh = min(MAX_USAGE_TOKENS, prompt - cached - written + round(written * llm.CACHE_WRITE_WEIGHT))
    model = response.get("model")
    key = (getattr(settings, "OPENROUTER_API_KEY", "") or "").strip()
    # Only public model identifiers belong in the usage ledger. Provider
    # bodies are untrusted and may echo a credential in arbitrary fields.
    if (
        not isinstance(model, str)
        or len(model) > 100
        or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.:+/-]+", model)
        or (key and key in model)
    ):
        model = llm.model_id()
    return (
        model,
        fresh,
        _tokens(usage.get("completion_tokens")),
        cached,
    )


def _provider_cost(response: dict) -> str | None:
    usage = response.get("usage")
    return llm.validated_provider_cost(usage.get("cost")) if isinstance(usage, dict) else None


def _reported_charge(response: dict) -> bool:
    """Avoid retries for paid or malformed billing reports even without tokens."""
    usage = response.get("usage")
    if not isinstance(usage, dict) or usage.get("cost") is None:
        return False
    cost = _provider_cost(response)
    return cost is None or cost != "0"


def _error(status: int, *, usage=None, provider_cost_usd=None) -> llm.StudioAgentError:
    if status == 401:
        message = "OpenRouter rejected OPENROUTER_API_KEY. Ask your admin to check or replace it."
    elif status == 402:
        message = "OpenRouter has insufficient credits for this request. Add credits or check the key's spending limit."
    elif status == 403:
        message = "OpenRouter refused access. Check the key's permissions, model access, and the server's network."
    elif status == 404:
        message = "OpenRouter does not recognize STUDIO_MODEL. Choose an available namespaced model."
    elif status == 429:
        message = "OpenRouter is rate-limiting this account. Wait a minute, then press Retry."
    elif status in {408, 504}:
        message = "OpenRouter took too long to answer. Press Retry; check STUDIO_TIMEOUT if this continues."
    elif status >= 500:
        message = f"OpenRouter is having trouble (HTTP {status}). Press Retry in a minute."
    elif status in {400, 422}:
        message = (
            "OpenRouter rejected the request. Check STUDIO_MODEL supports images, reasoning, and structured outputs."
        )
    else:
        message = f"OpenRouter returned HTTP {status}. Ask your admin to check its configuration."
    return llm.StudioAgentError(message, usage=usage, provider_cost_usd=provider_cost_usd)


def _messages(system: list[dict[str, Any]], content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    instructions = []
    for block in system:
        if block.get("type") != "text" or not isinstance(block.get("text"), str):
            raise llm.StudioAgentError("OpenRouter received unsupported system instructions.")
        instructions.append(block["text"])
    parts = []
    for block in content:
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append({"type": "text", "text": block["text"]})
        elif block.get("type") == "image":
            source = block.get("source") or {}
            if (
                source.get("type") != "base64"
                or source.get("media_type") != "image/jpeg"
                or not isinstance(source.get("data"), str)
            ):
                raise llm.StudioAgentError(
                    "OpenRouter received an unsupported image. Use a Studio-generated image block."
                )
            parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{source['data']}"}})
        else:
            raise llm.StudioAgentError("OpenRouter received unsupported message content.")
    return [{"role": "system", "content": "\n\n".join(instructions)}, {"role": "user", "content": parts}]


def _body_chunks(
    response: httpx.Response,
    *,
    deadline: float,
    usage: Callable[[], tuple[str, int, int, int]] | None = None,
) -> Iterator[bytes]:
    """Bound decoded body size and check the deadline on every received chunk.

    HTTPX's timeout also bounds inactivity inside the current socket read;
    the wall-time check happens as soon as that read returns a chunk.
    """
    size = 0
    for chunk in response.iter_bytes():
        if time.monotonic() >= deadline:
            raise llm.StudioAgentError(
                "OpenRouter took too long to answer. Press Retry.", usage=usage() if usage else None
            )
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise llm.StudioAgentError(
                "OpenRouter's answer exceeded the response size limit. Press Retry.", usage=usage() if usage else None
            )
        yield chunk
    if time.monotonic() >= deadline:
        raise llm.StudioAgentError("OpenRouter took too long to answer. Press Retry.", usage=usage() if usage else None)


def _stream_lines(response: httpx.Response, *, deadline: float, usage) -> Iterator[str]:
    pending = b""
    for chunk in _body_chunks(response, deadline=deadline, usage=usage):
        pending += chunk
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            yield line.rstrip(b"\r").decode("utf-8")
    if pending:
        yield pending.rstrip(b"\r").decode("utf-8")


def _read_stream(response: httpx.Response, *, deadline: float) -> dict:
    """Collect SSE text and the final usage chunk, including billed failures."""
    answer: dict[str, Any] = {"choices": [{"message": {"content": ""}, "finish_reason": None}]}
    choice = answer["choices"][0]
    text = []
    finished = False
    try:
        for line in _stream_lines(response, deadline=deadline, usage=lambda: _usage(answer)):
            if time.monotonic() >= deadline:
                raise llm.StudioAgentError("OpenRouter took too long to answer. Press Retry.", usage=_usage(answer))
            # OpenRouter emits keepalive comments while the model thinks.
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                finished = True
                break
            item = json.loads(data)
            if not isinstance(item, dict):
                raise ValueError("Invalid SSE event")
            if item.get("model"):
                answer["model"] = item["model"]
            if isinstance(item.get("usage"), dict):
                # Usage events are cumulative snapshots, not extra calls.
                # Keep earlier token counts when a later event adds cost.
                previous = answer.get("usage") or {}
                current = item["usage"]
                combined = {**previous, **{key: value for key, value in current.items() if value is not None}}
                if isinstance(previous.get("prompt_tokens_details"), dict) and isinstance(
                    current.get("prompt_tokens_details"), dict
                ):
                    combined["prompt_tokens_details"] = {
                        **previous["prompt_tokens_details"],
                        **current["prompt_tokens_details"],
                    }
                answer["usage"] = combined
            if item.get("error"):
                error = item["error"]
                code = _tokens(error.get("code")) if isinstance(error, dict) else 0
                raise _error(code or 502, usage=_usage(answer), provider_cost_usd=_provider_cost(answer))
            choices = item.get("choices") or []
            if not isinstance(choices, list):
                raise ValueError("Invalid choices")
            for entry in choices:
                if entry.get("index", 0) != 0:
                    continue
                delta = entry.get("delta") or {}
                chunk = delta.get("content")
                if chunk is not None:
                    if not isinstance(chunk, str):
                        raise ValueError("Invalid content")
                    text.append(chunk)
                if delta.get("refusal"):
                    choice["message"]["refusal"] = True
                if entry.get("finish_reason"):
                    choice["finish_reason"] = entry["finish_reason"]
    except llm.StudioAgentError as exc:
        exc.provider_cost_usd = _provider_cost(answer)
        raise
    except (ValueError, TypeError, AttributeError):
        raise llm.StudioAgentError(
            "OpenRouter returned an invalid streaming answer. Press Retry.",
            usage=_usage(answer),
            provider_cost_usd=_provider_cost(answer),
        ) from None
    except httpx.RequestError:
        raise llm.StudioAgentError(
            "OpenRouter's connection was interrupted. Press Retry.",
            usage=_usage(answer),
            provider_cost_usd=_provider_cost(answer),
        ) from None
    if not finished:
        raise llm.StudioAgentError(
            "OpenRouter's answer was cut off before it finished. Press Retry.",
            usage=_usage(answer),
            provider_cost_usd=_provider_cost(answer),
        )
    choice["message"]["content"] = "".join(text)
    return answer


def _request(payload: dict, *, agent: str, started: float) -> dict:
    try:
        limit = float(getattr(settings, "STUDIO_TIMEOUT", 300.0))
    except (TypeError, ValueError):
        limit = 0
    if not math.isfinite(limit) or limit <= 0:
        raise llm.StudioAgentError("STUDIO_TIMEOUT must be a positive, finite number of seconds.")
    deadline = started + limit
    headers = {"Authorization": f"Bearer {settings.OPENROUTER_API_KEY.strip()}"}
    for attempt in range(MAX_RETRIES + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise llm.StudioAgentError("OpenRouter took too long to answer. Press Retry.")
        timeout = httpx.Timeout(remaining, connect=min(10.0, remaining), pool=min(5.0, remaining))
        try:
            check_worker_lease()
            with get_client().stream("POST", ENDPOINT, headers=headers, json=payload, timeout=timeout) as response:
                if response.status_code != 200:
                    body = b"".join(_body_chunks(response, deadline=deadline))
                    try:
                        failed = json.loads(body)
                    except ValueError:
                        failed = {}
                    if not isinstance(failed, dict):
                        failed = {}
                    usage = _usage(failed) if isinstance(failed, dict) and failed.get("usage") else None
                    transient = response.status_code in {408, 409, 429} or response.status_code >= 500
                    if (
                        transient
                        and attempt < MAX_RETRIES
                        and not (usage and any(usage[1:]))
                        and not _reported_charge(failed)
                    ):
                        # Never discard a billed failed response in a retry.
                        # Otherwise retries consume the same turn deadline.
                        time.sleep(min(2**attempt, max(0.0, deadline - time.monotonic())))
                        continue
                    raise _error(response.status_code, usage=usage, provider_cost_usd=_provider_cost(failed))
                if payload.get("stream"):
                    return _read_stream(response, deadline=deadline)
                body = b"".join(_body_chunks(response, deadline=deadline))
                try:
                    answer = json.loads(body)
                except ValueError:
                    raise llm.StudioAgentError("OpenRouter returned an invalid JSON answer. Press Retry.") from None
                if not isinstance(answer, dict):
                    raise llm.StudioAgentError("OpenRouter returned an invalid answer. Press Retry.")
                return answer
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if attempt < MAX_RETRIES:
                time.sleep(min(2**attempt, max(0.0, deadline - time.monotonic())))
                continue
            logger.warning("Studio %s: OpenRouter connection failed after bounded retries", agent)
            raise llm.StudioAgentError(
                "Couldn't reach OpenRouter. Check the server's network, then press Retry."
            ) from None
        except httpx.TimeoutException:
            raise llm.StudioAgentError("OpenRouter took too long to answer. Press Retry.") from None
        except httpx.RequestError:
            logger.warning("Studio %s: OpenRouter transport failed", agent)
            raise llm.StudioAgentError(
                "Couldn't reach OpenRouter. Check the server's network, then press Retry."
            ) from None
    raise llm.StudioAgentError("OpenRouter could not complete this request. Press Retry.")


def run_agent[T: pydantic.BaseModel](
    *,
    agent: str,
    system: list[dict[str, Any]],
    content: list[dict[str, Any]],
    output_type: type[T],
    effort: str,
    max_tokens: int = llm.MAX_TOKENS,
) -> llm.AgentResult[T]:
    requested_model = llm.model_id()
    chosen_effort = llm.effort_for(effort)
    # OpenRouter normalizes reasoning effort to low/medium/high for this model.
    chosen_effort = "high" if chosen_effort in {"xhigh", "max"} else chosen_effort
    if chosen_effort not in {"low", "medium", "high"}:
        raise llm.StudioAgentError("OpenRouter reasoning effort must be low, medium, or high.")
    payload = {
        "model": requested_model,
        "max_tokens": max_tokens,
        "messages": _messages(system, content),
        "reasoning": {"effort": chosen_effort},
        # OpenRouter's usage-accounting opt-in includes request cost when
        # available, for both ordinary responses and the final SSE event.
        "usage": {"include": True},
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": output_type.__name__, "strict": True, "schema": output_type.model_json_schema()},
        },
        # A route that cannot enforce this schema must fail, rather than
        # silently dropping parameters and returning untrusted free text.
        "provider": {"require_parameters": True},
    }
    if max_tokens > llm.STREAM_ABOVE_TOKENS:
        payload.update(stream=True, stream_options={"include_usage": True})
    started = time.monotonic()
    answer = _request(payload, agent=agent, started=started)
    spent = _usage(answer)
    provider_cost = _provider_cost(answer)
    if answer.get("error"):
        error = answer["error"]
        code = _tokens(error.get("code")) if isinstance(error, dict) else 0
        raise _error(code or 502, usage=spent, provider_cost_usd=provider_cost)
    choices = answer.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise llm.StudioAgentError(
            "OpenRouter returned no usable answer. Press Retry.", usage=spent, provider_cost_usd=provider_cost
        )
    choice = choices[0]
    message = choice.get("message") or {}
    if not isinstance(message, dict):
        raise llm.StudioAgentError(
            "OpenRouter returned an invalid answer. Press Retry.", usage=spent, provider_cost_usd=provider_cost
        )
    if message.get("refusal") or choice.get("finish_reason") == "content_filter":
        raise llm.StudioAgentError(
            "OpenRouter declined this request. Rephrase the idea or notes, then press Retry.",
            usage=spent,
            provider_cost_usd=provider_cost,
        )
    if choice.get("finish_reason") == "length":
        raise llm.StudioAgentError(
            "OpenRouter's answer was cut off before it finished. Press Retry.",
            usage=spent,
            provider_cost_usd=provider_cost,
        )
    if choice.get("finish_reason") != "stop":
        raise llm.StudioAgentError(
            "OpenRouter did not finish with a usable answer. Press Retry.", usage=spent, provider_cost_usd=provider_cost
        )
    text = message.get("content")
    if not isinstance(text, str):
        raise llm.StudioAgentError(
            "OpenRouter returned no usable text answer. Press Retry.", usage=spent, provider_cost_usd=provider_cost
        )
    try:
        output = output_type.model_validate_json(text)
    except pydantic.ValidationError:
        logger.warning("Studio %s: OpenRouter answer did not match %s", agent, output_type.__name__)
        raise llm.StudioAgentError(
            "OpenRouter's answer wasn't in the expected shape. Press Retry.",
            usage=spent,
            provider_cost_usd=provider_cost,
        ) from None
    return llm.AgentResult(
        output=output,
        model=spent[0],
        input_tokens=spent[1],
        output_tokens=spent[2],
        cache_read_tokens=spent[3],
        duration_ms=int((time.monotonic() - started) * 1000),
        fallback_used=spent[0] != requested_model,
        provider_cost_usd=provider_cost,
    )
