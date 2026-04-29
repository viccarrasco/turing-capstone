"""initial schema

Revision ID: 0001_init_schema
Revises: 
Create Date: 2026-04-13
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_init_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("index_conversations_on_company_id", "conversations", ["company_id"])
    op.create_index(
        "index_conversations_on_company_id_and_updated_at",
        "conversations",
        ["company_id", "updated_at"],
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column("sql_query", sa.Text()),
        sa.Column("query_results", sa.JSON(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
    )
    op.create_index("index_messages_on_conversation_id", "messages", ["conversation_id"])

    op.create_table(
        "query_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("question", sa.String()),
        sa.Column("sql_query", sa.Text()),
        sa.Column("company_id", sa.Integer()),
        sa.Column("result_count", sa.Integer()),
        sa.Column("execution_time", sa.Float()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "import_cursors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("cursor_field", sa.String(), nullable=False, server_default="alarm_id"),
        sa.Column("last_alarm_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("index_import_cursors_on_source", "import_cursors", ["source"])
    op.create_unique_constraint(
        "uq_import_cursors_source_cursor",
        "import_cursors",
        ["source", "cursor_field"],
    )

    op.create_table(
        "historic_alarms",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("alarm_id", sa.Integer()),
        sa.Column("alarm_type_id", sa.Integer()),
        sa.Column("area_id", sa.Integer()),
        sa.Column("agent_id", sa.Integer()),
        sa.Column("client_id", sa.Integer()),
        sa.Column("billing_account_id", sa.Integer()),
        sa.Column("responder_id", sa.Integer()),
        sa.Column("triggered_zones_count", sa.Integer()),
        sa.Column("alarm_allocation", sa.String()),
        sa.Column("alarm_category", sa.String(), server_default=sa.text("'home_alarm'")),
        sa.Column("alarm_signal", sa.String()),
        sa.Column("alarm_type_description", sa.String()),
        sa.Column("alarm_confirmed_saved_user", sa.String()),
        sa.Column("alarm_canceled_user", sa.String()),
        sa.Column("area_description", sa.String()),
        sa.Column("agent_name", sa.String()),
        sa.Column("client_description", sa.String()),
        sa.Column("transmitter", sa.String()),
        sa.Column("responder_name", sa.String()),
        sa.Column("sqs_message_id", sa.String()),
        sa.Column("alarm_conclusion_at", sa.DateTime(timezone=True)),
        sa.Column("alarm_delegated_at", sa.DateTime(timezone=True)),
        sa.Column("alarm_reopened_at", sa.DateTime(timezone=True)),
        sa.Column("alarm_delegated", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("data", sa.JSON()),
        sa.Column("sqs_message_attributes", sa.JSON()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("mongodb_id", sa.String()),
        sa.Column("video_url", sa.String()),
        sa.Column("zones_description", sa.String()),
        sa.Column("alarm_creation_at", sa.DateTime(timezone=True)),
        sa.Column("imported_at", sa.DateTime(timezone=True)),
        sa.Column("import_batch_id", sa.String()),
        sa.Column("legacy_data", sa.JSON(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.PrimaryKeyConstraint("id", "company_id", "created_at", name="historic_alarms_pkey"),
    )

    op.execute(
        "SELECT create_hypertable('historic_alarms', 'created_at', partitioning_column => 'company_id', number_partitions => 8, chunk_time_interval => INTERVAL '1 month', if_not_exists => TRUE);"
    )
    op.execute("SELECT add_retention_policy('historic_alarms', INTERVAL '180 days', if_not_exists => TRUE);")

    op.create_index("index_historic_alarms_on_alarm_id", "historic_alarms", ["alarm_id"])
    op.create_index("index_historic_alarms_on_client_id", "historic_alarms", ["client_id"])
    op.create_index("index_historic_alarms_on_company_id", "historic_alarms", ["company_id"])
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_historic_alarms_company_alarm_creation ON historic_alarms (company_id, alarm_creation_at DESC);"
    )
    op.create_index(
        "idx_historic_alarms_company_mongo_created",
        "historic_alarms",
        ["company_id", "mongodb_id", "created_at"],
        unique=True,
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS historic_alarms_company_id_created_at_idx "
        "ON historic_alarms (company_id, created_at);"
    )
    op.create_index("idx_historic_alarms_company_time", "historic_alarms", ["company_id", "created_at"])
    op.create_index("index_historic_alarms_on_import_batch_id", "historic_alarms", ["import_batch_id"])
    # Timescale may create this default time index automatically; keep migration idempotent.
    op.execute(
        "CREATE INDEX IF NOT EXISTS historic_alarms_created_at_idx "
        "ON historic_alarms (created_at)"
    )


def downgrade() -> None:
    op.drop_index("historic_alarms_created_at_idx", table_name="historic_alarms")
    op.drop_index("index_historic_alarms_on_import_batch_id", table_name="historic_alarms")
    op.drop_index("idx_historic_alarms_company_time", table_name="historic_alarms")
    op.execute("DROP INDEX IF EXISTS historic_alarms_company_id_created_at_idx")
    op.drop_index("idx_historic_alarms_company_mongo_created", table_name="historic_alarms")
    op.drop_index("idx_historic_alarms_company_alarm_creation", table_name="historic_alarms")
    op.drop_index("index_historic_alarms_on_company_id", table_name="historic_alarms")
    op.drop_index("index_historic_alarms_on_client_id", table_name="historic_alarms")
    op.drop_index("index_historic_alarms_on_alarm_id", table_name="historic_alarms")
    op.drop_table("historic_alarms")

    op.drop_constraint("uq_import_cursors_source_cursor", "import_cursors", type_="unique")
    op.drop_index("index_import_cursors_on_source", table_name="import_cursors")
    op.drop_table("import_cursors")

    op.drop_table("query_logs")

    op.drop_index("index_messages_on_conversation_id", table_name="messages")
    op.drop_table("messages")

    op.drop_index("index_conversations_on_company_id_and_updated_at", table_name="conversations")
    op.drop_index("index_conversations_on_company_id", table_name="conversations")
    op.drop_table("conversations")
