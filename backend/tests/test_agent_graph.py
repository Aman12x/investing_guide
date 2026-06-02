"""Layer 5 — Agent graph wiring tests. Mocks Claude and service I/O; real node logic runs."""
import asyncio
import copy
import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.graph import build_graph
from agent.nodes.formatter import FormatterError
from agent.state import AgentState
from exceptions import ClaudeError
from services.models import TranscriptResult


def _initial_state(ticker: str = "AAPL") -> AgentState:
    return AgentState(
        ticker=ticker,
        user_intent="full analysis",
        plan={},
        transcript=None,
        signals={},
        draft_report={},
        final_report={},
        reflection_notes="",
    )


def _valid_report_dict(signal: str = "HOLD") -> dict:
    return {
        "company": "Apple Inc",
        "ticker": "AAPL",
        "quarter": "Q1 2025",
        "reportDate": "January 30, 2025",
        "signal": signal,
        "signalRationale": "Solid beat across all segments with raised guidance.",
        "signalConfidence": 75,
        "signalChanged": False,
        "sourceSignals": {
            "transcript": signal,
            "news": None,
            "analysts": None,
            "reddit": None,
        },
        "contradictions": [],
        "metrics": {
            "revenue": {"value": "$124.3b", "delta": "+4% YoY", "beat": True},
            "eps": {"value": "$2.18", "delta": "+8% YoY", "beat": True},
            "operatingMargin": {"value": "31%", "delta": "+50bps YoY", "beat": True},
            "guidance": {"value": "$500b full-year", "delta": "raised $10b", "beat": True},
        },
        "executiveSummary": (
            "Apple delivered a solid Q1 beat. Services growth continued to accelerate. "
            "iPhone demand remained resilient. Management raised full-year guidance."
        ),
        "keyHighlights": [
            "Services revenue grew 14% YoY to $26.3b",
            "iPhone revenue flat YoY but beat consensus by $2b",
            "Mac and iPad both delivered double-digit growth",
            "Gross margin expanded 50bps to 46.5%",
            "Share buyback program expanded by $90b",
        ],
        "watchlist": [
            "China iPhone demand trajectory in Q2",
            "Services margin as content costs rise",
            "Vision Pro adoption curves",
        ],
        "risks": [
            {"text": "China regulatory and demand risk remains elevated", "level": "high"},
            {"text": "FX headwinds from strong dollar", "level": "med"},
        ],
        "sentiment": {
            "overall": 72,
            "ceoConfidence": 78,
            "forwardLooking": 74,
            "caution": 30,
        },
        "managementTone": {
            "openingTone": "Confident, emphasised product ecosystem strength",
            "guidanceLanguage": "Raised with specific segment colour",
            "QATone": "Measured, detailed on China and Services",
            "keyTheme": "Services flywheel and premium hardware positioning",
        },
    }


def _mock_transcript() -> TranscriptResult:
    return TranscriptResult(
        ticker="AAPL",
        text="operator conference call earnings Q1 2025 " + "revenue grew. " * 200,
        source="edgar",
        quarter="Q1 2025",
        report_date=date(2025, 1, 30),
    )


def _plan_dict() -> dict:
    return {
        "tool_priority": ["transcript", "analysts", "news", "reddit"],
        "weight_overrides": {},
        "fetch_prior_quarter": False,
        "fetch_competitor": False,
        "competitor_ticker": None,
        "rationale": "default test plan",
    }


# ── helpers to reduce nesting ─────────────────────────────────────────────────

def _patch_services_to_fail():
    """Patch all external service calls so fetch_node returns None for everything.

    tools.py imports service functions into its own namespace at module load time, so
    patches must target agent.nodes.tools.* — patching services.*.* won't affect the
    already-bound local names inside tools.py.
    """
    return [
        patch("agent.nodes.tools.fetch_transcript", AsyncMock(side_effect=Exception("no transcript"))),
        patch("agent.nodes.tools.fetch_reddit_sentiment", AsyncMock(side_effect=Exception)),
        patch("agent.nodes.tools.fetch_news_sentiment", AsyncMock(side_effect=Exception)),
        patch("agent.nodes.tools.fetch_analyst_ratings", AsyncMock(side_effect=Exception)),
    ]


# ── test 1: sufficiency loop hard cap ────────────────────────────────────────

