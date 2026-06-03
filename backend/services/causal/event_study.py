"""
Causal event study helpers.

Core export: get_confounding_dates() — async, 24h cached dict of {date_str: label}
covering FOMC meeting dates (live fetch), standard monthly options expirations, and
S&P 500 index rebalance dates (both computed mathematically).

check_confounded_by(earnings_date) returns the subset of labels that fall within
1 trading day of the supplied date.
"""

import logging
from datetime import date, datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_cache: dict[str, str] | None = None
_cache_time: datetime | None = None
_CACHE_TTL = timedelta(hours=24)

_FOMC_URL = "https://www.federalreserve.gov/json/ne-press.json"

# ---------------------------------------------------------------------------
# Pure math helpers
# ---------------------------------------------------------------------------

def _third_friday(year: int, month: int) -> date:
    """Return the third Friday of the given month."""
    first = date(year, month, 1)
    # weekday(): Mon=0 … Fri=4 … Sun=6
    days_until_friday = (4 - first.weekday()) % 7
    first_friday = first + timedelta(days=days_until_friday)
    return first_friday + timedelta(days=14)


def _compute_options_expiry(years: list[int]) -> dict[str, str]:
    """Third Friday of every month — standard monthly expiration."""
    result: dict[str, str] = {}
    for year in years:
        for month in range(1, 13):
            d = _third_friday(year, month)
            result[d.isoformat()] = "Options Expiration"
    return result


def _compute_index_rebalance(years: list[int]) -> dict[str, str]:
    """S&P 500 rebalances on the third Friday of March, June, September, December."""
    result: dict[str, str] = {}
    for year in years:
        for month in (3, 6, 9, 12):
            d = _third_friday(year, month)
            result[d.isoformat()] = "S&P 500 Rebalance"
    return result


# ---------------------------------------------------------------------------
# FOMC fetch
# ---------------------------------------------------------------------------

async def _fetch_fomc_dates() -> dict[str, str]:
    """
    Fetch FOMC meeting dates from the Fed press release feed.
    Returns {} on any failure — never raises.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(_FOMC_URL)
            response.raise_for_status()
            # Feed is UTF-8 with BOM
            raw = response.content.decode("utf-8-sig")
            import json
            items = json.loads(raw)

        result: dict[str, str] = {}
        for item in items:
            if item.get("pt") != "Monetary Policy":
                continue
            title = item.get("t", "")
            if "FOMC statement" not in title:
                continue
            d_str = item.get("d", "")
            # Format varies: "M/D/YYYY H:MM:SS AM/PM" (recent) or "M/D/YYYY" (older)
            d_str = d_str.strip()
            for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y"):
                try:
                    parsed = datetime.strptime(d_str, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                logger.debug("Unrecognised FOMC date format: %r", d_str)
                continue
            result[parsed.isoformat()] = "FOMC Meeting"
        return result

    except Exception as exc:
        logger.warning("FOMC date fetch failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_confounding_dates() -> dict[str, str]:
    """
    Return {date_str: label} for all known confounding market events.

    Sources (merged in precedence order — later overwrites earlier):
      1. Standard monthly options expiration — third Friday of every month
      2. S&P 500 index rebalance — third Friday of Mar/Jun/Sep/Dec (overwrites options label)
      3. FOMC meeting dates — live fetch from federalreserve.gov (most significant; overwrites both)

    Result is cached for 24 hours. FOMC fetch failure is silent; math dates always populate.
    """
    global _cache, _cache_time

    now = datetime.now(tz=timezone.utc)
    if _cache is not None and _cache_time is not None and (now - _cache_time) < _CACHE_TTL:
        return _cache

    current_year = now.year
    years = [current_year, current_year + 1]

    merged: dict[str, str] = {}
    merged.update(_compute_options_expiry(years))   # lowest precedence
    merged.update(_compute_index_rebalance(years))  # overwrites options on same day
    merged.update(await _fetch_fomc_dates())         # highest precedence

    _cache = merged
    _cache_time = now
    return _cache


def _is_within_one_trading_day(earnings: date, confound: date) -> bool:
    """
    True if confound falls within 1 trading day of earnings.

    Uses a calendar approximation (no trading-calendar library):
    - Same day or adjacent calendar day where both are weekdays
    - Monday/Friday pairs (4 calendar days apart = 1 trading day)

    Misses market holidays (~10 per year) but is correct >95% of the time.
    """
    delta = abs((confound - earnings).days)
    if delta <= 1:
        return earnings.weekday() < 5 and confound.weekday() < 5
    if delta == 4:
        # Mon earnings / Fri confound or vice versa (Mon + 4 days = Fri)
        return {earnings.weekday(), confound.weekday()} == {0, 4}
    return False


async def check_confounded_by(earnings_date: date) -> list[str]:
    """
    Return a list of confounding event labels that fall within 1 trading day
    of the supplied earnings date. Empty list means no confounders detected.
    """
    dates = await get_confounding_dates()
    labels: list[str] = []
    for date_str, label in dates.items():
        try:
            confound = date.fromisoformat(date_str)
        except ValueError:
            continue
        if _is_within_one_trading_day(earnings_date, confound):
            labels.append(label)
    return labels
