import contextvars
import csv
import io
import json
import logging
import random
import time
from typing import Any, Dict, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from ..config import settings
from .response_generator import default_response
from .tools import execute_alarm_sql
from langchain_core.messages import AIMessage

from .lc_prompt import (
    build_sql_generation_messages,
    build_summary_messages,
)
from .sql_generator_prompts import (
    AGGREGATE_TOKENS,
    DEFAULT_LIMIT,
    SQL_PREFIXES,
    build_prompt,
    build_refiner_prompt as _build_refiner_prompt,
    build_repair_prompt as _build_repair_prompt,
)
from .openai_client import get_chat_model
from .sql_validator import is_safe_sql, sanitize_sql

try:
    from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
except Exception:  # pragma: no cover - openai package shape may differ by version
    APIConnectionError = None  # type: ignore[assignment]
    APIStatusError = None  # type: ignore[assignment]
    APITimeoutError = None  # type: ignore[assignment]
    RateLimitError = None  # type: ignore[assignment]

try:
    from langsmith import traceable as _traceable
    _langsmith_traceable_available = True
except Exception:  # pragma: no cover - optional dependency
    _langsmith_traceable_available = False
    def _traceable(*args, **kwargs):  # type: ignore
        def decorator(func):
            return func
        return decorator


_langsmith_tracing_logged = False


def _traceable_if_enabled(*args, **kwargs):
    if not settings.langsmith_tracing:
        def decorator(func):
            return func
        return decorator
    global _langsmith_tracing_logged
    if not _langsmith_tracing_logged:
        _langsmith_tracing_logged = True
        logger.info("LangSmith tracing enabled for SQL generation flow.")
    return _traceable(*args, **kwargs)


logger = logging.getLogger(__name__)
if settings.langsmith_tracing and not _langsmith_traceable_available:
    logger.warning(
        "LangSmith tracing is enabled, but langsmith.traceable is unavailable; LangGraph traces will not be recorded."
    )
SQL_GENERATION_FALLBACK_SQL = "SELECT 'Error generating SQL' as error;"
RESPONSE_TYPE_GRAPH_JSON = "graph_json"
RESPONSE_TYPE_TABLE_RECORDS = "table_records"
RESPONSE_TYPE_PLAIN_TEXT = "plain_text"
RESPONSE_TYPE_CSV = "csv"
ROUTE_CUSTOM_QUERY = "custom_query"
ROUTE_ERROR = "error"
CSV_RESULT_THRESHOLD = 10
VALID_RESPONSE_TYPES = {
    RESPONSE_TYPE_GRAPH_JSON,
    RESPONSE_TYPE_TABLE_RECORDS,
    RESPONSE_TYPE_PLAIN_TEXT,
    RESPONSE_TYPE_CSV,
}
_last_generation_error = contextvars.ContextVar("sql_generation_error", default=None)
_usage_calls = contextvars.ContextVar("sql_generation_usage_calls", default=None)
_reasoning_steps = contextvars.ContextVar("sql_generation_reasoning_steps", default=None)
_llm_stage = contextvars.ContextVar("sql_generation_llm_stage", default="unspecified")
# Per-1M-token pricing in USD for chat models accessible to this project's
# OpenAI API key. Sourced from OpenAI's official pricing pages
# (developers.openai.com/api/docs/pricing) and OpenRouter as of 2026-04-28.
#
# Scope is intentionally narrow:
# - Only models reachable with the current API key (verified via
#   `client.models.list()`)
# - Only chat / text-generation models (no codex coding-specific, no audio
#   transcribe variants, no image/embedding models)
# - We accept and price the base model name; dated variants
#   (e.g. "gpt-4o-mini-2024-07-18") share the same pricing.
#
# Cached-input pricing (typically ~10% of input) is recorded for future use;
# the cost estimator below uses input + output only because we do not yet
# plumb cached-token counts through usage_metadata.
_model_pricing_usd_per_1m = {
    # GPT-4 family (small/efficient tiers our key can use)
    "gpt-4o-mini": {"input": 0.15, "cached_input": 0.075, "output": 0.60},
    "gpt-4.1-mini": {"input": 0.40, "cached_input": 0.10, "output": 1.60},
    "gpt-4.1-nano": {"input": 0.10, "cached_input": 0.025, "output": 0.40},
    # GPT-5 family
    "gpt-5-mini": {"input": 0.25, "cached_input": 0.025, "output": 2.00},
    "gpt-5-nano": {"input": 0.05, "cached_input": 0.005, "output": 0.40},
    # GPT-5.2 (default for candidate B and refiner; released 2025-12-10)
    "gpt-5.2": {"input": 1.75, "cached_input": 0.175, "output": 14.00},
}


