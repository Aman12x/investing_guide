import json
import logging
import os

import anthropic

from agent.state import AgentState
from services.analyst import _SYSTEM_PROMPT
from services.signals.aggregator import ExternalContext, format_external_context

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"
_MAX_TRANSCRIPT_CHARS = 80_000
_MAX_CONTEXT_CHARS = 8_000

_CORRECTION_PROMPT = (
    "Your previous response was not valid JSON or did not match the required schema. "
    "Error: {error}\n\n"
    "Return ONLY the corrected JSON. No markdown fences, no explanation."
)


def _build_message(state: AgentState) -> str:
    signals = state.signals if hasattr(state, "signals") else state.get("signals", {})
    ticker = state.ticker if hasattr(state, "ticker") else state.get("ticker", "")
    transcript = state.transcript if hasattr(state, "transcript") else state.get("transcript")

    transcript_text = (
        transcript.text[:_MAX_TRANSCRIPT_CHARS]
        if transcript and hasattr(transcript, "text")
        else "(Transcript unavailable — base report on external signals only.)"
    )

    external = ExternalContext(
        reddit=signals.get("reddit"),
        news=signals.get("news"),
        analysts=signals.get("analysts"),
    )
    context_block = format_external_context(ticker, external)

    prior = signals.get("prior_quarter")
    if prior and hasattr(prior, "text"):
        context_block += (
            f"\n\n=== PRIOR QUARTER TRANSCRIPT EXCERPT ({ticker}) ===\n"
            f"{prior.text[:_MAX_CONTEXT_CHARS]}\n"
            f"=== END PRIOR QUARTER ==="
        )

    competitor = signals.get("competitor")
    if competitor and hasattr(competitor, "text"):
        context_block += (
            f"\n\n=== COMPETITOR TRANSCRIPT EXCERPT ===\n"
            f"{competitor.text[:_MAX_CONTEXT_CHARS]}\n"
            f"=== END COMPETITOR ==="
        )

    return (
        f"=== EARNINGS CALL TRANSCRIPT FOR {ticker} ===\n"
        f"{transcript_text}\n"
        f"=== END TRANSCRIPT ===\n\n"
        f"{context_block}\n\n"
        f"Generate the complete ReportJSON for {ticker} following the schema and adjudication rules above."
    )


async def analyst_node(state: AgentState) -> dict:
    ticker = state.ticker if hasattr(state, "ticker") else state.get("ticker", "")
    errors = list(state.errors if hasattr(state, "errors") else state.get("errors", []))
    transcript = state.transcript if hasattr(state, "transcript") else state.get("transcript")

    if transcript is None:
        errors.append("analyst_node: no transcript available — report based on signals only")

    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    messages = [{"role": "user", "content": _build_message(state)}]

    for attempt in range(2):
        try:
            response = await client.messages.create(
                model=_MODEL,
                max_tokens=4096,
                system=_SYSTEM_PROMPT,
                messages=messages,
            )
        except anthropic.APIError as exc:
            errors.append(f"analyst_node: Claude API error on attempt {attempt + 1}: {exc}")
            return {"draft_report": {}, "errors": errors}

        if not response.content or not hasattr(response.content[0], "text"):
            errors.append("analyst_node: empty Claude response")
            return {"draft_report": {}, "errors": errors}

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            draft = json.loads(raw)
            logger.info("Analyst node produced draft for %s", ticker)
            return {"draft_report": draft, "errors": errors}
        except json.JSONDecodeError as exc:
            if attempt == 0:
                logger.warning("Analyst JSON invalid for %s (attempt 1): %s", ticker, exc)
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": _CORRECTION_PROMPT.format(error=str(exc)),
                })
                continue
            errors.append(f"analyst_node: invalid JSON after retry: {exc}")
            return {"draft_report": {}, "errors": errors}

    return {"draft_report": {}, "errors": errors}
