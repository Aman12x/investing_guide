import logging
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agent.graph import agent
from agent.nodes.formatter import FormatterError
from agent.state import AgentState
from database import get_db
from models import Report

router = APIRouter()
logger = logging.getLogger(__name__)

_CACHE_TTL_HOURS = 24
_TICKER_RE = re.compile(r"^[A-Z0-9.]{1,10}$")


def _validate_ticker(ticker: str) -> str:
    t = ticker.upper().strip()
    if not _TICKER_RE.match(t):
        raise HTTPException(
            status_code=422,
            detail={"error": "Invalid ticker symbol", "code": "INVALID_TICKER"},
        )
    return t


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
async def analyze_ticker(
    ticker: str,
    intent: str = "full analysis",
    db: AsyncSession = Depends(get_db),
):
    ticker = _validate_ticker(ticker)

    cached = await _get_cached(ticker, db)
    if cached:
        logger.info("Cache hit for %s", ticker)
        return cached.report_json

    initial_state = AgentState(
        ticker=ticker,
        user_intent=intent,
        plan={},
        transcript=None,
        signals={},
        draft_report={},
        final_report={},
        reflection_notes="",
    )

    try:
        final_state = await agent.ainvoke(initial_state)
    except FormatterError as exc:
        logger.error("Formatter validation failed for %s: %s", ticker, exc)
        raise HTTPException(
            status_code=502,
            detail={"error": str(exc), "code": "FORMATTER_ERROR"},
        )
    except Exception as exc:
        logger.error("Agent failed for %s: %s", ticker, exc)
        raise HTTPException(
            status_code=502,
            detail={"error": "Agent failed to produce a report", "code": "AGENT_ERROR"},
        )

    # ainvoke returns either the state dataclass or a dict depending on LangGraph version
    if isinstance(final_state, dict):
        final_report = final_state.get("final_report", {})
        transcript = final_state.get("transcript")
    else:
        final_report = getattr(final_state, "final_report", {})
        transcript = getattr(final_state, "transcript", None)

    if not final_report:
        raise HTTPException(
            status_code=502,
            detail={"error": "Agent failed to produce a report", "code": "AGENT_ERROR"},
        )

    db_report = Report(
        ticker=ticker,
        company=final_report.get("company", ticker),
        quarter=final_report.get("quarter", "Unknown"),
        report_date=transcript.report_date if transcript and hasattr(transcript, "report_date") else None,
        transcript_source=transcript.source if transcript and hasattr(transcript, "source") else "unknown",
        raw_transcript=transcript.text if transcript and hasattr(transcript, "text") else "",
        report_json=final_report,
    )
    db.add(db_report)
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent request already inserted this ticker+quarter — return what's there.
        await db.rollback()
        cached = await _get_cached(ticker, db)
        if cached:
            return cached.report_json
        raise HTTPException(
            status_code=502,
            detail={"error": "Report storage conflict", "code": "STORAGE_CONFLICT"},
        )

    return final_report


@router.get("/analyze/{ticker}/latest")
async def get_latest_report(ticker: str, db: AsyncSession = Depends(get_db)):
    ticker = _validate_ticker(ticker)
    cached = await _get_cached(ticker, db)
    if not cached:
        raise HTTPException(
            status_code=404,
            detail={"error": f"No recent report for {ticker}", "code": "REPORT_NOT_FOUND"},
        )
    return cached.report_json
