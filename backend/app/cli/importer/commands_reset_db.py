import re
from pathlib import Path

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from ...config import settings


def reset_db(
    schema: str = typer.Option("public", "--schema", help="Schema to drop/recreate."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt."),
    skip_migrate: bool = typer.Option(False, "--skip-migrate", help="Skip running migrations."),
):
    """Drop and recreate a schema, then run Alembic migrations."""

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        typer.echo(f"Invalid schema name: {schema}")
        raise typer.Exit(code=1)

    if not yes:
        confirmed = typer.confirm(
            f"This will DROP schema '{schema}' and all data. Continue?",
            default=False,
        )
        if not confirmed:
            typer.echo("Aborted.")
            raise typer.Exit(code=0)

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    with engine.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))

    if not skip_migrate:
        alembic_ini = Path(__file__).resolve().parents[3] / "alembic.ini"
        cfg = Config(str(alembic_ini))
        command.upgrade(cfg, "head")
        typer.echo("Database reset complete and migrations applied.")
    else:
        typer.echo("Database reset complete. Migrations skipped.")
