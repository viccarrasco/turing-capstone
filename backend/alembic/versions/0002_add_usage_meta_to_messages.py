"""add usage_meta to messages

Revision ID: 0002_add_usage_meta_to_messages
Revises: 0001_init_schema
Create Date: 2026-04-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_add_usage_meta_to_messages"
down_revision = "0001_init_schema"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("messages", sa.Column("usage_meta", sa.JSON(), nullable=True))

def downgrade() -> None:
    op.drop_column("messages", "usage_meta")
