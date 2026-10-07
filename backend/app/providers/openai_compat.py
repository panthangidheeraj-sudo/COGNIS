"""OpenAI-compatible chat-completions provider (Groq today; any compatible endpoint later).

Requests go through the shared ``HttpClient`` so they are budgeted, logged with
redaction, SSRF-checked and cached by request body (identical evidence →
identical answer, which keeps refreshes idempotent and cheap).
"""
from __future__ import annotations

import json

from ..config import Settings
from ..errors import LLMOutputError
from ..net.http import FetchResult, HttpClient
from ..runtime.budgets import CompanyBudget, RunBudget
from ..security.redaction import redact
from .llm_base import LLMResponse


def provider_error_detail(res: FetchResult) -> str:
    """The provider's own explanation of a failed call (e.g. "model does not exist"), redacted and short."""
    if not res.body:
        return ""
    try:
        data = json.loads(res.body.decode("utf-8", errors="replace"))
    except ValueError:
        return redact(res.body.decode("utf-8", errors="replace").strip())[:200]
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        message = " ".join(str(x) for x in (err.get("message"), f"[{err['code']}]" if err.get("code") else "") if x)
    else:
        message = str(err or "")
    return redact(message.strip())[:240]


class OpenAICompatibleProvider:
    def __init__(self, *, name: str, base_url: str, api_key: str | None, model: str, http: HttpClient, settings: Settings,
                 budget: CompanyBudget | RunBudget | None = None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.http = http
        self.settings = settings
        self.budget = budget
        self.calls = 0

    def with_budget(self, budget: CompanyBudget | RunBudget | None) -> OpenAICompatibleProvider:
        clone = OpenAICompatibleProvider(name=self.name, base_url=self.base_url, api_key=self.api_key, model=self.model, http=self.http, settings=self.settings, budget=budget)
        return clone

    def reasoning_params(self) -> tuple[dict, int]:
        """Extra request fields and extra output-token headroom for reasoning models (their hidden reasoning shares the token limit,
        so a tight ``max_tokens`` would leave an empty answer). Chosen by model family; ``LLM_REASONING_EFFORT`` overrides the level."""
        model, effort = (self.model or "").lower(), self.settings.llm_reasoning_effort
        if model.startswith("openai/gpt-oss"):
            level = effort or "low"
            return {"reasoning_effort": level, "include_reasoning": False}, {"low": 768, "medium": 1536, "high": 3072}.get(level, 768)
        if model.startswith("qwen/qwen3"):
            level = effort or "none"
            return {"reasoning_effort": level, "reasoning_format": "hidden"}, 0 if level == "none" else 1536
        return {}, 0

    async def chat(self, messages: list[dict[str, str]], *, max_tokens: int = 800, temperature: float = 0.0, json_mode: bool = False, task: str = "") -> LLMResponse:
        tripped = getattr(self.http, "tripped", {}).get("llm")
        if tripped:  # the key or model was refused earlier in this run: do not keep sending doomed requests
            raise LLMOutputError(f"{task or 'llm'}: skipped - {tripped}")
        extras, headroom = self.reasoning_params()
        body: dict = {"model": self.model, "messages": messages, "temperature": temperature,
                      "max_tokens": min(max_tokens, self.settings.llm_max_output_tokens) + headroom}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        estimated_in = sum(len(m.get("content", "")) for m in messages) / 4
        estimated_cost = estimated_in / 1000 * self.settings.llm_cost_per_1k_input_usd + body["max_tokens"] / 1000 * self.settings.llm_cost_per_1k_output_usd

        async def call(payload: dict):  # noqa: ANN202
            return await self.http.fetch(f"{self.base_url}/chat/completions", connector="llm", budget=self.budget, method="POST", json_body=payload, headers=headers,
                                         accept="application/json", expect="json", cost_usd=estimated_cost, cache_ttl=7 * 24 * 3600, optional=True,
                                         interval_key="llm" if self.settings.llm_min_interval_seconds > 0 else None,
                                         max_bytes=2_000_000)

        res = await call({**body, **extras})
        if extras and res.status in (400, 422):  # the endpoint refused a reasoning option: retry once with the plain request
            res = await call(body)
        if not res.ok:
            detail = provider_error_detail(res)
            if res.status in (401, 403, 404) and hasattr(self.http, "tripped"):
                self.http.tripped["llm"] = f"the language model was refused (HTTP {res.status}){': ' + detail if detail else ''}. Check GROQ_API_KEY / GROQ_MODEL."
            raise LLMOutputError(f"{task or 'llm'}: provider call failed ({res.classification}{' ' + str(res.status) if res.status else ''})" + (f": {detail}" if detail else ""))
        data = res.json() or {}
        choices = data.get("choices") or []
        text = ((choices[0] or {}).get("message") or {}).get("content", "") if choices else ""
        usage = data.get("usage") or {}
        self.calls += 1
        return LLMResponse(text=text or "", input_tokens=int(usage.get("prompt_tokens") or 0), output_tokens=int(usage.get("completion_tokens") or 0),
                           model=str(data.get("model") or self.model), cost_usd=0.0 if res.from_cache else estimated_cost, from_cache=res.from_cache)

    async def list_models(self) -> tuple[list[str], str]:
        """Model ids this key may use (``GET {base}/models``). Returns (ids, problem); problem is empty on success."""
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        res = await self.http.fetch(f"{self.base_url}/models", connector="llm", headers=headers, accept="application/json", expect="json", use_cache=False, optional=False)
        if not res.ok:
            detail = provider_error_detail(res)
            return [], f"{res.classification}{' ' + str(res.status) if res.status else ''}" + (f": {detail}" if detail else (f" ({res.error})" if res.error else ""))
        data = res.json() or {}
        return sorted(str(m.get("id")) for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id")), ""
