"""Turn user input (pasted text, files) into Posting objects."""
from __future__ import annotations

import sys
from pathlib import Path

from .models import Posting

POSTING_SUFFIXES = {".txt", ".md", ".html", ".htm"}


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


def read_pasted() -> str:
    if sys.stdin.isatty():
        print("Paste the job description, then press Ctrl-D (Ctrl-Z Enter on Windows):", file=sys.stderr)
    return sys.stdin.read()
