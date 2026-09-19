"""GitHub public profile connector; deliberately does not mine commit emails."""

from __future__ import annotations

import os

import httpx

from talent_reach.fetch import USER_AGENT


API_ROOT = "https://api.github.com"


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def lookup_user(username: str) -> dict:
    username = username.strip().lstrip("@").strip("/")
    if not username or "/" in username:
        return {"status": "error", "message": "A single GitHub username is required"}
    async with httpx.AsyncClient(headers=_headers(), timeout=20.0, trust_env=False) as client:
        response = await client.get(f"{API_ROOT}/users/{username}")
    if response.status_code == 404:
        return {"status": "not_found", "username": username}
    response.raise_for_status()
    item = response.json()
    email = item.get("email") if isinstance(item.get("email"), str) else None
    evidence = []
    if email:
        evidence.append(
            {
                "field": "email",
                "value": email,
                "source_url": item.get("html_url"),
                "basis": "GitHub profile public email field",
            }
        )
    return {
        "status": "ok",
        "backend": "GitHub public REST",
        "username": item.get("login"),
        "name": item.get("name"),
        "company": item.get("company"),
        "location": item.get("location"),
        "bio": item.get("bio"),
        "profile_url": item.get("html_url"),
        "website_url": item.get("blog"),
        "public_repos": item.get("public_repos"),
        "followers": item.get("followers"),
        "email": email,
        "evidence": evidence,
        "note": "Only the profile's public email field is used; commit history is not mined.",
    }


async def search_users(query: str, location: str | None = None, per_page: int = 10) -> dict:
    per_page = max(1, min(int(per_page), 30))
    q = query.strip()
    if location:
        q += f' location:"{location.strip()}"'
    async with httpx.AsyncClient(headers=_headers(), timeout=20.0, trust_env=False) as client:
        response = await client.get(
            f"{API_ROOT}/search/users", params={"q": q, "per_page": per_page}
        )
    if response.status_code == 403:
        return {"status": "rate_limited", "message": response.headers.get("x-ratelimit-reset")}
    response.raise_for_status()
    payload = response.json()
    return {
        "status": "ok",
        "backend": "GitHub public REST",
        "total_count": payload.get("total_count"),
        "matches": [
            {"username": item.get("login"), "profile_url": item.get("html_url")}
            for item in payload.get("items", [])
        ],
    }


async def probe() -> dict:
    async with httpx.AsyncClient(headers=_headers(), timeout=15.0, trust_env=False) as client:
        response = await client.get(f"{API_ROOT}/rate_limit")
    remaining = response.headers.get("x-ratelimit-remaining")
    return {"ok": response.status_code == 200, "http_status": response.status_code, "remaining": remaining}

