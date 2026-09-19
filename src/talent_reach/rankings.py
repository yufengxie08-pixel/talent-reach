"""Versioned organization resolution and locally verified ranking snapshots."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse


QS_SOURCE = "https://www.topuniversities.com/qs-top-uni-wur"


class RankingSnapshotError(ValueError):
    pass


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _load_json(name: str) -> dict:
    path = files("talent_reach.data").joinpath(name)
    return json.loads(path.read_text(encoding="utf-8"))


def _is_public_source_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def validate_ranking_snapshot(payload: object, snapshot_kind: str) -> dict:
    """Validate a user-supplied QS or Fortune snapshot without modifying it."""
    kind = snapshot_kind.casefold().strip()
    errors: list[str] = []
    warnings: list[str] = []
    if kind not in {"qs", "fortune"}:
        return {
            "status": "invalid",
            "valid": False,
            "snapshot_kind": kind,
            "errors": ["snapshot_kind must be 'qs' or 'fortune'."],
            "warnings": [],
            "records": 0,
        }
    if not isinstance(payload, dict):
        return {
            "status": "invalid",
            "valid": False,
            "snapshot_kind": kind,
            "errors": ["Snapshot must be a JSON object."],
            "warnings": [],
            "records": 0,
        }

    organizations = payload.get("organizations")
    if not isinstance(organizations, list) or not organizations:
        errors.append("organizations must be a non-empty array.")
        organizations = []
    if len(organizations) > 10000:
        errors.append("organizations exceeds the 10,000-record safety limit.")
    edition = str(payload.get("edition") or "").strip()
    if not edition:
        errors.append("edition is required.")
    if not str(payload.get("coverage") or "").strip():
        errors.append("coverage is required.")
    if not _is_public_source_url(payload.get("source_url")):
        errors.append("source_url must be a public http(s) URL.")

    aliases_seen: dict[str, int] = {}
    domains_seen: dict[str, int] = {}
    for index, record in enumerate(organizations):
        prefix = f"organizations[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{prefix} must be an object.")
            continue
        canonical = str(record.get("canonical_name") or "").strip()
        if not canonical:
            errors.append(f"{prefix}.canonical_name is required.")
        aliases = record.get("aliases", [])
        domains = record.get("domains", [])
        if not isinstance(aliases, list) or not all(isinstance(value, str) for value in aliases):
            errors.append(f"{prefix}.aliases must be an array of strings.")
            aliases = []
        if not isinstance(domains, list) or not all(isinstance(value, str) for value in domains):
            errors.append(f"{prefix}.domains must be an array of strings.")
            domains = []
        if not _is_public_source_url(record.get("source_url", payload.get("source_url"))):
            errors.append(f"{prefix}.source_url must be a public http(s) URL.")

        for value in [canonical, *aliases]:
            normalized = _normalize(value)
            if not normalized:
                continue
            prior = aliases_seen.get(normalized)
            if prior is not None and prior != index:
                errors.append(f"{prefix} duplicates an organization alias from organizations[{prior}].")
            aliases_seen[normalized] = index
        for value in domains:
            normalized = value.casefold().strip().removeprefix("www.")
            if not normalized or "/" in normalized or ":" in normalized:
                errors.append(f"{prefix}.domains contains an invalid hostname: {value!r}.")
                continue
            prior = domains_seen.get(normalized)
            if prior is not None and prior != index:
                errors.append(f"{prefix} duplicates a domain from organizations[{prior}].")
            domains_seen[normalized] = index

        if kind == "qs":
            if record.get("type") != "university":
                errors.append(f"{prefix}.type must be 'university' for QS snapshots.")
            if record.get("ranking_system") != "QS_WUR":
                errors.append(f"{prefix}.ranking_system must be 'QS_WUR'.")
            if str(record.get("edition") or "") != edition:
                errors.append(f"{prefix}.edition must match the snapshot edition.")
            rank = record.get("rank")
            if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
                errors.append(f"{prefix}.rank must be a positive integer.")
            if not str(record.get("country_or_region") or "").strip():
                warnings.append(f"{prefix}.country_or_region is missing; overseas checks will review.")
        else:
            if record.get("type") != "company":
                errors.append(f"{prefix}.type must be 'company' for Fortune snapshots.")
            memberships = record.get("memberships")
            if not isinstance(memberships, list) or not memberships:
                errors.append(f"{prefix}.memberships must be a non-empty array.")
                memberships = []
            for member_index, membership in enumerate(memberships):
                member_prefix = f"{prefix}.memberships[{member_index}]"
                if not isinstance(membership, dict):
                    errors.append(f"{member_prefix} must be an object.")
                    continue
                if not str(membership.get("list") or "").strip():
                    errors.append(f"{member_prefix}.list is required.")
                if not isinstance(membership.get("year"), int):
                    errors.append(f"{member_prefix}.year must be an integer.")
                rank = membership.get("rank")
                if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
                    errors.append(f"{member_prefix}.rank must be a positive integer.")
                if not _is_public_source_url(membership.get("source_url")):
                    errors.append(f"{member_prefix}.source_url must be a public http(s) URL.")

    return {
        "status": "ok" if not errors else "invalid",
        "valid": not errors,
        "snapshot_kind": kind,
        "edition": edition or None,
        "records": len(organizations),
        "errors": errors,
        "warnings": warnings,
    }


def _validated_snapshot(payload: object, kind: str, source: str) -> dict:
    validation = validate_ranking_snapshot(payload, kind)
    if not validation["valid"]:
        detail = "; ".join(validation["errors"][:5])
        raise RankingSnapshotError(f"Invalid {kind} snapshot at {source}: {detail}")
    return payload


def _qs_snapshot() -> dict:
    configured = os.environ.get("TALENT_REACH_QS_DATA")
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise RankingSnapshotError(f"Configured QS snapshot does not exist: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RankingSnapshotError(f"Configured QS snapshot is unreadable: {type(exc).__name__}") from exc
        return _validated_snapshot(payload, "qs", str(path))
    payload = _load_json("qs_2027_verified_subset.json")
    return _validated_snapshot(payload, "qs", "built-in qs_2027_verified_subset.json")


def _fortune_records() -> list[dict]:
    configured = os.environ.get("TALENT_REACH_FORTUNE_DATA")
    if not configured:
        return []
    path = Path(configured)
    if not path.is_file():
        raise RankingSnapshotError(f"Configured Fortune snapshot does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RankingSnapshotError(f"Configured Fortune snapshot is unreadable: {type(exc).__name__}") from exc
    validated = _validated_snapshot(payload, "fortune", str(path))
    return validated["organizations"]


def _all_records() -> list[dict]:
    return _qs_snapshot()["organizations"] + _fortune_records()


def resolve_organization(name: str, domain: str | None = None) -> dict:
    query = _normalize(name)
    domain_lc = (domain or "").casefold().removeprefix("www.")
    matches = []
    try:
        records = _all_records()
    except RankingSnapshotError as exc:
        return {"status": "config_error", "query": name, "message": str(exc)}
    for record in records:
        names = [record["canonical_name"], *record.get("aliases", [])]
        name_match = query in {_normalize(value) for value in names}
        domain_match = bool(
            domain_lc
            and any(
                domain_lc == value.casefold() or domain_lc.endswith("." + value.casefold())
                for value in record.get("domains", [])
            )
        )
        if name_match or domain_match:
            matches.append({**record, "match_basis": "domain" if domain_match else "exact_alias"})
    if len(matches) == 1:
        return {"status": "resolved", "organization": matches[0]}
    if len(matches) > 1:
        return {"status": "ambiguous", "matches": matches}
    return {
        "status": "unresolved",
        "query": name,
        "message": "Organization is not in the installed verified snapshots; do not infer a rank.",
    }


def get_university_rank(name: str, edition: str = "2027", domain: str | None = None) -> dict:
    try:
        snapshot = _qs_snapshot()
    except RankingSnapshotError as exc:
        return {"status": "config_error", "ranking_system": "QS_WUR", "message": str(exc)}
    if edition != str(snapshot.get("edition")):
        return {
            "status": "unavailable",
            "ranking_system": "QS_WUR",
            "edition": edition,
            "message": f"The installed QS snapshot is edition {snapshot.get('edition')}.",
        }
    resolved = resolve_organization(name, domain)
    if resolved["status"] != "resolved":
        return {**resolved, "ranking_system": "QS_WUR", "edition": edition}
    record = resolved["organization"]
    if record.get("type") != "university" or record.get("ranking_system") != "QS_WUR":
        return {
            "status": "not_a_ranked_university",
            "organization": record,
            "ranking_system": "QS_WUR",
            "edition": edition,
        }
    return {
        "status": "ok",
        "canonical_name": record["canonical_name"],
        "rank": record["rank"],
        "ranking_system": "QS_WUR",
        "edition": edition,
        "country_or_region": record.get("country_or_region"),
        "source_url": record["source_url"],
        "coverage": snapshot["coverage"],
        "match_basis": record.get("match_basis", resolved["organization"].get("match_basis")),
    }


def get_company_membership(
    name: str, list_name: str = "fortune_global_500", year: int | None = None
) -> dict:
    try:
        records = _fortune_records()
    except RankingSnapshotError as exc:
        return {"status": "config_error", "list": list_name, "year": year, "message": str(exc)}
    if not records:
        return {
            "status": "unavailable",
            "list": list_name,
            "year": year,
            "message": (
                "No licensed or user-supplied Fortune snapshot is installed. Set "
                "TALENT_REACH_FORTUNE_DATA to a verified JSON snapshot."
            ),
        }
    resolved = resolve_organization(name)
    if resolved["status"] != "resolved":
        return {**resolved, "list": list_name, "year": year}
    record = resolved["organization"]
    memberships = record.get("memberships", [])
    hits = [
        item
        for item in memberships
        if item.get("list") == list_name and (year is None or int(item.get("year", 0)) == year)
    ]
    return {
        "status": "ok",
        "canonical_name": record["canonical_name"],
        "is_member": bool(hits),
        "memberships": hits,
        "list": list_name,
        "year": year,
    }


def ranking_doctor() -> dict:
    try:
        snapshot = _qs_snapshot()
        qs_status = "ok"
        qs_error = None
    except RankingSnapshotError as exc:
        snapshot = {"edition": None, "coverage": None, "organizations": [], "source_url": None}
        qs_status = "config_error"
        qs_error = str(exc)
    try:
        fortune = _fortune_records()
        fortune_error = None
    except RankingSnapshotError as exc:
        fortune = []
        fortune_error = str(exc)
    return {
        "status": "ok" if qs_status == "ok" and not fortune_error else "warn",
        "qs": {
            "status": qs_status,
            "edition": snapshot["edition"],
            "coverage": snapshot["coverage"],
            "records": len(snapshot["organizations"]),
            "source_url": snapshot["source_url"],
            "configured_path": os.environ.get("TALENT_REACH_QS_DATA"),
            "error": qs_error,
        },
        "fortune": {
            "status": "config_error" if fortune_error else ("configured" if fortune else "not_configured"),
            "records": len(fortune),
            "policy": "No unofficial or guessed Fortune membership is bundled.",
            "error": fortune_error,
        },
    }
