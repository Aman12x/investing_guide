import json
import logging
import os

from agent.state import AgentState
from observability import make_anthropic_client, observe, update_trace

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"
_MAX_TRANSCRIPT_CHARS = 40_000

REFLECTOR_PROMPT = """
You are a skeptical senior analyst reviewing a junior analyst's report.

You have the original transcript and the draft report. Your job:
1. Find any facts in the transcript that CONTRADICT the signal
2. Check if the confidence score is justified given the evidence quality
3. Check if any risks were missed
4. Check if contradictions[] is accurate and complete

If you would change the signal, confidence, risks, or contradictions — return a revised ReportJSON.
If the draft is solid — return it unchanged.

STRICT ENUM CONSTRAINTS — violating these will cause a hard failure:
- signal: ONLY "BUY", "HOLD", or "WATCH" (never "SELL", "STRONG BUY", "OUTPERFORM", etc.)
- sourceSignals.transcript: ONLY "BUY", "HOLD", or "WATCH"
- sourceSignals.news: ONLY "BUY", "HOLD", "WATCH", "MIXED", or null
- sourceSignals.analysts: ONLY "BUY", "HOLD", "WATCH", or null
- sourceSignals.reddit: ONLY "BULLISH", "BEARISH", "MIXED", or null
- risks[].level: ONLY "high", "med", or "low"

Either way, return a JSON object:
{
  "report": { ...ReportJSON... },
  "changed": true | false,
  "reflection_notes": "what you changed and why, or why you kept it"
}
""".strip()


@observe(name="reflector")
async def reflector_node(state: AgentState) -> dict:
    ticker = state.ticker if hasattr(state, "ticker") else state.get("ticker", "")
    draft_report = state.draft_report if hasattr(state, "draft_report") else state.get("draft_report", {})
    transcript = state.transcript if hasattr(state, "transcript") else state.get("transcript")
    errors = list(state.errors if hasattr(state, "errors") else state.get("errors", []))
    update_trace(user_id=ticker, session_id=ticker)

    if not draft_report:
        logger.warning("Reflector: no draft report for %s — skipping", ticker)
        return {"final_report": {}, "reflection_notes": "skipped: no draft report", "errors": errors}

    transcript_excerpt = (
        transcript.text[:_MAX_TRANSCRIPT_CHARS]
        if transcript and hasattr(transcript, "text")
        else "(Transcript unavailable)"
    )

    user_msg = (
        f"=== ORIGINAL TRANSCRIPT EXCERPT ===\n"
        f"{transcript_excerpt}\n"
        f"=== END TRANSCRIPT ===\n\n"
        f"=== DRAFT REPORT ===\n"
        f"{json.dumps(draft_report, indent=2)}\n"
        f"=== END DRAFT REPORT ===\n\n"
        f"Review the draft against the transcript and return your reflection JSON."
    )

    client = make_anthropic_client()

    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=4096,
            system=REFLECTOR_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )

        if not response.content or not hasattr(response.content[0], "text"):
            raise ValueError("Empty reflector response")

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        result = json.loads(raw)
        final_report = result.get("report", draft_report)
        reflection_notes = result.get("reflection_notes", "")
        changed = result.get("changed", False)
        logger.info("Reflector for %s: changed=%s — %s", ticker, changed, reflection_notes[:80])
        return {"final_report": final_report, "reflection_notes": reflection_notes, "errors": errors}

    except Exception as exc:
        logger.warning("Reflector failed for %s: %s — using draft unchanged", ticker, exc)
        errors.append(f"reflector_node: failed ({exc}), using draft report unchanged")
        return {
            "final_report": draft_report,
            "reflection_notes": f"reflection failed: {exc}",
            "errors": errors,
        }
