"""Layer 4 — LLM output quality tests against golden fixtures.

Gated behind @pytest.mark.llm — runs nightly in CI, not on every PR:
    pytest -m llm   (requires ANTHROPIC_API_KEY)
    pytest -m "not llm"  (skip these in normal PR runs)

Signal adjudication rules that are enforced purely inside the Claude prompt are also
tested here (signalChanged semantics, Reddit-alone-never-flips, confidence < 60 on
transcript/analyst disagreement) since they cannot be unit-tested without a real call.
"""
import json
import os
from pathlib import Path

import anthropic
import pytest

from schemas import ReportJSON
from services.analyst import generate_report
from services.signals.aggregator import ExternalContext

pytestmark = pytest.mark.llm

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "transcripts"
_BASELINES_DIR = Path(__file__).parent / "fixtures" / "baselines"
_BASELINES_DIR.mkdir(parents=True, exist_ok=True)

_JUDGE_PROMPT = """
You are a strict financial analyst evaluator. Given an earnings call transcript excerpt and a
ReportJSON produced by an AI analyst, evaluate the following four criteria and return a JSON object.

Return a JSON object with exactly these four boolean fields. Read the rules below before deciding.

FIELD RULES — the value true always means PASS; false always means FAIL:

1. "hallucination":
   PASS (true)  → every specific number in the report (revenue, EPS, margin %, deltas) appears
                  verbatim or as a clear paraphrase in the transcript.
   FAIL (false) → a specific number is clearly invented and cannot be found in the transcript.
   Notes rule: begin your notes for this criterion with "metrics_check: PASS" or "metrics_check: FAIL"
   — never write "Hallucination: FALSE" (that phrase is ambiguous and forbidden here).
   Schema note: the report's "operatingMargin" field is a catch-all for whatever margin the
   transcript discusses (gross margin, EBITDA, etc.). A field named "operatingMargin" containing
   a gross-margin value is correct, not a hallucination.

2. "rationale_support":
   PASS (true)  → signalRationale is grounded in evidence and does not contradict what management said.
   FAIL (false) → the rationale explicitly contradicts a key stated fact (e.g., calls an
                  acknowledged miss a beat, or ignores the dominant tone of the call).
   Notes rule: begin with "rationale_check: PASS" or "rationale_check: FAIL".

3. "sentiment_calibration":
   PASS (true)  → sentiment.overall matches the transcript tone within these bands:
                  80–100: transcript is unambiguously euphoric / record-breaking positive
                  60–79:  transcript is clearly positive / beat with minor concerns
                  40–59:  transcript is neutral, mixed, or in-line with measured tone
                  20–39:  transcript is cautious, guidance cut, or management flagged headwinds
                  0–19:   transcript is clearly negative / significant miss or crisis
                  Any score that lands in the correct band for the transcript's tone is a PASS.
                  Once you determine the score is in the right band, return PASS — do NOT
                  fail it because you prefer a different number within the same band.
                  Example: if you think 88–92 is ideal and the score is 94, but the transcript
                  is record-breaking positive (80–100 band), return PASS. Only fail if the
                  score is in an entirely wrong band.
   FAIL (false) → score is in a completely wrong band (e.g., 75 for a clearly negative transcript).
   Notes rule: begin with "sentiment_check: PASS" or "sentiment_check: FAIL".

4. "contradiction_accuracy":
   PASS (true)  → every item in contradictions[] is a genuine contradiction between statements
                  in the transcript, OR the array is empty and that is appropriate.
   FAIL (false) → an item in contradictions[] is a mischaracterization, a forward-looking risk,
                  or describes normal business practice (e.g., capital returned > single-quarter OCF).
   Notes rule: begin with "contradiction_check: PASS" or "contradiction_check: FAIL".

Return ONLY valid JSON with no markdown fences:
{"hallucination": true|false, "rationale_support": true|false, "sentiment_calibration": true|false, "contradiction_accuracy": true|false, "notes": "brief explanation"}
""".strip()


