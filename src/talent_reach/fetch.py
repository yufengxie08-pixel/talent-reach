"""Conservative public-page fetcher with SSRF and robots.txt protections."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx


USER_AGENT = "TalentReach/0.4 (+public-profile-research; respects robots.txt)"
MAX_BYTES = 1_500_000
_ROBOTS_CACHE: dict[str, tuple[float, RobotFileParser]] = {}
_LAST_REQUEST: dict[str, float] = {}
_RATE_LOCK = asyncio.Lock()


class PublicFetchError(RuntimeError):
    """A public page could not be fetched safely."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PublicPage:
    url: str
    status_code: int
    content_type: str
    text: str


@dataclass(frozen=True)
class PublicBinary:
    url: str
    status_code: int
    content_type: str
    data: bytes


def _is_forbidden_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


async def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise PublicFetchError("invalid_scheme", "Only http and https URLs are supported")
    if parsed.username or parsed.password:
        raise PublicFetchError("embedded_credentials", "URLs containing credentials are rejected")
    host = parsed.hostname
    if not host:
        raise PublicFetchError("missing_host", "URL has no hostname")
    if host.lower() == "localhost":
        raise PublicFetchError("private_network", "Local and private-network URLs are rejected")
    try:
        if _is_forbidden_ip(host):
            raise PublicFetchError("private_network", "Local and private-network URLs are rejected")
    except ValueError:
        pass

    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo, host, parsed.port or (443 if parsed.scheme == "https" else 80)
        )
    except socket.gaierror as exc:
        raise PublicFetchError("dns_error", f"Hostname could not be resolved: {host}") from exc
    for info in infos:
        address = info[4][0]
        if _is_forbidden_ip(address):
            raise PublicFetchError("private_network", "Hostname resolves to a private network")
    return url


async def _throttle(host: str, interval_seconds: float = 1.0) -> None:
    async with _RATE_LOCK:
        now = time.monotonic()
        wait = interval_seconds - (now - _LAST_REQUEST.get(host, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        _LAST_REQUEST[host] = time.monotonic()


async def _robots_allows(client: httpx.AsyncClient, url: str) -> bool:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    cached = _ROBOTS_CACHE.get(origin)
    if cached and time.time() - cached[0] < 3600:
        return cached[1].can_fetch(USER_AGENT, url)

    robots_url = origin + "/robots.txt"
    parser = RobotFileParser(robots_url)
    try:
        await _throttle(parsed.hostname or "")
        response = await client.get(robots_url, follow_redirects=False)
        if response.status_code == 200:
            parser.parse(response.text.splitlines())
        elif response.status_code in {401, 403}:
            parser.disallow_all = True
        else:
            parser.allow_all = True
    except httpx.HTTPError:
        parser.allow_all = True
    _ROBOTS_CACHE[origin] = (time.time(), parser)
    return parser.can_fetch(USER_AGENT, url)


async def fetch_public_page(url: str, *, max_bytes: int = MAX_BYTES) -> PublicPage:
    """Fetch a public page without cookies, auth, browser automation, or evasion."""
    current = await validate_public_url(url)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8"}
    timeout = httpx.Timeout(20.0, connect=10.0)
    async with httpx.AsyncClient(headers=headers, timeout=timeout, trust_env=False) as client:
        for _ in range(4):
            if not await _robots_allows(client, current):
                raise PublicFetchError("robots_denied", "robots.txt does not allow this URL")
            host = urlparse(current).hostname or ""
            await _throttle(host)
            try:
                async with client.stream("GET", current, follow_redirects=False) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise PublicFetchError("bad_redirect", "Redirect has no destination")
                        current = await validate_public_url(urljoin(current, location))
                        continue
                    if response.status_code in {401, 403, 429}:
                        raise PublicFetchError(
                            "access_blocked", f"Public request was blocked with HTTP {response.status_code}"
                        )
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    if not any(kind in content_type for kind in ("text/", "html", "xhtml", "json")):
                        raise PublicFetchError("unsupported_content", f"Unsupported content type: {content_type}")
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise PublicFetchError("too_large", "Page exceeds the configured size limit")
                        chunks.append(chunk)
                    encoding = response.encoding or "utf-8"
                    return PublicPage(
                        url=str(response.url),
                        status_code=response.status_code,
                        content_type=content_type,
                        text=b"".join(chunks).decode(encoding, errors="replace"),
                    )
            except PublicFetchError:
                raise
            except httpx.HTTPError as exc:
                detail = str(exc).strip() or "request failed"
                raise PublicFetchError(
                    "network_error", f"{type(exc).__name__}: {detail}"
                ) from exc
    raise PublicFetchError("too_many_redirects", "Too many redirects")


async def fetch_public_binary(
    url: str,
    *,
    allowed_content_types: tuple[str, ...] = ("application/pdf",),
    max_bytes: int = 5_000_000,
) -> PublicBinary:
    """Fetch a bounded public binary such as a linked CV PDF."""
    current = await validate_public_url(url)
    headers = {"User-Agent": USER_AGENT, "Accept": ",".join(allowed_content_types)}
    timeout = httpx.Timeout(25.0, connect=10.0)
    async with httpx.AsyncClient(headers=headers, timeout=timeout, trust_env=False) as client:
        for _ in range(4):
            if not await _robots_allows(client, current):
                raise PublicFetchError("robots_denied", "robots.txt does not allow this URL")
            await _throttle(urlparse(current).hostname or "")
            try:
                async with client.stream("GET", current, follow_redirects=False) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise PublicFetchError("bad_redirect", "Redirect has no destination")
                        current = await validate_public_url(urljoin(current, location))
                        continue
                    if response.status_code in {401, 403, 429}:
                        raise PublicFetchError(
                            "access_blocked", f"Public request was blocked with HTTP {response.status_code}"
                        )
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if content_type not in allowed_content_types:
                        raise PublicFetchError("unsupported_content", f"Unsupported content type: {content_type}")
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise PublicFetchError("too_large", "Binary exceeds the configured size limit")
                        chunks.append(chunk)
                    return PublicBinary(
                        url=str(response.url),
                        status_code=response.status_code,
                        content_type=content_type,
                        data=b"".join(chunks),
                    )
            except PublicFetchError:
                raise
            except httpx.HTTPError as exc:
                detail = str(exc).strip() or "request failed"
                raise PublicFetchError("network_error", f"{type(exc).__name__}: {detail}") from exc
    raise PublicFetchError("too_many_redirects", "Too many redirects")
