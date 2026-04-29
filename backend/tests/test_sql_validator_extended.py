from app.services.sql_validator import is_safe_sql, sanitize_sql


def test_is_safe_sql_rejects_comment_marker():
    assert not is_safe_sql("SELECT * FROM historic_alarms -- comment")


def test_sanitize_sql_inserts_before_order_by():
    sql = "SELECT * FROM historic_alarms ORDER BY alarm_creation_at DESC"
    out = sanitize_sql(sql, 7)
    assert "WHERE company_id = 7" in out
    assert out.index("WHERE company_id = 7") < out.index("ORDER BY")


def test_sanitize_sql_inserts_before_limit():
    sql = "SELECT * FROM historic_alarms LIMIT 10"
    out = sanitize_sql(sql, 9)
    assert "WHERE company_id = 9" in out
    assert out.index("WHERE company_id = 9") < out.index("LIMIT")


def test_sanitize_sql_injects_into_where_segment():
    sql = "SELECT * FROM historic_alarms WHERE alarm_id = 1 ORDER BY alarm_creation_at DESC"
    out = sanitize_sql(sql, 3)
    assert "WHERE company_id = 3 AND alarm_id = 1" in out


def test_sanitize_sql_does_not_duplicate_company_id():
    sql = "SELECT * FROM historic_alarms WHERE company_id = 2 AND alarm_id = 1"
    out = sanitize_sql(sql, 3)
    assert "company_id = 3" not in out