def _load_fixture(name: str) -> tuple[str, dict]:
    """Return (transcript_text, expected_dict) for a fixture name."""
    transcript = (_FIXTURES_DIR / f"{name}.txt").read_text()
    expected = json.loads((_FIXTURES_DIR / f"{name}_expected.json").read_text())
    return transcript, expected


def _null_context() -> ExternalContext:
    return ExternalContext(reddit=None, news=None, analysts=None)


async def _judge(transcript: str, report: ReportJSON) -> dict:
    """Run a second Claude call as judge; returns grader result dict."""
    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user_msg = (
        f"=== TRANSCRIPT EXCERPT ===\n{transcript[:8000]}\n=== END ===\n\n"
        f"=== REPORT JSON ===\n{json.dumps(report.model_dump(), indent=2)}\n=== END ==="
    )
    messages = [{"role": "user", "content": user_msg}]
    last_err: Exception | None = None
    for _ in range(3):
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_JUDGE_PROMPT,
            messages=messages,
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            last_err = exc
            messages = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "Your response was not valid JSON. Return ONLY the JSON object, no other text."},
            ]
    raise RuntimeError(f"Judge returned invalid JSON after retries: {last_err}")


def _save_baseline(name: str, grades: dict) -> None:
    path = _BASELINES_DIR / f"{name}_baseline.json"
    path.write_text(json.dumps(grades, indent=2))


def _check_regression(name: str, grades: dict) -> list[str]:
    """Return list of regressions (fields that were passing and now fail)."""
    path = _BASELINES_DIR / f"{name}_baseline.json"
    if not path.exists():
        return []
    baseline = json.loads(path.read_text())
    regressions = []
    for field in ("hallucination", "rationale_support", "sentiment_calibration", "contradiction_accuracy"):
        if baseline.get(field) is True and grades.get(field) is False:
            regressions.append(field)
    return regressions


# ── fixture tests ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fixture_name", [
    "aapl_q1_2025",
    "msft_q2_2025",
    "meta_q3_2024",
    "beat_and_raise_q2_2025",
    "small_cap_q1_2025",
])
async def test_llm_output_quality(fixture_name):
    """Generate a report from each golden fixture and grade it with a judge call."""
    transcript, expected = _load_fixture(fixture_name)
    ticker = fixture_name.split("_")[0].upper()

    report = await generate_report(transcript, ticker, _null_context())

    # Schema compliance — generation must produce a valid ReportJSON
    assert report.signal in ("BUY", "HOLD", "WATCH"), f"Invalid signal: {report.signal}"
    assert 0 <= report.signalConfidence <= 100

    # Confidence range check against golden expected
    conf_min = expected.get("confidence_min", 0)
    conf_max = expected.get("confidence_max", 100)
    assert conf_min <= report.signalConfidence <= conf_max, (
        f"{fixture_name}: confidence {report.signalConfidence} outside expected range "
        f"[{conf_min}, {conf_max}]"
    )

    # Judge grading
    grades = await _judge(transcript, report)
    assert grades.get("hallucination") is True, (
        f"{fixture_name}: hallucination check failed. Notes: {grades.get('notes')}"
    )
    assert grades.get("rationale_support") is True, (
        f"{fixture_name}: rationale_support check failed. Notes: {grades.get('notes')}"
    )
    assert grades.get("sentiment_calibration") is True, (
        f"{fixture_name}: sentiment_calibration check failed. Notes: {grades.get('notes')}"
    )
    assert grades.get("contradiction_accuracy") is True, (
        f"{fixture_name}: contradiction_accuracy check failed. Notes: {grades.get('notes')}"
    )

    # Regression gate: compare to baseline; fail on any newly-broken eval
    regressions = _check_regression(fixture_name, grades)
    assert not regressions, (
        f"{fixture_name}: regression detected in fields {regressions}. "
        f"These were passing in baseline. Notes: {grades.get('notes')}"
    )

    # Save/update baseline on success
    _save_baseline(fixture_name, grades)


