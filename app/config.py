"""
Application Configuration and Environment Settings.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env (single source of truth for runtime settings)
load_dotenv(dotenv_path=BASE_DIR / ".env")

DOCS_DIR = Path(os.getenv("DOCS_DIR", str(BASE_DIR / "docs")))
CASES_DIR = Path(os.getenv("CASES_DIR", str(BASE_DIR / "cases")))
MEMORY_DIR = Path(os.getenv("MEMORY_DIR", str(BASE_DIR / "memory")))
LOGS_DIR = Path(os.getenv("LOGS_DIR", str(BASE_DIR / "logs")))

# Ensure directories exist
for directory in [CASES_DIR, MEMORY_DIR, LOGS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# API Keys (multi-key pool across all configured Gemini API keys)
GEMINI_API_KEYS = []
for k in ["GEMINI_API_KEY", "GEMINI_API_KEY2", "GEMINI_API_KEY3", "GEMINI_API_KEY4", "GEMINI_API_KEY5", "GEMINI_API_KEY6", "GEMINI_API_KEY7"]:
    v = os.getenv(k)
    if v and v.strip() and v.strip() not in GEMINI_API_KEYS:
        GEMINI_API_KEYS.append(v.strip())

GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""

# LLM Models & Temperatures (gemini-3.5-flash-lite is supported across all keys with 1,500 req/day per key)
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
FAST_GROUNDED_MODE = os.getenv("FAST_GROUNDED_MODE", "false").lower() in ("true", "1", "yes")
ADVOCATE_TEMPERATURE = 0.7
JUDGE_TEMPERATURE = 0.2
GATEKEEPER_TEMPERATURE = 0.2

