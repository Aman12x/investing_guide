import asyncio
import logging
import os
import re
from datetime import date, datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from services.models import TranscriptResult

logger = logging.getLogger(__name__)

EDGAR_BASE = "https://data.sec.gov/submissions"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
HEADERS = {"User-Agent": os.getenv("EDGAR_USER_AGENT", "EarningsLens contact@earningslens.app")}

_TRANSCRIPT_MARKERS = [
    "operator", "question-and-answer", "q&a session",
    "thank you for participating", "conference call",
]
_QUARTER_RE = re.compile(r"Q[1-4]\s+20\d{2}", re.IGNORECASE)

# Companies that file 8-Ks with earnings press releases only — never actual call transcripts.
# EDGAR still has their CIKs, so without this blocklist we'd waste time fetching press-release
# exhibits that pass a loose _is_transcript() check or simply burn the fetch timeout budget.
_NON_TRANSCRIPT_FILERS: frozenset[str] = frozenset({
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
    "NFLX", "JPM", "BAC", "WFC", "C", "GS", "MS", "BRK.A", "BRK.B",
    "JNJ", "PFE", "MRK", "ABBV", "LLY", "AMGN", "GILD", "BIIB",
    "XOM", "CVX", "COP", "SLB",
    "HD", "WMT", "COST", "TGT", "LOW",
    "V", "MA", "PYPL", "AXP",
    "UNH", "CVS", "CI", "HUM",
    "DIS", "CMCSA", "T", "VZ",
    "BA", "LMT", "RTX", "GE", "NOC",
    "INTC", "AMD", "QCOM", "AVGO", "TXN",
    "ORCL", "CRM", "ADBE", "IBM", "INTU",
    "NOW", "SNOW", "PLTR", "UBER", "COIN", "RBLX",
    "SHOP", "SQ", "SPOT", "SNAP", "PINS",
    "BKNG", "ABNB", "LYFT",
    "SPGI", "ICE", "MSCI", "BLK", "SCHW",
    "MCD", "SBUX", "YUM", "NKE", "TJX", "LULU",
    "PG", "KO", "PEP", "PM", "MO",
    "CAT", "DE", "HON", "MMM",
    "AMT", "PLD", "CCI", "EQIX",
    "NEE", "DUK", "SO",
    "LIN", "APD", "ECL",
    "ACN", "ADP", "PAYX",
})

# Module-level CIK cache — populated once per process lifetime
_cik_map: dict[str, str] = {}


async def _load_cik_map(client: httpx.AsyncClient) -> None:
    if _cik_map:
        return
    resp = await client.get(TICKERS_URL, headers=HEADERS, timeout=15.0)
    resp.raise_for_status()
    data = resp.json()
    for entry in data.values():
        ticker = entry.get("ticker", "").upper()
        cik = str(entry.get("cik_str", "")).zfill(10)
        if ticker:
            _cik_map[ticker] = cik


def _is_transcript(text: str) -> bool:
    lower = text.lower()
    return sum(1 for marker in _TRANSCRIPT_MARKERS if marker in lower) >= 2


def _extract_quarter(text: str) -> str | None:
    m = _QUARTER_RE.search(text)
    return m.group(0).upper() if m else None


def _find_exhibit_urls(index_html: str, index_url: str) -> list[str]:
    """Parse the SEC filing index page and return URLs for EX-99.1 / EX-99.2 exhibits."""
    soup = BeautifulSoup(index_html, "html.parser")
    urls: list[str] = []
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        row_text = " ".join(c.get_text(strip=True) for c in cells)
        if not re.search(r"EX-99\.[12]", row_text, re.IGNORECASE):
            continue
        link = row.find("a", href=True)
        if not link:
            continue
        href: str = link["href"]
        url = href if href.startswith("http") else f"https://www.sec.gov{href}"
        urls.append(url)
    return urls


async def fetch_from_edgar(ticker: str) -> TranscriptResult | None:
    if ticker.upper() in _NON_TRANSCRIPT_FILERS:
        logger.info("EDGAR: %s is a known non-transcript-filer — skipping", ticker)
        return None

    async with httpx.AsyncClient(headers=HEADERS, timeout=20.0) as client:
        await _load_cik_map(client)
        cik = _cik_map.get(ticker.upper())
        if not cik:
            logger.warning("EDGAR: no CIK found for %s", ticker)
            return None

        sub_url = f"{EDGAR_BASE}/CIK{cik}.json"
        resp = await client.get(sub_url)
        resp.raise_for_status()
        submissions = resp.json()

        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])

        cutoff = (datetime.utcnow() - timedelta(days=120)).date()

        candidates: list[tuple[str, str, date]] = []
        for form, acc, fd, _doc in zip(forms, accessions, filing_dates, primary_docs):
            if form != "8-K":
                continue
            try:
                fdate = date.fromisoformat(fd)
            except ValueError:
                continue
            if fdate < cutoff:
                break  # filings are newest-first; stop when outside window
            candidates.append((acc, fd, fdate))

        for acc_no, _fd, fdate in candidates:
            acc_nodashes = acc_no.replace("-", "")
            index_url = f"{ARCHIVES_BASE}/{int(cik)}/{acc_nodashes}/"
            try:
                idx_resp = await client.get(index_url)
                idx_resp.raise_for_status()
            except httpx.HTTPError:
                continue

            for exhibit_url in _find_exhibit_urls(idx_resp.text, index_url):
                try:
                    ex_resp = await client.get(exhibit_url)
                    ex_resp.raise_for_status()
                    text = ex_resp.text
                except httpx.HTTPError:
                    continue

                if not _is_transcript(text):
                    continue

                return TranscriptResult(
                    ticker=ticker,
                    text=text,
                    source="edgar",
                    quarter=_extract_quarter(text),
                    report_date=fdate,
                )

    return None
