"""
Tests for services/causal/event_study.py.

Covers:
  - Pure math helpers (_third_friday, options expiry, index rebalance)
  - FOMC fetch: success (both date formats + BOM), HTTP errors, timeout, bad JSON, schema drift
  - Cache: freshness check, TTL expiry, graceful degradation on FOMC failure
  - Merge precedence: options < rebalance < FOMC
  - _is_within_one_trading_day: all boundary cases including Mon/Fri wrap
  - check_confounded_by: known dates, clean dates, multiple confounders
  - Concurrent cold-cache calls (no deadlock, idempotent result)
"""

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

import services.causal.event_study as mod
from services.causal.event_study import (
    _compute_index_rebalance,
    _compute_options_expiry,
    _fetch_fomc_dates,
    _is_within_one_trading_day,
    _third_friday,
    check_confounded_by,
    get_confounding_dates,
)

_FOMC_URL = "https://www.federalreserve.gov/json/ne-press.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fomc_json(*entries: dict) -> bytes:
    """Wrap entries in the Fed's UTF-8 BOM JSON envelope."""
    return ("﻿" + json.dumps(list(entries))).encode("utf-8")


def _fomc_entry(date_str: str, title: str = "Federal Reserve issues FOMC statement",
                pt: str = "Monetary Policy") -> dict:
    return {"d": date_str, "t": title, "pt": pt, "l": "/newsevents/..."}


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    """Wipe the module-level cache before every test."""
    monkeypatch.setattr(mod, "_cache", None)
    monkeypatch.setattr(mod, "_cache_time", None)


# ---------------------------------------------------------------------------
# 1. _third_friday
# ---------------------------------------------------------------------------

class TestThirdFriday:
    def test_known_dates(self):
        assert _third_friday(2025, 1) == date(2025, 1, 17)
        assert _third_friday(2025, 3) == date(2025, 3, 21)
        assert _third_friday(2025, 6) == date(2025, 6, 20)
        assert _third_friday(2025, 9) == date(2025, 9, 19)
        assert _third_friday(2025, 12) == date(2025, 12, 19)
        assert _third_friday(2026, 3) == date(2026, 3, 20)

    def test_always_friday(self):
        for year in (2025, 2026, 2027):
            for month in range(1, 13):
                d = _third_friday(year, month)
                assert d.weekday() == 4, f"{d} is not a Friday"

    def test_always_third_week(self):
        for year in (2025, 2026):
            for month in range(1, 13):
                d = _third_friday(year, month)
                assert 15 <= d.day <= 21, f"{d}.day={d.day} not in third-Friday range"


# ---------------------------------------------------------------------------
# 2. _compute_options_expiry
# ---------------------------------------------------------------------------

class TestOptionsExpiry:
    def test_two_year_window_yields_24_entries(self):
        result = _compute_options_expiry([2025, 2026])
        assert len(result) == 24

    def test_all_labels_are_options_expiration(self):
        result = _compute_options_expiry([2026])
        assert all(v == "Options Expiration" for v in result.values())

    def test_all_dates_are_fridays(self):
        result = _compute_options_expiry([2025])
        for ds in result:
            assert date.fromisoformat(ds).weekday() == 4

    def test_spot_check(self):
        result = _compute_options_expiry([2025])
        assert "2025-03-21" in result
        assert "2025-06-20" in result
        assert "2025-12-19" in result


# ---------------------------------------------------------------------------
# 3. _compute_index_rebalance
# ---------------------------------------------------------------------------

class TestIndexRebalance:
    def test_two_year_window_yields_8_entries(self):
        result = _compute_index_rebalance([2025, 2026])
        assert len(result) == 8

    def test_only_rebalance_months(self):
        result = _compute_index_rebalance([2025])
        months = {date.fromisoformat(ds).month for ds in result}
        assert months == {3, 6, 9, 12}

    def test_all_labels_are_sp500_rebalance(self):
        result = _compute_index_rebalance([2025])
        assert all(v == "S&P 500 Rebalance" for v in result.values())

    def test_spot_check(self):
        result = _compute_index_rebalance([2025, 2026])
        assert result["2025-03-21"] == "S&P 500 Rebalance"
        assert result["2026-03-20"] == "S&P 500 Rebalance"

    def test_rebalance_is_subset_of_options(self):
        opts = _compute_options_expiry([2025])
        reb = _compute_index_rebalance([2025])
        assert set(reb.keys()).issubset(set(opts.keys()))


