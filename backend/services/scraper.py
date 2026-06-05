import logging
import re
from datetime import date

import httpx
from bs4 import BeautifulSoup

from services.models import TranscriptResult

logger = logging.getLogger(__name__)

_SA_BASE = "https://stockanalysis.com"
_QUARTER_RE = re.compile(r"Q[1-4]\s+20\d{2}", re.IGNORECASE)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _extract_quarter(text: str) -> str | None:
    m = _QUARTER_RE.search(text)
    return m.group(0).upper() if m else None


async def fetch_from_motley_fool(ticker: str) -> TranscriptResult | None:
    """Third-tier fallback: StockAnalysis.com two-hop scraper. No API key required."""
    t = ticker.lower()
    listing_url = f"{_SA_BASE}/stocks/{t}/transcripts/"

    async with httpx.AsyncClient(headers=_HEADERS, timeout=15.0, follow_redirects=True) as client:
        # Hop 1: listing page → find first transcript slug
        try:
            resp = await client.get(listing_url)
            if resp.status_code in (403, 404, 429):
                return None
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("StockAnalysis listing failed for %s: %s", ticker, exc)
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        prefix = f"/stocks/{t}/transcripts/"
        links = [
            a["href"] for a in soup.find_all("a", href=True)
            if a["href"].startswith(prefix) and a["href"].rstrip("/") != prefix.rstrip("/")
        ]
        if not links:
            logger.info("StockAnalysis: no transcript links found for %s", ticker)
            return None

        detail_url = _SA_BASE + links[0]

        # Hop 2: detail page → extract transcript text
        try:
            resp = await client.get(detail_url)
            if resp.status_code in (403, 404, 429):
                return None
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("StockAnalysis detail failed for %s: %s", ticker, exc)
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        container = (
            soup.find("div", class_=lambda c: c and "transcript" in c.lower())
            or soup.find("article")
            or soup.find("main")
        )
        text = container.get_text(separator="\n", strip=True) if container else ""

        if len(text) < 2000:
            logger.info("StockAnalysis: transcript too short for %s (%d chars)", ticker, len(text))
            return None

        report_date: date | None = None
        time_tag = soup.find("time", attrs={"datetime": True})
        if time_tag:
            try:
                report_date = date.fromisoformat(str(time_tag["datetime"])[:10])
            except ValueError:
                pass

        logger.info("StockAnalysis: fetched transcript for %s (%d chars)", ticker, len(text))
        return TranscriptResult(
            ticker=ticker,
            text=text,
            source="stockanalysis",
            quarter=_extract_quarter(text),
            report_date=report_date,
        )
