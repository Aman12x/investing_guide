import logging
import os
import time

import httpx
from fastapi import APIRouter

from services.ticker_aliases import static_search

router = APIRouter()
logger = logging.getLogger(__name__)

_cache: dict[str, tuple[list, float]] = {}
_CACHE_TTL = 3600.0


@router.get("/search")
async def search_tickers(q: str = ""):
    q = q.strip()
    if not q:
        return []

    key = q.upper()
    if key in _cache:
        results, exp = _cache[key]
        if time.time() < exp:
            return results

    fmp_key = os.getenv("FMP_KEY")
    if fmp_key:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(
                    "https://financialmodelingprep.com/api/v3/search",
                    params={"query": q, "limit": 8, "apikey": fmp_key},
                )
                if resp.is_success:
                    data = resp.json()
                    results = [
                        {
                            "symbol": item["symbol"],
                            "name": item.get("name", ""),
                            "exchange": item.get("exchangeShortName", ""),
                        }
                        for item in data
                        if item.get("symbol")
                    ]
                    _cache[key] = (results, time.time() + _CACHE_TTL)
                    return results
        except Exception as exc:
            logger.warning("FMP search failed for '%s': %s", q, exc)

    # Fallback: static curated list (covers top ~60 tickers + alias resolution)
    results = static_search(q)
    _cache[key] = (results, time.time() + _CACHE_TTL)
    return results
