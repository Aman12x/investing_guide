import json
import logging
import os

from exceptions import ClaudeError
from observability import make_anthropic_client, observe, update_trace
from schemas import ReportJSON
from services.adjudication import adjudicate
from services.signals.aggregator import ExternalContext, format_external_context

logger = logging.getLogger(__name__)

_MAX_TRANSCRIPT_CHARS = 80_000
_MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = """
You are an elite buy-side analyst. You receive:
  1. A full earnings call transcript (40% weight by default — see adjusted weights)
  2. Recent news headlines (25% weight by default)
  3. Analyst consensus ratings (25% weight by default)
  4. Reddit retail sentiment summary (10% weight by default)

Produce a ReportJSON. The signal field must reflect ALL sources weighted as specified.

Signal adjudication rules:
- Sources agree → straightforward signal, confidence 75–95
- Transcript + analysts agree, news/Reddit diverge → keep signal, lower confidence 10–15 pts,
  note divergence in contradictions[]
- Transcript vs analysts DISAGREE → this is the most important case; explain explicitly in
  signalRationale, confidence must be ≤ 60
- Reddit alone NEVER flips a signal. It lowers confidence or adds a contradictions entry.
- signalChanged = true only if final signal differs from what transcript alone would suggest
- contradictions[]: max 3 items, plain English, each ≤ 15 words
- keyHighlights: exactly 5 items
- watchlist: exactly 3 items to watch next quarter

Return ONLY valid JSON. No markdown fences, no preamble. Schema:

{
  "company": string,
  "ticker": string,
  "quarter": string,          // "Q1 2025"
  "reportDate": string,       // "April 30, 2025"
  "signal": "BUY"|"HOLD"|"WATCH",
  "signalRationale": string,  // ≤ 25 words
  "signalConfidence": number, // 0-100
  "signalChanged": boolean,
  "sourceSignals": {
    "transcript": "BUY"|"HOLD"|"WATCH",
    "news": "BUY"|"HOLD"|"WATCH"|"MIXED"|null,
    "analysts": "BUY"|"HOLD"|"WATCH"|null,
    "reddit": "BULLISH"|"BEARISH"|"MIXED"|null
  },
  "contradictions": string[], // max 3
  "metrics": {
    "revenue":         {"value": string, "delta": string, "beat": boolean},
    "eps":             {"value": string, "delta": string, "beat": boolean},
    "operatingMargin": {"value": string, "delta": string, "beat": boolean},
    "guidance":        {"value": string, "delta": string, "beat": boolean}
  },
  "executiveSummary": string,   // 3-4 sentences
  "keyHighlights": string[],    // exactly 5
  "watchlist": string[],        // exactly 3
  "risks": [{"text": string, "level": "high"|"med"|"low"}],
  "sentiment": {
    "overall": number,        // 0-100
    "ceoConfidence": number,
    "forwardLooking": number,
    "caution": number
  },
  "managementTone": {
    "openingTone": string,
    "guidanceLanguage": string,
    "QATone": string,
    "keyTheme": string
  }
}
""".strip()

_CORRECTION_PROMPT = (
    "Your previous response was not valid JSON or did not match the required schema. "
    "Error: {error}\n\n"
    "Return ONLY the corrected JSON. No markdown fences, no explanation."
)


def _build_user_message(transcript: str, ticker: str, external: ExternalContext) -> str:
    truncated = transcript[:_MAX_TRANSCRIPT_CHARS]
    external_block = format_external_context(ticker, external)

    return (
        f"=== EARNINGS CALL TRANSCRIPT FOR {ticker} ===\n"
        f"{truncated}\n"
        f"=== END TRANSCRIPT ===\n\n"
        f"{external_block}\n\n"
        f"Generate the complete ReportJSON for {ticker} following the schema and adjudication rules above."
    )


@observe(name="generate_report")
async def generate_report(transcript: str, ticker: str, external: ExternalContext) -> ReportJSON:
    update_trace(user_id=ticker, session_id=ticker, input={"ticker": ticker})
    client = make_anthropic_client()
    user_msg = _build_user_message(transcript, ticker, external)
    messages = [{"role": "user", "content": user_msg}]

    for attempt in range(2):
        try:
            response = await client.messages.create(
                model=_MODEL,
                max_tokens=4096,
                system=_SYSTEM_PROMPT,
                messages=messages,
            )
        except anthropic.APIError as exc:
            raise ClaudeError(f"Claude API error: {exc}") from exc

        if not response.content or not hasattr(response.content[0], "text"):
            raise ClaudeError("Claude returned empty or non-text response")
        raw = response.content[0].text.strip()

        # Strip accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            data = json.loads(raw)
            data = adjudicate(data)
            return ReportJSON(**data)
        except (json.JSONDecodeError, ValueError) as exc:
            if attempt == 0:
                logger.warning("Claude returned invalid JSON for %s (attempt 1); retrying. Error: %s", ticker, exc)
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": _CORRECTION_PROMPT.format(error=str(exc)),
                })
                continue
            raise ClaudeError(f"Claude returned invalid report JSON after retry: {exc}") from exc

    raise ClaudeError("Report generation exhausted retries")  # unreachable but satisfies mypy
