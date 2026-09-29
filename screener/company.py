"""Resolve funding stage and AI focus: posting first, then Claude web search (cached per company)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import prompts
from .config import CompanyLookup
from .models import CompanyInfo, CompanyLookupResult, Extraction, Posting


def company_from_posting(ex: Extraction) -> CompanyInfo:
    info = CompanyInfo()
    if ex.funding_stage != "unknown":
        info.funding_stage, info.funding_source, info.funding_evidence = ex.funding_stage, "posting", ex.funding_evidence
    if ex.ai_core != "unknown":
        info.ai_core, info.ai_source, info.ai_evidence = ex.ai_core, "posting", ex.ai_evidence
    return info


def needs_lookup(info: CompanyInfo) -> bool:
    return info.funding_stage == "unknown" or info.ai_core == "unknown"


def _norm(name: str) -> str:
    name = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
    name = re.sub(r"\b(inc|llc|corp|corporation|co|ltd|technologies|labs)\b", " ", name)
    return " ".join(name.split())


class CompanyResolver:
    def __init__(self, cfg: CompanyLookup, llm, cache_path: Path):
        self.cfg = cfg
        self.llm = llm
        self.cache_path = cache_path
        self.cache: dict = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    def _cached(self, key: str) -> CompanyLookupResult | None:
        entry = self.cache.get(key)
        if not entry:
            return None
        age = datetime.now(timezone.utc) - datetime.fromisoformat(entry["fetched_at"])
        if age > timedelta(days=self.cfg.cache_ttl_days):
            return None
        return CompanyLookupResult.model_validate(entry["result"])

    def _save(self, key: str, company: str, result: CompanyLookupResult) -> None:
        self.cache[key] = {"company": company, "fetched_at": datetime.now(timezone.utc).isoformat(),
                           "result": result.model_dump()}
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, indent=2, sort_keys=True))

    def lookup(self, posting: Posting, ex: Extraction) -> CompanyLookupResult:
        key = _norm(ex.company)
        if (hit := self._cached(key)) is not None:
            return hit
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": self.cfg.web_search_max_uses}]
        result = self.llm.parse(task="lookup", system=prompts.lookup_system(),
                                user=prompts.lookup_user(ex.company, ex.company_website, ex.title),
                                schema=CompanyLookupResult, tools=tools, fixture_key=posting.fixture_key)
        self._save(key, ex.company, result)
        return result

    def resolve(self, posting: Posting, ex: Extraction) -> CompanyInfo:
        info = company_from_posting(ex)
        if not self.cfg.enabled or not needs_lookup(info):
            return info
        found = self.lookup(posting, ex)
        # Explicit statements in the posting win; lookup only fills unknowns.
        if info.funding_stage == "unknown" and found.funding_stage != "unknown":
            info.funding_stage = found.funding_stage
            info.funding_source = found.funding_source_url or "web search (no URL given)"
            info.funding_evidence = found.funding_evidence
        if info.ai_core == "unknown" and found.ai_core != "unknown":
            info.ai_core = found.ai_core
            info.ai_source = found.ai_source_url or "web search (no URL given)"
            info.ai_evidence = found.ai_evidence
        info.summary = found.sectors_hint
        return info
