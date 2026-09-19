"""Bounded batch qualification and spreadsheet-safe CSV rendering."""

from __future__ import annotations

import asyncio
import csv
import io
import json
from collections import Counter
from typing import Any

from talent_reach.qualifier import merge_candidate_profiles, qualify_candidate
from talent_reach.resolver import enrich_urls


MAX_BATCH_SIZE = 100
MAX_CONCURRENCY = 8


def _candidate_contacts(profile: dict) -> list[str]:
    def accepted(item: Any) -> bool:
        if not isinstance(item, dict):
            return False
        try:
            confidence = float(item.get("ownership_confidence", 0))
        except (TypeError, ValueError):
            return False
        return bool(
            item.get("kind") == "email"
            and item.get("owner_role") == "candidate"
            and confidence >= 0.85
            and item.get("visibility") == "explicit_public"
            and item.get("value")
        )

    return sorted(
        {
            str(item.get("value", "")).strip()
            for item in profile.get("contacts", [])
            if accepted(item)
        }
    )


def _csv_safe(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value)
    # Prevent formula execution when the CSV is opened in Excel or Google Sheets.
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _rank_from_check(check: dict) -> str:
    for item in check.get("evidence", []):
        if isinstance(item, dict) and item.get("rank") is not None:
            return str(item["rank"])
    return ""


def _phd_record(profile: dict) -> dict:
    for item in profile.get("education_records", []):
        if not isinstance(item, dict):
            continue
        degree = str(item.get("degree") or "").casefold().replace(".", "")
        if any(token in degree for token in ("phd", "dphil", "doctor")):
            return item
    return {}


def qualification_row(item: dict) -> dict[str, str]:
    profile = item.get("merged_profile") or {}
    qualification = item.get("qualification") or {}
    checks = qualification.get("checks") or {}
    phd = _phd_record(profile)
    education = [
        " | ".join(
            str(value)
            for value in (
                record.get("degree"),
                record.get("institution"),
                record.get("field"),
                record.get("year"),
            )
            if value not in (None, "")
        )
        for record in profile.get("education_records", [])
        if isinstance(record, dict)
    ]
    sources = sorted(
        {
            str(value)
            for value in [
                profile.get("profile_url"),
                *profile.get("source_profile_urls", []),
                *(
                    entry.get("source_url")
                    for entry in profile.get("evidence", [])
                    if isinstance(entry, dict)
                ),
            ]
            if value
        }
    )
    return {
        "input_index": str(item.get("input_index", "")),
        "candidate_name": str(item.get("candidate_name") or profile.get("name") or ""),
        "decision": str(qualification.get("decision") or "error"),
        "eligible": str(bool(qualification.get("eligible"))).lower(),
        "public_candidate_emails": "; ".join(_candidate_contacts(profile)),
        "education": "; ".join(education),
        "phd_institution": str(phd.get("institution") or ""),
        "phd_qs_rank": _rank_from_check(checks.get("phd_university_qs", {})),
        "current_organization": str(profile.get("current_org") or ""),
        "current_employer_check": str(checks.get("current_employer", {}).get("status") or ""),
        "stem_check": str(checks.get("stem", {}).get("status") or ""),
        "email_check": str(checks.get("candidate_email", {}).get("status") or ""),
        "unresolved": "; ".join(str(value) for value in qualification.get("unresolved", [])),
        "source_urls": "; ".join(sources),
        "error": str(item.get("error") or ""),
    }


def results_to_csv(batch_result: dict) -> str:
    rows = [qualification_row(item) for item in batch_result.get("results", [])]
    fieldnames = list(qualification_row({}).keys())
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows({key: _csv_safe(value) for key, value in row.items()} for row in rows)
    return output.getvalue()


async def qualify_batch(
    jobs: list[dict],
    *,
    max_concurrency: int = 3,
    phd_qs_max: int = 100,
    employer_qs_max: int = 200,
    qs_edition: str = "2027",
    allow_fortune_global_500: bool = True,
    fortune_year: int | None = None,
    include_research: bool = False,
) -> dict:
    if not 1 <= len(jobs) <= MAX_BATCH_SIZE:
        return {
            "status": "error",
            "message": f"Provide between 1 and {MAX_BATCH_SIZE} candidate jobs.",
            "results": [],
        }
    if not 1 <= int(max_concurrency) <= MAX_CONCURRENCY:
        return {
            "status": "error",
            "message": f"max_concurrency must be between 1 and {MAX_CONCURRENCY}.",
            "results": [],
        }

    semaphore = asyncio.Semaphore(int(max_concurrency))

    async def run_one(index: int, job: dict) -> dict:
        if not isinstance(job, dict):
            return {
                "input_index": index,
                "candidate_name": "",
                "status": "error",
                "error": "Each candidate job must be an object.",
            }
        name = str(job.get("candidate_name") or "").strip()
        base = {"input_index": index, "candidate_name": name}
        if not name:
            return {**base, "status": "error", "error": "candidate_name is required"}
        profiles = job.get("profiles") or []
        urls = job.get("urls") or []
        if not isinstance(profiles, list) or not isinstance(urls, list):
            return {**base, "status": "error", "error": "profiles and urls must be arrays."}
        if profiles and urls:
            return {
                **base,
                "status": "error",
                "error": "Provide profiles or urls for a job, not both.",
            }
        if not profiles and not urls:
            return {
                **base,
                "status": "error",
                "error": "At least one normalized profile or public URL is required.",
            }
        if len(profiles) > 10 or len(urls) > 10:
            return {**base, "status": "error", "error": "A job may contain at most 10 profiles or URLs."}
        try:
            async with semaphore:
                if profiles:
                    research = {"status": "ok", "profiles": profiles, "input_mode": "profiles"}
                else:
                    research = await enrich_urls(name, list(urls))
                if research.get("status") not in {"ok", "partial"}:
                    return {
                        **base,
                        "status": "error",
                        "error": str(research.get("message") or "Candidate research failed."),
                    }
                merged = merge_candidate_profiles(name, research.get("profiles", []))
                qualification = qualify_candidate(
                    merged,
                    phd_qs_max=phd_qs_max,
                    employer_qs_max=employer_qs_max,
                    qs_edition=qs_edition,
                    allow_fortune_global_500=allow_fortune_global_500,
                    fortune_year=fortune_year,
                )
            result = {
                **base,
                "status": "ok",
                "merged_profile": merged,
                "qualification": qualification,
            }
            if include_research:
                result["research"] = research
            return result
        except Exception as exc:
            return {
                **base,
                "status": "error",
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            }

    results = await asyncio.gather(*(run_one(index, job) for index, job in enumerate(jobs)))
    decisions = Counter(
        item.get("qualification", {}).get("decision", "error")
        if item.get("status") == "ok"
        else "error"
        for item in results
    )
    summary = {
        "total": len(results),
        "eligible": decisions["eligible"],
        "ineligible": decisions["ineligible"],
        "review": decisions["review"],
        "error": decisions["error"],
    }
    return {
        "status": "ok" if not summary["error"] else "partial",
        "summary": summary,
        "results": results,
        "policy": "Candidate failures are isolated; unknown evidence remains review and never passes.",
    }


def batch_doctor() -> dict:
    return {
        "status": "ok",
        "max_batch_size": MAX_BATCH_SIZE,
        "max_concurrency": MAX_CONCURRENCY,
        "failure_isolation": True,
        "csv_formula_injection_protection": True,
        "accepted_input_modes": ["normalized profiles", "public profile URLs"],
    }
