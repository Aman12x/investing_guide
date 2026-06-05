import logging
import re
from datetime import date

import httpx
from bs4 import BeautifulSoup

from services.models import TranscriptResult

logger = logging.getLogger(__name__)

_SA_BASE = "https://stockanalysis.com"
_QUARTER_RE = re.compile(r"Q[1-4]\s+20\d{2}", re.IGNORECASE)
# Matches quarterly earnings call slugs like q1-2026, q4-2025
_EARNINGS_SLUG_RE = re.compile(r"-q[1-4]-\d{4}", re.IGNORECASE)

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
        # Deduplicate while preserving order (each link appears twice in the HTML)
        seen: set[str] = set()
        all_links: list[str] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith(prefix) and href.rstrip("/") != prefix.rstrip("/") and href not in seen:
                seen.add(href)
                all_links.append(href)

        if not all_links:
            logger.info("StockAnalysis: no transcript links found for %s", ticker)
            return None

        # Prefer quarterly earnings calls (q1-2026, q4-2025, etc.) over AGMs and conferences
        earnings_links = [l for l in all_links if _EARNINGS_SLUG_RE.search(l)]
        ordered_links = earnings_links + [l for l in all_links if l not in earnings_links]

        # Hop 2: try links in order until we get usable transcript text
        for slug in ordered_links[:4]:
            detail_url = _SA_BASE + slug
            try:
                resp = await client.get(detail_url)
                if resp.status_code in (403, 404, 429):
                    continue
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("StockAnalysis detail failed for %s (%s): %s", ticker, slug, exc)
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            container = (
                soup.find("div", class_=lambda c: c and "space-y-6" in c and "text-base" in c)
                or soup.find("div", class_=lambda c: c and "transcript" in c.lower())
                or soup.find("article")
                or soup.find("main")
            )
            text = container.get_text(separator="\n", strip=True) if container else ""

            if len(text) < 2000:
                logger.info("StockAnalysis: transcript too short for %s on %s (%d chars)", ticker, slug, len(text))
                continue

            report_date: date | None = None
            time_tag = soup.find("time", attrs={"datetime": True})
            if time_tag:
                try:
                    report_date = date.fromisoformat(str(time_tag["datetime"])[:10])
                except ValueError:
                    pass

            logger.info("StockAnalysis: fetched transcript for %s from %s (%d chars)", ticker, slug, len(text))
            return TranscriptResult(
                ticker=ticker,
                text=text,
                source="stockanalysis",
                quarter=_extract_quarter(text),
                report_date=report_date,
            )

        logger.info("StockAnalysis: no usable transcript found for %s after trying %d links", ticker, min(len(ordered_links), 4))
        return None
