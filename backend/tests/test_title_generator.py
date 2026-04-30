import app.services.title_generator as title_generator


def test_generate_title_short_question_returns_original():
    question = "Short question"
    assert title_generator.generate_title(question) == question


def test_generate_title_long_question_uses_model(monkeypatch):
    class DummyAIMessage:
        def __init__(self, content: str):
            self.content = content

    class DummyChat:
        def invoke(self, messages):
            return DummyAIMessage("Alert summary")

    monkeypatch.setattr(title_generator, "get_chat_model", lambda *args, **kwargs: DummyChat())
    monkeypatch.setattr(title_generator.settings, "openai_chat_model", "test-model", raising=False)

    question = "x" * (title_generator.MAX_TITLE_LENGTH + 10)
    out = title_generator.generate_title(question)
    assert out == "Alert summary"
