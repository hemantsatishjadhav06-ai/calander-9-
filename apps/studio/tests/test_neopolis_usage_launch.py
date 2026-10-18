"""Launch cost controls at the real HTTP/ledger boundaries, without paid calls."""

from __future__ import annotations

import json
import traceback
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pydantic
import pytest

from apps.studio import budget, chat, engine, llm, openrouter, pipeline
from apps.studio.models import AgencyJob, AgencySettings, AgentRun, StudioBrief
from apps.studio.tests.conftest import make_brief
from apps.workspaces.models import Workspace

MODEL = "anthropic/claude-sonnet-4.5"
KEY = "sk-or-launch-test-no-real-credential"
PRIVATE_TEXT = "Private Neopolis campaign notes"


class Answer(pydantic.BaseModel):
    text: str


@pytest.fixture
def router(monkeypatch, settings):
    settings.STUDIO_PROVIDER = "openrouter"
    settings.OPENROUTER_API_KEY = KEY
    settings.STUDIO_MODEL = MODEL
    settings.STUDIO_EFFORT = ""
    settings.STUDIO_TIMEOUT = 300
    fake = SimpleNamespace(requests=[], responses=[], sleeps=[])

    def respond(request):
        fake.requests.append(request)
        response = fake.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(openrouter, "get_client", lambda: client)
        monkeypatch.setattr(openrouter.time, "sleep", fake.sleeps.append)
        yield fake


def _answer(*, usage=None, model=MODEL, content='{"text":"Ready"}', finish="stop"):
    return {
        "model": model,
        "usage": {"prompt_tokens": 100, "completion_tokens": 20} if usage is None else usage,
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
    }


def _call(**kwargs):
    return llm.run_agent(
        agent="copywriter",
        system=[llm.text_block("You write Neopolis drafts.")],
        content=[llm.text_block(PRIVATE_TEXT)],
        output_type=Answer,
        effort="medium",
        **kwargs,
    )


def _row(**fields):
    defaults = {
        "agent": "copywriter",
        "model": MODEL,
        "status": AgentRun.Status.SUCCEEDED,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "output": {},
    }
    return AgentRun(**(defaults | fields))


def _job(world, *, workspace=None):
    return AgencyJob.objects.create(
        workspace=workspace or world.workspace,
        kind=AgencyJob.Kind.REPORT,
        requested_by=world.owner,
        status=AgencyJob.Status.WORKING,
        stage="report",
    )


def _run(world, *, workspace=None, started_at=None, **fields):
    row = _row(**fields)
    row.workspace = workspace or world.workspace
    row.job = _job(world, workspace=workspace)
    if started_at is not None:
        row.started_at = started_at
    row.save()
    return row


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0", "0"), (0, "0"), (0.0, "0"), ("0.0012300", "0.00123"), ("2E-3", "0.002"), (Decimal("1.20"), "1.2")],
)
def test_provider_cost_normalizes_valid_values_and_preserves_zero(value, expected):
    assert llm.validated_provider_cost(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        -1,
        "-0.01",
        "NaN",
        "Infinity",
        "-Infinity",
        float("nan"),
        float("inf"),
        "1e999999",
        "1e-99999",
        "9" * 200,
        "not-money",
        {},
        [],
        KEY,
    ],
)
def test_untrusted_cost_metadata_is_rejected_without_leaking_its_value(value):
    assert llm.validated_provider_cost(value) is None
    error = llm.StudioAgentError("Safe error", provider_cost_usd=value)
    assert error.provider_cost_usd is None and str(error) == "Safe error"


def test_extreme_integer_cost_does_not_raise_during_validation():
    assert llm.validated_provider_cost(10**5000) is None


def test_reported_cost_precedes_estimates_including_valid_zero():
    paid = _row(model="unknown/expensive", input_tokens=100, output={"provider_cost_usd": "0.017", "web_searches": 4})
    free = _row(input_tokens=1_000_000, output={"provider_cost_usd": "0", "web_searches": 4})
    assert budget._run_cost(paid) == Decimal("0.017")
    assert llm.estimate_cost([paid]) == pytest.approx(0.017)
    assert budget._run_cost(free) == Decimal(0)
    assert llm.estimate_cost([free]) == 0


def test_unknown_model_fallback_uses_each_highest_component_but_ui_marks_unpriced():
    row = _row(
        model="unknown/arbitrary-model", input_tokens=1_000_000, output_tokens=1_000_000, cache_read_tokens=1_000_000
    )
    component_rates = [max(price[index] for price in llm.PRICES.values()) for index in range(3)]
    assert budget._run_cost(row) == sum((Decimal(str(rate)) for rate in component_rates), Decimal(0))
    assert llm.estimate_cost([row]) is None


