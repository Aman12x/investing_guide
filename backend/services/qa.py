import logging
import os

from exceptions import ClaudeError
from observability import make_anthropic_client, observe, update_trace

logger = logging.getLogger(__name__)

_MAX_TRANSCRIPT_CHARS = 60_000
_MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = (
    "You are an expert earnings analyst. The user will ask questions about the provided earnings call transcript. "
    "Answer concisely and accurately. Cite specific quotes from the transcript when relevant. "
    "If the answer cannot be determined from the transcript, say so clearly. "
    "Never speculate beyond what the transcript and provided context support."
)


@observe(name="answer_question")
async def answer_question(
    ticker: str,
    transcript: str,
    question: str,
    history: list[dict],
) -> str:
    update_trace(user_id=ticker, session_id=ticker, input={"ticker": ticker, "question": question})
    client = make_anthropic_client()

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

    # Enforce strict user/assistant alternation; messages already end with "assistant"
    expected_role = "user"
    for turn in history:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if role == expected_role and content:
            messages.append({"role": role, "content": content})
            expected_role = "assistant" if expected_role == "user" else "user"

    # Final question must be from user; ensure last appended role isn't also user
    if messages[-1]["role"] != "assistant":
        messages.append({"role": "assistant", "content": "Go ahead."})
    messages.append({"role": "user", "content": question})

    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )
        if not response.content or not hasattr(response.content[0], "text"):
            raise ClaudeError("Claude returned empty or non-text response")
        return response.content[0].text
    except anthropic.APIError as exc:
        raise ClaudeError(f"Claude QA failed: {exc}") from exc
