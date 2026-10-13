"""The OpenRouter boundary, exercised with an HTTP transport that cannot go online.

These checks cover the wire contract and failures which must preserve spend
without trusting a malformed answer or exposing brand prompts and credentials.
"""

from __future__ import annotations

import json
import traceback
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from apps.studio import llm, openrouter
from apps.studio.schemas import ReviewAnswer
from apps.studio.tests.conftest import jpeg_bytes, review_answer

MODEL = "anthropic/claude-sonnet-4.5"
API_KEY = "sk-or-test-never-a-real-key"
USAGE = {
    "prompt_tokens": 300,
    "completion_tokens": 50,
    "prompt_tokens_details": {"cached_tokens": 100, "cache_write_tokens": 40},
}
# OpenRouter prompt_tokens includes cache reads and writes. Cache writes carry
# the same 1.25x estimate as the Anthropic path, so 300 - 100 - 40 + 40*1.25.
SPENT = (MODEL, 210, 50, 100)
SYSTEM = [
    llm.text_block("You are the brand reviewer."),
    {"type": "text", "text": "Brand: Neopolis", "cache_control": {"type": "ephemeral"}},
]


class _TimedByteStream(httpx.SyncByteStream):
    """Advance a fake clock as bytes arrive, without waiting or using a socket."""

    def __init__(self, clock, chunks):
        self.clock = clock
        self.chunks = chunks

    def __iter__(self):
        for timestamp, chunk in self.chunks:
            self.clock.now = timestamp
            yield chunk


def _response(*, content=None, finish_reason="stop", refusal=None, usage=None, choices=None):
    if content is None:
        content = review_answer().model_dump_json()
    return {
        "id": "gen-test",
        "model": MODEL,
        "choices": choices
        if choices is not None
        else [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content, "refusal": refusal},
            }
        ],
        "usage": USAGE if usage is None else usage,
    }


def _stream_response(*, finish_reason="stop", refusal=None):
    answer = review_answer().model_dump_json()
    middle = len(answer) // 2
    chunks = [
        {"model": MODEL, "choices": [{"index": 0, "delta": {"content": answer[:middle]}}]},
        {"model": MODEL, "choices": [{"index": 0, "delta": {"content": answer[middle:]}}]},
        {
            "model": MODEL,
            "choices": [{"index": 0, "delta": {"refusal": refusal}, "finish_reason": finish_reason}],
        },
        {"model": MODEL, "choices": [], "usage": USAGE},
    ]
    content = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, content=content.encode(), headers={"content-type": "text/event-stream"})


@pytest.fixture
def router(monkeypatch, settings):
    settings.STUDIO_PROVIDER = "openrouter"
    settings.OPENROUTER_API_KEY = API_KEY
    settings.ANTHROPIC_API_KEY = ""
    settings.STUDIO_MODEL = MODEL
    settings.STUDIO_EFFORT = ""
    settings.STUDIO_FALLBACKS = True
    settings.STUDIO_WEB_SEARCH = True
    fake = SimpleNamespace(requests=[], sleeps=[], response=_response(), handler=None)

    def handle(request):
        fake.requests.append(request)
        if fake.handler is not None:
            return fake.handler(request)
        return httpx.Response(200, json=fake.response)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(openrouter, "get_client", lambda: client)
        monkeypatch.setattr(openrouter.time, "sleep", fake.sleeps.append)
        yield fake


def _run(**overrides):
    arguments = {
        "agent": "reviewer",
        "system": SYSTEM,
        "content": [llm.text_block("Review this post.")],
        "output_type": ReviewAnswer,
        "effort": "medium",
    }
    arguments.update(overrides)
    return llm.run_agent(**arguments)


def _sent(router):
    return json.loads(router.requests[-1].content)