def test_cache_only_and_search_only_calls_are_not_lost():
    cache = _row(cache_read_tokens=1_000_000)
    search = _row(model="unknown/no-token-model", status=AgentRun.Status.FAILED, output={"web_searches": 3})
    assert budget._run_cost(cache) == Decimal("0.3")
    assert budget._run_cost(search) == Decimal("0.03")
    assert llm.estimate_cost([cache, search]) == pytest.approx(0.33)


@pytest.mark.parametrize("counter", [None, -5, "bad", {}, float("nan")])
def test_malformed_search_counters_do_not_crash_budget_display(counter):
    row = _row(input_tokens=100, output={"web_searches": counter, "provider_cost_usd": "NaN"})
    assert budget._run_cost(row) == Decimal("0.0003")


def test_successful_images_count_once_while_failed_or_skipped_estimates_are_zero():
    rows = [_row(agent="illustrator", status=status) for status in ("succeeded", "failed", "skipped")]
    assert budget._run_cost(rows[0]) == Decimal(str(llm.PICTURE_PRICE))
    assert budget._run_cost(rows[1]) == budget._run_cost(rows[2]) == 0
    assert llm.estimate_cost(rows) == pytest.approx(llm.PICTURE_PRICE)


def test_month_reset_uses_neopolis_kolkata_boundary_and_excludes_future_rows(world):
    # November starts in Kolkata at 18:30 UTC on October 31.
    boundary = datetime(2026, 10, 31, 18, 30, tzinfo=UTC)
    previous = _run(world, started_at=boundary - timedelta(microseconds=1), output={"provider_cost_usd": "5"})
    current = _run(world, started_at=boundary, output={"provider_cost_usd": "2"})
    future = _run(world, started_at=boundary + timedelta(days=1), output={"provider_cost_usd": "100"})
    next_month = _run(world, started_at=boundary + timedelta(days=31), output={"provider_cost_usd": "200"})
    assert budget.month_start(world.workspace, boundary).astimezone(UTC) == boundary
    assert budget.month_spend(world.workspace, boundary - timedelta(microseconds=1)) == Decimal("5")
    assert budget.month_spend(world.workspace, boundary) == Decimal("2")
    assert budget.month_spend(world.workspace, future.started_at) == Decimal("102")
    assert previous.pk != current.pk != next_month.pk


def test_month_spend_is_tenant_scoped_even_if_jobs_share_organization(world):
    other = Workspace.objects.create(organization=world.org, name="More Space", timezone="Asia/Kolkata")
    _run(world, output={"provider_cost_usd": "0.019"})
    _run(world, workspace=other, output={"provider_cost_usd": "99"})
    assert budget.month_spend(world.workspace) == Decimal("0.019")
    assert budget.month_spend(other) == Decimal("99")


def test_subcent_spend_stops_at_budget_without_rounding_headroom(world):
    AgencySettings.objects.create(workspace=world.workspace, monthly_budget_usd=Decimal("0.01"))
    _run(world, output={"provider_cost_usd": "0.0096"})
    assert budget.month_spend(world.workspace) == Decimal("0.0096")
    assert budget.remaining(world.workspace) == Decimal("0.0004")
    assert budget.can_spend(world.workspace)
    _run(world, output={"provider_cost_usd": "0.0004"})
    assert not budget.can_spend(world.workspace)


def test_zero_budget_blocks_post_pipeline_before_any_model_or_image_work(world, monkeypatch):
    AgencySettings.objects.create(workspace=world.workspace, monthly_budget_usd=0)
    monkeypatch.setattr(pipeline, "enqueue", lambda *_args: None)
    monkeypatch.setitem(pipeline.STEP_FUNCTIONS, "strategy", lambda _brief: pytest.fail("Zero budget called a model"))
    brief = make_brief(world)
    pipeline.run_step(str(brief.pk), brief.revision, "strategy")
    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.FAILED and "budget" in brief.error
    assert not AgentRun.objects.filter(workspace=world.workspace).exists()


def test_zero_budget_blocks_chat_before_model_or_source_collection(world, monkeypatch):
    from apps.studio import creative_sources
    from apps.studio.roles import client

    AgencySettings.objects.create(workspace=world.workspace, monthly_budget_usd=0)
    monkeypatch.setattr(engine, "enqueue", lambda *_args: None)
    monkeypatch.setattr(client, "account_manager", lambda *_args, **_kwargs: pytest.fail("Zero budget called a model"))
    monkeypatch.setattr(creative_sources, "collect", lambda *_args, **_kwargs: pytest.fail("Zero budget read sources"))
    conversation = chat.general_conversation(world.workspace)
    # Queue while a budget exists, then revoke it before the worker starts.
    AgencySettings.objects.filter(workspace=world.workspace).update(monthly_budget_usd=1)
    posted = chat.post_message(conversation, world.owner, "Make a Neopolis post")
    AgencySettings.objects.filter(workspace=world.workspace).update(monthly_budget_usd=0)
    job = AgencyJob.objects.get(pk=posted.job.pk)
    engine.run_step(str(job.pk), job.revision, job.stage)
    job.refresh_from_db()
    assert job.status == AgencyJob.Status.DONE and job.result["skipped"] == "over budget"
    assert not AgentRun.objects.filter(job=job).exists()


