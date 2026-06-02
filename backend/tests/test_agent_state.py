"""Tests for AgentState dataclass."""
import dataclasses
from agent.state import AgentState


def _make_state(**overrides) -> AgentState:
    defaults = dict(
        ticker="AAPL",
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


def test_default_values():
    s = _make_state()
    assert s.iterations == 0
    assert s.sufficient is False
    assert s.errors == []
    assert s.formatter_attempts == 0


def test_errors_list_is_independent():
    """Each instance must get its own errors list (no shared default_factory bug)."""
    a = _make_state()
    b = _make_state()
    a.errors.append("boom")
    assert b.errors == [], "errors lists must not be shared across instances"


def test_all_fields_present():
    expected = {
        "ticker", "user_intent", "plan", "transcript", "signals",
        "draft_report", "final_report", "reflection_notes",
        "iterations", "sufficient", "errors", "formatter_attempts",
    }
    actual = {f.name for f in dataclasses.fields(AgentState)}
    assert actual == expected