class SQLGenerationErrorInfo(TypedDict):
    type: str
    message: str
    debug: str


ResponseType = Literal["graph_json", "table_records", "plain_text", "csv"]


class ConversationMessage(TypedDict):
    role: str
    content: str


class QueryPipelineResult(TypedDict):
    sql: str
    success: bool
    response_type: ResponseType
    results: Any
    summary: str
    row_count: int
    meta: "QueryMeta"


class LLMCallUsage(TypedDict):
    stage: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    cost_usd: float


class UsageTotals(TypedDict):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    total_llm_time_ms: int
    total_db_time_ms: int
    total_cost_usd: float


class UsageMeta(TypedDict):
    llm_calls: list[LLMCallUsage]
    totals: UsageTotals


class QueryMeta(TypedDict):
    route: str
    generated_sql: str
    response_type: ResponseType
    reasoning_steps: list[str]
    usage: UsageMeta


class SQLGenerationException(Exception):
    def __init__(self, error_info: SQLGenerationErrorInfo):
        self.error_info = error_info
        super().__init__(error_info["message"])


_SQL_FALLBACK_NORMALIZED = SQL_GENERATION_FALLBACK_SQL.rstrip(";")


def clear_last_generation_error() -> None:
    _last_generation_error.set(None)


def get_last_generation_error() -> SQLGenerationErrorInfo | None:
    value = _last_generation_error.get()
    return value if isinstance(value, dict) else None


def is_sql_generation_fallback(sql: str | None) -> bool:
    if not sql:
        return True
    normalized = extract_sql(sql).strip().rstrip(";")
    return normalized == _SQL_FALLBACK_NORMALIZED.rstrip(";")


def build_default_usage_meta(total_db_time_ms: int = 0) -> UsageMeta:
    return {
        "llm_calls": [],
        "totals": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "total_llm_time_ms": 0,
            "total_db_time_ms": max(int(total_db_time_ms), 0),
            "total_cost_usd": 0.0,
        },
    }


def build_default_query_meta(
    sql: str,
    response_type: str,
    success: bool,
    reasoning_steps: list[str] | None = None,
    usage: UsageMeta | None = None,
) -> QueryMeta:
    normalized_response_type = _normalize_response_type(response_type)
    return {
        "route": ROUTE_CUSTOM_QUERY if success else ROUTE_ERROR,
        "generated_sql": sql,
        "response_type": normalized_response_type,
        "reasoning_steps": list(reasoning_steps or []),
        "usage": usage or build_default_usage_meta(),
    }


def _reset_run_tracking() -> None:
    _usage_calls.set([])
    _reasoning_steps.set([])
    _llm_stage.set("unspecified")


def _append_reasoning_step(step: str) -> None:
    steps = _reasoning_steps.get()
    if isinstance(steps, list):
        steps.append(step)


def _current_reasoning_steps() -> list[str]:
    steps = _reasoning_steps.get()
    if isinstance(steps, list):
        return [str(step) for step in steps]
    return []


def _estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = _model_pricing_usd_per_1m.get(model)
    if not pricing:
        return 0.0
    input_cost = (max(prompt_tokens, 0) / 1_000_000) * pricing["input"]
    output_cost = (max(completion_tokens, 0) / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 8)