def test_success_uses_provider_actual_cost_for_unknown_models(router, settings):
    settings.STUDIO_MODEL = "unknown/test-model"
    router.responses = [httpx.Response(200, json=_answer(model=settings.STUDIO_MODEL, usage={"cost": "0.0187"}))]
    result = _call()
    assert result.provider_cost_usd == "0.0187"
    assert result.model == settings.STUDIO_MODEL
    assert (result.input_tokens, result.output_tokens, result.cache_read_tokens) == (0, 0, 0)
    assert len(router.requests) == 1
    assert json.loads(router.requests[0].content)["usage"] == {"include": True}


@pytest.mark.parametrize("counter", ["NaN", float("inf"), {}, -9, 10**100, KEY])
def test_impossible_token_counters_do_not_crash_or_contaminate_cost_ledger(router, counter):
    usage = {
        "cost": "0.003",
        "prompt_tokens": counter,
        "completion_tokens": counter,
        "prompt_tokens_details": {"cached_tokens": counter, "cache_write_tokens": counter},
    }
    router.responses = [httpx.Response(200, content=json.dumps(_answer(usage=usage)))]
    result = _call()
    assert (result.input_tokens, result.output_tokens, result.cache_read_tokens) == (0, 0, 0)
    assert result.provider_cost_usd == "0.003"


def test_cache_write_weight_never_exceeds_database_usage_range(router):
    usage = {
        "prompt_tokens": openrouter.MAX_USAGE_TOKENS,
        "prompt_tokens_details": {"cache_write_tokens": openrouter.MAX_USAGE_TOKENS},
    }
    router.responses = [httpx.Response(200, json=_answer(usage=usage))]
    result = _call()
    assert result.input_tokens == openrouter.MAX_USAGE_TOKENS


@pytest.mark.parametrize("cost", ["0.001", "NaN", "-1", "1e100000", {"unexpected": KEY}])
def test_transient_paid_or_malformed_billing_response_never_retries(router, cost, caplog):
    router.responses = [
        httpx.Response(503, json={"error": {"message": f"{KEY} {PRIVATE_TEXT}"}, "usage": {"cost": cost}})
    ]
    with pytest.raises(llm.StudioAgentError) as raised:
        _call()
    assert len(router.requests) == 1 and router.sleeps == []
    assert raised.value.provider_cost_usd == llm.validated_provider_cost(cost)
    diagnostic = "".join(traceback.format_exception(raised.value)) + caplog.text
    assert KEY not in diagnostic and PRIVATE_TEXT not in diagnostic


def test_zero_charge_transient_can_retry_and_final_usage_is_one_paid_turn(router):
    router.responses = [
        httpx.Response(429, json={"error": {"message": "Rate limited"}, "usage": {"cost": 0}}),
        httpx.Response(200, json=_answer(usage={"cost": "0.005", "prompt_tokens": 100, "completion_tokens": 20})),
    ]
    result = _call()
    assert len(router.requests) == 2 and router.sleeps == [1]
    assert result.provider_cost_usd == "0.005" and result.input_tokens == 100


def test_retry_after_connect_error_does_not_duplicate_reported_spend(router):
    router.responses = [
        httpx.ConnectError(f"{KEY} {PRIVATE_TEXT}"),
        httpx.Response(200, json=_answer(usage={"cost": ".02"})),
    ]
    result = _call()
    assert len(router.requests) == 2 and result.provider_cost_usd == "0.02"


@pytest.mark.parametrize("failure", ["shape", "refusal", "length", "missing_choice", "provider_error"])
def test_unusable_paid_answers_preserve_provider_dollars_and_tokens(router, failure):
    response = _answer(usage={"cost": "0.0123", "prompt_tokens": 100, "completion_tokens": 20})
    if failure == "shape":
        response["choices"][0]["message"]["content"] = f'{{"private":"{KEY} {PRIVATE_TEXT}"}}'
    elif failure == "refusal":
        response["choices"][0]["message"]["refusal"] = f"{KEY} {PRIVATE_TEXT}"
    elif failure == "length":
        response["choices"][0]["finish_reason"] = "length"
    elif failure == "missing_choice":
        response["choices"] = []
    else:
        response["error"] = {"code": 500, "message": f"{KEY} {PRIVATE_TEXT}"}
    router.responses = [httpx.Response(200, json=response)]
    with pytest.raises(llm.StudioAgentError) as raised:
        _call()
    assert raised.value.provider_cost_usd == "0.0123"
    assert raised.value.usage == (MODEL, 100, 20, 0)
    assert KEY not in str(raised.value) and PRIVATE_TEXT not in str(raised.value)
    assert len(router.requests) == 1


