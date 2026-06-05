"""Layer 3 — Transcript waterfall tests. Uses respx to mock all httpx calls."""
import json
from datetime import date, datetime, timedelta

import httpx
import pytest
import respx

import services.edgar as edgar_module
from exceptions import TranscriptNotFoundError
from services.transcript import fetch_transcript

# ── helpers ──────────────────────────────────────────────────────────────────

_AAPL_CIK = "0000320193"
_ACC_NO = "0000320193-25-000001"
_ACC_NODASHES = "000032019325000001"

_TRANSCRIPT_TEXT = (
    "Good morning, everyone. Thank you for joining today's earnings conference call. "
    "operator here. This is the Q1 2025 earnings call for Acme Corporation. "
    "We will now open for the question-and-answer session. "
) + ("The company delivered record revenue across all segments. " * 120)

assert len(_TRANSCRIPT_TEXT) > 2000

_SHORT_TEXT = "operator short " * 10  # < 2000 chars, has transcript marker

_SUBMISSIONS = {
    "filings": {
        "recent": {
            "form": ["8-K"],
            "accessionNumber": [_ACC_NO],
            "filingDate": [datetime.utcnow().strftime("%Y-%m-%d")],
            "primaryDocument": ["primary.htm"],
        }
    }
}

_INDEX_HTML = """
<html><body><table>
<tr>
  <td>EX-99.1</td>
  <td><a href="/Archives/edgar/data/320193/{acc}/exhibit.htm">exhibit.htm</a></td>
</tr>
</table></body></html>
""".format(acc=_ACC_NODASHES)

_EXHIBIT_URL = f"https://www.sec.gov/Archives/edgar/data/320193/{_ACC_NODASHES}/exhibit.htm"
_INDEX_URL = f"https://www.sec.gov/Archives/edgar/data/320193/{_ACC_NODASHES}/"
_SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{_AAPL_CIK}.json"
_FMP_URL = "https://financialmodelingprep.com/api/v3/earning_call_transcript/AAPL"
_STOCKANALYSIS_URL = "https://stockanalysis.com/stocks/aapl/transcripts/"

_SA_DETAIL_SLUG = "q1-2025-earnings-call"
_SA_DETAIL_URL = f"https://stockanalysis.com/stocks/aapl/transcripts/{_SA_DETAIL_SLUG}/"

_SA_LISTING_HTML = f"""
<html><body>
<a href="/stocks/aapl/transcripts/{_SA_DETAIL_SLUG}/">Q1 2025 Earnings Call</a>
</body></html>
"""

_SA_DETAIL_HTML = f"<html><body><article>{_TRANSCRIPT_TEXT}</article></body></html>"


def _fmp_response(text: str = _TRANSCRIPT_TEXT) -> dict:
    return [{"content": text, "quarter": 1, "year": 2025, "date": "2025-01-30"}]


@pytest.fixture(autouse=True)
def reset_cik_cache(monkeypatch):
    """Wipe the module-level CIK cache before every waterfall test."""
    monkeypatch.setattr(edgar_module, "_cik_map", {"AAPL": _AAPL_CIK})


# ── tests ─────────────────────────────────────────────────────────────────────


@respx.mock
async def test_edgar_succeeds(monkeypatch):
    """EDGAR returns a long-enough transcript → result.source == 'edgar'."""
    monkeypatch.setattr(edgar_module, "_NON_TRANSCRIPT_FILERS", frozenset())
    respx.get(_SUBMISSIONS_URL).mock(return_value=httpx.Response(200, json=_SUBMISSIONS))
    respx.get(_INDEX_URL).mock(return_value=httpx.Response(200, text=_INDEX_HTML))
    respx.get(_EXHIBIT_URL).mock(return_value=httpx.Response(200, text=_TRANSCRIPT_TEXT))

    result = await fetch_transcript("AAPL")
    assert result.source == "edgar"
    assert len(result.text) >= 2000


@respx.mock
async def test_edgar_short_text_falls_through_to_fmp(monkeypatch):
    """EDGAR returns <2000 chars; FMP returns a full transcript → source == 'fmp'."""
    monkeypatch.setenv("FMP_KEY", "testkey")

    short_index_html = _INDEX_HTML  # same structure
    respx.get(_SUBMISSIONS_URL).mock(return_value=httpx.Response(200, json=_SUBMISSIONS))
    respx.get(_INDEX_URL).mock(return_value=httpx.Response(200, text=short_index_html))
    respx.get(_EXHIBIT_URL).mock(return_value=httpx.Response(200, text=_SHORT_TEXT))
    respx.get(_FMP_URL).mock(return_value=httpx.Response(200, json=_fmp_response()))
    # Scraper should not be needed; block it to surface unexpected calls
    respx.get(_STOCKANALYSIS_URL).mock(return_value=httpx.Response(404))

    result = await fetch_transcript("AAPL")
    assert result.source == "fmp"


