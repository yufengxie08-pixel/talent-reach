"""Shared mechanics for platform-specific routes."""

from __future__ import annotations

from urllib.parse import urlparse

from talent_reach.connectors.public_web import read_public_profile
from talent_reach.models import BackendHealth, TalentProfile
from talent_reach.normalization import profile_from_markdown, profile_from_public_result
from talent_reach.opencli import doctor as opencli_doctor, read_markdown


def host_allowed(url: str, domains: set[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in domains)


async def read_with_routes(
    url: str,
    *,
    platform: str,
    domains: set[str],
    prefer_browser: bool,
) -> dict:
    if not host_allowed(url, domains):
        return TalentProfile(
            status="unavailable",
            platform=platform,
            profile_url=url,
            warnings=["URL domain is not allowed for this platform MCP"],
        ).as_dict()

    errors: list[str] = []
    routes = ["browser", "direct"] if prefer_browser else ["direct", "browser"]
    for route in routes:
        if route == "direct":
            result = await read_public_profile(url)
            if result.get("status") == "ok":
                final_url = str(result.get("source_url") or url)
                if not host_allowed(final_url, domains):
                    errors.append("direct:redirected_outside_platform_domain")
                    continue
                profile = profile_from_public_result(result, platform)
                profile.warnings.append("active_backend=direct-public-http")
                return profile.as_dict()
            errors.append(f"direct:{result.get('reason_code', 'unavailable')}")
        else:
            try:
                markdown = await read_markdown(url, domains)
            except Exception as exc:
                errors.append(f"browser:{type(exc).__name__}:{str(exc)[:240]}")
                continue
            profile = profile_from_markdown(markdown, url, platform)
            profile.warnings.append("active_backend=OpenCLI-browser")
            return profile.as_dict()

    return TalentProfile(
        status="unavailable",
        platform=platform,
        profile_url=url,
        warnings=errors or ["No backend succeeded"],
    ).as_dict()


def browser_health(platform: str, backends: list[str]) -> dict:
    status = opencli_doctor()
    return BackendHealth(
        platform=platform,
        status="ok" if status.get("ok") else "warn",
        active_backend="OpenCLI-browser" if status.get("ok") else None,
        backends=backends,
        details=status,
    ).as_dict()
