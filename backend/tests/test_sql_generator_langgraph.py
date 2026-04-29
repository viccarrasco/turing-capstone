import app.services.sql_generator as sql_generator
import app.services.tools as agent_tools
from app.config import settings


def _configure_models(monkeypatch):
    monkeypatch.setattr(settings, "openai_sql_model_a", "model_a", raising=False)
    monkeypatch.setattr(settings, "openai_sql_model_b", "model_b", raising=False)
    monkeypatch.setattr(settings, "openai_sql_refiner_model", "model_refiner", raising=False)


def test_langgraph_prefers_valid_candidate_and_postprocesses(monkeypatch):
    sql_generator._graph = None
    _configure_models(monkeypatch)

    calls = []

    def fake_generate(model: str, prompt: str):
        calls.append(model)
        if model == "model_a":
            return (
                "SELECT alarm_id, alarm_creation_at "
                "FROM historic_alarms ORDER BY alarm_creation_at DESC"
            )
        if model == "model_b":
            return "SELECT data->>'foo' FROM historic_alarms"
        if model == "model_refiner":
            raise AssertionError("Refiner should not be called")
        return None

    monkeypatch.setattr(sql_generator, "_generate_with_model", fake_generate)

    sql = sql_generator.generate_sql_with_langgraph("recent alarms", 42, None)

    assert sql.upper().startswith("SELECT")
    assert "company_id = 42" in sql
    assert "LIMIT 100" in sql
    assert "data->" not in sql
    assert "model_refiner" not in calls


def test_langgraph_includes_conversation_context_in_prompt(monkeypatch):
    sql_generator._graph = None
    _configure_models(monkeypatch)

    prompts = []

    def fake_generate(model: str, prompt: str):
        prompts.append(prompt)
        if model in {"model_a", "model_b"}:
            return "SELECT alarm_id, alarm_creation_at FROM historic_alarms"
        if model == "model_refiner":
            raise AssertionError("Refiner should not be called")
        return None

    monkeypatch.setattr(sql_generator, "_generate_with_model", fake_generate)

    sql = sql_generator.generate_sql_with_langgraph(
        "recent alarms",
        42,
        None,
        conversation_messages=[
            {"role": "user", "content": "Earlier I asked about ACME"},
            {"role": "assistant", "content": "Ok"},
        ],
    )

    assert sql.upper().startswith("SELECT")
    assert any("Conversation context" in prompt for prompt in prompts)


def test_langgraph_repairs_when_refiner_output_invalid(monkeypatch):
    sql_generator._graph = None
    _configure_models(monkeypatch)

    calls = []
    refiner_outputs = iter(
        [
            "SELECT data->>'bar' FROM historic_alarms",
            "SELECT alarm_id FROM historic_alarms",
        ]
    )

    def fake_generate(model: str, prompt: str):
        calls.append(model)
        if model == "model_a":
            return "UPDATE historic_alarms SET alarm_id = 1"
        if model == "model_b":
            return "SELECT data->>'foo' FROM historic_alarms"
        if model == "model_refiner":
            return next(refiner_outputs)
        return None

    monkeypatch.setattr(sql_generator, "_generate_with_model", fake_generate)

    sql = sql_generator.generate_sql_with_langgraph("recent alarms", 55, None)

    assert sql.upper().startswith("SELECT")
    assert "company_id = 55" in sql
    assert "data->" not in sql
    assert "LIMIT 100" in sql
    assert calls.count("model_refiner") == 2


def test_langgraph_does_not_add_limit_for_aggregates(monkeypatch):
    sql_generator._graph = None
    _configure_models(monkeypatch)

    def fake_generate(model: str, prompt: str):
        if model in {"model_a", "model_b"}:
            return "SELECT COUNT(*) FROM historic_alarms"
        if model == "model_refiner":
            raise AssertionError("Refiner should not be called")
        return None

    monkeypatch.setattr(sql_generator, "_generate_with_model", fake_generate)

    sql = sql_generator.generate_sql_with_langgraph("count alarms", 5, None)

    assert sql.upper().startswith("SELECT")
    assert "company_id = 5" in sql
    assert "LIMIT 100" not in sql


