"""Offline tests: filters, scoring math, dedupe, ingest parsing, and a dry-run end-to-end run."""
from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from screener.cli import app
from screener.company import company_from_posting
from screener.config import load_config
from screener.filters import check_funding, check_location, check_non_technical, check_salary
from screener.ingest import _ats_api_url, _text_from_ats_json, from_csv, from_file
from screener.models import CompanyInfo, Extraction, FitAssessment, LocationOption
from screener.scoring import recommend, total_score
from screener.store import ResultStore, url_key

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def cfg():
    return load_config(ROOT / "config.yaml")


def make_ex(**kw) -> Extraction:
    base = dict(title="Strategy & Operations Lead", company="Acme AI",
                locations=[LocationOption(location="New York, NY", arrangement="hybrid")],
                salary_min=150000, salary_max=180000, seniority="Senior", key_requirements=[],
                red_flags=[], requires_coding=False, cs_degree_required=False, technical_evidence=[],
                ai_core="yes", funding_stage="series_b")
    base.update(kw)
    return Extraction(**base)


def loc(*pairs):
    return [LocationOption(location=l, arrangement=a) for l, a in pairs]


# ---------- location ----------

@pytest.mark.parametrize("locations,status", [
    (loc(("New York, NY", "hybrid")), "pass"),
    (loc(("Brooklyn, NY", "onsite")), "pass"),
    (loc(("San Francisco, CA", "hybrid"), ("New York, NY", "hybrid")), "pass"),   # multi-city incl. NYC
    (loc(("Remote (US)", "remote")), "fail"),                                      # fully remote
    (loc(("New York, NY", "remote")), "fail"),                                     # remote, NYC-based
    (loc(("Remote (US)", "remote"), ("New York, NY", "hybrid")), "pass"),         # remote OR NYC hybrid
    (loc(("Chicago, IL", "onsite")), "fail"),                                      # other city
    (loc(("Jersey City, NJ", "hybrid")), "fail"),                                  # metro doesn't count
    (loc(("New York, NY", "unknown")), "unverified"),
    ([], "unverified"),
])
def test_location(cfg, locations, status):
    assert check_location(cfg, make_ex(locations=locations)).status == status


def test_location_fail_says_why(cfg):
    assert "remote" in check_location(cfg, make_ex(locations=loc(("Remote (US)", "remote")))).detail.lower()
    assert "outside new york" in check_location(cfg, make_ex(locations=loc(("Austin, TX", "onsite")))).detail.lower()


# ---------- salary ----------

@pytest.mark.parametrize("lo,hi,status", [
    (150000, 180000, "pass"),
    (120000, 160000, "pass"),     # floor inside range
    (110000, 135000, "fail"),
    (None, None, "unverified"),   # salary unknown -> flag, not reject
    (145000, None, "pass"),
    (None, 130000, "fail"),
])
def test_salary(cfg, lo, hi, status):
    assert check_salary(cfg, make_ex(salary_min=lo, salary_max=hi)).status == status


# ---------- company rules ----------

@pytest.mark.parametrize("stage,status", [
    ("seed", "fail"), ("pre_seed", "fail"), ("series_a", "pass"), ("public", "pass"),
    ("late_stage_private", "pass"), ("unknown", "unverified"),
])
def test_funding(cfg, stage, status):
    assert check_funding(cfg, CompanyInfo(funding_stage=stage, funding_source="posting")).status == status


def test_company_from_posting_records_source():
    info = company_from_posting(make_ex(ai_core="unknown", funding_stage="series_c", funding_evidence="Series C"))
    assert info.funding_source == "posting" and info.ai_source == "unverified"


# ---------- non-technical ----------

def test_non_technical(cfg):
    assert check_non_technical(cfg, make_ex()).status == "pass"
    fail = check_non_technical(cfg, make_ex(requires_coding=True, technical_evidence=["Write production Python"]))
    assert fail.status == "fail" and "Write production Python" in fail.detail
    assert check_non_technical(cfg, make_ex(cs_degree_required=True)).status == "fail"


# ---------- scoring ----------

