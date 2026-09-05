#!/usr/bin/env python3
"""
Heung-A schedule dashboard generator.

Reads one or more CSV files produced by heunga_schedule_scraper.py and
writes a single self-contained HTML dashboard with charts and a
filterable table. No build step, no local server — just open the HTML
in a browser.

Usage
-----
    # Combine every CSV in the current folder into dashboard.html
    python heunga_dashboard.py

    # Specific folder / pattern / output
    python heunga_dashboard.py --input-dir . --pattern "*.csv" \
        --output dashboard.html

    # Explicit list of files
    python heunga_dashboard.py --files laemchabang_busan.csv picked.csv \
        --output combined_dashboard.html
"""

import argparse
import csv
import glob
import html
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, Iterable, List, Tuple


# Default I/O locations live inside <script folder>/output/ so this script
# works the same no matter where it is launched from.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
DEFAULT_OUTPUT_FILE = os.path.join(DEFAULT_OUTPUT_DIR, "dashboard.html")


EXPECTED_COLUMNS = [
    "Month", "T/S", "Service", "Vessel", "Voyage",
    "POL", "POL_Terminal", "POD", "POD_Terminal",
    "ETD", "ETA", "Transit_Time",
    "POL_Code", "POD_Code", "Vessel_Code",
    "Doc_Cutoff", "Cargo_Cutoff", "VGM_Cutoff", "AFR_Cutoff",
]


def load_rows(paths: Iterable[str]) -> List[Dict[str, str]]:
    """Read + concat all CSVs. Dedupes by (POL, POD, Service, Voyage, ETD, ETA)."""
    rows: List[Dict[str, str]] = []
    seen = set()
    for path in paths:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                key = (r.get("POL_Code", ""), r.get("POD_Code", ""),
                       r.get("Service", ""), r.get("Voyage", ""),
                       r.get("ETD", ""), r.get("ETA", ""))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(r)
        print(f"loaded {path}", file=sys.stderr)
    return rows


def transit_hours(etd: str, eta: str) -> float:
    if not etd or not eta:
        return 0.0
    try:
        d1 = datetime.strptime(etd, "%Y-%m-%d %H:%M")
        d2 = datetime.strptime(eta, "%Y-%m-%d %H:%M")
    except ValueError:
        return 0.0
    return max(0.0, (d2 - d1).total_seconds() / 3600.0)


def summarize(rows: List[Dict[str, str]]) -> Dict:
    months = sorted({r.get("Month", "") for r in rows if r.get("Month")})
    services = Counter(r.get("Service", "") for r in rows if r.get("Service"))
    vessels = Counter(r.get("Vessel", "") for r in rows if r.get("Vessel"))
    ts_labels = Counter((r.get("T/S") or "Direct") for r in rows)
    pol_terminals = Counter(r.get("POL_Terminal", "") for r in rows
                             if r.get("POL_Terminal"))
    pod_terminals = Counter(r.get("POD_Terminal", "") for r in rows
                             if r.get("POD_Terminal"))
    lanes = Counter(f"{(r.get('POL') or '').strip()} → {(r.get('POD') or '').strip()}"
                     for r in rows if r.get("POL") and r.get("POD"))

    per_month = Counter(r.get("Month", "") for r in rows if r.get("Month"))

    # Per-service per-month grid (for stacked bars)
    per_month_service: Dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        m = r.get("Month", "")
        s = r.get("Service", "") or "?"
        if m:
            per_month_service[m][s] += 1

    # Transit-time histogram (bucketed by day)
    transit_buckets: Counter = Counter()
    for r in rows:
        h = transit_hours(r.get("ETD", ""), r.get("ETA", ""))
        if h > 0:
            bucket = f"{int(h // 24)}d"
            transit_buckets[bucket] += 1

    return {
        "rows": rows,
        "totals": {
            "sailings": len(rows),
            "months": len(months),
            "services": len(services),
            "vessels": len(vessels),
            "lanes": len(lanes),
        },
        "months": months,
        "per_month": per_month,
        "per_month_service": per_month_service,
        "services": services,
        "vessels": vessels,
        "ts_labels": ts_labels,
        "pol_terminals": pol_terminals,
        "pod_terminals": pod_terminals,
        "lanes": lanes,
        "transit_buckets": transit_buckets,
    }


