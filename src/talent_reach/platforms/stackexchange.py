"""Stack Overflow-specific user and expertise backend."""

from __future__ import annotations

import asyncio
from html import unescape

import httpx

from talent_reach.connectors import stackexchange as api
from talent_reach.fetch import USER_AGENT
from talent_reach.models import BackendHealth, Contact, Evidence, TalentProfile


BACKENDS = ["Stack Exchange public API", "OpenCLI stackoverflow"]


async def search_profiles(
    name: str, location: str | None = None, site: str = "stackoverflow", limit: int = 30
) -> dict:
    try:
        return await api.search_people(name, location=location, site=site, pagesize=limit)
    except httpx.HTTPError as exc:
        return {"status": "unavailable", "backend": "Stack Exchange public API", "message": str(exc), "matches": []}


async def read_profile(user_id: int, site: str = "stackoverflow", tag_limit: int = 20) -> dict:
    tag_limit = max(1, min(int(tag_limit), 100))
    headers = {"User-Agent": USER_AGENT}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=20.0, trust_env=False) as client:
            user_resp, tags_resp = await asyncio.gather(
                client.get(f"{api.API_ROOT}/users/{int(user_id)}", params={"site": site}),
                client.get(
                    f"{api.API_ROOT}/users/{int(user_id)}/tags",
                    params={"site": site, "pagesize": tag_limit, "sort": "popular"},
                ),
            )
            user_resp.raise_for_status()
            tags_resp.raise_for_status()
    except httpx.HTTPError as exc:
        return TalentProfile(
            status="unavailable",
            platform="stackoverflow",
            platform_id=str(user_id),
            profile_url=f"https://stackoverflow.com/users/{user_id}",
            warnings=[f"Stack Exchange public API unavailable: {type(exc).__name__}"],
        ).as_dict()
    users = user_resp.json().get("items", [])
    if not users:
        return TalentProfile(
            status="not_found",
            platform="stackoverflow",
            platform_id=str(user_id),
            profile_url=f"https://stackoverflow.com/users/{user_id}",
        ).as_dict()
    user = users[0]
    tags = [unescape(str(item.get("name"))) for item in tags_resp.json().get("items", [])]
    profile_url = user.get("link") or f"https://stackoverflow.com/users/{user_id}"
    evidence = [
        Evidence(
            field="technical_reputation",
            value=str(user.get("reputation", 0)),
            source_url=profile_url,
            basis="Stack Exchange public API",
        )
    ]
    for tag in tags:
        evidence.append(
            Evidence(
                field="skill",
                value=tag,
                source_url=profile_url,
                basis="top Stack Overflow tag",
                confidence="medium",
            )
        )
    contacts = []
    if user.get("website_url"):
        contacts.append(
            Contact(kind="website", value=user["website_url"], source_url=profile_url)
        )
    return TalentProfile(
        platform="stackoverflow",
        platform_id=str(user_id),
        profile_url=profile_url,
        name=unescape(str(user.get("display_name") or "")) or None,
        location=user.get("location"),
        skills=tags,
        contacts=contacts,
        links=[user["website_url"]] if user.get("website_url") else [],
        evidence=evidence,
        raw_summary=f"reputation={user.get('reputation', 0)}",
        warnings=["Stack Exchange does not expose private email addresses"],
    ).as_dict()


async def doctor() -> dict:
    try:
        status = await api.probe()
    except httpx.HTTPError as exc:
        status = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return BackendHealth(
        platform="stackoverflow",
        status="ok" if status.get("ok") else "warn",
        active_backend="Stack Exchange public API" if status.get("ok") else None,
        backends=BACKENDS,
        details=status,
    ).as_dict()
