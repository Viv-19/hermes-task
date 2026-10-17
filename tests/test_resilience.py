"""Circuit breaker: failing models are skipped, the free daily limit is remembered,
and the paid models are the safety net."""
import asyncio
import json
import time

import httpx

from app import config, llm
from app.pipeline import parse_router_output

DAILY_LIMIT = {"error": {"message": "Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day"}}


def _setup(monkeypatch, chain, handler):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(config, "MODEL_CHAIN", chain)
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))


def _ok():
    body = {"choices": [{"message": {"content": json.dumps({"category": "Other", "category_confidence": "low"})}}]}
    return httpx.Response(200, json=body)


def _run(events=None):
    return asyncio.run(
        llm.run_chain([{"role": "user", "content": "x"}], parse_router_output, on_event=events.append if events is not None else None)
    )


def test_a_model_that_just_failed_is_skipped_on_the_next_email(monkeypatch):
    calls = []

    def handler(request):
        model = json.loads(request.content)["model"]
        calls.append(model)
        return httpx.Response(503, json={"error": {"message": "overloaded"}}) if model == "m1" else _ok()

    _setup(monkeypatch, ["m1", "m2"], handler)
    _run()
    events = []
    _run(events)
    assert calls == ["m1", "m2", "m2"]  # second email never touched m1
    skips = [e for e in events if e["event"] == "model_skip"]
    assert skips and skips[0]["model"] == "m1" and skips[0]["reason"] == "cooling_down"


def test_free_daily_limit_blocks_every_free_model_and_goes_to_the_paid_one(monkeypatch):
    calls = []

    def handler(request):
        model = json.loads(request.content)["model"]
        calls.append(model)
        return httpx.Response(429, json=DAILY_LIMIT) if model == "a:free" else _ok()

    _setup(monkeypatch, ["a:free", "b:free", "paid"], handler)
    parsed, meta = _run()
    assert calls == ["a:free", "paid"]  # b:free was not tried: the daily limit applies to all free models
    assert meta["model"] == "paid"

    events = []
    _run(events)
    assert calls == ["a:free", "paid", "paid"]  # next email goes straight to the paid model
    reasons = {e["model"]: e["reason"] for e in events if e["event"] == "model_skip"}
    assert reasons == {"a:free": "daily_limit", "b:free": "daily_limit"}


def test_skipped_models_are_still_a_last_resort(monkeypatch):
    calls = []

    def handler(request):
        model = json.loads(request.content)["model"]
        calls.append(model)
        return httpx.Response(503, json={"error": {"message": "down"}}) if model == "m2" else _ok()

    _setup(monkeypatch, ["m1", "m2"], handler)
    llm._cooldown["m1"] = time.monotonic() + 300  # m1 failed a minute ago
    parsed, meta = _run()
    assert calls == ["m2", "m1"]  # m2 first (m1 is cooling), then m1 because nothing else worked
    assert meta["model"] == "m1"


def test_a_plain_rate_limit_only_cools_that_model_briefly(monkeypatch):
    def handler(request):
        model = json.loads(request.content)["model"]
        return httpx.Response(429, json={"error": {"message": "slow down"}}) if model == "a:free" else _ok()

    _setup(monkeypatch, ["a:free", "b:free"], handler)
    _run()
    assert llm.skip_reason("a:free") == "cooling_down"
    assert llm.skip_reason("b:free") is None  # a normal 429 is not the daily limit


def test_a_model_that_takes_too_long_is_cut_off_and_cooled(monkeypatch):
    """A slow model must be abandoned at the hard time limit, even if the connection stays open."""
    calls = []

    async def handler(request):
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == "slow":
            await asyncio.sleep(10)
        return _ok()

    _setup(monkeypatch, ["slow", "fast"], handler)
    monkeypatch.setattr(config, "LLM_TIMEOUT_S", 0.3)
    started = time.monotonic()
    parsed, meta = _run()
    assert time.monotonic() - started < 5  # did not wait for the slow model
    assert meta["model"] == "fast"
    assert [a["reason"] for a in meta["attempt_log"]] == ["timeout", "ok"]
    assert llm.skip_reason("slow") == "cooling_down"  # and it is skipped on the next email


def test_a_bad_answer_does_not_trigger_the_breaker(monkeypatch):
    def handler(request):
        model = json.loads(request.content)["model"]
        if model == "m1":
            return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
        return _ok()

    _setup(monkeypatch, ["m1", "m2"], handler)
    _run()
    assert llm.skip_reason("m1") is None  # it answered; the answer was just unusable for this email
