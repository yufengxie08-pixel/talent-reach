"""Wellfound-specific public talent profile backend."""

from __future__ import annotations

from urllib.parse import urlparse
import re

from talent_reach.models import BackendHealth, Evidence
from talent_reach.opencli import OpenCLIError, doctor as opencli_doctor, google_site_search, read_markdown
from talent_reach.platforms.common import read_with_routes


DOMAINS = {"wellfound.com", "angel.co"}
BACKENDS = ["direct-public-http", "OpenCLI-browser"]


def _is_access_gate(summary: str) -> bool:
    value = summary.casefold()
    return any(
        marker in value
        for marker in (
            "to view more information about",
            "one more step before you proceed",
            "we value your privacy",
            "manage choices agree & proceed",
        )
    )


def canonical_url(profile_or_url: str) -> str:
    value = profile_or_url.strip()
    if value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        return f"https://wellfound.com{parsed.path}"
    value = value.lstrip("@/")
    if value.startswith(("p/", "u/")):
        return f"https://wellfound.com/{value}"
    return f"https://wellfound.com/p/{value}"


async def read_profile(profile_or_url: str) -> dict:
    url = canonical_url(profile_or_url)
    profile = await read_with_routes(
        url,
        platform="wellfound",
        domains=DOMAINS,
        prefer_browser=False,
    )
    if profile.get("status") == "ok":
        try:
            markdown = await read_markdown(url, DOMAINS)
            parsed = _parse_wellfound_markdown(markdown, url)
            profile["name"] = profile.get("name") or parsed.get("name")
            profile["current_org"] = parsed.get("current_org") or profile.get("current_org")
            profile["education"] = parsed.get("education", [])
            profile["evidence"].extend(parsed.get("evidence", []))
            profile["warnings"].append("supplemental_backend=OpenCLI-browser")
        except Exception as exc:
            profile["warnings"].append(f"structured supplement unavailable: {type(exc).__name__}")
    profile.setdefault("warnings", []).append(
        "Only public profile content is returned; recruiter-only data is not bypassed"
    )
    summary = str(profile.get("raw_summary") or "").casefold()
    if (
        not profile.get("current_org")
        and not profile.get("education")
        and _is_access_gate(summary)
    ):
        profile["status"] = "partial"
        if profile.get("headline") == profile.get("name"):
            profile["headline"] = None
        profile["warnings"].append(
            "Wellfound exposed only the public identity shell; a login or consent gate hid additional fields"
        )
    return profile


def _parse_wellfound_markdown(markdown: str, source_url: str) -> dict:
    lines = [line.strip() for line in markdown.splitlines()]
    name = next((line[2:].strip() for line in lines if line.startswith("# ")), None)
    current_org = None
    experience_index = next((i for i, line in enumerate(lines) if line == "Experience"), -1)
    education_index = next((i for i, line in enumerate(lines) if line == "Education"), -1)
    if experience_index >= 0:
        for line in lines[experience_index + 1 : education_index if education_index > 0 else None]:
            match = re.match(r"\[([^\]]+)\]\(https://wellfound\.com/company/", line)
            if match and not match.group(1).startswith("!"):
                current_org = match.group(1).strip()
                break
    education = []
    if education_index >= 0:
        for line in lines[education_index + 1 :]:
            if not line or line.startswith(("!", "[", "#", ">")):
                continue
            if line in {"Help", "Blog", "Terms", "Privacy Policy & Cookies"}:
                break
            if len(line) <= 160:
                education.append(line)
    evidence = [
        Evidence(
            field="education",
            value=value,
            source_url=source_url,
            basis="visible Wellfound Education section",
            confidence="medium",
        ).model_dump(mode="json")
        for value in education[:20]
    ]
    return {"name": name, "current_org": current_org, "education": education[:20], "evidence": evidence}


async def search_people(query: str, location: str | None = None, limit: int = 10) -> dict:
    search_query = f'(inurl:/p/ OR inurl:/u/) {query.strip()}'
    if location:
        search_query += f' "{location.strip()}"'
    try:
        hits = await google_site_search("wellfound.com", search_query, platform="wellfound", limit=limit)
    except OpenCLIError as exc:
        return {"status": "unavailable", "platform": "wellfound", "message": str(exc), "matches": []}
    hits = [
        hit for hit in hits if urlparse(hit["url"]).path.startswith(("/p/", "/u/"))
    ]
    return {"status": "ok", "platform": "wellfound", "backend": "OpenCLI Google search", "matches": hits}


async def doctor(check_network: bool = False) -> dict:
    details = opencli_doctor()
    direct_ok = False
    if check_network:
        sample = await read_with_routes(
            "https://wellfound.com/candidates/overview",
            platform="wellfound",
            domains=DOMAINS,
            prefer_browser=False,
        )
        direct_ok = sample.get("status") == "ok"
        details["direct_public_http"] = direct_ok
    active = "direct-public-http" if direct_ok else ("OpenCLI-browser" if details.get("ok") else None)
    return BackendHealth(
        platform="wellfound",
        status="ok" if active else "warn",
        active_backend=active,
        backends=BACKENDS,
        details=details,
    ).as_dict()
