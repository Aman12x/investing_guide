"""Layer 1 — Schema compliance tests. No I/O, no mocking needed."""
import copy

import pytest
from pydantic import ValidationError

from schemas import ReportJSON


class TestBaselineParse:
    def test_valid_sample_parses(self, sample_report):
        report = ReportJSON(**sample_report)
        assert report.ticker == "ACME"
        assert report.signal == "HOLD"

    def test_model_dump_round_trips(self, sample_report):
        report = ReportJSON(**sample_report)
        assert ReportJSON(**report.model_dump()).ticker == "ACME"


class TestRequiredFields:
    TOP_LEVEL_REQUIRED = [
        "company", "ticker", "quarter", "reportDate",
        "signal", "signalRationale", "signalConfidence", "signalChanged",
        "sourceSignals", "metrics", "executiveSummary", "keyHighlights",
        "watchlist", "risks", "sentiment", "managementTone",
    ]

    @pytest.mark.parametrize("field", TOP_LEVEL_REQUIRED)
    def test_missing_required_field_raises(self, sample_report, field):
        bad = copy.deepcopy(sample_report)
        del bad[field]
        with pytest.raises(ValidationError):
            ReportJSON(**bad)


class TestSignalConfidence:
    def test_confidence_at_boundaries(self, sample_report):
        for val in (0, 50, 100):
            r = copy.deepcopy(sample_report)
            r["signalConfidence"] = val
            assert ReportJSON(**r).signalConfidence == val

    def test_confidence_below_zero_raises(self, sample_report):
        bad = copy.deepcopy(sample_report)
        bad["signalConfidence"] = -1
        with pytest.raises(ValidationError):
            ReportJSON(**bad)

    def test_confidence_above_100_raises(self, sample_report):
        bad = copy.deepcopy(sample_report)
        bad["signalConfidence"] = 101
        with pytest.raises(ValidationError):
            ReportJSON(**bad)


class TestSignalEnum:
    @pytest.mark.parametrize("valid_signal", ["BUY", "HOLD", "WATCH"])
    def test_valid_signal_values(self, sample_report, valid_signal):
        r = copy.deepcopy(sample_report)
        r["signal"] = valid_signal
        assert ReportJSON(**r).signal == valid_signal

    @pytest.mark.parametrize("bad_signal", ["MAYBE", "buy", "hold", ""])
    def test_invalid_signal_raises(self, sample_report, bad_signal):
        bad = copy.deepcopy(sample_report)
        bad["signal"] = bad_signal
        with pytest.raises(ValidationError):
            ReportJSON(**bad)


class TestKeyHighlights:
    def test_exactly_five_passes(self, sample_report):
        assert len(sample_report["keyHighlights"]) == 5
        ReportJSON(**sample_report)  # should not raise

    def test_four_items_raises(self, sample_report):
        bad = copy.deepcopy(sample_report)
        bad["keyHighlights"] = bad["keyHighlights"][:4]
        with pytest.raises(ValidationError):
            ReportJSON(**bad)

    def test_six_items_truncated_to_five(self, sample_report):
        bad = copy.deepcopy(sample_report)
        bad["keyHighlights"] = bad["keyHighlights"] + ["extra item"]
        report = ReportJSON(**bad)
        assert len(report.keyHighlights) == 5


class TestWatchlist:
    def test_exactly_three_passes(self, sample_report):
        assert len(sample_report["watchlist"]) == 3
        ReportJSON(**sample_report)

    def test_two_items_raises(self, sample_report):
        bad = copy.deepcopy(sample_report)
        bad["watchlist"] = bad["watchlist"][:2]
        with pytest.raises(ValidationError):
            ReportJSON(**bad)

    def test_four_items_truncated_to_three(self, sample_report):
        bad = copy.deepcopy(sample_report)
        bad["watchlist"] = bad["watchlist"] + ["fourth item"]
        report = ReportJSON(**bad)
        assert len(report.watchlist) == 3


class TestContradictions:
    def test_empty_list_passes(self, sample_report):
        r = copy.deepcopy(sample_report)
        r["contradictions"] = []
        ReportJSON(**r)

    def test_three_items_passes(self, sample_report):
        r = copy.deepcopy(sample_report)
        r["contradictions"] = ["a", "b", "c"]
        ReportJSON(**r)

    def test_four_items_truncated_to_three(self, sample_report):
        bad = copy.deepcopy(sample_report)
        bad["contradictions"] = ["a", "b", "c", "d"]
        report = ReportJSON(**bad)
        assert len(report.contradictions) == 3

    def test_five_items_truncated_to_three(self, sample_report):
        bad = copy.deepcopy(sample_report)
        bad["contradictions"] = ["a", "b", "c", "d", "e"]
        report = ReportJSON(**bad)
        assert len(report.contradictions) == 3


class TestRisksLevel:
    @pytest.mark.parametrize("level", ["high", "med", "low"])
    def test_valid_risk_levels(self, sample_report, level):
        r = copy.deepcopy(sample_report)
        r["risks"] = [{"text": "some risk", "level": level}]
        ReportJSON(**r)

    @pytest.mark.parametrize("bad_level", ["critical", ""])
    def test_invalid_risk_level_raises(self, sample_report, bad_level):
        bad = copy.deepcopy(sample_report)
        bad["risks"] = [{"text": "some risk", "level": bad_level}]
        with pytest.raises(ValidationError):
            ReportJSON(**bad)


class TestSourceSignalsOptional:
    def test_reddit_null_is_valid(self, sample_report):
        r = copy.deepcopy(sample_report)
        r["sourceSignals"]["reddit"] = None
        report = ReportJSON(**r)
        assert report.sourceSignals.reddit is None

    def test_news_null_is_valid(self, sample_report):
        r = copy.deepcopy(sample_report)
        r["sourceSignals"]["news"] = None
        report = ReportJSON(**r)
        assert report.sourceSignals.news is None

    def test_analysts_null_is_valid(self, sample_report):
        r = copy.deepcopy(sample_report)
        r["sourceSignals"]["analysts"] = None
        report = ReportJSON(**r)
        assert report.sourceSignals.analysts is None

    def test_transcript_required(self, sample_report):
        bad = copy.deepcopy(sample_report)
        del bad["sourceSignals"]["transcript"]
        with pytest.raises(ValidationError):
            ReportJSON(**bad)


class TestMetricBeat:
    def test_beat_true_and_false_are_valid(self, sample_report):
        r = copy.deepcopy(sample_report)
        r["metrics"]["revenue"]["beat"] = True
        r["metrics"]["eps"]["beat"] = False
        ReportJSON(**r)

    def test_beat_arbitrary_string_raises(self, sample_report):
        # Pydantic v2 coerces "yes"/"no"/"true"/"false" but rejects arbitrary strings
        bad = copy.deepcopy(sample_report)
        bad["metrics"]["revenue"]["beat"] = "maybe"
        with pytest.raises(ValidationError):
            ReportJSON(**bad)

    def test_beat_integer_coerces(self, sample_report):
        # Pydantic v2 coerces int to bool by default; just ensure no crash
        r = copy.deepcopy(sample_report)
        r["metrics"]["revenue"]["beat"] = 1
        report = ReportJSON(**r)
        assert report.metrics.revenue.beat is True
