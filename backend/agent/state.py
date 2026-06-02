from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    ticker: str
    user_intent: str
    plan: dict                              # planner output — tool priorities, weight overrides
    transcript: Any                         # TranscriptResult | None
    signals: dict                           # {reddit, news, analysts, market} — any can be None
    draft_report: dict
    final_report: dict
    reflection_notes: str
    iterations: int = 0                     # sufficiency check loop counter
    sufficient: bool = False                # did we get enough data to generate?
    errors: list[str] = field(default_factory=list)
    formatter_attempts: int = 0             # tracks formatter retry; max 1 retry allowed