def counter_to_sorted_pairs(counter: Counter, limit: int = None,
                             sort_by_key: bool = False) -> Tuple[List[str], List[int]]:
    items = list(counter.items())
    if sort_by_key:
        items.sort(key=lambda kv: kv[0])
    else:
        items.sort(key=lambda kv: (-kv[1], kv[0]))
    if limit:
        items = items[:limit]
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    return labels, values


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Heung-A Schedule Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0f172a;
    --card: #1e293b;
    --border: #334155;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --accent-2: #a78bfa;
    --good: #34d399;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px;
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 14px;
  }
  h1 { margin: 0 0 4px 0; font-size: 22px; }
  .subtitle { color: var(--muted); margin-bottom: 20px; font-size: 13px; }
  .kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 20px; }
  .kpi {
    background: var(--card); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px 16px;
  }
  .kpi .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; }
  .kpi .value { font-size: 28px; font-weight: 600; margin-top: 4px; color: var(--accent); }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; margin-bottom: 20px; }
  .card {
    background: var(--card); border: 1px solid var(--border); border-radius: 10px;
    padding: 16px;
  }
  .card h2 { font-size: 14px; margin: 0 0 12px 0; color: var(--text); font-weight: 600; }
  .chart-wrap { position: relative; height: 260px; }
  .card.tall .chart-wrap { height: 340px; }

  .table-card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
  .table-controls { display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
  .table-controls input, .table-controls select {
    background: #0b1220; color: var(--text); border: 1px solid var(--border);
    padding: 6px 10px; border-radius: 6px; font-size: 13px;
  }
  .table-controls input { flex: 1; min-width: 200px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }
  th {
    background: #0b1220; color: var(--muted); cursor: pointer; user-select: none;
    position: sticky; top: 0;
  }
  th:hover { color: var(--accent); }
  tbody tr:hover { background: rgba(56, 189, 248, 0.05); }
  .table-scroll { max-height: 500px; overflow: auto; border: 1px solid var(--border); border-radius: 6px; }
  .badge { padding: 2px 8px; border-radius: 999px; font-size: 11px; }
  .badge.direct { background: rgba(52, 211, 153, 0.15); color: var(--good); }
  .badge.ts { background: rgba(167, 139, 250, 0.15); color: var(--accent-2); }
  .count { color: var(--muted); font-size: 12px; margin-top: 8px; }
</style>
</head>
<body>

<h1>Heung-A Line — Schedule Dashboard</h1>
<div class="subtitle">Generated __GENERATED__ · __SOURCES__</div>

<div class="kpi-row">
  <div class="kpi"><div class="label">Total sailings</div><div class="value" id="kpi-sailings"></div></div>
  <div class="kpi"><div class="label">Months</div><div class="value" id="kpi-months"></div></div>
  <div class="kpi"><div class="label">Services</div><div class="value" id="kpi-services"></div></div>
  <div class="kpi"><div class="label">Vessels</div><div class="value" id="kpi-vessels"></div></div>
  <div class="kpi"><div class="label">Lanes</div><div class="value" id="kpi-lanes"></div></div>
</div>

<div class="grid">
  <div class="card"><h2>Sailings per month</h2><div class="chart-wrap"><canvas id="chart-month"></canvas></div></div>
  <div class="card"><h2>Sailings per service</h2><div class="chart-wrap"><canvas id="chart-service"></canvas></div></div>
  <div class="card tall"><h2>Sailings per month (stacked by service)</h2><div class="chart-wrap"><canvas id="chart-month-service"></canvas></div></div>
  <div class="card"><h2>Direct vs Transshipment</h2><div class="chart-wrap"><canvas id="chart-ts"></canvas></div></div>
  <div class="card"><h2>Top 10 vessels</h2><div class="chart-wrap"><canvas id="chart-vessel"></canvas></div></div>
  <div class="card"><h2>Transit time (days)</h2><div class="chart-wrap"><canvas id="chart-transit"></canvas></div></div>
  <div class="card"><h2>Origin terminals</h2><div class="chart-wrap"><canvas id="chart-pol-term"></canvas></div></div>
  <div class="card"><h2>Destination terminals</h2><div class="chart-wrap"><canvas id="chart-pod-term"></canvas></div></div>
</div>

<div class="table-card">
  <h2 style="margin:0 0 12px 0;font-size:14px;">Sailings</h2>
  <div class="table-controls">
    <input id="tbl-search" type="text" placeholder="Filter by any column (vessel, service, port, terminal, month…)"/>
    <select id="tbl-month"><option value="">All months</option></select>
    <select id="tbl-service"><option value="">All services</option></select>
    <select id="tbl-ts"><option value="">All (Direct + T/S)</option><option value="Direct">Direct only</option><option value="TS">T/S only</option></select>
  </div>
  <div class="table-scroll">
    <table>
      <thead>
        <tr>
          <th data-key="Month">Month</th>
          <th data-key="T/S">T/S</th>
          <th data-key="Service">Service</th>
          <th data-key="Vessel">Vessel</th>
          <th data-key="Voyage">Voyage</th>
          <th data-key="POL">POL</th>
          <th data-key="POL_Terminal">POL Terminal</th>
          <th data-key="POD">POD</th>
          <th data-key="POD_Terminal">POD Terminal</th>
          <th data-key="ETD">ETD</th>
          <th data-key="ETA">ETA</th>
          <th data-key="Transit_Time">Transit</th>
        </tr>
      </thead>
      <tbody id="tbl-body"></tbody>
    </table>
  </div>
  <div class="count" id="tbl-count"></div>
</div>

<script>
const DATA = __DATA__;
const TEXT = { accent: '#38bdf8', accent2: '#a78bfa', good: '#34d399', muted: '#94a3b8', grid: 'rgba(148, 163, 184, 0.15)' };
Chart.defaults.color = TEXT.muted;
Chart.defaults.borderColor = TEXT.grid;

// KPIs
document.getElementById('kpi-sailings').textContent = DATA.totals.sailings.toLocaleString();
document.getElementById('kpi-months').textContent   = DATA.totals.months;
document.getElementById('kpi-services').textContent = DATA.totals.services;
document.getElementById('kpi-vessels').textContent  = DATA.totals.vessels;
document.getElementById('kpi-lanes').textContent    = DATA.totals.lanes;

// Palette generator (stable per label so colors don't jump on refresh)
function color(i, alpha=1) {
  const hues = [200, 265, 155, 25, 335, 45, 105, 295, 220, 175];
  const h = hues[i % hues.length];
  return `hsla(${h}, 70%, 60%, ${alpha})`;
}

function bar(id, labels, values, opts={}) {
  new Chart(document.getElementById(id), {
    type: 'bar',
    data: { labels, datasets: [{
      data: values,
      backgroundColor: labels.map((_, i) => color(i, 0.75)),
      borderColor: labels.map((_, i) => color(i, 1)),
      borderWidth: 1,
    }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { intersect: false } },
      indexAxis: opts.horizontal ? 'y' : 'x',
      scales: {
        x: { grid: { color: TEXT.grid }, ticks: { autoSkip: !opts.horizontal, maxRotation: 45, minRotation: 0 } },
        y: { grid: { color: TEXT.grid }, beginAtZero: true }
      }
    }
  });
}

function doughnut(id, labels, values) {
  new Chart(document.getElementById(id), {
    type: 'doughnut',
    data: { labels, datasets: [{
      data: values,
      backgroundColor: labels.map((_, i) => color(i, 0.85)),
      borderColor: '#1e293b', borderWidth: 2,
    }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'right', labels: { boxWidth: 12 } } }
    }
  });
}