async def test_sufficiency_loop_hard_cap():
    """Graph must exit after ≤3 fetch iterations even when signals never arrive."""
    report = _valid_report_dict()

    # Transcript present (good), but signals never arrive → sufficiency fails until iter 3
    with patch("agent.nodes.tools.fetch_transcript", AsyncMock(return_value=_mock_transcript())):
        with patch("agent.nodes.tools.fetch_reddit_sentiment", AsyncMock(side_effect=Exception)):
            with patch("agent.nodes.tools.fetch_news_sentiment", AsyncMock(side_effect=Exception)):
                with patch("agent.nodes.tools.fetch_analyst_ratings", AsyncMock(side_effect=Exception)):
                    with patch("agent.graph.planner_node", AsyncMock(return_value={"plan": _plan_dict()})):
                        with patch("agent.graph.analyst_node", AsyncMock(return_value={"draft_report": report})):
                            with patch("agent.graph.reflector_node", AsyncMock(
                                return_value={"final_report": report, "reflection_notes": "ok"}
                            )):
                                g = build_graph()
                                final = await g.ainvoke(_initial_state())

    state = final if isinstance(final, dict) else vars(final)
    assert state["iterations"] <= 3, f"expected iterations ≤ 3, got {state['iterations']}"
    assert state["sufficient"] is True


# ── test 2: formatter retry cap ───────────────────────────────────────────────

async def test_formatter_retry_cap():
    """Formatter retries analyst at most once on validation failure, then raises FormatterError."""
    bad_report = {"ticker": "AAPL", "signal": "BUY"}  # missing required fields

    with patch("agent.nodes.tools.fetch_transcript", AsyncMock(return_value=_mock_transcript())):
        with patch("agent.nodes.tools.fetch_reddit_sentiment", AsyncMock(return_value=None)):
            with patch("agent.nodes.tools.fetch_news_sentiment", AsyncMock(return_value=None)):
                with patch("agent.nodes.tools.fetch_analyst_ratings", AsyncMock(return_value=None)):
                    with patch("agent.graph.planner_node", AsyncMock(return_value={"plan": _plan_dict()})):
                        # Analyst always returns a malformed report
                        with patch("agent.graph.analyst_node", AsyncMock(return_value={"draft_report": bad_report})):
                            with patch("agent.graph.reflector_node", AsyncMock(
                                return_value={"final_report": bad_report, "reflection_notes": "unchanged"}
                            )):
                                g = build_graph()
                                with pytest.raises(FormatterError):
                                    await g.ainvoke(_initial_state())


# ── test 3: slow news source does not block graph ────────────────────────────

async def test_news_timeout_does_not_block_graph():
    """A news fetcher that sleeps 10s (> 5s tool timeout) still produces a report."""
    report = _valid_report_dict()

    async def _slow_news(ticker):
        await asyncio.sleep(10)

    with patch("agent.nodes.tools.fetch_transcript", AsyncMock(return_value=_mock_transcript())):
        with patch("agent.nodes.tools.fetch_reddit_sentiment", AsyncMock(return_value=None)):
            with patch("agent.nodes.tools.fetch_news_sentiment", _slow_news):
                with patch("agent.nodes.tools.fetch_analyst_ratings", AsyncMock(return_value=None)):
                    with patch("agent.graph.planner_node", AsyncMock(return_value={"plan": _plan_dict()})):
                        with patch("agent.graph.analyst_node", AsyncMock(return_value={"draft_report": report})):
                            with patch("agent.graph.reflector_node", AsyncMock(
                                return_value={"final_report": report, "reflection_notes": "ok"}
                            )):
                                g = build_graph()
                                final = await g.ainvoke(_initial_state())

    state = final if isinstance(final, dict) else vars(final)
    assert state["final_report"], "expected a final report even with timed-out news"
    signals = state.get("signals", {})
    assert signals.get("news") is None


# ── test 4: planner failure is handled gracefully ─────────────────────────────

