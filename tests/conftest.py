import os
import sys
from pathlib import Path

# Tests never call OpenRouter: force mock mode before the app is imported.
os.environ["MOCK_LLM"] = "1"
os.environ["MOCK_DELAY_S"] = "0"  # no artificial pauses in tests
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_circuit_breaker():
    """Models that 'failed' in one test must not be skipped in the next."""
    from app import llm

    llm.reset_cooldowns()
    yield
    llm.reset_cooldowns()
