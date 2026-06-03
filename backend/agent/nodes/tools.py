import asyncio
import logging

from services.signals.analysts import fetch_analyst_ratings
from services.signals.news import fetch_news_sentiment
from services.signals.reddit import fetch_reddit_sentiment
from services.transcript import fetch_transcript

from agent.state import AgentState

logger = logging.getLogger(__name__)

# Transcript fetch runs a multi-hop waterfall (EDGAR → FMP → AV); needs its own longer timeout.
_TRANSCRIPT_TIMEOUT = 30.0
_SIGNAL_TIMEOUT = 5.0


async def _safe(coro, name: str, ticker: str, timeout: float = _SIGNAL_TIMEOUT):
    """Run coro with timeout; return None and log on any failure."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Tool %s timed out for %s", name, ticker)
        return None
    except Exception as exc:
        logger.warning("Tool %s failed for %s: %s", name, ticker, exc)
        return None


async def fetch_transcript_tool(ticker: str):
    return await _safe(fetch_transcript(ticker), "fetch_transcript", ticker, timeout=_TRANSCRIPT_TIMEOUT)


async def fetch_reddit_tool(ticker: str):
    return await _safe(fetch_reddit_sentiment(ticker), "fetch_reddit", ticker)


async def fetch_news_tool(ticker: str):
    return await _safe(fetch_news_sentiment(ticker), "fetch_news", ticker)


async def fetch_analyst_tool(ticker: str):
    return await _safe(fetch_analyst_ratings(ticker), "fetch_analyst", ticker)


async def fetch_market_tool(ticker: str):
    # services.signals.market is not yet implemented — returns None gracefully
    logger.info("Market context tool not yet implemented — skipping for %s", ticker)
    return None


async def fetch_prior_quarter_tool(ticker: str):
    # Best-effort: underlying services always return the most recent transcript.
    # True prior-quarter offset requires service-level support (e.g. FMP limit=2).
    logger.info("Fetching prior quarter transcript for %s (best-effort)", ticker)
    return await _safe(fetch_transcript(ticker), "fetch_prior_quarter", ticker)


async def fetch_competitor_tool(competitor_ticker: str):
    return await _safe(
        fetch_transcript(competitor_ticker), "fetch_competitor", competitor_ticker
    )


async def fetch_node(state: AgentState) -> dict:
    """Run all tools concurrently per the planner's priority list."""
    plan = state.plan if hasattr(state, "plan") else {}
    ticker = state.ticker if hasattr(state, "ticker") else state.get("ticker", "")
    errors = list(state.errors if hasattr(state, "errors") else state.get("errors", []))
    iterations = state.iterations if hasattr(state, "iterations") else state.get("iterations", 0)

    fetch_prior = plan.get("fetch_prior_quarter", False)
    fetch_competitor = plan.get("fetch_competitor", False)
    competitor_ticker = plan.get("competitor_ticker")

    optional_coros: list[tuple[str, object]] = []
    if fetch_prior:
        optional_coros.append(("prior_quarter", fetch_prior_quarter_tool(ticker)))
    if fetch_competitor and competitor_ticker:
        optional_coros.append(("competitor", fetch_competitor_tool(competitor_ticker)))

    results = await asyncio.gather(
        fetch_transcript_tool(ticker),
        fetch_reddit_tool(ticker),
        fetch_news_tool(ticker),
        fetch_analyst_tool(ticker),
        fetch_market_tool(ticker),
        *[coro for _, coro in optional_coros],
        return_exceptions=True,
    )

    def _unwrap(r):
        return None if isinstance(r, Exception) else r

    transcript = _unwrap(results[0])
    reddit = _unwrap(results[1])
    news = _unwrap(results[2])
    analysts = _unwrap(results[3])
    # market (results[4]) — not wired to ExternalContext yet

    signals: dict = {"reddit": reddit, "news": news, "analysts": analysts}
    for i, (name, _) in enumerate(optional_coros):
        signals[name] = _unwrap(results[5 + i])

    if transcript is None:
        errors.append(f"fetch_node iteration {iterations + 1}: transcript unavailable")

    return {
        "transcript": transcript,
        "signals": signals,
        "errors": errors,
        "iterations": iterations + 1,
    }