def test_query_pipeline_returns_table_records_with_summary(monkeypatch):
    sql_generator._query_graph = None

    rows = [{"responder_name": "Alex", "alarm_count": 9}]

    monkeypatch.setattr(
        sql_generator,
        "generate_sql_with_langgraph",
        lambda question, company_id, schema_context: "SELECT responder_name, COUNT(*) AS alarm_count FROM historic_alarms",
    )
    monkeypatch.setattr(agent_tools, "execute_safe_query", lambda db, sql, company_id: rows)
    monkeypatch.setattr(
        sql_generator,
        "_summarize_results_with_model",
        lambda question, sql, rows: {
            "response_type": "table_records",
            "summary": "Alex handled the most alarms.",
            "graph_json": None,
        },
    )

    result = sql_generator.generate_query_result_with_langgraph(
        db=object(),
        question="Top responders",
        company_id=77,
        schema_context=None,
    )

    assert result["success"] is True
    assert result["response_type"] == "table_records"
    assert result["results"] == rows
    assert result["summary"] == "Alex handled the most alarms."
    assert result["row_count"] == 1
    assert result["meta"]["route"] == "custom_query"
    assert result["meta"]["generated_sql"].startswith("SELECT")
    assert "generate_sql" in result["meta"]["reasoning_steps"]
    assert "execute_sql" in result["meta"]["reasoning_steps"]
    assert "summarize_results" in result["meta"]["reasoning_steps"]
    assert result["meta"]["usage"]["totals"]["total_db_time_ms"] >= 0


def test_query_pipeline_can_return_graph_json(monkeypatch):
    sql_generator._query_graph = None

    monkeypatch.setattr(
        sql_generator,
        "generate_sql_with_langgraph",
        lambda question, company_id, schema_context: "SELECT DATE(alarm_creation_at) AS day, COUNT(*) AS alarms FROM historic_alarms",
    )
    monkeypatch.setattr(
        agent_tools,
        "execute_safe_query",
        lambda db, sql, company_id: [
            {"day": "2026-04-18", "alarms": 12},
            {"day": "2026-04-19", "alarms": 18},
        ],
    )
    monkeypatch.setattr(
        sql_generator,
        "_summarize_results_with_model",
        lambda question, sql, rows: {
            "response_type": "graph_json",
            "summary": "Alarm volume increased day over day.",
            "graph_json": {
                "chart_type": "line",
                "x_key": "day",
                "y_key": "alarms",
                "series": rows,
            },
        },
    )

    result = sql_generator.generate_query_result_with_langgraph(
        db=object(),
        question="Trend by day",
        company_id=77,
        schema_context=None,
    )

    assert result["success"] is True
    assert result["response_type"] == "graph_json"
    assert result["results"]["chart_type"] == "line"
    assert result["summary"] == "Alarm volume increased day over day."
    assert result["row_count"] == 2
    assert result["meta"]["response_type"] == "graph_json"


def test_query_pipeline_returns_plain_text_on_execution_error(monkeypatch):
    sql_generator._query_graph = None

    monkeypatch.setattr(
        sql_generator,
        "generate_sql_with_langgraph",
        lambda question, company_id, schema_context: "SELECT * FROM historic_alarms",
    )
    monkeypatch.setattr(
        agent_tools,
        "execute_safe_query",
        lambda db, sql, company_id: {"error": "Query failed: boom"},
    )

    result = sql_generator.generate_query_result_with_langgraph(
        db=object(),
        question="Show alarms",
        company_id=77,
        schema_context=None,
    )

    assert result["success"] is False
    assert result["response_type"] == "plain_text"
    assert "Query failed: boom" in result["results"]
    assert result["row_count"] == 0
    assert result["meta"]["route"] == "error"


def test_query_pipeline_returns_csv_when_rows_exceed_threshold(monkeypatch):
    sql_generator._query_graph = None

    rows = [{"alarm_id": idx, "client_description": f"Client {idx}"} for idx in range(1, 12)]

    monkeypatch.setattr(
        sql_generator,
        "generate_sql_with_langgraph",
        lambda question, company_id, schema_context: "SELECT alarm_id, client_description FROM historic_alarms",
    )
    monkeypatch.setattr(agent_tools, "execute_safe_query", lambda db, sql, company_id: rows)
    monkeypatch.setattr(
        sql_generator,
        "_summarize_results_with_model",
        lambda question, sql, rows: (_ for _ in ()).throw(AssertionError("Summarizer should not be called for CSV path")),
    )

    result = sql_generator.generate_query_result_with_langgraph(
        db=object(),
        question="Show many rows",
        company_id=77,
        schema_context=None,
    )

    assert result["success"] is True
    assert result["response_type"] == "csv"
    assert result["row_count"] == 11
    assert isinstance(result["results"], str)
    assert "alarm_id,client_description" in result["results"]
    assert result["meta"]["response_type"] == "csv"
