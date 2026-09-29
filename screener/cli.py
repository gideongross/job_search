"""Command-line interface: `python -m screener --help`."""
from __future__ import annotations

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


state = Ctx()


@app.callback()
def main(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c", help="Path to config.yaml"),
    resume: Optional[Path] = typer.Option(None, "--resume", "-r", help="Override profile.resume_path"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Use canned responses for the bundled samples (no API calls)"),
):
    state.config, state.resume, state.dry_run = config, resume, dry_run


def build_screener() -> Screener:
    cfg = load_config(state.config)
    resume_text = load_resume(state.resume or cfg.resolve(cfg.profile.resume_path))
    llm = DryRunLLM(FIXTURES_DIR) if state.dry_run else LLM(cfg.llm)
    return Screener(cfg, llm, resume_text)


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
