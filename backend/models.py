from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import mapped_column

from database import Base


def _utcnow() -> datetime:
    return datetime.utcnow()


class Report(Base):
    __tablename__ = "reports"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    ticker = mapped_column(String(10), nullable=False, index=True)
    company = mapped_column(String, nullable=False)
    quarter = mapped_column(String(20))
    report_date = mapped_column(Date)
    transcript_source = mapped_column(String)
    raw_transcript = mapped_column(Text)  # never returned to frontend
    report_json = mapped_column(JSONB, nullable=False)
    created_at = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("ticker", "quarter", name="uq_reports_ticker_quarter"),)


class Watchlist(Base):
    __tablename__ = "watchlist"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    ticker = mapped_column(String(10), nullable=False, unique=True)
    added_at = mapped_column(DateTime, default=_utcnow)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = mapped_column(String, nullable=False, unique=True)
    tickers = mapped_column(ARRAY(String))
    schedule = mapped_column(String)   # "earnings_day" | "daily" | "weekly"
    format = mapped_column(String)     # "summary" | "full" | "bullets"
    active = mapped_column(Boolean, default=True)
    created_at = mapped_column(DateTime, default=_utcnow)


class QASession(Base):
    __tablename__ = "qa_sessions"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    ticker = mapped_column(String(10), nullable=False, index=True)
    history = mapped_column(JSONB, default=list)
    created_at = mapped_column(DateTime, default=_utcnow)
    updated_at = mapped_column(DateTime, default=_utcnow)
