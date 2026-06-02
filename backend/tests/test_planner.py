"""Tests for the planner node (mocked Claude calls)."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.state import AgentState
from agent.nodes.planner import planner_node, PLANNER_PROMPT, _DEFAULT_PLAN


def _state(ticker="NVDA") -> AgentState:
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


def _mock_response(text: str):
    content_item = MagicMock()
    content_item.text = text
    response = MagicMock()
    response.content = [content_item]
    return response


VALID_PLAN = {
    "tool_priority": ["transcript", "analysts", "news", "market", "reddit"],
    "weight_overrides": {"reddit": 0.20},
    "fetch_prior_quarter": False,
    "fetch_competitor": False,
    "competitor_ticker": None,
    "rationale": "High-retail-interest ticker; boost Reddit weight.",
}


@pytest.mark.asyncio
async def test_planner_returns_valid_plan():
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(VALID_PLAN)))

    with patch("agent.nodes.planner.make_anthropic_client", return_value=mock_client):
        result = await planner_node(_state("NVDA"))

    assert result["plan"]["tool_priority"][0] == "transcript"
    assert result["plan"]["weight_overrides"]["reddit"] == 0.20
    assert result["plan"]["rationale"] == VALID_PLAN["rationale"]


@pytest.mark.asyncio
async def test_planner_strips_markdown_fences():
    fenced = f"```json\n{json.dumps(VALID_PLAN)}\n```"
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=_mock_response(fenced))

    with patch("agent.nodes.planner.make_anthropic_client", return_value=mock_client):
        result = await planner_node(_state("NVDA"))

    assert result["plan"]["rationale"] == VALID_PLAN["rationale"]


@pytest.mark.asyncio
async def test_planner_falls_back_to_default_on_api_error():
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(side_effect=Exception("network error"))

    with patch("agent.nodes.planner.make_anthropic_client", return_value=mock_client):
        result = await planner_node(_state("GME"))

    assert result["plan"] == _DEFAULT_PLAN


@pytest.mark.asyncio
async def test_planner_falls_back_on_invalid_json():
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=_mock_response("not json at all"))

    with patch("agent.nodes.planner.make_anthropic_client", return_value=mock_client):
        result = await planner_node(_state("AMC"))

    assert result["plan"] == _DEFAULT_PLAN


@pytest.mark.asyncio
async def test_planner_falls_back_on_empty_response():
    mock_client = AsyncMock()
    empty_response = MagicMock()
    empty_response.content = []
    mock_client.messages.create = AsyncMock(return_value=empty_response)

    with patch("agent.nodes.planner.make_anthropic_client", return_value=mock_client):
        result = await planner_node(_state("TSLA"))

    assert result["plan"] == _DEFAULT_PLAN
