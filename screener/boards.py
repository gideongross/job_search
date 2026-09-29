"""List open roles from company job boards (Greenhouse, Lever, Ashby) via their public posting APIs."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

import httpx

from .config import Config, WatchCompany
from .models import Posting

BOARD_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}


@dataclass
class BoardJob:
    company: str
    title: str
    locations: list[str]
    url: str
    text: str
    fixture_key: str | None = None   # --dry-run only

    def to_posting(self) -> Posting:
        p = Posting(text=self.text, url=self.url, source=self.url, fixture_key=self.fixture_key)
        p.company_hint, p.title_hint = self.company, self.title
        return p


def _html_to_text(raw: str) -> str:
    import trafilatura
    return trafilatura.extract(f"<html><body>{raw}</body></html>") or re.sub(r"<[^>]+>", " ", raw)


def parse_greenhouse(company: str, data: dict) -> list[BoardJob]:
    jobs = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        body = _html_to_text(html.unescape(j.get("content", "")))
        jobs.append(BoardJob(company, j.get("title", ""), [loc] if loc else [], j.get("absolute_url", ""),
                             f"{company}\n{j.get('title', '')}\n{loc}\n\n{body}"))
    return jobs


def parse_lever(company: str, data: list) -> list[BoardJob]:
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        locs = cats.get("allLocations") or ([cats["location"]] if cats.get("location") else [])
        parts = [company, j.get("text", ""), " / ".join(locs), j.get("workplaceType", ""),
                 j.get("descriptionPlain", "")]
        for section in j.get("lists", []):
            parts += [section.get("text", ""), _html_to_text(f"<ul>{section.get('content', '')}</ul>")]
        parts.append(j.get("additionalPlain", ""))
        jobs.append(BoardJob(company, j.get("text", ""), locs, j.get("hostedUrl", ""),
                             "\n".join(p for p in parts if p)))
    return jobs


def parse_ashby(company: str, data: dict) -> list[BoardJob]:
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        locs = [l for l in locs if l]
        comp = (j.get("compensation") or {}).get("compensationTierSummary", "")
        body = j.get("descriptionPlain") or _html_to_text(j.get("descriptionHtml", ""))
        header = [company, j.get("title", ""), " / ".join(locs), j.get("workplaceType", ""), comp]
        jobs.append(BoardJob(company, j.get("title", ""), locs, j.get("jobUrl", ""),
                             "\n".join(p for p in header if p) + "\n\n" + body))
    return jobs


PARSERS = {"greenhouse": parse_greenhouse, "lever": parse_lever, "ashby": parse_ashby}


def fetch_board(client: httpx.Client, c: WatchCompany) -> list[BoardJob]:
    url = BOARD_URLS[c.ats].format(slug=c.slug)
    if c.ats == "ashby":
        url += "?includeCompensation=true"
    r = client.get(url)
    r.raise_for_status()
    return PARSERS[c.ats](c.name, r.json())


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("&", " and ")).strip()


def title_matches(cfg: Config, title: str) -> bool:
    t = _norm(title)
    if any(_norm(x) in t for x in cfg.watch.exclude_title_keywords + cfg.profile.technical_title_patterns):
        return False
    keywords = cfg.profile.target_roles + cfg.profile.title_variants + cfg.watch.extra_title_keywords
    return any(_norm(k) in t for k in keywords)


def location_matches(cfg: Config, locations: list[str]) -> bool:
    """Cheap pre-filter before paying for extraction; the real location rule runs later."""
    if not cfg.watch.require_location_match or not locations:
        return True
    return any(a.lower() in l.lower() for l in locations for a in cfg.filters.location.accepted_locations)


def find_jobs(cfg: Config) -> tuple[list[BoardJob], list[str]]:
    """Return (matching jobs across all watched companies, errors for boards that couldn't be read)."""
    matches, errors = [], []
    headers = {"User-Agent": cfg.fetch.user_agent}
    with httpx.Client(timeout=cfg.fetch.timeout_seconds, follow_redirects=True, headers=headers) as client:
        for c in cfg.watch.companies:
            try:
                jobs = fetch_board(client, c)
            except (httpx.HTTPError, ValueError) as e:
                errors.append(f"{c.name} ({c.ats}/{c.slug}): {e}")
                continue
            matches += [j for j in jobs if j.url and title_matches(cfg, j.title) and location_matches(cfg, j.locations)]
    return matches, errors
