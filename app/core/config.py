"""Core configuration — loads from .env or environment variables."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATASET_DIR = BASE_DIR / "dataset"
EXPANDED_DIR = DATASET_DIR / "expanded"

# ── Server ─────────────────────────────────────────────────────────────
BOT_HOST: str = os.getenv("BOT_HOST", "0.0.0.0")
BOT_PORT: int = int(os.getenv("BOT_PORT", "8080"))

# ── LLM ────────────────────────────────────────────────────────────────
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")
LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4.1-mini")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# ── Redis ──────────────────────────────────────────────────────────────
REDIS_URL: Optional[str] = os.getenv("REDIS_URL", None)

# ── Team metadata ──────────────────────────────────────────────────────
TEAM_NAME: str = os.getenv("TEAM_NAME", "Vera-AI")
_raw_members = os.getenv("TEAM_MEMBERS", '["Builder"]')
try:
    TEAM_MEMBERS: list[str] = json.loads(_raw_members)
except Exception:
    TEAM_MEMBERS = ["Builder"]
CONTACT_EMAIL: str = os.getenv("CONTACT_EMAIL", "builder@example.com")

# ── Feature flags ──────────────────────────────────────────────────────
DETERMINISTIC_MODE: bool = os.getenv("DETERMINISTIC_MODE", "true").lower() == "true"
LLM_TEMPERATURE: float = 0.0   # always 0 for determinism
MAX_ACTIONS_PER_TICK: int = 20
RESPONSE_TIMEOUT_SEC: int = 25  # leave headroom for 30s judge timeout
CACHE_LLM_RESPONSES: bool = True
# Allow LLM enhancement when a valid API key is present; templates are still the fallback
USE_TEMPLATES_FIRST: bool = not bool(GEMINI_API_KEY or OPENAI_API_KEY or ANTHROPIC_API_KEY)

# ── Version ────────────────────────────────────────────────────────────
VERSION: str = "1.0.0"
