"""The two-stage workflow: event order, streaming endpoint, sticky model, failure stages."""
import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from app import config, llm, pipeline
from app.main import app

client = TestClient(app)


def collect(subject, body, **kw):
    async def run():
        return [e async for e in pipeline.analyze_events(subject, body, **kw)]

    return asyncio.run(run())


def names(events):
    """Workflow step events only (model_try / model_fail / ping are reported separately)."""
    return [e["event"] for e in events if e["event"] not in ("ping", "model_try", "model_fail", "model_skip")]


def test_mock_workflow_emits_every_step_in_order():
    events = collect("Urgent shipment of pharmaceutical samples", "move pharmaceutical samples from Mumbai to Frankfurt urgently")
    assert names(events) == [
        "received", "router_start", "router_done", "skill_loaded", "skill_start", "skill_done", "validation", "done",
    ]
    router = next(e for e in events if e["event"] == "router_done")
    assert router["category"] == "Freight Quotation Enquiry"
    loaded = next(e for e in events if e["event"] == "skill_loaded")
    assert loaded["file"] == "freight_quotation.md"
    validation = next(e for e in events if e["event"] == "validation")
    assert {c["name"] for c in validation["checks"]} >= {"Grounding", "Transport mode", "Missing information", "Draft guard"}
    done = events[-1]["result"]
    assert done["mode"] == "UNKNOWN" and done["checks"] and done["meta"]["router_mode"] == "mock"


def test_user_example_with_typos_is_freight_with_unknown_mode():
    events = collect("price quation for mumbai to new york", "give me price qatation for sending textile from mumbai port to new york")
    result = events[-1]["result"]
    assert result["category"] == "Freight Quotation Enquiry"
    assert result["mode"] == "UNKNOWN"  # "mumbai port" must not decide the mode
    assert result["fields"]["commodity"]["value"] == "textile"
    assert "mode" in {m["field"] for m in result["missing_information"]}


