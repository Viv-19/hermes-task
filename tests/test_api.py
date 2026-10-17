"""End-to-end through the HTTP API in mock mode (no network, no quota)."""
import asyncio
import json

from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)
SAMPLES = {s["id"]: s for s in json.loads(config.SAMPLES_FILE.read_text(encoding="utf-8"))}


def analyze(sample_id):
    s = SAMPLES[sample_id]
    response = client.post("/api/analyze", json={"subject": s["subject"], "body": s["body"]})
    assert response.status_code == 200, response.text
    return response.json()


def test_health():
    data = client.get("/api/health").json()
    assert data["ok"] is True and data["mock"] is True


def test_samples_endpoint_lists_the_four_assessment_tests():
    ids = [s["id"] for s in client.get("/api/samples").json()]
    assert ids[:4] == ["t1", "t2", "t3", "t4"]


def test_index_page_is_served():
    assert client.get("/").status_code == 200


def test_t1():
    r = analyze("t1")
    assert (r["category"], r["mode"]) == ("Freight Quotation Enquiry", "AIR")
    assert r["fields"]["origin"]["value"] == "Mumbai"
    assert r["meta"]["mock"] is True
    assert r["draft_reply"]["source"] == "ai"  # the canned draft passes every guard


def test_t2():
    r = analyze("t2")
    assert (r["category"], r["mode"], r["submode"]) == ("Freight Quotation Enquiry", "OCEAN", "FCL")
    assert r["fields"]["incoterm"]["value"] == "FOB"


def test_t3_is_documentation_not_freight():
    r = analyze("t3")
    assert r["category"] == "Documentation"
    assert r["mode"] is None


def test_t4_mode_unknown_and_asks_for_key_details():
    r = analyze("t4")
    assert r["mode"] == "UNKNOWN"
    keys = {m["field"] for m in r["missing_information"]}
    assert {"gross_weight", "dimensions_or_cbm", "delivery_deadline"} <= keys
    assert r["draft_reply"]["source"] == "ai"


def test_empty_email_is_rejected():
    r = client.post("/api/analyze", json={"subject": " ", "body": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "EMPTY_EMAIL"


def test_too_long_email_is_rejected():
    r = client.post("/api/analyze", json={"subject": "x", "body": "a" * 20000})
    assert r.status_code == 422 and r.json()["error"]["code"] == "TOO_LONG"


def test_all_models_failing_returns_502_with_the_openrouter_message(monkeypatch):
    monkeypatch.setattr(config, "MOCK_LLM", False)
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")  # no key -> LLM_AUTH, no network call
    r = client.post("/api/analyze", json={"subject": "Hi", "body": "Hello there"})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "LLM_AUTH"


def test_fallback_chain_skips_failing_models(monkeypatch):
    """First model returns 429, second returns junk, third returns good JSON."""
    import httpx

    from app import llm

    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(config, "MODEL_CHAIN", ["m1", "m2", "m3"])
    good = {"choices": [{"message": {"content": '{"category": "Other", "fields": {}}'}}]}

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        if model == "m1":
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        if model == "m2":
            return httpx.Response(200, json={"choices": [{"message": {"content": "not json at all"}}]})
        return httpx.Response(200, json=good)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw))

    from app.pipeline import parse_model_output

    parsed, meta = asyncio.run(llm.run_chain([{"role": "user", "content": "x"}], parse_model_output))
    assert parsed["category"] == "Other"
    assert meta["model"] == "m3"
    assert [a["reason"] for a in meta["attempt_log"]] == ["rate_limited", "bad_output", "ok"]
