"""LLM provider abstraction. Business logic never imports a vendor SDK.

``structured()`` returns a validated Pydantic model or raises
``LLMOutputError`` after one corrective retry — model output is never
``eval``-ed and its ids/URLs/numbers are re-validated by the caller.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from ..errors import LLMOutputError

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    cost_usd: float = 0.0
    from_cache: bool = False


class LLMProvider(Protocol):
    name: str
    model: str

    async def chat(self, messages: list[dict[str, str]], *, max_tokens: int = 800, temperature: float = 0.0, json_mode: bool = False, task: str = "") -> LLMResponse: ...


_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def parse_json_loose(text: str) -> Any:
    """Strict JSON first; then the first {...} block (handles code fences). Never evaluates code."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    try:
        return json.loads(text)
    except ValueError:
        match = _JSON_BLOCK.search(text)
        if match:
            try:
                return json.loads(match.group(0))
            except ValueError:
                return None
    return None


async def structured(provider: LLMProvider, messages: list[dict[str, str]], schema: type[T], *, max_tokens: int = 900, task: str = "",
                     on_response: Any = None) -> T:
    """Ask for JSON matching ``schema``; one corrective retry; then raise LLMOutputError."""
    attempt_messages = list(messages)
    last_error = ""
    for _attempt in range(2):
        response = await provider.chat(attempt_messages, max_tokens=max_tokens, temperature=0.0, json_mode=True, task=task)
        if on_response:
            on_response(response)
        data = parse_json_loose(response.text)
        if data is not None:
            try:
                return schema.model_validate(data)
            except ValidationError as exc:
                last_error = str(exc)[:600]
        else:
            last_error = "response was not valid JSON"
        attempt_messages = [*messages, {"role": "assistant", "content": response.text[:2000]},
                            {"role": "user", "content": f"Your previous answer was invalid ({last_error}). Reply with JSON only, matching the requested schema exactly."}]
    raise LLMOutputError(f"{task or 'llm'}: invalid structured output: {last_error}")
