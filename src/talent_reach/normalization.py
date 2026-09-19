"""Normalize rendered Markdown and legacy public-web results."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from talent_reach.contact_attribution import attribute_email
from talent_reach.models import Contact, Evidence, TalentProfile


EMAIL_RE = re.compile(
    r"(?<![\w@.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w@.-])", re.I
)
OBFUSCATED_EMAIL_RE = re.compile(
    r"(?<!\w)([A-Z0-9._%+-]+)\s*(?:\[at\]|\(at\))\s*([A-Z0-9.-]+)\s*(?:\[dot\]|\(dot\))\s*([A-Z]{2,})(?!\w)",
    re.I,
)
WORD_OBFUSCATED_EMAIL_RE = re.compile(
    r"(?<![\w@.+-])([A-Z0-9._%+-]+)\s+(?:\[at\]|\(at\)|at)\s+"
    r"([A-Z0-9-]+(?:\s+(?:\[dot\]|\(dot\)|dot)\s+[A-Z0-9-]+)+)(?![\w@.-])",
    re.I,
)
DOT_TOKEN_RE = re.compile(r"\s+(?:\[dot\]|\(dot\)|dot)\s+", re.I)
LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^\s)]+)")


def visible_emails(text: str) -> list[str]:
    values = {match.group(1).lower() for match in EMAIL_RE.finditer(text)}
    for match in OBFUSCATED_EMAIL_RE.finditer(text):
        values.add(f"{match.group(1)}@{match.group(2)}.{match.group(3)}".lower())
    for match in WORD_OBFUSCATED_EMAIL_RE.finditer(text):
        candidate = f"{match.group(1)}@{DOT_TOKEN_RE.sub('.', match.group(2))}".lower()
        if EMAIL_RE.fullmatch(candidate):
            values.add(candidate)
    return sorted(values)


def visible_email_mentions(text: str) -> list[dict]:
    """Return public email values with their visible extraction method and context."""
    mentions: dict[str, dict] = {}
    for match in EMAIL_RE.finditer(text):
        value = match.group(1).lower()
        mentions[value] = {
            "value": value,
            "method": "visible_text",
            "source_text": match.group(0),
            "context": text[max(0, match.start() - 140) : match.end() + 140],
        }
    for pattern in (OBFUSCATED_EMAIL_RE, WORD_OBFUSCATED_EMAIL_RE):
        for match in pattern.finditer(text):
            if pattern is OBFUSCATED_EMAIL_RE:
                value = f"{match.group(1)}@{match.group(2)}.{match.group(3)}".lower()
            else:
                value = f"{match.group(1)}@{DOT_TOKEN_RE.sub('.', match.group(2))}".lower()
            if EMAIL_RE.fullmatch(value):
                mentions[value] = {
                    "value": value,
                    "method": "visible_obfuscation_normalized",
                    "source_text": match.group(0),
                    "context": text[max(0, match.start() - 140) : match.end() + 140],
                }
    return [mentions[key] for key in sorted(mentions)]


def _section_bullets(markdown: str, heading: str) -> list[str]:
    """Return only nested bullet values belonging to a rendered section.

    About.me represents its profile fields as a top-level bullet followed by
    indented bullets.  A broad multiline regex used to accidentally absorb
    unrelated page text (for example Mastodon handles) into Education.  This
    small state machine deliberately stops at the first peer-level line.
    """

    lines = markdown.expandtabs(4).splitlines()
    heading_index: int | None = None
    heading_indent = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        label = re.sub(r"^[-*+]\s+", "", stripped).strip()
        if label.casefold() == heading.casefold():
            heading_index = index
            heading_indent = len(line) - len(line.lstrip())
            break
    if heading_index is None:
        return []

    values: list[str] = []
    for line in lines[heading_index + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())
        if stripped.startswith("#") or indent <= heading_indent:
            break
        bullet = re.match(r"^[-*+]\s+(.+)$", stripped)
        if not bullet:
            if values:
                break
            continue
        cleaned = bullet.group(1).strip()
        if cleaned and not cleaned.startswith("["):
            values.append(cleaned)
    return values[:20]


def profile_from_markdown(markdown: str, source_url: str, platform: str) -> TalentProfile:
    headings = [
        re.sub(r"^#+\s*", "", line).strip()
        for line in markdown.splitlines()
        if re.match(r"^#+\s+", line)
    ]
    if headings and headings[0].casefold().endswith(" on about.me") and len(headings) > 1:
        headings = headings[1:]
    name = headings[0] if headings else None
    headline = headings[1] if len(headings) > 1 else None
    links = sorted(set(LINK_RE.findall(markdown)))
    email_mentions = visible_email_mentions(markdown)
    education = _section_bullets(markdown, "Education")
    work = _section_bullets(markdown, "Work")
    evidence: list[Evidence] = []
    contacts: list[Contact] = []
    if name:
        evidence.append(Evidence(field="name", value=name, source_url=source_url, basis="rendered page heading"))
    for item in email_mentions:
        ownership = attribute_email(
            item["value"],
            candidate_name=name,
            context=item.get("context", ""),
            page_title=name,
            email_count=len(email_mentions),
        )
        contacts.append(
            Contact(
                kind="email",
                value=item["value"],
                source_url=source_url,
                owner_name=ownership["owner_name"],
                owner_role=ownership["owner_role"],
                ownership_confidence=ownership["ownership_confidence"],
                association_basis=ownership["association_basis"],
                extraction_method=item["method"],
                source_text=item["source_text"],
            )
        )
        evidence.append(
            Evidence(
                field="email",
                value=item["value"],
                source_url=source_url,
                basis=f"{item['method']}; {ownership['association_basis']}",
            )
        )
    for item in education:
        evidence.append(Evidence(field="education", value=item, source_url=source_url, basis="platform Education section"))
    return TalentProfile(
        platform=platform,
        platform_id=urlparse(source_url).path.strip("/") or None,
        profile_url=source_url,
        name=name,
        headline=headline,
        current_org=work[0] if work else None,
        education=education,
        contacts=contacts,
        links=links,
        evidence=evidence,
        raw_summary=markdown[:6000],
    )


def profile_from_public_result(result: dict, platform: str) -> TalentProfile:
    source_url = result.get("source_url") or result.get("profile_url") or ""
    contacts = []
    mentions = result.get("email_mentions", [])
    if mentions:
        for item in mentions:
            contacts.append(
                Contact(
                    kind="email",
                    value=item["value"],
                    source_url=source_url,
                    owner_name=item.get("owner_name"),
                    owner_role=item.get("owner_role", "unknown"),
                    ownership_confidence=float(item.get("ownership_confidence", 0)),
                    association_basis=item.get("association_basis"),
                    extraction_method=item.get("method", "unknown"),
                    source_text=item.get("source_text"),
                )
            )
    else:
        contacts = [
            Contact(kind="email", value=email, source_url=source_url)
            for email in result.get("emails", [])
        ]
    evidence = []
    for item in result.get("evidence", []):
        if item.get("field") and item.get("value") and item.get("source_url"):
            evidence.append(
                Evidence(
                    field=str(item["field"]),
                    value=str(item["value"]),
                    source_url=str(item["source_url"]),
                    basis=str(item.get("basis") or "public page"),
                )
            )
    status = result.get("status", "ok")
    if status not in {"ok", "partial", "unavailable", "not_found"}:
        status = "unavailable"
    return TalentProfile(
        status=status,
        platform=platform,
        profile_url=source_url,
        name=result.get("name"),
        headline=result.get("headline"),
        contacts=contacts,
        links=sorted(set(result.get("links", []) + result.get("same_as", []))),
        evidence=evidence,
        raw_summary=result.get("text_excerpt"),
        warnings=[result.get("message")] if result.get("message") else [],
    )
