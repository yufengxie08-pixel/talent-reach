"""Low-level visible-page extraction shared by platform-specific backends."""

from __future__ import annotations

import json
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from talent_reach.contact_attribution import attribute_email
from talent_reach.fetch import PublicFetchError, fetch_public_page
from talent_reach.normalization import EMAIL_RE, visible_email_mentions
from talent_reach.routing import platform_for_url
import re


def _meta(soup: BeautifulSoup, *names: str) -> str | None:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    return None


def _jsonld_people(soup: BeautifulSoup) -> list[dict]:
    people: list[dict] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        values = payload if isinstance(payload, list) else [payload]
        for value in values:
            if not isinstance(value, dict):
                continue
            graph = value.get("@graph")
            if isinstance(graph, list):
                values.extend(item for item in graph if isinstance(item, dict))
            kind = value.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if "Person" in kinds:
                people.append(value)
    return people


def extract_public_profile(html: str, source_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    visible_text = " ".join(soup.stripped_strings)
    visible_text = re.sub(r"\s+", " ", visible_text).strip()

    person = (_jsonld_people(BeautifulSoup(html, "html.parser")) or [{}])[0]
    title = _meta(soup, "og:title", "twitter:title")
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()
    description = _meta(soup, "og:description", "description", "twitter:description")
    name = person.get("name") if isinstance(person.get("name"), str) else None
    if not name:
        name = title
    directory_name = re.search(r"Details\s+for\s+([A-Z][\w' -]+),\s*([A-Z][\w' -]+)", visible_text)
    if directory_name:
        name = f"{directory_name.group(2).strip()} {directory_name.group(1).strip()}"

    mentions = {item["value"]: item for item in visible_email_mentions(visible_text)}
    for item in mentions.values():
        visible_form = str(item.get("source_text") or item["value"])
        for node in soup.find_all(string=True):
            node_text = str(node)
            if visible_form.casefold() in node_text.casefold() or item["value"].casefold() in node_text.casefold():
                item["context"] = str(node.parent.get_text(" ", strip=True) if node.parent else node_text)[:500]
                break
    for anchor in soup.select('a[href^="mailto:"]'):
        address = str(anchor.get("href", ""))[7:].split("?", 1)[0].strip().lower()
        if EMAIL_RE.fullmatch(address):
            mentions[address] = {
                "value": address,
                "method": "mailto",
                "source_text": str(anchor.get_text(" ", strip=True) or address),
                "context": str(anchor.parent.get_text(" ", strip=True) if anchor.parent else address),
            }

    email_mentions = []
    for item in mentions.values():
        ownership = attribute_email(
            item["value"],
            candidate_name=name,
            context=item.get("context", ""),
            page_title=title,
            email_count=len(mentions),
        )
        email_mentions.append({**item, **ownership})

    links: set[str] = set()
    link_records: list[dict] = []
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href", "")).strip()
        if href.startswith(("http://", "https://", "/")):
            absolute = urljoin(source_url, href)
            host = (urlparse(absolute).hostname or "").lower()
            if host and absolute != source_url:
                links.add(absolute)
                link_records.append(
                    {
                        "url": absolute,
                        "text": str(anchor.get_text(" ", strip=True))[:160],
                    }
                )

    evidence = [
        {
            "field": "email",
            "value": item["value"],
            "source_url": source_url,
            "basis": f"{item['method']}; {item['association_basis']}",
        }
        for item in email_mentions
    ]
    if name:
        evidence.append({"field": "name", "value": name, "source_url": source_url, "basis": "page metadata"})

    return {
        "status": "ok",
        "platform": platform_for_url(source_url),
        "source_url": source_url,
        "name": name,
        "headline": person.get("jobTitle") if isinstance(person.get("jobTitle"), str) else description,
        "emails": sorted(mentions),
        "candidate_emails": sorted(
            item["value"]
            for item in email_mentions
            if item["owner_role"] == "candidate" and item["ownership_confidence"] >= 0.85
        ),
        "email_mentions": sorted(email_mentions, key=lambda item: item["value"]),
        "same_as": person.get("sameAs", []) if isinstance(person.get("sameAs"), list) else [],
        "links": sorted(links)[:100],
        "link_records": link_records[:150],
        "text_excerpt": visible_text[:12000],
        "evidence": evidence,
        "sensitive_inferences": {"nationality": "not_inferred"},
    }


async def read_public_profile(url: str) -> dict:
    try:
        page = await fetch_public_page(url)
    except PublicFetchError as exc:
        return {
            "status": "unavailable",
            "reason_code": exc.code,
            "message": str(exc),
            "platform": platform_for_url(url),
            "source_url": url,
            "emails": [],
            "evidence": [],
        }
    result = extract_public_profile(page.text, page.url)
    result["http_status"] = page.status_code
    result["content_type"] = page.content_type
    return result


_CONTACT_PATH_TERMS = (
    "contact",
    "about",
    "aboutme",
    "bio",
    "cv",
    "resume",
)

_SAFE_LINK_LABELS = ("about", "bio", "biography", "contact", "cv", "resume", "vita")
_BLOCKED_PATH_MARKERS = (
    "/people-finder",
    "/directory",
    "/people/",
    "/contact-us",
    "/search",
    "/staff",
    "/team",
)


def _crawl_candidate_allowed(start_url: str, link: dict) -> bool:
    clean, _ = urldefrag(str(link.get("url") or ""))
    start = urlparse(start_url)
    parsed = urlparse(clean)
    if (parsed.hostname or "").lower() != (start.hostname or "").lower():
        return False
    if clean == start_url or parsed.path.casefold().endswith(
        (".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png", ".zip")
    ):
        return False
    if start.query or "/people-finder" in start.path.casefold():
        return False
    path = parsed.path.casefold()
    label = str(link.get("text") or "").casefold().strip()
    if any(marker in path for marker in _BLOCKED_PATH_MARKERS):
        return False
    if parsed.query and any(key in parsed.query.casefold() for key in ("page=", "search=", "filter=")):
        return False
    return any(term in path for term in _CONTACT_PATH_TERMS) or any(
        label == term or label.startswith(term + " ") for term in _SAFE_LINK_LABELS
    )


async def crawl_public_site(url: str, max_pages: int = 5) -> dict:
    """Read a small, same-origin set of profile/contact pages without broad crawling."""
    max_pages = max(1, min(int(max_pages), 8))
    first = await read_public_profile(url)
    if first.get("status") != "ok":
        return {
            "status": first.get("status", "unavailable"),
            "start_url": url,
            "pages": [first],
            "public_emails": [],
        }

    candidates: list[str] = []
    for link in first.get("link_records", []):
        clean, _ = urldefrag(str(link.get("url") or ""))
        if clean not in candidates and _crawl_candidate_allowed(first["source_url"], link):
            candidates.append(clean)

    pages = [first]
    for candidate in candidates[: max_pages - 1]:
        pages.append(await read_public_profile(candidate))

    email_sources: dict[str, set[str]] = {}
    email_contacts: dict[str, dict] = {}
    warnings: list[str] = []
    for page in pages:
        if page.get("status") != "ok":
            continue
        mentions = page.get("email_mentions", [])
        if len(mentions) > 10:
            warnings.append(f"directory_page_email_limit:{page.get('source_url')}")
            continue
        for item in mentions:
            if item.get("owner_role") != "candidate" or float(item.get("ownership_confidence", 0)) < 0.85:
                continue
            email = str(item.get("value") or "")
            if not email:
                continue
            email_sources.setdefault(email, set()).add(page["source_url"])
            email_contacts[email] = {**item, "source_url": page["source_url"]}
    return {
        "status": "ok",
        "start_url": url,
        "pages_checked": len(pages),
        "pages": pages,
        "public_emails": [
            {
                "email": email,
                "sources": sorted(sources),
                "confidence": "source-visible",
            }
            for email, sources in sorted(email_sources.items())
        ],
        "candidate_email_contacts": [email_contacts[key] for key in sorted(email_contacts)],
        "warnings": warnings,
        "scope": "same-origin profile/contact pages only",
    }
