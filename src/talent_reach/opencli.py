"""Read-only OpenCLI bridge used as a browser-backed public-page backend."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from urllib.parse import urlparse

from talent_reach.fetch import PublicFetchError, validate_public_url
from talent_reach.models import SearchHit


class OpenCLIError(RuntimeError):
    pass


def available() -> bool:
    return bool(shutil.which("opencli"))


def run(args: list[str], timeout: int = 60) -> str:
    executable = shutil.which("opencli")
    if not executable:
        raise OpenCLIError("opencli is not installed")
    try:
        result = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OpenCLIError("opencli timed out") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise OpenCLIError(detail[:1000] or f"opencli exited with {result.returncode}")
    return result.stdout


def doctor() -> dict:
    if not available():
        return {"ok": False, "message": "opencli is not installed"}
    try:
        output = run(["doctor"], timeout=20)
    except OpenCLIError as exc:
        return {"ok": False, "message": str(exc)}
    connected = "[OK] Extension: connected" in output and "Everything looks good" in output
    return {"ok": connected, "message": output.strip()[:2000]}


async def google_site_search(
    domain: str, query: str, *, platform: str, limit: int = 10
) -> list[dict]:
    limit = max(1, min(int(limit), 25))
    raw = await asyncio.to_thread(
        run,
        [
            "google",
            "search",
            f"site:{domain} {query.strip()}",
            "--limit",
            str(limit),
            "--window",
            "background",
            "-f",
            "json",
        ],
    )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OpenCLIError("google search returned invalid JSON") from exc
    hits = []
    for item in payload if isinstance(payload, list) else []:
        url = str(item.get("url") or "")
        host = (urlparse(url).hostname or "").lower()
        if not (host == domain or host.endswith("." + domain)):
            continue
        hits.append(
            SearchHit(
                platform=platform,
                title=item.get("title"),
                url=url,
                snippet=item.get("snippet"),
                source_backend="OpenCLI Google search",
            ).as_dict()
        )
    return hits


async def read_markdown(url: str, allowed_domains: set[str]) -> str:
    await validate_public_url(url)
    host = (urlparse(url).hostname or "").lower()
    if not any(host == domain or host.endswith("." + domain) for domain in allowed_domains):
        raise PublicFetchError("domain_not_allowed", f"Domain is not allowed: {host}")
    return await asyncio.to_thread(
        run,
        [
            "web",
            "read",
            "--url",
            url,
            "--stdout",
            "true",
            "--download-images",
            "false",
            "--wait",
            "2",
            "--window",
            "background",
        ],
        75,
    )
