"""Prompt assembly: role prompts + team guidelines + the change under review."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid a circular import at runtime
    from ..agent.reviewers import Reviewer
from .system_prompts import LEAD_PROMPT, SPECIALIST_PROMPT


def load_guidelines(directory: Path) -> str:
    """Team review guidelines from data/knowledge_base/*.md (sorted, so prompts are stable)."""
    if not directory.is_dir():
        return ""
    docs = [p.read_text(encoding="utf-8").strip() for p in sorted(directory.glob("*.md"))]
    return "\nTeam review guidelines:\n<guidelines>\n" + "\n\n".join(docs) + "\n</guidelines>\n" if docs else ""


def specialist_system(reviewer: Reviewer, guidelines: str) -> str:
    return SPECIALIST_PROMPT.format(name=reviewer.name, focus=reviewer.focus, guidelines=guidelines)


def lead_system(guidelines: str) -> str:
    return LEAD_PROMPT.format(guidelines=guidelines)


def change_message(title: str, description: str, annotated_diff: str) -> str:
    parts = [f"<change_title>{title or '(untitled change)'}</change_title>"]
    if description.strip():
        parts.append(f"<change_description>\n{description.strip()}\n</change_description>")
    parts.append(f"<diff>\n{annotated_diff}\n</diff>")
    return "\n".join(parts)


def lead_message(change: str, reviews: list[dict]) -> str:
    blocks = []
    for review in reviews:
        if review.get("error"):
            blocks.append(f'<review reviewer="{review["reviewer"]}">(failed: {review["error"]})</review>')
            continue
        lines = [f'<review reviewer="{review["reviewer"]}">', f"Summary: {review['summary']}"]
        for i, f in enumerate(review["findings"], 1):
            lines.append(
                f"{i}. [{f['severity']}, confidence {f['confidence']}] {f['file']}:{f['line']}: {f['title']}\n"
                f"   Why: {f['explanation']}\n   Fix: {f['suggestion']}"
            )
        if not review["findings"]:
            lines.append("(no findings)")
        lines.append("</review>")
        blocks.append("\n".join(lines))
    return f"{change}\n\nSpecialist reviews:\n" + "\n\n".join(blocks)
