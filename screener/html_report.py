"""Export results.csv to a self-contained HTML page with a sortable, filterable table."""
from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Screener Results</title>
<style>
:root { --bg:#fbfbfa; --fg:#1d1d1b; --muted:#6b6b66; --line:#e4e3de; --apply:#1f7a3f; --maybe:#9a6a00; --skip:#a33; --chip:#f0efea; }
@media (prefers-color-scheme: dark) { :root { --bg:#161615; --fg:#ecebe6; --muted:#a09f99; --line:#2e2e2b; --apply:#5cc27f; --maybe:#e0b44c; --skip:#ef7b7b; --chip:#262624; } }
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px; background:var(--bg); color:var(--fg); font:14px/1.45 system-ui, sans-serif; }
h1 { font-size:20px; margin:0 0 4px; } .sub { color:var(--muted); margin-bottom:16px; }
.controls { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
input, select { font:inherit; padding:6px 8px; border:1px solid var(--line); border-radius:6px; background:var(--bg); color:var(--fg); }
.wrap { overflow-x:auto; }
table { border-collapse:collapse; width:100%; min-width:900px; }
th, td { text-align:left; vertical-align:top; padding:8px; border-bottom:1px solid var(--line); }
th { cursor:pointer; user-select:none; white-space:nowrap; font-weight:600; }
th.sorted::after { content:" ▾"; } th.sorted.asc::after { content:" ▴"; }
.Apply { color:var(--apply); font-weight:600; } .Maybe { color:var(--maybe); font-weight:600; } .Skip { color:var(--skip); }
.num, .nowrap { white-space:nowrap; } .num { text-align:right; font-variant-numeric:tabular-nums; }
.why { color:var(--muted); max-width:460px; } .fail { color:var(--skip); } .flag { color:var(--maybe); }
.chip { background:var(--chip); border-radius:4px; padding:1px 6px; margin-right:4px; font-size:12px; white-space:nowrap; }
a { color:inherit; }
</style></head><body>
<h1>Job screener results</h1>
<div class="sub" id="count"></div>
<div class="controls">
  <input id="q" placeholder="Filter by company, title, text…" size="32">
  <select id="rec"><option value="">All recommendations</option><option>Apply</option><option>Maybe</option><option>Skip</option></select>
</div>
<div class="wrap"><table><thead><tr>
  <th data-k="recommendation">Rec</th><th data-k="score" class="num">Score</th><th data-k="company">Company</th>
  <th data-k="title">Title</th><th data-k="salary" class="num">Salary</th><th data-k="location">Location</th>
  <th data-k="sectors">Sectors</th><th data-k="status">Status</th><th data-k="screened_at">Screened</th><th>Why</th>
</tr></thead><tbody id="rows"></tbody></table></div>
<script>
const DATA = __DATA__;
const REC = {Apply:0, Maybe:1, Skip:2};
let sortKey = "score", asc = false;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const val = (r, k) => k === "score" ? (r.score === "" ? -1 : +r.score)
  : k === "salary" ? +(r.salary_max || r.salary_min || 0)
  : k === "recommendation" ? (REC[r.recommendation] ?? 3) * 1000 - (r.score === "" ? -1 : +r.score) : String(r[k] ?? "").toLowerCase();
const money = r => (r.salary_min || r.salary_max)
  ? "$" + [r.salary_min, r.salary_max].map(v => v ? Math.round(v / 1000) + "k" : "?").join("–") : "unknown";
function render() {
  const q = document.getElementById("q").value.toLowerCase(), rec = document.getElementById("rec").value;
  const rows = DATA.filter(r => (!rec || r.recommendation === rec) &&
      (!q || Object.values(r).join(" ").toLowerCase().includes(q)))
    .sort((a, b) => { const x = val(a, sortKey), y = val(b, sortKey); return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1); });
  document.getElementById("rows").innerHTML = rows.map(r => `<tr>
    <td class="${esc(r.recommendation)}">${esc(r.recommendation)}</td>
    <td class="num">${r.score === "" ? "—" : esc(r.score)}</td>
    <td>${esc(r.company)}</td>
    <td>${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a>` : esc(r.title)}</td>
    <td class="num">${money(r)}</td><td>${esc(r.location)}</td>
    <td>${(r.sectors || "").split(", ").filter(Boolean).map(s => `<span class="chip">${esc(s)}</span>`).join("")}</td>
    <td>${esc(r.status)}</td><td class="nowrap">${esc((r.screened_at || "").slice(0, 10))}</td>
    <td class="why">${r.failed_rules ? `<span class="fail">${esc(r.failed_rules)}</span>` : esc(r.explanation)}
      ${r.flags ? `<br><span class="flag">⚑ ${esc(r.flags)}</span>` : ""}</td></tr>`).join("");
  document.getElementById("count").textContent = `${rows.length} of ${DATA.length} postings · click a column to sort`;
  document.querySelectorAll("th").forEach(th => th.classList.toggle("sorted", th.dataset.k === sortKey));
  document.querySelectorAll("th.sorted").forEach(th => th.classList.toggle("asc", asc));
}
document.querySelectorAll("th[data-k]").forEach(th => th.onclick = () => {
  asc = sortKey === th.dataset.k ? !asc : ["company", "title", "location", "status"].includes(th.dataset.k);
  sortKey = th.dataset.k; render();
});
document.getElementById("q").oninput = render; document.getElementById("rec").onchange = render;
sortKey = "recommendation"; asc = true; render();
</script></body></html>
"""


def export_html(rows: list[dict], out: Path) -> Path:
    # Escape "</" so posting text can't close the <script> element.
    data = json.dumps(rows).replace("</", "<\\/")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.replace("__DATA__", data), encoding="utf-8")
    return out
