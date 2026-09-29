"""Persist results to a CSV you can track over time, and dedupe already-screened postings.

Dedupe keys, checked in order (cheapest first, so re-runs don't spend API calls):
  1. normalized URL                       — before extraction
  2. hash of the posting text             — before extraction
  3. normalized company + title           — after extraction
"""
from __future__ import annotations

import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .models import ScreenResult
from .report import location_str

COLUMNS = [
    "screened_at", "recommendation", "score", "company", "title", "location", "salary_min", "salary_max",
    "seniority", "funding_stage", "funding_source", "ai_core", "ai_source", "hard_filters", "failed_rules",
    "flags", "sectors", "explanation", "requirements_met", "gaps", "red_flags", "url", "source",
    "url_key", "text_hash", "company_title_key",
    # Yours to edit in a spreadsheet; preserved when a posting is re-screened with --force.
    "status", "notes",
]
USER_COLUMNS = ("status", "notes")


def url_key(url: str | None) -> str:
    if not url:
        return ""
    u = urlparse(url.strip())
    return f"{u.netloc.lower().removeprefix('www.')}{u.path.rstrip('/')}"


def text_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).lower().encode()).hexdigest()[:16]


def company_title_key(company: str, title: str) -> str:
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return f"{norm(company)}|{norm(title)}"


class ResultStore:
    def __init__(self, path: Path):
        self.path = path
        self.rows: list[dict] = []
        if path.exists():
            with path.open(newline="", encoding="utf-8") as fh:
                self.rows = list(csv.DictReader(fh))

    def find(self, *, url: str | None = None, text: str | None = None,
             company: str | None = None, title: str | None = None) -> dict | None:
        checks = []
        if url:
            checks.append(("url_key", url_key(url)))
        if text:
            checks.append(("text_hash", text_hash(text)))
        if company and title:
            checks.append(("company_title_key", company_title_key(company, title)))
        for col, val in checks:
            for row in self.rows:
                if val and row.get(col) == val:
                    return row
        return None

    def upsert(self, r: ScreenResult) -> None:
        ex, fit = r.extraction, r.fit
        row = {
            "screened_at": datetime.now().isoformat(timespec="seconds"),
            "recommendation": r.recommendation,
            "score": "" if r.score is None else r.score,
            "company": ex.company, "title": ex.title, "location": location_str(r),
            "salary_min": ex.salary_min or "", "salary_max": ex.salary_max or "",
            "seniority": ex.seniority,
            "funding_stage": r.company.funding_stage, "funding_source": r.company.funding_source,
            "ai_core": r.company.ai_core, "ai_source": r.company.ai_source,
            "hard_filters": "PASS" if r.passed else "FAIL",
            "failed_rules": " | ".join(f"{f.rule}: {f.detail}" for f in r.failed_rules),
            "flags": " | ".join(r.flags),
            "sectors": ", ".join(fit.matching_sectors) if fit else "",
            "explanation": fit.explanation if fit else "",
            "requirements_met": " | ".join(fit.requirements_met) if fit else "",
            "gaps": " | ".join(fit.gaps) if fit else "",
            "red_flags": " | ".join(ex.red_flags),
            "url": r.posting.url or "", "source": r.posting.source,
            "url_key": url_key(r.posting.url), "text_hash": text_hash(r.posting.text),
            "company_title_key": company_title_key(ex.company, ex.title),
            "status": "", "notes": "",
        }
        existing = self.find(url=r.posting.url, text=r.posting.text, company=ex.company, title=ex.title)
        if existing:
            for col in USER_COLUMNS:
                row[col] = existing.get(col, "")
            self.rows[self.rows.index(existing)] = row
        else:
            self.rows.append(row)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(self.rows)
        tmp.replace(self.path)


def save_tailoring(r: ScreenResult, folder: Path) -> Path | None:
    """Write resume bullets and cover-letter points for an Apply result to a Markdown file."""
    if not r.tailoring:
        return None
    ex = r.extraction
    slug = re.sub(r"[^a-z0-9]+", "-", f"{ex.company} {ex.title}".lower()).strip("-")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{slug}.md"
    lines = [f"# {ex.title} — {ex.company}", "",
             f"Score {r.score}/100 · screened {datetime.now():%Y-%m-%d}" + (f" · {r.posting.url}" if r.posting.url else ""),
             "", r.fit.explanation if r.fit else "", "",
             "## Tailored resume bullets", *[f"- {b}" for b in r.tailoring.resume_bullets], "",
             "## Cover letter talking points", *[f"- {p}" for p in r.tailoring.cover_letter_points], ""]
    if r.fit and r.fit.gaps:
        lines += ["## Gaps to prepare for", *[f"- {g}" for g in r.fit.gaps], ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
