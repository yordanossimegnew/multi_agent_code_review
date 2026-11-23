"""Review memory: a LangGraph SQLite checkpointer (one thread per review)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


def open_checkpointer(directory: Path) -> SqliteSaver:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(directory / "reviews.sqlite", check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver
