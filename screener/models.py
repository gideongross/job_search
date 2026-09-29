"""Data models: raw postings, LLM outputs (used as structured-output schemas), and results."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Arrangement = Literal["onsite", "hybrid", "remote", "unknown"]
FundingStage = Literal[
    "pre_seed", "seed", "series_a", "series_b", "series_c", "series_d_plus",
    "late_stage_private", "public", "subsidiary", "bootstrapped", "unknown",
]
TriState = Literal["yes", "no", "unknown"]
Recommendation = Literal["Apply", "Maybe", "Skip"]


class Posting(BaseModel):
    """A job posting as ingested, before any analysis."""
    text: str
    url: Optional[str] = None
    source: str = "pasted"          # "pasted", file path, "csv:<file>#<row id>", or URL
    fixture_key: Optional[str] = None  # used only by --dry-run to find canned responses
    title_hint: Optional[str] = None
    company_hint: Optional[str] = None


# ---------- Stage: extraction (LLM structured output) ----------

class LocationOption(BaseModel):
    location: str = Field(description="City/region as written, e.g. 'New York, NY' or 'Remote (US)'")
    arrangement: Arrangement


class Extraction(BaseModel):
    title: str
    company: str
    company_website: Optional[str] = Field(None, description="Company domain if stated in the posting")
    locations: list[LocationOption] = Field(description="Every location/arrangement option the posting offers")
    salary_min: Optional[int] = Field(None, description="Annual base salary lower bound in USD, null if not listed")
    salary_max: Optional[int] = Field(None, description="Annual base salary upper bound in USD, null if not listed")
    salary_text: Optional[str] = Field(None, description="Salary exactly as written")
    seniority: str = Field(description="e.g. 'Mid', 'Senior', 'Manager', 'Director', with years of experience if stated")
    key_requirements: list[str]
    red_flags: list[str] = Field(description="Concerns for the candidate: vague scope, unrealistic asks, "
                                             "on-call, heavy travel, missing salary, etc.")
    requires_coding: bool = Field(description="True only if hands-on software engineering or production "
                                              "coding is a real requirement (SQL/light analysis does not count)")
    cs_degree_required: bool = Field(description="True only if a CS/engineering degree is a hard requirement")
    technical_evidence: list[str] = Field(description="Verbatim quotes supporting the two technical judgments")
    ai_core: TriState = Field(description="Does the company build or deploy AI as a core part of its product, "
                                          "per the posting? 'unknown' if the posting doesn't say")
    ai_evidence: Optional[str] = Field(None, description="Verbatim quote supporting ai_core")
    funding_stage: FundingStage = Field(description="Only if the posting states it; otherwise 'unknown'")
    funding_evidence: Optional[str] = Field(None, description="Verbatim quote supporting funding_stage")


# ---------- Stage: company lookup ----------

class CompanyLookupResult(BaseModel):
    """LLM structured output from the web-search lookup."""
    funding_stage: FundingStage
    funding_evidence: Optional[str] = None
    funding_source_url: Optional[str] = None
    ai_core: TriState
    ai_evidence: Optional[str] = None
    ai_source_url: Optional[str] = None
    sectors_hint: Optional[str] = Field(None, description="One line on what the company sells and to whom")


class CompanyInfo(BaseModel):
    """Resolved company facts with provenance."""
    funding_stage: FundingStage = "unknown"
    funding_source: str = "unverified"   # "posting", a URL, or "unverified"
    funding_evidence: Optional[str] = None
    ai_core: TriState = "unknown"
    ai_source: str = "unverified"
    ai_evidence: Optional[str] = None
    summary: Optional[str] = None


# ---------- Stage: hard filters ----------

class FilterResult(BaseModel):
    rule: str
    status: Literal["pass", "fail", "unverified"]
    detail: str


# ---------- Stage: fit scoring (LLM structured output) ----------

class FitAssessment(BaseModel):
    role_match: int = Field(description="Points for role/title fit, 0..role_match max")
    experience_match: int = Field(description="Points for requirements met by the resume, 0..max")
    seniority_fit: int = Field(description="Points for level fit, 0..max")
    matching_sectors: list[str] = Field(description="Keys of nice-to-have sectors that clearly apply")
    explanation: str = Field(description="2-3 sentences on overall fit")
    requirements_met: list[str]
    gaps: list[str]


class Tailoring(BaseModel):
    resume_bullets: list[str] = Field(description="3-5 tailored resume bullet suggestions")
    cover_letter_points: list[str] = Field(description="3-5 cover letter talking points")


# ---------- Final result ----------

class ScreenResult(BaseModel):
    key: str
    posting: Posting
    extraction: Extraction
    company: CompanyInfo
    filters: list[FilterResult]
    flags: list[str]
    fit: Optional[FitAssessment] = None
    sector_bonus: int = 0
    score: Optional[int] = None
    recommendation: Recommendation
    tailoring: Optional[Tailoring] = None

    @property
    def passed(self) -> bool:
        return not any(f.status == "fail" for f in self.filters)

    @property
    def failed_rules(self) -> list[FilterResult]:
        return [f for f in self.filters if f.status == "fail"]