function stackedBar(id, labels, seriesMap) {
  const services = Object.keys(seriesMap);
  const datasets = services.map((svc, i) => ({
    label: svc,
    data: labels.map(m => seriesMap[svc][m] || 0),
    backgroundColor: color(i, 0.75),
    borderColor: color(i, 1),
    borderWidth: 1,
  }));
  new Chart(document.getElementById(id), {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'right', labels: { boxWidth: 10, font: {size: 11} } }, tooltip: { intersect: false, mode: 'index' } },
      scales: {
        x: { stacked: true, grid: { color: TEXT.grid } },
        y: { stacked: true, grid: { color: TEXT.grid }, beginAtZero: true }
      }
    }
  });
}

bar('chart-month',   DATA.per_month.labels,   DATA.per_month.values);
bar('chart-service', DATA.services.labels,    DATA.services.values);
bar('chart-vessel',  DATA.vessels.labels,     DATA.vessels.values, { horizontal: true });
bar('chart-transit', DATA.transit.labels,     DATA.transit.values);
doughnut('chart-ts',        DATA.ts.labels,           DATA.ts.values);
doughnut('chart-pol-term',  DATA.pol_terminals.labels, DATA.pol_terminals.values);
doughnut('chart-pod-term',  DATA.pod_terminals.labels, DATA.pod_terminals.values);
stackedBar('chart-month-service', DATA.per_month.labels, DATA.per_month_service);

