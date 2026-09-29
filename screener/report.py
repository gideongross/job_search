"""Terminal output: ranked results table and per-posting detail."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .models import ScreenResult

console = Console()

REC_STYLE = {"Apply": "bold green", "Maybe": "bold yellow", "Skip": "red"}
STATUS_ICON = {"pass": "[green]✔[/]", "fail": "[red]✘[/]", "unverified": "[yellow]?[/]"}
REC_ORDER = {"Apply": 0, "Maybe": 1, "Skip": 2}


def salary_str(r: ScreenResult) -> str:
    ex = r.extraction
    if ex.salary_min is None and ex.salary_max is None:
        return "unknown"
    lo = f"{ex.salary_min // 1000}k" if ex.salary_min else "?"
    hi = f"{ex.salary_max // 1000}k" if ex.salary_max else "?"
    return f"${lo}–{hi}"


def location_str(r: ScreenResult) -> str:
    return "; ".join(f"{o.location} ({o.arrangement})" for o in r.extraction.locations) or "unknown"


def sort_results(results: list[ScreenResult], by: str = "score") -> list[ScreenResult]:
    if by == "company":
        return sorted(results, key=lambda r: r.extraction.company.lower())
    if by == "salary":
        return sorted(results, key=lambda r: -(r.extraction.salary_max or r.extraction.salary_min or 0))
    return sorted(results, key=lambda r: (REC_ORDER[r.recommendation], -(r.score if r.score is not None else -1)))


def print_table(results: list[ScreenResult], sort_by: str = "score", title: str = "Screening results") -> None:
    t = Table(title=title, show_lines=True, expand=True)
    for col, kw in [("#", {"justify": "right"}), ("Rec", {}), ("Score", {"justify": "right"}),
                    ("Role", {"ratio": 3}), ("Location", {"ratio": 2}), ("Salary", {}),
                    ("Why / failed rule", {"ratio": 4})]:
        t.add_column(col, **kw)
    for i, r in enumerate(sort_results(results, sort_by), 1):
        if r.failed_rules:
            why = "[red]" + "\n".join(f"{f.rule}: {f.detail}" for f in r.failed_rules) + "[/]"
        else:
            why = r.fit.explanation if r.fit else ""
        if r.flags:
            why += "\n[yellow]⚑ " + "; ".join(r.flags) + "[/]"
        t.add_row(str(i), f"[{REC_STYLE[r.recommendation]}]{r.recommendation}[/]",
                  "—" if r.score is None else str(r.score),
                  f"[bold]{r.extraction.title}[/]\n{r.extraction.company}",
                  location_str(r), salary_str(r), why)
    console.print(t)


def print_detail(r: ScreenResult) -> None:
    ex = r.extraction
    lines = [
        f"[bold]{ex.title}[/] — {ex.company}",
        f"Location: {location_str(r)}   Salary: {salary_str(r)}   Seniority: {ex.seniority}",
        f"Funding: {r.company.funding_stage} ({r.company.funding_source})   "
        f"AI core: {r.company.ai_core} ({r.company.ai_source})",
        "",
        "[bold]Hard filters[/]",
        *[f"  {STATUS_ICON[f.status]} {f.rule}: {f.detail}" for f in r.filters],
    ]
    if r.fit:
        f = r.fit
        lines += [
            "",
            f"[bold]Fit score {r.score}/100[/]  (role {f.role_match} + experience {f.experience_match} + "
            f"seniority {f.seniority_fit} + sectors {r.sector_bonus})",
            f.explanation,
            "[green]Meets:[/] " + "; ".join(f.requirements_met),
            "[yellow]Gaps:[/] " + "; ".join(f.gaps),
            "Sectors: " + (", ".join(f.matching_sectors) or "none"),
        ]
    lines += ["", "[bold]Key requirements:[/] " + "; ".join(ex.key_requirements)]
    if ex.red_flags:
        lines.append("[bold red]Red flags:[/] " + "; ".join(ex.red_flags))
    if r.tailoring:
        lines += ["", "[bold]Tailored resume bullets[/]", *[f"  • {b}" for b in r.tailoring.resume_bullets],
                  "[bold]Cover letter talking points[/]", *[f"  • {p}" for p in r.tailoring.cover_letter_points]]
    console.print(Panel("\n".join(lines), title=f"[{REC_STYLE[r.recommendation]}]{r.recommendation}[/]",
                        expand=True))


def _row_sort_key(sort_by: str):
    if sort_by == "date":
        return lambda r: r["screened_at"], True
    if sort_by == "company":
        return lambda r: r["company"].lower(), False
    if sort_by == "salary":
        return lambda r: int(r["salary_max"] or r["salary_min"] or 0), True
    return lambda r: (-REC_ORDER.get(r["recommendation"], 3), int(r["score"] or -1)), True


def print_rows(rows: list[dict], sort_by: str = "score", limit: int = 50) -> None:
    """Table of saved results.csv rows."""
    key, reverse = _row_sort_key(sort_by)
    rows = sorted(rows, key=key, reverse=reverse)[:limit]
    t = Table(title=f"Screened postings (sorted by {sort_by})", show_lines=False, expand=True)
    for col, kw in [("Date", {}), ("Rec", {}), ("Score", {"justify": "right"}), ("Company", {"ratio": 2}),
                    ("Title", {"ratio": 3}), ("Salary", {}), ("Sectors", {}), ("Status", {}),
                    ("Failed rule / flags", {"ratio": 4})]:
        t.add_column(col, **kw)
    for r in rows:
        lo, hi = r["salary_min"], r["salary_max"]
        salary = f"${int(lo or 0) // 1000 or '?'}k–{int(hi or 0) // 1000 or '?'}k" if (lo or hi) else "unknown"
        note = f"[red]{r['failed_rules']}[/]" if r["failed_rules"] else f"[yellow]{r['flags']}[/]"
        t.add_row(r["screened_at"][:10], f"[{REC_STYLE.get(r['recommendation'], '')}]{r['recommendation']}[/]",
                  r["score"] or "—", r["company"], r["title"], salary, r["sectors"], r["status"], note)
    console.print(t)
