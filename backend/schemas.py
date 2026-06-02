from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class Metric(BaseModel):
    value: str
    delta: str
    beat: bool


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
    signalRationale: str
    signalConfidence: float = Field(ge=0, le=100)
    signalChanged: bool
    sourceSignals: SourceSignals
    contradictions: list[str] = Field(default_factory=list)

    metrics: Metrics

    executiveSummary: str
    keyHighlights: list[str]
    watchlist: list[str]

    risks: list[Risk]
    sentiment: Sentiment
    managementTone: ManagementTone

    @field_validator("contradictions")
    @classmethod
    def cap_contradictions(cls, v: list[str]) -> list[str]:
        if len(v) > 3:
            raise ValueError(f"contradictions must have at most 3 items, got {len(v)}")
        return v

    @field_validator("keyHighlights")
    @classmethod
    def normalise_highlights(cls, v: list[str]) -> list[str]:
        if len(v) != 5:
            raise ValueError(f"keyHighlights must have exactly 5 items, got {len(v)}")
        return v

    @field_validator("watchlist")
    @classmethod
    def normalise_watchlist(cls, v: list[str]) -> list[str]:
        if len(v) != 3:
            raise ValueError(f"watchlist must have exactly 3 items, got {len(v)}")
        return v


class AskRequest(BaseModel):
    question: str
    history: list[dict] = Field(default_factory=list)
