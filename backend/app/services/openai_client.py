import logging
import os
from typing import Any

from langchain_openai import ChatOpenAI
from openai import OpenAI

try:
    from langsmith.wrappers import wrap_openai
except Exception:  # pragma: no cover - optional dependency
    wrap_openai = None

from ..config import settings


_client = None
_langsmith_configured = False
_chat_model_cache: dict[tuple[Any, ...], ChatOpenAI] = {}
logger = logging.getLogger(__name__)


def _configure_langsmith_env():
    global _langsmith_configured
    if _langsmith_configured or not settings.langsmith_tracing:
        return
    if settings.langsmith_api_key:
        os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
        os.environ.setdefault("LANGCHAIN_API_KEY", settings.langsmith_api_key)
    if settings.langsmith_project:
        os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
        os.environ.setdefault("LANGCHAIN_PROJECT", settings.langsmith_project)
    if settings.langsmith_endpoint:
        os.environ.setdefault("LANGSMITH_ENDPOINT", settings.langsmith_endpoint)
        os.environ.setdefault("LANGCHAIN_ENDPOINT", settings.langsmith_endpoint)
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    _langsmith_configured = True
    logger.info(
        "LangSmith tracing enabled (project=%r endpoint=%r).",
        settings.langsmith_project or os.environ.get("LANGSMITH_PROJECT", ""),
        settings.langsmith_endpoint or os.environ.get("LANGSMITH_ENDPOINT", ""),
    )


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
        if settings.langsmith_tracing:
            if not wrap_openai:
                logger.warning(
                    "LangSmith tracing is enabled, but langsmith.wrap_openai is unavailable; OpenAI calls will not be traced."
                )
            else:
                try:
                    _configure_langsmith_env()
                    _client = wrap_openai(_client)
                    logger.info("OpenAI client wrapped with LangSmith tracing.")
                except Exception:
                    logger.exception(
                        "Failed to wrap OpenAI client for LangSmith tracing; OpenAI calls will not be traced."
                    )
    return _client


def get_chat_model(
    model: str,
    *,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    timeout: float | None = None,
    max_retries: int = 0,
) -> ChatOpenAI:
    """Return a cached ``ChatOpenAI`` instance configured for our defaults.

    LangSmith tracing is automatic when ``LANGSMITH_TRACING=true`` is set in
    the environment; we ensure that here on first use.
    """
    if settings.langsmith_tracing:
        _configure_langsmith_env()

    cache_key = (model, temperature, max_tokens, timeout, max_retries)
    cached = _chat_model_cache.get(cache_key)
    if cached is not None:
        return cached

    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "api_key": settings.openai_api_key,
        # We keep our own retry loop in sql_generator; default ChatOpenAI to 0
        # so it does not double-retry on top of ours.
        "max_retries": max_retries,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if timeout is not None:
        kwargs["timeout"] = timeout

    instance = ChatOpenAI(**kwargs)
    _chat_model_cache[cache_key] = instance
    return instance
