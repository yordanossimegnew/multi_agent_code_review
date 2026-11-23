"""Scripted stand-ins for the structured-output models, so tests run offline."""

from __future__ import annotations

import threading
import time

from langchain_core.messages import AIMessage

from src.agent import PanelReport, SpecialistReview


def finding(file="app/users.py", line=19, severity="high", title="Issue", **extra) -> dict:
    return {"file": file, "line": line, "severity": severity, "title": title,
            "explanation": extra.get("explanation", "Why it matters."),
            "suggestion": extra.get("suggestion", "How to fix it."),
            "confidence": extra.get("confidence", "high")}


class ScriptedModel:
    def __init__(self, result, delay: float = 0.0, fail: str | None = None):
        self.result, self.delay, self.fail = result, delay, fail
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(messages)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError(self.fail)
        raw = AIMessage(content="", response_metadata={"stop_reason": "end_turn"},
                        usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
        return {"raw": raw, "parsed": self.result, "parsing_error": None}


class ScriptedFactory:
    """factory(schema, role) -> ScriptedModel. Configure per role; records concurrency."""

    def __init__(self, specialists: dict[str, dict], lead: dict | None, delay: float = 0.0,
                 fail: dict[str, str] | None = None):
        self.specialists, self.lead, self.delay, self.fail = specialists, lead, delay, fail or {}
        self.models: dict[str, ScriptedModel] = {}
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def __call__(self, schema, role):
        if schema is SpecialistReview:
            data = self.specialists.get(role, {"summary": "Nothing to add.", "findings": []})
            result = SpecialistReview(**data)
        else:
            result = PanelReport(**self.lead) if self.lead else None
        model = ScriptedModel(result, self.delay, self.fail.get(role))
        factory = self

        class Tracking:
            def invoke(self, messages):
                with factory._lock:
                    factory.active += 1
                    factory.max_active = max(factory.max_active, factory.active)
                try:
                    return model.invoke(messages)
                finally:
                    with factory._lock:
                        factory.active -= 1

        self.models[role] = model
        return Tracking()
