import logging
import os
from datetime import date

import httpx

from services.models import TranscriptResult

logger = logging.getLogger(__name__)

_FMP_BASE = "https://financialmodelingprep.com/api/v3"


async def fetch_from_fmp(ticker: str) -> TranscriptResult | None:
    key = os.getenv("FMP_KEY")
    if not key:
        return None

    url = f"{_FMP_BASE}/earning_call_transcript/{ticker}"
    params = {"limit": 1, "apikey": key}

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("FMP transcript request failed for %s: %s", ticker, exc)
            return None

    data = resp.json()
    if not data or not isinstance(data, list):
        logger.info("FMP: no transcript data for %s", ticker)
        return None

    entry = data[0]
    content: str = entry.get("content", "")
    if not content or len(content) < 2000:
        logger.info("FMP: transcript too short for %s (%d chars)", ticker, len(content))
        return None

    quarter_num = entry.get("quarter")
    year = entry.get("year")
    quarter = f"Q{quarter_num} {year}" if quarter_num and year else None

    raw_date = entry.get("date", "")
    report_date: date | None = None
    if raw_date:
        try:
            report_date = date.fromisoformat(raw_date[:10])
        except ValueError:
            pass

    logger.info("FMP: fetched transcript for %s (%d chars)", ticker, len(content))
    return TranscriptResult(
        ticker=ticker,
        text=content,
        source="fmp",
        quarter=quarter,
        report_date=report_date,
    )
