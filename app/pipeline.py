"""The workflow: email -> router agent -> skill loaded -> skill agent -> validation -> draft.

analyze_events() yields every step as a real event (this is what the dashboard shows live),
including which model is being tried and which ones failed.
analyze() just returns the final result, for tests and scripts.
"""
import asyncio
import copy
import hashlib
import json
import re
import time

from . import config, llm, mock, skills, validators
from . import schemas as S

_CACHE: dict[str, tuple[float, list[dict], dict]] = {}
_CACHE_TTL_S = 3600
_CACHE_MAX = 200
_PING_EVERY_S = 8  # keeps free hosts from closing a quiet connection


# --------------------------------------------------------------------------- parsing the model's reply


def extract_json(content: str) -> dict:
    """Pull one JSON object out of a model reply (tolerates fences and <think> blocks)."""
    text = re.sub(r"<think>.*?</think>", "", content, flags=re.S | re.I).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise llm.BadModelOutput("no JSON object found in the reply")
    candidate = text[start : end + 1]
    for attempt in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
        try:
            data = json.loads(attempt)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    raise llm.BadModelOutput("the reply was not valid JSON")


def _confidence(value) -> str:
    return value if value in ("high", "medium", "low") else "medium"


def _flags(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [f for f in (str(x).strip().upper() for x in value) if f in S.LLM_FLAGS]


def parse_router_output(content: str) -> dict:
    """Stage 1 reply -> {category, confidence, reason, flags}."""
    data = extract_json(content)
    category = S.canonical_category(data.get("category"))
    if category is None:
        raise llm.BadModelOutput(f"unknown category “{data.get('category')}”")
    return {
        "category": category,
        "confidence": _confidence(data.get("category_confidence") or data.get("confidence")),
        "reason": validators.clean_str(data.get("category_reason") or data.get("reason"), 220),
        "flags": _flags(data.get("flags")),
    }


def parse_skill_output(content: str) -> dict:
    """Stage 2 reply -> raw dict (the category was already decided by the router)."""
    data = extract_json(content)
    if not isinstance(data.get("fields", {}), dict):
        raise llm.BadModelOutput("“fields” is not an object")
    return data


def parse_model_output(content: str) -> dict:
    """Single-call mode reply -> raw dict including a valid category."""
    data = parse_skill_output(content)
    category = S.canonical_category(data.get("category"))
    if category is None:
        raise llm.BadModelOutput(f"unknown category “{data.get('category')}”")
    data["category"] = category
    return data


# --------------------------------------------------------------------------- prompts


def _email_message(subject: str, body: str) -> str:
    safe_subject = subject.replace("</email>", "")
    safe_body = body.replace("</email>", "")
    return f"<email>\nSubject: {safe_subject}\n\nBody:\n{safe_body}\n</email>\n\nReturn the JSON object now."


def _cache_key(subject: str, body: str) -> str:
    raw = "\x00".join(
        [subject, body, skills.skills_fingerprint(), ",".join(config.MODEL_CHAIN), config.ROUTER_MODE]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _watch(task: "asyncio.Future", queue: "asyncio.Queue", ev):
    """While `task` runs: yield model events (which model is tried / failed) as they arrive,
    and a ping every few seconds so free hosts do not close a quiet connection."""
    last_ping = time.monotonic()
    while True:
        done, _ = await asyncio.wait({task}, timeout=0.2)
        while not queue.empty():
            item = queue.get_nowait()
            yield ev(item.pop("event"), **item)
        if done:
            return
        if time.monotonic() - last_ping >= _PING_EVERY_S:
            last_ping = time.monotonic()
            yield {"event": "ping"}


def _tag(attempts: list[dict], stage: str) -> list[dict]:
    return [{**a, "stage": stage} for a in attempts]


def _stage_sink(queue: "asyncio.Queue", stage: str):
    return lambda event: queue.put_nowait({**event, "stage": stage})


# --------------------------------------------------------------------------- the workflow


async def analyze_events(subject: str, body: str, fresh: bool = False):
    """Async generator of workflow events. The last event is `done` or `error`."""
    t0 = time.monotonic()

    def ev(name: str, **data) -> dict:
        return {"event": name, "t": int((time.monotonic() - t0) * 1000), **data}

    recorded: list[dict] = []

    def rec(event: dict) -> dict:
        recorded.append(event)
        return event

    yield ev("received", subject=subject, chars=len(body))

    # ---- cached? replay the recorded steps instantly
    key = _cache_key(subject, body)
    hit = _CACHE.get(key)
    if hit and not fresh and not config.MOCK_LLM and time.monotonic() - hit[0] < _CACHE_TTL_S:
        for old in hit[1]:
            yield {**old, "cached": True}
        result = copy.deepcopy(hit[2])
        result["meta"]["cached"] = True
        yield ev("done", result=result, cached=True)
        return

    mode = "mock" if config.MOCK_LLM else ("single" if config.ROUTER_MODE == "single" else "two_stage")
    attempt_log: list[dict] = []
    stage_info: dict = {}
    router_attempts: list[dict] = []
    skill_attempts: list[dict] = []

    # ================================================================ stage 1: router agent
    yield rec(ev("router_start", single_call=(mode == "single")))
    t_stage = time.monotonic()
    raw: dict
    route: dict
    router_model = "MOCK"

    if mode == "mock":
        raw = mock.mock_response(subject, body)
        await asyncio.sleep(config.MOCK_DELAY_S)
        route = {
            "category": S.canonical_category(raw["category"]) or S.OTHER,
            "confidence": _confidence(raw.get("category_confidence")),
            "reason": validators.clean_str(raw.get("category_reason"), 220),
            "flags": [],
        }
    elif mode == "single":
        messages = [
            {"role": "system", "content": skills.build_system_prompt()},
            {"role": "user", "content": _email_message(subject, body)},
        ]
        queue: asyncio.Queue = asyncio.Queue()
        task = asyncio.ensure_future(
            llm.run_chain(messages, parse_model_output, on_event=_stage_sink(queue, "router"))
        )
        try:
            async for item in _watch(task, queue, ev):
                yield item
            raw, meta = task.result()
        except llm.AllModelsFailed as exc:
            yield ev("error", stage="router", code=exc.code, message=exc.message, attempts=_tag(exc.attempts, "single"))
            return
        finally:
            if not task.done():
                task.cancel()
        attempt_log += _tag(meta["attempt_log"], "single")
        router_attempts = _tag(meta["attempt_log"], "single")
        router_model = meta["model"]
        route = {
            "category": raw["category"],
            "confidence": _confidence(raw.get("category_confidence")),
            "reason": validators.clean_str(raw.get("category_reason"), 220),
            "flags": [],
        }
    else:
        messages = [
            {"role": "system", "content": skills.build_router_prompt()},
            {"role": "user", "content": _email_message(subject, body)},
        ]
        queue = asyncio.Queue()
        task = asyncio.ensure_future(
            llm.run_chain(
                messages, parse_router_output, max_tokens=config.LLM_ROUTER_MAX_TOKENS,
                on_event=_stage_sink(queue, "router"),
            )
        )
        try:
            async for item in _watch(task, queue, ev):
                yield item
            route, meta = task.result()
        except llm.AllModelsFailed as exc:
            yield ev("error", stage="router", code=exc.code, message=exc.message, attempts=_tag(exc.attempts, "router"))
            return
        finally:
            if not task.done():
                task.cancel()
        attempt_log += _tag(meta["attempt_log"], "router")
        router_attempts = _tag(meta["attempt_log"], "router")
        router_model = meta["model"]

    router_ms = int((time.monotonic() - t_stage) * 1000)
    category = route["category"]
    stage_info["router"] = {"model": router_model, "ms": router_ms}
    yield rec(ev(
        "router_done",
        category=category,
        confidence=route["confidence"],
        reason=route["reason"],
        flags=route["flags"],
        model=router_model,
        ms=router_ms,
        attempts=router_attempts,
        single_call=(mode == "single"),
    ))

    skill = skills.get_skill(category) or {"name": "other", "file": "other.md", "description": ""}
    yield rec(ev("skill_loaded", skill=skill["name"], file=skill["file"], description=skill["description"], single_call=(mode == "single")))

    # ================================================================ stage 2: skill agent
    yield rec(ev("skill_start", single_call=(mode == "single")))
    t_stage = time.monotonic()
    skill_model = router_model

    if mode == "two_stage":
        messages = [
            {"role": "system", "content": skills.build_skill_prompt(category)},
            {"role": "user", "content": _email_message(subject, body)},
        ]
        queue = asyncio.Queue()
        task = asyncio.ensure_future(
            llm.run_chain(
                messages, parse_skill_output, prefer=router_model, on_event=_stage_sink(queue, "skill"),
            )
        )
        try:
            async for item in _watch(task, queue, ev):
                yield item
            raw, meta2 = task.result()
        except llm.AllModelsFailed as exc:
            yield ev("error", stage="skill", code=exc.code, message=exc.message, attempts=_tag(exc.attempts, "skill"), category=category)
            return
        finally:
            if not task.done():
                task.cancel()
        attempt_log += _tag(meta2["attempt_log"], "skill")
        skill_attempts = _tag(meta2["attempt_log"], "skill")
        skill_model = meta2["model"]
    elif mode == "mock":
        await asyncio.sleep(config.MOCK_DELAY_S * 1.4)

    skill_ms = int((time.monotonic() - t_stage) * 1000) if mode != "single" else 0
    stage_info["skill"] = {"model": skill_model, "ms": skill_ms, "name": skill["name"], "file": skill["file"]}
    yield rec(ev("skill_done", model=skill_model, ms=skill_ms, attempts=skill_attempts, single_call=(mode == "single")))

    # ================================================================ validation (Python, no AI)
    raw["category"] = category
    raw["category_confidence"] = route["confidence"]
    raw["category_reason"] = route["reason"]
    raw["flags"] = list(raw.get("flags") or []) + route["flags"]
    result = validators.build_result(subject, body, raw)
    checks = validators.summarize_checks(result)
    result["checks"] = checks
    issues = sum(1 for c in checks if c["status"] in ("warn", "fail"))
    if mode == "mock":
        await asyncio.sleep(config.MOCK_DELAY_S * 0.6)
    yield rec(ev("validation", checks=checks, issues=issues))

    result["meta"] = {
        "model": skill_model,
        "router_model": router_model,
        "mock": mode == "mock",
        "cached": False,
        "router_mode": mode,
        "attempts": len(attempt_log),
        "attempt_log": attempt_log,
        "latency_ms": int((time.monotonic() - t0) * 1000),
        "stages": stage_info,
    }

    if mode != "mock":
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = (time.monotonic(), copy.deepcopy(recorded), copy.deepcopy(result))
    yield ev("done", result=result)


async def analyze(subject: str, body: str, fresh: bool = False) -> dict:
    """Run the whole workflow and return only the final result (raises AllModelsFailed on failure)."""
    async for event in analyze_events(subject, body, fresh=fresh):
        if event["event"] == "done":
            return event["result"]
        if event["event"] == "error":
            raise llm.AllModelsFailed(event["code"], event["message"], event.get("attempts", []))
    raise RuntimeError("The workflow ended without a result.")
