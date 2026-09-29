"""End-to-end screening of one posting: extract -> company facts -> hard filters -> fit score."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import prompts
from .company import CompanyResolver, company_from_posting, needs_lookup
from .config import Config
from .filters import run_filters
from .models import Extraction, FitAssessment, Posting, ScreenResult
from .scoring import recommend, total_score
from .store import ResultStore, company_title_key

COMPANY_RULES = {"ai_core", "funding_stage"}


@dataclass
class Outcome:
    posting: Posting
    result: Optional[ScreenResult] = None
    duplicate_of: Optional[dict] = None   # existing results.csv row, if skipped as a duplicate


class Screener:
    def __init__(self, cfg: Config, llm, resume_text: str, lookup: bool = True):
        self.cfg = cfg
        self.llm = llm
        self.lookup_enabled = lookup and cfg.company_lookup.enabled
        self.companies = CompanyResolver(cfg.company_lookup, llm, cfg.resolve(cfg.storage.company_cache))
        self.extract_system = prompts.extraction_system(cfg)
        self.candidate_system = prompts.candidate_system(cfg, resume_text)

    def extract(self, posting: Posting) -> Extraction:
        return self.llm.parse(task="extract", system=self.extract_system,
                              user=prompts.extraction_user(posting.text),
                              schema=Extraction, fixture_key=posting.fixture_key)

    def screen(self, posting: Posting, ex: Extraction | None = None) -> ScreenResult:
        ex = ex or self.extract(posting)

        company = company_from_posting(ex)
        filters = run_filters(self.cfg, ex, company)
        # Only pay for a web lookup if the posting survives the rules that don't depend on it.
        other_rules_pass = not any(f.status == "fail" and f.rule not in COMPANY_RULES for f in filters)
        if self.lookup_enabled and other_rules_pass and needs_lookup(company):
            company = self.companies.resolve(posting, ex)
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

    def process(self, posting: Posting, store: ResultStore, force: bool = False) -> Outcome:
        """Screen a posting unless it was already screened; save the result."""
        if not force and (dup := store.find(url=posting.url, text=posting.text)):
            return Outcome(posting, duplicate_of=dup)
        ex = self.extract(posting)
        if not force and (dup := store.find(company=ex.company, title=ex.title)):
            return Outcome(posting, duplicate_of=dup)
        result = self.screen(posting, ex)
        store.upsert(result)
        return Outcome(posting, result=result)
