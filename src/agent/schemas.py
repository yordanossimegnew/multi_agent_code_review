"""Structured outputs: what each specialist and the lead reviewer must return.

These Pydantic models become JSON schemas that Claude's structured outputs enforce,
so every response is guaranteed to parse.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low"]
Category = Literal["security", "correctness", "performance", "maintainability"]
Confidence = Literal["high", "medium", "low"]
Verdict = Literal["approve", "comment", "request_changes"]

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class Finding(BaseModel):
    file: str = Field(description="Path of the changed file, exactly as shown after '===' in the diff.")
    line: int = Field(description="Line number in the NEW file (left column of the diff) where the problem is. 0 if it concerns the whole file.")
    severity: Severity = Field(description="critical: exploitable or data loss; high: likely bug in normal use; medium: real but limited impact; low: minor.")
    title: str = Field(description="One-line summary, under 80 characters.")
    explanation: str = Field(description="What is wrong and why it matters, concretely, in 1-3 sentences.")
    suggestion: str = Field(description="A concrete fix. Include a short corrected code snippet when helpful.")
    confidence: Confidence = Field(description="How sure you are this is a real problem in the changed code.")


class SpecialistReview(BaseModel):
    summary: str = Field(description="Two sentences on the change from your specialist angle.")
    findings: list[Finding] = Field(description="Problems in the changed lines. Empty if you found none.")


class PanelFinding(Finding):
    category: Category = Field(description="The main category of the problem.")
    raised_by: list[str] = Field(description="Keys of the specialists who reported this (e.g. ['security']).")


class Dismissed(BaseModel):
    title: str
    raised_by: list[str]
    reason: str = Field(description="Why it was dropped: duplicate, false positive, not in the changed code, or too speculative.")


class PanelReport(BaseModel):
    verdict: Verdict = Field(description="approve: no real problems; comment: only minor ones; request_changes: at least one high or critical problem.")
    summary: str = Field(description="3-5 sentences: what the change does and the most important problems.")
    findings: list[PanelFinding] = Field(description="Verified, de-duplicated findings, most severe first.")
    dismissed: list[Dismissed] = Field(description="Specialist findings you dropped, with the reason.")