def test_score_clamps_and_sector_bonus(cfg):
    fit = FitAssessment(role_match=99, experience_match=35, seniority_fit=-3,
                        matching_sectors=["govtech", "industrial", "regtech", "not_a_sector"],
                        explanation="", requirements_met=[], gaps=[])
    score, bonus = total_score(cfg, fit)
    assert (fit.role_match, fit.seniority_fit) == (30, 0)
    assert bonus == cfg.nice_to_have.max_bonus
    assert "not_a_sector" not in fit.matching_sectors
    assert score == 30 + 35 + 0 + 15


def test_recommend(cfg):
    assert recommend(cfg, 90, True) == "Apply"
    assert recommend(cfg, 60, True) == "Maybe"
    assert recommend(cfg, 40, True) == "Skip"
    assert recommend(cfg, 95, False) == "Skip"


# ---------- dedupe ----------

def test_url_key_normalizes():
    assert url_key("https://www.Example.com/jobs/1/?utm_source=x#top") == url_key("http://example.com/jobs/1")


def test_store_dedupe(tmp_path):
    store = ResultStore(tmp_path / "r.csv")
    store.rows.append({"url_key": url_key("https://a.com/j/1"), "text_hash": "abc", "company_title_key": "acme ai|bizops"})
    assert store.find(url="https://a.com/j/1/")
    assert store.find(company="ACME AI", title="BizOps")
    assert store.find(url="https://a.com/j/2") is None


# ---------- ingest ----------

def test_from_file_reads_url_header():
    p = from_file(ROOT / "samples/postings/01_halden_deployment_strategist.txt")
    assert p.url.endswith("deployment-strategist") and not p.text.startswith("URL:")


def test_from_csv(tmp_path):
    f = tmp_path / "p.csv"
    with f.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Title", "Company", "Description", "URL"])
        w.writerow(["BizOps", "Acme", "x" * 150, "https://a.com/1"])
    [p] = from_csv(f)
    assert (p.title_hint, p.company_hint, p.url) == ("BizOps", "Acme", "https://a.com/1")


def test_ats_urls():
    assert _ats_api_url("https://boards.greenhouse.io/acme/jobs/123") == \
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs/123"
    assert _ats_api_url("https://jobs.lever.co/acme/0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b").startswith(
        "https://api.lever.co/v0/postings/acme/")
    assert _ats_api_url("https://acme.com/careers/123") is None


def test_greenhouse_json_parsing():
    data = {"title": "BizOps Lead", "location": {"name": "New York, NY"},
            "content": "&lt;p&gt;We build AI for factories.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;5+ years in ops&lt;/li&gt;&lt;/ul&gt;"}
    text = _text_from_ats_json(data)
    assert "BizOps Lead" in text and "New York" in text and "AI for factories" in text


# ---------- end to end (dry run, no API) ----------

def test_dry_run_batch_end_to_end(tmp_path):
    shutil.copy(ROOT / "config.yaml", tmp_path / "config.yaml")
    runner = CliRunner()
    args = ["--config", str(tmp_path / "config.yaml"), "--dry-run",
            "--resume", str(ROOT / "samples/sample_resume.md")]
    r = runner.invoke(app, [*args, "batch", str(ROOT / "samples/postings")])
    assert r.exit_code == 0, r.output
    rows = {row["company"]: row for row in csv.DictReader(open(tmp_path / "data/dry_run/results.csv"))}
    assert {c: rows[c]["recommendation"] for c in rows} == {
        "Halden Systems": "Apply", "Ledgerline": "Apply", "Corvid Freight": "Maybe",
        "Arbiter AI": "Skip", "Vantor": "Skip", "Quillo": "Skip"}
    assert rows["Arbiter AI"]["failed_rules"].startswith("location")
    assert rows["Vantor"]["failed_rules"].startswith("non_technical")
    assert "Salary unknown" in rows["Corvid Freight"]["flags"]
    assert rows["Corvid Freight"]["funding_source"].startswith("https://")   # filled by lookup
    assert len(list((tmp_path / "data/dry_run/tailoring").glob("*.md"))) == 2

    again = runner.invoke(app, [*args, "batch", str(ROOT / "samples/postings.csv")])
    assert again.output.count("Already screened") == 6
