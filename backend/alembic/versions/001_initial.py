"""initial schema

Revision ID: 001
Revises:
Create Date: 2025-06-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("company", sa.String, nullable=False),
        sa.Column("quarter", sa.String(20)),
        sa.Column("report_date", sa.Date),
        sa.Column("transcript_source", sa.String),
        sa.Column("raw_transcript", sa.Text),
        sa.Column("report_json", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_reports_ticker", "reports", ["ticker"])
    op.create_unique_constraint("uq_reports_ticker_quarter", "reports", ["ticker", "quarter"])

    op.create_table(
        "watchlist",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("added_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_watchlist_ticker", "watchlist", ["ticker"])

    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String, nullable=False),
        sa.Column("tickers", postgresql.ARRAY(sa.String)),
        sa.Column("schedule", sa.String),
        sa.Column("format", sa.String),
        sa.Column("active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_subscriptions_email", "subscriptions", ["email"])

    op.create_table(
        "qa_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("history", postgresql.JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_qa_sessions_ticker", "qa_sessions", ["ticker"])


def downgrade() -> None:
    op.drop_table("qa_sessions")
    op.drop_table("subscriptions")
    op.drop_table("watchlist")
    op.drop_table("reports")