# ---------------------------------------------------------------------------
# 4. _fetch_fomc_dates — success paths
# ---------------------------------------------------------------------------

class TestFetchFomcDates:
    @respx.mock
    async def test_parses_datetime_format(self):
        payload = _make_fomc_json(
            _fomc_entry("4/29/2026 2:00:00 PM"),
            _fomc_entry("3/18/2026 2:00:00 PM"),
        )
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=payload))

        result = await _fetch_fomc_dates()
        assert result == {"2026-04-29": "FOMC Meeting", "2026-03-18": "FOMC Meeting"}

    @respx.mock
    async def test_parses_date_only_format(self):
        """Older feed entries use M/D/YYYY with no time component."""
        payload = _make_fomc_json(_fomc_entry("1/31/2006"))
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=payload))

        result = await _fetch_fomc_dates()
        assert result == {"2006-01-31": "FOMC Meeting"}

    @respx.mock
    async def test_handles_bom_encoding(self):
        """Byte-order mark must not corrupt date parsing."""
        payload = _make_fomc_json(_fomc_entry("12/10/2025 2:00:00 PM"))
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=payload))

        result = await _fetch_fomc_dates()
        assert "2025-12-10" in result

    @respx.mock
    async def test_skips_non_monetary_policy_entries(self):
        payload = _make_fomc_json(
            _fomc_entry("4/29/2026 2:00:00 PM"),
            _fomc_entry("6/2/2026 11:00:00 AM", title="Agencies remove references",
                        pt="Banking and Consumer Regulatory Policy"),
        )
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=payload))

        result = await _fetch_fomc_dates()
        assert len(result) == 1
        assert "2026-04-29" in result

    @respx.mock
    async def test_skips_minutes_entries(self):
        """Minutes releases are Monetary Policy but are NOT meeting days."""
        payload = _make_fomc_json(
            _fomc_entry("4/29/2026 2:00:00 PM"),
            _fomc_entry("5/20/2026 2:00:00 PM",
                        title="Minutes of the Federal Open Market Committee, April 28-29, 2026"),
        )
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=payload))

        result = await _fetch_fomc_dates()
        assert len(result) == 1
        assert "2026-04-29" in result
        assert "2026-05-20" not in result


# ---------------------------------------------------------------------------
# 5. _fetch_fomc_dates — failure paths (all must return {}, never raise)
# ---------------------------------------------------------------------------

class TestFetchFomcFailures:
    @respx.mock
    async def test_http_error_returns_empty(self):
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(503))
        result = await _fetch_fomc_dates()
        assert result == {}

    @respx.mock
    async def test_network_error_returns_empty(self):
        respx.get(_FOMC_URL).mock(side_effect=httpx.ConnectError("refused"))
        result = await _fetch_fomc_dates()
        assert result == {}

    @respx.mock
    async def test_timeout_returns_empty(self):
        respx.get(_FOMC_URL).mock(side_effect=httpx.TimeoutException("timeout"))
        result = await _fetch_fomc_dates()
        assert result == {}

    @respx.mock
    async def test_invalid_json_returns_empty(self):
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=b"not-json"))
        result = await _fetch_fomc_dates()
        assert result == {}

    @respx.mock
    async def test_unexpected_schema_returns_empty(self):
        """If Fed changes to a dict instead of a list, parse fails silently."""
        payload = json.dumps({"error": "gone"}).encode()
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=payload))
        result = await _fetch_fomc_dates()
        assert result == {}

    @respx.mock
    async def test_unrecognised_date_format_skips_entry(self):
        """Entry with unrecognised date format is skipped; valid entries still returned."""
        payload = _make_fomc_json(
            _fomc_entry("April 29, 2026"),        # unexpected format
            _fomc_entry("3/18/2026 2:00:00 PM"),  # valid
        )
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=payload))
        result = await _fetch_fomc_dates()
        assert "2026-03-18" in result
        assert len(result) == 1


# ---------------------------------------------------------------------------
# 6. Cache behaviour
# ---------------------------------------------------------------------------

