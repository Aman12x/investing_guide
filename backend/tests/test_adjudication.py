"""
Adjudication rule tests — no Claude calls, no I/O.

These cover the three invariants from CLAUDE.md that were previously only
enforceable via nightly LLM evals:
  1. signalChanged = (signal != sourceSignals.transcript)
  2. signalConfidence <= 60 when transcript and analysts disagree
  3. Reddit alone never flips a signal away from transcript+analysts consensus
"""
import pytest

from services.adjudication import adjudicate


def _base(**overrides) -> dict:
    """Minimal dict that mirrors what Claude produces."""
    d = {
        "signal": "HOLD",
        "signalChanged": False,
        "signalConfidence": 75,
        "sourceSignals": {
            "transcript": "HOLD",
            "news": None,
            "analysts": None,
            "reddit": None,
        },
    }
    d.update(overrides)
    return d


# ── Rule 1: signalChanged correctness ─────────────────────────────────────────

class TestSignalChanged:
    def test_signal_matches_transcript_sets_false(self):
        assert adjudicate(_base())["signalChanged"] is False

    def test_signal_differs_from_transcript_sets_true(self):
        r = adjudicate(_base(signal="WATCH"))  # transcript="HOLD"
        assert r["signalChanged"] is True

    def test_corrects_wrong_value_set_by_claude(self):
        d = _base(signal="BUY", signalChanged=False)  # Claude got it wrong
        r = adjudicate(d)
        assert r["signalChanged"] is True

    def test_missing_transcript_leaves_value_untouched(self):
        d = _base(signalChanged=True)
        d["sourceSignals"]["transcript"] = None
        r = adjudicate(d)
        assert r["signalChanged"] is True  # unchanged

    def test_missing_signal_leaves_value_untouched(self):
        d = _base(signalChanged=False)
        d["signal"] = None
        r = adjudicate(d)
        assert r["signalChanged"] is False  # unchanged

    @pytest.mark.parametrize("sig", ["BUY", "HOLD", "WATCH"])
    def test_all_signal_values_handled(self, sig):
        d = _base(signal=sig)
        d["sourceSignals"]["transcript"] = "HOLD"
        r = adjudicate(d)
        assert r["signalChanged"] is (sig != "HOLD")


# ── Rule 2: confidence cap ────────────────────────────────────────────────────

class TestConfidenceCap:
    def test_transcript_analyst_disagree_caps_at_60(self):
        d = _base(signalConfidence=85)
        d["sourceSignals"]["transcript"] = "BUY"
        d["sourceSignals"]["analysts"] = "WATCH"
        r = adjudicate(d)
        assert r["signalConfidence"] == 60

    def test_transcript_analyst_agree_no_cap(self):
        d = _base(signalConfidence=85)
        d["sourceSignals"]["transcript"] = "BUY"
        d["sourceSignals"]["analysts"] = "BUY"
        r = adjudicate(d)
        assert r["signalConfidence"] == 85

    def test_confidence_already_at_60_unchanged(self):
        d = _base(signalConfidence=60)
        d["sourceSignals"]["transcript"] = "BUY"
        d["sourceSignals"]["analysts"] = "HOLD"
        r = adjudicate(d)
        assert r["signalConfidence"] == 60

    def test_confidence_below_60_not_raised(self):
        d = _base(signalConfidence=40)
        d["sourceSignals"]["transcript"] = "BUY"
        d["sourceSignals"]["analysts"] = "WATCH"
        r = adjudicate(d)
        assert r["signalConfidence"] == 40

    def test_no_analyst_signal_no_cap(self):
        d = _base(signalConfidence=90)
        d["sourceSignals"]["analysts"] = None
        r = adjudicate(d)
        assert r["signalConfidence"] == 90

    def test_mixed_analyst_treated_as_absent(self):
        d = _base(signalConfidence=90)
        d["sourceSignals"]["transcript"] = "BUY"
        d["sourceSignals"]["analysts"] = "MIXED"
        r = adjudicate(d)
        assert r["signalConfidence"] == 90  # MIXED → no cap


# ── Rule 3: Reddit alone never flips ──────────────────────────────────────────

