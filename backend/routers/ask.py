import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from exceptions import ClaudeError
from models import Report
from schemas import AskRequest
from services.qa import answer_question

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/ask/{ticker}")
async def ask(ticker: str, body: AskRequest, db: AsyncSession = Depends(get_db)):
    ticker = ticker.upper().strip()

    stmt = select(Report).where(Report.ticker == ticker).order_by(Report.created_at.desc())
    result = await db.execute(stmt)
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=404,
            detail={"error": f"No report found for {ticker}. Run /analyze/{ticker} first.", "code": "REPORT_NOT_FOUND"},
        )

    try:
        answer = await answer_question(
            ticker=ticker,
            transcript=report.raw_transcript or "",
            question=body.question,
            history=[h.model_dump() for h in body.history],
        )
    except ClaudeError as exc:
        logger.error("Claude QA failed for %s: %s", ticker, exc)
        raise HTTPException(
            status_code=502,
            detail={"error": "Q&A failed", "code": "CLAUDE_ERROR"},
        )

    return {"answer": answer}
