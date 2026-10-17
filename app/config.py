"""Settings, read once from environment variables (and a local .env file)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

VERSION = "2.2"

DEFAULT_CHAIN = (
    "nvidia/nemotron-3-ultra-550b-a55b:free,"
    "nvidia/nemotron-3-super-120b-a12b:free,"
    "google/gemma-4-31b-it:free,"
    "nvidia/nemotron-3.5-super-vl:free"
)


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# The key is only ever read here, on the server. It is never sent to the browser.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

MODEL_CHAIN = [m.strip() for m in os.getenv("MODEL_CHAIN", DEFAULT_CHAIN).split(",") if m.strip()]

LLM_TIMEOUT_S = _float("LLM_TIMEOUT_S", 40)  # per model
LLM_DEADLINE_S = _float("LLM_DEADLINE_S", 85)  # whole chain, stays under Render's ~100 s limit
LLM_MAX_TOKENS = _int("LLM_MAX_TOKENS", 4000)

MOCK_LLM = os.getenv("MOCK_LLM", "0").strip() == "1"
MOCK_DELAY_S = _float("MOCK_DELAY_S", 0.7)  # pause between mock workflow steps so the UI can be watched

# two_stage = router agent, then the chosen skill (2 AI calls, real step-by-step workflow)
# single    = one call with all six skills (1 AI call)
ROUTER_MODE = os.getenv("ROUTER_MODE", "two_stage").strip().lower()
LLM_ROUTER_MAX_TOKENS = _int("LLM_ROUTER_MAX_TOKENS", 600)
FREE_DAILY_LIMIT = 50  # OpenRouter free models, accounts with < $10 credits

MAX_SUBJECT_CHARS = 300
MAX_BODY_CHARS = _int("MAX_BODY_CHARS", 8000)
RATE_LIMIT_PER_MIN = _int("RATE_LIMIT_PER_MIN", 10)

SKILLS_DIR = ROOT / "skills"
STATIC_DIR = ROOT / "static"
SAMPLES_FILE = ROOT / "samples" / "emails.json"
