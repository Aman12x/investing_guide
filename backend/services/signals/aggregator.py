import asyncio
import logging
from dataclasses import dataclass

from services.signals.analysts import AnalystSignal, fetch_analyst_ratings
from services.signals.news import NewsSignal, fetch_news_sentiment
from services.signals.reddit import RedditSignal, fetch_reddit_sentiment

logger = logging.getLogger(__name__)

_SIGNAL_WEIGHTS = {
    "transcript": 0.40,
    "news": 0.25,
    "analysts": 0.25,
    "reddit": 0.10,
}

_HIGH_RETAIL_TICKERS = {"GME", "AMC", "TSLA", "MSTR", "RIVN"}


@dataclass
class ExternalContext:
    reddit: RedditSignal | None
    news: NewsSignal | None
    analysts: AnalystSignal | None


def effective_weights(ticker: str, context: ExternalContext) -> dict[str, float]:
    """Redistribute weight from missing sources proportionally across available ones."""
    base = dict(_SIGNAL_WEIGHTS)

    # Boost reddit for high-retail-interest tickers
    if ticker.upper() in _HIGH_RETAIL_TICKERS:
        base["reddit"] = 0.20
        scale = sum(base.values())
        base = {k: v / scale for k, v in base.items()}

    available = {
        "transcript": True,
        "news": context.news is not None,
        "analysts": context.analysts is not None,
        "reddit": context.reddit is not None,
    }

    active_total = sum(base[k] for k, v in available.items() if v)
    if active_total == 0:
        active_total = 1.0  # guard

    return {k: (base[k] / active_total if available[k] else 0.0) for k in base}


def format_external_context(ticker: str, context: ExternalContext) -> str:
    """Produce the structured text block sent to Claude alongside the transcript."""
    weights = effective_weights(ticker, context)
    lines: list[str] = []

    lines.append("=== EXTERNAL SIGNALS ===")
    lines.append("Effective source weights (adjusted for available data):")
    for source, w in weights.items():
        lines.append(f"  {source}: {w:.0%}")
    lines.append("")

    if context.news:
        n = context.news
        lines.append(f"NEWS HEADLINES ({len(n.headlines)} articles, sources: {', '.join(n.sources) or 'RSS'}):")
        for h in n.headlines:
            lines.append(f"  • {h}")
        lines.append(f"  Pre-computed signal: {n.raw_signal}")
        lines.append("")

    if context.analysts:
        a = context.analysts
        total = a.buy + a.strong_buy + a.hold + a.sell + a.strong_sell
        lines.append(f"ANALYST CONSENSUS (Finnhub, period: {a.period}, n={total}):")
        lines.append(f"  Strong Buy: {a.strong_buy}  Buy: {a.buy}  Hold: {a.hold}  Sell: {a.sell}  Strong Sell: {a.strong_sell}")
        lines.append(f"  Pre-computed signal: {a.raw_signal}")
        lines.append("")

    if context.reddit:
        r = context.reddit
        lines.append(f"REDDIT RETAIL SENTIMENT ({r.post_count} posts, B:{r.bullish_count} / Bear:{r.bearish_count}):")
        for title in r.top_titles:
            lines.append(f"  • {title}")
        lines.append(f"  Pre-computed signal: {r.raw_signal}")
        if ticker.upper() in _HIGH_RETAIL_TICKERS:
            lines.append("  NOTE: Reddit weight boosted to 20% — high-retail-interest ticker.")
        lines.append("")

    if not context.news and not context.analysts and not context.reddit:
        lines.append("(No external signals available — base report on transcript only. Calibrate signalConfidence solely on transcript quality per the calibration rules in the system prompt.)")

    return "\n".join(lines)


async def fetch_external_context(ticker: str) -> ExternalContext:
    """Fetch all three signal sources concurrently with individual 5s timeouts."""
    results = await asyncio.gather(
        asyncio.wait_for(fetch_reddit_sentiment(ticker), timeout=5.0),
        asyncio.wait_for(fetch_news_sentiment(ticker), timeout=5.0),
        asyncio.wait_for(fetch_analyst_ratings(ticker), timeout=5.0),
        return_exceptions=True,
    )

    def _extract(r, name: str):
        if isinstance(r, Exception):
            logger.warning("Signal source %s failed or timed out for %s: %s", name, ticker, r)
            return None
        return r

    reddit, news, analysts = (
        _extract(results[0], "reddit"),
        _extract(results[1], "news"),
        _extract(results[2], "analysts"),
    )
    return ExternalContext(reddit=reddit, news=news, analysts=analysts)