def _sse(items, *, done=True):
    content = "".join(f"data: {json.dumps(item)}\n\n" for item in items)
    return httpx.Response(200, content=content + ("data: [DONE]\n\n" if done else ""))


def test_stream_usage_fragments_preserve_tokens_cache_and_later_cost_without_double_count(router):
    usage = {"prompt_tokens": 300, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 100}}
    router.responses = [
        _sse(
            [
                {"choices": [{"delta": {"content": '{"text":"Ready"}'}, "finish_reason": "stop"}]},
                {"usage": usage},
                {"usage": {"cost": "0.012", "prompt_tokens_details": {"cache_write_tokens": 40}}},
                {"usage": {"cost": "0.012"}},
                {"usage": {"cost": None, "prompt_tokens": None}},
            ]
        )
    ]
    result = _call(max_tokens=llm.STREAM_ABOVE_TOKENS + 1)
    assert result.provider_cost_usd == "0.012"
    assert (result.input_tokens, result.output_tokens, result.cache_read_tokens) == (210, 20, 100)
    assert json.loads(router.requests[0].content)["usage"] == {"include": True}


@pytest.mark.parametrize("failure", ["provider_error", "malformed_chunk", "cutoff"])
def test_stream_failure_retains_last_reported_cost(router, failure):
    items = [{"usage": {"cost": "0.015", "prompt_tokens": 123}}]
    if failure == "provider_error":
        items.append({"error": {"code": 500, "message": KEY}})
    elif failure == "malformed_chunk":
        items.append({"choices": [{"delta": {"content": {"key": KEY}}}]})
    router.responses = [_sse(items, done=failure != "cutoff")]
    with pytest.raises(llm.StudioAgentError) as raised:
        _call(max_tokens=llm.STREAM_ABOVE_TOKENS + 1)
    assert raised.value.provider_cost_usd == "0.015"
    assert raised.value.usage == (MODEL, 123, 0, 0)
    assert KEY not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize("model", [KEY, f"vendor/{KEY}", PRIVATE_TEXT, "vendor/" + "x" * 101])
def test_provider_cannot_echo_a_key_or_private_text_as_ledger_model(router, model):
    router.responses = [httpx.Response(200, json=_answer(model=model))]
    result = _call()
    assert result.model == MODEL


def test_actual_http_result_cost_survives_engine_end_and_untrusted_schema_output(world, router):
    router.responses = [httpx.Response(200, json=_answer(usage={"cost": "0.0199"}))]
    job = _job(world)
    run, result = engine.call(job, "copywriter", _call)
    run.refresh_from_db()
    assert run.output["provider_cost_usd"] == "0.0199"
    engine.end(run, summary="Ready", output={"provider_cost_usd": "999", "text": "Ready"}, result=result)
    run.refresh_from_db()
    assert run.output == {"provider_cost_usd": "0.0199", "text": "Ready"}
    assert budget.month_spend(world.workspace) == Decimal("0.0199")


def test_cost_only_provider_failure_is_recorded_in_failed_engine_run(world, router):
    router.responses = [httpx.Response(503, json={"error": {"message": KEY}, "usage": {"cost": "0.004"}})]
    job = _job(world)
    with pytest.raises(llm.StudioAgentError):
        engine.call(job, "copywriter", _call)
    run = AgentRun.objects.get(job=job)
    assert run.status == AgentRun.Status.FAILED and run.output["provider_cost_usd"] == "0.004"
    assert run.input_tokens == run.output_tokens == 0
    assert budget.month_spend(world.workspace) == Decimal("0.004")


def test_paid_tokens_on_failed_retry_response_are_not_discarded(world, router):
    router.responses = [httpx.Response(502, json={"usage": {"prompt_tokens": 100, "completion_tokens": 10}})]
    job = _job(world)
    with pytest.raises(llm.StudioAgentError):
        engine.call(job, "copywriter", _call)
    assert len(router.requests) == 1
    run = AgentRun.objects.get(job=job)
    assert (run.input_tokens, run.output_tokens) == (100, 10)
    assert budget.month_spend(world.workspace) == Decimal("0.00045")
