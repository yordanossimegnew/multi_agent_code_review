"""LangChain ChatAnthropic configured for structured output.

The graph asks for a model per (schema, role) through a factory, so tests can swap
in scripted models. Opus 5.5 does not accept forced tool choice, so structured output
uses Claude's native JSON-schema mode (`method="json_schema"`), not function calling.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel

from ..utils.config import Settings

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class StructuredModel(Protocol):
    def invoke(self, messages: list) -> dict: ...  # {"raw": AIMessage, "parsed": BaseModel | None, ...}


ModelFactory = Callable[[type[BaseModel], str], StructuredModel]


def chat_model(settings: Settings) -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.model,
        max_tokens=settings.max_tokens,
        output_config={"effort": settings.effort},  # adaptive thinking is on by default; effort sets depth
        betas=[FALLBACK_BETA],
        model_kwargs={"fallbacks": "default", "cache_control": {"type": "ephemeral"}},
        max_retries=3,
    )


def anthropic_factory(settings: Settings) -> ModelFactory:
    base = chat_model(settings)

    def factory(schema: type[BaseModel], role: str) -> Any:
        # include_raw keeps the AIMessage so we can read stop_reason and token usage
        return base.with_structured_output(schema, method="json_schema", include_raw=True)

    return factory