async def test_planner_error_falls_back_to_default_plan():
    """planner_node catches its own errors and uses default plan; graph completes."""
    report = _valid_report_dict()

    # Make the Anthropic client inside planner raise
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=Exception("API unavailable"))

    with patch("agent.nodes.planner.anthropic.AsyncAnthropic", return_value=mock_client):
        with patch("agent.nodes.tools.fetch_transcript", AsyncMock(return_value=_mock_transcript())):
            with patch("agent.nodes.tools.fetch_reddit_sentiment", AsyncMock(return_value=None)):
                with patch("agent.nodes.tools.fetch_news_sentiment", AsyncMock(return_value=None)):
                    with patch("agent.nodes.tools.fetch_analyst_ratings", AsyncMock(return_value=None)):
                        with patch("agent.graph.analyst_node", AsyncMock(return_value={"draft_report": report})):
                            with patch("agent.graph.reflector_node", AsyncMock(
                                return_value={"final_report": report, "reflection_notes": "ok"}
                            )):
                                g = build_graph()
                                final = await g.ainvoke(_initial_state())

    state = final if isinstance(final, dict) else vars(final)
    assert state["final_report"], "graph should still produce a report via fallback plan"


# ── test 5: happy path ────────────────────────────────────────────────────────

async def test_happy_path_produces_final_report():
    """All services return good data; final_report is set, iterations < 3, sufficient is True."""
    from services.signals.analysts import AnalystSignal
    from services.signals.news import NewsSignal
    from services.signals.reddit import RedditSignal

    report = _valid_report_dict()

    mock_reddit = RedditSignal(
        ticker="AAPL", post_count=30, bullish_count=20, bearish_count=5,
        top_titles=["Apple beats"], raw_signal="BULLISH",
    )
    mock_news = NewsSignal(ticker="AAPL", headlines=["Apple strong"], raw_signal="BUY", sources=["Reuters"])
    mock_analysts = AnalystSignal(
        ticker="AAPL", buy=20, hold=5, sell=1, strong_buy=15, strong_sell=0,
        raw_signal="BUY", period="2025-01",
    )

    with patch("agent.nodes.tools.fetch_transcript", AsyncMock(return_value=_mock_transcript())):
        with patch("agent.nodes.tools.fetch_reddit_sentiment", AsyncMock(return_value=mock_reddit)):
            with patch("agent.nodes.tools.fetch_news_sentiment", AsyncMock(return_value=mock_news)):
                with patch("agent.nodes.tools.fetch_analyst_ratings", AsyncMock(return_value=mock_analysts)):
                    with patch("agent.graph.planner_node", AsyncMock(return_value={"plan": _plan_dict()})):
                        with patch("agent.graph.analyst_node", AsyncMock(return_value={"draft_report": report})):
                            with patch("agent.graph.reflector_node", AsyncMock(
                                return_value={"final_report": report, "reflection_notes": "all good"}
                            )):
                                g = build_graph()
                                final = await g.ainvoke(_initial_state())

    state = final if isinstance(final, dict) else vars(final)
    assert state["final_report"], "final_report should be set on happy path"
    assert state["iterations"] < 3, f"expected < 3 iterations, got {state['iterations']}"
    assert state["sufficient"] is True


# ── test 6: reflector changes draft ──────────────────────────────────────────

async def test_reflector_changes_draft_populates_reflection_notes():
    """When reflector returns a different signal than analyst, reflection_notes is non-empty."""
    analyst_draft = _valid_report_dict(signal="BUY")
    reflector_final = _valid_report_dict(signal="HOLD")  # changed
    reflection_text = "Lowered signal from BUY to HOLD — guidance language was hedged despite beat."

    with patch("agent.nodes.tools.fetch_transcript", AsyncMock(return_value=_mock_transcript())):
        with patch("agent.nodes.tools.fetch_reddit_sentiment", AsyncMock(return_value=None)):
            with patch("agent.nodes.tools.fetch_news_sentiment", AsyncMock(return_value=None)):
                with patch("agent.nodes.tools.fetch_analyst_ratings", AsyncMock(return_value=None)):
                    with patch("agent.graph.planner_node", AsyncMock(return_value={"plan": _plan_dict()})):
                        with patch("agent.graph.analyst_node", AsyncMock(return_value={"draft_report": analyst_draft})):
                            with patch("agent.graph.reflector_node", AsyncMock(return_value={
                                "final_report": reflector_final,
                                "reflection_notes": reflection_text,
                            })):
                                g = build_graph()
                                final = await g.ainvoke(_initial_state())

    state = final if isinstance(final, dict) else vars(final)
    assert state["reflection_notes"], "reflection_notes should be non-empty when reflector changed draft"
    assert state["final_report"]["signal"] == "HOLD"