# ── signal adjudication assertions ────────────────────────────────────────────

async def test_reddit_alone_does_not_flip_signal():
    """When only Reddit is bullish and all other signals say HOLD/WATCH, signal must not be BUY."""
    from services.signals.reddit import RedditSignal

    # Transcript clearly pessimistic (guidance cut, margins declining)
    bearish_transcript = (
        "operator conference call earnings. "
        "We are reducing our full-year revenue guidance from $10 billion to $8.5 billion "
        "due to deteriorating demand conditions and competitive pricing pressure. "
        "Operating margin declined 400 basis points year over year to 8%. "
        "We are implementing a cost reduction program affecting 12% of our workforce. "
        "The macro environment has deteriorated more sharply than anticipated. "
        "We withdrew guidance for Q3 and Q4 given visibility constraints. "
        "Free cash flow turned negative for the first time in six years. "
        "The question-and-answer session is now open. "
    ) * 15  # repeat to reach transcript length

    # Reddit is bullish (retail speculation)
    bullish_reddit = RedditSignal(
        ticker="MEME",
        post_count=500,
        bullish_count=450,
        bearish_count=20,
        top_titles=["MEME to the moon", "Short squeeze incoming", "Buy the dip MEME"],
        raw_signal="BULLISH",
    )
    external = ExternalContext(reddit=bullish_reddit, news=None, analysts=None)

    report = await generate_report(bearish_transcript, "MEME", external)

    # Reddit alone must not flip the signal to BUY
    assert report.signal != "BUY", (
        f"Reddit alone flipped signal to BUY despite bearish transcript. "
        f"signal={report.signal}, confidence={report.signalConfidence}, "
        f"sourceSignals={report.sourceSignals}"
    )


async def test_signal_changed_flag_semantics():
    """signalChanged must be True when final signal differs from transcript-only signal."""
    # Give a strong BUY transcript but antagonistic news signal
    bullish_transcript = (
        "operator conference call earnings Q1 2025. "
        "We are delighted to report record revenue of $5 billion, up 25% year over year. "
        "Earnings per share of $2.50 beat consensus by 30%. "
        "We are raising full-year guidance by 15%. "
        "Gross margin expanded 300 basis points to 72%. "
        "Customer churn reached an all-time low. "
        "Net revenue retention improved to 130%. "
        "We initiated a $500 million share repurchase program. "
        "The business has never been stronger. "
        "The question-and-answer session is now open. "
    ) * 20

    from services.signals.analysts import AnalystSignal
    from services.signals.news import NewsSignal

    # Analysts strongly disagree (geopolitical risk not in transcript)
    bearish_analysts = AnalystSignal(
        ticker="BEAR",
        buy=2, hold=5, sell=8, strong_buy=0, strong_sell=3,
        raw_signal="WATCH", period="2025-01",
    )
    bearish_news = NewsSignal(
        ticker="BEAR",
        headlines=[
            "Regulatory probe launched into BEAR Corp's accounting practices",
            "CEO facing shareholder lawsuit over undisclosed related-party transactions",
            "DOJ investigation expanding to cover three additional subsidiaries",
        ],
        raw_signal="WATCH",
        sources=["Reuters", "WSJ"],
    )
    external = ExternalContext(reddit=None, news=bearish_news, analysts=bearish_analysts)

    report = await generate_report(bullish_transcript, "BEAR", external)

    # When external sources disagree with transcript, signalChanged should be set appropriately
    # and confidence should be reduced
    if report.signal != report.sourceSignals.transcript:
        assert report.signalChanged is True, (
            "signalChanged must be True when final signal != sourceSignals.transcript"
        )
    # With transcript vs analyst disagreement, confidence must be <= 60
    if (
        report.sourceSignals.transcript == "BUY"
        and report.sourceSignals.analysts in ("HOLD", "WATCH")
    ):
        assert report.signalConfidence <= 60, (
            f"Transcript vs analyst disagreement requires confidence <= 60, "
            f"got {report.signalConfidence}"
        )