class TestProviderConfiguration:
    def test_openrouter_needs_its_own_key_not_an_anthropic_key(self, router, settings):
        assert llm.is_configured()
        settings.OPENROUTER_API_KEY = " "
        settings.ANTHROPIC_API_KEY = "sk-ant-present-but-wrong-provider"

        assert not llm.is_configured()
        with pytest.raises(llm.NotConfiguredError, match="OPENROUTER_API_KEY"):
            _run()
        assert router.requests == []

    def test_the_provider_default_is_a_namespaced_model(self, router, settings):
        settings.STUDIO_MODEL = ""

        _run()

        assert _sent(router)["model"] == MODEL
        assert llm.model_id() == MODEL

    def test_an_old_anthropic_model_id_is_reported_before_any_request(self, router, settings):
        settings.STUDIO_MODEL = "claude-opus-5-5"

        assert not llm.is_configured()
        with pytest.raises(llm.NotConfiguredError, match="namespaced STUDIO_MODEL"):
            _run()
        assert router.requests == []

    def test_unknown_provider_does_not_silently_fall_back_to_anthropic(self, router, settings):
        settings.STUDIO_PROVIDER = "typo"
        settings.ANTHROPIC_API_KEY = "sk-ant-present"

        assert not llm.is_configured()
        with pytest.raises(llm.NotConfiguredError, match="STUDIO_PROVIDER"):
            _run()
        assert router.requests == []

    def test_openrouter_dispatch_preserves_agent_arguments(self, router, monkeypatch):
        captured = {}
        expected = object()

        def run_agent(**arguments):
            captured.update(arguments)
            return expected

        monkeypatch.setattr(openrouter, "run_agent", run_agent)

        assert _run(max_tokens=1234) is expected
        assert captured == {
            "agent": "reviewer",
            "system": SYSTEM,
            "content": [llm.text_block("Review this post.")],
            "output_type": ReviewAnswer,
            "effort": "medium",
            "max_tokens": 1234,
        }
        assert router.requests == []

    def test_research_fails_closed_without_calling_either_provider(self, router, monkeypatch):
        def unexpected():
            pytest.fail("OpenRouter research attempted an Anthropic network call")

        monkeypatch.setattr(llm, "get_client", unexpected)

        assert not llm.web_search_enabled()
        with pytest.raises(llm.StudioAgentError):
            llm.research(agent="researcher", system=SYSTEM, question="Research this property.")
        assert router.requests == []

    def test_release_agency_check_accepts_openrouter_without_an_anthropic_key(self, router, monkeypatch):
        from background_task.models import Task

        from apps.common.management.commands.live_verify import Command

        registered = Mock()
        registered.values_list.return_value = ["run_agency_cycle", "sweep_stuck_studio_briefs"]
        task_filter = Mock(return_value=registered)
        monkeypatch.setattr(Task.objects, "filter", task_filter)
        records = []
        command = Command()
        monkeypatch.setattr(command, "record", lambda result, check, detail: records.append((result, check, detail)))

        command.check_agency()

        task_filter.assert_called_once_with(repeat__gt=0)
        registered.values_list.assert_called_once_with("verbose_name", flat=True)
        key_check = next(record for record in records if record[1] == "agency.openrouter_key")
        assert key_check[0] == "PASS"
        assert MODEL in key_check[2]
        assert not any(record[1] == "agency.anthropic_key" or record[0] == "BLOCKED" for record in records)
        assert next(record[0] for record in records if record[1] == "agency.agents_cannot_approve") == "PASS"
        assert API_KEY not in str(records)
        assert router.requests == []


