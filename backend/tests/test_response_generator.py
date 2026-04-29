from app.services.response_generator import default_response, generate_response


def test_default_response_english_no_results():
    assert default_response([], question="Show alarms") == "No results found."


def test_default_response_german_no_results():
    assert default_response([], question="Bitte zeige Alarme") == "Keine Ergebnisse gefunden."


def test_generate_response_empty_results_uses_default_language():
    out = generate_response(question="Show alarms", sql_results=[], sql_query="SELECT 1")
    assert out == "No results found."


def test_generate_response_includes_conversation_context_and_final_sql(monkeypatch):
    import app.services.response_generator as response_generator

    class DummyResponse:
        def __init__(self, content: str):
            class _Msg:
                def __init__(self, content: str):
                    self.content = content

            class _Choice:
                def __init__(self, content: str):
                    self.message = _Msg(content)

            self.choices = [_Choice(content)]

    class DummyCompletions:
        def __init__(self):
            self.last_kwargs = None

        def create(self, **kwargs):
            self.last_kwargs = kwargs
            return DummyResponse("summary")

    class DummyChat:
        def __init__(self):
            self.completions = DummyCompletions()

    class DummyClient:
        def __init__(self):
            self.chat = DummyChat()

    dummy = DummyClient()

    monkeypatch.setattr(response_generator, "get_client", lambda: dummy)
    monkeypatch.setattr(response_generator.settings, "openai_chat_model", "test-model", raising=False)

    out = generate_response(
        question="What about those alarms?",
        sql_results=[{"alarm_id": 1, "client_description": "ACME"}],
        sql_query="SELECT alarm_id FROM historic_alarms WHERE company_id = 1 LIMIT 100",
        conversation_messages=[
            {"role": "user", "content": "Show me recent alarms"},
            {"role": "assistant", "content": "Sure, running a query."},
        ],
    )

    assert out == "summary"
    kwargs = dummy.chat.completions.last_kwargs
    assert kwargs["model"] == "test-model"
    assert len(kwargs["messages"]) == 2
    user_prompt = kwargs["messages"][1]["content"]
    assert "Conversation context" in user_prompt
    assert "user: Show me recent alarms" in user_prompt
    assert "assistant: Sure, running a query." in user_prompt
    assert "Latest user question" in user_prompt
    assert "Final SQL query executed" in user_prompt
