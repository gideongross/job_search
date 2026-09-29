# Job Search Screener

Screens job postings against your resume and preferences, tells you which ones are worth applying to
and why, and drafts tailored resume bullets and cover-letter talking points for the best matches.

```
posting (text / URL / CSV / folder)
   │
   ├─ 1. Extract ─────── Claude pulls out title, company, locations + arrangement, salary, seniority,
   │                     key requirements, red flags, coding/CS-degree requirements (with quotes)
   ├─ 2. Company facts ─ funding stage + "is AI core to the product": from the posting if stated,
   │                     else Claude web search (source URL recorded, cached), else "unverified"
   ├─ 3. Hard filters ── plain Python rules from config.yaml; each shows pass / fail / unverified
   ├─ 4. Fit score ───── Claude scores role, experience and seniority fit; nice-to-have sectors add a bonus
   ├─ 5. Tailoring ───── Apply results only: 3-5 resume bullets + cover-letter talking points
   └─ 6. Save ────────── data/results.csv (deduped), data/tailoring/*.md, optional HTML table
```

## Setup

Requires Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# API key: export it, or put it in a .env file (gitignored)
export ANTHROPIC_API_KEY=sk-ant-...

# Your resume: PDF, DOCX, Markdown or text. ./private/ is gitignored.
mkdir -p private && cp ~/Documents/resume.pdf private/resume.pdf
```

Then open `config.yaml` and check `profile.resume_path` and the rest of your preferences.

## Try it without an API key

The six bundled sample postings have canned Claude responses, so you can run the whole pipeline
offline. `--dry-run` writes to `data/dry_run/`, so it never mixes with your real results.

```bash
python -m screener --dry-run -r samples/sample_resume.md batch samples/postings
python -m screener --dry-run results
python -m screener --dry-run export          # -> data/dry_run/results.html
```

| Sample | Expected | Why |
|---|---|---|
| 01 Halden Systems: Deployment Strategist | **Apply** (92) | NYC hybrid, Series C defense-AI, $170–210k, industrial + govtech |
| 02 Ledgerline: Strategy & Operations Lead | **Apply** (81) | Public regtech AI company, NYC hybrid, $165–195k |
| 03 Corvid Freight: Business Operations Manager | **Maybe** (62) | Salary not listed, AI focus unverified, more tactical than target roles |
| 04 Arbiter AI: Strategic Initiatives Manager | **Skip** | `location`: fully remote |
| 05 Vantor: Forward Deployed Engineer | **Skip** | `non_technical`: production Python/TypeScript + CS degree required |
| 06 Quillo: Founding BizOps Lead | **Skip** | `salary` below floor + `funding_stage`: seed |

All sample companies and the sample resume are fictional.

## Usage

Options that apply to every command (`--config`, `--resume`, `--dry-run`, `--no-lookup`,
`--no-tailor`) go **before** the command name.

```bash
# One posting: paste text (end with Ctrl-D), or pass a saved file
python -m screener text
python -m screener text ~/Downloads/posting.txt

# One posting by URL (falls back to asking you to paste if it can't be fetched)
python -m screener url https://boards.greenhouse.io/somecompany/jobs/123456

# Many postings: a folder of .txt/.md/.html files, or a CSV
python -m screener batch ~/job-postings/
python -m screener batch postings.csv --detail

# Your history, sortable: score | date | company | salary
python -m screener results --sort salary --rec Apply

# Sortable/filterable HTML table of everything you've screened
python -m screener export && open data/results.html
```

**CSV format:** one of the columns `text`, `description`, `job_description` or `posting` is required.
The `url`, `company`, `title` and `id` columns are optional.

**Saved files:** a first line of `URL: https://...` in a saved `.txt` posting is used for dedupe.

**Re-screening:** anything already in `results.csv` is skipped. The match is on URL or identical text
before any API call, and on company + title after extraction. Use `--force` to re-screen. It
overwrites the row but keeps your `status` and `notes` columns.

**Tracking applications:** open `data/results.csv` in a spreadsheet and fill in `status`
(e.g. applied / interviewing / rejected) and `notes`.

## Run it on GitHub

`.github/workflows/screen.yml` runs the screener in GitHub Actions, so you don't need Python locally.

1. **Make the repo private** (Settings → General → Danger Zone). Run logs and results contain your
   scores and resume-based tailoring.
