"""Secret redaction for logs, errors and any text that leaves the process."""
from __future__ import annotations

import re
from typing import Any

from ..config import get_settings

_SECRET_QUERY = re.compile(r"(?i)\b(api[_-]?key|apikey|token|access_token|key|secret|password|signature|sig|auth)=([^&\s\"']+)")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_GROQ_KEY = re.compile(r"\bgsk_[A-Za-z0-9]{12,}\b")
_TAVILY_KEY = re.compile(r"\btvly-[A-Za-z0-9_-]{10,}")
_GENERIC_KEY = re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9]{16,}\b")
_SENSITIVE_HEADERS = {"authorization", "x-subscription-token", "ocp-apim-subscription-key", "cookie", "set-cookie", "x-api-key", "api-key"}


def _known_secrets() -> list[str]:
    s = get_settings()
    values = [s.groq_api_key, s.llm_api_key, s.tavily_api_key, s.proff_api_key, s.doffin_api_key, s.patentstyret_api_key, s.nav_feed_token]
    return [v for v in values if v and len(v) >= 6]


def redact(text: Any) -> str:
    value = str(text)
    for secret in _known_secrets():
        value = value.replace(secret, "[REDACTED]")
    value = _SECRET_QUERY.sub(lambda m: f"{m.group(1)}=[REDACTED]", value)
    value = _BEARER.sub(lambda m: f"{m.group(1)} [REDACTED]", value)
    value = _GROQ_KEY.sub("[REDACTED]", value)
    value = _TAVILY_KEY.sub("[REDACTED]", value)
    value = _GENERIC_KEY.sub("[REDACTED]", value)
    return value


def redact_headers(headers: dict[str, str] | None) -> dict[str, str]:
    return {k: ("[REDACTED]" if k.lower() in _SENSITIVE_HEADERS else v) for k, v in (headers or {}).items()}


def contains_secret(text: str) -> bool:
    """True when ``text`` contains a configured secret or a key-shaped token (used by leak tests)."""
    if any(secret in text for secret in _known_secrets()):
        return True
    return bool(_GROQ_KEY.search(text) or _TAVILY_KEY.search(text) or _GENERIC_KEY.search(text) or _BEARER.search(text))
