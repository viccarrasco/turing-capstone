"""LangChain ``@tool``-decorated capabilities exposed by the agent.

The agent's runtime path is deterministic: the LangGraph orchestrates SQL
generation → safety validation → execution → summarisation, and the
``company_id`` scope is enforced by ``sql_validator.sanitize_sql`` regardless
of what the LLM produced. We do **not** rely on the LLM choosing whether to
call this tool.

That said, exposing ``execute_alarm_sql`` as a real ``@tool`` has two payoffs:

1. The execute node calls into a contract-typed, schema-validated entry
   point instead of the raw helper. The contract surface is documented in
   one place and is the same shape an LLM would see if we ever bound the
   tool to a model via ``ChatOpenAI.bind_tools``.

2. It is the canonical LangChain agent-tool primitive. Code search for
   ``@tool`` finds it. Future agentic paths (e.g. an exploratory mode that
   lets the model decide which of several tools to invoke) can reuse it
   without further plumbing.

The ``db`` session is supplied via ``InjectedToolArg`` so an LLM binding
this tool only sees ``sql`` and ``company_id`` in the tool schema — the
session is provided by the calling code and is invisible to the model.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import InjectedToolArg, tool
from typing_extensions import Annotated

from .query_executor import execute_safe_query


@tool
def execute_alarm_sql(
    sql: str,
    company_id: int,
    db: Annotated[Any, InjectedToolArg],
) -> Any:
    """Execute a single SELECT statement against the multi-tenant alarm history.

    The SQL is structurally validated (single SELECT, no DDL/DML, no comment
    markers) and the ``company_id`` predicate is injected before execution.
    A statement timeout is applied. Returns a list of row dicts on success or
    a ``{"error": <message>}`` dict on failure (e.g. invalid SQL, query timeout,
    missing table).

    Args:
        sql: The SELECT statement produced by the SQL generation graph.
        company_id: The authenticated tenant ID. The sanitiser injects this
            into the WHERE clause regardless of what the SQL contains; the
            argument is required and never taken from inside ``sql``.

    Returns:
        On success: ``list[dict[str, Any]]`` (one dict per row, JSON-safe).
        On failure: ``{"error": "<message>"}``.
    """
    return execute_safe_query(db, sql, company_id)
