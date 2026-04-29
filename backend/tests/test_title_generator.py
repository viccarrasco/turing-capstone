import app.services.title_generator as title_generator


def test_generate_title_short_question_returns_original():
    question = "Short question"
    assert title_generator.generate_title(question) == question


def test_generate_title_long_question_uses_model(monkeypatch):
    class DummyResponse:
        def __init__(self):
            self.choices = [type("Choice", (), {"message": type("Msg", (), {"content": "Alert summary"})()})()]

    class DummyChat:
        class completions:
            @staticmethod
            def create(**kwargs):
                return DummyResponse()

    class DummyClient:
        chat = DummyChat()

    monkeypatch.setattr(title_generator, "get_client", lambda: DummyClient())
    monkeypatch.setattr(title_generator.settings, "openai_chat_model", "test-model", raising=False)

    question = "x" * (title_generator.MAX_TITLE_LENGTH + 10)
    out = title_generator.generate_title(question)
    assert out == "Alert summary"
