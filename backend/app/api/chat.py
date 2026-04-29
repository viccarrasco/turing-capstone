import hashlib
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import QueryLog
from ..redis_client import get_redis
from ..schemas import (
    ChatQueryRequest,
    ChatQueryResponse,
    V1QueryError,
    V1QueryMeta,
    V1QueryRequest,
    V1QueryResponse,
)
from ..security import require_api_key, require_company_id
from ..services.sql_generation_errors import build_sql_generation_user_error
from ..services.sql_generator import (
    RESPONSE_TYPE_CSV,
    RESPONSE_TYPE_GRAPH_JSON,
    RESPONSE_TYPE_PLAIN_TEXT,
    RESPONSE_TYPE_TABLE_RECORDS,
    SQLGenerationException,
    build_default_query_meta,
    build_default_usage_meta,
    generate_query_result_with_langgraph,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_redis_safe():
    try:
        return get_redis()
    except Exception:
        logger.warning("Redis client unavailable", exc_info=True)
        return None


def _query_cache_key(company_id: int, question: str) -> str:
    # md5 is sufficient for stable cache keys; cryptographic strength is not required.
    digest = hashlib.md5(question.encode("utf-8")).hexdigest()
    return f"query:{company_id}:{digest}"


def _evict_cache_key(redis_client, cache_key: str):
    if redis_client is None:
        return
    try:
        redis_client.delete(cache_key)
    except Exception:
        pass


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _infer_response_type(results: Any) -> str:
    if isinstance(results, list):
        return RESPONSE_TYPE_TABLE_RECORDS
    if isinstance(results, str):
        # Backward-compatible heuristic for legacy cache payloads.
        if "," in results and "\n" in results:
            return RESPONSE_TYPE_CSV
        return RESPONSE_TYPE_PLAIN_TEXT
    if isinstance(results, dict):
        if {"labels", "datasets", "chart_type", "series"} & set(results.keys()):
            return RESPONSE_TYPE_GRAPH_JSON
        return RESPONSE_TYPE_PLAIN_TEXT
    return RESPONSE_TYPE_PLAIN_TEXT


def _normalize_usage_meta(raw_usage: Any) -> dict[str, Any]:
    usage = build_default_usage_meta()
    if not isinstance(raw_usage, dict):
        return usage

    raw_calls = raw_usage.get("llm_calls")
    if isinstance(raw_calls, list):
        cleaned_calls: list[dict[str, Any]] = []
        for item in raw_calls:
            if not isinstance(item, dict):
                continue
            cleaned_calls.append(
                {
                    "stage": str(item.get("stage", "unspecified")),
                    "model": str(item.get("model", "")),
                    "prompt_tokens": max(_safe_int(item.get("prompt_tokens"), 0), 0),
                    "completion_tokens": max(_safe_int(item.get("completion_tokens"), 0), 0),
                    "total_tokens": max(_safe_int(item.get("total_tokens"), 0), 0),
                    "latency_ms": max(_safe_int(item.get("latency_ms"), 0), 0),
                    "cost_usd": max(round(_safe_float(item.get("cost_usd"), 0.0), 8), 0.0),
                }
            )
        usage["llm_calls"] = cleaned_calls

    totals = usage["totals"]
    raw_totals = raw_usage.get("totals")
    if isinstance(raw_totals, dict):
        totals["prompt_tokens"] = max(_safe_int(raw_totals.get("prompt_tokens"), totals["prompt_tokens"]), 0)
        totals["completion_tokens"] = max(
            _safe_int(raw_totals.get("completion_tokens"), totals["completion_tokens"]),
            0,
        )
        totals["total_tokens"] = max(_safe_int(raw_totals.get("total_tokens"), totals["total_tokens"]), 0)
        totals["total_llm_time_ms"] = max(
            _safe_int(raw_totals.get("total_llm_time_ms"), totals["total_llm_time_ms"]),
            0,
        )
        totals["total_db_time_ms"] = max(
            _safe_int(raw_totals.get("total_db_time_ms"), totals["total_db_time_ms"]),
            0,
        )
        totals["total_cost_usd"] = max(
            round(_safe_float(raw_totals.get("total_cost_usd"), totals["total_cost_usd"]), 8),
            0.0,
        )
    return usage


def _normalize_meta(
    raw_meta: Any,
    sql: str,
    response_type: str,
    success: bool,
    cached: bool,
) -> dict[str, Any]:
    base_meta = build_default_query_meta(
        sql=sql,
        response_type=response_type,
        success=success,
        reasoning_steps=[],
        usage=build_default_usage_meta(),
    )
    meta: dict[str, Any] = {
        "route": base_meta["route"],
        "generated_sql": base_meta["generated_sql"],
        "response_type": base_meta["response_type"],
        "reasoning_steps": list(base_meta["reasoning_steps"]),
        "usage": dict(base_meta["usage"]),
        "cached": bool(cached),
    }
    if not isinstance(raw_meta, dict):
        return meta

    route = raw_meta.get("route")
    if isinstance(route, str) and route.strip():
        meta["route"] = route.strip()

    generated_sql = raw_meta.get("generated_sql")
    if isinstance(generated_sql, str):
        meta["generated_sql"] = generated_sql

    raw_response_type = raw_meta.get("response_type")
    if isinstance(raw_response_type, str) and raw_response_type.strip():
        meta["response_type"] = raw_response_type.strip()

    reasoning_steps = raw_meta.get("reasoning_steps")
    if isinstance(reasoning_steps, list):
        meta["reasoning_steps"] = [str(step) for step in reasoning_steps]

    meta["usage"] = _normalize_usage_meta(raw_meta.get("usage"))
    meta["cached"] = bool(cached)
    return meta


def _load_cached_query(redis_client, cache_key: str) -> dict[str, Any] | None:
    if redis_client is None:
        return None

    try:
        cached = redis_client.get(cache_key)
    except Exception:
        return None

    if not cached:
        return None

    try:
        payload = json.loads(cached)
    except (TypeError, json.JSONDecodeError):
        _evict_cache_key(redis_client, cache_key)
        return None

    if not isinstance(payload, dict):
        _evict_cache_key(redis_client, cache_key)
        return None

    sql = payload.get("sql")
    results = payload.get("results")
    response_type = payload.get("response_type")
    summary = payload.get("summary")
    row_count = payload.get("row_count")
    success = payload.get("success")

    if not isinstance(sql, str):
        _evict_cache_key(redis_client, cache_key)
        return None

    if not isinstance(response_type, str):
        response_type = _infer_response_type(results)
    if not isinstance(summary, str):
        summary = ""
    if not isinstance(row_count, int):
        row_count = len(results) if isinstance(results, list) else 0
    if not isinstance(success, bool):
        success = not (isinstance(results, dict) and results.get("error"))

    meta = _normalize_meta(
        raw_meta=payload.get("meta"),
        sql=sql,
        response_type=response_type,
        success=success,
        cached=True,
    )
    return {
        "sql": sql,
        "results": results,
        "response_type": response_type,
        "summary": summary,
        "row_count": row_count,
        "success": success,
        "meta": meta,
    }


def _store_cached_query(
    redis_client,
    cache_key: str,
    sql: str,
    results: Any,
    response_type: str,
    summary: str,
    row_count: int,
    success: bool,
    meta: dict[str, Any],
):
    if redis_client is None:
        return

    payload = json.dumps(
        {
            "sql": sql,
            "results": results,
            "response_type": response_type,
            "summary": summary,
            "row_count": row_count,
            "success": success,
            "meta": meta,
        },
        default=str,
    )
    try:
        redis_client.setex(cache_key, settings.cache_ttl_seconds, payload)
    except Exception:
        pass


def enforce_rate_limit(request: Request):
    redis_client = _get_redis_safe()
    if redis_client is None:
        return

    ip = request.client.host if request.client else "unknown"
    key = f"chat_query:{ip}"

    try:
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, 60)
    except Exception:
        return

    if count > settings.rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


