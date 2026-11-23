from __future__ import annotations

from pathlib import Path

import pytest

from src.utils.config import Settings

EXAMPLE_DIFF = (Path(__file__).resolve().parents[1] / "data" / "examples" / "user_service.diff").read_text()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(sessions_dir=tmp_path / "sessions", knowledge_base_dir=tmp_path / "kb", log_dir=tmp_path / "logs")


@pytest.fixture
def example_diff() -> str:
    return EXAMPLE_DIFF