def _extract_usage_tokens(response: Any) -> tuple[int, int, int]:
    # LangChain AIMessage exposes token counts on .usage_metadata as
    # {input_tokens, output_tokens, total_tokens}. Map those onto our
    # prompt/completion naming.
    usage_metadata = getattr(response, "usage_metadata", None)
    if isinstance(usage_metadata, dict) and usage_metadata:
        prompt_tokens = int(usage_metadata.get("input_tokens") or 0)
        completion_tokens = int(usage_metadata.get("output_tokens") or 0)
        total_tokens = int(
            usage_metadata.get("total_tokens") or (prompt_tokens + completion_tokens)
        )
        return prompt_tokens, completion_tokens, total_tokens

    usage = getattr(response, "usage", None)
    if isinstance(usage, dict):
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
        return prompt_tokens, completion_tokens, total_tokens
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", 0) or (prompt_tokens + completion_tokens))
    return prompt_tokens, completion_tokens, total_tokens


def _record_llm_usage(model: str, response: Any, started_at: float) -> None:
    calls = _usage_calls.get()
    if not isinstance(calls, list):
        return
    prompt_tokens, completion_tokens, total_tokens = _extract_usage_tokens(response)
    latency_ms = int((time.monotonic() - started_at) * 1000)
    calls.append(
        {
            "stage": str(_llm_stage.get() or "unspecified"),
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "latency_ms": max(latency_ms, 0),
            "cost_usd": _estimate_cost_usd(model, prompt_tokens, completion_tokens),
        }
    )


def _current_usage_meta(total_db_time_ms: int = 0) -> UsageMeta:
    calls = _usage_calls.get()
    if not isinstance(calls, list):
        return build_default_usage_meta(total_db_time_ms=total_db_time_ms)
    llm_calls: list[LLMCallUsage] = []
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    total_llm_time_ms = 0
    total_cost_usd = 0.0
    for call in calls:
        if not isinstance(call, dict):
            continue
        prompt = int(call.get("prompt_tokens", 0) or 0)
        completion = int(call.get("completion_tokens", 0) or 0)
        total = int(call.get("total_tokens", 0) or 0)
        latency_ms = int(call.get("latency_ms", 0) or 0)
        cost_usd = float(call.get("cost_usd", 0.0) or 0.0)
        prompt_tokens += prompt
        completion_tokens += completion
        total_tokens += total
        total_llm_time_ms += latency_ms
        total_cost_usd += cost_usd
        llm_calls.append(
            {
                "stage": str(call.get("stage", "unspecified")),
                "model": str(call.get("model", "")),
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": total,
                "latency_ms": latency_ms,
                "cost_usd": round(cost_usd, 8),
            }
        )
    return {
        "llm_calls": llm_calls,
        "totals": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "total_llm_time_ms": total_llm_time_ms,
            "total_db_time_ms": max(int(total_db_time_ms), 0),
            "total_cost_usd": round(total_cost_usd, 8),
        },
    }


def _classify_generation_exception(exc: Exception) -> SQLGenerationErrorInfo:
    if APITimeoutError is not None and isinstance(exc, APITimeoutError):
        return {
            "type": "timeout",
            "message": "SQL service timed out while processing the request.",
            "debug": repr(exc),
        }
    if APIConnectionError is not None and isinstance(exc, APIConnectionError):
        return {
            "type": "network_error",
            "message": "Network error while contacting the SQL service.",
            "debug": repr(exc),
        }
    if RateLimitError is not None and isinstance(exc, RateLimitError):
        return {
            "type": "rate_limited",
            "message": "SQL service is currently rate-limited.",
            "debug": repr(exc),
        }
    if APIStatusError is not None and isinstance(exc, APIStatusError):
        status_code = getattr(exc, "status_code", None)
        if status_code in (401, 403):
            return {
                "type": "auth_error",
                "message": "SQL service authentication failed.",
                "debug": f"status={status_code} {exc!r}",
            }
        if isinstance(status_code, int) and status_code >= 500:
            return {
                "type": "service_unavailable",
                "message": "SQL service is temporarily unavailable.",
                "debug": f"status={status_code} {exc!r}",
            }
        return {
            "type": "upstream_error",
            "message": "SQL service returned an upstream error.",
            "debug": f"status={status_code} {exc!r}",
        }

    lowered = str(exc).lower()
    if "timed out" in lowered or "timeout" in lowered:
        return {
            "type": "timeout",
            "message": "SQL service timed out while processing the request.",
            "debug": repr(exc),
        }
    if "connection" in lowered or "network" in lowered or "dns" in lowered:
        return {
            "type": "network_error",
            "message": "Network error while contacting the SQL service.",
            "debug": repr(exc),
        }
    return {
        "type": "generation_failed",
        "message": "SQL generation failed unexpectedly.",
        "debug": repr(exc),
    }


