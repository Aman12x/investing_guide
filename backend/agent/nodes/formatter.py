import logging

from pydantic import ValidationError

from agent.state import AgentState
from schemas import ReportJSON

logger = logging.getLogger(__name__)


class FormatterError(Exception):
    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(f"Validation failed on '{field}': {message}")


def formatter_node(state: AgentState) -> dict:
    """Validate final_report against ReportJSON schema. Retry analyst once on first failure."""
    report_dict = state.final_report if hasattr(state, "final_report") else state.get("final_report", {})
    ticker = state.ticker if hasattr(state, "ticker") else state.get("ticker", "")
    errors = list(state.errors if hasattr(state, "errors") else state.get("errors", []))
    formatter_attempts = (
        state.formatter_attempts if hasattr(state, "formatter_attempts")
        else state.get("formatter_attempts", 0)
    )

    if not report_dict:
        raise FormatterError("final_report", "no report produced by analyst/reflector")

    try:
        validated = ReportJSON(**report_dict)
        logger.info("Formatter: report for %s validated successfully", ticker)
        return {"final_report": validated.model_dump(), "errors": errors}

    except ValidationError as exc:
        first_err = exc.errors()[0]
        field = ".".join(str(loc) for loc in first_err["loc"])
        message = first_err["msg"]
        logger.warning("Formatter validation failed for %s on '%s': %s", ticker, field, message)
        errors.append(f"formatter_node: validation error on '{field}': {message}")

        if formatter_attempts < 1:
            # Signal a retry: clear reports so formatter_router routes back to analyst
            return {
                "final_report": {},
                "draft_report": {},
                "formatter_attempts": formatter_attempts + 1,
                "errors": errors,
            }

        raise FormatterError(field, message)


def formatter_router(state: AgentState) -> str:
    """Route to END on success, back to analyst for one retry on first failure."""
    final_report = (
        state.final_report if hasattr(state, "final_report") else state.get("final_report", {})
    )
    return "end" if final_report else "retry_analyst"
