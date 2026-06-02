"""Tests for the formatter node (pure Python validation, no I/O)."""
import pytest
from agent.state import AgentState
from agent.nodes.formatter import FormatterError, formatter_node, formatter_router


def _state(**overrides) -> AgentState:
    defaults = dict(
        ticker="TSLA",
        user_intent="full analysis",
        plan={},
        transcript=None,
        signals={},
        draft_report={},
        final_report={},
        reflection_notes="",
    )
    defaults.update(overrides)
    return AgentState(**defaults)


def _valid_report() -> dict:
    return {
        "company": "Tesla Inc",
        "ticker": "TSLA",
        "quarter": "Q1 2025",
        "reportDate": "April 23, 2025",
        "signal": "BUY",
        "signalRationale": "Strong revenue growth and raised full-year guidance beat analyst expectations.",
        "signalConfidence": 78,
        "signalChanged": False,
        "sourceSignals": {
            "transcript": "BUY",
            "news": "BUY",
            "analysts": "HOLD",
            "reddit": "BULLISH",
        },
        "contradictions": ["Analysts hold despite strong transcript beat"],
        "metrics": {
            "revenue": {"value": "$25.7b", "delta": "+9% YoY", "beat": True},
            "eps": {"value": "$0.45", "delta": "+12% YoY", "beat": True},
            "operatingMargin": {"value": "7.4%", "delta": "-120bps YoY", "beat": False},
            "guidance": {"value": "$110b full-year", "delta": "raised $2b", "beat": True},
        },
        "executiveSummary": (
            "Tesla delivered a solid Q1 beat driven by energy storage and services. "
            "Automotive margins remain compressed but recovered modestly QoQ. "
            "Management raised full-year guidance, citing FSD expansion and Megapack demand. "
            "Key risk remains pricing pressure in China."
        ),
        "keyHighlights": [
            "Energy storage revenue up 67% YoY",
            "FSD take rate expanding in North America",
            "Megapack backlog at record levels",
            "China ASP held flat after price cuts",
            "Cybertruck production ramp on track",
        ],
        "watchlist": [
            "Q2 automotive gross margin trajectory",
            "FSD regulatory approval timeline in EU",
            "Megapack delivery pace vs backlog",
        ],
        "risks": [
            {"text": "China pricing pressure could compress margins further", "level": "high"},
            {"text": "Macro slowdown dampening EV demand in Europe", "level": "med"},
        ],
        "sentiment": {
            "overall": 72,
            "ceoConfidence": 80,
            "forwardLooking": 75,
            "caution": 35,
        },
        "managementTone": {
            "openingTone": "Confident, focused on profitability recovery",
            "guidanceLanguage": "Raised with clear reasoning",
            "QATone": "Defensive on margins, bullish on energy",
            "keyTheme": "Transition from volume to profitability",
        },
    }


class TestFormatterNode:
    def test_valid_report_passes(self):
        s = _state(final_report=_valid_report())
        result = formatter_node(s)
        assert result["final_report"]["ticker"] == "TSLA"
        assert result["final_report"]["signal"] == "BUY"

    def test_empty_final_report_raises_formatter_error(self):
        s = _state(final_report={})
        with pytest.raises(FormatterError) as exc_info:
            formatter_node(s)
        assert "final_report" in str(exc_info.value)

    def test_missing_required_field_triggers_retry_on_first_attempt(self):
        bad = _valid_report()
        del bad["signal"]
        s = _state(final_report=bad, formatter_attempts=0)
        result = formatter_node(s)
        # First failure: clears report and sets formatter_attempts=1
        assert result["final_report"] == {}
        assert result["formatter_attempts"] == 1
        assert any("signal" in e for e in result["errors"])

    def test_missing_required_field_raises_on_second_attempt(self):
        bad = _valid_report()
        del bad["signal"]
        s = _state(final_report=bad, formatter_attempts=1)
        with pytest.raises(FormatterError):
            formatter_node(s)

    def test_wrong_signal_value_fails_validation(self):
        bad = _valid_report()
        bad["signal"] = "MAYBE"
        s = _state(final_report=bad, formatter_attempts=0)
        result = formatter_node(s)
        assert result["final_report"] == {}

    def test_sentiment_out_of_range_fails(self):
        bad = _valid_report()
        bad["sentiment"]["overall"] = 150  # out of 0-100
        s = _state(final_report=bad, formatter_attempts=0)
        result = formatter_node(s)
        assert result["final_report"] == {}

    def test_too_few_key_highlights_fails(self):
        bad = _valid_report()
        bad["keyHighlights"] = ["only one"]  # must be exactly 5
        s = _state(final_report=bad, formatter_attempts=0)
        result = formatter_node(s)
        assert result["final_report"] == {}

    def test_too_few_watchlist_items_fails(self):
        bad = _valid_report()
        bad["watchlist"] = ["just one", "two"]  # must be exactly 3
        s = _state(final_report=bad, formatter_attempts=0)
        result = formatter_node(s)
        assert result["final_report"] == {}

    def test_errors_accumulate(self):
        bad = _valid_report()
        del bad["signal"]
        s = _state(final_report=bad, formatter_attempts=0, errors=["prior error"])
        result = formatter_node(s)
        assert "prior error" in result["errors"]
        assert len(result["errors"]) == 2  # prior + new


class TestFormatterRouter:
    def test_routes_end_when_final_report_populated(self):
        s = _state(final_report={"ticker": "TSLA"})
        assert formatter_router(s) == "end"

    def test_routes_retry_analyst_when_final_report_empty(self):
        s = _state(final_report={})
        assert formatter_router(s) == "retry_analyst"
