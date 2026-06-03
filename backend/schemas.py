from __future__ import annotations
import re
from typing import Annotated, Literal
from pydantic import BaseModel, Field, field_validator

_QUARTER_RE = re.compile(r"^Q[1-4] \d{4}$")


class Metric(BaseModel):
    value: str
    delta: str
    beat: bool

    @field_validator("beat", mode="before")
    @classmethod
    def coerce_beat(cls, v: object) -> bool:
        if isinstance(v, str):
            if v.lower() == "true":
                return True
            if v.lower() == "false":
                return False
        return v  # type: ignore[return-value]


class SourceSignals(BaseModel):
    transcript: Literal["BUY", "HOLD", "WATCH"]
    news: Literal["BUY", "HOLD", "WATCH", "MIXED"] | None = None
    analysts: Literal["BUY", "HOLD", "WATCH"] | None = None
    reddit: Literal["BULLISH", "BEARISH", "MIXED"] | None = None


class Metrics(BaseModel):
    revenue: Metric
    eps: Metric
    operatingMargin: Metric
    guidance: Metric


class Risk(BaseModel):
    text: str
    level: Literal["high", "med", "low"]


class Sentiment(BaseModel):
    overall: float = Field(ge=0, le=100)
    ceoConfidence: float = Field(ge=0, le=100)
    forwardLooking: float = Field(ge=0, le=100)
    caution: float = Field(ge=0, le=100)


class ManagementTone(BaseModel):
    openingTone: str
    guidanceLanguage: str
    QATone: str
    keyTheme: str


class ReportJSON(BaseModel):
    company: str
    ticker: str
    quarter: str
    reportDate: str

    signal: Literal["BUY", "HOLD", "WATCH"]
    signalRationale: str = Field(min_length=1)
    signalConfidence: float = Field(ge=0, le=100)
    signalChanged: bool
    sourceSignals: SourceSignals
    contradictions: list[str] = Field(default_factory=list)

    metrics: Metrics

    executiveSummary: str
    keyHighlights: list[str]
    watchlist: list[str]

    risks: list[Risk] = Field(min_length=1)
    sentiment: Sentiment
    managementTone: ManagementTone

    @field_validator("quarter")
    @classmethod
    def normalise_quarter(cls, v: str) -> str:
        """Coerce common LLM variants to canonical 'Q1 2025' format."""
        v = v.strip()
        if _QUARTER_RE.match(v):
            return v
        # e.g. "Q1FY2025", "Q1-2025", "Q1/2025"
        m = re.match(r"Q([1-4])\s*[-/]?\s*(?:FY)?(\d{4})", v, re.IGNORECASE)
        if m:
            return f"Q{m.group(1)} {m.group(2)}"
        # e.g. "1Q 2025", "1Q2025"
        m = re.match(r"([1-4])Q\s*(\d{4})", v, re.IGNORECASE)
        if m:
            return f"Q{m.group(1)} {m.group(2)}"
        raise ValueError(f"quarter '{v}' is not a recognised format; expected 'Q1 2025'")

    @field_validator("contradictions")
    @classmethod
    def cap_contradictions(cls, v: list[str]) -> list[str]:
        return v[:3]

    @field_validator("keyHighlights")
    @classmethod
    def normalise_highlights(cls, v: list[str]) -> list[str]:
        if len(v) > 5:
            return v[:5]
        if len(v) < 5:
            raise ValueError(f"keyHighlights must have exactly 5 items, got {len(v)}")
        return v

    @field_validator("watchlist")
    @classmethod
    def normalise_watchlist(cls, v: list[str]) -> list[str]:
        if len(v) > 3:
            return v[:3]
        if len(v) < 3:
            raise ValueError(f"watchlist must have exactly 3 items, got {len(v)}")
        return v


class HistoryEntry(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    history: list[HistoryEntry] = Field(default_factory=list)
