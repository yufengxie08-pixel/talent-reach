"""GitHub-specific talent evidence backend."""

from __future__ import annotations

import httpx

from talent_reach.connectors import github
from talent_reach.models import BackendHealth, Contact, Evidence, TalentProfile


BACKENDS = ["GitHub public REST", "gh CLI"]


async def read_profile(username: str, repo_limit: int = 12) -> dict:
    try:
        base = await github.lookup_user(username)
    except httpx.HTTPError as exc:
        return TalentProfile(
            status="unavailable",
            platform="github",
            profile_url=f"https://github.com/{username.strip().lstrip('@')}",
            warnings=[f"GitHub public REST unavailable: {type(exc).__name__}"],
        ).as_dict()
    if base.get("status") != "ok":
        return TalentProfile(
            status="not_found" if base.get("status") == "not_found" else "unavailable",
            platform="github",
            profile_url=f"https://github.com/{username.strip().lstrip('@')}",
            warnings=[base.get("message") or base.get("status", "unavailable")],
        ).as_dict()

    repo_limit = max(1, min(int(repo_limit), 30))
    repos: list[dict] = []
    try:
        async with httpx.AsyncClient(
            headers=github._headers(), timeout=20.0, trust_env=False
        ) as client:
            response = await client.get(
                f"{github.API_ROOT}/users/{base['username']}/repos",
                params={"sort": "updated", "per_page": repo_limit},
            )
            response.raise_for_status()
            repos = response.json()
    except httpx.HTTPError:
        repos = []

    languages = sorted(
        {str(repo.get("language")) for repo in repos if repo.get("language")}
    )
    evidence = [
        Evidence(
            field="github_profile",
            value=base["username"],
            source_url=base["profile_url"],
            basis="GitHub public REST profile",
        )
    ]
    for language in languages:
        evidence.append(
            Evidence(
                field="skill",
                value=language,
                source_url=base["profile_url"],
                basis="primary language of a recent public repository",
                confidence="medium",
            )
        )
    contacts = []
    if base.get("email"):
        contacts.append(
            Contact(
                kind="email",
                value=base["email"],
                source_url=base["profile_url"],
                owner_name=base.get("name"),
                owner_role="candidate",
                ownership_confidence=1.0,
                association_basis="GitHub public profile email field",
                extraction_method="public_api",
            )
        )
    if base.get("website_url"):
        contacts.append(
            Contact(kind="website", value=base["website_url"], source_url=base["profile_url"])
        )
    return TalentProfile(
        platform="github",
        platform_id=base["username"],
        profile_url=base["profile_url"],
        name=base.get("name"),
        headline=base.get("bio"),
        location=base.get("location"),
        current_org=base.get("company"),
        skills=languages,
        contacts=contacts,
        links=[value for value in [base.get("website_url")] if value],
        evidence=evidence,
        raw_summary=f"{base.get('public_repos', 0)} public repos; {base.get('followers', 0)} followers",
        warnings=["Commit history is not mined for email addresses"],
    ).as_dict()


async def search_profiles(query: str, location: str | None = None, limit: int = 10) -> dict:
    try:
        return await github.search_users(query, location=location, per_page=limit)
    except httpx.HTTPError as exc:
        return {"status": "unavailable", "backend": "GitHub public REST", "message": str(exc), "matches": []}


async def doctor() -> dict:
    try:
        status = await github.probe()
    except httpx.HTTPError as exc:
        status = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return BackendHealth(
        platform="github",
        status="ok" if status.get("ok") else "warn",
        active_backend="GitHub public REST" if status.get("ok") else None,
        backends=BACKENDS,
        details=status,
    ).as_dict()
