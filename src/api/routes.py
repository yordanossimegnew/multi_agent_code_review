"""FastAPI app: submit a diff or GitHub PR, stream the panel's progress, fetch the report."""

from __future__ import annotations

import json
from typing import Callable

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..agent import REVIEWERS, ReviewPanel, open_checkpointer
from ..models import ModelFactory, anthropic_factory
from ..tools import DiffError, GitHubError, PullRequest, parse_diff, parse_pr_url
from ..utils.config import Settings, load_settings
from .reviews import Review, ReviewManager
from .schemas import HealthResponse, ReviewCreated, ReviewDetail, ReviewerInfo, ReviewRequest, ReviewSummary


def create_app(settings: Settings | None = None, model_factory: ModelFactory | None = None,
               pr_fetcher: Callable[[str], PullRequest] | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="Multi-Agent Code Review", version="1.0.0")
    checkpointer = open_checkpointer(settings.database_url)

    def panel_factory() -> ReviewPanel:
        return ReviewPanel(settings, model_factory or anthropic_factory(settings), checkpointer)

    manager = ReviewManager(settings, panel_factory, pr_fetcher=pr_fetcher)

    def get_review(review_id: str) -> Review:
        review = manager.get(review_id)
        if review is None:
            raise HTTPException(status_code=404, detail="Review not found")
        return review

    def summary(r: Review) -> dict:
        report = r.report or {}
        return {"review_id": r.id, "title": r.title, "status": r.status, "created_at": r.created_at,
                "verdict": report.get("verdict"), "findings": len(report["findings"]) if report else None}

    def validate(request: ReviewRequest) -> None:
        """Fail fast on input problems, before starting background work."""
        try:
            if request.pr_url:
                parse_pr_url(request.pr_url)
            else:
                if len(request.diff) > settings.max_diff_chars:
                    raise DiffError(f"Diff is {len(request.diff):,} characters; the limit is {settings.max_diff_chars:,}.")
                parse_diff(request.diff)
        except (DiffError, GitHubError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def start(request: ReviewRequest) -> Review:
        validate(request)
        return manager.start(diff=request.diff, pr_url=request.pr_url, title=request.title,
                             description=request.description, reviewers=request.reviewers)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(model=settings.model, reviewers=list(REVIEWERS), github_token=bool(settings.github_token))

    @app.get("/reviewers", response_model=list[ReviewerInfo])
    def reviewers() -> list[dict]:
        return [vars(r) for r in REVIEWERS.values()]

    @app.post("/reviews", response_model=ReviewCreated, status_code=202)
    def create_review(request: ReviewRequest) -> ReviewCreated:
        """Start a review in the background; follow it at events_url (Server-Sent Events)."""
        r = start(request)
        return ReviewCreated(review_id=r.id, status=r.status, events_url=f"/reviews/{r.id}/events")

    @app.post("/review", response_model=ReviewDetail)
    def review_sync(request: ReviewRequest, timeout: float = Query(600, ge=1, le=3600)) -> dict:
        """Run a review and wait for the report."""
        r = start(request)
        if not manager.wait(r, timeout=timeout):
            raise HTTPException(status_code=504, detail=f"Still running; follow /reviews/{r.id}")
        return detail(r.id)

    @app.get("/reviews", response_model=list[ReviewSummary])
    def list_reviews() -> list[dict]:
        return [summary(r) for r in manager.list()]

    @app.get("/reviews/{review_id}", response_model=ReviewDetail)
    def detail(review_id: str) -> dict:
        r = get_review(review_id)
        return {**summary(r), "source": r.source, "reviewers": r.reviewers, "files": r.files, "reviews": r.reviews,
                "report": r.report, "usage": r.usage, "error": r.error, "events": r.events}

    @app.get("/reviews/{review_id}/diff")
    def review_diff(review_id: str) -> dict:
        """Parsed diff with line numbers (for rendering inline annotations)."""
        r = get_review(review_id)
        state = checkpointer.get({"configurable": {"thread_id": r.id}})
        diff = (state or {}).get("channel_values", {}).get("diff")
        if not diff:
            raise HTTPException(status_code=404, detail="Diff not available yet")
        return {"files": [f.to_dict() for f in parse_diff(diff)]}

    @app.get("/reviews/{review_id}/events")
    def events(review_id: str, start: int = Query(0, ge=0)) -> StreamingResponse:
        """Server-Sent Events: specialist progress, findings and the final report."""
        r = get_review(review_id)

        def sse():
            for event in manager.stream(r, start=start):
                yield ": keepalive\n\n" if event is None else f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app
