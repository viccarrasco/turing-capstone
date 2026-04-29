import time

import typer
from sqlalchemy import create_engine

from ...config import settings
from ...db import SessionLocal
from .constants import (
    CURSOR_FIELD_DEFAULT,
    DEFAULT_BATCH_LIMIT,
    DEFAULT_BATCH_SIZE,
    DEFAULT_INTERVAL_SECONDS,
    SOURCE_MONGO,
    SOURCE_POSTGRES,
)
from .ingest import (
    fetch_mongo_records,
    fetch_postgres_records,
    get_or_create_cursor,
    ingest_rows,
    last_cursor_value,
    prepare_records,
    update_cursor,
)
from .optional_deps import MongoClient
from .validation import validate_identifier


def sync(
    batch_size: int = DEFAULT_BATCH_SIZE,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    cursor_field: str = CURSOR_FIELD_DEFAULT,
    source_postgres_table: str | None = None,
    source_mongo_collection: str | None = None,
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate and report without inserting."),
    once: bool = typer.Option(False, "--once", help="Run one sync cycle and exit."),
):
    """Continuously pull from source Postgres + MongoDB every interval."""

    cursor_field = validate_identifier(cursor_field, "cursor_field")
    source_postgres_table = source_postgres_table or settings.source_postgres_table
    source_mongo_collection = source_mongo_collection or settings.source_mongo_collection

    postgres_engine = None
    mongo_client = None

    if settings.source_postgres_url:
        validate_identifier(source_postgres_table, "source_postgres_table")
        postgres_engine = create_engine(settings.source_postgres_url, pool_pre_ping=True)

    if settings.source_mongo_url:
        if MongoClient is None:
            typer.echo("pymongo is not installed. Add pymongo to requirements.txt")
            raise typer.Exit(code=1)
        mongo_client = MongoClient(settings.source_mongo_url)

    if not postgres_engine and not mongo_client:
        typer.echo("No source connections configured. Set SOURCE_POSTGRES_URL and/or SOURCE_MONGO_URL")
        raise typer.Exit(code=1)

    sources = []
    if postgres_engine:
        sources.append(SOURCE_POSTGRES)
    if mongo_client:
        sources.append(SOURCE_MONGO)

    while True:
        for source in sources:
            session = SessionLocal()
            try:
                cursor = get_or_create_cursor(session, source, cursor_field)
                last_value = cursor.last_alarm_id
                batch_id = f"sync_{source}_{int(time.time())}"

                if source == SOURCE_POSTGRES:
                    records = fetch_postgres_records(
                        postgres_engine,
                        source_postgres_table,
                        cursor_field,
                        last_value,
                        batch_limit,
                    )
                else:
                    records = fetch_mongo_records(
                        mongo_client,
                        settings.source_mongo_db,
                        source_mongo_collection,
                        cursor_field,
                        last_value,
                        batch_limit,
                    )

                if not records:
                    typer.echo(f"[{source}] No new records")
                    continue

                prepared, errors = prepare_records(records, batch_id, source)
                inserted = ingest_rows(session, prepared, batch_size, dry_run)
                last_seen = last_cursor_value(records, cursor_field)
                update_cursor(session, cursor, last_seen)

                typer.echo(
                    f"[{source}] fetched={len(records)} inserted={inserted} last_{cursor_field}={last_seen}"
                )
                if errors:
                    typer.echo(f"[{source}] errors={len(errors)} sample={errors[0]}")
            finally:
                session.close()

        if once:
            break
        time.sleep(interval_seconds)
