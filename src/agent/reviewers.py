"""The review panel: four specialists, each with a narrow focus."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reviewer:
    key: str
    name: str
    icon: str
    focus: str


REVIEWERS: dict[str, Reviewer] = {r.key: r for r in [
    Reviewer(
        key="security",
        name="Security reviewer",
        icon="🛡️",
        focus=(
            "Injection (SQL, shell, template), authentication and authorization gaps, secrets or "
            "credentials in code, weak cryptography (MD5/SHA1 for passwords, homemade crypto), unsafe "
            "deserialization, path traversal, SSRF, missing input validation, and sensitive data in logs."
        ),
    ),
    Reviewer(
        key="correctness",
        name="Correctness reviewer",
        icon="🎯",
        focus=(
            "Logic errors, off-by-one and boundary mistakes, wrong conditions, unhandled None/empty "
            "cases, broken error handling (swallowed exceptions, misleading return values), race "
            "conditions, resource leaks, and behaviour changes that break existing callers."
        ),
    ),
    Reviewer(
        key="performance",
        name="Performance reviewer",
        icon="⚡",
        focus=(
            "N+1 queries, queries or I/O inside loops, missing pagination or limits, unbounded memory "
            "growth, accidental quadratic algorithms, repeated expensive work that could be cached or "
            "batched, and blocking calls on hot paths."
        ),
    ),
    Reviewer(
        key="maintainability",
        name="Maintainability reviewer",
        icon="🧹",
        focus=(
            "Unclear names, duplicated logic, functions doing too much, missing or misleading "
            "docstrings and types, dead code and unused imports, magic numbers, and missing tests for "
            "new behaviour. Only raise issues a senior engineer would actually ask to change."
        ),
    ),
]}

DEFAULT_REVIEWERS = list(REVIEWERS)
