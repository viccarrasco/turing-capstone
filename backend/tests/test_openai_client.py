import os

import app.services.openai_client as openai_client


def test_get_client_singleton(monkeypatch):
    openai_client._client = None

    class DummyClient:
        def __init__(self, api_key):
            self.api_key = api_key

    monkeypatch.setattr(openai_client, "OpenAI", DummyClient)
    monkeypatch.setattr(openai_client.settings, "openai_api_key", "test-key", raising=False)
    monkeypatch.setattr(openai_client.settings, "langsmith_tracing", False, raising=False)

    client_a = openai_client.get_client()
    client_b = openai_client.get_client()

    assert client_a is client_b
    assert client_a.api_key == "test-key"


def test_get_client_wraps_with_langsmith(monkeypatch):
    openai_client._client = None
    openai_client._langsmith_configured = False

    class DummyClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.wrapped = False

    def wrap(client):
        client.wrapped = True
        return client

    monkeypatch.setattr(openai_client, "OpenAI", DummyClient)
    monkeypatch.setattr(openai_client, "wrap_openai", wrap)
    monkeypatch.setattr(openai_client.settings, "openai_api_key", "test-key", raising=False)
    monkeypatch.setattr(openai_client.settings, "langsmith_tracing", True, raising=False)
    monkeypatch.setattr(openai_client.settings, "langsmith_api_key", "ls-key", raising=False)
    monkeypatch.setattr(openai_client.settings, "langsmith_project", "proj", raising=False)
    monkeypatch.setattr(openai_client.settings, "langsmith_endpoint", "", raising=False)

    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.delenv("LANGCHAIN_PROJECT", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)

    client = openai_client.get_client()

    assert client.wrapped is True
    assert os.environ.get("LANGSMITH_API_KEY") == "ls-key"
    assert os.environ.get("LANGCHAIN_API_KEY") == "ls-key"
    assert os.environ.get("LANGSMITH_PROJECT") == "proj"
    assert os.environ.get("LANGCHAIN_PROJECT") == "proj"
    assert os.environ.get("LANGSMITH_TRACING") == "true"
    assert os.environ.get("LANGCHAIN_TRACING_V2") == "true"
