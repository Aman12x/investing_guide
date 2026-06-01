import logging
import os
from dataclasses import dataclass

import httpx

from exceptions import RedditError

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_SEARCH_URL = "https://oauth.reddit.com/r/{sub}/search"
_SUBREDDITS = ["investing", "stocks", "wallstreetbets"]
_LOOKBACK = "week"
_MIN_SCORE = 10
_LIMIT = 25


@dataclass
class RedditSignal:
    ticker: str
    post_count: int
    bullish_count: int
    bearish_count: int
    top_titles: list[str]
    raw_signal: str   # "BULLISH" | "BEARISH" | "MIXED"


_BULLISH_WORDS = {"bull", "bullish", "buy", "long", "moon", "rocket", "calls", "up", "beat", "strong"}
_BEARISH_WORDS = {"bear", "bearish", "sell", "short", "puts", "down", "miss", "weak", "dump", "crash"}


def _score_title(title: str) -> int:
    lower = title.lower()
    bull = sum(1 for w in _BULLISH_WORDS if w in lower)
    bear = sum(1 for w in _BEARISH_WORDS if w in lower)
    return bull - bear


async def _get_token(client: httpx.AsyncClient, client_id: str, secret: str) -> str:
    resp = await client.post(
        _TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(client_id, secret),
        headers={"User-Agent": "EarningsLens/1.0"},
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


async def fetch_reddit_sentiment(ticker: str) -> RedditSignal | None:
    client_id = os.getenv("REDDIT_CLIENT_ID")
    secret = os.getenv("REDDIT_CLIENT_SECRET")
    if not client_id or not secret:
        logger.info("Reddit credentials not set — skipping")
        return None

    try:
        async with httpx.AsyncClient() as client:
            token = await _get_token(client, client_id, secret)
            headers = {"Authorization": f"bearer {token}", "User-Agent": "EarningsLens/1.0"}

            all_posts: list[dict] = []
            for sub in _SUBREDDITS:
                url = _SEARCH_URL.format(sub=sub)
                resp = await client.get(
                    url,
                    params={"q": ticker, "sort": "top", "t": _LOOKBACK, "limit": _LIMIT, "restrict_sr": "true"},
                    headers=headers,
                    timeout=10.0,
                )
                if resp.status_code != 200:
                    continue
                posts = resp.json().get("data", {}).get("children", [])
                for p in posts:
                    d = p.get("data", {})
                    if d.get("score", 0) >= _MIN_SCORE:
                        all_posts.append(d)

            if not all_posts:
                return None

            all_posts.sort(key=lambda p: p.get("score", 0), reverse=True)
            top_titles = [p["title"] for p in all_posts[:5]]

            scores = [_score_title(p["title"]) for p in all_posts]
            total = sum(1 for s in scores if s > 0) + sum(1 for s in scores if s < 0)
            bullish = sum(1 for s in scores if s > 0)
            bearish = sum(1 for s in scores if s < 0)

            if total == 0:
                raw_signal = "MIXED"
            elif bullish / max(total, 1) > 0.6:
                raw_signal = "BULLISH"
            elif bearish / max(total, 1) > 0.6:
                raw_signal = "BEARISH"
            else:
                raw_signal = "MIXED"

            return RedditSignal(
                ticker=ticker,
                post_count=len(all_posts),
                bullish_count=bullish,
                bearish_count=bearish,
                top_titles=top_titles,
                raw_signal=raw_signal,
            )
    except httpx.HTTPError as exc:
        raise RedditError(f"Reddit fetch failed for {ticker}: {exc}") from exc