def _persist_query_log(
    db: Session,
    question: str,
    company_id: int,
    sql_query: str,
    result_count: int,
    execution_time: float,
) -> None:
    try:
        db.add(
            QueryLog(
                question=question,
                sql_query=sql_query,
                company_id=company_id,
                result_count=result_count,
                execution_time=execution_time,
            )
        )
        db.commit()
    except Exception:
        db.rollback()


def _run_query_flow(db: Session, question: str, company_id: int) -> dict[str, Any]:
    cache_key = _query_cache_key(company_id, question)
    redis_client = _get_redis_safe()

    cached = _load_cached_query(redis_client, cache_key)
    if cached is not None:
        return {
            **cached,
            "log_sql": cached["sql"],
        }

    try:
        pipeline_result = generate_query_result_with_langgraph(
            db=db,
            question=question,
            company_id=company_id,
            schema_context=None,
        )
    except SQLGenerationException as exc:
        user_error = build_sql_generation_user_error(exc.error_info)
        logger.error(
            "SQL generation unavailable company_id=%s type=%s debug=%s question=%r",
            company_id,
            user_error["type"],
            exc.error_info.get("debug"),
            question,
        )
        meta = _normalize_meta(
            raw_meta=None,
            sql="",
            response_type=RESPONSE_TYPE_PLAIN_TEXT,
            success=False,
            cached=False,
        )
        return {
            "success": False,
            "results": user_error,
            "sql": "",
            "response_type": RESPONSE_TYPE_PLAIN_TEXT,
            "summary": user_error["error"],
            "row_count": 0,
            "meta": meta,
            "log_sql": f"SQL_GENERATION_ERROR:{user_error['type']}",
        }

    sql = pipeline_result.get("sql", "")
    results = pipeline_result.get("results")
    response_type = pipeline_result.get("response_type", RESPONSE_TYPE_PLAIN_TEXT)
    summary = pipeline_result.get("summary", "")
    row_count = pipeline_result.get("row_count", 0)
    success = bool(pipeline_result.get("success"))
    if not isinstance(summary, str):
        summary = ""
    if not isinstance(row_count, int):
        row_count = len(results) if isinstance(results, list) else 0
    if not isinstance(response_type, str):
        response_type = _infer_response_type(results)

    meta = _normalize_meta(
        raw_meta=pipeline_result.get("meta"),
        sql=sql if isinstance(sql, str) else "",
        response_type=response_type,
        success=success,
        cached=False,
    )
    result = {
        "success": success,
        "results": results,
        "sql": sql if isinstance(sql, str) else "",
        "response_type": response_type,
        "summary": summary,
        "row_count": row_count,
        "meta": meta,
        "log_sql": sql if isinstance(sql, str) else "",
    }
    _store_cached_query(
        redis_client=redis_client,
        cache_key=cache_key,
        sql=result["sql"],
        results=result["results"],
        response_type=result["response_type"],
        summary=result["summary"],
        row_count=result["row_count"],
        success=result["success"],
        meta=result["meta"],
    )
    return result


