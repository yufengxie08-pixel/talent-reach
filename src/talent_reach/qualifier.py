"""Deterministic hard-condition qualification with three-state checks."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from talent_reach.rankings import get_company_membership, get_university_rank, ranking_doctor
from talent_reach.resume_parser import detect_stem, extract_education


def _norm_name(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _confidence(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def merge_candidate_profiles(candidate_name: str, profiles: list[dict]) -> dict:
    """Merge only profiles whose visible name agrees with the requested candidate."""
    candidate = _norm_name(candidate_name)
    accepted = []
    rejected = []
    for profile in profiles:
        observed = _norm_name(profile.get("name"))
        similarity = SequenceMatcher(None, candidate, observed).ratio() if candidate and observed else 0.0
        item = {"profile_url": profile.get("profile_url"), "name_similarity": round(similarity, 3)}
        if profile.get("status") in {"ok", "partial"} and similarity >= 0.75:
            accepted.append(profile)
        else:
            rejected.append(item)

    merged = {
        "status": "ok" if accepted else "unavailable",
        "platform": "qualified_candidate",
        "profile_url": accepted[0].get("profile_url") if accepted else "",
        "name": candidate_name,
        "headline": next((p.get("headline") for p in accepted if p.get("headline")), None),
        "current_org": next((p.get("current_org") for p in accepted if p.get("current_org")), None),
        "education": [],
        "education_records": [],
        "employment_records": [],
        "skills": [],
        "contacts": [],
        "links": [],
        "evidence": [],
        "raw_summary": "",
        "source_profile_urls": [p.get("profile_url") for p in accepted],
        "rejected_profiles": rejected,
    }
    for profile in accepted:
        for key in (
            "education", "education_records", "employment_records", "skills", "contacts", "links", "evidence"
        ):
            merged[key].extend(profile.get(key, []))
        if profile.get("raw_summary"):
            merged["raw_summary"] += "\n" + str(profile["raw_summary"])

    for key in ("education", "skills", "links"):
        merged[key] = list(dict.fromkeys(str(value) for value in merged[key] if value))
    for key in ("education_records", "employment_records", "contacts", "evidence"):
        unique = {}
        for item in merged[key]:
            if key == "contacts":
                identity = (item.get("kind"), str(item.get("value", "")).casefold())
            elif key == "education_records":
                identity = (item.get("degree"), item.get("institution"), item.get("field"))
            elif key == "employment_records":
                identity = (item.get("organization"), item.get("title"))
            else:
                identity = (item.get("field"), item.get("value"), item.get("source_url"))
            unique[identity] = item
        merged[key] = list(unique.values())
    merged["raw_summary"] = merged["raw_summary"][:24000]
    return merged


def _check(status: str, summary: str, evidence: list[dict] | None = None) -> dict:
    return {"status": status, "summary": summary, "evidence": evidence or []}


def _education_records(profile: dict) -> list[dict]:
    records = list(profile.get("education_records", []))
    if not records:
        source = str(profile.get("profile_url") or "")
        texts = [str(value) for value in profile.get("education", [])]
        if profile.get("raw_summary"):
            texts.append(str(profile["raw_summary"]))
        for item in extract_education("\n".join(texts), source):
            records.append(item.model_dump(mode="json"))
    return records


def _phd_record(records: list[dict]) -> dict | None:
    for record in records:
        degree = str(record.get("degree") or "").casefold().replace(".", "")
        if any(value in degree for value in ("phd", "dphil", "doctor")):
            return record
    return None


def _current_organization(profile: dict) -> tuple[str | None, dict | None]:
    if profile.get("current_org"):
        return str(profile["current_org"]), {
            "source_url": profile.get("profile_url"),
            "value": profile["current_org"],
            "basis": "normalized current_org",
        }
    for record in profile.get("employment_records", []):
        if record.get("current", True) and record.get("organization"):
            return str(record["organization"]), record
    return None, None


def qualify_candidate(
    profile: dict,
    *,
    phd_qs_max: int = 100,
    employer_qs_max: int = 200,
    qs_edition: str = "2027",
    allow_fortune_global_500: bool = True,
    fortune_year: int | None = None,
    require_overseas_phd: bool = True,
    require_public_candidate_email: bool = True,
) -> dict:
    checks: dict[str, dict] = {}
    unresolved: list[str] = []

    education_records = _education_records(profile)
    phd = _phd_record(education_records)
    if not phd:
        checks["has_phd"] = _check("review", "No structured doctorate evidence was found.")
        checks["phd_university_qs"] = _check("review", "Doctoral institution is unresolved.")
        unresolved.extend(["doctorate", "doctoral institution rank"])
    else:
        checks["has_phd"] = _check("pass", f"Doctorate found: {phd.get('degree')}", [phd])
        institution = phd.get("institution")
        if not institution:
            checks["phd_university_qs"] = _check("review", "Doctoral institution is missing.", [phd])
            unresolved.append("doctoral institution rank")
        else:
            rank = get_university_rank(str(institution), qs_edition)
            if rank.get("status") != "ok":
                checks["phd_university_qs"] = _check(
                    "review", f"No verified QS {qs_edition} rank for {institution}.", [rank, phd]
                )
                unresolved.append("doctoral institution rank")
            elif int(rank["rank"]) <= phd_qs_max:
                overseas_ok = not require_overseas_phd or rank.get("country_or_region") != "China (Mainland)"
                if overseas_ok:
                    checks["phd_university_qs"] = _check(
                        "pass", f"{rank['canonical_name']} is QS {qs_edition} #{rank['rank']}.", [rank, phd]
                    )
                else:
                    checks["phd_university_qs"] = _check(
                        "fail", "Doctoral institution is in China (Mainland), not overseas under this rule.", [rank, phd]
                    )
            else:
                checks["phd_university_qs"] = _check(
                    "fail", f"QS rank {rank['rank']} exceeds the maximum {phd_qs_max}.", [rank, phd]
                )

    organization, organization_evidence = _current_organization(profile)
    if not organization:
        checks["current_employer"] = _check("review", "Current organization is unresolved.")
        unresolved.append("current organization")
    else:
        university_rank = get_university_rank(organization, qs_edition)
        if university_rank.get("status") == "ok":
            status = "pass" if int(university_rank["rank"]) <= employer_qs_max else "fail"
            checks["current_employer"] = _check(
                status,
                f"{university_rank['canonical_name']} is QS {qs_edition} #{university_rank['rank']}.",
                [university_rank, organization_evidence],
            )
        elif allow_fortune_global_500:
            company = get_company_membership(
                organization, "fortune_global_500", fortune_year
            )
            if company.get("status") == "ok" and company.get("is_member"):
                checks["current_employer"] = _check(
                    "pass", "Current employer is in the verified Fortune Global 500 snapshot.",
                    [company, organization_evidence],
                )
            else:
                checks["current_employer"] = _check(
                    "review",
                    "Current organization is not resolved as a QS university and Fortune data is unavailable or has no verified match.",
                    [university_rank, company, organization_evidence],
                )
                unresolved.append("current employer ranking")
        else:
            checks["current_employer"] = _check(
                "review", "Current organization has no verified QS university match.",
                [university_rank, organization_evidence],
            )
            unresolved.append("current employer ranking")

    stem_texts = [
        str(profile.get("headline") or ""),
        str(profile.get("raw_summary") or ""),
        *[str(value) for value in profile.get("skills", [])],
        *[str(item.get("field") or "") for item in education_records],
    ]
    stem = detect_stem(stem_texts)
    checks["stem"] = _check(
        "pass" if stem["is_stem"] else "review",
        stem["basis"],
        [stem],
    )
    if not stem["is_stem"]:
        unresolved.append("STEM field")

    candidate_contacts = [
        item
        for item in profile.get("contacts", [])
        if isinstance(item, dict)
        and item.get("kind") == "email"
        and item.get("owner_role") == "candidate"
        and _confidence(item.get("ownership_confidence")) >= 0.85
        and item.get("visibility") == "explicit_public"
    ]
    if candidate_contacts:
        checks["candidate_email"] = _check(
            "pass", "At least one explicitly public candidate-owned email was found.", candidate_contacts
        )
    elif require_public_candidate_email:
        checks["candidate_email"] = _check(
            "review", "No public email with verified candidate ownership was found."
        )
        unresolved.append("candidate-owned public email")
    else:
        checks["candidate_email"] = _check("pass", "A public email is not required by this run.")

    statuses = [item["status"] for item in checks.values()]
    decision = "eligible" if all(value == "pass" for value in statuses) else (
        "ineligible" if "fail" in statuses else "review"
    )
    return {
        "status": "ok",
        "decision": decision,
        "eligible": decision == "eligible",
        "candidate_name": profile.get("name"),
        "checks": checks,
        "unresolved": sorted(set(unresolved)),
        "policy": (
            "Every hard condition must pass with source evidence. Unknown rankings, ambiguous "
            "email ownership, and search snippets remain review rather than pass."
        ),
    }


def qualifier_doctor() -> dict:
    return {
        "status": "ok",
        "decision_policy": "all hard conditions must pass; unknown evidence remains review",
        "email_policy": "candidate ownership confidence must be at least 0.85",
        "ranking": ranking_doctor(),
    }
