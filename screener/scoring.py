"""Combine the LLM's component scores into a 0-100 score and a recommendation."""
from __future__ import annotations

from .config import Config
from .models import FitAssessment, Recommendation


def _clamp(v: int, hi: int) -> int:
    return max(0, min(int(v), hi))


def sector_bonus(cfg: Config, fit: FitAssessment) -> int:
    known = [s for s in dict.fromkeys(fit.matching_sectors) if s in cfg.nice_to_have.sectors]
    fit.matching_sectors = known
    return min(len(known) * cfg.nice_to_have.points_per_sector, cfg.nice_to_have.max_bonus)


def total_score(cfg: Config, fit: FitAssessment) -> tuple[int, int]:
    """Returns (score, sector_bonus). Clamps each component to its configured max."""
    w = cfg.scoring.weights
    fit.role_match = _clamp(fit.role_match, w.role_match)
    fit.experience_match = _clamp(fit.experience_match, w.experience_match)
    fit.seniority_fit = _clamp(fit.seniority_fit, w.seniority_fit)
    bonus = sector_bonus(cfg, fit)
    return min(fit.role_match + fit.experience_match + fit.seniority_fit + bonus, 100), bonus


def recommend(cfg: Config, score: int | None, passed_filters: bool) -> Recommendation:
    if not passed_filters or score is None:
        return "Skip"
    t = cfg.scoring.thresholds
    if score >= t.apply:
        return "Apply"
    if score >= t.maybe:
        return "Maybe"
    return "Skip"
