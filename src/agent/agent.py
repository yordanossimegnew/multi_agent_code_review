"""The review panel as a LangGraph graph: fan-out to specialists, fan-in to a lead reviewer.

    START -> prepare --Send x N--> specialist (parallel) --> lead -> END

* prepare    - parses the diff and builds one shared, line-numbered prompt
* specialist - one branch per reviewer (security, correctness, ...), run in parallel via
               Send; each returns structured findings that a reducer appends to `reviews`
* lead       - verifies, de-duplicates and ranks everything into one report; then code
               checks every finding against the real diff (see verify.py)
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ..models import ModelFactory
from ..prompts import change_message, lead_message, lead_system, load_guidelines, specialist_system
from ..tools import parse_diff, render_for_review
from ..utils.config import Settings
from ..utils.logger import get_logger
from .reviewers import REVIEWERS
from .schemas import PanelReport, SpecialistReview
from .state import ReviewState, SpecialistTask, usage_of
from .verify import fallback_report, ground_report

log = get_logger("panel")


class StructuredOutputError(Exception):
    pass


def _call(model: Any, system: str, user: str):
    """Invoke a structured model; return (parsed pydantic object, raw AIMessage)."""
    out = model.invoke([SystemMessage(system), HumanMessage(user)])
    raw, parsed = out.get("raw"), out.get("parsed")
    if parsed is None:
        stop = (getattr(raw, "response_metadata", None) or {}).get("stop_reason")
        detail = out.get("parsing_error") or f"stop_reason={stop}"
        raise StructuredOutputError(f"no structured output ({detail})")
    return parsed, raw


class ReviewPanel:
    def __init__(self, settings: Settings, model_factory: ModelFactory, checkpointer: Any = None):
        self.settings = settings
        self.factory = model_factory
        self.guidelines = load_guidelines(settings.knowledge_base_dir)
        self.graph = self._build(checkpointer)

    # ------------------------------------------------------------------ nodes
    def _prepare(self, state: ReviewState) -> dict:
        files = parse_diff(state["diff"])
        change = change_message(state.get("title", ""), state.get("description", ""), render_for_review(files))
        get_stream_writer()({"type": "prepared", "files": [
            {"path": f.path, "status": f.status, "additions": f.additions, "deletions": f.deletions} for f in files
        ]})
        return {"change": change}

    def _fan_out(self, state: ReviewState) -> list[Send]:
        return [Send("specialist", {"reviewer": key, "change": state["change"]}) for key in state["reviewers"]]

    def _specialist(self, task: SpecialistTask) -> dict:
        reviewer = REVIEWERS[task["reviewer"]]
        writer = get_stream_writer()
        writer({"type": "specialist_started", "reviewer": reviewer.key})
        try:
            model = self.factory(SpecialistReview, reviewer.key)
            parsed, raw = _call(model, specialist_system(reviewer, self.guidelines), task["change"])
        except Exception as exc:  # one failing specialist must not sink the whole panel
            log.warning("%s failed: %s", reviewer.key, exc)
            writer({"type": "specialist_failed", "reviewer": reviewer.key, "error": str(exc)[:300]})
            return {"reviews": [{"reviewer": reviewer.key, "summary": "", "findings": [], "error": str(exc)[:300]}]}
        review = {"reviewer": reviewer.key, "summary": parsed.summary,
                  "findings": [f.model_dump() for f in parsed.findings], "error": None}
        writer({"type": "specialist_done", "reviewer": reviewer.key, "count": len(parsed.findings),
                "summary": parsed.summary, "findings": review["findings"]})
        return {"reviews": [review], "usage": usage_of(raw)}

    def _lead(self, state: ReviewState) -> dict:
        writer = get_stream_writer()
        writer({"type": "lead_started"})
        reviews = sorted(state.get("reviews", []), key=lambda r: list(REVIEWERS).index(r["reviewer"]))
        usage = {}
        ok = [r for r in reviews if not r.get("error")]
        if not ok:
            raise StructuredOutputError("every specialist failed; see the specialist errors")
        try:
            model = self.factory(PanelReport, "lead")
            parsed, raw = _call(model, lead_system(self.guidelines), lead_message(state["change"], reviews))
            report, usage = parsed.model_dump(), usage_of(raw)
        except Exception as exc:
            log.warning("lead reviewer failed: %s", exc)
            report = fallback_report(ok, str(exc)[:200])
        report = ground_report(report, parse_diff(state["diff"]))
        writer({"type": "lead_done", "verdict": report["verdict"], "count": len(report["findings"])})
        return {"report": report, "usage": usage}

    def _build(self, checkpointer):
        g = StateGraph(ReviewState)
        g.add_node("prepare", self._prepare)
        g.add_node("specialist", self._specialist)
        g.add_node("lead", self._lead)
        g.add_edge(START, "prepare")
        g.add_conditional_edges("prepare", self._fan_out, ["specialist"])
        g.add_edge("specialist", "lead")  # lead waits for every parallel branch
        g.add_edge("lead", END)
        return g.compile(checkpointer=checkpointer)

    # ------------------------------------------------------------------ public API
    def review(self, review_id: str, diff: str, title: str = "", description: str = "",
               reviewers: list[str] | None = None, emit=None) -> dict:
        """Run the panel; stream custom events to `emit`; return the final state values."""
        config = {"configurable": {"thread_id": review_id}}
        inputs = {"diff": diff, "title": title, "description": description,
                  "reviewers": reviewers or list(REVIEWERS), "reviews": []}
        for event in self.graph.stream(inputs, config, stream_mode="custom"):
            if emit:
                emit(event)
        return self.graph.get_state(config).values