2. Add repository secrets (Settings → Secrets and variables → Actions → New repository secret):
   - `ANTHROPIC_API_KEY`: your Claude API key
   - `RESUME_TEXT`: your resume pasted as plain text or Markdown. Alternatively, `RESUME_B64` is a
     base64-encoded PDF/DOCX (`base64 -i resume.pdf`), but secrets are capped at 48 KB.
3. Actions tab → **Screen job postings** → **Run workflow**, then paste one or more posting URLs
   separated by spaces or commas.

The run page shows a summary table of everything screened so far. The **screening-results**
artifact has `results.html`, `results.csv` and the tailoring notes. Results are carried between
runs in the Actions cache, so postings you've already screened are skipped unless you tick
"Re-screen". The cache is evicted after 7 days without a run, which resets your history on GitHub.
LinkedIn, Indeed and similar links can't be fetched; use a Greenhouse, Lever or company careers link.

## How screening works

### Hard filters (reject only if clearly failed)

| Rule | Fails when | Unknown → |
|---|---|---|
| `location` | No hybrid/in-office option in NYC (fully remote, remote-only NYC, or another city). Multi-city postings that include NYC pass. | flag if NYC is listed but the arrangement isn't stated |
| `salary` | The top of the range is below `filters.salary.floor` | flag "Salary unknown" |
| `ai_core` | The posting or lookup says AI is **not** core to the product | flag "AI focus unverified" |
| `funding_stage` | The stage is in `rejected_stages` (pre-seed, seed) | flag "Funding stage unverified" |
| `non_technical` | Hands-on coding or a CS degree is a hard requirement (with the quote shown). SQL and light analysis are fine. | n/a |

Claude does the extraction, and the rules are plain code in `screener/filters.py`. Every rejection
names its rule and quotes the evidence. Company lookups only run when a posting has already passed
the other rules, so you don't pay for web searches on postings that would be rejected anyway.

### Fit score (0–100)

| Component | Max | Source |
|---|---|---|
| Role match | 30 | Claude: does the actual work match your target roles? |
| Experience match | 40 | Claude: how many stated requirements your resume clearly shows |
| Seniority fit | 15 | Claude: level/years vs. your experience |
| Sector bonus | 15 | +10 per matching nice-to-have sector (industrial, govtech, regtech), capped |

**Apply** at 75 or above, **Maybe** at 55–74, otherwise **Skip**. A posting that fails any hard
filter is always Skip. The weights and thresholds are in `config.yaml` under `scoring`.

## Configuration

Everything is in `config.yaml`: target roles and title variants, location and arrangement, salary
floor, funding stages to reject, sectors and their bonus, score weights and thresholds, the Claude
model and effort per task, fetch rules, and storage paths.

- **Model:** `claude-sonnet-5-5` by default (`llm.model`). Extraction and lookup run at `low` effort;
  scoring and tailoring run at `medium`.
- **Refusal fallback:** `llm.refusal_fallback: true` turns on the API's server-side fallback. If a
  safety classifier declines a request, it's retried automatically on a fallback model. Set it to
  `false` to turn this off.
- **Blocked sites:** `fetch.blocked_domains` lists sites whose terms prohibit scraping (LinkedIn,
  Indeed, Glassdoor, …). The tool never fetches from them and asks you to paste the text instead.
  It also respects `robots.txt`, and for Greenhouse and Lever links it uses their public job APIs.

## Cost

Per new posting that passes the filters, expect about 3 Claude calls (extract, score, tailor if
Apply), plus one web-search lookup per new company. Rejected postings stop after the extraction
call. The candidate profile is sent as a cached system prompt, so batches reuse it.

## Development

```bash
python -m pytest -q     # offline: filters, scoring, dedupe, ingest parsing, dry-run end to end
```

```
screener/
  cli.py          commands: text, url, batch, results, export
  config.py       loads/validates config.yaml
  ingest.py       text / file / folder / CSV / URL → Posting (blocklist, robots.txt, ATS APIs)
  llm.py          Claude API structured-output wrapper; DryRunLLM replays samples/fixtures/
  prompts.py      all prompts, built from config
  pipeline.py     extract → company → filters → score → tailor; dedupe-aware process()
  company.py      funding / AI-focus lookup via web search, cached in data/companies.json
  filters.py      hard filters (plain Python)
  scoring.py      component clamping, sector bonus, recommendation
  store.py        results.csv upsert + dedupe; tailoring Markdown
  report.py       terminal tables and detail view
  html_report.py  sortable HTML export
samples/          fictional resume, 6 postings (.txt + postings.csv), dry-run fixtures
```
