import asyncio
import json
import logging
import os

import anthropic
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
- Sources agree → confidence 75–95; for a clean beat-and-raise with no contradictions, lean toward 85–95
- Transcript + analysts agree, news/Reddit diverge → keep signal, lower confidence 10–15 pts,
  note divergence in contradictions[]
- Transcript vs analysts DISAGREE → this is the most important case; explain explicitly in
  signalRationale, confidence must be ≤ 60
- Reddit alone NEVER flips a signal. It lowers confidence or adds a contradictions entry.
- signalChanged = true only if final signal differs from what transcript alone would suggest
- contradictions[]: max 3 items, plain English, each ≤ 15 words
- keyHighlights: exactly 5 items
- watchlist: exactly 3 items to watch next quarter

Metric accuracy rules (critical — violations are treated as hallucination):
- Every value in metrics{} must be cited verbatim or as a direct paraphrase from the transcript.
  Never compute, estimate, or invent a figure that does not appear in the transcript.
- operatingMargin.value: use whichever margin metric is most relevant, in this priority order:
  1. Operating margin (GAAP) if explicitly stated as a % or computable from stated revenue + operating income
  2. Adjusted operating margin if stated
  3. Gross margin only if operating margin is not disclosed at all
  Label the delta to match (e.g., "+250bps operating margin YoY" or "+180bps gross margin YoY").
- beat: true only when management or the transcript explicitly states the result beat guidance or
  consensus. If management says the metric "came in below guidance" or "was below our target,"
  set beat: false — never characterize a self-acknowledged miss as a beat.
- If a YoY delta is not stated in the transcript, write "not disclosed" for delta rather than
  computing it yourself.
- For the guidance field: only cite guidance that management explicitly stated in this call.
  Never project, infer, or carry over prior-quarter guidance. If no revenue/EPS guidance was
  given, write "not provided" for value and delta.
- In the guidance delta, never characterize the prior guidance as a "midpoint" unless management
  called it that. If prior guidance was a point ($13.8B), write "raised from $13.8B" not
  "raised from $13.8B midpoint."
- In signalRationale: never write that guidance was "raised" for a specific metric unless the
  transcript explicitly states the guidance was raised for that metric. Always verify direction.
- In risks[]: never annualize or extrapolate quarterly figures. If a segment's quarterly revenue
  or loss was not annualized by management, do not annualize it yourself. Cite only figures
  management explicitly stated.

Signal and confidence calibration:
- Absence of external signals does NOT lower confidence. Calibrate on transcript alone.
- First determine signal (BUY/HOLD/WATCH) independently. Then set confidence.

Signal guidance:
- BUY: clear beat on key metrics + guidance raised or maintained + no major acknowledged negatives
- HOLD: mixed results, OR beat but management acknowledged a significant negative
  (margin below guidance, unquantified CapEx escalation, major segment losses, guidance uncertainty)
- WATCH: guidance cut, results missed, or management flagged serious headwinds

Confidence hard minimums for BUY signal (only when signal=BUY):
- BUY + beat + guidance raised + NO acknowledged negatives (no margin misses, no unquantified
  CapEx escalation, no material segment losses) → signalConfidence MUST be ≥ 82
- BUY + beat + guidance raised + CapEx headwind or minor uncertainty acknowledged
  → signalConfidence MUST be ≥ 75

These minimums do NOT apply when:
  - Management said a key metric came in below prior guidance (even for strategic reasons)
  - 2025 cost trajectory is explicitly unquantified/uncertain
  - A major business segment has ongoing material losses with no profitability timeline
  In those cases, HOLD is appropriate with confidence 55–68.

Confidence anchors (treat as exact targets):
  Clean beat-and-raise, margins above guidance, first buyback, no acknowledged negatives → BUY 87
  Strong beat, guidance raised, CapEx headwind noted by CFO → BUY 80
  Revenue beat, margin acknowledged below prior guidance, CapEx unquantified → HOLD 62
  In-line results, guidance maintained, acknowledged competitive risks → HOLD 65
  Guidance cut, margins declining → WATCH 44

contradictions[] rules — strict:
- ONLY list items where management's words directly and explicitly contradict each other within
  the same call (e.g., claiming strong demand while guiding revenue down).
- DO NOT list: forward-looking risks, acknowledged challenges, deliberate strategic choices
  management explained, capital returned vs. single-quarter OCF (standard treasury practice),
  or any item that requires inference rather than a direct quote contradiction.
- When in doubt, leave contradictions[] EMPTY. An empty array is always correct;
  a wrong contradiction fails the quality check.

Rationale and beat rules:
- signalRationale (≤25 words): describe the key result drivers only — what the quarter showed.
  Do NOT characterize forward guidance direction (e.g., "raised-floor guidance", "durable momentum")
  unless management used those exact words. If guidance was conservative ("low to mid single digits"),
  omit the guidance characterization from the rationale entirely and focus on the result.
  Do NOT use the word "beat" in signalRationale if the metrics section has beat: false for all
  key metrics — the rationale must be internally consistent with the metrics you reported.
- If management says a metric "came in below guidance due to accelerated strategic investment,"
  do NOT call it a miss — frame it as an intentional choice that reduces near-term margin.
- beat: true only when the transcript explicitly states a result beat a specific prior guidance
  figure or consensus. Default to false when no prior guidance was disclosed.

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


_OVERLOAD_DELAYS = [5, 15, 30]  # seconds to wait between retries on 529


async def _create_with_backoff(client, messages: list) -> anthropic.types.Message:
    """Call Claude with exponential-ish backoff on 529 overload responses."""
    last_exc: Exception | None = None
    for i, wait in enumerate([0] + _OVERLOAD_DELAYS):
        if wait:
            logger.warning("Claude overloaded (attempt %d/%d), retrying in %ss", i, len(_OVERLOAD_DELAYS) + 1, wait)
            await asyncio.sleep(wait)
        try:
            return await client.messages.create(
                model=_MODEL,
                max_tokens=4096,
                system=_SYSTEM_PROMPT,
                messages=messages,
            )
        except anthropic.InternalServerError as exc:
            if "overloaded" in str(exc).lower():
                last_exc = exc
                continue
            raise
    raise ClaudeError("Claude API overloaded after retries") from last_exc


@observe(name="generate_report")
async def generate_report(transcript: str, ticker: str, external: ExternalContext) -> ReportJSON:
    update_trace(user_id=ticker, session_id=ticker, input={"ticker": ticker})
    client = make_anthropic_client()
    user_msg = _build_user_message(transcript, ticker, external)
    messages = [{"role": "user", "content": user_msg}]

    for attempt in range(2):
        try:
            response = await _create_with_backoff(client, messages)
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