@respx.mock
async def test_fmp_key_absent_skips_fmp(monkeypatch):
    """When FMP_KEY is unset, FMP makes no HTTP call; EDGAR still runs."""
    monkeypatch.delenv("FMP_KEY", raising=False)

    # EDGAR finds no 8-K filings in the window → returns None
    empty_submissions = {
        "filings": {"recent": {"form": [], "accessionNumber": [], "filingDate": [], "primaryDocument": []}}
    }
    respx.get(_SUBMISSIONS_URL).mock(return_value=httpx.Response(200, json=empty_submissions))
    # FMP URL must NOT be called; if it is, respx will raise (no route registered)
    respx.get(_STOCKANALYSIS_URL).mock(return_value=httpx.Response(404))

    with pytest.raises(TranscriptNotFoundError):
        await fetch_transcript("AAPL")


@respx.mock
async def test_all_sources_fail_raises_not_found(monkeypatch):
    """All three sources fail → TranscriptNotFoundError (not a bare Exception)."""
    monkeypatch.setenv("FMP_KEY", "testkey")

    respx.get(_SUBMISSIONS_URL).mock(return_value=httpx.Response(500))
    respx.get(_FMP_URL).mock(return_value=httpx.Response(200, json=[]))  # empty list
    respx.get(_STOCKANALYSIS_URL).mock(return_value=httpx.Response(404))

    with pytest.raises(TranscriptNotFoundError):
        await fetch_transcript("AAPL")


@respx.mock
async def test_edgar_500_continues_to_fmp(monkeypatch):
    """EDGAR submissions endpoint returns 500; waterfall continues to FMP."""
    monkeypatch.setenv("FMP_KEY", "testkey")

    respx.get(_SUBMISSIONS_URL).mock(return_value=httpx.Response(500))
    respx.get(_FMP_URL).mock(return_value=httpx.Response(200, json=_fmp_response()))
    respx.get(_STOCKANALYSIS_URL).mock(return_value=httpx.Response(404))

    result = await fetch_transcript("AAPL")
    assert result.source == "fmp"


@respx.mock
async def test_fmp_empty_list_continues_to_scraper(monkeypatch):
    """FMP returns an empty list → treated as None; waterfall continues."""
    monkeypatch.setenv("FMP_KEY", "testkey")

    # EDGAR has no candidates in window
    empty_submissions = {
        "filings": {"recent": {"form": [], "accessionNumber": [], "filingDate": [], "primaryDocument": []}}
    }
    respx.get(_SUBMISSIONS_URL).mock(return_value=httpx.Response(200, json=empty_submissions))
    respx.get(_FMP_URL).mock(return_value=httpx.Response(200, json=[]))
    respx.get(_STOCKANALYSIS_URL).mock(return_value=httpx.Response(404))

    with pytest.raises(TranscriptNotFoundError):
        await fetch_transcript("AAPL")


@respx.mock
async def test_scraper_none_exhausts_waterfall(monkeypatch):
    """StockAnalysis returns 403 (blocked) → waterfall exhausted → TranscriptNotFoundError."""
    monkeypatch.delenv("FMP_KEY", raising=False)

    empty_submissions = {
        "filings": {"recent": {"form": [], "accessionNumber": [], "filingDate": [], "primaryDocument": []}}
    }
    respx.get(_SUBMISSIONS_URL).mock(return_value=httpx.Response(200, json=empty_submissions))
    # stockanalysis blocks non-browser requests
    respx.get(_STOCKANALYSIS_URL).mock(return_value=httpx.Response(403))

    with pytest.raises(TranscriptNotFoundError):
        await fetch_transcript("AAPL")


@respx.mock
async def test_fmp_empty_falls_through_to_stockanalysis(monkeypatch):
    """FMP returns []; StockAnalysis listing + detail succeed → source == 'stockanalysis'."""
    monkeypatch.setenv("FMP_KEY", "testkey")
    # EDGAR skips AAPL immediately (_NON_TRANSCRIPT_FILERS) — no HTTP mock needed
    respx.get(_FMP_URL).mock(return_value=httpx.Response(200, json=[]))
    respx.get(_STOCKANALYSIS_URL).mock(return_value=httpx.Response(200, text=_SA_LISTING_HTML))
    respx.get(_SA_DETAIL_URL).mock(return_value=httpx.Response(200, text=_SA_DETAIL_HTML))

    result = await fetch_transcript("AAPL")
    assert result.source == "stockanalysis"
    assert len(result.text) >= 2000


@respx.mock
async def test_stockanalysis_listing_no_links_exhausts_waterfall(monkeypatch):
    """SA listing page exists but has no transcript links → TranscriptNotFoundError."""
    monkeypatch.delenv("FMP_KEY", raising=False)
    # EDGAR skips AAPL immediately (_NON_TRANSCRIPT_FILERS) — no HTTP mock needed
    respx.get(_STOCKANALYSIS_URL).mock(
        return_value=httpx.Response(200, text="<html><body><p>nothing</p></body></html>")
    )

    with pytest.raises(TranscriptNotFoundError):
        await fetch_transcript("AAPL")
