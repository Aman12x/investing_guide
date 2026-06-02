import json
import logging
import os

import anthropic

from agent.state import AgentState

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"

PLANNER_PROMPT = """
You are an analysis planner. Given a ticker and user intent, decide:
1. Which tools are most important for this specific ticker (rank them)
2. Whether Reddit weight should be increased (high retail interest tickers: GME, AMC, TSLA, NVDA, AAPL)
3. Whether macro/market context is especially relevant (rate-sensitive tickers: banks, REITs, utilities)
4. Any additional context worth fetching (competitor earnings, prior quarter transcript)

Return JSON only:
{
  "tool_priority": ["transcript", "analysts", "news", "market", "reddit"],
  "weight_overrides": {"reddit": 0.15, "market": 0.25},
  "fetch_prior_quarter": true | false,
  "fetch_competitor": true | false,
  "competitor_ticker": "string | null",
  "rationale": "one sentence"
}
""".strip()

_DEFAULT_PLAN = {
    "tool_priority": ["transcript", "analysts", "news", "market", "reddit"],
    "weight_overrides": {},
    "fetch_prior_quarter": False,
    "fetch_competitor": False,
    "competitor_ticker": None,
    "rationale": "default plan (planner unavailable)",
}


async def planner_node(state: AgentState) -> dict:
    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    user_msg = f"Ticker: {state.ticker}\nUser intent: {state.user_intent}"

    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=512,
            system=PLANNER_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )

        if not response.content or not hasattr(response.content[0], "text"):
            raise ValueError("Empty planner response")

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        plan = json.loads(raw)
        logger.info("Planner for %s: %s", state.ticker, plan.get("rationale", ""))
        return {"plan": plan}

    except Exception as exc:
        logger.warning("Planner failed for %s: %s — using default plan", state.ticker, exc)
        return {"plan": _DEFAULT_PLAN}
