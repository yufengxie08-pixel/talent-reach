"""Quora-specific public profile backend."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from talent_reach.models import Evidence
from talent_reach.opencli import OpenCLIError, google_site_search
from talent_reach.platforms.common import browser_health, read_with_routes


DOMAINS = {"quora.com"}
BACKENDS = ["OpenCLI-browser", "direct-public-http"]


def canonical_url(profile_or_url: str) -> str:
    value = profile_or_url.strip()
    if value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        path = parsed.path
    else:
        path = value if value.startswith("/profile/") else f"/profile/{value.lstrip('@/')}"
    return f"https://www.quora.com{path}"


async def read_profile(profile_or_url: str) -> dict:
    profile = await read_with_routes(
        canonical_url(profile_or_url),
        platform="quora",
        domains=DOMAINS,
        prefer_browser=True,
    )
    if profile.get("status") == "ok" and profile.get("raw_summary"):
        parsed = _parse_quora_markdown(
            str(profile["raw_summary"]),
            str(profile.get("profile_url") or canonical_url(profile_or_url)),
            profile.get("name"),
        )
        for field in ("headline", "location", "current_org"):
            profile[field] = parsed.get(field) or profile.get(field)
        profile["education"] = parsed.get("education") or profile.get("education", [])
        profile["skills"] = parsed.get("skills") or profile.get("skills", [])
        profile["evidence"].extend(parsed.get("evidence", []))
    profile.setdefault("warnings", []).append(
        "Quora is treated as expertise/activity evidence, not a reliable email source"
    )
    return profile


def _parse_quora_markdown(markdown: str, source_url: str, name: str | None) -> dict:
    headline = None
    if name:
        match = re.search(rf"(?m)^{re.escape(name)}\s*$\n+([^\n]+)", markdown)
        if match:
            candidate = match.group(1).strip()
            if len(candidate) <= 160 and candidate not in {"Profile", "More"}:
                headline = candidate

    def credential(prefix: str) -> str | None:
        match = re.search(rf"(?m)^{re.escape(prefix)}\s+(.+?)\s*$", markdown)
        return match.group(1).strip() if match else None

    organization = credential("Worked at")
    school = credential("Studied at")
    location = credential("Lives in")
    topic_segment = markdown.split("Knows about", 1)[1] if "Knows about" in markdown else ""
    topics = []
    for label, _ in re.findall(
        r"\[([^\]\n]+)\]\((https://www\.quora\.com/topic/[^)]+)\)", topic_segment
    ):
        value = label.strip()
        if value and value not in topics:
            topics.append(value)

    evidence = []
    for field, value, basis, confidence in (
        ("headline", headline, "visible Quora profile tagline", "high"),
        ("organization", organization, "visible Quora credential", "medium"),
        ("education", school, "visible Quora credential", "medium"),
        ("location", location, "visible Quora credential", "medium"),
    ):
        if value:
            evidence.append(
                Evidence(
                    field=field,
                    value=value,
                    source_url=source_url,
                    basis=basis,
                    confidence=confidence,
                ).model_dump(mode="json")
            )
    for topic in topics[:20]:
        evidence.append(
            Evidence(
                field="skill",
                value=topic,
                source_url=source_url,
                basis="visible Quora Knows about topic",
                confidence="low",
            ).model_dump(mode="json")
        )
    return {
        "headline": headline,
        "current_org": organization,
        "education": [school] if school else [],
        "location": location,
        "skills": topics[:20],
        "evidence": evidence,
    }


async def search_profiles(query: str, location: str | None = None, limit: int = 10) -> dict:
    search_query = f'inurl:profile {query.strip()}'
    if location:
        search_query += f' "{location.strip()}"'
    try:
        hits = await google_site_search("quora.com", search_query, platform="quora", limit=limit)
    except OpenCLIError as exc:
        return {"status": "unavailable", "platform": "quora", "message": str(exc), "matches": []}
    hits = [hit for hit in hits if "/profile/" in urlparse(hit["url"]).path]
    return {"status": "ok", "platform": "quora", "backend": "OpenCLI Google search", "matches": hits}


def doctor() -> dict:
    return browser_health("quora", BACKENDS)
