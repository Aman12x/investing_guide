import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta

import feedparser
import httpx

from exceptions import NewsError

logger = logging.getLogger(__name__)

_NEWSAPI_URL = "https://newsapi.org/v2/everything"
_RSS_FEEDS = [
    ("Reuters", "https://feeds.reuters.com/reuters/businessNews"),
    ("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664"),
]


@dataclass
class NewsSignal:
    ticker: str
    headlines: list[str]
    raw_signal: str   # "BUY" | "HOLD" | "WATCH" | "MIXED"
    sources: list[str]


_POSITIVE_WORDS = {"beat", "strong", "growth", "record", "raised", "exceeded", "positive", "bullish", "surge", "gain"}
_NEGATIVE_WORDS = {"miss", "missed", "weak", "cut", "lower", "decline", "loss", "disappointing", "bearish", "warning"}


def _infer_signal(headlines: list[str]) -> str:
    pos = neg = 0
    for h in headlines:
        lower = h.lower()
        pos += sum(1 for w in _POSITIVE_WORDS if w in lower)
        neg += sum(1 for w in _NEGATIVE_WORDS if w in lower)
    total = pos + neg
    if total == 0:
        return "MIXED"
    ratio = pos / total
    if ratio > 0.65:
        return "BUY"
    if ratio < 0.35:
        return "WATCH"
    return "MIXED"


async def fetch_news_sentiment(ticker: str) -> NewsSignal | None:
    api_key = os.getenv("NEWSAPI_KEY")
    headlines: list[str] = []
    sources: list[str] = []

    if api_key:
        try:
            from_date = (datetime.utcnow() - timedelta(days=14)).strftime("%Y-%m-%d")
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    _NEWSAPI_URL,
                    params={
                        "q": f"{ticker} earnings",
                        "sources": "reuters,cnbc,marketwatch,bloomberg",
                        "from": from_date,
                        "sortBy": "relevancy",
                        "pageSize": 10,
                        "apiKey": api_key,
                    },
                )
                if resp.status_code == 200:
                    articles = resp.json().get("articles", [])
                    headlines = [a["title"] for a in articles if a.get("title")][:10]
                    sources = list({a.get("source", {}).get("name", "") for a in articles if a.get("source")})
        except httpx.HTTPError as exc:
            logger.warning("NewsAPI failed for %s: %s", ticker, exc)

    if not headlines:
        # RSS fallback
        for source_name, feed_url in _RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:20]:
                    title = entry.get("title", "")
                    if ticker.lower() in title.lower():
                        headlines.append(title)
                if headlines:
                    sources.append(source_name)
            except Exception as exc:
                logger.warning("RSS feed %s failed: %s", source_name, exc)

    if not headlines:
        return None

    try:
        return NewsSignal(
            ticker=ticker,
            headlines=headlines[:10],
            raw_signal=_infer_signal(headlines),
            sources=sources,
        )
    except Exception as exc:
        raise NewsError(f"News signal failed for {ticker}: {exc}") from exc
