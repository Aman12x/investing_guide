import logging
import os
from datetime import date

import httpx

from services.models import TranscriptResult

logger = logging.getLogger(__name__)

_FMP_BASE = "https://financialmodelingprep.com/api/v3"


def _recent_quarters(n: int = 5) -> list[tuple[int, int]]:
    """Return the last n (quarter, year) tuples, most recent first."""
    today = date.today()
    q = (today.month - 1) // 3 + 1
    y = today.year
    out = []
    for _ in range(n):
        out.append((q, y))
        q -= 1
        if q == 0:
            q, y = 4, y - 1
    return out


def _parse_entry(ticker: str, entry: dict) -> TranscriptResult | None:
    content: str = entry.get("content", "")
    if not content or len(content) < 2000:
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


async def fetch_from_fmp(ticker: str) -> TranscriptResult | None:
    key = os.getenv("FMP_KEY")
    if not key:
        return None

    url = f"{_FMP_BASE}/earning_call_transcript/{ticker}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Primary: limit=1 (works on some FMP plans)
        try:
            resp = await client.get(url, params={"limit": 1, "apikey": key})
            resp.raise_for_status()
            data = resp.json()
            if data and isinstance(data, list):
                result = _parse_entry(ticker, data[0])
                if result:
                    return result
        except httpx.HTTPError as exc:
            logger.warning("FMP transcript request failed for %s: %s", ticker, exc)
            return None

        # Fallback: explicit quarter/year — required on some FMP plans/tickers
        for q, y in _recent_quarters():
            try:
                resp = await client.get(url, params={"quarter": q, "year": y, "apikey": key})
                resp.raise_for_status()
                data = resp.json()
                if data and isinstance(data, list):
                    result = _parse_entry(ticker, data[0])
                    if result:
                        logger.info("FMP: found transcript for %s via explicit Q%d %d", ticker, q, y)
                        return result
            except httpx.HTTPError:
                continue

    logger.info("FMP: no transcript found for %s", ticker)
    return None
