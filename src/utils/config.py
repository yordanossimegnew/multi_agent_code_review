"""Configuration loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    model: str = "claude-opus-5-5"
    effort: str = "high"  # low | medium | high | xhigh | max
    max_tokens: int = 16000
    max_diff_chars: int = 150_000  # larger diffs are rejected rather than silently truncated
    github_token: str | None = None  # optional: higher rate limits / private repos
    github_api: str = "https://api.github.com"
    max_concurrent_reviews: int = 3
    log_level: str = "INFO"
    log_dir: Path = PROJECT_ROOT / "logs"
    database_url: str = "postgresql://postgres:postgres@localhost:5432/code_review"
    knowledge_base_dir: Path = PROJECT_ROOT / "data" / "knowledge_base"


def load_settings(**overrides) -> Settings:
    """Build Settings from env vars, then apply any non-None keyword overrides."""
    load_dotenv(PROJECT_ROOT / ".env")
    settings = Settings(
        model=os.getenv("AGENT_MODEL", Settings.model),
        effort=os.getenv("AGENT_EFFORT", Settings.effort),
        max_tokens=int(os.getenv("AGENT_MAX_TOKENS", Settings.max_tokens)),
        max_diff_chars=int(os.getenv("MAX_DIFF_CHARS", Settings.max_diff_chars)),
        github_token=os.getenv("GITHUB_TOKEN") or None,
        max_concurrent_reviews=int(os.getenv("MAX_CONCURRENT_REVIEWS", Settings.max_concurrent_reviews)),
        log_level=os.getenv("LOG_LEVEL", Settings.log_level),
        database_url=os.getenv("DATABASE_URL", Settings.database_url),
    )
    return replace(settings, **{k: v for k, v in overrides.items() if v is not None})
