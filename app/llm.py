"""OpenRouter client with a model fallback chain.

Each model in MODEL_CHAIN is tried in order. A model is skipped (next one tried) on:
rate limit, 5xx, timeout, network error, empty reply, or a reply that is not usable JSON.
If every model fails, AllModelsFailed is raised and the API answers 502, which the
front-end shows as "OpenRouter API is not working".
"""
import datetime
import time

import httpx

from . import config

URL = "https://openrouter.ai/api/v1/chat/completions"

# Free variants that advertise `response_format` support on OpenRouter. The free 550B
# model does NOT, so for it we rely on the prompt + tolerant JSON parsing.
JSON_MODE_MODELS = {
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "google/gemma-4-31b-it:free",
}


# Free reasoning models can spend minutes "thinking" (and sometimes return empty text).
# Thinking is switched off where the model allows it; the 550B model is asked for low effort.
LOW_EFFORT_MODELS = {"nvidia/nemotron-3-ultra-550b-a55b:free"}


class BadModelOutput(Exception):
    """The model answered, but the answer is not usable."""


class AllModelsFailed(Exception):
    def __init__(self, code: str, message: str, attempts: list[dict]):
        super().__init__(message)
        self.code = code
        self.message = message
        self.attempts = attempts


_calls = {"day": "", "count": 0}


def _count_call() -> None:
    """Count requests sent to OpenRouter today (UTC) — the free tier allows ~50/day."""
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    if _calls["day"] != today:
        _calls["day"], _calls["count"] = today, 0
    _calls["count"] += 1


def calls_today() -> int:
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    return _calls["count"] if _calls["day"] == today else 0


def _short(text, limit: int = 180) -> str:
    text = " ".join(str(text).split())
    return text[:limit]


def _provider_message(response: httpx.Response) -> str:
    try:
        data = response.json()
        err = data.get("error", data)
        if isinstance(err, dict):
            return _short(err.get("message") or err)
        return _short(err)
    except Exception:
        return _short(response.text)


async def run_chain(
    messages: list[dict], parse_fn, *, max_tokens: int | None = None, prefer: str | None = None, on_event=None
):
    """Return (parsed_result, meta). Raises AllModelsFailed when nothing worked.

    `prefer` moves one model to the front (the one that just answered the previous
    stage), so an overloaded primary is not retried for every stage.
    """
    chain = list(config.MODEL_CHAIN)
    if prefer in chain:
        chain = [prefer] + [m for m in chain if m != prefer]

    def emit(event: dict) -> None:
        """Tell the caller which model is being tried / failed, as it happens (drives the live workflow)."""
        if on_event:
            on_event(event)
    if not config.OPENROUTER_API_KEY:
        raise AllModelsFailed(
            "LLM_AUTH",
            "The server has no OPENROUTER_API_KEY configured, so no model can be called.",
            [],
        )

    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "Hermes Email Assistant",
    }
    started = time.monotonic()
    attempts: list[dict] = []

    async with httpx.AsyncClient() as client:
        for model in chain:
            remaining = config.LLM_DEADLINE_S - (time.monotonic() - started)
            if remaining < 5:
                attempts.append({"model": model, "status": None, "reason": "skipped_deadline", "ms": 0})
                continue

            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": max_tokens or config.LLM_MAX_TOKENS,
                "reasoning": {"effort": "low"} if model in LOW_EFFORT_MODELS else {"enabled": False},
            }
            if model in JSON_MODE_MODELS:
                payload["response_format"] = {"type": "json_object"}

            emit({"event": "model_try", "model": model})
            t0 = time.monotonic()

            def log(status, reason, detail=None):
                entry = {
                    "model": model,
                    "status": status,
                    "reason": reason,
                    "ms": int((time.monotonic() - t0) * 1000),
                }
                if detail:
                    entry["detail"] = detail
                attempts.append(entry)
                if reason != "ok":
                    emit({"event": "model_fail", "model": model, "reason": reason, "status": status, "ms": entry["ms"]})

            _count_call()
            try:
                response = await client.post(
                    URL, headers=headers, json=payload, timeout=min(config.LLM_TIMEOUT_S, remaining)
                )
            except httpx.TimeoutException:
                log(None, "timeout")
                continue
            except httpx.HTTPError as exc:
                log(None, "network_error", _short(exc))
                continue

            status = response.status_code
            if status == 401:
                log(status, "invalid_api_key", _provider_message(response))
                raise AllModelsFailed(
                    "LLM_AUTH", "OpenRouter rejected the API key (HTTP 401).", attempts
                )
            if status == 402:
                log(status, "insufficient_credits", _provider_message(response))
                raise AllModelsFailed(
                    "LLM_CREDITS", "OpenRouter reports insufficient credits (HTTP 402).", attempts
                )
            if status != 200:
                log(status, "rate_limited" if status == 429 else f"http_{status}", _provider_message(response))
                continue

            try:
                data = response.json()
            except ValueError:
                log(status, "invalid_response", "Response was not JSON")
                continue
            if isinstance(data, dict) and data.get("error"):
                log(status, "provider_error", _short(data["error"]))
                continue

            try:
                content = data["choices"][0]["message"].get("content") or ""
            except (KeyError, IndexError, TypeError, AttributeError):
                log(status, "invalid_response", "No choices in response")
                continue
            if not content.strip():
                log(status, "empty_content", "Model returned no text (reasoning may have used the token budget)")
                continue

            try:
                parsed = parse_fn(content)
            except BadModelOutput as exc:
                log(status, "bad_output", _short(exc))
                continue

            log(status, "ok")
            meta = {
                "model": model,
                "mock": False,
                "cached": False,
                "attempts": len(attempts),
                "attempt_log": attempts,
            }
            return parsed, meta

    raise AllModelsFailed(
        "LLM_UNAVAILABLE",
        f"The OpenRouter API is not working. All {len(chain)} models failed.",
        attempts,
    )
