"""About.me-specific discovery and profile parsing."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from talent_reach.models import Evidence
from talent_reach.opencli import OpenCLIError, google_site_search
from talent_reach.platforms.common import browser_health, read_with_routes


DOMAINS = {"about.me"}
BACKENDS = ["OpenCLI-browser", "direct-public-http"]


def canonical_url(handle_or_url: str) -> str:
    value = handle_or_url.strip()
    if value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        return f"https://about.me/{parsed.path.strip('/')}"
    return f"https://about.me/{value.lstrip('@/')}"


async def read_profile(handle_or_url: str) -> dict:
    profile = await read_with_routes(
        canonical_url(handle_or_url),
        platform="aboutme",
        domains=DOMAINS,
        prefer_browser=True,
    )
    headline = profile.get("headline") or ""
    if " in " in headline:
        role, location = headline.rsplit(" in ", 1)
        profile["headline"] = role.strip() or headline
        profile["location"] = location.strip() or None
    elif re.search(r",\s*(?:United States|USA)\s*$", headline, re.I):
        profile["location"] = headline.strip()
        profile["headline"] = None

    summary = str(profile.get("raw_summary") or "")
    specialties = re.search(r"(?im)^Specialties:\s*(.+)$", summary)
    if specialties:
        skills = [value.strip() for value in specialties.group(1).split(",") if value.strip()]
        profile["skills"] = skills[:30]
        profile["evidence"].extend(
            Evidence(
                field="skill",
                value=skill,
                source_url=str(profile.get("profile_url") or canonical_url(handle_or_url)),
                basis="visible About.me Specialties line",
                confidence="medium",
            ).model_dump(mode="json")
            for skill in skills[:30]
        )
    return profile


async def search_profiles(query: str, location: str | None = None, limit: int = 10) -> dict:
    search_query = query.strip()
    if location:
        search_query += f' "{location.strip()}"'
    try:
        hits = await google_site_search("about.me", search_query, platform="aboutme", limit=limit)
    except OpenCLIError as exc:
        return {"status": "unavailable", "platform": "aboutme", "message": str(exc), "matches": []}
    hits = [hit for hit in hits if urlparse(hit["url"]).path.strip("/")]
    return {"status": "ok", "platform": "aboutme", "backend": "OpenCLI Google search", "matches": hits}


def doctor() -> dict:
    return browser_health("aboutme", BACKENDS)
