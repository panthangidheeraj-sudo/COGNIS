"""LLM tasks with strict Python validation and deterministic fallbacks.

The LLM reads evidence and writes language; Python checks every output:
quotes must exist verbatim on the cited page, numbers in prose must appear in
the supplied facts, ids must be ids we gave it, filters must be from the
allowed set. Anything that fails validation is discarded and the
deterministic fallback is used. The LLM never fetches anything itself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from ..connectors.website import SiteCrawl
from ..core.util import clean_ws, fold, truncate
from ..errors import LLMOutputError
from ..evidence.models import Observation
from ..extraction.html import PageDoc, text_contains
from ..extraction.web_facts import _page_base
from ..identity.model import CanonicalIdentity
from ..providers.llm_base import LLMProvider, LLMResponse, structured
from ..runtime.budgets import CompanyBudget, RunBudget
from . import prompts

SPECULATIVE = re.compile(r"\b(leading|innovative|world[- ]class|best|likely|probably|expected to|will (grow|increase|decline)|forecast|recommend|should invest|market leader)\b", re.I)


# ----------------------------------------------------------------- schemas --
class QuotedText(BaseModel):
    text: str = Field(max_length=800)
    quote: str = Field(max_length=900)
    page: str = Field(max_length=600)


class NamedQuote(BaseModel):
    name: str = Field(max_length=160)
    quote: str = Field(max_length=900)
    page: str = Field(max_length=600)


class WebsiteExtraction(BaseModel):
    business_description: QuotedText | None = None
    products_services: list[NamedQuote] = Field(default_factory=list, max_length=12)


class SynthesisOut(BaseModel):
    summary: str | None = Field(default=None, max_length=1200)


class PlannedAction(BaseModel):
    tool: str = Field(max_length=40)
    arg: str = Field(default="", max_length=600)
    reason: str = Field(default="", max_length=300)


class PlanOut(BaseModel):
    actions: list[PlannedAction] = Field(default_factory=list, max_length=6)
    done: bool = False


class FilterOut(BaseModel):
    key: str = Field(max_length=40)
    value: str | float | int | bool


class InterpretOut(BaseModel):
    filters: list[FilterOut] = Field(default_factory=list, max_length=10)
    keywords: str | None = Field(default=None, max_length=200)


class ExplainOut(BaseModel):
    synthesis: str | None = Field(default=None, max_length=900)


class AskBlock(BaseModel):
    text: str = Field(max_length=900)
    fact_ids: list[str] = Field(default_factory=list, max_length=12)


class AskOut(BaseModel):
    blocks: list[AskBlock] = Field(default_factory=list, max_length=8)


class ColumnOut(BaseModel):
    field: str | None = None
    title: str = Field(default="", max_length=80)


# ------------------------------------------------------------------ runner --
@dataclass
class LLMRunner:
    provider: LLMProvider | None
    budget: CompanyBudget | RunBudget | None = None
    calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    errors: list[dict[str, str]] = field(default_factory=list)
    model: str | None = None

    @property
    def enabled(self) -> bool:
        if self.provider is None:
            return False
        if isinstance(self.budget, CompanyBudget):
            return self.budget.allow_llm()
        return True

    def _record(self, response: LLMResponse) -> None:
        self.calls += 1
        self.tokens += response.input_tokens + response.output_tokens
        self.cost_usd += response.cost_usd
        self.model = response.model or self.model
        if isinstance(self.budget, CompanyBudget):
            self.budget.record_llm(tokens=response.input_tokens + response.output_tokens, cost_usd=0.0)  # cost already charged by the HTTP layer
        elif isinstance(self.budget, RunBudget):
            self.budget.record_llm(tokens=response.input_tokens + response.output_tokens, cost_usd=0.0)

    async def run(self, task: str, system: str, user: str, schema: type[BaseModel], *, max_tokens: int = 700) -> Any:
        if not self.enabled:
            return None
        provider = self.provider.with_budget(self.budget) if hasattr(self.provider, "with_budget") else self.provider  # type: ignore[union-attr]
        try:
            return await structured(provider, [{"role": "system", "content": system}, {"role": "user", "content": user}], schema, max_tokens=max_tokens, task=task,
                                    on_response=self._record)
        except LLMOutputError as exc:
            self.errors.append({"stage": f"llm:{task}", "error": str(exc)[:300]})
            return None
        except Exception as exc:  # provider bugs must never break research
            self.errors.append({"stage": f"llm:{task}", "error": f"{type(exc).__name__}"})
            return None


# ---------------------------------------------------------- website facts --
def _page_excerpt(doc: PageDoc, limit: int) -> str:
    parts = []
    if doc.description:
        parts.append(doc.description)
    parts.extend(doc.headings[:6])
    parts.extend(doc.paragraphs[:14])
    return truncate("\n".join(dict.fromkeys(p for p in parts if p)), limit)


def _find_page(quote: str, page_url: str, docs: list[PageDoc]) -> PageDoc | None:
    ordered = sorted(docs, key=lambda d: 0 if d.final_url.rstrip("/") == page_url.rstrip("/") else 1)
    for doc in ordered:
        hay = "\n".join([doc.text, doc.description, " ".join(doc.paragraphs)])
        if text_contains(hay, quote):
            return doc
    return None


async def extract_website_facts(runner: LLMRunner, crawl: SiteCrawl, identity: CanonicalIdentity) -> list[Observation]:
    """LLM reads verified pages; only quote-verified values become observations."""
    if not crawl.verified or not runner.enabled:
        return []
    docs = (crawl.docs("about") + crawl.docs("products") + [d for d in [crawl.homepage] if d])[:3]
    if not docs:
        return []
    pages = "\n\n".join(f"PAGE [{d.final_url}]\n{_page_excerpt(d, 1700)}" for d in docs)
    out = await runner.run("extract_website", prompts.EXTRACT_WEBSITE_SYSTEM,
                           prompts.EXTRACT_WEBSITE_USER.format(legal_name=identity.legal_name, org_number=identity.org_number, industry=identity.industry_label or "unknown",
                                                               pages=pages), WebsiteExtraction, max_tokens=700)
    if out is None:
        return []
    obs: list[Observation] = []
    desc = out.business_description
    if desc and len(clean_ws(desc.quote)) >= 25:
        page = _find_page(desc.quote, desc.page, crawl.docs())
        if page is not None:
            translation = clean_ws(desc.text) if desc.text and fold(desc.text) != fold(desc.quote) and not SPECULATIVE.search(desc.text) else None
            obs.append(Observation(field="business_description", value=clean_ws(desc.quote), claim_span=clean_ws(desc.quote), extraction_method="llm_quote_verified",
                                   label="What the company does (company-stated)", document_title=page.title or None,
                                   attributes={"quote_verified": True, "translation": translation, "model": runner.model}, **_page_base(crawl, page)))
    seen: set[str] = set()
    for item in out.products_services[:6]:
        name = clean_ws(item.name)
        if not name or fold(name) in seen or len(clean_ws(item.quote)) < 10:
            continue
        page = _find_page(item.quote, item.page, crawl.docs())
        # The product name itself must appear in the verified quote — no invented names.
        if page is None or fold(name) not in fold(item.quote):
            continue
        seen.add(fold(name))
        obs.append(Observation(field="product_or_service", value=name, key_suffix=fold(name), claim_span=clean_ws(item.quote), extraction_method="llm_quote_verified",
                               label="Product or service (company-stated)", document_title=page.title or None, attributes={"quote_verified": True, "model": runner.model},
                               **_page_base(crawl, page)))
    return obs


# --------------------------------------------------------------- synthesis --
NUMBER = re.compile(r"\d[\d\s.,  ]*\d|\d")


CURRENCY_CODES = ("NOK", "SEK", "DKK", "EUR", "USD", "GBP", "CHF", "ISK", "JPY", "CNY", "CAD", "AUD", "PLN", "CZK", "HUF", "INR", "BRL", "SGD", "HKD", "KRW", "ZAR", "AED")
_CURRENCY_BEFORE_AMOUNT = re.compile(r"\b(" + "|".join(CURRENCY_CODES) + r")\b\s*[−-]?\d")
_CURRENCY_AFTER_AMOUNT = re.compile(r"\d[\d\s.,  ]*[kMB]?\s+(" + "|".join(CURRENCY_CODES) + r")\b")


def currencies_grounded(text: str, facts_text: str) -> bool:
    """A currency code written next to an amount must be one the facts themselves state: a model may not relabel a USD amount as NOK."""
    stated = set(re.findall(r"\b[A-Z]{3}\b", facts_text))
    used = set(_CURRENCY_BEFORE_AMOUNT.findall(text)) | set(_CURRENCY_AFTER_AMOUNT.findall(text))
    return used <= stated


def numbers_grounded(text: str, facts_text: str) -> bool:
    """Every number in ``text`` must occur (digits only) in the facts, and every currency code next to an amount must be stated by the facts."""
    if not currencies_grounded(text, facts_text):
        return False
    fact_digits = re.sub(r"\D", " ", facts_text)
    fact_numbers = set(re.sub(r"[\s.,  ]", "", m) for m in NUMBER.findall(facts_text))
    joined = re.sub(r"\s+", "", fact_digits)
    for m in NUMBER.findall(text):
        digits = re.sub(r"[\s.,  ]", "", m)
        if not digits:
            continue
        if digits in fact_numbers:
            continue
        if len(digits) <= 2 and digits in joined:
            continue
        return False
    return True


async def synthesize(runner: LLMRunner, identity: CanonicalIdentity, fact_lines: list[tuple[str, str]]) -> tuple[str | None, str]:
    """Return (summary, method). ``fact_lines`` = [(text, evidence_id)]."""
    if not fact_lines or not runner.enabled:
        return None, "none"
    facts = "\n".join(f"- {text} [{eid}]" for text, eid in fact_lines)
    out = await runner.run("synthesis", prompts.SYNTHESIS_SYSTEM,
                           prompts.SYNTHESIS_USER.format(legal_name=identity.legal_name, org_number=identity.org_number, facts=facts), SynthesisOut, max_tokens=300)
    text = clean_ws(out.summary) if out and out.summary else ""
    if not text:
        return None, "none"
    if len(text) > 900 or SPECULATIVE.search(text) or not numbers_grounded(text, facts):
        runner.errors.append({"stage": "llm:synthesis", "error": "summary rejected by grounding check (ungrounded number or speculative wording)"})
        return None, "rejected"
    return text, "llm_grounded"


# ----------------------------------------------------------------- planner --
async def plan_actions(runner: LLMRunner, identity: CanonicalIdentity, known: list[str], missing: list[str], options: list[dict[str, str]], budget_text: str,
                       max_actions: int) -> list[dict[str, str]] | None:
    """LLM proposes actions; only options we offered are accepted (by exact tool+arg)."""
    if not options or not runner.enabled:
        return None
    listing = "\n".join(f"- tool={o['tool']} arg={o['arg']} ({o.get('hint', '')})" for o in options)
    out = await runner.run("plan", prompts.PLANNER_SYSTEM, prompts.PLANNER_USER.format(
        legal_name=identity.legal_name, org_number=identity.org_number, known=", ".join(known) or "none", missing=", ".join(missing) or "nothing",
        budget=budget_text, max_actions=max_actions, options=listing), PlanOut, max_tokens=400)
    if out is None:
        return None
    allowed = {(o["tool"], o["arg"]) for o in options}
    chosen = []
    for action in out.actions:
        if (action.tool, action.arg) in allowed and all((c["tool"], c["arg"]) != (action.tool, action.arg) for c in chosen):
            chosen.append({"tool": action.tool, "arg": action.arg, "reason": truncate(action.reason, 200)})
        if len(chosen) >= max_actions:
            break
    return chosen


# --------------------------------------------------------------- interpret --
async def interpret_with_llm(runner: LLMRunner, text: str, allowed_keys: set[str]) -> tuple[list[dict[str, Any]], str | None] | None:
    out = await runner.run("interpret", prompts.INTERPRET_SYSTEM, prompts.INTERPRET_USER.format(text=truncate(text, 400)), InterpretOut, max_tokens=300)
    if out is None:
        return None
    filters = []
    for f in out.filters:
        if f.key not in allowed_keys:
            continue
        if isinstance(f.value, str):
            # Text values must come from the user's own words.
            if not f.value.strip() or fold(f.value) not in fold(text):
                continue
        filters.append({"key": f.key, "value": f.value})
    keywords = out.keywords if out.keywords and fold(out.keywords) in fold(text) else None
    return filters, keywords


# ----------------------------------------------------------------- explain --
async def explain_synthesis(runner: LLMRunner, question: str, observed: list[str], reported: list[str]) -> str | None:
    if not observed or not runner.enabled:
        return None
    out = await runner.run("explain", prompts.EXPLAIN_SYSTEM, prompts.EXPLAIN_USER.format(
        question=question, observed="\n".join(f"- {o}" for o in observed), reported="\n".join(f'- "{r}"' for r in reported) or "(none)"), ExplainOut, max_tokens=250)
    text = clean_ws(out.synthesis) if out and out.synthesis else ""
    if not text or SPECULATIVE.search(text) or not numbers_grounded(text, "\n".join(observed + reported)):
        return None
    return text


# --------------------------------------------------------------------- ask --
async def answer_question(runner: LLMRunner, identity: CanonicalIdentity, question: str, facts: list[tuple[str, str]]) -> list[dict[str, Any]] | None:
    """facts = [(fact_id, text)]. Returns blocks citing only given fact ids."""
    if not facts or not runner.enabled:
        return None
    listing = "\n".join(f"[{fid}] {text}" for fid, text in facts)
    out = await runner.run("ask", prompts.ASK_SYSTEM, prompts.ASK_USER.format(legal_name=identity.legal_name, org_number=identity.org_number, question=truncate(question, 400),
                                                                            facts=listing), AskOut, max_tokens=600)
    if out is None:
        return None
    valid = {fid for fid, _ in facts}
    blocks = []
    for block in out.blocks:
        ids = [i for i in block.fact_ids if i in valid]
        cited_text = "\n".join(text for fid, text in facts if fid in ids)
        if not ids or SPECULATIVE.search(block.text) or not numbers_grounded(block.text, cited_text):
            continue
        blocks.append({"text": clean_ws(block.text), "fact_ids": ids})
    return blocks


async def map_column(runner: LLMRunner, instruction: str, fields: dict[str, str]) -> tuple[str | None, str] | None:
    out = await runner.run("column", prompts.COLUMN_SYSTEM, prompts.COLUMN_USER.format(instruction=truncate(instruction, 300),
                                                                                     fields="\n".join(f"- {k}: {v}" for k, v in fields.items())), ColumnOut, max_tokens=120)
    if out is None:
        return None
    return (out.field if out.field in fields else None), clean_ws(out.title)[:60]