def extract_sql(content: str) -> str:
    if not content:
        return "SELECT 'No response' as error;"
    if "```" in content:
        lines = [line for line in content.splitlines() if not line.strip().startswith("```")]
        content = "\n".join(lines)
    content = content.strip()
    lowered = content.lower()
    for prefix in SQL_PREFIXES:
        if lowered.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    return content.strip()


def _needs_limit(sql: str) -> bool:
    upper = sql.upper()
    if "LIMIT" in upper:
        return False
    if "GROUP BY" in upper or "DISTINCT" in upper:
        return False
    return not any(token in upper for token in AGGREGATE_TOKENS)


def _ensure_limit(sql: str) -> str:
    if _needs_limit(sql):
        return f"{sql} LIMIT {DEFAULT_LIMIT}"
    return sql


def _uses_data_jsonb(sql: str) -> bool:
    lower = sql.lower()
    return "data->" in lower or "data ->" in lower


def _mentions_company_id(sql: str) -> bool:
    return "company_id" in sql.lower()


def _mentions_historic_alarms(sql: str) -> bool:
    return "historic_alarms" in sql.lower()


def _collect_violations(sql: str, company_id: int) -> list[str]:
    violations: list[str] = []
    if not sql or not sql.strip():
        return ["empty_output"]
    if not is_safe_sql(sql):
        violations.append("not_a_single_safe_select")
    if _uses_data_jsonb(sql):
        violations.append("uses_data_jsonb_column")
    if not _mentions_historic_alarms(sql):
        violations.append("missing_historic_alarms_table")
    if not _mentions_company_id(sql):
        violations.append(f"missing_company_id_filter={company_id}")
    return violations


def _postprocess_sql(sql: str | None, company_id: int) -> str | None:
    if not sql:
        return None
    cleaned = extract_sql(sql)
    if is_safe_sql(cleaned):
        cleaned = _ensure_limit(cleaned)
        cleaned = sanitize_sql(cleaned, company_id)
    return cleaned


