from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# DEPRECATED: Used only by the legacy /api/chat/query endpoint.
# Kept for backward compatibility reference; safe to remove in a future cleanup.
# unused: no active callers
class ChatQueryRequest(BaseModel):
    question: str
    company_id: int


# DEPRECATED: Used only by the legacy /api/chat/query endpoint.
# Kept for backward compatibility reference; safe to remove in a future cleanup.
# unused: no active callers
class ChatQueryResponse(BaseModel):
    success: bool
    results: Any
    sql: str
    execution_time: float
    response_type: str = "table_records"
    summary: Optional[str] = None


class V1QueryRequest(BaseModel):
    question: str


class V1QueryError(BaseModel):
    type: str
    message: str


class V1LLMCallUsage(BaseModel):
    stage: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0


class V1UsageTotals(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_llm_time_ms: int = 0
    total_db_time_ms: int = 0
    total_cost_usd: float = 0.0


class V1UsageMeta(BaseModel):
    llm_calls: list[V1LLMCallUsage] = Field(default_factory=list)
    totals: V1UsageTotals = Field(default_factory=V1UsageTotals)


class V1QueryMeta(BaseModel):
    route: str = "custom_query"
    generated_sql: str = ""
    response_type: str = "plain_text"
    reasoning_steps: list[str] = Field(default_factory=list)
    usage: V1UsageMeta = Field(default_factory=V1UsageMeta)
    cached: bool = False


class V1QueryResponse(BaseModel):
    answer: Optional[str] = None
    chart_data: Optional[dict[str, Any]] = None
    table_records: Optional[list[dict[str, Any]]] = None
    csv_inline: Optional[str] = None
    error: Optional[V1QueryError] = None
    meta: V1QueryMeta


class ConversationCreateRequest(BaseModel):
    company_id: int


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    title: Optional[str]
    created_at: datetime
    updated_at: datetime


class MessageCreateRequest(BaseModel):
    content: str


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: Optional[str]
    sql_query: Optional[str]
    query_results: Any = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ConversationDetailResponse(BaseModel):
    conversation: ConversationResponse
    messages: List[MessageResponse]
