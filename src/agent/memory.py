"""Review memory: a LangGraph PostgreSQL checkpointer (one thread per review)."""

from __future__ import annotations

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def open_checkpointer(database_url: str) -> PostgresSaver:
    """Connection-pooled LangGraph checkpointer; creates its tables on first use."""
    conninfo = database_url.replace("postgresql+psycopg://", "postgresql://")
    pool = ConnectionPool(conninfo, min_size=1, max_size=10, open=True,
                          kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
    saver = PostgresSaver(pool)
    saver.setup()
    return saver
