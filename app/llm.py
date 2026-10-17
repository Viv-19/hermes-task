"""OpenRouter client with a model fallback chain and a circuit breaker.

Each model in MODEL_CHAIN is tried in order. A model is skipped (next one tried) on:
rate limit, 5xx, timeout, network error, empty reply, or a reply that is not usable JSON.
If every model fails, AllModelsFailed is raised and the API answers 502, which the
front-end shows as "OpenRouter API is not working".

Circuit breaker: a model that just failed (overloaded, timed out, rate limited) is skipped for a few
minutes, so it does not waste a request on every email. If the *free daily limit* is hit, every
":free" model is skipped until midnight UTC. Skipped models are only tried as a last resort.
"""
import asyncio
import datetime
import time

import httpx

from . import config

URL = "https://openrouter.ai/api/v1/chat/completions"

# Models that advertise `response_format` support on OpenRouter. The free 550B model does NOT,
# so for it we rely on the prompt + tolerant JSON parsing.
JSON_MODE_MODELS = {
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia/nemotron-3.5-super-vl:free",
    "google/gemma-4-31b-it:free",
}

# Free reasoning models can spend minutes "thinking" (and sometimes return empty text).
# Thinking is switched off where the model allows it; the 550B model is asked for low effort.
LOW_EFFORT_MODELS = {"nvidia/nemotron-3-ultra-550b-a55b:free", "nvidia/nemotron-3-ultra-550b-a55b"}


class BadModelOutput(Exception):
    """The model answered, but the answer is not usable."""


class AllModelsFailed(Exception):
    def __init__(self, code: str, message: str, attempts: list[dict]):
        super().__init__(message)
        self.code = code
        self.message = message
        self.attempts = attempts


# --------------------------------------------------------------------------- request counter

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


# --------------------------------------------------------------------------- circuit breaker

_cooldown: dict[str, float] = {}        # model -> monotonic time until which it is skipped
_free_blocked = {"until": 0.0}          # all ":free" models are blocked (daily limit) until then


def reset_cooldowns() -> None:
    _cooldown.clear()
    _free_blocked["until"] = 0.0


def _seconds_until_utc_midnight() -> float:
    now = datetime.datetime.now(datetime.timezone.utc)
    midnight = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (midnight - now).total_seconds()


def cooldown_left(model: str) -> float:
    now = time.monotonic()
    left = _cooldown.get(model, 0.0) - now
    if model.endswith(":free"):
        left = max(left, _free_blocked["until"] - now)
    return max(0.0, left)


def skip_reason(model: str) -> str | None:
    """Why a model is being skipped right now (None = it may be used)."""
    if cooldown_left(model) <= 0:
        return None
    if model.endswith(":free") and _free_blocked["until"] > time.monotonic():
        return "daily_limit"
    return "cooling_down"


def _is_daily_limit(detail: str | None) -> bool:
    text = (detail or "").lower()
    return "per-day" in text or "per day" in text or "daily" in text


def _apply_cooldown(model: str, reason: str, status: int | None, detail: str | None) -> None:
    """Remember infrastructure failures (not bad answers) so the same model is not retried at once."""
    now = time.monotonic()
    if reason == "rate_limited":
        if model.endswith(":free") and _is_daily_limit(detail):
            _free_blocked["until"] = now + _seconds_until_utc_midnight()
        else:
            _cooldown[model] = now + 60
    elif reason in ("provider_error", "timeout") or (reason.startswith("http_") and (status or 0) >= 500):
        _cooldown[model] = now + config.MODEL_COOLDOWN_S
    elif reason == "http_404":
        _cooldown[model] = now + 3600


# --------------------------------------------------------------------------- helpers


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


# --------------------------------------------------------------------------- the chain