class TestRedditNeverFlips:
    def test_reddit_flip_reverted_to_consensus(self):
        d = _base(signal="BUY")  # Claude was swayed by BULLISH reddit
        d["sourceSignals"]["transcript"] = "HOLD"
        d["sourceSignals"]["analysts"] = "HOLD"  # agree with transcript
        d["sourceSignals"]["reddit"] = "BULLISH"
        d["sourceSignals"]["news"] = None
        r = adjudicate(d)
        assert r["signal"] == "HOLD"

    def test_reddit_flip_reverted_with_mixed_news(self):
        d = _base(signal="BUY")
        d["sourceSignals"]["transcript"] = "HOLD"
        d["sourceSignals"]["analysts"] = "HOLD"
        d["sourceSignals"]["news"] = "MIXED"  # mixed = absent for this rule
        d["sourceSignals"]["reddit"] = "BULLISH"
        r = adjudicate(d)
        assert r["signal"] == "HOLD"

    def test_news_present_justifies_flip(self):
        """When news independently supports the flip, don't revert."""
        d = _base(signal="BUY")
        d["sourceSignals"]["transcript"] = "HOLD"
        d["sourceSignals"]["analysts"] = "HOLD"
        d["sourceSignals"]["news"] = "BUY"      # news explains it
        d["sourceSignals"]["reddit"] = "BULLISH"
        r = adjudicate(d)
        assert r["signal"] == "BUY"             # legitimate flip

    def test_transcript_analyst_disagree_rule_not_applied(self):
        """Rule 3 only triggers when transcript and analysts agree."""
        d = _base(signal="BUY")
        d["sourceSignals"]["transcript"] = "BUY"
        d["sourceSignals"]["analysts"] = "WATCH"  # analysts disagree with transcript
        d["sourceSignals"]["reddit"] = "BULLISH"
        r = adjudicate(d)
        assert r["signal"] == "BUY"             # rule 3 doesn't apply

    def test_no_analyst_data_rule_not_applied(self):
        """Without analyst data we can't confirm consensus."""
        d = _base(signal="BUY")
        d["sourceSignals"]["transcript"] = "HOLD"
        d["sourceSignals"]["analysts"] = None
        d["sourceSignals"]["reddit"] = "BULLISH"
        r = adjudicate(d)
        assert r["signal"] == "BUY"

    def test_signal_already_matches_consensus_no_change(self):
        d = _base(signal="HOLD")
        d["sourceSignals"]["transcript"] = "HOLD"
        d["sourceSignals"]["analysts"] = "HOLD"
        d["sourceSignals"]["reddit"] = "BULLISH"
        r = adjudicate(d)
        assert r["signal"] == "HOLD"

    def test_revert_also_corrects_signal_changed(self):
        d = _base(signal="BUY", signalChanged=True)
        d["sourceSignals"]["transcript"] = "HOLD"
        d["sourceSignals"]["analysts"] = "HOLD"
        d["sourceSignals"]["news"] = None
        d["sourceSignals"]["reddit"] = "BULLISH"
        r = adjudicate(d)
        assert r["signal"] == "HOLD"
        assert r["signalChanged"] is False

    def test_bearish_reddit_flip_also_reverted(self):
        d = _base(signal="WATCH")
        d["sourceSignals"]["transcript"] = "BUY"
        d["sourceSignals"]["analysts"] = "BUY"
        d["sourceSignals"]["reddit"] = "BEARISH"
        d["sourceSignals"]["news"] = None
        r = adjudicate(d)
        assert r["signal"] == "BUY"


# ── Interaction between rules ─────────────────────────────────────────────────

class TestRuleInteractions:
    def test_all_three_rules_applied_in_order(self):
        """Transcript=BUY, analysts=WATCH (disagree), reddit=BEARISH flips signal to WATCH.
        Rule 2 should cap confidence. Rule 3 does NOT apply (transcript≠analysts)."""
        d = _base(signal="WATCH", signalConfidence=80, signalChanged=False)
        d["sourceSignals"]["transcript"] = "BUY"
        d["sourceSignals"]["analysts"] = "WATCH"
        d["sourceSignals"]["reddit"] = "BEARISH"
        r = adjudicate(d)
        assert r["signalChanged"] is True    # rule 1: WATCH != BUY
        assert r["signalConfidence"] == 60   # rule 2: cap on disagreement
        assert r["signal"] == "WATCH"        # rule 3 not triggered (analysts ≠ transcript)

    def test_does_not_mutate_input(self):
        d = _base(signal="BUY")
        d["sourceSignals"]["transcript"] = "HOLD"
        adjudicate(d)
        assert d["signal"] == "BUY"   # original untouched

    def test_empty_dict_does_not_raise(self):
        assert adjudicate({}) == {}

    def test_partial_dict_does_not_raise(self):
        r = adjudicate({"signal": "BUY"})
        assert r["signal"] == "BUY"

    def test_idempotent(self):
        d = _base(signal="BUY", signalConfidence=80)
        d["sourceSignals"]["transcript"] = "BUY"
        d["sourceSignals"]["analysts"] = "WATCH"
        first = adjudicate(d)
        second = adjudicate(first)
        assert first == second
