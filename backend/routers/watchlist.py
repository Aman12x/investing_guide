import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Watchlist

router = APIRouter()
logger = logging.getLogger(__name__)

_TICKER_RE = re.compile(r"^[A-Z0-9.]{1,10}$")


def _validate_ticker(ticker: str) -> str:
    t = ticker.upper().strip()
    if not _TICKER_RE.match(t):
        raise HTTPException(
            status_code=422,
            detail={"error": "Invalid ticker symbol", "code": "INVALID_TICKER"},
        )
    return t


@router.get("/watchlist")
async def list_watchlist(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Watchlist).order_by(Watchlist.added_at.desc()))
    rows = result.scalars().all()
    return [{"ticker": r.ticker, "added_at": r.added_at.isoformat()} for r in rows]


@router.post("/watchlist/{ticker}", status_code=201)
async def add_to_watchlist(ticker: str, db: AsyncSession = Depends(get_db)):
    ticker = _validate_ticker(ticker)
    existing = await db.execute(select(Watchlist).where(Watchlist.ticker == ticker))
    if existing.scalar_one_or_none():
        return {"ticker": ticker, "message": "already in watchlist"}

    db.add(Watchlist(ticker=ticker))
    await db.commit()
    logger.info("Added %s to watchlist", ticker)
    return {"ticker": ticker, "message": "added"}


@router.delete("/watchlist/{ticker}")
async def remove_from_watchlist(ticker: str, db: AsyncSession = Depends(get_db)):
    ticker = _validate_ticker(ticker)
    result = await db.execute(delete(Watchlist).where(Watchlist.ticker == ticker))
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(
            status_code=404,
            detail={"error": f"{ticker} not in watchlist", "code": "NOT_IN_WATCHLIST"},
        )
    logger.info("Removed %s from watchlist", ticker)
    return {"ticker": ticker, "message": "removed"}
