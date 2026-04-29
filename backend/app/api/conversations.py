from datetime import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Conversation, Message
from ..schemas import (
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationResponse,
    MessageCreateRequest,
    MessageResponse,
)
from ..security import require_api_key
from ..services.query_executor import execute_safe_query
from ..services.response_generator import generate_response
from ..services.sql_generation_errors import build_sql_generation_user_error
from ..services.sql_generator import (
    generate_sql,
    SQLGenerationException,
)
from ..services.title_generator import generate_title

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_conversation_or_404(db: Session, conversation_id: int, company_id: int) -> Conversation:
    conversation = db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.company_id == company_id,
        )
    ).scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _get_recent_messages(db: Session, conversation_id: int, limit: int = 10) -> list[dict[str, str]]:
    # Most recent N messages, returned oldest->newest, for LLM context.
    messages = (
        db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    messages.reverse()
    payload: list[dict[str, str]] = []
    for message in messages:
        role = (message.role or "").strip()
        content = (message.content or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        payload.append({"role": role, "content": content})
    return payload


@router.get(
    "/api/conversations",
    response_model=list[ConversationResponse],
    dependencies=[Depends(require_api_key)],
)
def list_conversations(company_id: int, db: Session = Depends(get_db)):
    conversations = db.execute(
        select(Conversation)
        .where(Conversation.company_id == company_id)
        .order_by(Conversation.updated_at.desc())
    ).scalars().all()
    return [ConversationResponse.model_validate(c) for c in conversations]


@router.get(
    "/api/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
    dependencies=[Depends(require_api_key)],
)
def get_conversation(conversation_id: int, company_id: int, db: Session = Depends(get_db)):
    conversation = _get_conversation_or_404(db, conversation_id, company_id)
    messages = db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
    ).scalars().all()

    return ConversationDetailResponse(
        conversation=ConversationResponse.model_validate(conversation),
        messages=[MessageResponse.model_validate(m) for m in messages],
    )


@router.post(
    "/api/conversations",
    response_model=ConversationResponse,
    dependencies=[Depends(require_api_key)],
)
def create_conversation(payload: ConversationCreateRequest, db: Session = Depends(get_db)):
    conversation = Conversation(company_id=payload.company_id)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return ConversationResponse.model_validate(conversation)


@router.delete(
    "/api/conversations/{conversation_id}",
    dependencies=[Depends(require_api_key)],
)
def delete_conversation(conversation_id: int, company_id: int, db: Session = Depends(get_db)):
    conversation = _get_conversation_or_404(db, conversation_id, company_id)
    db.delete(conversation)
    db.commit()
    return {"status": "deleted"}


@router.post(
    "/api/conversations/{conversation_id}/messages",
    response_model=MessageResponse,
    dependencies=[Depends(require_api_key)],
)
def create_message(
    conversation_id: int,
    payload: MessageCreateRequest,
    company_id: int,
    db: Session = Depends(get_db),
):
    question = payload.content.strip()
    if not question:
        raise HTTPException(status_code=400, detail="content is required")

    conversation = _get_conversation_or_404(db, conversation_id, company_id)

    user_message = Message(conversation_id=conversation.id, role="user", content=question)
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    conversation_messages = _get_recent_messages(db, conversation.id, limit=10)

    try:
        sql = generate_sql(
            question=question,
            company_id=company_id,
            schema_context=None,
            conversation_messages=conversation_messages,
        )
    except SQLGenerationException as exc:
        user_error = build_sql_generation_user_error(exc.error_info)
        logger.error(
            "SQL generation unavailable (conversation) company_id=%s conversation_id=%s type=%s debug=%s question=%r",
            company_id,
            conversation_id,
            user_error["type"],
            exc.error_info.get("debug"),
            question,
        )
        print(
            f"[SQL_GENERATION_ERROR] conversation_id={conversation_id} company_id={company_id} "
            f"type={user_error['type']} debug={exc.error_info.get('debug')!r}"
        )
        response_text = user_error["error"]
        result_rows = []
        sql = None
    else:
        results = execute_safe_query(db, sql, company_id)
        result_rows = results if isinstance(results, list) else []
        response_text = generate_response(
            question=question,
            sql_results=result_rows,
            sql_query=sql,
            conversation_messages=conversation_messages,
        )

    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=response_text,
        sql_query=sql,
        query_results=result_rows,
    )
    db.add(assistant_message)

    if not conversation.title:
        try:
            conversation.title = generate_title(question)
        except Exception:
            conversation.title = question[:50]
    conversation.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(assistant_message)

    return MessageResponse.model_validate(assistant_message)