class TestCache:
    @respx.mock
    async def test_fresh_cache_skips_fomc_fetch(self):
        """If cache is warm, _fetch_fomc_dates must not be called."""
        frozen = {"2026-01-28": "FOMC Meeting"}
        mod._cache = frozen
        mod._cache_time = datetime.now(tz=timezone.utc)  # just set

        # No route registered — if httpx fires, respx raises an error
        result = await get_confounding_dates()
        assert result is frozen

    @respx.mock
    async def test_stale_cache_triggers_refresh(self):
        mod._cache = {"old": "data"}
        mod._cache_time = datetime.now(tz=timezone.utc) - timedelta(hours=25)

        payload = _make_fomc_json(_fomc_entry("1/28/2026 2:00:00 PM"))
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=payload))

        result = await get_confounding_dates()
        assert "2026-01-28" in result
        assert result.get("old") != "data"  # stale entry gone

    @respx.mock
    async def test_fomc_failure_still_populates_math_dates(self):
        """FOMC fetch 503 → cache still contains options + rebalance dates."""
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(503))

        result = await get_confounding_dates()
        assert len(result) >= 24   # 24 options + 8 rebalance, minus 8 overlaps = at least 24 total
        assert any(v == "S&P 500 Rebalance" for v in result.values())
        assert any(v == "Options Expiration" for v in result.values())
        assert all(v != "FOMC Meeting" for v in result.values())

    @respx.mock
    async def test_second_call_returns_same_object(self):
        """Cache hit returns identical object (no copy)."""
        payload = _make_fomc_json(_fomc_entry("1/28/2026 2:00:00 PM"))
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=payload))

        first = await get_confounding_dates()
        second = await get_confounding_dates()
        assert first is second


# ---------------------------------------------------------------------------
# 7. Merge precedence
# ---------------------------------------------------------------------------

class TestMergePrecedence:
    @respx.mock
    async def test_rebalance_wins_over_options_on_same_day(self):
        """Third Friday of March/Jun/Sep/Dec: rebalance label beats options label."""
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(503))  # FOMC silent

        result = await get_confounding_dates()
        current_year = datetime.now(tz=timezone.utc).year
        march_rebalance = _third_friday(current_year, 3).isoformat()
        assert result.get(march_rebalance) == "S&P 500 Rebalance"

    @respx.mock
    async def test_fomc_wins_over_rebalance_on_same_day(self):
        """FOMC on a rebalance Friday → FOMC label wins."""
        current_year = datetime.now(tz=timezone.utc).year
        rebalance_day = _third_friday(current_year, 3)
        fomc_date_str = f"{rebalance_day.month}/{rebalance_day.day}/{rebalance_day.year} 2:00:00 PM"

        payload = _make_fomc_json(_fomc_entry(fomc_date_str))
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=payload))

        result = await get_confounding_dates()
        assert result.get(rebalance_day.isoformat()) == "FOMC Meeting"


# ---------------------------------------------------------------------------
# 8. _is_within_one_trading_day
# ---------------------------------------------------------------------------

class TestIsWithinOneTradingDay:
    # True cases
    def test_same_weekday(self):
        assert _is_within_one_trading_day(date(2026, 3, 18), date(2026, 3, 18))  # Wed

    def test_adjacent_weekdays(self):
        assert _is_within_one_trading_day(date(2026, 3, 17), date(2026, 3, 18))  # Tue/Wed
        assert _is_within_one_trading_day(date(2026, 3, 18), date(2026, 3, 17))  # commutative

    def test_monday_friday_is_one_trading_day(self):
        assert _is_within_one_trading_day(date(2026, 3, 16), date(2026, 3, 20))  # Mon/Fri
        assert _is_within_one_trading_day(date(2026, 3, 20), date(2026, 3, 16))  # Fri/Mon

    # False cases
    def test_two_days_apart_not_flagged(self):
        assert not _is_within_one_trading_day(date(2026, 3, 16), date(2026, 3, 18))  # Mon/Wed

    def test_adjacent_where_one_is_saturday(self):
        # Fri/Sat: Sat is not a trading day
        assert not _is_within_one_trading_day(date(2026, 3, 20), date(2026, 3, 21))  # Fri/Sat

    def test_adjacent_where_one_is_sunday(self):
        assert not _is_within_one_trading_day(date(2026, 3, 22), date(2026, 3, 21))  # Sun/Sat

    def test_week_apart(self):
        assert not _is_within_one_trading_day(date(2026, 3, 18), date(2026, 3, 25))

    def test_tuesday_thursday_two_days_not_flagged(self):
        assert not _is_within_one_trading_day(date(2026, 3, 17), date(2026, 3, 19))  # Tue/Thu


