"""Email a screening digest with CSV attachments over SMTP (Gmail by default)."""
from __future__ import annotations

import csv
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from .store import COLUMNS

# Columns worth reading in an email/spreadsheet; the dedupe keys are internal.
DIGEST_COLUMNS = [c for c in COLUMNS if c not in {"url_key", "text_hash", "company_title_key", "source"}]
REC_ORDER = {"Apply": 0, "Maybe": 1, "Skip": 2}


def sort_rows(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (REC_ORDER.get(r.get("recommendation", ""), 3), -float(r.get("score") or 0)))


def write_csv(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=DIGEST_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sort_rows(rows))
    return path


def digest_body(new_rows: list[dict], total: int, errors: list[str]) -> str:
    counts = {rec: sum(r["recommendation"] == rec for r in new_rows) for rec in REC_ORDER}
    lines = [f"{len(new_rows)} new posting(s) screened: "
             f"{counts['Apply']} Apply, {counts['Maybe']} Maybe, {counts['Skip']} Skip.", ""]
    for r in sort_rows(new_rows):
        if r["recommendation"] == "Skip":
            continue
        lines.append(f"[{r['recommendation']} {r['score']}] {r['title']} at {r['company']} ({r['location']})")
        if r.get("explanation"):
            lines.append(f"    {r['explanation']}")
        if r.get("url"):
            lines.append(f"    {r['url']}")
        lines.append("")
    lines.append(f"Attached: new postings from this run, and all {total} results so far.")
    if errors:
        lines += ["", "Couldn't read these job boards (check the company's ats/slug in config.yaml):"]
        lines += [f"  - {e}" for e in errors]
    return "\n".join(lines)


def send_email(to: str, subject: str, body: str, attachments: list[Path]) -> None:
    user, password = os.environ.get("SMTP_USERNAME"), os.environ.get("SMTP_PASSWORD")
    if not user or not password:
        raise RuntimeError("Set SMTP_USERNAME and SMTP_PASSWORD (for Gmail, an app password).")
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))

    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = user, to, subject
    msg.set_content(body)
    for path in attachments:
        msg.add_attachment(path.read_bytes(), maintype="text", subtype="csv", filename=path.name)

    with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
