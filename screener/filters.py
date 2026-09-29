"""Hard filters — plain, deterministic code over extracted fields so every rejection is auditable.

Each rule returns pass / fail / unverified. Only "fail" rejects; "unverified" becomes a flag.
"""
from __future__ import annotations

from .config import Config
from .models import CompanyInfo, Extraction, FilterResult

STAGE_LABELS = {
    "pre_seed": "pre-seed", "seed": "seed", "series_a": "Series A", "series_b": "Series B",
    "series_c": "Series C", "series_d_plus": "Series D+", "late_stage_private": "late-stage private",
    "public": "public", "subsidiary": "subsidiary of a larger company", "bootstrapped": "bootstrapped",
    "unknown": "unknown",
}


def _matches_accepted_city(location: str, accepted: list[str]) -> bool:
    loc = location.lower()
    return any(a.lower() in loc for a in accepted)


def check_location(cfg: Config, ex: Extraction) -> FilterResult:
    rule = "location"
    lf = cfg.filters.location
    accepted_arr = {a.lower() for a in lf.accepted_arrangements}
    if not ex.locations:
        return FilterResult(rule=rule, status="unverified", detail="No location listed in posting")

    nyc = [o for o in ex.locations if _matches_accepted_city(o.location, lf.accepted_locations)]
    ok = [o for o in nyc if o.arrangement in accepted_arr]
    listed = "; ".join(f"{o.location} ({o.arrangement})" for o in ex.locations)
    if ok:
        return FilterResult(rule=rule, status="pass", detail=f"In-person/hybrid NYC option: {listed}")
    if any(o.arrangement == "unknown" for o in nyc):
        return FilterResult(rule=rule, status="unverified",
                            detail=f"NYC listed but work arrangement not stated: {listed}")
    if nyc:  # NYC appears only as a remote option
        return FilterResult(rule=rule, status="fail", detail=f"Fully remote (no hybrid/in-office NYC option): {listed}")
    if all(o.arrangement == "remote" for o in ex.locations):
        return FilterResult(rule=rule, status="fail", detail=f"Fully remote role: {listed}")
    return FilterResult(rule=rule, status="fail", detail=f"Based outside New York: {listed}")


def check_salary(cfg: Config, ex: Extraction) -> FilterResult:
    rule = "salary"
    floor = cfg.filters.salary.floor
    top = ex.salary_max or ex.salary_min
    if top is None:
        return FilterResult(rule=rule, status="unverified", detail="Salary unknown (not listed)")
    shown = ex.salary_text or "–".join(f"${v:,}" for v in (ex.salary_min, ex.salary_max) if v is not None)
    if top < floor:
        return FilterResult(rule=rule, status="fail", detail=f"Top of range {shown} is below ${floor:,} floor")
    if ex.salary_min is not None and ex.salary_min < floor:
        return FilterResult(rule=rule, status="pass", detail=f"{shown} — floor ${floor:,} is within range, negotiate")
    return FilterResult(rule=rule, status="pass", detail=f"{shown} meets ${floor:,} floor")


def check_ai_core(cfg: Config, company: CompanyInfo) -> FilterResult:
    rule = "ai_core"
    ev = f" — \"{company.ai_evidence}\"" if company.ai_evidence else ""
    if company.ai_core == "yes":
        return FilterResult(rule=rule, status="pass", detail=f"AI is core to product (source: {company.ai_source}){ev}")
    if company.ai_core == "no":
        return FilterResult(rule=rule, status="fail",
                            detail=f"AI is not core to the product (source: {company.ai_source}){ev}")
    return FilterResult(rule=rule, status="unverified", detail="AI focus unverified")


def check_funding(cfg: Config, company: CompanyInfo) -> FilterResult:
    rule = "funding_stage"
    stage = company.funding_stage
    label = STAGE_LABELS.get(stage, stage)
    ev = f" — \"{company.funding_evidence}\"" if company.funding_evidence else ""
    if stage == "unknown":
        return FilterResult(rule=rule, status="unverified", detail="Funding stage unverified")
    if stage in cfg.filters.funding_stage.rejected_stages:
        return FilterResult(rule=rule, status="fail",
                            detail=f"Company is {label}; must be Series A or later (source: {company.funding_source}){ev}")
    return FilterResult(rule=rule, status="pass", detail=f"{label} (source: {company.funding_source}){ev}")


def check_non_technical(cfg: Config, ex: Extraction) -> FilterResult:
    rule = "non_technical"
    nt = cfg.filters.non_technical
    reasons = []
    if nt.reject_if_requires_coding and ex.requires_coding:
        reasons.append("requires hands-on coding")
    if nt.reject_if_cs_degree_required and ex.cs_degree_required:
        reasons.append("CS degree required")
    if reasons:
        quotes = "; ".join(f"\"{q}\"" for q in ex.technical_evidence[:3])
        return FilterResult(rule=rule, status="fail",
                            detail=f"Technical role: {', '.join(reasons)}" + (f" — {quotes}" if quotes else ""))
    return FilterResult(rule=rule, status="pass", detail="No coding or CS-degree requirement")


def run_filters(cfg: Config, ex: Extraction, company: CompanyInfo) -> list[FilterResult]:
    f = cfg.filters
    results = []
    if f.location.enabled:
        results.append(check_location(cfg, ex))
    if f.salary.enabled:
        results.append(check_salary(cfg, ex))
    if f.ai_core.enabled:
        results.append(check_ai_core(cfg, company))
    if f.funding_stage.enabled:
        results.append(check_funding(cfg, company))
    if f.non_technical.enabled:
        results.append(check_non_technical(cfg, ex))
    return results
