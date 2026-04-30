import logging
from typing import Any

from langchain_openai import ChatOpenAI

from ..config import settings


_chat_model_cache: dict[tuple[Any, ...], ChatOpenAI] = {}
logger = logging.getLogger(__name__)


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
    the environment.
    """
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
