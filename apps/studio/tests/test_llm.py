"""One agent turn against a stand-in for the Anthropic client.

What is pinned: the request (model, effort, structured output, the cached
brand block, the fallback beta), and that every way a turn can go wrong ends
as a sentence a person can act on rather than a stack trace.
"""

from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from apps.studio import llm
from apps.studio.models import AgentRun
from apps.studio.schemas import ReviewAnswer
from apps.studio.tests.conftest import review_answer


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


def _response(text, *, stop_reason="end_turn", iterations=(), **extra):
    usage = SimpleNamespace(
        input_tokens=900,
        cache_creation_input_tokens=300,
        cache_read_input_tokens=2000,
        output_tokens=450,
        iterations=list(iterations),
    )
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        usage=usage,
        model="claude-opus-5-5",
        _request_id="req_123",
        **extra,
    )


@pytest.fixture
def claude(monkeypatch, settings):
    settings.ANTHROPIC_API_KEY = "sk-ant-test"
    settings.STUDIO_MODEL = "claude-opus-5-5"
    settings.STUDIO_EFFORT = ""
    settings.STUDIO_FALLBACKS = True
    fake = FakeMessages(_response(review_answer().model_dump_json()))
    monkeypatch.setattr(llm, "get_client", lambda: SimpleNamespace(beta=SimpleNamespace(messages=fake)))
    return fake


SYSTEM = [
    {"type": "text", "text": "You are the brand reviewer."},
    {"type": "text", "text": "Brand: Neopolis", "cache_control": {"type": "ephemeral"}},
]


def _run(**overrides):
    kwargs = {
        "agent": "reviewer",
        "system": SYSTEM,
        "content": [llm.text_block("Review this post.")],
        "output_type": ReviewAnswer,
        "effort": "medium",
    }
    kwargs.update(overrides)
    return llm.run_agent(**kwargs)


def _api_error(cls, status, message="nope"):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(message, response=httpx2.Response(status, request=request), body=None)


class TestTheRequest:
    def test_structured_output_effort_and_fallback(self, claude):
        result = _run()

        request = claude.requests[0]
        assert request["model"] == "claude-opus-5-5"
        assert request["system"] == SYSTEM
        assert request["messages"] == [{"role": "user", "content": [{"type": "text", "text": "Review this post."}]}]
        assert request["output_config"]["effort"] == "medium"
        assert request["output_config"]["format"]["type"] == "json_schema"
        assert request["output_config"]["format"]["schema"]["type"] == "object"
        assert request["betas"] == [llm.FALLBACK_BETA] and request["fallbacks"] == "default"
        # Thinking is adaptive on this model and must not be switched off or budgeted.
        assert "thinking" not in request
        assert "tool_choice" not in request

        assert result.output.verdict == "approve"
        assert (result.input_tokens, result.output_tokens, result.cache_read_tokens) == (1200, 450, 2000)
        assert result.model == "claude-opus-5-5"
        assert result.fallback_used is False

    def test_the_fallback_can_be_turned_off(self, claude, settings):
        settings.STUDIO_FALLBACKS = False

        _run()

        assert "betas" not in claude.requests[0] and "fallbacks" not in claude.requests[0]

    def test_one_effort_for_every_agent_when_set(self, claude, settings):
        settings.STUDIO_EFFORT = "high"
        _run(effort="low")
        settings.STUDIO_EFFORT = "turbo"  # not a level: each agent keeps its own
        _run(effort="low")

        assert [r["output_config"]["effort"] for r in claude.requests] == ["high", "low"]

    def test_a_fallback_answer_is_noted(self, claude):
        claude.response = _response(
            review_answer().model_dump_json(),
            iterations=[SimpleNamespace(type="message"), SimpleNamespace(type="fallback_message")],
        )

        assert _run().fallback_used is True

    def test_images_go_as_downscaled_jpeg(self):
        from apps.studio.tests.conftest import jpeg_bytes

        block = llm.image_block(jpeg_bytes(3000, 2000))

        assert block["type"] == "image"
        assert block["source"]["media_type"] == "image/jpeg"
        import base64
        import io

        from PIL import Image

        with Image.open(io.BytesIO(base64.b64decode(block["source"]["data"]))) as image:
            assert max(image.size) == llm.IMAGE_MAX_SIDE


class TestWhenATurnGoesWrong:
    def test_without_a_key_nothing_is_sent(self, claude, settings):
        settings.ANTHROPIC_API_KEY = " "

        with pytest.raises(llm.NotConfiguredError, match="ANTHROPIC_API_KEY"):
            _run()
        assert claude.requests == []

    def test_a_refusal_says_so_and_how_to_move_on(self, claude):
        claude.response = _response("", stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"))

        with pytest.raises(llm.StudioAgentError, match="declined.*cyber.*Rephrase"):
            _run()

    def test_a_cut_off_answer_is_not_trusted(self, claude):
        claude.response = _response('{"verdict": "appr', stop_reason="max_tokens")

        with pytest.raises(llm.StudioAgentError, match="cut off"):
            _run()

    def test_an_answer_in_the_wrong_shape(self, claude):
        claude.response = _response('{"verdict": "maybe"}')

        with pytest.raises(llm.StudioAgentError, match="expected shape"):
            _run()

    @pytest.mark.parametrize(
        ("error", "says"),
        [
            (_api_error(anthropic.AuthenticationError, 401), "rejected ANTHROPIC_API_KEY"),
            (_api_error(anthropic.PermissionDeniedError, 403), "isn't allowed to use claude-opus-5-5"),
            (_api_error(anthropic.NotFoundError, 404), "doesn't know the model"),
            (_api_error(anthropic.RateLimitError, 429), "rate-limiting"),
            (
                _api_error(anthropic.BadRequestError, 400, "prompt is too long"),
                "refused the request: prompt is too long",
            ),
            (_api_error(anthropic.InternalServerError, 529), "HTTP 529"),
            (
                anthropic.APITimeoutError(request=httpx2.Request("POST", "https://api.anthropic.com")),
                "too long to answer",
            ),
            (
                anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")),
                "Couldn't reach",
            ),
        ],
    )
    def test_api_errors_become_sentences(self, claude, error, says):
        claude.error = error

        with pytest.raises(llm.StudioAgentError) as raised:
            _run()

        assert says in str(raised.value)
        assert raised.value.__cause__ is error


class TestCost:
    def _run_row(self, agent, model="claude-opus-5-5", status="succeeded", **tokens):
        return AgentRun(agent=agent, model=model, status=status, **tokens)

    def test_tokens_at_list_price_plus_pictures(self):
        runs = [
            self._run_row("copywriter", input_tokens=1_000_000, output_tokens=100_000, cache_read_tokens=1_000_000),
            self._run_row("illustrator"),
            self._run_row("illustrator", status="failed"),
        ]

        assert llm.estimate_cost(runs) == pytest.approx(4.0 + 2.0 + 0.2 + llm.PICTURE_PRICE)

    def test_an_unknown_model_has_no_estimate(self):
        assert llm.estimate_cost([self._run_row("copywriter", model="claude-x", input_tokens=10)]) is None
