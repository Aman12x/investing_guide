import asyncio
import logging
import os
import re
from datetime import date, datetime, timedelta

import httpx

from services.transcript import TranscriptResult

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
    return any(marker in lower for marker in _TRANSCRIPT_MARKERS)


def _extract_quarter(text: str) -> str | None:
    m = _QUARTER_RE.search(text)
    return m.group(0).upper() if m else None


async def fetch_from_edgar(ticker: str) -> TranscriptResult | None:
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

            # Look for exhibit 99.1 / 99.2 links in the index page
            for exhibit in ["99-1", "99-2", "99.1", "99.2"]:
                href_match = re.search(
                    rf'href="([^"]*{re.escape(exhibit)}[^"]*\.(?:htm|txt))"',
                    idx_resp.text,
                    re.IGNORECASE,
                )
                if not href_match:
                    continue
                exhibit_path = href_match.group(1)
                exhibit_url = f"https://www.sec.gov{exhibit_path}" if exhibit_path.startswith("/") else f"{index_url}{exhibit_path}"
                try:
                    ex_resp = await client.get(exhibit_url)
                    ex_resp.raise_for_status()
                    text = ex_resp.text
                except httpx.HTTPError:
                    continue

                if not _is_transcript(text):
                    continue

                quarter = _extract_quarter(text)
                return TranscriptResult(
                    ticker=ticker,
                    text=text,
                    source="edgar",
                    quarter=quarter,
                    report_date=fdate,
                )

    return None
