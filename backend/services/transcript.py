import logging

from exceptions import TranscriptNotFoundError
from services.edgar import fetch_from_edgar
from services.fmp_transcript import fetch_from_fmp
from services.models import TranscriptResult
from services.scraper import fetch_from_motley_fool

logger = logging.getLogger(__name__)

_MIN_LENGTH = 2000


async def fetch_transcript(ticker: str) -> TranscriptResult:
    """Waterfall: EDGAR → FMP → scraper. Raises TranscriptNotFoundError if all fail."""
    for source_fn in [fetch_from_edgar, fetch_from_fmp, fetch_from_motley_fool]:
        try:
            result = await source_fn(ticker)
            if result and len(result.text) >= _MIN_LENGTH:
                logger.info("Transcript for %s fetched from %s (%d chars)", ticker, result.source, len(result.text))
                return result
        except Exception as exc:
            logger.warning("Source %s failed for %s: %s", source_fn.__name__, ticker, exc)
            continue

    raise TranscriptNotFoundError(ticker)
