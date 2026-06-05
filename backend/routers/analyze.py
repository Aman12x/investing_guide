import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agent.graph import agent
from agent.nodes.formatter import FormatterError
from agent.state import AgentState
from database import get_db
from services.ticker_aliases import normalize
from models import Report
from observability import update_trace

router = APIRouter()
logger = logging.getLogger(__name__)

_TICKER_RE = re.compile(r"^[A-Z0-9.]{1,10}$")

_NODE_MESSAGES = {
    "planner":   "Planning analysis…",
    "fetch":     "Fetching transcript & signals…",
    "analyst":   "Drafting analysis…",
    "reflector": "Reviewing draft…",
    "formatter": "Finalizing report…",
}


def _validate_ticker(ticker: str) -> str:
    t = normalize(ticker.strip())
    if not _TICKER_RE.match(t):
        raise HTTPException(
            status_code=422,
            detail={"error": "Invalid ticker symbol", "code": "INVALID_TICKER"},
        )
    return t


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def _get_cached(ticker: str, db: AsyncSession) -> Report | None:
    stmt = (
        select(Report)
        .where(Report.ticker == ticker)
        .order_by(Report.created_at.desc())
        .limit(1)
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

        async def _cached_stream():
            yield _sse({"type": "progress", "message": "Loading cached report…"})
            yield _sse({"type": "done", "report": cached.report_json})

        return StreamingResponse(
            _cached_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

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

    async def _stream():
        update_trace(
            name=f"analyze/{ticker}",
            user_id=ticker,
            session_id=ticker,
            input={"ticker": ticker, "intent": intent},
        )

        accumulated: dict = {}
        try:
            async for chunk in agent.astream(initial_state, stream_mode="updates"):
                for node_name, node_updates in chunk.items():
                    accumulated.update(node_updates)
                    msg = _NODE_MESSAGES.get(node_name)
                    if msg:
                        yield _sse({"type": "progress", "message": msg})
        except FormatterError as exc:
            logger.error("Formatter error for %s: %s", ticker, exc)
            yield _sse({"type": "error", "message": str(exc), "code": "FORMATTER_ERROR"})
            return
        except Exception as exc:
            logger.error("Agent failed for %s: %s", ticker, exc)
            yield _sse({"type": "error", "message": "Agent failed to produce a report", "code": "AGENT_ERROR"})
            return

        final_report = accumulated.get("final_report") or {}
        transcript = accumulated.get("transcript")

        if not final_report:
            yield _sse({"type": "error", "message": "Agent failed to produce a report", "code": "AGENT_ERROR"})
            return

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
            await db.rollback()

        yield _sse({"type": "done", "report": final_report})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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


@router.get("/analyze/{ticker}/history")
async def get_ticker_history(
    ticker: str,
    n: int = 6,
    db: AsyncSession = Depends(get_db),
):
    ticker = _validate_ticker(ticker)
    n = max(1, min(n, 12))
    stmt = (
        select(Report)
        .where(Report.ticker == ticker)
        .order_by(Report.report_date.desc().nullslast(), Report.created_at.desc())
        .limit(n)
    )
    result = await db.execute(stmt)
    reports = result.scalars().all()
    return [r.report_json for r in reports]
