"""Prompt builders. All candidate preferences come from config.yaml."""
from __future__ import annotations

from .config import Config
from .models import CompanyInfo, Extraction, FitAssessment


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- (none)"


def extraction_system(cfg: Config) -> str:
    allowed = ", ".join(cfg.filters.non_technical.allowed_technical_skills) or "SQL, light data analysis"
    return f"""You extract structured facts from job postings for a job-search screening tool.

Be literal: report what the posting says, not what is typical for such roles. Use null or "unknown"
when the posting doesn't state something — downstream code treats unknowns differently from negatives.

Guidance for the judgment fields:
- locations: list every location/arrangement option offered. "Hybrid in NYC or SF" is two entries.
  "Remote (US)" is a remote entry. If a city is named with no arrangement stated, use "unknown".
- salary: annual base in USD. Convert hourly (x2080) or "k" notation. Exclude equity/bonus/OTE.
- requires_coding: true only when writing software, scripts or production code is an actual part of
  the job or a hard requirement. These are fine and do NOT count as coding: {allowed}.
  "Technical fluency", "comfortable with APIs", or "works closely with engineers" is not coding.
- cs_degree_required: true only if a CS/engineering degree is required, not "preferred" or "or equivalent experience".
- ai_core: "yes" if the company's product is built on or delivers AI/ML (e.g. AI platform, models,
  AI-powered software it sells). "no" if AI is only used internally or not mentioned as part of the product.
  "unknown" if the posting doesn't describe the product well enough.
- funding_stage: only from explicit statements ("Series B", "publicly traded", "seed-funded"). Else "unknown".
- red_flags: things this candidate would want to know — missing salary, unclear scope, heavy travel,
  title/level mismatch, quota-carrying sales disguised as strategy, etc. Empty list if none."""


def extraction_user(text: str) -> str:
    return f"Extract the structured fields from this job posting.\n\n<posting>\n{text}\n</posting>"


def candidate_system(cfg: Config, resume_text: str) -> str:
    p = cfg.profile
    sectors = "\n".join(f"- {k}: {s.label} ({s.description})" for k, s in cfg.nice_to_have.sectors.items())
    extra = f"\nAdditional background from the candidate:\n{p.background_notes}\n" if p.background_notes else ""
    seniority = f"\nTarget seniority: {p.target_seniority}\n" if p.target_seniority else ""
    return f"""You help a job seeker decide which roles to apply to and how to position themselves.

The candidate is non-technical (does not write production code) and is based in {p.home_location}.

Target roles:
{_bullets(p.target_roles)}
Close title variants that also count:
{_bullets(p.title_variants)}
Roles like these are mismatches when they require coding:
{_bullets(p.technical_title_patterns)}
{seniority}
Nice-to-have sectors (keys in brackets):
{sectors}
{extra}
<resume>
{resume_text}
</resume>

Be candid. The candidate would rather skip a weak match than waste an application, and would rather
hear about a real gap now than in an interview. Never invent experience that isn't in the resume."""


def scoring_user(cfg: Config, posting_text: str, ex: Extraction, company: CompanyInfo) -> str:
    w = cfg.scoring.weights
    keys = ", ".join(cfg.nice_to_have.sectors)
    return f"""Score how well the candidate fits this role.

Scoring components (integers):
- role_match (0-{w.role_match}): how closely the actual work matches the target roles. Judge the work, not
  just the title — a "Strategy" title that is really sales or pure analytics scores low.
- experience_match (0-{w.experience_match}): how much of the stated requirements the resume clearly demonstrates.
- seniority_fit (0-{w.seniority_fit}): whether the level and years asked for match the candidate.
- matching_sectors: which of [{keys}] clearly apply to this company/role (can be empty).

requirements_met: requirements the resume clearly demonstrates, citing the evidence briefly.
gaps: requirements the resume doesn't show, or shows weakly.

Known company facts: funding stage = {company.funding_stage} (source: {company.funding_source});
AI is core to product = {company.ai_core} (source: {company.ai_source}).
{('Company summary: ' + company.summary) if company.summary else ''}

Extracted title: {ex.title} at {ex.company}; seniority: {ex.seniority}

<posting>
{posting_text}
</posting>"""


def lookup_system() -> str:
    return """You research companies for a job seeker. Use web search to determine two facts:

1. funding_stage: the company's latest funding stage (pre_seed, seed, series_a, series_b, series_c,
   series_d_plus, late_stage_private, public, subsidiary, bootstrapped). Prefer primary sources
   (company press releases, SEC filings) or reputable coverage (Crunchbase, TechCrunch, Bloomberg).
2. ai_core: whether the company builds or deploys AI as a core part of the product it sells
   ("yes"), or merely uses AI tools internally / isn't an AI product company ("no").

Give the URL you relied on for each. If you can't find reliable evidence, answer "unknown" —
a wrong answer is worse than "unknown". Watch out for different companies with similar names."""


def lookup_user(company: str, website: str | None, title: str) -> str:
    hint = f" (website: {website})" if website else ""
    return f"Company: {company}{hint}. It is hiring a '{title}'. Determine its funding stage and whether AI is core to its product."


def tailoring_user(posting_text: str, ex: Extraction, fit: FitAssessment) -> str:
    return f"""The candidate is applying to {ex.title} at {ex.company}.

Write:
- resume_bullets: 3-5 resume bullet suggestions that reframe the candidate's REAL experience (from the
  resume) toward this posting's requirements. Use strong verbs and keep any numbers that are in the resume;
  don't invent metrics — use [X] placeholders where a number would help but isn't known.
- cover_letter_points: 3-5 specific talking points connecting the candidate's background to this
  company and role, including how to address the main gap honestly.

Fit notes — met: {'; '.join(fit.requirements_met)}. Gaps: {'; '.join(fit.gaps)}.

<posting>
{posting_text}
</posting>"""
