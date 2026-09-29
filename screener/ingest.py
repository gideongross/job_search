"""Turn user input (pasted text, files, folders, CSVs, URLs) into Posting objects."""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import httpx

from .config import Fetch
from .models import Posting

POSTING_SUFFIXES = {".txt", ".md", ".html", ".htm"}
CSV_TEXT_COLUMNS = ("text", "description", "job_description", "posting")


class FetchError(RuntimeError):
    """The URL couldn't (or shouldn't) be fetched; the caller should ask for pasted text."""


def from_text(text: str, source: str = "pasted", fixture_key: str | None = None) -> Posting:
    text = text.strip()
    if len(text) < 100:
        raise ValueError("Posting text is too short to screen (under 100 characters).")
    return Posting(text=text, source=source, fixture_key=fixture_key)


def from_file(path: Path) -> Posting:
    raw = path.read_text(encoding="utf-8", errors="replace")
    url = None
    # Saved postings may start with a "URL: ..." line so dedupe-by-URL works for them too.
    first, _, rest = raw.partition("\n")
    if first.lower().startswith("url:"):
        url, raw = first[4:].strip() or None, rest
    if path.suffix.lower() in {".html", ".htm"}:
        import trafilatura
        raw = trafilatura.extract(raw) or raw
    p = from_text(raw, source=str(path), fixture_key=path.stem)
    p.url = url
    return p


def from_folder(folder: Path) -> list[Posting]:
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in POSTING_SUFFIXES)
    if not files:
        raise ValueError(f"No posting files ({', '.join(sorted(POSTING_SUFFIXES))}) found in {folder}")
    return [from_file(f) for f in files]


def from_csv(path: Path) -> list[Posting]:
    """CSV with a text/description column; optional url, company, title, id columns."""
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"{path} has no rows")
    cols = {c.lower().strip(): c for c in rows[0].keys()}
    text_col = next((cols[c] for c in CSV_TEXT_COLUMNS if c in cols), None)
    if not text_col:
        raise ValueError(f"{path} needs one of these columns: {', '.join(CSV_TEXT_COLUMNS)}")
    def get(row: dict, name: str) -> str | None:
        return (row.get(cols[name]) or "").strip() or None if name in cols else None

    postings = []
    for i, row in enumerate(rows, 1):
        row_id = get(row, "id") or str(i)
        p = from_text(row[text_col] or "", source=f"{path.name}#{row_id}", fixture_key=get(row, "id"))
        p.url, p.company_hint, p.title_hint = get(row, "url"), get(row, "company"), get(row, "title")
        postings.append(p)
    return postings


def from_path(path: Path) -> list[Posting]:
    if path.is_dir():
        return from_folder(path)
    if path.suffix.lower() == ".csv":
        return from_csv(path)
    return [from_file(path)]


# ---------- URLs ----------

def _is_blocked(host: str, blocked: list[str]) -> bool:
    host = host.lower()
    return any(host == d or host.endswith("." + d) for d in blocked)


def _ats_api_url(url: str) -> str | None:
    """Public JSON APIs offered by applicant-tracking systems for exactly this use."""
    u = urlparse(url)
    m = re.match(r"/([^/]+)/jobs/(\d+)", u.path)
    if u.netloc in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and m:
        return f"https://boards-api.greenhouse.io/v1/boards/{m[1]}/jobs/{m[2]}"
    m = re.match(r"/([^/]+)/([0-9a-f-]{36})", u.path)
    if u.netloc == "jobs.lever.co" and m:
        return f"https://api.lever.co/v0/postings/{m[1]}/{m[2]}"
    return None


def _text_from_ats_json(data: dict) -> str:
    import html

    import trafilatura
    if "content" in data:  # Greenhouse (HTML-escaped HTML)
        body = trafilatura.extract(f"<html><body>{html.unescape(data['content'])}</body></html>") or ""
        loc = (data.get("location") or {}).get("name", "")
        return f"{data.get('title', '')}\n{loc}\n\n{body}"
    parts = [data.get("text", ""), data.get("categories", {}).get("location", ""),  # Lever
             data.get("descriptionPlain", "")]
    for section in data.get("lists", []):
        parts.append(section.get("text", ""))
        parts.append(trafilatura.extract(f"<html><body><ul>{section.get('content', '')}</ul></body></html>") or "")
    parts.append(data.get("additionalPlain", ""))
    return "\n".join(p for p in parts if p)


def from_url(url: str, cfg: Fetch) -> Posting:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise FetchError(f"Not an http(s) URL: {url}")
    if _is_blocked(parsed.netloc, cfg.blocked_domains):
        raise FetchError(f"{parsed.netloc} doesn't permit scraping (fetch.blocked_domains); please paste the text.")

    headers = {"User-Agent": cfg.user_agent}
    try:
        with httpx.Client(timeout=cfg.timeout_seconds, follow_redirects=True, headers=headers) as client:
            api = _ats_api_url(url)
            if api:
                r = client.get(api)
                if r.status_code == 200:
                    return _finish(_text_from_ats_json(r.json()), url)
            if cfg.respect_robots_txt and not _robots_allows(client, url, cfg.user_agent):
                raise FetchError(f"robots.txt on {parsed.netloc} disallows fetching this page; please paste the text.")
            r = client.get(url)
    except httpx.HTTPError as e:
        raise FetchError(f"Couldn't fetch {url}: {e}") from e
    if r.status_code != 200:
        raise FetchError(f"Fetching {url} returned HTTP {r.status_code}")

    import trafilatura
    text = trafilatura.extract(r.text, include_tables=True) or ""
    return _finish(text, url)


def _finish(text: str, url: str) -> Posting:
    if len(text.strip()) < 300:
        raise FetchError("Page had too little readable text (it may be rendered by JavaScript or need a login).")
    p = from_text(text, source=url)
    p.url = url
    return p


def _robots_allows(client: httpx.Client, url: str, agent: str) -> bool:
    u = urlparse(url)
    try:
        r = client.get(f"{u.scheme}://{u.netloc}/robots.txt")
    except httpx.HTTPError:
        return True
    if r.status_code != 200:
        return True
    rp = robotparser.RobotFileParser()
    rp.parse(r.text.splitlines())
    return rp.can_fetch(agent, url)


def read_pasted(prompt: str = "Paste the job description, then press Ctrl-D (Ctrl-Z Enter on Windows):") -> str:
    if sys.stdin.isatty():
        print(prompt, file=sys.stderr)
    return sys.stdin.read()
