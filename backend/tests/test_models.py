from sqlalchemy import Boolean, CheckConstraint, UniqueConstraint

from app import models


def test_conversation_model_columns():
    table = models.Conversation.__table__
    assert table.name == "conversations"
    for column in ("id", "company_id", "title", "created_at", "updated_at"):
        assert column in table.c


def test_message_role_constraint_exists():
    constraints = [
        constraint
        for constraint in models.Message.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    assert any(constraint.name == "chk_messages_role" for constraint in constraints)


def test_import_cursor_unique_constraint_exists():
    constraints = [
        constraint
        for constraint in models.ImportCursor.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    assert any(constraint.name == "uq_import_cursors_source_cursor" for constraint in constraints)


def test_historic_alarm_primary_key_and_columns():
    table = models.HistoricAlarm.__table__
    pk_columns = {col.name for col in table.primary_key.columns}
    assert pk_columns == {"id", "company_id", "created_at"}
    assert "alarm_id" in table.c
    assert isinstance(table.c.alarm_delegated.type, Boolean)


def test_query_log_model_columns():
    table = models.QueryLog.__table__
    assert table.name == "query_logs"
    for column in ("id", "question", "sql_query", "company_id", "result_count", "execution_time"):
        assert column in table.c
