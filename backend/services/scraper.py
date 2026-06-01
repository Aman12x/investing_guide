import asyncio
import logging
import os
import re
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup

from services.transcript import TranscriptResult

logger = logging.getLogger(__name__)

POLITENESS_DELAY = float(os.getenv("SCRAPER_DELAY_MS", "1500")) / 1000
_SEARCH_URL = "https://www.fool.com/search/solr.aspx"
_BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_TRANSCRIPT_MARKERS = ["operator", "question-and-answer", "earnings call transcript"]
_QUARTER_RE = re.compile(r"Q[1-4]\s+20\d{2}", re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{4})/(\d{2})/(\d{2})")


def _is_transcript(text: str) -> bool:
    lower = text.lower()
    return any(m in lower for m in _TRANSCRIPT_MARKERS)


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
    async with httpx.AsyncClient(headers=_BASE_HEADERS, timeout=20.0, follow_redirects=True) as client:
        params = {
            "q": f"{ticker.lower()} earnings call transcript",
            "source": "eptsbts",
            "d": "Article",
        }
        try:
            search_resp = await client.get(_SEARCH_URL, params=params)
            search_resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Motley Fool search failed for %s: %s", ticker, exc)
            return None

        soup = BeautifulSoup(search_resp.text, "html.parser")
        links = soup.select("a[href*='earnings-call-transcript']")

        if not links:
            return None

        for link in links[:4]:
            href = link.get("href", "")
            if not href:
                continue
            url = href if href.startswith("http") else f"https://www.fool.com{href}"

            if ticker.lower() not in url.lower():
                continue

            await asyncio.sleep(POLITENESS_DELAY)
            try:
                page_resp = await client.get(url)
                page_resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("Motley Fool page fetch failed for %s (%s): %s", ticker, url, exc)
                continue

            page_soup = BeautifulSoup(page_resp.text, "html.parser")
            article = page_soup.select_one("article") or page_soup.select_one("[class*='article-body']") or page_soup.select_one("main")
            if not article:
                continue

            # Strip nav/ads/scripts
            for tag in article.select("script, style, nav, aside, .ad, .advertisement"):
                tag.decompose()

            text = article.get_text(separator="\n")

            if not _is_transcript(text):
                continue

            return TranscriptResult(
                ticker=ticker,
                text=text,
                source="motley_fool",
                quarter=_extract_quarter(text),
                report_date=_extract_date_from_url(url),
            )

    return None
