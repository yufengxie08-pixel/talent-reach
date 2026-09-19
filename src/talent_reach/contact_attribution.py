"""Conservative ownership attribution for explicitly public email mentions."""

from __future__ import annotations

import re
import unicodedata


ROLE_MARKERS = {
    "assistant": (
        r"\badministrative assistant\b",
        r"\bresearch support\b",
        r"\bassistant\s*:",
        r"\bcoordinator\b",
    ),
    "administrator": (
        r"\badministrator\b",
        r"\badmin\s*:",
        r"\bmanager\b",
        r"\bwebmaster\b",
    ),
    "lab": (r"\blab contact\b", r"\bgroup contact\b", r"\bgeneral inquiries\b"),
}


def _tokens(value: str | None) -> list[str]:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.findall(r"[a-z0-9]+", normalized.casefold())


def attribute_email(
    email: str,
    *,
    candidate_name: str | None,
    context: str = "",
    page_title: str | None = None,
    email_count: int = 1,
) -> dict:
    """Attribute an email without guessing an address that is not visibly present."""
    local = email.split("@", 1)[0].casefold()
    context_lc = context.casefold()
    name_tokens = [token for token in _tokens(candidate_name) if len(token) >= 3]

    for role, markers in ROLE_MARKERS.items():
        if any(re.search(marker, context_lc) for marker in markers):
            return {
                "owner_name": None,
                "owner_role": role,
                "ownership_confidence": 0.9,
                "association_basis": f"visible role marker near email: {role}",
            }

    matched_tokens = [token for token in name_tokens if token in local]
    if matched_tokens:
        return {
            "owner_name": candidate_name,
            "owner_role": "candidate",
            "ownership_confidence": 0.98 if len(matched_tokens) >= 2 else 0.93,
            "association_basis": "email local-part visibly matches candidate name",
        }

    normalized_context = " ".join(_tokens(context))
    normalized_name = " ".join(name_tokens)
    if normalized_name and normalized_name in normalized_context and "email" in context_lc:
        return {
            "owner_name": candidate_name,
            "owner_role": "candidate",
            "ownership_confidence": 0.95,
            "association_basis": "candidate name and Email label appear in the same visible context",
        }

    title_tokens = set(_tokens(page_title))
    if email_count == 1 and name_tokens and set(name_tokens).issubset(title_tokens):
        return {
            "owner_name": candidate_name,
            "owner_role": "candidate",
            "ownership_confidence": 0.87,
            "association_basis": "single visible email on a candidate-named page",
        }

    return {
        "owner_name": None,
        "owner_role": "unknown",
        "ownership_confidence": 0.25,
        "association_basis": "visible email present but ownership is not established",
    }
