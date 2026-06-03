"""
Pure-Python adjudication rules applied to Claude's raw report dict.

Called before schema validation in both services/analyst.py and
agent/nodes/formatter.py to enforce the invariants from CLAUDE.md:

  1. signalChanged = (signal != sourceSignals.transcript)
  2. signalConfidence <= 60 when transcript and analysts actively disagree
  3. Reddit alone never flips a signal away from transcript+analysts consensus
"""
from __future__ import annotations

_SIGNAL_COERCE = {
    "SELL": "WATCH",
    "STRONG BUY": "BUY",
    "STRONG_BUY": "BUY",
    "OUTPERFORM": "BUY",
    "OVERWEIGHT": "BUY",
    "STRONG SELL": "WATCH",
    "STRONG_SELL": "WATCH",
    "UNDERPERFORM": "WATCH",
    "UNDERWEIGHT": "WATCH",
    "NEUTRAL": "HOLD",
    "MARKET PERFORM": "HOLD",
    "MARKET_PERFORM": "HOLD",
}
_VALID_SIGNALS = {"BUY", "HOLD", "WATCH"}


def _coerce_signal(value: str | None) -> str | None:
    """Normalize common LLM signal variants to the allowed BUY/HOLD/WATCH enum."""
    if value is None:
        return None
    normalized = _SIGNAL_COERCE.get(value.upper().strip(), value)
    return normalized if normalized in _VALID_SIGNALS else value


def _norm(signal: str | None) -> str | None:
    """Map Reddit BULLISH/BEARISH into the BUY/HOLD/WATCH namespace."""
    if signal is None:
        return None
    return {"BULLISH": "BUY", "BEARISH": "WATCH"}.get(signal, signal)


def adjudicate(report: dict) -> dict:
    """
    Enforce signal adjudication invariants on a raw report dict.
    Returns a corrected copy; never mutates the input.
    Each rule is applied only when its required fields are present.
    """
    report = dict(report)

    # Coerce top-level signal and sourceSignals.transcript before any rule runs.
    if report.get("signal"):
        report["signal"] = _coerce_signal(report["signal"])
    source_raw = report.get("sourceSignals") or {}
    if source_raw.get("transcript"):
        source_raw = dict(source_raw)
        source_raw["transcript"] = _coerce_signal(source_raw["transcript"])
        report["sourceSignals"] = source_raw

    source = report.get("sourceSignals") or {}

    signal = report.get("signal")
    t_sig = source.get("transcript")           # BUY | HOLD | WATCH
    a_sig = source.get("analysts")             # BUY | HOLD | WATCH | None
    n_sig = source.get("news")                 # BUY | HOLD | WATCH | MIXED | None
    # Reddit expressed in its own vocab; normalise for comparison
    r_sig = _norm(source.get("reddit"))        # BUY | WATCH | None (after norm)

    # ── Rule 1: signalChanged correctness ────────────────────────────────────
    if signal and t_sig:
        report["signalChanged"] = signal != t_sig

    # ── Rule 2: confidence cap on transcript/analyst disagreement ─────────────
    if t_sig and a_sig and a_sig not in ("MIXED", None) and t_sig != a_sig:
        conf = report.get("signalConfidence")
        if isinstance(conf, (int, float)) and conf > 60:
            report["signalConfidence"] = 60

    # ── Rule 3: Reddit alone never flips a signal ────────────────────────────
    # Conditions for applying: transcript and analysts agree on a consensus,
    # news is absent or mixed (can't independently justify the flip),
    # but the final signal deviates from that consensus.
    if (
        signal
        and t_sig
        and a_sig
        and a_sig not in ("MIXED", None)
        and t_sig == a_sig                         # transcript + analysts agree
        and signal != t_sig                        # final signal flipped anyway
        and (n_sig is None or n_sig == "MIXED")    # news doesn't justify the flip
    ):
        report["signal"] = t_sig
        report["signalChanged"] = False

    return report
