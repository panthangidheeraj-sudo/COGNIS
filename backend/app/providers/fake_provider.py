"""Deterministic fake LLM for tests and offline development.

It never invents facts: extraction answers quote the first sentences of the
supplied page excerpts verbatim, synthesis restates the supplied facts, and
malformed-output scenarios can be forced for robustness tests.
"""
from __future__ import annotations

import json
import re

from .llm_base import LLMResponse


class FakeProvider:
    name = "fake"
    model = "fake-deterministic-1"

    def __init__(self, *, malformed: bool = False, script: dict[str, str] | None = None):
        self.malformed = malformed
        self.script = script or {}
        self.calls = 0

    def with_budget(self, budget):  # noqa: ANN001 — interface parity
        return self

    async def chat(self, messages: list[dict[str, str]], *, max_tokens: int = 800, temperature: float = 0.0, json_mode: bool = False, task: str = "") -> LLMResponse:
        self.calls += 1
        if self.malformed:
            return LLMResponse(text="Sure! Here is what I found: {not json", model=self.model)
        if task in self.script:
            return LLMResponse(text=self.script[task], model=self.model)
        user = messages[-1]["content"] if messages else ""
        if task == "extract_website":
            match = re.search(r"PAGE \[(?P<url>[^\]]+)\]\n(?P<text>.+?)(?:\n\nPAGE \[|\Z)", user, re.S)
            if not match:
                return LLMResponse(text=json.dumps({"business_description": None}), model=self.model)
            sentences = re.split(r"(?<=[.!?])\s+", match.group("text").strip())
            quote = next((s for s in sentences if len(s) > 40), sentences[0] if sentences else "")
            return LLMResponse(text=json.dumps({"business_description": {"text": quote, "quote": quote, "page": match.group("url")},
                                                "products_services": [], "people": [], "locations": []}), model=self.model)
        if task == "synthesis":
            facts = re.findall(r"^- (.+)$", user, re.M)
            return LLMResponse(text=json.dumps({"summary": " ".join(f.split(" [")[0].rstrip(".") + "." for f in facts[:4])}), model=self.model)
        if task == "plan":
            missing = re.search(r"Still unknown: (.*)", user)
            wanted = [w.strip() for w in (missing.group(1) if missing else "").split(",")]
            options = re.findall(r"^- tool=(\S+) arg=(\S+) \(([^)]*)\)", user, re.M)
            picked = [{"tool": t, "arg": a, "reason": f"fills {k}"} for t, a, k in options if k in wanted][:2]
            return LLMResponse(text=json.dumps({"actions": picked, "done": not picked}), model=self.model)
        if task == "interpret":
            return LLMResponse(text=json.dumps({"filters": [], "keywords": None}), model=self.model)
        if task == "explain":
            return LLMResponse(text=json.dumps({"synthesis": None}), model=self.model)
        if task == "ask":
            return LLMResponse(text=json.dumps({"blocks": []}), model=self.model)
        return LLMResponse(text=json.dumps({}), model=self.model)
