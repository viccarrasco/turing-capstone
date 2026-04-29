from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ..config import settings
from .sql_validator import is_safe_sql, sanitize_sql

try:  # psycopg is used via SQLAlchemy (psycopg3)
    from psycopg.errors import UndefinedTable as _PsycopgUndefinedTable
except Exception:  # pragma: no cover
    _PsycopgUndefinedTable = None


def _jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return str(value)


def execute_safe_query(db, sql: str, company_id: int):
    if not is_safe_sql(sql):
        return {"error": "Invalid SQL"}

    sanitized = sanitize_sql(sql, company_id)
    timeout = f"{settings.openai_sql_timeout_seconds}s"

    db.execute(text(f"SET statement_timeout = '{timeout}'"))
    try:
        result = db.execute(text(sanitized))
        rows = [dict(row._mapping) for row in result]
        return _jsonable(rows)
    except Exception as exc:
        db.rollback()
        hint = ""
        orig = getattr(exc, "orig", None)
        if _PsycopgUndefinedTable and isinstance(orig, _PsycopgUndefinedTable):
            hint = " (missing table; run migrations: `alembic -c alembic.ini upgrade head` or `docker compose exec api alembic -c alembic.ini upgrade head`)"
        return {"error": f"Query failed: {exc}{hint}"}
    finally:
        db.execute(text("RESET statement_timeout"))
