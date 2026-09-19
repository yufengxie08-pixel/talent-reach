"""Normalized, source-grounded talent data models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Evidence(BaseModel):
    field: str
    value: str
    source_url: str
    basis: str
    observed_at: str = Field(default_factory=utc_now)
    confidence: Literal["high", "medium", "low"] = "high"


class Contact(BaseModel):
    kind: Literal["email", "website", "social"]
    value: str
    source_url: str
    visibility: Literal["explicit_public"] = "explicit_public"
    confidence: Literal["source-visible"] = "source-visible"
    owner_name: str | None = None
    owner_role: Literal[
        "candidate", "assistant", "administrator", "lab", "generic", "unknown"
    ] = "unknown"
    ownership_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    association_basis: str | None = None
    extraction_method: Literal[
        "visible_text",
        "visible_obfuscation_normalized",
        "mailto",
        "public_api",
        "public_cv_pdf",
        "unknown",
    ] = "unknown"
    source_text: str | None = None


class EducationRecord(BaseModel):
    degree: str
    institution: str | None = None
    field: str | None = None
    year: int | None = None
    source_url: str
    source_text: str
    confidence: Literal["high", "medium", "low"] = "medium"


class EmploymentRecord(BaseModel):
    organization: str
    title: str | None = None
    current: bool = True
    source_url: str
    source_text: str
    confidence: Literal["high", "medium", "low"] = "medium"


class TalentProfile(BaseModel):
    status: Literal["ok", "partial", "unavailable", "not_found"] = "ok"
    platform: str
    platform_id: str | None = None
    profile_url: str
    name: str | None = None
    headline: str | None = None
    location: str | None = None
    current_org: str | None = None
    education: list[str] = Field(default_factory=list)
    education_records: list[EducationRecord] = Field(default_factory=list)
    employment_records: list[EmploymentRecord] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    contacts: list[Contact] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    fetched_at: str = Field(default_factory=utc_now)
    raw_summary: str | None = None
    warnings: list[str] = Field(default_factory=list)
    sensitive_inferences: dict[str, str] = Field(
        default_factory=lambda: {"nationality": "not_inferred"}
    )

    def as_dict(self) -> dict:
        return self.model_dump(mode="json")


class SearchHit(BaseModel):
    platform: str
    title: str | None = None
    url: str
    snippet: str | None = None
    source_backend: str

    def as_dict(self) -> dict:
        return self.model_dump(mode="json")


class BackendHealth(BaseModel):
    platform: str
    status: Literal["ok", "warn", "off", "error"]
    active_backend: str | None = None
    backends: list[str]
    details: dict = Field(default_factory=dict)

    def as_dict(self) -> dict:
        return self.model_dump(mode="json")