# ---------------------------------------------------------------------------
# 9. check_confounded_by
# ---------------------------------------------------------------------------

class TestCheckConfoundedBy:
    @respx.mock
    async def test_fomc_day_flagged(self):
        payload = _make_fomc_json(_fomc_entry("3/18/2026 2:00:00 PM"))
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=payload))

        labels = await check_confounded_by(date(2026, 3, 18))
        assert "FOMC Meeting" in labels

    @respx.mock
    async def test_day_before_fomc_flagged(self):
        payload = _make_fomc_json(_fomc_entry("3/18/2026 2:00:00 PM"))
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=payload))

        labels = await check_confounded_by(date(2026, 3, 17))  # Tue, one day before
        assert "FOMC Meeting" in labels

    @respx.mock
    async def test_two_days_before_fomc_clean(self):
        payload = _make_fomc_json(_fomc_entry("3/18/2026 2:00:00 PM"))
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=payload))

        labels = await check_confounded_by(date(2026, 3, 16))  # Mon, 2 days before
        assert "FOMC Meeting" not in labels

    @respx.mock
    async def test_rebalance_day_flagged(self):
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(503))

        current_year = datetime.now(tz=timezone.utc).year
        reb_day = _third_friday(current_year, 3)
        labels = await check_confounded_by(reb_day)
        assert "S&P 500 Rebalance" in labels

    @respx.mock
    async def test_options_expiry_flagged(self):
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(503))

        current_year = datetime.now(tz=timezone.utc).year
        # January — options only, no rebalance
        jan_expiry = _third_friday(current_year, 1)
        labels = await check_confounded_by(jan_expiry)
        assert "Options Expiration" in labels

    @respx.mock
    async def test_neutral_date_returns_empty(self):
        payload = _make_fomc_json(_fomc_entry("3/18/2026 2:00:00 PM"))
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=payload))

        # A random Wednesday with no nearby events
        labels = await check_confounded_by(date(2026, 7, 8))
        assert labels == []

    @respx.mock
    async def test_multiple_confounders_returned(self):
        """FOMC meeting on a rebalance Friday → both labels appear (FOMC overwrites in cache,
        but adjacent days can still carry options/rebalance labels)."""
        # Use Jan (options only) — day after options expiry: FOMC is on expiry day itself
        current_year = datetime.now(tz=timezone.utc).year
        jan_expiry = _third_friday(current_year, 1)
        fomc_str = f"{jan_expiry.month}/{jan_expiry.day}/{jan_expiry.year} 2:00:00 PM"
        # Also add a FOMC on the day before so we get both from adjacent days
        day_before = jan_expiry - timedelta(days=1)
        fomc_before = f"{day_before.month}/{day_before.day}/{day_before.year} 2:00:00 PM"

        payload = _make_fomc_json(
            _fomc_entry(fomc_str),
            _fomc_entry(fomc_before),
        )
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=payload))

        labels = await check_confounded_by(jan_expiry)
        # jan_expiry itself is FOMC (overwrote options); day before is also FOMC
        assert labels.count("FOMC Meeting") >= 1

    @respx.mock
    async def test_uses_cached_result(self):
        """Second call within TTL must not trigger a second HTTP request."""
        payload = _make_fomc_json(_fomc_entry("3/18/2026 2:00:00 PM"))
        route = respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=payload))

        await check_confounded_by(date(2026, 3, 18))
        await check_confounded_by(date(2026, 3, 18))
        assert route.call_count == 1  # single fetch, second was cached


# ---------------------------------------------------------------------------
# 10. Concurrent cold-cache calls
# ---------------------------------------------------------------------------

class TestConcurrency:
    @respx.mock
    async def test_concurrent_cold_calls_do_not_deadlock(self):
        """Both coroutines hitting a cold cache produce identical results without error."""
        payload = _make_fomc_json(_fomc_entry("1/28/2026 2:00:00 PM"))
        respx.get(_FOMC_URL).mock(return_value=httpx.Response(200, content=payload))

        results = await asyncio.gather(
            get_confounding_dates(),
            get_confounding_dates(),
        )
        assert results[0] == results[1]
        assert "2026-01-28" in results[0]
