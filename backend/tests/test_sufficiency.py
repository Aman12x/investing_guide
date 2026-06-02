"""Tests for the sufficiency node (pure logic, no I/O)."""
from dataclasses import replace
from unittest.mock import MagicMock

from agent.state import AgentState
from agent.nodes.sufficiency import check_sufficiency, sufficiency_router


def _state(**overrides) -> AgentState:
    defaults = dict(
        ticker="MSFT",
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


def _mock_transcript(text_len: int = 5000):
    t = MagicMock()
    t.text = "x" * text_len
    return t


def _signals(reddit=True, news=True, analysts=True):
    return {
        "reddit": MagicMock() if reddit else None,
        "news": MagicMock() if news else None,
        "analysts": MagicMock() if analysts else None,
    }


class TestCheckSufficiency:
    def test_pass_with_good_transcript_and_two_signals(self):
        s = _state(transcript=_mock_transcript(), signals=_signals(), iterations=1)
        result = check_sufficiency(s)
        assert result["sufficient"] is True

    def test_fail_when_transcript_missing_and_low_iterations(self):
        s = _state(transcript=None, signals=_signals(), iterations=1)
        result = check_sufficiency(s)
        assert result["sufficient"] is False

    def test_proceed_without_transcript_after_two_iterations(self):
        """Agent should give up waiting for transcript after iter >= 2."""
        s = _state(transcript=None, signals=_signals(), iterations=2)
        result = check_sufficiency(s)
        assert result["sufficient"] is True

    def test_max_iterations_forces_proceed(self):
        s = _state(transcript=None, signals={}, iterations=3)
        result = check_sufficiency(s)
        assert result["sufficient"] is True

    def test_fail_when_only_one_signal_source(self):
        s = _state(
            transcript=_mock_transcript(),
            signals=_signals(reddit=False, analysts=False),
            iterations=1,
        )
        result = check_sufficiency(s)
        assert result["sufficient"] is False

    def test_pass_with_exactly_two_signal_sources(self):
        s = _state(
            transcript=_mock_transcript(),
            signals=_signals(reddit=False),
            iterations=1,
        )
        result = check_sufficiency(s)
        assert result["sufficient"] is True

    def test_fail_with_short_transcript(self):
        s = _state(
            transcript=_mock_transcript(text_len=100),
            signals=_signals(),
            iterations=1,
        )
        result = check_sufficiency(s)
        assert result["sufficient"] is False


class TestSufficiencyRouter:
    def test_routes_proceed_when_sufficient(self):
        s = _state(sufficient=True)
        assert sufficiency_router(s) == "proceed"

    def test_routes_fetch_more_when_not_sufficient(self):
        s = _state(sufficient=False)
        assert sufficiency_router(s) == "fetch_more"
