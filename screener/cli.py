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
from .pipeline import Screener
from .resume import load_resume

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Screen job postings against your background and preferences.")

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "samples" / "fixtures"


class Ctx:
    config: Path = DEFAULT_CONFIG
    resume: Optional[Path] = None
    dry_run: bool = False
    lookup: bool = True


state = Ctx()


@app.callback()
def main(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c", help="Path to config.yaml"),
    resume: Optional[Path] = typer.Option(None, "--resume", "-r", help="Override profile.resume_path"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Use canned responses for the bundled samples (no API calls)"),
    lookup: bool = typer.Option(True, "--lookup/--no-lookup", help="Look up funding stage / AI focus via web search"),
):
    state.config, state.resume, state.dry_run, state.lookup = config, resume, dry_run, lookup


def get_config():
    cfg = load_config(state.config)
    if state.dry_run:
        # Keep canned sample data out of your real results and company cache.
        d = cfg.resolve(Path("data/dry_run"))
        cfg.storage.results_csv = d / "results.csv"
        cfg.storage.company_cache = d / "companies.json"
        cfg.storage.tailoring_dir = d / "tailoring"
    return cfg


def build_screener(cfg=None) -> Screener:
    cfg = cfg or get_config()
    resume_text = load_resume(state.resume or cfg.resolve(cfg.profile.resume_path))
    llm = DryRunLLM(FIXTURES_DIR) if state.dry_run else LLM(cfg.llm)
    return Screener(cfg, llm, resume_text, lookup=state.lookup)


def _fail(msg: str) -> None:
    report.console.print(f"[bold red]Error:[/] {msg}")
    raise typer.Exit(1)


def _screen_one(posting: Posting) -> None:
    try:
        screener = build_screener()
        result = screener.screen(posting)
    except (LLMError, FileNotFoundError, ValueError) as e:
        _fail(str(e))
    report.print_detail(result)


@app.command()
def text(file: Optional[Path] = typer.Argument(None, help="File with the posting text; omit to paste via stdin")):
    """Screen a single posting from pasted text or a saved file."""
    try:
        posting = ingest.from_file(file) if file else ingest.from_text(ingest.read_pasted())
    except (OSError, ValueError) as e:
        _fail(str(e))
    _screen_one(posting)


@app.command()
def url(link: str = typer.Argument(..., help="URL of a single job posting")):
    """Fetch a posting URL and screen it. Falls back to asking you to paste the text."""
    cfg = get_config()
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
    _screen_one(posting)


@app.command()
def batch(path: Path = typer.Argument(..., exists=True, help="A CSV file or a folder of saved postings")):
    """Screen many postings from a CSV (text/description column) or a folder of .txt/.md/.html files."""
    try:
        postings = ingest.from_path(path)
        screener = build_screener()
    except (LLMError, OSError, ValueError) as e:
        _fail(str(e))
    results, errors = [], []
    with report.console.status("") as status:
        for i, p in enumerate(postings, 1):
            status.update(f"Screening {i}/{len(postings)}: {p.source}")
            try:
                results.append(screener.screen(p))
            except (LLMError, ValueError) as e:
                errors.append((p.source, str(e)))
    if results:
        report.print_table(results)
    for source, err in errors:
        report.console.print(f"[red]✘ {source}:[/] {err}")
