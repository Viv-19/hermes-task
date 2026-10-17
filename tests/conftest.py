import os
import sys
from pathlib import Path

# Tests never call OpenRouter: force mock mode before the app is imported.
os.environ["MOCK_LLM"] = "1"
os.environ["MOCK_DELAY_S"] = "0"  # no artificial pauses in tests
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
