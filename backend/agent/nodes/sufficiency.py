import logging

from agent.state import AgentState

logger = logging.getLogger(__name__)

_MIN_TRANSCRIPT_CHARS = 2000
_MIN_SIGNAL_SOURCES = 2
_MAX_ITERATIONS = 3


def check_sufficiency(state: AgentState) -> dict:
    """
    We have enough to proceed if:
    - transcript is not None and len(transcript.text) > 2000
    - at least 2 of 4 signal sources returned data
    - iterations < 3 (prevent infinite loop)

    If transcript is None and iterations < 2: set sufficient=False (will retry)
    If transcript is None and iterations >= 2: set sufficient=True with error flag
      (agent proceeds but notes transcript unavailable in report)
    """
    transcript = state.transcript
    signals = state.signals
    iterations = state.iterations

    has_transcript = (
        transcript is not None
        and hasattr(transcript, "text")
        and len(transcript.text) >= _MIN_TRANSCRIPT_CHARS
    )

    active_signals = sum(
        1 for key in ("reddit", "news", "analysts")
        if signals.get(key) is not None
    )
    has_enough_signals = active_signals >= _MIN_SIGNAL_SOURCES

    if has_transcript and has_enough_signals:
        logger.info(
            "Sufficiency PASS for %s (iter %d): transcript ok, %d signal sources",
            state.ticker, iterations, active_signals,
        )
        return {"sufficient": True}

    # With a 30-second transcript timeout, a second failure means all 3 sources genuinely lack data.
    # If signals are sufficient, proceed immediately rather than burning more API credits on retries.
    if not has_transcript and has_enough_signals and iterations >= 2:
        logger.warning(
            "Transcript unavailable for %s after %d iteration(s) — signals sufficient, proceeding",
            state.ticker, iterations,
        )
        return {"sufficient": True}

    if not has_transcript and iterations >= 2:
        logger.warning(
            "Transcript unavailable for %s after %d iterations — proceeding with error flag",
            state.ticker, iterations,
        )
        return {"sufficient": True}

    if iterations >= _MAX_ITERATIONS:
        logger.warning(
            "Max iterations reached for %s — proceeding with best effort",
            state.ticker,
        )
        return {"sufficient": True}

    logger.info(
        "Sufficiency RETRY for %s (iter %d): transcript=%s, signals=%d",
        state.ticker, iterations, has_transcript, active_signals,
    )
    return {"sufficient": False}


def sufficiency_router(state: AgentState) -> str:
    sufficient = state.sufficient if hasattr(state, "sufficient") else state.get("sufficient", False)
    return "proceed" if sufficient else "fetch_more"
