from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from ...models import HistoricAlarm, ImportCursor
from .constants import SOURCE_MONGO
from .transform import coerce_types, filter_target_fields, transform_postgres_record, transform_record
from .validation import validate_record


def chunked(items: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def get_or_create_cursor(session, source: str, cursor_field: str) -> ImportCursor:
    cursor = session.execute(
        select(ImportCursor).where(
            ImportCursor.source == source,
            ImportCursor.cursor_field == cursor_field,
        )
    ).scalar_one_or_none()
    if cursor:
        return cursor

    cursor = ImportCursor(source=source, cursor_field=cursor_field, last_alarm_id=None)
    session.add(cursor)
    session.commit()
    session.refresh(cursor)
    return cursor


def update_cursor(session, cursor: ImportCursor, last_value: int | None):
    if last_value is None:
        return
    cursor.last_alarm_id = int(last_value)
    cursor.updated_at = datetime.utcnow()
    session.add(cursor)
    session.commit()


def fetch_postgres_records(
    engine,
    table: str,
    cursor_field: str,
    last_value: int | None,
    limit: int,
) -> list[dict[str, Any]]:
    where_clause = f"WHERE {cursor_field} > :last_value" if last_value is not None else ""
    query = text(f"SELECT * FROM {table} {where_clause} ORDER BY {cursor_field} ASC LIMIT :limit")

    params = {"limit": limit}
    if last_value is not None:
        params["last_value"] = last_value

    with engine.connect() as conn:
        result = conn.execute(query, params)
        return [dict(row._mapping) for row in result]


def fetch_mongo_records(
    client,
    database: str,
    collection: str,
    cursor_field: str,
    last_value: int | None,
    limit: int,
) -> list[dict[str, Any]]:
    mongo_collection = client[database][collection]
    if last_value is None:
        query = {}
        cursor = mongo_collection.find(query).sort(cursor_field, 1).limit(limit)
        return list(cursor)

    # Try a bounded cursor window first for dense sequential IDs.
    bounded_query = {cursor_field: {"$gt": last_value, "$lte": last_value + limit}}
    bounded_cursor = mongo_collection.find(bounded_query).sort(cursor_field, 1).limit(limit)
    bounded_records = list(bounded_cursor)
    if bounded_records:
        return bounded_records

    # Fallback keeps progress safe for sparse/non-sequential ID spaces.
    query = {cursor_field: {"$gt": last_value}}
    cursor = mongo_collection.find(query).sort(cursor_field, 1).limit(limit)
    return list(cursor)


def prepare_records(records: list[dict[str, Any]], batch_id: str, source: str) -> tuple[list[dict[str, Any]], list[str]]:
    prepared: list[dict[str, Any]] = []
    errors: list[str] = []

    for record in records:
        validation_errors = validate_record(record)
        if validation_errors:
            errors.extend(validation_errors)
            continue

        if source == SOURCE_MONGO:
            transformed = transform_record(record, batch_id)
        else:
            transformed = transform_postgres_record(record, batch_id)

        try:
            coerced = coerce_types(transformed)
        except Exception as exc:
            errors.append(str(exc))
            continue

        filtered = filter_target_fields(coerced)
        if not filtered.get("created_at") or not filtered.get("company_id"):
            errors.append("Missing required fields after transformation")
            continue

        prepared.append(filtered)

    return prepared, errors


def filter_existing_by_alarm_id(session, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alarm_ids = [row.get("alarm_id") for row in rows if row.get("alarm_id") is not None]
    if not alarm_ids:
        return rows

    existing = session.execute(
        select(HistoricAlarm.alarm_id).where(HistoricAlarm.alarm_id.in_(alarm_ids))
    ).scalars().all()
    existing_set = set(existing)
    return [row for row in rows if row.get("alarm_id") not in existing_set]


def ingest_rows(session, rows: list[dict[str, Any]], batch_size: int, dry_run: bool) -> int:
    inserted = 0
    for chunk in chunked(rows, batch_size):
        to_insert = filter_existing_by_alarm_id(session, chunk)
        if not to_insert:
            continue

        if not dry_run:
            all_keys = set().union(*to_insert)
            normalized = [{k: row.get(k) for k in all_keys} for row in to_insert]
            session.execute(insert(HistoricAlarm).values(normalized).on_conflict_do_nothing())
            session.commit()

        inserted += len(to_insert)

    return inserted


def last_cursor_value(records: list[dict[str, Any]], cursor_field: str) -> int | None:
    values = [record.get(cursor_field) for record in records if record.get(cursor_field) is not None]
    if not values:
        return None
    return int(max(values))
