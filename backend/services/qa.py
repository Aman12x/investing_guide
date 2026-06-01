import logging
import os

import anthropic

from exceptions import ClaudeError

logger = logging.getLogger(__name__)

_MAX_TRANSCRIPT_CHARS = 60_000
_MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = (
    "You are an expert earnings analyst. The user will ask questions about the provided earnings call transcript. "
    "Answer concisely and accurately. Cite specific quotes from the transcript when relevant. "
    "If the answer cannot be determined from the transcript, say so clearly. "
    "Never speculate beyond what the transcript and provided context support."
)


async def answer_question(
    ticker: str,
    transcript: str,
    question: str,
    history: list[dict],
) -> str:
    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    truncated = transcript[:_MAX_TRANSCRIPT_CHARS]

    # Seed the conversation with the transcript so it's always in context
    messages: list[dict] = [
        {
            "role": "user",
            "content": f"=== EARNINGS CALL TRANSCRIPT FOR {ticker} ===\n{truncated}\n=== END TRANSCRIPT ===\n\nI'll ask you questions about this call.",
        },
        {
            "role": "assistant",
            "content": f"I've read the {ticker} earnings call transcript. What would you like to know?",
        },
    ]

    for turn in history:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": question})

    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )
        return response.content[0].text
    except anthropic.APIError as exc:
        raise ClaudeError(f"Claude QA failed: {exc}") from exc
