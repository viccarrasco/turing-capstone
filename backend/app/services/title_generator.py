from ..config import settings
from .openai_client import get_client


MAX_TITLE_LENGTH = 50


def truncate_title(text: str) -> str:
    if len(text) <= MAX_TITLE_LENGTH:
        return text
    return text[:MAX_TITLE_LENGTH]


def generate_title(question: str) -> str:
    if len(question) <= MAX_TITLE_LENGTH:
        return truncate_title(question)

    client = get_client()
    response = client.chat.completions.create(
        model=settings.openai_chat_model,
        temperature=0,
        max_tokens=30,
        messages=[
            {
                "role": "system",
                "content": f"Generate a very short title (max {MAX_TITLE_LENGTH} characters) that summarizes the user's question. Output only the title, nothing else. Use the same language as the question.",
            },
            {"role": "user", "content": question},
        ],
    )
    content = response.choices[0].message.content if response.choices else ""
    content = content.strip()
    return truncate_title(content) if content else truncate_title(question)
