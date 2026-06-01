import logging
from dataclasses import dataclass
from datetime import date

from exceptions import TranscriptNotFoundError
from services.edgar import fetch_from_edgar
from services.scraper import fetch_from_motley_fool

logger = logging.getLogger(__name__)

_MIN_LENGTH = 2000


@dataclass
class TranscriptResult:
    ticker: str
    text: str
    source: str            # "edgar" | "motley_fool"
    quarter: str | None
    report_date: date | None


async def fetch_transcript(ticker: str) -> TranscriptResult:
    """Try EDGAR first, fall back to Motley Fool. Raises TranscriptNotFoundError if all fail."""
    for source_fn in [fetch_from_edgar, fetch_from_motley_fool]:
        try:
            result = await source_fn(ticker)
            if result and len(result.text) >= _MIN_LENGTH:
                logger.info("Transcript for %s fetched from %s (%d chars)", ticker, result.source, len(result.text))
                return result
        except Exception as exc:
            logger.warning("Source %s failed for %s: %s", source_fn.__name__, ticker, exc)
            continue

    raise TranscriptNotFoundError(ticker)