def test_stream_endpoint_returns_ndjson_events():
    with client.stream("POST", "/api/analyze/stream", json={"subject": "Request for shipping documents", "body": "Please share the final bill of lading and invoice for the shipment delivered last week."}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-ndjson")
        events = [json.loads(line) for line in r.iter_lines() if line.strip()]
    assert [e["event"] for e in events][-1] == "done"
    assert events[-1]["result"]["category"] == "Documentation"


def test_stream_endpoint_rejects_empty_email_with_plain_json_error():
    r = client.post("/api/analyze/stream", json={"subject": "", "body": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "EMPTY_EMAIL"


def test_health_reports_router_mode_and_quota_counter():
    data = client.get("/api/health").json()
    assert data["router_mode"] == "mock" and "ai_calls_today" in data and data["free_daily_limit"] == 50


# ---------------------------------------------------------------- real (non-mock) two-stage with a fake OpenRouter


def _fake_openrouter(monkeypatch, handler):
    monkeypatch.setattr(config, "MOCK_LLM", False)
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(config, "ROUTER_MODE", "two_stage")
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))
    pipeline._CACHE.clear()


def _reply(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


def test_two_stage_uses_router_then_only_the_chosen_skill_and_sticks_to_the_working_model(monkeypatch):
    monkeypatch.setattr(config, "MODEL_CHAIN", ["m1", "m2", "m3"])
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        system = payload["messages"][0]["content"]
        stage = "router" if system.startswith("You are the ROUTER AGENT") else "skill"
        calls.append((stage, payload["model"], system))
        if payload["model"] == "m1":  # primary is overloaded
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        if stage == "router":
            return _reply({"category": "Payment", "category_confidence": "high", "category_reason": "asks about an invoice"})
        return _reply({
            "category": "Payment", "fields": {"invoice_number": {"value": "INV-9", "evidence": "invoice INV-9"}},
            "draft_reply": {"subject": "Re", "body": "Dear Customer,\n\nThank you. The payment needs to be verified with accounts.\n\nBest regards,\nHermes Team"},
        })

    _fake_openrouter(monkeypatch, handler)
    events = collect("Payment query", "Did you get my payment for invoice INV-9?", fresh=True)
    assert names(events) == ["received", "router_start", "router_done", "skill_loaded", "skill_start", "skill_done", "validation", "done"]
    # router: m1 failed, m2 answered. skill stage must START with m2 (sticky), never retry m1 first.
    assert [(s, m) for s, m, _ in calls] == [("router", "m1"), ("router", "m2"), ("skill", "m2")]
    # the skill prompt carries ONLY the payment skill, the router prompt carries only descriptions
    skill_prompt = calls[-1][2]
    assert 'SKILL "payment"' in skill_prompt and 'SKILL "freight_quotation"' not in skill_prompt
    assert "Cargo-ready" not in calls[0][2]  # router never sees full skill bodies
    result = events[-1]["result"]
    assert result["category"] == "Payment" and result["fields"]["invoice_number"]["value"] == "INV-9"
    assert result["meta"]["router_model"] == "m2" and result["meta"]["model"] == "m2"
    stages = [a["stage"] for a in result["meta"]["attempt_log"]]
    assert stages == ["router", "router", "skill"]


def test_model_events_show_which_model_is_tried_and_which_one_failed(monkeypatch):
    monkeypatch.setattr(config, "MODEL_CHAIN", ["m1", "m2"])

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        system = payload["messages"][0]["content"]
        if payload["model"] == "m1":
            return httpx.Response(200, json={"error": {"message": "Service temporarily overloaded"}})
        if system.startswith("You are the ROUTER AGENT"):
            return _reply({"category": "Other", "category_confidence": "low"})
        return _reply({"fields": {}, "draft_reply": {"subject": "Re", "body": "Dear Customer,\n\nThanks.\n\nBest regards,\nHermes Team"}})

    _fake_openrouter(monkeypatch, handler)
    events = collect("Hello", "Just saying hi", fresh=True)
    model_events = [(e["event"], e["stage"], e["model"], e.get("reason")) for e in events if e["event"] in ("model_try", "model_fail")]
    assert model_events == [
        ("model_try", "router", "m1", None),
        ("model_fail", "router", "m1", "provider_error"),
        ("model_try", "router", "m2", None),
        ("model_try", "skill", "m2", None),   # sticky: the skill stage starts with the model that worked
    ]
    # the order on the wire: the try/fail events arrive between router_start and router_done
    order = [e["event"] for e in events if e["event"] != "ping"]
    assert order.index("router_start") < order.index("model_try") < order.index("router_done")
    router_done = next(e for e in events if e["event"] == "router_done")
    assert router_done["model"] == "m2" and router_done["attempts"][0]["reason"] == "provider_error"
    skill_done = next(e for e in events if e["event"] == "skill_done")
    assert skill_done["model"] == "m2"


def test_router_failure_ends_with_error_event_naming_the_stage(monkeypatch):
    monkeypatch.setattr(config, "MODEL_CHAIN", ["m1"])
    _fake_openrouter(monkeypatch, lambda request: httpx.Response(429, json={"error": {"message": "limit"}}))
    events = collect("Hi", "Hello there", fresh=True)
    assert names(events) == ["received", "router_start", "error"]
    assert events[-1]["stage"] == "router" and events[-1]["code"] == "LLM_UNAVAILABLE"
    assert events[-1]["attempts"][0]["reason"] == "rate_limited"


def test_skill_stage_failure_keeps_the_category_in_the_error_event(monkeypatch):
    monkeypatch.setattr(config, "MODEL_CHAIN", ["m1"])

    def handler(request):
        system = json.loads(request.content)["messages"][0]["content"]
        if system.startswith("You are the ROUTER AGENT"):
            return _reply({"category": "Shipment Status", "category_confidence": "high"})
        return httpx.Response(503, json={"error": {"message": "down"}})

    _fake_openrouter(monkeypatch, handler)
    events = collect("Where is it", "AWB 176-12345675?", fresh=True)
    error = events[-1]
    assert error["event"] == "error" and error["stage"] == "skill" and error["category"] == "Shipment Status"


def test_second_identical_email_is_replayed_from_cache_without_new_ai_calls(monkeypatch):
    monkeypatch.setattr(config, "MODEL_CHAIN", ["m1"])
    count = {"n": 0}

    def handler(request):
        count["n"] += 1
        system = json.loads(request.content)["messages"][0]["content"]
        if system.startswith("You are the ROUTER AGENT"):
            return _reply({"category": "General Business Email", "category_confidence": "high"})
        return _reply({"fields": {}, "draft_reply": {"subject": "Re", "body": "Dear Customer,\n\nThanks.\n\nBest regards,\nHermes Team"}})

    _fake_openrouter(monkeypatch, handler)
    collect("Meeting", "Can we meet next week?", fresh=True)
    assert count["n"] == 2
    again = collect("Meeting", "Can we meet next week?")
    assert count["n"] == 2  # nothing new was sent
    assert again[-1]["result"]["meta"]["cached"] is True
    assert "router_done" in names(again)
