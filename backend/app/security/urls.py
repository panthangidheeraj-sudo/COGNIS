"""URL policy and SSRF protection.

Every outbound URL — including URLs discovered on the web or proposed by the
LLM — passes ``check_url_syntax`` before any network access and
``check_resolved_host`` after DNS resolution. Redirect targets are re-checked
hop by hop by the HTTP client.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import urllib.parse
from collections.abc import Awaitable, Callable

from ..errors import UnsafeUrlError

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443, 8080, 8443}
BLOCKED_HOST_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet", ".arpa")
BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata", "instance-data", "169.254.169.254", "100.100.100.200", "fd00:ec2::254"}
MAX_URL_LENGTH = 2048

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "gclid", "fbclid", "mc_cid", "mc_eid", "_ga", "_gl", "ref", "ref_src", "igshid", "si", "trk",
}

Resolver = Callable[[str], Awaitable[list[str]]]


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return _ip_is_public(ip.ipv4_mapped)
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"))  # CGNAT
        or not ip.is_global
    )


def check_url_syntax(url: str) -> urllib.parse.SplitResult:
    """Reject anything that is not a plain public http(s) URL. Raises UnsafeUrlError."""
    if not isinstance(url, str) or not url.strip():
        raise UnsafeUrlError("empty URL")
    if len(url) > MAX_URL_LENGTH:
        raise UnsafeUrlError("URL too long")
    if any(ch in url for ch in ("\x00", "\r", "\n", "\t")):
        raise UnsafeUrlError("control characters in URL")
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"scheme not allowed: {parts.scheme or '(none)'}")
    if parts.username or parts.password:
        raise UnsafeUrlError("credentials in URL are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeUrlError("missing host")
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeUrlError("invalid port") from exc
    if port not in ALLOWED_PORTS:
        raise UnsafeUrlError(f"port not allowed: {port}")
    if host in BLOCKED_HOSTS or host.endswith(BLOCKED_HOST_SUFFIXES):
        raise UnsafeUrlError(f"host not allowed: {host}")
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
        if "." not in host:
            raise UnsafeUrlError("single-label hosts are not allowed") from None
        if not all(part and len(part) <= 63 for part in host.split(".")):
            raise UnsafeUrlError("malformed host") from None
    if literal is not None and not _ip_is_public(literal):
        raise UnsafeUrlError(f"non-public address: {host}")
    return parts


async def default_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


def _proxy_configured() -> bool:
    return any(os.environ.get(name) for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY"))


async def check_resolved_host(host: str, resolver: Resolver | None = None) -> None:
    """Every address a host resolves to must be public. Raises UnsafeUrlError."""
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if not _ip_is_public(literal):
            raise UnsafeUrlError(f"non-public address: {host}")
        return
    try:
        addresses = await (resolver or default_resolver)(host)
    except (OSError, UnicodeError) as exc:
        if _proxy_configured() and resolver is None:
            # Name resolution happens at the egress proxy, which enforces its own policy.
            return
        raise UnsafeUrlError(f"host does not resolve: {host}") from exc
    if not addresses:
        raise UnsafeUrlError(f"host does not resolve: {host}")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError as exc:
            raise UnsafeUrlError(f"unparseable address for {host}") from exc
        if not _ip_is_public(ip):
            raise UnsafeUrlError(f"{host} resolves to a non-public address")


def canonical_url(url: str) -> str:
    """Comparison/dedup form: lower-case scheme+host, no fragment, no tracking params, no default port."""
    parts = urllib.parse.urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower().rstrip(".")
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = urllib.parse.quote(urllib.parse.unquote(parts.path or "/"), safe="/%:@!$&'()*+,;=-._~")
    if len(path) > 1:
        path = path.rstrip("/")
    query = urllib.parse.urlencode(sorted((k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS))
    return urllib.parse.urlunsplit((scheme, netloc, path or "/", query, ""))


def normalize_website(value: str | None) -> str | None:
    """Registry 'hjemmeside' values are often bare domains ("www.example.no"). Return an https URL or None."""
    if not value:
        return None
    text = value.strip().strip("/").replace("\\", "/")
    if not text or " " in text:
        return None
    if not text.lower().startswith(("http://", "https://")):
        text = "https://" + text
    try:
        check_url_syntax(text)
    except UnsafeUrlError:
        return None
    return canonical_url(text)


def host_of(url: str | None) -> str:
    if not url:
        return ""
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


_MULTI_PART_SUFFIXES = {"co.uk", "com.au", "co.nz", "co.jp", "com.br", "co.za", "org.uk", "ac.uk", "gov.uk", "priv.no", "kommune.no", "fhs.no", "vgs.no", "mil.no", "stat.no", "dep.no", "herad.no"}


def registrable_domain(host_or_url: str | None) -> str:
    """eTLD+1 for the hosts we care about ("www.shop.example.no" → "example.no")."""
    host = host_of(host_or_url) if "/" in (host_or_url or "") else (host_or_url or "").lower().strip(".")
    host = host.removeprefix("www.")
    labels = [label for label in host.split(".") if label]
    if len(labels) <= 2:
        return ".".join(labels)
    if ".".join(labels[-2:]) in _MULTI_PART_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def same_site(url_a: str, url_b: str) -> bool:
    return bool(registrable_domain(host_of(url_a))) and registrable_domain(host_of(url_a)) == registrable_domain(host_of(url_b))
