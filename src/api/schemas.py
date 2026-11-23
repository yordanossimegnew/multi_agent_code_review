"""Request/response models for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from ..agent import DEFAULT_REVIEWERS, REVIEWERS


class ReviewRequest(BaseModel):
    diff: str | None = Field(None, description="A unified diff (e.g. `git diff` output).")
    pr_url: str | None = Field(None, description="A GitHub pull request URL to fetch and review.")
    title: str = Field("", max_length=300, description="Optional title for pasted diffs.")
    description: str = Field("", max_length=8000, description="Optional context about the change.")
    reviewers: list[str] = Field(default_factory=lambda: list(DEFAULT_REVIEWERS),
                                 description=f"Which specialists to run: {', '.join(REVIEWERS)}.")

    @model_validator(mode="after")
    def _check(self) -> "ReviewRequest":
        if bool(self.diff and self.diff.strip()) == bool(self.pr_url and self.pr_url.strip()):
            raise ValueError("Provide exactly one of `diff` or `pr_url`.")
        unknown = [r for r in self.reviewers if r not in REVIEWERS]
        if unknown or not self.reviewers:
            raise ValueError(f"reviewers must be a non-empty subset of {list(REVIEWERS)}; got {self.reviewers}")
        self.reviewers = list(dict.fromkeys(self.reviewers))
        return self


class ReviewCreated(BaseModel):
    review_id: str
    status: str
    events_url: str


class ReviewSummary(BaseModel):
    review_id: str
    title: str
    status: str
    created_at: float
    verdict: str | None
    findings: int | None


class ReviewDetail(ReviewSummary):
    source: dict
    reviewers: list[str]
    files: list[dict]
    reviews: list[dict]
    report: dict | None
    usage: dict | None
    error: str | None
    events: list[dict]


class ReviewerInfo(BaseModel):
    key: str
    name: str
    icon: str
    focus: str


class HealthResponse(BaseModel):
    status: str = "ok"
    model: str
    reviewers: list[str]
    github_token: bool