async def run_chain(
    messages: list[dict], parse_fn, *, max_tokens: int | None = None, prefer: str | None = None, on_event=None
):
    """Return (parsed_result, meta). Raises AllModelsFailed when nothing worked.

    `prefer` moves one model to the front (the one that just answered the previous stage).
    `on_event` receives model_try / model_fail / model_skip events as they happen.
    """
    if not config.OPENROUTER_API_KEY:
        raise AllModelsFailed(
            "LLM_AUTH",
            "The server has no OPENROUTER_API_KEY configured, so no model can be called.",
            [],
        )

    chain = list(config.MODEL_CHAIN)
    if prefer in chain and skip_reason(prefer) is None:
        chain = [prefer] + [m for m in chain if m != prefer]

    def emit(event: dict) -> None:
        if on_event:
            on_event(event)

    ready = [m for m in chain if skip_reason(m) is None]
    cooling = [m for m in chain if skip_reason(m) is not None]
    skipped = []
    for model in cooling:
        info = {"model": model, "reason": skip_reason(model), "seconds": int(cooldown_left(model))}
        skipped.append(info)
        emit({"event": "model_skip", **info})

    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "Hermes Email Assistant",
    }
    started = time.monotonic()
    attempts: list[dict] = []

    async with httpx.AsyncClient() as client:

        async def attempt(model: str):
            """Try one model. Returns (parsed, meta) on success, None on failure."""
            remaining = config.LLM_DEADLINE_S - (time.monotonic() - started)
            if remaining < 5:
                attempts.append({"model": model, "status": None, "reason": "skipped_deadline", "ms": 0})
                return None

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
                    _apply_cooldown(model, reason, status, detail)
                    emit({"event": "model_fail", "model": model, "reason": reason, "status": status, "ms": entry["ms"]})

            _count_call()
            budget = min(config.LLM_TIMEOUT_S, remaining)
            try:
                # httpx's timeout restarts whenever OpenRouter sends a keep-alive byte, so a slow model could
                # run for minutes. wait_for puts a hard limit on the whole request.
                response = await asyncio.wait_for(
                    client.post(URL, headers=headers, json=payload, timeout=budget), timeout=budget + 1
                )
            except (httpx.TimeoutException, asyncio.TimeoutError):
                log(None, "timeout")
                return None
            except httpx.HTTPError as exc:
                log(None, "network_error", _short(exc))
                return None

            status = response.status_code
            if status == 401:
                log(status, "invalid_api_key", _provider_message(response))
                raise AllModelsFailed("LLM_AUTH", "OpenRouter rejected the API key (HTTP 401).", attempts)
            if status == 402:
                log(status, "insufficient_credits", _provider_message(response))
                raise AllModelsFailed("LLM_CREDITS", "OpenRouter reports insufficient credits (HTTP 402).", attempts)
            if status != 200:
                log(status, "rate_limited" if status == 429 else f"http_{status}", _provider_message(response))
                return None

            try:
                data = response.json()
            except ValueError:
                log(status, "invalid_response", "Response was not JSON")
                return None
            if isinstance(data, dict) and data.get("error"):
                log(status, "provider_error", _short(data["error"]))
                return None

            try:
                content = data["choices"][0]["message"].get("content") or ""
            except (KeyError, IndexError, TypeError, AttributeError):
                log(status, "invalid_response", "No choices in response")
                return None
            if not content.strip():
                log(status, "empty_content", "Model returned no text (reasoning may have used the token budget)")
                return None

            try:
                parsed = parse_fn(content)
            except BadModelOutput as exc:
                log(status, "bad_output", _short(exc))
                return None

            log(status, "ok")
            _cooldown.pop(model, None)
            meta = {
                "model": model,
                "mock": False,
                "cached": False,
                "attempts": len(attempts),
                "attempt_log": attempts,
                "skipped": skipped,
            }
            return parsed, meta

        late: list[str] = []
        for model in ready + cooling:
            if model in ready and skip_reason(model):
                late.append(model)  # blocked earlier in this very run (e.g. the free daily limit): last resort
                continue
            outcome = await attempt(model)
            if outcome:
                return outcome
        for model in late:
            outcome = await attempt(model)
            if outcome:
                return outcome

    raise AllModelsFailed(
        "LLM_UNAVAILABLE",
        f"The OpenRouter API is not working. All {len(chain)} models failed.",
        attempts,
    )
