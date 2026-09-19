"""Bounded personal-site, browser fallback, and public CV backend."""

from __future__ import annotations

import re
from io import BytesIO
from urllib.parse import urldefrag, urlparse

from pypdf import PdfReader

from talent_reach.contact_attribution import attribute_email
from talent_reach.connectors.public_web import crawl_public_site
from talent_reach.fetch import fetch_public_binary
from talent_reach.models import (
    BackendHealth,
    Contact,
    EducationRecord,
    EmploymentRecord,
    Evidence,
    TalentProfile,
)
from talent_reach.normalization import LINK_RE, visible_email_mentions
from talent_reach.opencli import read_markdown
from talent_reach.resume_parser import detect_stem, extract_current_employment, extract_education


BACKENDS = ["bounded-direct-crawler", "OpenCLI-browser", "public-CV-PDF"]


def _clean_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.split(r"\s+[|–—]\s+|,\s+(?:Stanford|MIT|UC |University|Caltech)", value, maxsplit=1)[0]
    return cleaned.strip() or None


def _contact_from_mention(
    item: dict, *, candidate_name: str | None, source_url: str, email_count: int,
    extraction_method: str | None = None,
) -> Contact:
    ownership = attribute_email(
        item["value"],
        candidate_name=candidate_name,
        context=item.get("context", ""),
        page_title=candidate_name,
        email_count=email_count,
    )
    return Contact(
        kind="email",
        value=item["value"],
        source_url=source_url,
        owner_name=ownership["owner_name"],
        owner_role=ownership["owner_role"],
        ownership_confidence=ownership["ownership_confidence"],
        association_basis=ownership["association_basis"],
        extraction_method=extraction_method or item.get("method", "unknown"),
        source_text=item.get("source_text"),
    )


async def read_cv_pdf(url: str, candidate_name: str | None = None) -> dict:
    """Read a directly supplied public PDF with bounded size and page count."""
    try:
        binary = await fetch_public_binary(url)
        reader = PdfReader(BytesIO(binary.data))
        page_texts = [(page.extract_text() or "") for page in reader.pages[:20]]
        text = "\n".join(page_texts)
    except Exception as exc:
        return TalentProfile(
            status="unavailable",
            platform="public_cv_pdf",
            profile_url=url,
            name=candidate_name,
            warnings=[f"Public CV PDF unavailable: {type(exc).__name__}: {str(exc)[:240]}"],
        ).as_dict()

    if not text.strip():
        return TalentProfile(
            status="partial",
            platform="public_cv_pdf",
            profile_url=url,
            name=candidate_name,
            warnings=["ocr_required: PDF contains no extractable text"],
        ).as_dict()

    inferred_name = candidate_name
    if not inferred_name:
        first_lines = [line.strip() for line in page_texts[0].splitlines() if line.strip()]
        inferred_name = first_lines[0][:120] if first_lines else None
    mentions = visible_email_mentions(text)
    contacts = [
        _contact_from_mention(
            item,
            candidate_name=inferred_name,
            source_url=binary.url,
            email_count=len(mentions),
            extraction_method="public_cv_pdf",
        )
        for item in mentions
    ]
    education_records = extract_education(text, binary.url)
    employment_records = extract_current_employment(text, binary.url)
    evidence = [
        Evidence(
            field="email",
            value=contact.value,
            source_url=binary.url,
            basis=f"visible text in public CV PDF; {contact.association_basis}",
        )
        for contact in contacts
    ]
    evidence.extend(
        Evidence(
            field="education",
            value=record.source_text,
            source_url=binary.url,
            basis="visible text in public CV PDF",
            confidence=record.confidence,
        )
        for record in education_records
    )
    evidence.extend(
        Evidence(
            field="current_org",
            value=record.organization,
            source_url=binary.url,
            basis="visible current-role statement in public CV PDF",
            confidence=record.confidence,
        )
        for record in employment_records
    )
    return TalentProfile(
        platform="public_cv_pdf",
        profile_url=binary.url,
        name=inferred_name,
        current_org=employment_records[0].organization if employment_records else None,
        education=[record.source_text for record in education_records],
        education_records=education_records,
        employment_records=employment_records,
        contacts=contacts,
        evidence=evidence,
        raw_summary=text[:12000],
        warnings=[f"pdf_pages_read={min(len(reader.pages), 20)}"],
    ).as_dict()


