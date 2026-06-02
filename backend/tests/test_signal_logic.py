"""Layer 2 — Signal weight redistribution tests. Pure Python, no network calls.

Signal adjudication rules (Reddit never flips signal, signalChanged logic, etc.) live
entirely inside the Claude prompt in services/analyst.py and are therefore tested as
LLM output assertions in test_llm_quality.py (Layer 4).
"""
from unittest.mock import MagicMock

import pytest

from services.signals.aggregator import (
    ExternalContext,
    _HIGH_RETAIL_TICKERS,
    _SIGNAL_WEIGHTS,
    effective_weights,
    format_external_context,
)
from services.signals.analysts import AnalystSignal
from services.signals.news import NewsSignal
from services.signals.reddit import RedditSignal


def _make_reddit() -> RedditSignal:
    return RedditSignal(
        ticker="AAPL",
        post_count=50,
        bullish_count=30,
        bearish_count=10,
        top_titles=["Apple beats estimates", "AAPL momentum strong"],
        raw_signal="BULLISH",
    )


def _make_news() -> NewsSignal:
    return NewsSignal(
        ticker="AAPL",
        headlines=["Apple reports record revenue", "iPhone sales surge"],
        raw_signal="BUY",
        sources=["Reuters", "CNBC"],
    )


def _make_analysts() -> AnalystSignal:
    return AnalystSignal(
        ticker="AAPL",
        buy=20,
        hold=5,
        sell=2,
        strong_buy=15,
        strong_sell=1,
        raw_signal="BUY",
        period="2025-01",
    )


class TestEffectiveWeights:
    def test_all_sources_present_weights_sum_to_one(self):
        ctx = ExternalContext(reddit=_make_reddit(), news=_make_news(), analysts=_make_analysts())
        weights = effective_weights("AAPL", ctx)
        assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_all_sources_present_match_base_weights(self):
        ctx = ExternalContext(reddit=_make_reddit(), news=_make_news(), analysts=_make_analysts())
        weights = effective_weights("AAPL", ctx)
        assert weights["transcript"] == pytest.approx(_SIGNAL_WEIGHTS["transcript"])
        assert weights["news"] == pytest.approx(_SIGNAL_WEIGHTS["news"])
        assert weights["analysts"] == pytest.approx(_SIGNAL_WEIGHTS["analysts"])
        assert weights["reddit"] == pytest.approx(_SIGNAL_WEIGHTS["reddit"])

    def test_reddit_none_weights_sum_to_one(self):
        ctx = ExternalContext(reddit=None, news=_make_news(), analysts=_make_analysts())
        weights = effective_weights("AAPL", ctx)
        assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_reddit_none_transcript_still_largest(self):
        ctx = ExternalContext(reddit=None, news=_make_news(), analysts=_make_analysts())
        weights = effective_weights("AAPL", ctx)
        assert weights["transcript"] > weights["news"]
        assert weights["transcript"] > weights["analysts"]
        assert weights["reddit"] == 0.0

    def test_news_and_reddit_none_weights_sum_to_one(self):
        ctx = ExternalContext(reddit=None, news=None, analysts=_make_analysts())
        weights = effective_weights("AAPL", ctx)
        assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_news_and_reddit_none_only_transcript_and_analysts(self):
        ctx = ExternalContext(reddit=None, news=None, analysts=_make_analysts())
        weights = effective_weights("AAPL", ctx)
        assert weights["news"] == 0.0
        assert weights["reddit"] == 0.0
        assert weights["transcript"] > 0.0
        assert weights["analysts"] > 0.0

    def test_all_external_none_transcript_weight_is_one(self):
        ctx = ExternalContext(reddit=None, news=None, analysts=None)
        weights = effective_weights("AAPL", ctx)
        assert weights["transcript"] == pytest.approx(1.0)
        assert weights["news"] == 0.0
        assert weights["analysts"] == 0.0
        assert weights["reddit"] == 0.0

    def test_high_retail_ticker_reddit_weight_boosted(self):
        for ticker in _HIGH_RETAIL_TICKERS:
            ctx = ExternalContext(reddit=_make_reddit(), news=_make_news(), analysts=_make_analysts())
            weights = effective_weights(ticker, ctx)
            assert weights["reddit"] > _SIGNAL_WEIGHTS["reddit"], (
                f"{ticker}: expected boosted reddit weight > {_SIGNAL_WEIGHTS['reddit']}, got {weights['reddit']}"
            )
            assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_non_retail_ticker_reddit_weight_not_boosted(self):
        ctx = ExternalContext(reddit=_make_reddit(), news=_make_news(), analysts=_make_analysts())
        weights = effective_weights("MSFT", ctx)
        assert weights["reddit"] == pytest.approx(_SIGNAL_WEIGHTS["reddit"])


class TestFormatExternalContext:
    def test_all_none_emits_no_signals_message(self):
        ctx = ExternalContext(reddit=None, news=None, analysts=None)
        text = format_external_context("AAPL", ctx)
        assert "No external signals available" in text

    def test_all_sources_present_emits_all_sections(self):
        ctx = ExternalContext(reddit=_make_reddit(), news=_make_news(), analysts=_make_analysts())
        text = format_external_context("AAPL", ctx)
        assert "NEWS HEADLINES" in text
        assert "ANALYST CONSENSUS" in text
        assert "REDDIT RETAIL SENTIMENT" in text

    def test_news_only_emits_only_news_section(self):
        ctx = ExternalContext(reddit=None, news=_make_news(), analysts=None)
        text = format_external_context("AAPL", ctx)
        assert "NEWS HEADLINES" in text
        assert "ANALYST CONSENSUS" not in text
        assert "REDDIT RETAIL SENTIMENT" not in text

    def test_high_retail_ticker_note_appears(self):
        ctx = ExternalContext(reddit=_make_reddit(), news=None, analysts=None)
        text = format_external_context("GME", ctx)
        assert "Reddit weight boosted" in text or "high-retail-interest" in text

    def test_weights_section_always_present(self):
        ctx = ExternalContext(reddit=None, news=None, analysts=None)
        text = format_external_context("AAPL", ctx)
        assert "Effective source weights" in text
