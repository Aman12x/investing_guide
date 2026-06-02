import asyncio
import sys
import os

# Ensure backend/ is on the path so all absolute imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest


@pytest.fixture
def sample_report() -> dict:
    """Minimal valid ReportJSON dict used across schema and API tests."""
    return {
        "company": "Acme Corp",
        "ticker": "ACME",
        "quarter": "Q1 2025",
        "reportDate": "April 30, 2025",
        "signal": "HOLD",
        "signalRationale": "Steady results with no major surprises versus consensus estimates.",
        "signalConfidence": 65,
        "signalChanged": False,
        "sourceSignals": {
            "transcript": "HOLD",
            "news": "HOLD",
            "analysts": "HOLD",
            "reddit": None,
        },
        "contradictions": [],
        "metrics": {
            "revenue": {"value": "$5.2b", "delta": "+4% YoY", "beat": True},
            "eps": {"value": "$1.10", "delta": "+2% YoY", "beat": False},
            "operatingMargin": {"value": "18%", "delta": "-50bps YoY", "beat": False},
            "guidance": {"value": "$21b full-year", "delta": "in-line", "beat": False},
        },
        "executiveSummary": (
            "Acme delivered in-line results with modest revenue growth. "
            "Operating margins compressed slightly on higher R&D spend. "
            "Management maintained full-year guidance. "
            "No material changes to the investment thesis."
        ),
        "keyHighlights": [
            "Revenue grew 4% YoY, in line with consensus",
            "EPS slightly missed due to higher stock-based compensation",
            "Operating margin compressed 50bps from increased R&D investment",
            "Guidance maintained at the midpoint of prior range",
            "Free cash flow conversion remained healthy at 92%",
        ],
        "watchlist": [
            "Q2 margin trajectory as R&D spend normalizes",
            "New product launch cadence in H2 2025",
            "International revenue mix shift",
        ],
        "risks": [
            {"text": "Margin pressure from elevated R&D could persist", "level": "med"},
            {"text": "Currency headwinds in EMEA region", "level": "low"},
        ],
        "sentiment": {
            "overall": 58,
            "ceoConfidence": 62,
            "forwardLooking": 55,
            "caution": 42,
        },
        "managementTone": {
            "openingTone": "Measured and factual, no promotional language",
            "guidanceLanguage": "Conservatively maintained with narrow range",
            "QATone": "Transparent, acknowledged margin headwinds directly",
            "keyTheme": "Disciplined investment while protecting profitability",
        },
    }
