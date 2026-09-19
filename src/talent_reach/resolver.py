"""Cross-platform identity resolution with explainable, conservative scoring."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlparse

from talent_reach.platforms import aboutme, github_public, personal_site, quora, stackexchange, wellfound


def _norm(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _candidate_name_similarity(left: str, right: str) -> float:
    """Blend character and token agreement so a shared surname is not enough."""
    if not left or not right:
        return 0.0
    sequence = SequenceMatcher(None, left, right).ratio()
    left_tokens, right_tokens = set(left.split()), set(right.split())
    token_union = left_tokens | right_tokens
    token_jaccard = len(left_tokens & right_tokens) / len(token_union) if token_union else 0.0
    return (sequence + token_jaccard) / 2


def _confidence(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _contacts(profile: dict, kind: str) -> set[str]:
    return {
        str(item.get("value", "")).casefold().strip()
        for item in profile.get("contacts", [])
        if isinstance(item, dict)
        and item.get("kind") == kind
        and item.get("value")
        and (
            kind != "email"
            or (
                item.get("owner_role") == "candidate"
                and _confidence(item.get("ownership_confidence")) >= 0.85
            )
        )
    }


def _links(profile: dict) -> set[str]:
    values = set(profile.get("links", [])) | {profile.get("profile_url", "")}
    return {str(value).casefold().rstrip("/") for value in values if value}


def _declared_links(profile: dict) -> set[str]:
    return {
        str(value).casefold().rstrip("/")
        for value in profile.get("links", [])
        if value
    }


def compare_profiles(left: dict, right: dict) -> dict:
    breakdown: dict[str, float] = {}
    left_name, right_name = _norm(left.get("name")), _norm(right.get("name"))
    name_similarity = SequenceMatcher(None, left_name, right_name).ratio() if left_name and right_name else 0.0
    breakdown["name"] = round(name_similarity * 0.2, 3)

    email_overlap = _contacts(left, "email") & _contacts(right, "email")
    breakdown["email"] = 0.45 if email_overlap else 0.0

    left_url = str(left.get("profile_url") or "").casefold().rstrip("/")
    right_url = str(right.get("profile_url") or "").casefold().rstrip("/")
    direct_cross_links = {
        value
        for value, found in (
            (right_url, right_url and right_url in _declared_links(left)),
            (left_url, left_url and left_url in _declared_links(right)),
        )
        if found
    }
    link_overlap = _links(left) & _links(right)
    breakdown["cross_link"] = 0.45 if direct_cross_links else (0.2 if link_overlap else 0.0)

    org_left, org_right = _norm(left.get("current_org")), _norm(right.get("current_org"))
    org_similarity = SequenceMatcher(None, org_left, org_right).ratio() if org_left and org_right else 0.0
    breakdown["organization"] = round(org_similarity * 0.1, 3)

    loc_left, loc_right = _norm(left.get("location")), _norm(right.get("location"))
    loc_similarity = SequenceMatcher(None, loc_left, loc_right).ratio() if loc_left and loc_right else 0.0
    breakdown["location"] = round(loc_similarity * 0.05, 3)

    score = min(sum(breakdown.values()), 1.0)
    if name_similarity < 0.55:
        score = min(score, 0.49)
    decision = "same_person_likely" if score >= 0.65 else "needs_review" if score >= 0.4 else "insufficient_evidence"
    return {
        "score": round(score, 3),
        "decision": decision,
        "breakdown": breakdown,
        "matching_emails": sorted(email_overlap),
        "matching_links": sorted(link_overlap),
        "direct_cross_links": sorted(direct_cross_links),
    }


def resolve_profiles(candidate_name: str, profiles: list[dict]) -> dict:
    usable = [profile for profile in profiles if profile.get("status") in {"ok", "partial"}]
    candidate_normalized = _norm(candidate_name)
    candidate_name_matches = {
        str(profile.get("profile_url")): round(
            _candidate_name_similarity(candidate_normalized, _norm(profile.get("name"))), 3
        )
        if candidate_normalized and _norm(profile.get("name"))
        else 0.0
        for profile in usable
    }
    comparisons = []
    for i, left in enumerate(usable):
        for j in range(i + 1, len(usable)):
            right = usable[j]
            comparisons.append(
                {
                    "left": left.get("platform"),
                    "left_url": left.get("profile_url"),
                    "right": right.get("platform"),
                    "right_url": right.get("profile_url"),
                    **compare_profiles(left, right),
                }
            )

    confirmed_indexes = set()
    for comparison in comparisons:
        if comparison["decision"] == "same_person_likely":
            if any(
                candidate_name_matches.get(str(url), 0.0) < 0.75
                for url in (comparison["left_url"], comparison["right_url"])
            ):
                continue
            for index, profile in enumerate(usable):
                if profile.get("profile_url") in {comparison["left_url"], comparison["right_url"]}:
                    confirmed_indexes.add(index)
    if len(usable) == 1:
        observed = _norm(usable[0].get("name"))
        if SequenceMatcher(None, _norm(candidate_name), observed).ratio() >= 0.8:
            confirmed_indexes.add(0)

    confirmed = [usable[index] for index in sorted(confirmed_indexes)]
    public_contacts = {}
    for profile in confirmed:
        for contact in profile.get("contacts", []):
            if not isinstance(contact, dict):
                continue
            if contact.get("kind") == "email" and not (
                contact.get("owner_role") == "candidate"
                and _confidence(contact.get("ownership_confidence")) >= 0.85
            ):
                continue
            key = (contact.get("kind"), str(contact.get("value", "")).casefold())
            public_contacts.setdefault(key, contact)
    return {
        "status": "ok",
        "candidate_name": candidate_name,
        "profiles": profiles,
        "comparisons": comparisons,
        "candidate_name_matches": candidate_name_matches,
        "confirmed_profile_urls": [profile.get("profile_url") for profile in confirmed],
        "public_contacts_from_confirmed_profiles": list(public_contacts.values()),
        "nationality": {"value": None, "reason": "not inferred"},
        "policy": "Name-only matches are never auto-merged; email or cross-link evidence is required.",
    }


async def _read_url(url: str) -> dict:
    host = (urlparse(url).hostname or "").lower()
    path = urlparse(url).path
    if host == "about.me" or host.endswith(".about.me"):
        return await aboutme.read_profile(url)
    if host == "quora.com" or host.endswith(".quora.com"):
        return await quora.read_profile(url)
    if host in {"wellfound.com", "angel.co"} or host.endswith((".wellfound.com", ".angel.co")):
        return await wellfound.read_profile(url)
    if host == "github.com" or host.endswith(".github.com"):
        username = path.strip("/").split("/", 1)[0]
        return await github_public.read_profile(username)
    if host == "stackoverflow.com" or host.endswith(".stackoverflow.com"):
        match = re.search(r"/users/(\d+)", path)
        if match:
            return await stackexchange.read_profile(int(match.group(1)))
    return await personal_site.read_site(url)


async def enrich_urls(candidate_name: str, urls: list[str]) -> dict:
    if not urls or len(urls) > 10:
        return {"status": "error", "message": "Provide between 1 and 10 profile URLs"}
    results = await asyncio.gather(*(_read_url(url) for url in urls), return_exceptions=True)
    profiles = []
    for url, result in zip(urls, results, strict=True):
        if isinstance(result, Exception):
            profiles.append(
                {
                    "status": "unavailable",
                    "platform": "unknown",
                    "profile_url": url,
                    "warnings": [f"Backend failed: {type(result).__name__}"],
                    "sensitive_inferences": {"nationality": "not_inferred"},
                }
            )
        else:
            profiles.append(result)
    return resolve_profiles(candidate_name, profiles)