def _extract_first_json_object(raw_content: str | None) -> dict[str, Any] | None:
    if not raw_content:
        return None
    content = raw_content.strip()
    if not content:
        return None
    if "```" in content:
        lines = [line for line in content.splitlines() if not line.strip().startswith("```")]
        content = "\n".join(lines).strip()
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(content[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _ordered_columns(rows: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in row.keys():
            key_str = str(key)
            if key_str not in columns:
                columns.append(key_str)
    return columns


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _rows_to_csv(rows: list[dict[str, Any]]) -> str:
    columns = _ordered_columns(rows)
    if not columns:
        return ""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_csv_cell(row.get(column)) for column in columns])
    return output.getvalue()


def _normalize_response_type(value: Any) -> ResponseType:
    if isinstance(value, str) and value in VALID_RESPONSE_TYPES:
        return value  # type: ignore[return-value]
    return RESPONSE_TYPE_TABLE_RECORDS


@_traceable_if_enabled(run_type="llm", name="Results Summarizer LLM")
def _summarize_results_with_model(question: str, sql: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    sample_rows = rows[:30]
    payload = {
        "question": question,
        "sql": sql,
        "row_count": len(rows),
        "sample_rows": sample_rows,
    }
    summary_messages = build_summary_messages(payload)

    token = _llm_stage.set("summarize_results")
    try:
        started_at = time.monotonic()
        chat = get_chat_model(
            settings.openai_chat_model,
            temperature=0.2,
            max_tokens=600,
            timeout=settings.openai_sql_timeout_seconds,
        )
        ai_message: AIMessage = chat.invoke(summary_messages)
        _record_llm_usage(settings.openai_chat_model, ai_message, started_at)
    except Exception:
        return None
    finally:
        _llm_stage.reset(token)

    content = ai_message.content if isinstance(ai_message.content, str) else ""
    return _extract_first_json_object(content)


def _build_response_payload(
    question: str,
    sql: str,
    rows: list[dict[str, Any]],
) -> tuple[ResponseType, Any, str]:
    if not rows:
        summary = default_response(rows, question)
        return RESPONSE_TYPE_PLAIN_TEXT, summary, summary

    # Large result sets are returned as CSV without calling the LLM summarizer.
    if len(rows) > CSV_RESULT_THRESHOLD:
        summary = default_response(rows, question)
        return RESPONSE_TYPE_CSV, _rows_to_csv(rows), summary

    parsed = _summarize_results_with_model(question, sql, rows)
    summary = ""
    if isinstance(parsed, dict):
        model_summary = parsed.get("summary")
        if isinstance(model_summary, str) and model_summary.strip():
            summary = model_summary.strip()
    if not summary:
        summary = default_response(rows, question)

    response_type = _normalize_response_type(parsed.get("response_type") if isinstance(parsed, dict) else None)

    if response_type == RESPONSE_TYPE_GRAPH_JSON:
        graph_json = parsed.get("graph_json") if isinstance(parsed, dict) else None
        if isinstance(graph_json, dict):
            return RESPONSE_TYPE_GRAPH_JSON, graph_json, summary
        # Fall back to table payload if graph payload is missing/invalid.
        return RESPONSE_TYPE_TABLE_RECORDS, rows, summary

    if response_type == RESPONSE_TYPE_PLAIN_TEXT:
        return RESPONSE_TYPE_PLAIN_TEXT, summary, summary

    return RESPONSE_TYPE_TABLE_RECORDS, rows, summary


def generate_sql(
    question: str,
    company_id: int,
    schema_context: dict | None = None,
    conversation_messages: list[ConversationMessage] | None = None,
) -> str:
    return generate_sql_with_langgraph(question, company_id, schema_context, conversation_messages)


class SqlGraphState(TypedDict):
    question: str
    company_id: int
    schema_context: Optional[Dict[str, Any]]
    conversation_messages: Optional[list[ConversationMessage]]
    sql_a: Optional[str]
    sql_b: Optional[str]
    sql: Optional[str]


class QueryGraphState(TypedDict):
    db: Any
    question: str
    company_id: int
    schema_context: Optional[Dict[str, Any]]
    sql: Optional[str]
    raw_results: Any
    response_type: Optional[ResponseType]
    results: Any
    summary: str
    success: bool
    row_count: int
    db_time_ms: int


@_traceable_if_enabled(run_type="llm", name="SQL Generator LLM")
def _generate_with_model(model: str, prompt: str) -> Optional[str]:
    attempts = 0
    max_retries = max(settings.openai_sql_max_retries, 0)
    base_delay = max(settings.openai_sql_retry_base_delay, 0)
    last_error: SQLGenerationErrorInfo | None = None
    while True:
        try:
            if settings.langsmith_tracing:
                logger.info(
                    "OpenAI SQL generation call starting (model=%s attempt=%s/%s).",
                    model,
                    attempts + 1,
                    max_retries + 1,
                )
            start_time = time.monotonic()
            chat = get_chat_model(
                model,
                temperature=0,
                timeout=settings.openai_sql_timeout_seconds,
            )
            messages = build_sql_generation_messages(prompt)
            ai_message: AIMessage = chat.invoke(messages)
            _record_llm_usage(model, ai_message, start_time)
            if settings.langsmith_tracing:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                logger.info(
                    "OpenAI SQL generation call finished (model=%s duration_ms=%s).",
                    model,
                    duration_ms,
                )
            content = ai_message.content if isinstance(ai_message.content, str) else ""
            sql = extract_sql(content)
            return sql if sql else None
        except Exception as exc:
            last_error = _classify_generation_exception(exc)
            logger.warning(
                "SQL generation call failed model=%s attempt=%s/%s type=%s debug=%s",
                model,
                attempts + 1,
                max_retries + 1,
                last_error["type"],
                last_error["debug"],
            )
            if attempts >= max_retries:
                if last_error:
                    _last_generation_error.set(last_error)
                return None
            delay = base_delay * (2**attempts)
            delay = delay * (0.75 + random.random() * 0.5)
            time.sleep(delay)
            attempts += 1


def _generate_with_stage(model: str, prompt: str, stage: str) -> Optional[str]:
    token = _llm_stage.set(stage)
    try:
        return _generate_with_model(model, prompt)
    finally:
        _llm_stage.reset(token)


@_traceable_if_enabled(run_type="chain", name="SQL Candidate A")
def _node_sql_a(state: SqlGraphState) -> SqlGraphState:
    _append_reasoning_step("sql_candidate_a")
    prompt = build_prompt(
        state["question"],
        state["company_id"],
        state["schema_context"],
        state.get("conversation_messages"),
    )
    sql = _generate_with_stage(settings.openai_sql_model_a, prompt, "sql_candidate_a")
    # Return only the field owned by this parallel branch to avoid merge conflicts.
    return {"sql_a": sql}


@_traceable_if_enabled(run_type="chain", name="SQL Candidate B")
def _node_sql_b(state: SqlGraphState) -> SqlGraphState:
    _append_reasoning_step("sql_candidate_b")
    prompt = build_prompt(
        state["question"],
        state["company_id"],
        state["schema_context"],
        state.get("conversation_messages"),
    )
    sql = _generate_with_stage(settings.openai_sql_model_b, prompt, "sql_candidate_b")
    # Return only the field owned by this parallel branch to avoid merge conflicts.
    return {"sql_b": sql}


@_traceable_if_enabled(run_type="chain", name="SQL Refiner")
def _node_refine(state: SqlGraphState) -> SqlGraphState:
    _append_reasoning_step("sql_refine")
    sql_a = _postprocess_sql(state.get("sql_a"), state["company_id"])
    sql_b = _postprocess_sql(state.get("sql_b"), state["company_id"])
    if not sql_a and not sql_b:
        return {**state, "sql": None}

    violations_a = _collect_violations(sql_a or "", state["company_id"]) if sql_a else ["empty_output"]
    violations_b = _collect_violations(sql_b or "", state["company_id"]) if sql_b else ["empty_output"]

    if sql_a and not violations_a and not sql_b:
        return {**state, "sql": sql_a}
    if sql_b and not violations_b and not sql_a:
        return {**state, "sql": sql_b}
    if sql_a and sql_b:
        if not violations_a and violations_b:
            return {**state, "sql": sql_a}
        if not violations_b and violations_a:
            return {**state, "sql": sql_b}
        if not violations_a and not violations_b and sql_a.strip().lower() == sql_b.strip().lower():
            return {**state, "sql": sql_a}

    prompt = _build_refiner_prompt(
        question=state["question"],
        company_id=state["company_id"],
        sql_a=sql_a,
        sql_b=sql_b,
        violations_a=violations_a,
        violations_b=violations_b,
        schema_context=state["schema_context"],
        conversation_messages=state.get("conversation_messages"),
    )
    sql = _generate_with_stage(settings.openai_sql_refiner_model, prompt, "sql_refiner")
    return {**state, "sql": sql or sql_a or sql_b}


@_traceable_if_enabled(run_type="chain", name="SQL Finalize")
def _node_finalize(state: SqlGraphState) -> SqlGraphState:
    _append_reasoning_step("sql_finalize")
    sql = state.get("sql") or state.get("sql_a") or state.get("sql_b")
    if not sql:
        return {**state, "sql": None}
    sql = _postprocess_sql(sql, state["company_id"])
    violations = _collect_violations(sql or "", state["company_id"]) if sql else ["empty_output"]
    if violations:
        prompt = _build_repair_prompt(
            question=state["question"],
            company_id=state["company_id"],
            sql=sql or "",
            violations=violations,
            schema_context=state["schema_context"],
            conversation_messages=state.get("conversation_messages"),
        )
        repaired = _generate_with_stage(settings.openai_sql_refiner_model, prompt, "sql_repair")
        repaired = _postprocess_sql(repaired, state["company_id"]) if repaired else None
        if repaired:
            sql = repaired
    if not sql or not is_safe_sql(sql):
        return {**state, "sql": None}
    return {**state, "sql": sql}


_graph = None
_query_graph = None


@_traceable_if_enabled(run_type="chain", name="Pipeline SQL Generation")
def _node_pipeline_generate_sql(state: QueryGraphState) -> QueryGraphState:
    _append_reasoning_step("generate_sql")
    sql = generate_sql_with_langgraph(
        question=state["question"],
        company_id=state["company_id"],
        schema_context=state["schema_context"],
    )
    return {"sql": sql}


@_traceable_if_enabled(run_type="chain", name="Pipeline SQL Execution")
def _node_pipeline_execute_sql(state: QueryGraphState) -> QueryGraphState:
    _append_reasoning_step("execute_sql")
    sql = state.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        return {
            "raw_results": {"error": "No SQL generated"},
            "row_count": 0,
            "success": False,
            "db_time_ms": 0,
        }
    started_at = time.monotonic()
    # The agent invokes its database-execution capability through a real
    # langchain_core @tool (see backend/app/services/tools.py). The tool wraps
    # execute_safe_query so the deterministic safety contract — single SELECT,
    # company_id injection, statement timeout — is preserved.
    raw_results = execute_alarm_sql.invoke(
        {"sql": sql, "company_id": state["company_id"], "db": state["db"]}
    )
    db_time_ms = int((time.monotonic() - started_at) * 1000)
    row_count = len(raw_results) if isinstance(raw_results, list) else 0
    success = not (isinstance(raw_results, dict) and raw_results.get("error"))
    return {
        "raw_results": raw_results,
        "row_count": row_count,
        "success": success,
        "db_time_ms": max(db_time_ms, 0),
    }


@_traceable_if_enabled(run_type="chain", name="Pipeline Summarize Results")
def _node_pipeline_summarize(state: QueryGraphState) -> QueryGraphState:
    _append_reasoning_step("summarize_results")
    raw_results = state.get("raw_results")
    sql = state.get("sql") or ""

    if isinstance(raw_results, dict) and raw_results.get("error"):
        message = str(raw_results.get("error") or "Query failed")
        return {
            "response_type": RESPONSE_TYPE_PLAIN_TEXT,
            "results": message,
            "summary": message,
            "success": False,
        }

    if not isinstance(raw_results, list):
        message = "Unable to summarize query results."
        return {
            "response_type": RESPONSE_TYPE_PLAIN_TEXT,
            "results": message,
            "summary": message,
            "success": False,
        }

    response_type, payload, summary = _build_response_payload(
        question=state["question"],
        sql=sql,
        rows=raw_results,
    )
    return {
        "response_type": response_type,
        "results": payload,
        "summary": summary,
        "success": True,
    }


def _get_graph():
    global _graph
    if _graph is None:
        graph = StateGraph(SqlGraphState)
        graph.add_node("sql_a", _node_sql_a)
        graph.add_node("sql_b", _node_sql_b)
        graph.add_node("refine", _node_refine)
        graph.add_node("finalize", _node_finalize)
        graph.add_edge(START, "sql_a")
        graph.add_edge(START, "sql_b")
        # Both candidates run in parallel and converge at refine.
        graph.add_edge("sql_a", "refine")
        graph.add_edge("sql_b", "refine")
        graph.add_edge("refine", "finalize")
        graph.add_edge("finalize", END)
        _graph = graph.compile()
    return _graph


def _get_query_graph():
    global _query_graph
    if _query_graph is None:
        graph = StateGraph(QueryGraphState)
        graph.add_node("generate_sql", _node_pipeline_generate_sql)
        graph.add_node("execute_sql", _node_pipeline_execute_sql)
        graph.add_node("summarize", _node_pipeline_summarize)
        graph.add_edge(START, "generate_sql")
        graph.add_edge("generate_sql", "execute_sql")
        graph.add_edge("execute_sql", "summarize")
        graph.add_edge("summarize", END)
        _query_graph = graph.compile()
    return _query_graph


@_traceable_if_enabled(run_type="chain", name="LangGraph SQL Generation")
def generate_sql_with_langgraph(
    question: str,
    company_id: int,
    schema_context: dict | None = None,
    conversation_messages: list[ConversationMessage] | None = None,
) -> str:
    clear_last_generation_error()
    try:
        state: SqlGraphState = {
            "question": question,
            "company_id": company_id,
            "schema_context": schema_context,
            "conversation_messages": conversation_messages,
            "sql_a": None,
            "sql_b": None,
            "sql": None,
        }
        result = _get_graph().invoke(state)
        sql = result.get("sql") or result.get("sql_a") or result.get("sql_b")
        if not sql:
            error_info = get_last_generation_error() or {
                "type": "service_unavailable",
                "message": "SQL service is temporarily unavailable.",
                "debug": "no_sql_candidates_generated",
            }
            _last_generation_error.set(error_info)
            raise SQLGenerationException(error_info)
        return sql
    except SQLGenerationException:
        raise
    except Exception as exc:
        classified = _classify_generation_exception(exc)
        _last_generation_error.set(classified)
        logger.exception(
            "LangGraph SQL generation failed type=%s debug=%s",
            classified["type"],
            classified["debug"],
        )
        raise SQLGenerationException(classified) from exc


@_traceable_if_enabled(run_type="chain", name="LangGraph SQL Query Pipeline")
def generate_query_result_with_langgraph(
    db: Any,
    question: str,
    company_id: int,
    schema_context: dict | None = None,
) -> QueryPipelineResult:
    _reset_run_tracking()
    try:
        state: QueryGraphState = {
            "db": db,
            "question": question,
            "company_id": company_id,
            "schema_context": schema_context,
            "sql": None,
            "raw_results": [],
            "response_type": None,
            "results": [],
            "summary": "",
            "success": False,
            "row_count": 0,
            "db_time_ms": 0,
        }
        result = _get_query_graph().invoke(state)
        sql = result.get("sql") or ""
        response_type = result.get("response_type")
        if not isinstance(response_type, str) or response_type not in VALID_RESPONSE_TYPES:
            response_type = RESPONSE_TYPE_PLAIN_TEXT
        summary = result.get("summary")
        if not isinstance(summary, str):
            summary = ""
        row_count = result.get("row_count")
        if not isinstance(row_count, int):
            row_count = 0
        db_time_ms = result.get("db_time_ms")
        if not isinstance(db_time_ms, int):
            db_time_ms = 0
        success = bool(result.get("success")) and bool(sql)
        meta = build_default_query_meta(
            sql=sql,
            response_type=response_type,
            success=success,
            reasoning_steps=_current_reasoning_steps(),
            usage=_current_usage_meta(total_db_time_ms=db_time_ms),
        )
        return {
            "sql": sql,
            "success": success,
            "response_type": response_type,  # type: ignore[typeddict-item]
            "results": result.get("results"),
            "summary": summary,
            "row_count": row_count,
            "meta": meta,
        }
    except SQLGenerationException:
        raise
    except Exception:
        logger.exception("LangGraph SQL query pipeline failed")
        meta = build_default_query_meta(
            sql="",
            response_type=RESPONSE_TYPE_PLAIN_TEXT,
            success=False,
            reasoning_steps=_current_reasoning_steps(),
            usage=_current_usage_meta(total_db_time_ms=0),
        )
        return {
            "sql": "",
            "success": False,
            "response_type": RESPONSE_TYPE_PLAIN_TEXT,
            "results": "Unable to process request.",
            "summary": "Unable to process request.",
            "row_count": 0,
            "meta": meta,
        }
