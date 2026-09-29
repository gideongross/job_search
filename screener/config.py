"""Load and validate config.yaml."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

DEFAULT_CONFIG = Path("config.yaml")


class Profile(BaseModel):
    resume_path: Path
    home_location: str = "New York, NY"
    target_roles: list[str]
    title_variants: list[str] = []
    technical_title_patterns: list[str] = []
    target_seniority: str = ""
    background_notes: str = ""


class LocationFilter(BaseModel):
    enabled: bool = True
    accepted_locations: list[str]
    accepted_arrangements: list[str] = ["hybrid", "onsite"]


class SalaryFilter(BaseModel):
    enabled: bool = True
    floor: int


class Toggle(BaseModel):
    enabled: bool = True


class FundingFilter(BaseModel):
    enabled: bool = True
    rejected_stages: list[str] = ["pre_seed", "seed"]


class NonTechnicalFilter(BaseModel):
    enabled: bool = True
    reject_if_requires_coding: bool = True
    reject_if_cs_degree_required: bool = True
    allowed_technical_skills: list[str] = []


class Filters(BaseModel):
    location: LocationFilter
    salary: SalaryFilter
    ai_core: Toggle = Toggle()
    funding_stage: FundingFilter = FundingFilter()
    non_technical: NonTechnicalFilter = NonTechnicalFilter()


class Sector(BaseModel):
    label: str
    description: str


class NiceToHave(BaseModel):
    points_per_sector: int = 10
    max_bonus: int = 15
    sectors: dict[str, Sector]


class Weights(BaseModel):
    role_match: int = 30
    experience_match: int = 40
    seniority_fit: int = 15


class Thresholds(BaseModel):
    apply: int = 75
    maybe: int = 55


class Scoring(BaseModel):
    weights: Weights = Weights()
    thresholds: Thresholds = Thresholds()
    score_rejected: bool = False


class Effort(BaseModel):
    extract: str = "low"
    lookup: str = "low"
    score: str = "medium"
    tailor: str = "medium"


class LLMConfig(BaseModel):
    model: str = "claude-sonnet-5-5"
    max_tokens: int = 16000
    effort: Effort = Effort()
    refusal_fallback: bool = True


class CompanyLookup(BaseModel):
    enabled: bool = True
    web_search_max_uses: int = 5
    cache_ttl_days: int = 30


class Fetch(BaseModel):
    blocked_domains: list[str] = []
    respect_robots_txt: bool = True
    timeout_seconds: int = 20
    user_agent: str = "job-search-screener/0.1"


class Storage(BaseModel):
    results_csv: Path = Path("data/results.csv")
    company_cache: Path = Path("data/companies.json")
    tailoring_dir: Path = Path("data/tailoring")


class Config(BaseModel):
    profile: Profile
    filters: Filters
    nice_to_have: NiceToHave
    scoring: Scoring = Scoring()
    llm: LLMConfig = LLMConfig()
    company_lookup: CompanyLookup = CompanyLookup()
    fetch: Fetch = Fetch()
    storage: Storage = Storage()
    # Set at load time: directory of the config file, used to resolve relative paths.
    base_dir: Path = Field(default=Path("."), exclude=True)

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else (self.base_dir / path).resolve()


def load_config(path: Path = DEFAULT_CONFIG) -> Config:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    data = yaml.safe_load(path.read_text()) or {}
    cfg = Config.model_validate(data)
    cfg.base_dir = path.resolve().parent
    return cfg
