import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Google retires models regularly. If you get a 404, use "Check Gemini connection" in the app
# (or: python main.py --check) to see which models your key can use, then put one here.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "")   # optional: "low" is faster on Gemini 3 models
CACHE_DIR = Path(os.getenv("CACHE_DIR", ".cache"))

PROMPT_VERSION = "v2"    # bump when prompts or schemas change (invalidates the cache)
MAX_BODY_CHARS = 6000    # cap on how much of one email is sent to the model
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "8"))      # emails per model call
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "3"))    # batches sent in parallel
RATE_TOLERANCE = 0.9     # fee >= 90% of the creator's rate counts as "at rate"