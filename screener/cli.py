"""Command-line interface: `python -m screener --help`."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer

from . import ingest, report
from .config import DEFAULT_CONFIG, load_config
from .llm import LLM, DryRunLLM, LLMError
from .models import Posting
from .pipeline import Outcome, Screener
from .resume import load_resume
from .store import ResultStore, save_tailoring

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Screen job postings against your background and preferences.")

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "samples" / "fixtures"


class Ctx:
    config: Path = DEFAULT_CONFIG
    resume: Optional[Path] = None
    dry_run: bool = False
    lookup: bool = True
    tailor: bool = True


state = Ctx()

FORCE = typer.Option(False, "--force", "-f", help="Re-screen even if already in results.csv")


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env support: KEY=VALUE lines; never overrides variables already set."""
    import os
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@app.callback()
def main(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c", help="Path to config.yaml"),
    resume: Optional[Path] = typer.Option(None, "--resume", "-r", help="Override profile.resume_path"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Use canned responses for the bundled samples (no API calls)"),
    lookup: bool = typer.Option(True, "--lookup/--no-lookup", help="Look up funding stage / AI focus via web search"),
    tailor: bool = typer.Option(True, "--tailor/--no-tailor", help="Generate resume bullets + cover letter points for Apply results"),
):
    load_dotenv()
    state.config, state.resume, state.dry_run = config, resume, dry_run
    state.lookup, state.tailor = lookup, tailor


def get_config():
    try:
        cfg = load_config(state.config)
    except Exception as e:  # missing file, bad YAML, or failed validation
        _fail(f"Couldn't load config {state.config}: {e}")
    if state.dry_run:
        # Keep canned sample data out of your real results and company cache.
        d = cfg.resolve(Path("data/dry_run"))
        cfg.storage.results_csv = d / "results.csv"
        cfg.storage.company_cache = d / "companies.json"
        cfg.storage.tailoring_dir = d / "tailoring"
    return cfg


def build_screener(cfg) -> Screener:
    resume_text = load_resume(state.resume or cfg.resolve(cfg.profile.resume_path))
    llm = DryRunLLM(FIXTURES_DIR) if state.dry_run else LLM(cfg.llm)
    return Screener(cfg, llm, resume_text, lookup=state.lookup, tailor=state.tailor)


def _fail(msg: str) -> None:
    report.console.print(f"[bold red]Error:[/] {msg}")
    raise typer.Exit(1)


def _print_duplicate(o: Outcome) -> None:
    d = o.duplicate_of
    score = f", {d['score']}" if d.get("score") else ""
    report.console.print(f"[dim]↺ Already screened {d['screened_at'][:10]}: {d['title']} — {d['company']} "
                         f"({d['recommendation']}{score}). Use --force to re-screen.[/]")


def _run(postings: list[Posting], force: bool, detail: bool) -> None:
    cfg = get_config()
    try:
        screener = build_screener(cfg)
    except (LLMError, OSError, ValueError) as e:
        _fail(str(e))
    store = ResultStore(cfg.resolve(cfg.storage.results_csv))
    outcomes, errors = [], []
    with report.console.status("") as status:
        for i, p in enumerate(postings, 1):
            status.update(f"Screening {i}/{len(postings)}: {p.source}")
            try:
                outcomes.append(screener.process(p, store, force=force))
            except (LLMError, ValueError) as e:
                errors.append((p.source, str(e)))

    results = [o.result for o in outcomes if o.result]
    if detail:
        for r in results:
            report.print_detail(r)
    elif results:
        report.print_table(results)
    for o in outcomes:
        if o.duplicate_of:
            _print_duplicate(o)
    for source, err in errors:
        report.console.print(f"[red]✘ {source}:[/] {err}")
    if results:
        report.console.print(f"[dim]Saved {len(results)} result(s) to {store.path}[/]")
    for r in results:
        if path := save_tailoring(r, cfg.resolve(cfg.storage.tailoring_dir)):
            report.console.print(f"[green]✎ Tailoring for {r.extraction.company}: {path}[/]")
    if errors and not results:
        raise typer.Exit(1)


@app.command()
def text(file: Optional[Path] = typer.Argument(None, help="File with the posting text; omit to paste via stdin"),
         force: bool = FORCE):
    """Screen a single posting from pasted text or a saved file."""
    try:
        posting = ingest.from_file(file) if file else ingest.from_text(ingest.read_pasted())
    except (OSError, ValueError) as e:
        _fail(str(e))
    _run([posting], force, detail=True)


@app.command()
def url(link: str = typer.Argument(..., help="URL of a single job posting"), force: bool = FORCE):
    """Fetch a posting URL and screen it. Falls back to asking you to paste the text."""
    cfg = get_config()
    if not force and (dup := ResultStore(cfg.resolve(cfg.storage.results_csv)).find(url=link)):
        _print_duplicate(Outcome(Posting(text="", url=link), duplicate_of=dup))
        return
    try:
        posting = ingest.from_url(link, cfg.fetch)
    except ingest.FetchError as e:
        report.console.print(f"[yellow]{e}[/]")
        if not sys.stdin.isatty():
            _fail("Can't prompt for pasted text (stdin is not a terminal). Save the text and use `text FILE`.")
        try:
            posting = ingest.from_text(ingest.read_pasted("Paste the posting text instead, then Ctrl-D:"),
                                       source=link)
        except ValueError as e2:
            _fail(str(e2))
        posting.url = link
    _run([posting], force, detail=True)


@app.command()
def batch(path: Path = typer.Argument(..., exists=True, help="A CSV file or a folder of saved postings"),
          force: bool = FORCE,
          detail: bool = typer.Option(False, "--detail", help="Show full detail for each posting")):
    """Screen many postings from a CSV (text/description column) or a folder of .txt/.md/.html files."""
    try:
        postings = ingest.from_path(path)
    except (OSError, ValueError) as e:
        _fail(str(e))
    _run(postings, force, detail)


@app.command()
def results(
    sort: str = typer.Option("score", "--sort", "-s", help="score | date | company | salary"),
    rec: Optional[str] = typer.Option(None, "--rec", help="Only show Apply, Maybe or Skip"),
    limit: int = typer.Option(50, "--limit", "-n"),
):
    """Show everything you've screened so far (from results.csv)."""
    cfg = get_config()
    rows = ResultStore(cfg.resolve(cfg.storage.results_csv)).rows
    if rec:
        rows = [r for r in rows if r["recommendation"].lower() == rec.lower()]
    if not rows:
        report.console.print("No results yet. Screen something first, e.g. `python -m screener batch samples/postings`.")
        return
    report.print_rows(rows, sort, limit)


@app.command()
def export(out: Path = typer.Option(Path("data/results.html"), "--out", "-o", help="Where to write the HTML file")):
    """Write results.csv to a self-contained HTML page with a sortable, filterable table."""
    from .html_report import export_html
    cfg = get_config()
    rows = ResultStore(cfg.resolve(cfg.storage.results_csv)).rows
    if not rows:
        _fail("No results to export yet.")
    if state.dry_run and out == Path("data/results.html"):
        out = Path("data/dry_run/results.html")
    path = export_html(rows, out)
    report.console.print(f"Wrote {len(rows)} results to {path.resolve()} — open it in your browser.")
