"""LangChain prompt + message helpers used by the SQL generator.

The agent's runtime is LangGraph + ``langchain_openai.ChatOpenAI``. Prompts
are constructed as ``langchain_core`` ``BaseMessage`` lists
(``SystemMessage`` / ``HumanMessage``) and passed directly to ``ChatOpenAI``;
no dict-shape conversion is needed. The summariser uses
``ChatPromptTemplate`` for variable validation and templated composition.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from .sql_generator_prompts import (
    RESULTS_SUMMARY_SYSTEM_PROMPT,
    SQL_GENERATOR_SYSTEM_PROMPT,
)


# The two system prompts contain literal '{...}' JSON-shape examples, so we
# pre-build them as SystemMessage instances rather than feeding them through
# ChatPromptTemplate's f-string parser (which would reject the braces).
_SQL_SYSTEM_MESSAGE = SystemMessage(content=SQL_GENERATOR_SYSTEM_PROMPT)
_SUMMARY_SYSTEM_MESSAGE = SystemMessage(content=RESULTS_SUMMARY_SYSTEM_PROMPT)


def build_sql_generation_messages(user_prompt: str) -> list[BaseMessage]:
    """SQL generation: system prompt is the SQL contract, user message is the
    fully-rendered per-question prompt produced by ``build_prompt``."""
    return [_SQL_SYSTEM_MESSAGE, HumanMessage(content=user_prompt)]


# Templated user prompt for the summariser. The system prompt is fixed and
# attached separately. ``ChatPromptTemplate`` validates that ``payload`` is
# supplied at format time.
_SUMMARY_USER_TEMPLATE: ChatPromptTemplate = ChatPromptTemplate.from_messages(
    [
        (
            "human",
            "Analyze this SQL result payload and return ONLY the strict JSON "
            "format described.\n\n{payload}",
        ),
    ]
)


def build_summary_messages(payload: dict[str, Any]) -> list[BaseMessage]:
    """Build the summariser messages from a payload dict.

    The system prompt is a pre-built ``SystemMessage`` (it contains literal
    JSON-shape braces that the template parser would reject). The user message
    is rendered through ``ChatPromptTemplate`` for variable validation.
    """
    rendered_payload = json.dumps(payload, ensure_ascii=False, default=str)
    user_messages = _SUMMARY_USER_TEMPLATE.format_messages(payload=rendered_payload)
    return [_SUMMARY_SYSTEM_MESSAGE, *user_messages]
