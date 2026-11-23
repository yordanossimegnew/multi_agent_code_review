"""Graph state. Parallel specialists append to `reviews` through a reducer."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def add_usage(a: dict | None, b: dict | None) -> dict:
    """Reducer: sum token usage reported by parallel nodes."""
    a, b = a or {}, b or {}
    return {k: a.get(k, 0) + b.get(k, 0) for k in USAGE_KEYS}


class ReviewState(TypedDict, total=False):
    title: str
    description: str
    diff: str
    reviewers: list[str]
    change: str  # the prompt-ready change (title, description, annotated diff)
    reviews: Annotated[list[dict], operator.add]  # one entry per specialist, merged across branches
    report: dict
    usage: Annotated[dict, add_usage]


class SpecialistTask(TypedDict):
    """Payload sent to each parallel specialist branch via Send."""

    reviewer: str
    change: str


def usage_of(raw) -> dict:
    meta = getattr(raw, "usage_metadata", None) or {}
    details = meta.get("input_token_details") or {}
    return {
        "input_tokens": meta.get("input_tokens", 0),
        "output_tokens": meta.get("output_tokens", 0),
        "cache_read_input_tokens": details.get("cache_read", 0) or 0,
        "cache_creation_input_tokens": details.get("cache_creation", 0) or 0,
    }
