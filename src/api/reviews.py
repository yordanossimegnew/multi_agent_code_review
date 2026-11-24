"""Background reviews: each runs on a worker thread; events are kept for streaming."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Iterator

import anthropic

from ..agent import ReviewPanel
from ..tools import DiffError, GitHubError, PullRequest, fetch_pr, parse_diff
from ..utils.config import Settings
from ..utils.logger import get_logger

log = get_logger("reviews")
FINISHED = {"completed", "error"}
MAX_KEPT = 50


@dataclass
class Review:
    id: str
    source: dict  # {"type": "diff"|"github", ...}
    reviewers: list[str]
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    title: str = ""
    files: list[dict] = field(default_factory=list)
    reviews: list[dict] = field(default_factory=list)
    report: dict | None = None
    usage: dict | None = None
    error: str | None = None
    events: list[dict] = field(default_factory=list)
    cond: threading.Condition = field(default_factory=threading.Condition, repr=False)

    @property
    def finished(self) -> bool:
        return self.status in FINISHED


class ReviewManager:
    def __init__(self, settings: Settings, panel_factory: Callable[[], ReviewPanel],
                 pr_fetcher: Callable[[str], PullRequest] | None = None):
        self.settings = settings
        self.panel_factory = panel_factory
        self.pr_fetcher = pr_fetcher or (lambda url: fetch_pr(url, settings.github_token, settings.github_api,
                                                              max_chars=settings.max_diff_chars))
        self._slots = threading.BoundedSemaphore(settings.max_concurrent_reviews)
        self._reviews: dict[str, Review] = {}
        self._lock = threading.Lock()

    def start(self, *, diff: str | None, pr_url: str | None, title: str, description: str,
              reviewers: list[str]) -> Review:
        source = {"type": "github", "url": pr_url} if pr_url else {"type": "diff", "title": title}
        review = Review(id=uuid.uuid4().hex[:12], source=source, reviewers=reviewers, title=title)
        with self._lock:
            self._reviews[review.id] = review
            for old in sorted(self._reviews.values(), key=lambda r: r.created_at)[:-MAX_KEPT]:
                if old.finished:
                    del self._reviews[old.id]
        args = (review, diff, title, description)
        threading.Thread(target=self._worker, args=args, daemon=True, name=f"review-{review.id}").start()
        return review

    def get(self, review_id: str) -> Review | None:
        return self._reviews.get(review_id)

    def list(self) -> list[Review]:
        return sorted(self._reviews.values(), key=lambda r: r.created_at, reverse=True)

    def wait(self, review: Review, timeout: float | None = None) -> bool:
        with review.cond:
            return review.cond.wait_for(lambda: review.finished, timeout=timeout)

    def stream(self, review: Review, start: int = 0, keepalive: float = 15.0) -> Iterator[dict | None]:
        index = start
        while True:
            with review.cond:
                review.cond.wait_for(lambda: len(review.events) > index or review.finished, timeout=keepalive)  # noqa: B023 (called before index changes)
                batch, done = review.events[index:], review.finished
            for event in batch:
                yield event
            index += len(batch)
            if not batch:
                if done:
                    return
                yield None

    # ------------------------------------------------------------------ worker
    def _emit(self, review: Review, event: dict) -> None:
        with review.cond:
            review.events.append({"seq": len(review.events), "time": round(time.time() - review.created_at, 2), **event})
            review.cond.notify_all()

    def _on_event(self, review: Review, event: dict) -> None:
        if event["type"] == "prepared":
            review.files = event["files"]
        self._emit(review, event)

    def _worker(self, review: Review, diff: str | None, title: str, description: str) -> None:
        with self._slots:
            review.status = "running"
            self._emit(review, {"type": "status", "status": "running"})
            try:
                if review.source["type"] == "github":
                    self._emit(review, {"type": "fetching", "url": review.source["url"]})
                    pr = self.pr_fetcher(review.source["url"])
                    diff, description = pr.diff, pr.description
                    review.title = title or f"{pr.owner}/{pr.repo}#{pr.number}: {pr.title}"
                    review.source.update({"repo": f"{pr.owner}/{pr.repo}", "number": pr.number,
                                          "author": pr.author, "base": pr.base, "head": pr.head})
                    self._emit(review, {"type": "fetched", "title": review.title})
                if len(diff) > self.settings.max_diff_chars:
                    raise DiffError(f"Diff is {len(diff):,} characters; the limit is {self.settings.max_diff_chars:,}.")
                parse_diff(diff)  # validate early, before any model call

                panel = self.panel_factory()
                values = panel.review(review.id, diff, review.title, description, review.reviewers,
                                      emit=lambda e: self._on_event(review, e))
                review.reviews = values.get("reviews", [])
                review.report = values.get("report")
                review.usage = values.get("usage")
                self._finish(review, "completed")
            except (DiffError, GitHubError) as exc:
                self._fail(review, str(exc))
            except anthropic.AuthenticationError:
                self._fail(review, "Authentication failed: set ANTHROPIC_API_KEY in .env.")
            except anthropic.APIError as exc:
                self._fail(review, f"Model API error: {exc}")
            except Exception as exc:
                log.exception("review %s crashed", review.id)
                self._fail(review, f"{type(exc).__name__}: {exc}")

    def _finish(self, review: Review, status: str) -> None:
        self._emit(review, {"type": "done", "status": status, "report": review.report, "usage": review.usage})
        with review.cond:
            review.status = status
            review.cond.notify_all()

    def _fail(self, review: Review, message: str) -> None:
        review.error = message
        self._emit(review, {"type": "error", "message": message})
        self._finish(review, "error")
