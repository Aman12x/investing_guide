"""Tests for agent graph structure and wiring."""
import pytest
from langgraph.graph.state import CompiledStateGraph

from agent.graph import agent, build_graph
from agent.state import AgentState


def test_agent_is_compiled_state_graph():
    assert isinstance(agent, CompiledStateGraph)


def test_build_graph_returns_fresh_compiled_graph():
    g = build_graph()
    assert isinstance(g, CompiledStateGraph)
    assert g is not agent  # each call produces a new instance


def test_graph_has_expected_nodes():
    g = build_graph()
    node_names = set(g.nodes.keys())
    expected = {"planner", "fetch", "sufficiency", "analyst", "reflector", "formatter"}
    assert expected.issubset(node_names), f"Missing nodes: {expected - node_names}"


def test_agent_state_fields_are_complete():
    """Regression: ensure all fields required by graph nodes are on AgentState."""
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(AgentState)}
    required = {
        "ticker", "user_intent", "plan", "transcript", "signals",
        "draft_report", "final_report", "reflection_notes",
        "iterations", "sufficient", "errors", "formatter_attempts",
    }
    missing = required - field_names
    assert not missing, f"AgentState is missing fields: {missing}"


def test_initial_state_instantiates():
    """The initial state used by the router must be constructible without errors."""
    s = AgentState(
        ticker="AAPL",
        user_intent="full analysis",
        plan={},
        transcript=None,
        signals={},
        draft_report={},
        final_report={},
        reflection_notes="",
    )
    assert s.ticker == "AAPL"
    assert s.iterations == 0
    assert s.sufficient is False
    assert s.errors == []
