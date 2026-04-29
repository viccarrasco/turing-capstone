from datetime import datetime

import typer
from sqlalchemy import select, text

from ...config import settings
from ...db import SessionLocal
from ...models import Conversation, HistoricAlarm, ImportCursor, Message, QueryLog


def shell():
    """Interactive shell (rails console-style)."""

    session = SessionLocal()
    try:
        engine = session.get_bind()

        def exec_sql(sql: str, **params):
            result = session.execute(text(sql), params)
            if result.returns_rows:
                return [dict(row._mapping) for row in result]
            return result.rowcount

        models = {
            "HistoricAlarm": HistoricAlarm,
            "Conversation": Conversation,
            "Message": Message,
            "QueryLog": QueryLog,
            "ImportCursor": ImportCursor,
        }

        banner = (
            "Seon History Shell\n"
            "Helpers: session, engine, models, exec_sql, select, text, settings, utcnow\n"
            "Example: session.execute(select(models['HistoricAlarm']).limit(5)).scalars().all()"
        )
        namespace = {
            "session": session,
            "engine": engine,
            "models": models,
            "HistoricAlarm": HistoricAlarm,
            "Conversation": Conversation,
            "Message": Message,
            "QueryLog": QueryLog,
            "ImportCursor": ImportCursor,
            "select": select,
            "text": text,
            "settings": settings,
            "exec_sql": exec_sql,
            "utcnow": datetime.utcnow,
        }

        try:
            from IPython import start_ipython  # type: ignore

            typer.echo("Starting IPython shell...")
            start_ipython(argv=[], user_ns=namespace)
        except Exception:
            import code

            typer.echo("IPython not available. Falling back to basic Python shell.")
            code.interact(banner=banner, local=namespace)
    finally:
        session.close()
