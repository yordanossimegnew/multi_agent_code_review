"""FastAPI endpoints: validation, background reviews, SSE, GitHub source."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from src.api import create_app
from src.tools import GitHubError, PullRequest
from tests.fakes import ScriptedFactory, finding

LEAD = {"verdict": "request_changes", "summary": "SQL injection in search.", "dismissed": [],
        "findings": [{**finding(line=19, severity="critical", title="SQL injection"),
                      "category": "security", "raised_by": ["security"]}]}


def client(settings, example_diff, fetcher=None):
    factory = ScriptedFactory(specialists={"security": {"summary": "s", "findings": [finding(line=19)]}}, lead=LEAD)
    return TestClient(create_app(settings, model_factory=factory, pr_fetcher=fetcher))


def read_events(c, url):
    with c.stream("GET", url) as r:
        return [json.loads(l[6:]) for l in r.iter_lines() if l.startswith("data: ")]


def test_health_and_reviewers(settings, example_diff):
    c = client(settings, example_diff)
    assert c.get("/health").json()["reviewers"] == ["security", "correctness", "performance", "maintainability"]
    assert {r["key"] for r in c.get("/reviewers").json()} == {"security", "correctness", "performance", "maintainability"}


def test_streamed_review(settings, example_diff):
    c = client(settings, example_diff)
    created = c.post("/reviews", json={"diff": example_diff, "title": "Add search"})
    assert created.status_code == 202
    rid = created.json()["review_id"]
    events = read_events(c, created.json()["events_url"])
    kinds = [e["type"] for e in events]
    assert kinds[:2] == ["status", "prepared"] and kinds[-1] == "done"
    assert kinds.count("specialist_started") == 4
    assert events[-1]["report"]["findings"][0]["title"] == "SQL injection"

    detail = c.get(f"/reviews/{rid}").json()
    assert detail["status"] == "completed" and detail["verdict"] == "request_changes"
    assert detail["files"][0]["path"] == "app/users.py" and len(detail["reviews"]) == 4
    diff = c.get(f"/reviews/{rid}/diff").json()["files"][0]
    assert diff["path"] == "app/users.py" and diff["hunks"][0]["lines"][0]["new_no"] == 1
    assert c.get("/reviews").json()[0]["findings"] == 1


def test_sync_review_with_github_source(settings, example_diff):
    def fetcher(url):
        return PullRequest(url=url, owner="o", repo="r", number=7, title="Add search", description="d",
                           author="dev", base="main", head="feat", diff=example_diff)

    c = client(settings, example_diff, fetcher)
    body = c.post("/review", json={"pr_url": "https://github.com/o/r/pull/7"}).json()
    assert body["status"] == "completed" and body["title"] == "o/r#7: Add search"
    assert body["source"]["author"] == "dev"


def test_github_errors_are_reported(settings, example_diff):
    def fetcher(url):
        raise GitHubError("PR o/r#9 not found (private repos need GITHUB_TOKEN).")

    c = client(settings, example_diff, fetcher)
    body = c.post("/review", json={"pr_url": "https://github.com/o/r/pull/9"}).json()
    assert body["status"] == "error" and "not found" in body["error"]


def test_validation(settings, example_diff):
    c = client(settings, example_diff)
    assert c.post("/reviews", json={}).status_code == 422
    assert c.post("/reviews", json={"diff": example_diff, "pr_url": "https://github.com/o/r/pull/1"}).status_code == 422
    assert c.post("/reviews", json={"diff": "not a diff"}).status_code == 422
    assert c.post("/reviews", json={"pr_url": "https://example.com/x"}).status_code == 422
    assert c.post("/reviews", json={"diff": example_diff, "reviewers": ["astrology"]}).status_code == 422
    assert c.get("/reviews/missing").status_code == 404
