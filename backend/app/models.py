from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    desc,
)
from sqlalchemy.orm import relationship

from .db import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True)
    title = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

    __table_args__ = (
        Index("index_conversations_on_company_id_and_updated_at", "company_id", "updated_at"),
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    role = Column(String, nullable=False)
    content = Column(Text)
    sql_query = Column(Text)
    query_results = Column(JSON, default=list)
    usage_meta = Column(JSON, nullable=True)  # Stores LLM usage/cost per message
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    conversation = relationship("Conversation", back_populates="messages")

    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="chk_messages_role"),
    )


class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(Integer, primary_key=True)
    question = Column(String)
    sql_query = Column(Text)
    company_id = Column(Integer)
    result_count = Column(Integer)
    execution_time = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ImportCursor(Base):
    __tablename__ = "import_cursors"

    id = Column(Integer, primary_key=True)
    source = Column(String, nullable=False)
    cursor_field = Column(String, nullable=False, default="alarm_id")
    last_alarm_id = Column(BigInteger)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("source", "cursor_field", name="uq_import_cursors_source_cursor"),
        Index("index_import_cursors_on_source", "source"),
    )


class HistoricAlarm(Base):
    __tablename__ = "historic_alarms"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(Integer, primary_key=True)

    alarm_id = Column(Integer)
    alarm_type_id = Column(Integer)
    area_id = Column(Integer)
    agent_id = Column(Integer)
    client_id = Column(Integer)
    billing_account_id = Column(Integer)
    responder_id = Column(Integer)
    triggered_zones_count = Column(Integer)

    alarm_allocation = Column(String)
    alarm_category = Column(String, default="home_alarm")
    alarm_signal = Column(String)
    alarm_type_description = Column(String)
    alarm_confirmed_saved_user = Column(String)
    alarm_canceled_user = Column(String)
    area_description = Column(String)
    agent_name = Column(String)
    client_description = Column(String)
    transmitter = Column(String)
    responder_name = Column(String)
    sqs_message_id = Column(String)

    alarm_conclusion_at = Column(DateTime(timezone=True))
    alarm_delegated_at = Column(DateTime(timezone=True))
    alarm_reopened_at = Column(DateTime(timezone=True))
    alarm_delegated = Column(Boolean, default=False)

    data = Column(JSON)
    sqs_message_attributes = Column(JSON)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, primary_key=True)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    mongodb_id = Column(String)
    video_url = Column(String)
    zones_description = Column(String)
    alarm_creation_at = Column(DateTime(timezone=True))
    imported_at = Column(DateTime(timezone=True))
    import_batch_id = Column(String)
    legacy_data = Column(JSON, default=dict)

    __table_args__ = (
        Index("index_historic_alarms_on_alarm_id", "alarm_id"),
        Index("index_historic_alarms_on_client_id", "client_id"),
        Index("index_historic_alarms_on_company_id", "company_id"),
        Index("idx_historic_alarms_company_alarm_creation", "company_id", desc("alarm_creation_at")),
        Index("idx_historic_alarms_company_mongo_created", "company_id", "mongodb_id", "created_at", unique=True),
        Index("historic_alarms_company_id_created_at_idx", "company_id", "created_at"),
        Index("idx_historic_alarms_company_time", "company_id", "created_at"),
        Index("index_historic_alarms_on_import_batch_id", "import_batch_id"),
        Index("historic_alarms_created_at_idx", "created_at"),
    )
