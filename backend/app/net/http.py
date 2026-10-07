"""The only way the backend talks to the network.

``HttpClient.fetch`` enforces, in order:
  1. URL syntax policy (scheme/host/port) — before anything else;
  2. cache lookup (cached responses keep their original retrieval time);
  3. robots.txt (for crawled pages);
  4. the run/company budget (charged before the request is sent);
  5. DNS → public-address check, re-done for every redirect hop;
  6. per-host concurrency and spacing;
  7. response size / content-type limits;
  8. bounded retries for transient failures only (respects Retry-After).

Every outcome is classified; connectors never see raw exceptions.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from ..config import get_settings
from ..core.util import now_iso, sha256_bytes, stable_id
from ..errors import UnsafeUrlError
from ..runtime.budgets import CompanyBudget, RunBudget
from ..runtime.rate_limits import HostLimiter
from ..security.redaction import redact
from ..security.urls import Resolver, canonical_url, check_resolved_host, check_url_syntax
from ..storage.cache import ResponseCache
from .robots import RobotsCache

Classification = Literal[
    "ok", "not_found", "gone", "blocked", "rate_limited", "server_error", "client_error", "timeout", "network",
    "unsafe_url", "too_large", "robots_disallowed", "budget_exhausted", "invalid_content",
]

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    classification: Classification
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    content_type: str = ""
    retrieved_at: str = ""
    elapsed_ms: int = 0
    retries: int = 0
    redirects: int = 0
    from_cache: bool = False
    error: str | None = None
    content_sha256: str | None = None
    effective_at: str | None = None  # set by snapshot replays (evaluator-owned bytes)

    @property
    def ok(self) -> bool:
        return self.classification == "ok"

    @property
    def bytes_received(self) -> int:
        return len(self.body)

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8", errors="replace")) if self.body else None

    def text(self) -> str:
        charset = "utf-8"
        if "charset=" in self.content_type:
            charset = self.content_type.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def classify_status(status: int) -> Classification:
    if 200 <= status < 300:
        return "ok"
    if status == 404:
        return "not_found"
    if status == 410:
        return "gone"
    if status in (401, 403, 451):
        return "blocked"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "server_error"
    return "client_error"


Budget = RunBudget | CompanyBudget | None


class HttpClient:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver | None = None,
        cache: ResponseCache | None = None,
        limiter: HostLimiter | None = None,
        recorder: Callable[[dict[str, Any]], None] | None = None,
        skip_dns_check: bool = False,
        sleep: Callable[[float], Any] | None = None,
    ):
        self.settings = get_settings()
        s = self.settings
        timeout = httpx.Timeout(s.http_timeout_seconds, connect=s.http_connect_timeout_seconds)
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": s.http_user_agent, "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en;q=0.7"},
        )
        self.resolver = resolver
        self.skip_dns_check = skip_dns_check or transport is not None and resolver is None
        self.cache = cache if s.cache_enabled else None
        self.limiter = limiter or HostLimiter()
        self.limiter.set_min_interval("brreg-account-copies", s.brreg_account_copies_min_interval_seconds)
        if s.llm_min_interval_seconds > 0:
            self.limiter.set_min_interval("llm", s.llm_min_interval_seconds)
        self.recorder = recorder
        self.robots = RobotsCache(self)
        self._sleep = sleep or asyncio.sleep
        self.total_requests = 0
        self.tripped: dict[str, str] = {}  # e.g. {"search": reason}: a source that must not be called again in this run

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------- helpers --
    @staticmethod
    def build_url(url: str, params: dict[str, Any] | None) -> str:
        if not params:
            return url
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        sep = "&" if urllib.parse.urlsplit(url).query else "?"
        return url + sep + urllib.parse.urlencode(clean, doseq=True)

    def _cache_key(self, connector: str, method: str, url: str, accept: str, body: bytes | None) -> str:
        return stable_id(connector, method, canonical_url(url), accept, sha256_bytes(body or b""), length=40)

    def _record(self, **row: Any) -> None:
        if self.recorder:
            try:
                row["url"] = redact(row.get("url", ""))
                self.recorder(row)
            except Exception:  # recording must never break research
                pass

    @staticmethod
    def _reserve(budget: Budget, connector: str, optional: bool, cost_usd: float, search: bool) -> bool:
        if budget is None:
            return True
        if isinstance(budget, CompanyBudget):
            return budget.reserve(connector=connector, requests=1, cost_usd=cost_usd, optional=optional, search=search)
        return budget.reserve(connector=connector, requests=1, cost_usd=cost_usd, optional=optional)

    @staticmethod
    def _refund(budget: Budget, connector: str, cost_usd: float, search: bool, requests: int = 1) -> None:
        if budget is None:
            return
        if isinstance(budget, CompanyBudget):
            budget.refund(connector=connector, requests=requests, cost_usd=cost_usd, search=search)
        else:
            budget.refund(connector=connector, requests=requests, cost_usd=cost_usd)

    # ------------------------------------------------------------- public ---
    async def fetch(
        self,
        url: str,
        *,
        connector: str,
        budget: Budget = None,
        optional: bool = True,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json_body: Any = None,
        accept: str = "*/*",
        max_bytes: int | None = None,
        cache_ttl: int | None = None,
        use_cache: bool = True,
        cost_usd: float = 0.0,
        search: bool = False,
        interval_key: str | None = None,
        check_robots: bool = False,
        expect: Literal["any", "json", "html", "pdf", "text"] = "any",
        run_id: str | None = None,
        org_number: str | None = None,
    ) -> FetchResult:
        full_url = self.build_url(url, params)
        started = time.monotonic()
        try:
            check_url_syntax(full_url)
        except UnsafeUrlError as exc:
            self._record(run_id=run_id, org_number=org_number, connector=connector, operation=method, url=full_url, classification="unsafe_url", http_status=0, duration_ms=0, retries=0, from_cache=0)
            return FetchResult(full_url, full_url, 0, "unsafe_url", error=str(exc), retrieved_at=now_iso())

        body_bytes = json.dumps(json_body).encode() if json_body is not None else None
        key = self._cache_key(connector, method, full_url, accept, body_bytes)
        if use_cache and self.cache is not None and method in ("GET", "POST"):
            entry = self.cache.get(key)
            if entry is not None and method == "POST" and not 200 <= entry.status < 300:
                entry = None  # a failed POST (e.g. an LLM call with a wrong model or key) must never be replayed from cache
            if entry is not None:
                if budget is not None:
                    (budget.run if isinstance(budget, CompanyBudget) else budget).record_cache_hit()
                self._record(run_id=run_id, org_number=org_number, connector=connector, operation=method, url=full_url, classification=classify_status(entry.status), http_status=entry.status, duration_ms=0, retries=0, from_cache=1)
                return FetchResult(full_url, entry.final_url, entry.status, classify_status(entry.status), entry.body, entry.headers, entry.content_type, entry.retrieved_at, 0, 0, 0, True, None, entry.content_sha256)

        if check_robots and self.settings.respect_robots:
            allowed = await self.robots.allowed(full_url, budget=budget, optional=optional, run_id=run_id, org_number=org_number)
            if allowed is False:
                self._record(run_id=run_id, org_number=org_number, connector=connector, operation=method, url=full_url, classification="robots_disallowed", http_status=0, duration_ms=0, retries=0, from_cache=0)
                return FetchResult(full_url, full_url, 0, "robots_disallowed", error="disallowed by robots.txt", retrieved_at=now_iso())

        if not self._reserve(budget, connector, optional, cost_usd, search):
            self._record(run_id=run_id, org_number=org_number, connector=connector, operation=method, url=full_url, classification="budget_exhausted", http_status=0, duration_ms=0, retries=0, from_cache=0)
            return FetchResult(full_url, full_url, 0, "budget_exhausted", error="budget exhausted", retrieved_at=now_iso())

        limit = max_bytes or (self.settings.max_pdf_bytes if expect == "pdf" else self.settings.max_fetch_bytes)
        req_headers = {"Accept": accept, **(headers or {})}
        result = await self._fetch_with_retries(full_url, method, req_headers, body_bytes, limit, budget, connector, optional, interval_key)
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        if result.ok:
            result = self._check_content(result, expect)
        if cost_usd and not result.ok:
            self._refund(budget, connector, cost_usd, False, requests=0)  # providers do not bill failed calls
        cacheable = result.classification == "ok" or (method == "GET" and result.classification in ("not_found", "gone"))
        if cacheable and self.cache is not None and use_cache:
            ttl = cache_ttl if cache_ttl is not None else self.settings.cache_ttl_web_seconds
            if result.classification != "ok":
                ttl = min(ttl, 3600)
            self.cache.put(key=key, source=connector, url=full_url, final_url=result.final_url, status=result.status, content_type=result.content_type,
                           headers={k: v for k, v in result.headers.items() if k in ("content-type", "last-modified", "etag", "date")},
                           body=result.body, content_sha256=result.content_sha256 or "", retrieved_at=result.retrieved_at, ttl_seconds=ttl)
        self._record(run_id=run_id, org_number=org_number, connector=connector, operation=method, url=full_url, classification=result.classification,
                     http_status=result.status, duration_ms=result.elapsed_ms, retries=result.retries, from_cache=0)
        return result

    # ------------------------------------------------------------- internals
    def _check_content(self, result: FetchResult, expect: str) -> FetchResult:
        ctype = result.content_type.lower()
        if expect == "pdf" and not result.body.startswith(b"%PDF"):
            result.classification = "invalid_content"
            result.error = "expected a PDF document"
        elif expect == "json":
            try:
                result.json()
            except ValueError:
                result.classification = "invalid_content"
                result.error = "malformed JSON payload"
        elif expect == "html" and not ("html" in ctype or "xml" in ctype or ctype.startswith("text/") or not ctype):
            result.classification = "invalid_content"
            result.error = f"unexpected content type {ctype}"
        return result

    async def _fetch_with_retries(self, url: str, method: str, headers: dict[str, str], body: bytes | None, limit: int, budget: Budget, connector: str, optional: bool, interval_key: str | None) -> FetchResult:
        s = self.settings
        attempt = 0
        last: FetchResult | None = None
        while True:
            last = await self._fetch_once(url, method, headers, body, limit, budget, connector, optional, interval_key)
            last.retries = attempt
            retryable = last.classification in ("timeout", "network") or last.status in RETRYABLE_STATUS
            if not retryable or attempt >= s.retry_attempts:
                return last
            delay = min(s.retry_max_delay_seconds, s.retry_base_delay_seconds * (2 ** attempt)) * (0.75 + random.random() * 0.5)
            retry_after = last.headers.get("retry-after")
            if retry_after:
                try:
                    wanted = float(retry_after)
                except ValueError:
                    wanted = s.retry_max_delay_seconds + 1
                if wanted > s.retry_max_delay_seconds:
                    return last  # the source asked for a longer pause than our budget allows
                delay = max(delay, wanted)
            if not self._reserve(budget, connector, optional, 0.0, False):
                return last
            attempt += 1
            await self._sleep(delay)

    async def _fetch_once(self, url: str, method: str, headers: dict[str, str], body: bytes | None, limit: int, budget: Budget, connector: str, optional: bool, interval_key: str | None) -> FetchResult:
        current = url
        redirects = 0
        retrieved_at = now_iso()
        while True:
            try:
                parts = check_url_syntax(current)
                if not self.skip_dns_check:
                    await check_resolved_host(parts.hostname or "", self.resolver)
            except UnsafeUrlError as exc:
                return FetchResult(url, current, 0, "unsafe_url", error=str(exc), retrieved_at=retrieved_at, redirects=redirects)
            host = (parts.hostname or "").lower()
            try:
                async with self.limiter.slot(host, interval_key):
                    self.total_requests += 1
                    retrieved_at = now_iso()
                    request = self._client.build_request(method, current, headers=headers, content=body)
                    response = await self._client.send(request, stream=True)
                    try:
                        if response.is_redirect and response.headers.get("location"):
                            location = urllib.parse.urljoin(current, response.headers["location"])
                            await response.aclose()
                            redirects += 1
                            if redirects > self.settings.max_redirects:
                                return FetchResult(url, location, response.status_code, "client_error", error="too many redirects", retrieved_at=retrieved_at, redirects=redirects)
                            if not self._reserve(budget, connector, optional, 0.0, False):
                                return FetchResult(url, location, 0, "budget_exhausted", error="budget exhausted during redirect", retrieved_at=retrieved_at, redirects=redirects)
                            current = location
                            if method == "POST" and response.status_code in (301, 302, 303):
                                method, body = "GET", None
                            continue
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > limit:
                                return FetchResult(url, str(response.url), response.status_code, "too_large", error=f"response larger than {limit} bytes", retrieved_at=retrieved_at, redirects=redirects,
                                                   headers={k.lower(): v for k, v in response.headers.items()})
                            chunks.append(chunk)
                        data = b"".join(chunks)
                    finally:
                        await response.aclose()
            except httpx.TimeoutException as exc:
                return FetchResult(url, current, 0, "timeout", error=redact(f"timeout: {type(exc).__name__}"), retrieved_at=retrieved_at, redirects=redirects)
            except (httpx.TransportError, OSError) as exc:
                return FetchResult(url, current, 0, "network", error=redact(f"network error: {type(exc).__name__}"), retrieved_at=retrieved_at, redirects=redirects)
            hdrs = {k.lower(): v for k, v in response.headers.items()}
            status = response.status_code
            return FetchResult(
                url=url, final_url=str(response.url), status=status, classification=classify_status(status), body=data, headers=hdrs,
                content_type=hdrs.get("content-type", ""), retrieved_at=retrieved_at, redirects=redirects,
                error=None if 200 <= status < 300 else f"HTTP {status}", content_sha256=sha256_bytes(data),
            )
