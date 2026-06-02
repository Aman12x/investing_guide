"""
Optional Langfuse observability.

Completely inert when LANGFUSE_PUBLIC_KEY is absent or langfuse is not installed.
All public symbols in this module are safe to import and call unconditionally.

Usage:
  from observability import make_anthropic_client, observe, update_trace

  client = make_anthropic_client()           # instrumented or plain Anthropic client
  @observe(name="my_span")                   # span under current trace, or new trace
  async def my_fn(): ...
  update_trace(user_id="AAPL", ...)          # annotate the current active trace
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# ── Langfuse init ─────────────────────────────────────────────────────────────

_enabled = False

try:
    from langfuse.decorators import observe, langfuse_context as _lf_ctx

    def update_trace(**kwargs) -> None:
        try:
            _lf_ctx.update_current_observation(**kwargs)
        except Exception:
            pass

    _lf_imported = True
except ImportError:
    _lf_imported = False

    def observe(func=None, **_kw):
        """No-op fallback when langfuse package is not installed."""
        if func is not None:
            return func
        return lambda f: f

    def update_trace(**_kw) -> None:
        pass


def setup() -> None:
    """Call once at application startup. Reads env vars and activates Langfuse."""
    global _enabled
    if not _lf_imported:
        logger.debug("langfuse package not installed — observability disabled")
        return

    pk = os.getenv("LANGFUSE_PUBLIC_KEY")
    sk = os.getenv("LANGFUSE_SECRET_KEY")
    if not (pk and sk):
        logger.info("LANGFUSE_PUBLIC_KEY not set — observability disabled")
        return

    try:
        from langfuse import Langfuse
        Langfuse(
            public_key=pk,
            secret_key=sk,
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
        _enabled = True
        logger.info(
            "Langfuse observability active (host=%s)",
            os.getenv("LANGFUSE_HOST", "cloud.langfuse.com"),
        )
    except Exception as exc:
        logger.warning("Langfuse setup failed — running without observability: %s", exc)


def is_enabled() -> bool:
    return _enabled


# ── Anthropic client factory ──────────────────────────────────────────────────

def make_anthropic_client():
    """
    Return a Langfuse-instrumented Anthropic AsyncAnthropic client when Langfuse
    is active, or a plain one otherwise.  All existing code that calls
    `client.messages.create(...)` works unchanged — Langfuse just intercepts it.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if _enabled:
        try:
            from langfuse.anthropic import anthropic as lf_ant
            return lf_ant.AsyncAnthropic(api_key=api_key)
        except Exception as exc:
            logger.warning("Langfuse Anthropic wrapper failed, using plain client: %s", exc)
    import anthropic
    return anthropic.AsyncAnthropic(api_key=api_key)
