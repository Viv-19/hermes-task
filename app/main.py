"""FastAPI app: JSON API under /api, static dashboard everywhere else."""
import collections
import json
import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import config, llm, pipeline
from .llm import AllModelsFailed
from .schemas import AnalyzeRequest

log = logging.getLogger("hermes")
app = FastAPI(title="Hermes Email Assistant", version=config.VERSION, docs_url=None, redoc_url=None)

_hits: dict[str, collections.deque] = collections.defaultdict(collections.deque)


def _error(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, **extra}})


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    hits = _hits[ip]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= config.RATE_LIMIT_PER_MIN:
        return True
    hits.append(now)
    return False


def _check_request(req: AnalyzeRequest, request: Request) -> tuple[str, str, JSONResponse | None]:
    """Validate input; return (subject, body, error_response_or_None)."""
    subject, body = req.subject.strip(), req.body.strip()
    if not subject and not body:
        return subject, body, _error(422, "EMPTY_EMAIL", "Please enter an email subject or body.")
    if len(subject) > config.MAX_SUBJECT_CHARS or len(body) > config.MAX_BODY_CHARS:
        return subject, body, _error(
            422,
            "TOO_LONG",
            f"The email is too long (subject max {config.MAX_SUBJECT_CHARS}, body max {config.MAX_BODY_CHARS} characters).",
        )
    if _rate_limited(_client_ip(request)):
        return subject, body, _error(429, "RATE_LIMITED", "Too many requests — please wait a minute and try again.")
    return subject, body, None


@app.middleware("http")
async def no_cache_for_static(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(AllModelsFailed)
async def models_failed(_request: Request, exc: AllModelsFailed):
    log.warning("All models failed (%s): %s", exc.code, exc.attempts)
    return _error(502, exc.code, exc.message, attempts=exc.attempts)


@app.exception_handler(RequestValidationError)
async def bad_request(_request: Request, _exc: RequestValidationError):
    return _error(422, "BAD_REQUEST", "The request was not valid. Send JSON with a subject and a body.")


@app.exception_handler(Exception)
async def unexpected(_request: Request, exc: Exception):
    log.exception("Unexpected error: %s", exc)
    return _error(500, "SERVER_ERROR", "Unexpected server error while analysing the email.")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "version": config.VERSION,
        "mock": config.MOCK_LLM,
        "key_configured": bool(config.OPENROUTER_API_KEY),
        "models": config.MODEL_CHAIN,
        "router_mode": "mock" if config.MOCK_LLM else config.ROUTER_MODE,
        "max_body_chars": config.MAX_BODY_CHARS,
        "ai_calls_today": llm.calls_today(),
        "commit": os.getenv("RENDER_GIT_COMMIT", "")[:7],  # set by Render; lets CI confirm the new version is live
        "free_daily_limit": config.FREE_DAILY_LIMIT,
    }


@app.get("/api/samples")
def samples():
    try:
        return json.loads(config.SAMPLES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest, request: Request):
    """Run the workflow and return only the final result."""
    subject, body, error = _check_request(req, request)
    if error:
        return error
    return await pipeline.analyze(subject, body, fresh=req.fresh)


@app.post("/api/analyze/stream")
async def analyze_stream(req: AnalyzeRequest, request: Request):
    """Run the workflow and stream every step as newline-delimited JSON events."""
    subject, body, error = _check_request(req, request)
    if error:
        return error

    async def events():
        try:
            async for event in pipeline.analyze_events(subject, body, fresh=req.fresh):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as exc:  # noqa: BLE001 - report as an event, the HTTP status is already sent
            log.exception("Workflow crashed: %s", exc)
            yield json.dumps({
                "event": "error", "stage": "server", "code": "SERVER_ERROR",
                "message": "Unexpected server error while analysing the email.", "attempts": [],
            }) + "\n"

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Must come last: serves index.html at "/" and the assets.
app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
