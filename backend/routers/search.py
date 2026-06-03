import logging
import os
import time

import httpx
from fastapi import APIRouter

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
    if not fmp_key:
        return []

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                "https://financialmodelingprep.com/api/v3/search",
                params={"query": q, "limit": 8, "apikey": fmp_key},
            )
            if not resp.is_success:
                return []
            data = resp.json()
    except Exception as exc:
        logger.warning("FMP search failed for '%s': %s", q, exc)
        return []

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
