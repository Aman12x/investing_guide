from dataclasses import dataclass
from datetime import date


@dataclass
class TranscriptResult:
    ticker: str
    text: str
    source: str            # "edgar" | "fmp" | "stockanalysis"
    quarter: str | None
    report_date: date | None
