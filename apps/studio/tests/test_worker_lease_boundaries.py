from types import SimpleNamespace
from unittest.mock import Mock

import anthropic
import httpx
import httpx2
import pydantic
import pytest

from apps.blog import ai_images
from apps.common.background import WorkerLeaseLostError, worker_lease_checks
from apps.studio import llm, openrouter


class Answer(pydantic.BaseModel):
    text: str


def _lost_lease():
    raise RuntimeError("Worker session disappeared")


def test_anthropic_turn_never_calls_a_provider_after_lease_loss(settings, monkeypatch):
    settings.STUDIO_PROVIDER = "anthropic"
    settings.ANTHROPIC_API_KEY = "synthetic-lease-test"
    fake = Mock()
    monkeypatch.setattr(llm, "get_client", lambda: SimpleNamespace(beta=SimpleNamespace(messages=fake)))
    with worker_lease_checks(_lost_lease), pytest.raises(WorkerLeaseLostError):
        llm.run_agent(agent="planner", system=[], content=[], output_type=Answer, effort="low")
    fake.create.assert_not_called()
    fake.stream.assert_not_called()


def test_anthropic_sdk_internal_retry_rechecks_the_worker_lease(monkeypatch):
    requests, checks = [], []

    def respond(request):
        requests.append(request)
        return httpx2.Response(500, json={"error": {"type": "api_error", "message": "Retry"}})

    def check():
        checks.append(True)
        if len(checks) > 1:
            _lost_lease()

    original = anthropic.DefaultHttpxClient
    monkeypatch.setattr(
        anthropic,
        "DefaultHttpxClient",
        lambda **kwargs: original(transport=httpx2.MockTransport(respond), **kwargs),
    )
    llm._client.cache_clear()
    client = llm._client("synthetic-sdk-lease-test", 1.0)
    monkeypatch.setattr(client, "_calculate_retry_timeout", lambda *_args, **_kwargs: 0)
    try:
        with worker_lease_checks(check), pytest.raises(WorkerLeaseLostError):
            client.messages.create(model="synthetic-model", max_tokens=10, messages=[{"role": "user", "content": "Hi"}])
        assert len(requests) == 1 and len(checks) == 2
    finally:
        client.close()
        llm._client.cache_clear()


def test_research_continuations_recheck_lease_before_another_paid_turn(settings, monkeypatch):
    settings.STUDIO_PROVIDER = "anthropic"
    settings.ANTHROPIC_API_KEY = "synthetic-research-lease-test"
    response = SimpleNamespace(stop_reason="pause_turn", content=[], model="synthetic-model", usage=None)
    messages = Mock()
    messages.create.return_value = response
    monkeypatch.setattr(llm, "get_client", lambda: SimpleNamespace(messages=messages))
    checks = []

    def check():
        checks.append(True)
        if len(checks) > 1:
            _lost_lease()

    with worker_lease_checks(check), pytest.raises(WorkerLeaseLostError):
        llm.research(agent="trend_scout", system=[], question="Next week")
    assert messages.create.call_count == 1


def test_openrouter_retry_does_not_make_a_second_request_after_lease_loss(settings, monkeypatch):
    settings.STUDIO_PROVIDER = "openrouter"
    settings.OPENROUTER_API_KEY = "synthetic-router-lease-test"
    requests, checks = [], []

    def respond(request):
        requests.append(request)
        return httpx.Response(500, json={"error": {"code": 500}})

    def check():
        checks.append(True)
        if len(checks) > 1:
            _lost_lease()

    monkeypatch.setattr(openrouter.time, "sleep", lambda _seconds: None)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(openrouter, "get_client", lambda: client)
        with worker_lease_checks(check), pytest.raises(WorkerLeaseLostError):
            llm.run_agent(agent="planner", system=[], content=[], output_type=Answer, effort="low")
    assert len(requests) == 1 and len(checks) == 2


def test_fal_image_generation_stops_before_a_paid_request_after_lease_loss(settings):
    settings.FAL_KEY = "synthetic-image-lease-test"
    client = Mock()
    with worker_lease_checks(_lost_lease), pytest.raises(WorkerLeaseLostError):
        ai_images.generate_from_prompt("A reviewed illustrative scene", client=client)
    client.post.assert_not_called()
