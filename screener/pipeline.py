"""End-to-end screening of one posting: extract -> company facts -> hard filters -> fit score."""
from __future__ import annotations

import re

from . import prompts
from .config import Config
from .filters import run_filters
from .models import CompanyInfo, Extraction, FitAssessment, Posting, ScreenResult
from .scoring import recommend, total_score


def company_title_key(company: str, title: str) -> str:
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return f"{norm(company)}|{norm(title)}"


def company_from_posting(ex: Extraction) -> CompanyInfo:
    info = CompanyInfo()
    if ex.funding_stage != "unknown":
        info.funding_stage, info.funding_source, info.funding_evidence = ex.funding_stage, "posting", ex.funding_evidence
    if ex.ai_core != "unknown":
        info.ai_core, info.ai_source, info.ai_evidence = ex.ai_core, "posting", ex.ai_evidence
    return info


class Screener:
    def __init__(self, cfg: Config, llm, resume_text: str):
        self.cfg = cfg
        self.llm = llm
        self.extract_system = prompts.extraction_system(cfg)
        self.candidate_system = prompts.candidate_system(cfg, resume_text)

    def extract(self, posting: Posting) -> Extraction:
        return self.llm.parse(task="extract", system=self.extract_system,
                              user=prompts.extraction_user(posting.text),
                              schema=Extraction, fixture_key=posting.fixture_key)

    def resolve_company(self, posting: Posting, ex: Extraction) -> CompanyInfo:
        return company_from_posting(ex)

    def screen(self, posting: Posting, ex: Extraction | None = None) -> ScreenResult:
        ex = ex or self.extract(posting)
        company = self.resolve_company(posting, ex)
        filters = run_filters(self.cfg, ex, company)
        flags = [f.detail for f in filters if f.status == "unverified"]
        passed = not any(f.status == "fail" for f in filters)

        fit = score = None
        bonus = 0
        if passed or self.cfg.scoring.score_rejected:
            fit = self.llm.parse(task="score", system=self.candidate_system,
                                 user=prompts.scoring_user(self.cfg, posting.text, ex, company),
                                 schema=FitAssessment, fixture_key=posting.fixture_key)
            score, bonus = total_score(self.cfg, fit)

        return ScreenResult(
            key=posting.url or company_title_key(ex.company, ex.title),
            posting=posting, extraction=ex, company=company, filters=filters, flags=flags,
            fit=fit, sector_bonus=bonus, score=score,
            recommendation=recommend(self.cfg, score, passed),
        )
