import logging
import os
from dataclasses import dataclass

import httpx

from exceptions import AnalystError

logger = logging.getLogger(__name__)

_FINNHUB_URL = "https://finnhub.io/api/v1/stock/recommendation"


@dataclass
class AnalystSignal:
    ticker: str
    buy: int
    hold: int
    sell: int
    strong_buy: int
    strong_sell: int
    raw_signal: str   # "BUY" | "HOLD" | "WATCH"
    period: str       # "2025-04"


def _compute_signal(buy: int, strong_buy: int, hold: int, sell: int, strong_sell: int) -> str:
    total = buy + strong_buy + hold + sell + strong_sell
    if total == 0:
        return "HOLD"
    if (buy + strong_buy) / total > 0.60:
        return "BUY"
    if (sell + strong_sell) / total > 0.40:
        return "WATCH"
    return "HOLD"


async def fetch_analyst_ratings(ticker: str) -> AnalystSignal | None:
    api_key = os.getenv("FINNHUB_KEY")
    if not api_key:
        logger.info("FINNHUB_KEY not set — skipping analyst ratings")
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _FINNHUB_URL,
                params={"symbol": ticker, "token": api_key},
            )
            resp.raise_for_status()
            data = resp.json()

        if not data:
            return None

        # Use the most recent month only
        latest = data[0]
        buy = latest.get("buy", 0)
        strong_buy = latest.get("strongBuy", 0)
        hold = latest.get("hold", 0)
        sell = latest.get("sell", 0)
        strong_sell = latest.get("strongSell", 0)
        period = latest.get("period", "unknown")

        return AnalystSignal(
            ticker=ticker,
            buy=buy,
            hold=hold,
            sell=sell,
            strong_buy=strong_buy,
            strong_sell=strong_sell,
            raw_signal=_compute_signal(buy, strong_buy, hold, sell, strong_sell),
            period=period,
        )
    except httpx.HTTPError as exc:
        raise AnalystError(f"Finnhub fetch failed for {ticker}: {exc}") from exc
