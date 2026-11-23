"""The LangGraph review panel: parallel fan-out, lead reviewer, verification, failure handling."""

from __future__ import annotations

from src.agent import ReviewPanel, ground_report, open_checkpointer
from src.tools import parse_diff
from tests.fakes import ScriptedFactory, finding


def panel_finding(category="security", raised_by=None, **kw):
    return {**finding(**kw), "category": category, "raised_by": raised_by or [category]}


def run(settings, diff, factory, reviewers=None):
    events = []
    panel = ReviewPanel(settings, factory, open_checkpointer(settings.sessions_dir))
    values = panel.review("r1", diff, title="Add user search", reviewers=reviewers, emit=events.append)
    return values, events


def test_specialists_run_in_parallel_and_lead_merges(settings, example_diff):
    factory = ScriptedFactory(
        specialists={
            "security": {"summary": "Injection risk.", "findings": [finding(line=19, severity="critical", title="SQL injection")]},
            "correctness": {"summary": "Pagination bug.", "findings": [finding(line=25, severity="high", title="Off-by-one offset")]},
        },
        lead={"verdict": "request_changes", "summary": "Two serious bugs.", "dismissed": [], "findings": [
            panel_finding("correctness", line=25, severity="high", title="Off-by-one offset"),
            panel_finding("security", line=19, severity="critical", title="SQL injection"),
        ]},
        delay=0.3,
    )
    values, events = run(settings, example_diff, factory)

    assert factory.max_active == 4  # all four specialists ran at the same time
    assert {r["reviewer"] for r in values["reviews"]} == {"security", "correctness", "performance", "maintainability"}
    report = values["report"]
    assert [f["title"] for f in report["findings"]] == ["SQL injection", "Off-by-one offset"]  # sorted by severity
    assert [f["id"] for f in report["findings"]] == ["F1", "F2"]
    assert report["findings"][0]["code"].strip().startswith('query = f"SELECT')
    assert values["usage"]["input_tokens"] == 500  # 4 specialists + lead

    kinds = [e["type"] for e in events]
    assert kinds[0] == "prepared" and kinds[-2:] == ["lead_started", "lead_done"]
    assert kinds.count("specialist_done") == 4

    lead_prompt = factory.models["lead"].calls[0][1].content
    assert "SQL injection" in lead_prompt and "Off-by-one offset" in lead_prompt
    spec_prompt = factory.models["security"].calls[0][1].content
    assert "   19 +     query = f\"SELECT" in spec_prompt  # line-numbered diff


def test_subset_of_reviewers(settings, example_diff):
    factory = ScriptedFactory(specialists={}, lead={"verdict": "approve", "summary": "ok", "findings": [], "dismissed": []})
    values, _ = run(settings, example_diff, factory, reviewers=["security"])
    assert [r["reviewer"] for r in values["reviews"]] == ["security"]


def test_failed_specialist_does_not_sink_the_panel(settings, example_diff):
    factory = ScriptedFactory(
        specialists={"security": {"summary": "s", "findings": [finding(line=19, severity="critical", title="SQLi")]}},
        lead={"verdict": "request_changes", "summary": "s", "dismissed": [],
              "findings": [panel_finding(line=19, severity="critical", title="SQLi")]},
        fail={"performance": "overloaded"},
    )
    values, events = run(settings, example_diff, factory)
    failed = [r for r in values["reviews"] if r["error"]]
    assert [r["reviewer"] for r in failed] == ["performance"]
    assert any(e["type"] == "specialist_failed" for e in events)
    assert "(failed: overloaded)" in factory.models["lead"].calls[0][1].content
    assert values["report"]["findings"][0]["title"] == "SQLi"


def test_lead_failure_falls_back_to_merge(settings, example_diff):
    factory = ScriptedFactory(
        specialists={
            "security": {"summary": "s", "findings": [finding(line=8, severity="high", title="Hard-coded secret")]},
            "maintainability": {"summary": "m", "findings": [finding(line=8, severity="high", title="Hard-coded secret")]},
        },
        lead=None, fail={"lead": "timeout"},
    )
    report = run(settings, example_diff, factory)[0]["report"]
    assert "lead reviewer was unavailable" in report["summary"]
    assert report["verdict"] == "request_changes"
    [merged] = report["findings"]  # exact duplicates merged mechanically
    assert merged["raised_by"] == ["security", "maintainability"]


def test_grounding_checks_every_finding(example_diff):
    files = parse_diff(example_diff)
    report = {"verdict": "approve", "summary": "s", "dismissed": [], "findings": [
        panel_finding(line=19, severity="critical", title="exact"),
        panel_finding(line=50, severity="low", title="near the end"),        # 2 past the last added line (48)
        panel_finding(line=400, severity="medium", title="nowhere"),
        panel_finding(file="app/ghost.py", line=1, title="ghost file"),
        panel_finding(file="users.py", line=0, severity="low", title="file level"),
    ]}
    out = ground_report(report, files)
    by_title = {f["title"]: f for f in out["findings"]}
    assert by_title["exact"]["location"] == "exact"
    assert (by_title["near the end"]["line"], by_title["near the end"]["location"]) == (48, "adjusted")
    assert by_title["nowhere"]["location"] == "unverified" and by_title["nowhere"]["code"] is None
    assert by_title["file level"]["file"] == "app/users.py" and by_title["file level"]["location"] == "file"
    assert [d["title"] for d in out["dismissed"]] == ["ghost file"]
    assert out["verdict"] == "request_changes"  # a critical finding overrides "approve"
