import logging
import os
import re
from datetime import date

import httpx

from services.models import TranscriptResult

logger = logging.getLogger(__name__)

_AV_BASE = "https://www.alphavantage.co/query"
_QUARTER_RE = re.compile(r"Q[1-4]\s+20\d{2}", re.IGNORECASE)


def _recent_quarters(n: int = 3) -> list[tuple[int, int]]:
    """Return the last n (year, quarter_num) tuples, most recent first."""
    today = date.today()
    q = (today.month - 1) // 3 + 1
    y = today.year
    out = []
    for _ in range(n):
        out.append((y, q))
        q -= 1
        if q == 0:
            q, y = 4, y - 1
    return out


def _extract_quarter(text: str) -> str | None:
    m = _QUARTER_RE.search(text)
    return m.group(0).upper() if m else None


async def fetch_from_motley_fool(ticker: str) -> TranscriptResult | None:
    """
    Third-tier fallback: Alpha Vantage EARNINGS_CALL_TRANSCRIPT endpoint.
    Requires ALPHA_VANTAGE_KEY env var. Returns None gracefully if absent or rate-limited.
    Tries the 3 most recent calendar quarters, returns on first hit ≥ 2000 chars.
    """
    key = os.getenv("ALPHA_VANTAGE_KEY")
    if not key:
        return None

    async with httpx.AsyncClient(timeout=15.0) as client:
        for year, quarter in _recent_quarters():
            try:
                resp = await client.get(
                    _AV_BASE,
                    params={
                        "function": "EARNINGS_CALL_TRANSCRIPT",
                        "symbol": ticker,
                        "year": year,
                        "quarter": quarter,
                        "apikey": key,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                # Alpha Vantage returns these keys on rate limit or invalid/insufficient key
                if "Information" in data or "Note" in data:
                    logger.warning(
                        "Alpha Vantage quota/key issue for %s: %s",
                        ticker,
                        data.get("Information") or data.get("Note"),
                    )
                    return None

                transcript_text: str = data.get("transcript", "")
                if not transcript_text or len(transcript_text) < 2000:
                    continue

                quarter_str = data.get("quarter") or _extract_quarter(transcript_text)

                raw_date: str = data.get("date", "")
                report_date: date | None = None
                if raw_date:
                    try:
                        report_date = date.fromisoformat(raw_date[:10])
                    except ValueError:
                        pass

                logger.info("Alpha Vantage: fetched transcript for %s (%d chars)", ticker, len(transcript_text))
                return TranscriptResult(
                    ticker=ticker,
                    text=transcript_text,
                    source="alphavantage",
                    quarter=quarter_str,
                    report_date=report_date,
                )
            except httpx.HTTPError as exc:
                logger.warning(
                    "Alpha Vantage request failed for %s (Q%d %d): %s", ticker, quarter, year, exc
                )
                continue

    logger.info("Alpha Vantage: no transcript found for %s", ticker)
    return None
