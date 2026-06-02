"""Tests for the reflector node (mocked Claude calls)."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.state import AgentState
from agent.nodes.reflector import reflector_node


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


def _mock_transcript(text="earnings call content"):
    t = MagicMock()
    t.text = text
    return t


def _mock_response(payload: dict):
    content_item = MagicMock()
    content_item.text = json.dumps(payload)
    response = MagicMock()
    response.content = [content_item]
    return response


DRAFT = {"ticker": "MSFT", "signal": "BUY", "signalConfidence": 80}
REVISED = {"ticker": "MSFT", "signal": "HOLD", "signalConfidence": 55}


@pytest.mark.asyncio
async def test_reflector_accepts_unchanged_draft():
    payload = {"report": DRAFT, "changed": False, "reflection_notes": "draft is solid"}
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=_mock_response(payload))

    with patch("agent.nodes.reflector.make_anthropic_client", return_value=mock_client):
        result = await reflector_node(_state(draft_report=DRAFT, transcript=_mock_transcript()))

    assert result["final_report"] == DRAFT
    assert result["reflection_notes"] == "draft is solid"


@pytest.mark.asyncio
async def test_reflector_returns_revised_report():
    payload = {"report": REVISED, "changed": True, "reflection_notes": "lowered confidence"}
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=_mock_response(payload))

    with patch("agent.nodes.reflector.make_anthropic_client", return_value=mock_client):
        result = await reflector_node(_state(draft_report=DRAFT, transcript=_mock_transcript()))

    assert result["final_report"]["signal"] == "HOLD"
    assert result["final_report"]["signalConfidence"] == 55


@pytest.mark.asyncio
async def test_reflector_falls_back_to_draft_on_api_error():
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(side_effect=Exception("timeout"))

    with patch("agent.nodes.reflector.make_anthropic_client", return_value=mock_client):
        result = await reflector_node(_state(draft_report=DRAFT, transcript=_mock_transcript()))

    assert result["final_report"] == DRAFT
    assert "reflection failed" in result["reflection_notes"]
    assert any("reflector_node" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_reflector_skips_when_no_draft():
    result = await reflector_node(_state(draft_report={}))
    assert result["final_report"] == {}
    assert "skipped" in result["reflection_notes"]


@pytest.mark.asyncio
async def test_reflector_handles_missing_transcript():
    payload = {"report": DRAFT, "changed": False, "reflection_notes": "ok"}
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=_mock_response(payload))

    with patch("agent.nodes.reflector.make_anthropic_client", return_value=mock_client):
        # transcript=None should not crash the node
        result = await reflector_node(_state(draft_report=DRAFT, transcript=None))

    assert result["final_report"] == DRAFT
