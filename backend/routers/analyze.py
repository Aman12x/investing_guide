import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from exceptions import ClaudeError, TranscriptNotFoundError
from models import Report
from services.analyst import generate_report
from services.signals.aggregator import fetch_external_context
from services.transcript import fetch_transcript

router = APIRouter()
logger = logging.getLogger(__name__)

_CACHE_TTL_HOURS = 24


async def _get_cached(ticker: str, db: AsyncSession) -> Report | None:
    cutoff = datetime.utcnow() - timedelta(hours=_CACHE_TTL_HOURS)
    stmt = (
        select(Report)
        .where(Report.ticker == ticker, Report.created_at >= cutoff)
        .order_by(Report.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


@router.post("/analyze/{ticker}")
async def analyze_ticker(ticker: str, db: AsyncSession = Depends(get_db)):
    ticker = ticker.upper().strip()

    cached = await _get_cached(ticker, db)
    if cached:
        logger.info("Cache hit for %s", ticker)
        return cached.report_json

    try:
        transcript_result = await fetch_transcript(ticker)
    except TranscriptNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": f"No earnings transcript found for {ticker}", "code": "TRANSCRIPT_NOT_FOUND"},
        )

    external = await fetch_external_context(ticker)

    try:
        report = await generate_report(transcript_result.text, ticker, external)
    except ClaudeError as exc:
        logger.error("Claude report generation failed for %s: %s", ticker, exc)
        raise HTTPException(
            status_code=502,
            detail={"error": "Report generation failed", "code": "CLAUDE_ERROR"},
        )

    db_report = Report(
        ticker=ticker,
        company=report.company,
        quarter=report.quarter,
        report_date=transcript_result.report_date,
        transcript_source=transcript_result.source,
        raw_transcript=transcript_result.text,
        report_json=report.model_dump(),
    )
    db.add(db_report)
    await db.commit()

    return report.model_dump()


@router.get("/analyze/{ticker}/latest")
async def get_latest_report(ticker: str, db: AsyncSession = Depends(get_db)):
    ticker = ticker.upper().strip()
    cached = await _get_cached(ticker, db)
    if not cached:
        raise HTTPException(
            status_code=404,
            detail={"error": f"No recent report for {ticker}", "code": "REPORT_NOT_FOUND"},
        )
    return cached.report_json
