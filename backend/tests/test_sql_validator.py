from app.services.sql_validator import is_safe_sql, sanitize_sql


def test_is_safe_sql_allows_select():
    assert is_safe_sql("SELECT * FROM historic_alarms")


def test_is_safe_sql_blocks_update():
    assert not is_safe_sql("UPDATE historic_alarms SET alarm_id = 1")


def test_sanitize_sql_adds_company_id():
    sql = "SELECT * FROM historic_alarms"
    out = sanitize_sql(sql, 12)
    assert "company_id = 12" in out


def test_sanitize_sql_injects_into_where():
    sql = "SELECT * FROM historic_alarms WHERE alarm_id = 1"
    out = sanitize_sql(sql, 33)
    assert "company_id = 33" in out
