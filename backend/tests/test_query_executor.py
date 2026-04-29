import app.services.query_executor as query_executor
from decimal import Decimal


class DummyRow:
    def __init__(self, mapping):
        self._mapping = mapping


class DummyResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter([DummyRow(row) for row in self._rows])


class DummyDB:
    def __init__(self):
        self.calls = []
        self.rolled_back = False

    def execute(self, stmt):
        text = stmt.text if hasattr(stmt, "text") else str(stmt)
        self.calls.append(text)
        if text.startswith("SELECT"):
            return DummyResult([{"value": Decimal("1.25")}])
        return DummyResult([])

    def rollback(self):
        self.rolled_back = True


def test_execute_safe_query_rejects_invalid_sql(monkeypatch):
    monkeypatch.setattr(query_executor, "is_safe_sql", lambda sql: False)
    db = DummyDB()
    result = query_executor.execute_safe_query(db, "UPDATE historic_alarms SET alarm_id = 1", 1)
    assert result == {"error": "Invalid SQL"}
    assert db.calls == []


def test_execute_safe_query_returns_rows(monkeypatch):
    monkeypatch.setattr(query_executor, "is_safe_sql", lambda sql: True)
    monkeypatch.setattr(query_executor, "sanitize_sql", lambda sql, company_id: "SELECT 1 AS value")
    db = DummyDB()
    result = query_executor.execute_safe_query(db, "SELECT 1", 1)
    assert result == [{"value": 1.25}]
    assert "SET statement_timeout = '20s'" in db.calls[0]
    assert "SELECT 1 AS value" in db.calls[1]
    assert "RESET statement_timeout" in db.calls[-1]


def test_execute_safe_query_rolls_back_on_error(monkeypatch):
    monkeypatch.setattr(query_executor, "is_safe_sql", lambda sql: True)
    monkeypatch.setattr(query_executor, "sanitize_sql", lambda sql, company_id: "SELECT 1 AS value")

    class FailingDB(DummyDB):
        def execute(self, stmt):
            text = stmt.text if hasattr(stmt, "text") else str(stmt)
            self.calls.append(text)
            if text.startswith("SELECT"):
                raise RuntimeError("boom")
            return DummyResult([])

    db = FailingDB()
    result = query_executor.execute_safe_query(db, "SELECT 1", 1)
    assert "Query failed:" in result["error"]
    assert db.rolled_back is True
    assert "RESET statement_timeout" in db.calls[-1]
