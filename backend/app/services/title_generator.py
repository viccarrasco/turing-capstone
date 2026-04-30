from langchain_core.messages import AIMessage

from ..config import settings
from .openai_client import get_chat_model


MAX_TITLE_LENGTH = 50


def truncate_title(text: str) -> str:
    if len(text) <= MAX_TITLE_LENGTH:
        return text
    return text[:MAX_TITLE_LENGTH]


def generate_title(question: str) -> str:
    if len(question) <= MAX_TITLE_LENGTH:
        return truncate_title(question)

    try:
        chat = get_chat_model(settings.openai_chat_model, temperature=0, max_tokens=30)
        ai_message: AIMessage = chat.invoke([
            {
                "role": "system",
                "content": f"Generate a very short title (max {MAX_TITLE_LENGTH} characters) that summarizes the user's question. Output only the title, nothing else. Use the same language as the question.",
            },
            {"role": "user", "content": question},
        ])
        content = ai_message.content if isinstance(ai_message.content, str) else ""
        content = content.strip()
        return truncate_title(content) if content else truncate_title(question)
    except Exception:
        return truncate_title(question)
