"""robots.txt handling (RFC 9309 semantics).

4xx on robots.txt → no restrictions; 5xx / unreachable → treat the site as
disallowed; parsed rules are cached per origin for the life of the client.
"""
from __future__ import annotations

import urllib.parse
import urllib.robotparser
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .http import HttpClient

ROBOTS_AGENT = "COGNIS-Signalpost"


class RobotsCache:
    def __init__(self, client: HttpClient):
        self.client = client
        self._rules: dict[str, urllib.robotparser.RobotFileParser | bool] = {}
        self.sitemaps: dict[str, list[str]] = {}

    async def allowed(self, url: str, *, budget: Any = None, optional: bool = True, run_id: str | None = None, org_number: str | None = None) -> bool | None:
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}".lower()
        if origin not in self._rules:
            result = await self.client.fetch(origin + "/robots.txt", connector="robots", budget=budget, optional=optional, accept="text/plain,*/*;q=0.5",
                                             max_bytes=500_000, cache_ttl=self.client.settings.cache_ttl_web_seconds, run_id=run_id, org_number=org_number)
            if result.classification == "budget_exhausted":
                return None
            if result.ok:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(result.text().splitlines())
                self._rules[origin] = parser
                self.sitemaps[origin] = list(parser.site_maps() or [])
            elif result.status and 400 <= result.status < 500:
                self._rules[origin] = True
            elif result.classification in ("unsafe_url",):
                self._rules[origin] = False
            else:
                self._rules[origin] = False  # 5xx / timeout / network: assume complete disallow (RFC 9309 §2.3.1.4)
        rule = self._rules[origin]
        if isinstance(rule, bool):
            return rule
        return rule.can_fetch(ROBOTS_AGENT, url)
