"""Stack Exchange public API connector."""

from __future__ import annotations

import httpx

from talent_reach.fetch import USER_AGENT


API_ROOT = "https://api.stackexchange.com/2.3"


async def search_people(
    name: str,
    *,
    location: str | None = None,
    site: str = "stackoverflow",
    pagesize: int = 30,
) -> dict:
    pagesize = max(1, min(int(pagesize), 100))
    params = {"site": site, "inname": name, "pagesize": pagesize, "order": "desc", "sort": "reputation"}
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=20.0, trust_env=False
    ) as client:
        response = await client.get(f"{API_ROOT}/users", params=params)
        response.raise_for_status()
        payload = response.json()
    people = []
    location_lc = (location or "").casefold().strip()
    for item in payload.get("items", []):
        item_location = str(item.get("location") or "")
        if location_lc and location_lc not in item_location.casefold():
            continue
        people.append(
            {
                "display_name": item.get("display_name"),
                "location": item_location or None,
                "reputation": item.get("reputation"),
                "profile_url": item.get("link"),
                "website_url": item.get("website_url"),
                "user_id": item.get("user_id"),
                "email": None,
                "evidence": [
                    {
                        "field": "technical_activity",
                        "value": f"Stack Exchange reputation {item.get('reputation', 0)}",
                        "source_url": item.get("link"),
                        "basis": "Stack Exchange public API",
                    }
                ],
            }
        )
    return {
        "status": "ok",
        "backend": "Stack Exchange public API",
        "site": site,
        "matches": people,
        "quota_remaining": payload.get("quota_remaining"),
        "has_more": payload.get("has_more", False),
        "note": "The API does not expose private email addresses.",
    }


async def probe() -> dict:
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=15.0, trust_env=False
    ) as client:
        response = await client.get(f"{API_ROOT}/info", params={"site": "stackoverflow"})
    return {"ok": response.status_code == 200, "http_status": response.status_code}