class TestRequestAndResponse:
    def test_native_request_and_validated_answer(self, router):
        result = _run()

        request = router.requests[0]
        sent = _sent(router)
        assert request.method == "POST"
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["Authorization"] == f"Bearer {API_KEY}"
        assert sent["model"] == MODEL
        assert sent["max_tokens"] == llm.MAX_TOKENS
        assert [message["role"] for message in sent["messages"]] == ["system", "user"]
        system = sent["messages"][0]["content"]
        system_text = system if isinstance(system, str) else "\n".join(block["text"] for block in system)
        assert "You are the brand reviewer." in system_text
        assert "Brand: Neopolis" in system_text
        assert sent["messages"][1]["content"] == [{"type": "text", "text": "Review this post."}]
        schema_format = sent["response_format"]
        assert schema_format["type"] == "json_schema"
        assert schema_format["json_schema"]["strict"] is True
        schema = schema_format["json_schema"]["schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(ReviewAnswer.model_fields)
        assert schema["$defs"]["ReviewCheck"]["additionalProperties"] is False
        assert sent["provider"]["require_parameters"] is True
        assert sent["reasoning"]["effort"] == "medium"
        assert not {"betas", "output_config", "fallbacks", "tools", "tool_choice"} & sent.keys()
        assert "cache_control" not in json.dumps(sent)
        assert not sent.get("stream", False)
        assert result.output == review_answer()
        assert (result.model, result.input_tokens, result.output_tokens, result.cache_read_tokens) == SPENT
        assert result.fallback_used is False
        assert result.duration_ms >= 0

    def test_images_are_openai_data_urls(self, router):
        image = llm.image_block(jpeg_bytes())

        _run(content=[llm.text_block("Judge the graphic."), image])

        content = _sent(router)["messages"][1]["content"]
        assert content[0] == {"type": "text", "text": "Judge the graphic."}
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"] == "data:image/jpeg;base64," + image["source"]["data"]
        assert "source" not in content[1]

    @pytest.mark.parametrize(
        ("effort", "expected"),
        [("low", "low"), ("medium", "medium"), ("high", "high"), ("xhigh", "high"), ("max", "high")],
    )
    def test_effort_stays_within_openrouter_supported_levels(self, router, effort, expected):
        _run(effort=effort)

        assert _sent(router)["reasoning"]["effort"] == expected

    def test_global_effort_override_is_honoured(self, router, settings):
        settings.STUDIO_EFFORT = "max"
        _run(effort="low")
        assert _sent(router)["reasoning"]["effort"] == "high"
        settings.STUDIO_EFFORT = "turbo"
        _run(effort="low")
        assert _sent(router)["reasoning"]["effort"] == "low"

    def test_no_usage_remains_a_valid_zero_cost_result(self, router):
        router.response = _response(usage={})

        result = _run()

        assert (result.input_tokens, result.output_tokens, result.cache_read_tokens) == (0, 0, 0)

    def test_a_different_response_model_is_recorded_for_budget_accounting(self, router):
        router.response["model"] = "anthropic/claude-sonnet-4"

        result = _run()

        assert result.model == "anthropic/claude-sonnet-4"
        assert result.fallback_used is True

    def test_long_answers_stream_and_include_the_final_usage_chunk(self, router):
        router.handler = lambda request: _stream_response()

        result = _run(max_tokens=llm.STREAM_ABOVE_TOKENS + 1)

        sent = _sent(router)
        assert sent["stream"] is True
        assert sent["stream_options"] == {"include_usage": True}
        assert result.output == review_answer()
        assert (result.model, result.input_tokens, result.output_tokens, result.cache_read_tokens) == SPENT

    @pytest.mark.parametrize("finish_reason", ["length", "content_filter"])
    def test_stream_failures_keep_usage_even_when_the_final_chunk_has_no_choice(self, router, finish_reason):
        router.handler = lambda request: _stream_response(finish_reason=finish_reason)

        with pytest.raises(llm.StudioAgentError) as raised:
            _run(max_tokens=llm.STREAM_ABOVE_TOKENS + 1)

        assert raised.value.usage == SPENT

    def test_stream_refusal_keeps_spend(self, router):
        router.handler = lambda request: _stream_response(refusal="not allowed")

        with pytest.raises(llm.StudioAgentError, match="declined") as raised:
            _run(max_tokens=llm.STREAM_ABOVE_TOKENS + 1)

        assert raised.value.usage == SPENT

    def test_a_stream_ending_before_done_cannot_be_trusted(self, router):
        def handle(request):
            response = _stream_response()
            return httpx.Response(200, content=response.content.replace(b"data: [DONE]\n\n", b""))

        router.handler = handle

        with pytest.raises(llm.StudioAgentError, match="cut off") as raised:
            _run(max_tokens=llm.STREAM_ABOVE_TOKENS + 1)

        assert raised.value.usage == SPENT


class TestUnusableAnswers:
    @pytest.mark.parametrize(
        "response",
        [
            _response(refusal="I cannot help with this"),
            _response(finish_reason="content_filter"),
            _response(finish_reason="length", content='{"verdict": "appro'),
            _response(content="This is prose, not JSON."),
            _response(content='{"verdict": "maybe"}'),
            _response(content={"unexpected": "object instead of content text"}),
            _response(choices=[]),
            _response(choices=[{"index": 0, "finish_reason": "stop", "message": {}}]),
        ],
        ids=[
            "refusal",
            "filtered",
            "truncated",
            "invalid-json",
            "schema-mismatch",
            "nontext",
            "no-choice",
            "no-content",
        ],
    )
    def test_refusals_and_invalid_answers_preserve_the_spend(self, router, response):
        router.response = response

        with pytest.raises(llm.StudioAgentError) as raised:
            _run()

        assert raised.value.usage == SPENT
        assert len(router.requests) == 1
        assert router.sleeps == []

    def test_invalid_upstream_json_becomes_an_actionable_error(self, router):
        router.handler = lambda request: httpx.Response(200, text="an upstream proxy returned non-JSON")

        with pytest.raises(llm.StudioAgentError):
            _run()

    def test_a_provider_error_embedded_in_http_200_is_not_an_answer(self, router):
        router.response = {"model": MODEL, "error": {"code": 402, "message": "private provider body"}, "usage": USAGE}

        with pytest.raises(llm.StudioAgentError, match="credits") as raised:
            _run()

        assert raised.value.usage == SPENT
        assert "private provider body" not in str(raised.value)


class TestApiFailures:
    @pytest.mark.parametrize(
        ("status", "message", "attempts"),
        [
            (400, "request", 1),
            (401, "OPENROUTER_API_KEY", 1),
            (402, "credit", 1),
            (403, "permissions", 1),
            (404, "model", 1),
            (408, "too long", 3),
            (409, "HTTP 409", 3),
            (429, "rate", 3),
            (500, "HTTP 500", 3),
            (503, "HTTP 503", 3),
            (504, "too long", 3),
        ],
    )
    def test_status_errors_are_actionable_and_retry_only_transient_failures(self, router, status, message, attempts):
        router.handler = lambda request: httpx.Response(status, json={"error": {"message": "private upstream detail"}})

        with pytest.raises(llm.StudioAgentError) as raised:
            _run()

        assert message.lower() in str(raised.value).lower()
        assert len(router.requests) == attempts
        assert len(router.sleeps) == attempts - 1
        assert "private upstream detail" not in str(raised.value)

    @pytest.mark.parametrize("status", [429, 500])
    def test_a_retry_can_recover_without_duplicate_agent_results(self, router, status):
        def handle(request):
            if len(router.requests) < 3:
                return httpx.Response(status, json={"error": {"message": "retry"}})
            return httpx.Response(200, json=_response())

        router.handler = handle

        result = _run()

        assert result.output == review_answer()
        assert len(router.requests) == 3
        assert len(router.sleeps) == 2

    def test_a_billed_transient_error_is_recorded_without_another_paid_attempt(self, router):
        router.handler = lambda request: httpx.Response(
            503, json={"model": MODEL, "usage": USAGE, "error": {"message": "private failure detail"}}
        )

        with pytest.raises(llm.StudioAgentError, match="HTTP 503") as raised:
            _run()

        assert raised.value.usage == SPENT
        assert len(router.requests) == 1
        assert router.sleeps == []
        assert "private failure detail" not in str(raised.value)

    @pytest.mark.parametrize(
        ("error_type", "attempts"), [(httpx.ConnectError, 3), (httpx.ConnectTimeout, 3), (httpx.ReadTimeout, 1)]
    )
    def test_transport_errors_never_expose_credentials_or_brand_content(self, router, caplog, error_type, attempts):
        prompt = "private prompt text"
        sensitive = f"{prompt} and {API_KEY}"

        def handle(request):
            raise error_type(sensitive, request=request)

        router.handler = handle

        with pytest.raises(llm.StudioAgentError) as raised:
            _run(content=[llm.text_block(prompt)])

        displayed = "".join(traceback.format_exception(raised.value)) + caplog.text
        assert API_KEY not in displayed
        assert prompt not in displayed
        assert len(router.requests) == attempts
        assert len(router.sleeps) == attempts - 1

    def test_a_redirect_cannot_send_the_key_to_another_host(self, router):
        router.handler = lambda request: httpx.Response(302, headers={"location": "https://unexpected.invalid/leak"})

        with pytest.raises(llm.StudioAgentError, match="HTTP 302"):
            _run()

        assert len(router.requests) == 1
        assert router.requests[0].url.host == "openrouter.ai"

    @pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), "invalid"])
    def test_invalid_timeout_is_rejected_before_connecting(self, router, settings, timeout):
        settings.STUDIO_TIMEOUT = timeout

        with pytest.raises(llm.StudioAgentError, match="STUDIO_TIMEOUT"):
            _run()

        assert router.requests == []