// Table
const tbody = document.getElementById('tbl-body');
const searchEl = document.getElementById('tbl-search');
const monthEl = document.getElementById('tbl-month');
const serviceEl = document.getElementById('tbl-service');
const tsEl = document.getElementById('tbl-ts');
const countEl = document.getElementById('tbl-count');

DATA.per_month.labels.forEach(m => {
  const o = document.createElement('option'); o.value = m; o.textContent = m; monthEl.appendChild(o);
});
DATA.services.labels.forEach(s => {
  const o = document.createElement('option'); o.value = s; o.textContent = s; serviceEl.appendChild(o);
});

let sortKey = 'ETD', sortAsc = true;
document.querySelectorAll('th[data-key]').forEach(th => {
  th.addEventListener('click', () => {
    const k = th.dataset.key;
    if (k === sortKey) sortAsc = !sortAsc; else { sortKey = k; sortAsc = true; }
    renderTable();
  });
});

[searchEl, monthEl, serviceEl, tsEl].forEach(el => el.addEventListener('input', renderTable));

function renderTable() {
  const q = searchEl.value.trim().toLowerCase();
  const mFilter = monthEl.value, sFilter = serviceEl.value, tsFilter = tsEl.value;
  let rows = DATA.rows.filter(r => {
    if (mFilter && r.Month !== mFilter) return false;
    if (sFilter && r.Service !== sFilter) return false;
    if (tsFilter === 'Direct' && (r['T/S'] || 'Direct') !== 'Direct') return false;
    if (tsFilter === 'TS' && (r['T/S'] || 'Direct') === 'Direct') return false;
    if (!q) return true;
    return Object.values(r).some(v => (v || '').toString().toLowerCase().includes(q));
  });
  rows.sort((a, b) => {
    const av = (a[sortKey] || '').toString(), bv = (b[sortKey] || '').toString();
    return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
  });
  tbody.innerHTML = rows.slice(0, 500).map(r => {
    const ts = r['T/S'] || 'Direct';
    const tsHtml = ts === 'Direct'
      ? '<span class="badge direct">Direct</span>'
      : `<span class="badge ts">${escapeHtml(ts)}</span>`;
    return `<tr>
      <td>${escapeHtml(r.Month)}</td>
      <td>${tsHtml}</td>
      <td>${escapeHtml(r.Service)}</td>
      <td>${escapeHtml(r.Vessel)}</td>
      <td>${escapeHtml(r.Voyage)}</td>
      <td>${escapeHtml(r.POL)}</td>
      <td>${escapeHtml(r.POL_Terminal)}</td>
      <td>${escapeHtml(r.POD)}</td>
      <td>${escapeHtml(r.POD_Terminal)}</td>
      <td>${escapeHtml(r.ETD)}</td>
      <td>${escapeHtml(r.ETA)}</td>
      <td>${escapeHtml(r.Transit_Time)}</td>
    </tr>`;
  }).join('');
  countEl.textContent = `Showing ${Math.min(rows.length, 500).toLocaleString()} of ${rows.length.toLocaleString()} filtered sailings (from ${DATA.rows.length.toLocaleString()} total).`;
}
function escapeHtml(s) {
  return (s || '').toString().replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
renderTable();
</script>
</body>
</html>
"""


def build_html(summary: Dict, sources: List[str]) -> str:
    per_month_labels, per_month_values = counter_to_sorted_pairs(
        summary["per_month"], sort_by_key=True)
    services_labels, services_values = counter_to_sorted_pairs(
        summary["services"], limit=20)
    vessels_labels, vessels_values = counter_to_sorted_pairs(
        summary["vessels"], limit=10)
    ts_labels, ts_values = counter_to_sorted_pairs(summary["ts_labels"])
    pol_term_labels, pol_term_values = counter_to_sorted_pairs(
        summary["pol_terminals"], limit=8)
    pod_term_labels, pod_term_values = counter_to_sorted_pairs(
        summary["pod_terminals"], limit=8)

    # Order transit buckets numerically ("10d" < "12d" — sort by int prefix)
    transit_pairs = sorted(summary["transit_buckets"].items(),
                            key=lambda kv: int(kv[0].rstrip("d")))
    transit_labels = [k for k, _ in transit_pairs]
    transit_values = [v for _, v in transit_pairs]

    # Stacked-bar per_month_service: {service: {month: n}}
    all_services_in_stack = [s for s, _ in
                              summary["services"].most_common(10)]
    stack_map: Dict[str, Dict[str, int]] = {s: {} for s in all_services_in_stack}
    for month, svc_counter in summary["per_month_service"].items():
        for svc, n in svc_counter.items():
            if svc in stack_map:
                stack_map[svc][month] = n

    data = {
        "totals": summary["totals"],
        "per_month":         {"labels": per_month_labels, "values": per_month_values},
        "per_month_service": stack_map,
        "services":          {"labels": services_labels, "values": services_values},
        "vessels":           {"labels": vessels_labels, "values": vessels_values},
        "ts":                {"labels": ts_labels,      "values": ts_values},
        "transit":           {"labels": transit_labels, "values": transit_values},
        "pol_terminals":     {"labels": pol_term_labels, "values": pol_term_values},
        "pod_terminals":     {"labels": pod_term_labels, "values": pod_term_values},
        "rows":              summary["rows"],
    }

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    sources_str = html.escape(
        f"{len(sources)} file(s): " + ", ".join(os.path.basename(p) for p in sources))

    return (HTML_TEMPLATE
             .replace("__GENERATED__", generated_at)
             .replace("__SOURCES__", sources_str)
             .replace("__DATA__", json.dumps(data, ensure_ascii=False)))


def resolve_input_files(args: argparse.Namespace) -> List[str]:
    if args.files:
        paths = args.files
    else:
        pattern = os.path.join(args.input_dir, args.pattern)
        paths = sorted(glob.glob(pattern))
        # Never include our own output file in the input set
        out_abs = os.path.abspath(args.output)
        paths = [p for p in paths if os.path.abspath(p) != out_abs]
    if not paths:
        raise SystemExit(f"No CSV files matched (dir={args.input_dir!r}, "
                          f"pattern={args.pattern!r}).")
    return paths


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate an HTML dashboard from Heung-A schedule CSVs.")
    p.add_argument("--input-dir", default=DEFAULT_OUTPUT_DIR,
                    help="Folder to scan for CSVs "
                         "(default: <script-dir>/output)")
    p.add_argument("--pattern", default="*.csv",
                    help="Glob pattern within --input-dir (default: *.csv)")
    p.add_argument("--files", nargs="+",
                    help="Explicit list of CSV files (overrides --input-dir/--pattern)")
    p.add_argument("--output", default=DEFAULT_OUTPUT_FILE,
                    help="Output HTML path "
                         "(default: <script-dir>/output/dashboard.html)")
    return p


def main() -> None:
    args = build_arg_parser().parse_args()
    paths = resolve_input_files(args)
    rows = load_rows(paths)
    if not rows:
        raise SystemExit("Loaded 0 rows — nothing to render.")
    summary = summarize(rows)
    html_out = build_html(summary, paths)

    parent = os.path.dirname(os.path.abspath(args.output))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"Wrote {args.output}  ({summary['totals']['sailings']} sailings "
          f"from {len(paths)} file(s))", file=sys.stderr)


if __name__ == "__main__":
    main()
