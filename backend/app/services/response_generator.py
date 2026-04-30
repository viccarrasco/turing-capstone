from langchain_core.messages import AIMessage

from ..config import settings
from .openai_client import get_chat_model


SYSTEM_PROMPT = """You are a helpful assistant that explains database query results in natural language.
Your task is to provide a clear, concise summary of the query results.

Guidelines:
- Use the same language as the user's question
- Be concise but informative
- Highlight key findings and numbers
- If there are many results, summarize the patterns
- Format numbers nicely (e.g., use thousands separators)
- Don't repeat the SQL query
- Don't mention technical details unless relevant
"""

_MAX_CONVERSATION_MESSAGES = 10
_MAX_MESSAGE_CHARS = 500

GERMAN_HINTS = {
    "der",
    "die",
    "das",
    "und",
    "oder",
    "nicht",
    "keine",
    "bitte",
    "wie",
    "was",
    "warum",
    "wieviele",
    "wieviel",
    "zeige",
    "gib",
}


def _looks_german(text: str | None) -> bool:
    if not text:
        return False
    if any(ch in text for ch in "äöüß"):
        return True
    padded = f" {text.lower()} "
    return any(f" {hint} " in padded for hint in GERMAN_HINTS)


def default_response(results: list, question: str | None = None) -> str:
    count = len(results) if results else 0
    german = _looks_german(question)
    if count == 0:
        return "Keine Ergebnisse gefunden." if german else "No results found."
    if count == 1:
        return "1 Ergebnis gefunden." if german else "1 result found."
    return f"{count} Ergebnisse gefunden." if german else f"{count} results found."


def format_results(results: list) -> str:
    if not results:
        return ""
    limited = results[:20]
    lines = []
    for row in limited:
        parts = [f"{k}: {v}" for k, v in row.items()]
        lines.append(", ".join(parts))
    return "\n".join(lines)


def _format_conversation_context(conversation_messages: list[dict[str, str]] | None) -> str:
    if not conversation_messages:
        return ""
    lines: list[str] = []
    for message in conversation_messages[-_MAX_CONVERSATION_MESSAGES:]:
        role = str(message.get("role") or "").strip().lower()
        content = str(message.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        content = " ".join(content.split())
        if len(content) > _MAX_MESSAGE_CHARS:
            content = content[:_MAX_MESSAGE_CHARS].rstrip() + "..."
        lines.append(f"{role}: {content}")
    if not lines:
        return ""
    return "Conversation context (most recent last):\n" + "\n".join(lines)


def generate_response(
    question: str,
    sql_results: list,
    sql_query: str,
    conversation_messages: list[dict[str, str]] | None = None,
) -> str:
    if not sql_results:
        return default_response(sql_results, question)

    try:
        conversation_text = _format_conversation_context(conversation_messages)
        prompt_parts = []
        if conversation_text:
            prompt_parts.append(conversation_text)
        prompt_parts.append(f"Latest user question:\n{question}")
        prompt_parts.append(
            "Final SQL query executed (for context only; do not show SQL back to the user):\n"
            f"{sql_query}"
        )
        prompt_parts.append(
            f"SQL Query Results ({len(sql_results)} rows):\n{format_results(sql_results)}"
        )
        prompt_parts.append(
            "Task:\n"
            "- Provide a natural-language summary of the SQL results.\n"
            "- Use the conversation context only to resolve references; base factual statements only on the SQL results.\n"
        )

        chat = get_chat_model(
            settings.openai_chat_model,
            temperature=0.3,
            max_tokens=500,
        )
        ai_message: AIMessage = chat.invoke([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(prompt_parts)},
        ])
        content = ai_message.content if isinstance(ai_message.content, str) else ""
        return content.strip() or default_response(sql_results, question)
    except Exception:
        return default_response(sql_results, question)