def _build_v1_response(result: dict[str, Any]) -> V1QueryResponse:
    response_type = str(result.get("response_type") or RESPONSE_TYPE_PLAIN_TEXT)
    results = result.get("results")
    summary = result.get("summary")
    answer = summary if isinstance(summary, str) and summary.strip() else None

    chart_data = None
    table_records = None
    csv_inline = None
    if response_type == RESPONSE_TYPE_GRAPH_JSON and isinstance(results, dict):
        chart_data = results
    elif response_type == RESPONSE_TYPE_TABLE_RECORDS and isinstance(results, list):
        table_records = results
    elif response_type == RESPONSE_TYPE_CSV and isinstance(results, str):
        csv_inline = results
    elif response_type == RESPONSE_TYPE_PLAIN_TEXT and isinstance(results, str) and not answer:
        answer = results

    error = None
    if not bool(result.get("success")):
        error_type = "query_error"
        error_message = "Unable to process request."
        if isinstance(results, dict):
            error_type = str(results.get("type") or error_type)
            maybe_error = results.get("error") or results.get("message")
            if isinstance(maybe_error, str) and maybe_error.strip():
                error_message = maybe_error.strip()
        elif isinstance(results, str) and results.strip():
            error_message = results.strip()
        error = V1QueryError(type=error_type, message=error_message)
        if not answer:
            answer = error_message

    raw_meta = result.get("meta")
    meta = V1QueryMeta(**raw_meta) if isinstance(raw_meta, dict) else V1QueryMeta()
    return V1QueryResponse(
        answer=answer,
        chart_data=chart_data,
        table_records=table_records,
        csv_inline=csv_inline,
        error=error,
        meta=meta,
    )


@router.post(
    "/api/chat/query",
    response_model=ChatQueryResponse,
    dependencies=[Depends(require_api_key), Depends(enforce_rate_limit)],
)
def chat_query(payload: ChatQueryRequest, db: Session = Depends(get_db)):
    start = time.time()

    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    company_id = payload.company_id
    query_result = _run_query_flow(db=db, question=question, company_id=company_id)
    execution_time = time.time() - start
    _persist_query_log(
        db=db,
        question=question,
        company_id=company_id,
        sql_query=str(query_result.get("log_sql") or ""),
        result_count=max(_safe_int(query_result.get("row_count"), 0), 0),
        execution_time=execution_time,
    )

    return ChatQueryResponse(
        success=bool(query_result.get("success")),
        results=query_result.get("results"),
        sql=str(query_result.get("sql") or ""),
        execution_time=execution_time,
        response_type=str(query_result.get("response_type") or RESPONSE_TYPE_PLAIN_TEXT),
        summary=str(query_result.get("summary") or ""),
    )


@router.post(
    "/api/v1/query",
    response_model=V1QueryResponse,
    dependencies=[Depends(require_api_key), Depends(enforce_rate_limit)],
)
def query_v1(
    payload: V1QueryRequest,
    company_id: int = Depends(require_company_id),
    db: Session = Depends(get_db),
):
    start = time.time()
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    query_result = _run_query_flow(db=db, question=question, company_id=company_id)
    execution_time = time.time() - start
    _persist_query_log(
        db=db,
        question=question,
        company_id=company_id,
        sql_query=str(query_result.get("log_sql") or ""),
        result_count=max(_safe_int(query_result.get("row_count"), 0), 0),
        execution_time=execution_time,
    )
    return _build_v1_response(query_result)