async def _browser_fallback(url: str) -> dict:
    host = (urlparse(url).hostname or "").lower()
    try:
        markdown = await read_markdown(url, {host})
    except Exception as exc:
        return {
            "status": "unavailable",
            "source_url": url,
            "message": f"browser fallback unavailable: {type(exc).__name__}",
        }
    headings = [
        re.sub(r"^#+\s*", "", line).strip()
        for line in markdown.splitlines()
        if re.match(r"^#+\s+", line)
    ]
    name = _clean_name(headings[0] if headings else None)
    mentions = visible_email_mentions(markdown)
    contacts = [
        _contact_from_mention(
            item, candidate_name=name, source_url=url, email_count=len(mentions)
        ).model_dump(mode="json")
        for item in mentions
    ]
    return {
        "status": "ok",
        "source_url": url,
        "name": name,
        "headline": headings[1] if len(headings) > 1 else None,
        "text_excerpt": markdown[:12000],
        "links": sorted(set(LINK_RE.findall(markdown)))[:150],
        "candidate_email_contacts": [
            item
            for item in contacts
            if item.get("owner_role") == "candidate"
            and float(item.get("ownership_confidence", 0)) >= 0.85
        ],
        "active_backend": "OpenCLI-browser",
    }


async def read_site(url: str, max_pages: int = 5, include_cv_pdf: bool = True) -> dict:
    if urlparse(url).path.casefold().endswith(".pdf"):
        return await read_cv_pdf(url)

    crawl = await crawl_public_site(url, max_pages=max_pages)
    browser_used = False
    if crawl.get("status") != "ok":
        fallback = await _browser_fallback(url)
        if fallback.get("status") != "ok":
            return TalentProfile(
                status="unavailable",
                platform="personal_site",
                profile_url=url,
                warnings=[
                    crawl.get("message") or crawl.get("status", "unavailable"),
                    fallback.get("message", "browser fallback unavailable"),
                ],
            ).as_dict()
        browser_used = True
        crawl = {
            "status": "ok",
            "pages": [fallback],
            "candidate_email_contacts": fallback.get("candidate_email_contacts", []),
            "warnings": [],
        }

    pages = [page for page in crawl.get("pages", []) if page.get("status") == "ok"]
    first = pages[0] if pages else {}
    name = _clean_name(first.get("name"))
    contacts: list[Contact] = []
    evidence: list[Evidence] = []
    links: set[str] = set()
    all_text: list[str] = []
    education_records: list[EducationRecord] = []
    employment_records: list[EmploymentRecord] = []
    contact_records = {
        (item.get("value"), item.get("source_url")): item
        for item in crawl.get("candidate_email_contacts", [])
    }
    for page in pages:
        source = page.get("source_url") or url
        links.update(page.get("links", []))
        text = str(page.get("text_excerpt") or "")
        if text:
            all_text.append(text)
            education_records.extend(extract_education(text, source))
            employment_records.extend(extract_current_employment(text, source))
        for item in page.get("email_mentions", []):
            if item.get("owner_role") == "candidate" and float(item.get("ownership_confidence", 0)) >= 0.85:
                contact_records[(item.get("value"), source)] = {**item, "source_url": source}

    for item in contact_records.values():
        contact = Contact(
            kind="email",
            value=item["value"],
            source_url=item.get("source_url") or url,
            owner_name=item.get("owner_name") or name,
            owner_role="candidate",
            ownership_confidence=float(item.get("ownership_confidence", 0.85)),
            association_basis=item.get("association_basis"),
            extraction_method=item.get("method") or item.get("extraction_method", "visible_text"),
            source_text=item.get("source_text"),
        )
        contacts.append(contact)
        evidence.append(
            Evidence(
                field="email",
                value=contact.value,
                source_url=contact.source_url,
                basis=contact.association_basis or "visible candidate-owned email",
            )
        )

    warnings: list[str] = list(crawl.get("warnings", []))
    combined_text = "\n".join(all_text)
    evidence.extend(
        Evidence(
            field="education",
            value=record.source_text,
            source_url=record.source_url,
            basis="explicit education statement on public biography",
            confidence=record.confidence,
        )
        for record in education_records
    )
    evidence.extend(
        Evidence(
            field="current_org",
            value=record.organization,
            source_url=record.source_url,
            basis="explicit current-role statement on public biography",
            confidence=record.confidence,
        )
        for record in employment_records
    )

    if include_cv_pdf:
        origin_host = (urlparse(first.get("source_url") or url).hostname or "").lower()
        pdf_links = sorted(
            {
                urldefrag(link)[0]
                for link in links
                if (urlparse(link).hostname or "").lower() == origin_host
                and urlparse(link).path.casefold().endswith(".pdf")
                and any(term in urlparse(link).path.casefold() for term in ("cv", "resume", "vita"))
            }
        )[:2]
        for pdf_url in pdf_links:
            cv = await read_cv_pdf(pdf_url, name)
            if cv.get("status") not in {"ok", "partial"}:
                warnings.extend(cv.get("warnings", []))
                continue
            contacts.extend(Contact.model_validate(item) for item in cv.get("contacts", []))
            education_records.extend(
                EducationRecord.model_validate(item)
                for item in cv.get("education_records", [])
            )
            employment_records.extend(
                EmploymentRecord.model_validate(item)
                for item in cv.get("employment_records", [])
            )
            evidence.extend(Evidence.model_validate(item) for item in cv.get("evidence", []))

    unique_contacts: dict[tuple[str, str], Contact] = {}
    for contact in contacts:
        key = (contact.kind, contact.value.casefold())
        prior = unique_contacts.get(key)
        if not prior or contact.ownership_confidence > prior.ownership_confidence:
            unique_contacts[key] = contact
    unique_education = {}
    for record in education_records:
        unique_education[(record.degree, record.institution, record.field)] = record
    unique_employment = {}
    for record in employment_records:
        unique_employment[(record.organization, record.title)] = record
    stem = detect_stem(
        [combined_text, first.get("headline") or "", *[record.field or "" for record in unique_education.values()]]
    )
    current_org = next(iter(unique_employment.values())).organization if unique_employment else None
    return TalentProfile(
        platform="personal_site",
        profile_url=first.get("source_url") or url,
        name=name,
        headline=first.get("headline"),
        current_org=current_org,
        education=[record.source_text for record in unique_education.values()],
        education_records=list(unique_education.values()),
        employment_records=list(unique_employment.values()),
        skills=stem["matched_terms"],
        contacts=list(unique_contacts.values()),
        links=sorted(links)[:150],
        evidence=evidence,
        raw_summary=combined_text[:12000] or None,
        warnings=warnings
        + [f"pages_checked={len(pages)}", f"active_backend={'OpenCLI-browser' if browser_used else 'bounded-direct-crawler'}"],
    ).as_dict()


def doctor() -> dict:
    return BackendHealth(
        platform="personal_site",
        status="ok",
        active_backend="bounded-direct-crawler",
        backends=BACKENDS,
        details={
            "max_pages": 8,
            "max_pdf_bytes": 5_000_000,
            "max_pdf_pages": 20,
            "ssrf_protection": True,
            "browser_fallback": True,
            "candidate_email_ownership_required": True,
        },
    ).as_dict()