class TestBoundedResponseBodies:
    @pytest.mark.parametrize("status", [200, 400], ids=["ordinary-answer", "error-body"])
    def test_slow_body_chunks_use_the_total_deadline(self, router, settings, monkeypatch, status):
        settings.STUDIO_TIMEOUT = 5
        clock = SimpleNamespace(now=0.0)
        monkeypatch.setattr(openrouter.time, "monotonic", lambda: clock.now)
        body = json.dumps(_response() if status == 200 else {"error": {"message": "upstream request error"}}).encode()
        router.handler = lambda request: httpx.Response(
            status, stream=_TimedByteStream(clock, [(1.0, body[:8]), (6.0, body[8:])])
        )

        with pytest.raises(llm.StudioAgentError, match="too long"):
            _run()

        assert len(router.requests) == 1
        assert router.sleeps == []

    def test_an_oversized_response_is_bounded_and_does_not_expose_its_content(self, router, monkeypatch, caplog):
        monkeypatch.setattr(openrouter, "MAX_RESPONSE_BYTES", 16)
        clock = SimpleNamespace(now=0.0)
        body = f"private oversized response {API_KEY}".encode()
        router.handler = lambda request: httpx.Response(200, stream=_TimedByteStream(clock, [(0.0, body)]))

        with pytest.raises(llm.StudioAgentError, match="response size limit") as raised:
            _run()

        displayed = "".join(traceback.format_exception(raised.value)) + caplog.text
        assert API_KEY not in displayed
        assert body.decode() not in displayed
        assert len(router.requests) == 1
        assert router.sleeps == []

    def test_partial_sse_line_cannot_avoid_the_deadline_and_keeps_earlier_usage(self, router, settings, monkeypatch):
        settings.STUDIO_TIMEOUT = 5
        clock = SimpleNamespace(now=0.0)
        monkeypatch.setattr(openrouter.time, "monotonic", lambda: clock.now)
        usage_event = ("data: " + json.dumps({"model": MODEL, "choices": [], "usage": USAGE}) + "\n\n").encode()
        partial_line = b'data: {"choices": ['
        router.handler = lambda request: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_TimedByteStream(clock, [(1.0, usage_event), (6.0, partial_line)]),
        )

        with pytest.raises(llm.StudioAgentError, match="too long") as raised:
            _run(max_tokens=llm.STREAM_ABOVE_TOKENS + 1)

        assert raised.value.usage == SPENT
        assert len(router.requests) == 1
        assert router.sleeps == []
