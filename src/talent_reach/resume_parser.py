"""Evidence-first extraction of education, employment, and STEM indicators."""

from __future__ import annotations

import re

from talent_reach.models import EducationRecord, EmploymentRecord


DEGREE_PATTERN = re.compile(
    r"\b(?P<degree>"
    r"Ph\.?\s*D\.?|D\.?\s*Phil\.?|Doctor(?:ate|al degree)?|"
    r"M\.?\s*S\.?|S\.?\s*M\.?|MSc|MEng|Master(?:'s)?(?: degree)?|"
    r"B\.?\s*S\.?|BSc|BTech|Bachelor(?:'s)?(?: degree)?|undergraduate degree"
    r")\b"
    r"(?P<tail>[^.!?\n]{0,220})",
    re.I,
)
INSTITUTION_AFTER = re.compile(
    r"(?:from|at|,\s*)\s+(?P<institution>"
    r"(?:University of [A-Z][A-Za-z&.' -]+|"
    r"[A-Z][A-Za-z&.' -]+ University|"
    r"Massachusetts Institute of Technology|MIT|"
    r"California Institute of Technology|Caltech|"
    r"University of California,?\s+Berkeley|UC Berkeley|UCB|"
    r"ETH Zurich|EPFL|UCL))",
)
FIELD_BEFORE_INSTITUTION = re.compile(
    r"(?:in|of)\s+(?P<field>[A-Za-z][A-Za-z &/\-]{2,100}?)"
    r"(?:\s*\([^)]{1,40}\))?\s+(?:from|at)\s+",
    re.I,
)
YEAR_PATTERN = re.compile(r"\b(19\d{2}|20\d{2})\b")

CURRENT_EMPLOYMENT_PATTERNS = (
    re.compile(
        r"\bI am (?:an?|the)\s+(?P<title>[^.!?\n]{2,100}?)\s+at\s+"
        r"(?P<organization>[A-Z][^.!?\n]{2,100})",
        re.I,
    ),
    re.compile(
        r"\b(?P<title>(?:Assistant|Associate|Full|Bren|Distinguished) Professor[^.!?\n]{0,100}?)"
        r"\s+(?:at|,\s*)\s*(?P<organization>[A-Z][^.!?\n]{2,100})",
        re.I,
    ),
    re.compile(
        r"\bjoined the faculty of\s+(?P<title>[^.!?\n]{2,120}?)\s+at\s+"
        r"(?P<organization>[A-Z][^.!?\n]{2,100})",
        re.I,
    ),
)

STEM_KEYWORDS = {
    "aerospace",
    "artificial intelligence",
    "astronomy",
    "astrophysics",
    "bioengineering",
    "biology",
    "biomedical",
    "chemistry",
    "computer engineering",
    "computer science",
    "computing",
    "data science",
    "deep learning",
    "earth science",
    "electrical engineering",
    "engineering",
    "geology",
    "machine learning",
    "materials science",
    "mathematics",
    "mechanical engineering",
    "neuroscience",
    "optimization",
    "physics",
    "robotics",
    "statistics",
}


def _clean_institution(value: str) -> str:
    return re.sub(
        r"\s+(?:and|where|working|advised|in\s+\d{4}|\(\d{4}\)).*$",
        "",
        value.strip(" ,;:-"),
        flags=re.I,
    ).strip()


def _canonical_degree(value: str) -> str:
    compact = re.sub(r"[.\s]", "", value).casefold()
    if compact.startswith("phd"):
        return "PhD"
    if compact.startswith("dphil"):
        return "DPhil"
    if compact.startswith("doctor"):
        return "Doctorate"
    if compact in {"ms", "sm", "msc"} or compact.startswith("master"):
        return "Master's"
    if compact == "meng":
        return "MEng"
    if compact in {"bs", "bsc"} or compact.startswith("bachelor") or compact.startswith("undergraduate"):
        return "Bachelor's"
    if compact == "btech":
        return "BTech"
    return value.strip()


def extract_education(text: str, source_url: str) -> list[EducationRecord]:
    records: list[EducationRecord] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    masked = re.sub(
        r"(?i)ph\.\s*d\.",
        lambda match: "PhD" + " " * (len(match.group(0)) - 3),
        text,
    )
    boundaries = [0]
    boundaries.extend(match.end() for match in re.finditer(r"[.!?]\s+(?=[A-Z])|\n+", masked))
    boundaries.append(len(text))
    for match in DEGREE_PATTERN.finditer(text):
        clause_start = max(value for value in boundaries if value <= match.start())
        clause_end = min(value for value in boundaries if value > match.start())
        source_text = re.sub(r"\s+", " ", text[clause_start:clause_end]).strip()
        after_degree = text[match.end("degree"):clause_end]
        institution_match = INSTITUTION_AFTER.search(after_degree)
        institution = _clean_institution(institution_match.group("institution")) if institution_match else None
        field_match = FIELD_BEFORE_INSTITUTION.search(after_degree)
        field = field_match.group("field").strip(" ,;:-") if field_match else None
        year_match = YEAR_PATTERN.search(after_degree)
        degree = _canonical_degree(match.group("degree"))
        key = (degree, institution, field)
        if key in seen:
            continue
        seen.add(key)
        records.append(
            EducationRecord(
                degree=degree,
                institution=institution,
                field=field,
                year=int(year_match.group(1)) if year_match else None,
                source_url=source_url,
                source_text=source_text or match.group(0),
                confidence="high" if institution else "medium",
            )
        )
    return records[:20]


def extract_current_employment(text: str, source_url: str) -> list[EmploymentRecord]:
    for pattern in CURRENT_EMPLOYMENT_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        source_text = re.sub(r"\s+", " ", match.group(0)).strip()
        organization = re.sub(
            r"\s+(?:and|where|working|My|Before|Previously|in\s+(?:fall|spring|summer|winter|19\d{2}|20\d{2})).*$",
            "",
            match.group("organization").strip(" ,;:-"),
            flags=re.I,
        ).strip()
        return [
            EmploymentRecord(
                organization=organization,
                title=match.group("title").strip(" ,;:-"),
                source_url=source_url,
                source_text=source_text,
                confidence="high",
            )
        ]
    return []


def detect_stem(texts: list[str]) -> dict:
    haystack = " ".join(texts).casefold()
    matches = sorted(keyword for keyword in STEM_KEYWORDS if keyword in haystack)
    return {
        "is_stem": bool(matches),
        "matched_terms": matches,
        "basis": "explicit field, role, skill, or research text" if matches else "no explicit STEM term found",
    }
