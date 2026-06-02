import asyncio
import logging
import os
import re
from datetime import date

import httpx
from bs4 import BeautifulSoup

from services.models import TranscriptResult

logger = logging.getLogger(__name__)

POLITENESS_DELAY = float(os.getenv("SCRAPER_DELAY_MS", "1500")) / 1000
_BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_TRANSCRIPT_MARKERS = ["operator", "question-and-answer", "earnings call transcript", "conference call"]
_QUARTER_RE = re.compile(r"Q[1-4]\s*(?:FY)?\s*20\d{2}", re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{4})[/-](\d{2})[/-](\d{2})")


def _is_transcript(text: str) -> bool:
    lower = text.lower()
    return sum(1 for m in _TRANSCRIPT_MARKERS if m in lower) >= 2


def _extract_quarter(text: str) -> str | None:
    m = _QUARTER_RE.search(text)
    return m.group(0).upper() if m else None


def _extract_date_from_url(url: str) -> date | None:
    m = _DATE_RE.search(url)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


async def fetch_from_motley_fool(ticker: str) -> TranscriptResult | None:
    """Try stockanalysis.com — Motley Fool's transcript endpoints are no longer available."""
    return await _fetch_from_stockanalysis(ticker)


async def _fetch_from_stockanalysis(ticker: str) -> TranscriptResult | None:
    listing_url = f"https://stockanalysis.com/stocks/{ticker.lower()}/transcripts/"
    async with httpx.AsyncClient(headers=_BASE_HEADERS, timeout=20.0, follow_redirects=True) as client:
        try:
            listing_resp = await client.get(listing_url)
            listing_resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("StockAnalysis listing failed for %s: %s", ticker, exc)
            return None

        soup = BeautifulSoup(listing_resp.text, "html.parser")
        transcript_url = _find_first_transcript_link(soup, ticker)
        if not transcript_url:
            logger.info("StockAnalysis: no transcript link found for %s", ticker)
            return None

        await asyncio.sleep(POLITENESS_DELAY)
        try:
            page_resp = await client.get(transcript_url)
            page_resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("StockAnalysis page fetch failed for %s (%s): %s", ticker, transcript_url, exc)
            return None

        page_soup = BeautifulSoup(page_resp.text, "html.parser")
        text = _extract_text(page_soup)
        if not text or not _is_transcript(text):
            logger.info("StockAnalysis: content for %s did not pass transcript check", ticker)
            return None

        return TranscriptResult(
            ticker=ticker,
            text=text,
            source="stockanalysis",
            quarter=_extract_quarter(text),
            report_date=_extract_date_from_url(transcript_url),
        )


def _find_first_transcript_link(soup: BeautifulSoup, ticker: str) -> str | None:
    ticker_lower = ticker.lower()
    patterns = [
        f"/stocks/{ticker_lower}/transcripts/",
        f"/{ticker_lower}/transcripts/",
        "transcripts",
    ]
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        # Must be a sub-page of the listing (not the listing itself)
        if any(p in href.lower() for p in patterns[:2]):
            full = href if href.startswith("http") else f"https://stockanalysis.com{href}"
            # Skip the listing page itself
            if full.rstrip("/") != f"https://stockanalysis.com/stocks/{ticker_lower}/transcripts":
                return full
    return None


def _extract_text(soup: BeautifulSoup) -> str | None:
    for tag in soup.select("script, style, nav, aside, header, footer, .ad"):
        tag.decompose()
    content = (
        soup.select_one("main article")
        or soup.select_one("main")
        or soup.select_one("article")
        or soup.select_one("[class*='transcript']")
        or soup.select_one("[class*='content']")
    )
    if not content:
        return None
    return content.get_text(separator="\n").strip()
