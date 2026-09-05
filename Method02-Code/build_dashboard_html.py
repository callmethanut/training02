"""
build_dashboard_html.py
=======================

Reads every *.xlsx file that daily_schedule_scraper.py has dropped into
./schedule-daily/ and produces Dashboard.html — a single self-contained
web page you can open in any browser (double-click, no server needed).

The page contains:
    * A summary strip (routes / total sailings / week span).
    * A line chart of weekly sailings per route (Chart.js from CDN).
    * A weekly totals table (with a Total column).
    * A searchable/filterable raw table of every schedule row.

HOW TO RUN
----------
    pip install openpyxl
    python build_dashboard_html.py
    # or:
    python build_dashboard_html.py --indir schedule-daily --out Dashboard.html

The generated file loads Chart.js from a CDN
(https://cdn.jsdelivr.net/npm/chart.js) — an internet connection is only
needed the first time it's opened in a browser (the browser then caches it).
Everything else, including the data, is embedded inline as JSON.

NO AI / NO API CALLS at runtime. Pure openpyxl + string templating.

MAINTENANCE WARNING
-------------------
If daily_schedule_scraper.py changes the sheet layout (columns, sheet names,
meta keys), update SOURCE_COLUMNS / _read_source() in build_dashboard.py —
this script re-uses that module's schema constants.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

# Reuse the loader + column schema from the xlsx dashboard so both dashboards
# stay in sync automatically.
from build_dashboard import (
    SOURCE_COLUMNS,
    discover_sources,
    parse_etd,
    week_start,
)

# Default I/O lives under <script folder>/output/ so this script works the
# same no matter where it is launched from.
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INDIR = SCRIPT_DIR / "output" / "schedule-daily"
DEFAULT_OUT = SCRIPT_DIR / "output" / "Dashboard.html"

RAW_COLUMNS = ["Route", "Snapshot"] + SOURCE_COLUMNS


def _collect(indir: Path) -> tuple[list[dict], list[str], list[date]]:
    """Return (raw_rows, routes_seen_in_order, weeks_sorted)."""
    from build_dashboard import _read_source  # local re-use, avoids duplicating

    sources = discover_sources(indir)
    raw: list[dict] = []
    routes_seen: list[str] = []
    weeks: set[date] = set()

    for src in sources:
        parsed = _read_source(src.path)
        if parsed is None:
            continue
        _pol, _pod, _snap, rows = parsed
        for r in rows:
            padded = (r + [""] * len(SOURCE_COLUMNS))[: len(SOURCE_COLUMNS)]
            record = {"Route": src.route, "Snapshot": src.snapshot.isoformat()}
            record.update(dict(zip(SOURCE_COLUMNS, padded)))
            raw.append(record)
            d = parse_etd(record.get("ETD", ""))
            if d:
                weeks.add(week_start(d))
        if src.route not in routes_seen:
            routes_seen.append(src.route)

    return raw, routes_seen, sorted(weeks)


def _weekly_matrix(raw: list[dict], routes: list[str], weeks: list[date]) -> list[list[int]]:
    """Return counts[week_idx][route_idx]."""
    grid = [[0] * len(routes) for _ in weeks]
    idx_week = {w: i for i, w in enumerate(weeks)}
    idx_route = {r: i for i, r in enumerate(routes)}
    for row in raw:
        d = parse_etd(row.get("ETD", ""))
        if not d:
            continue
        w = week_start(d)
        if w in idx_week and row["Route"] in idx_route:
            grid[idx_week[w]][idx_route[row["Route"]]] += 1
    return grid


# Palette used for the chart lines + the badge next to each route in the table.
PALETTE = [
    "#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed",
    "#0891b2", "#db2777", "#65a30d", "#ea580c", "#4338ca",
]


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sinokor Schedule Dashboard — {generated}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #f6f7fb;
    --panel: #ffffff;
    --ink: #1f2937;
    --muted: #6b7280;
    --line: #e5e7eb;
    --accent: #2563eb;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: var(--ink);
    background: var(--bg);
  }}
  header {{
    padding: 28px 32px 20px;
    background: linear-gradient(180deg, #ffffff 0%, #f6f7fb 100%);
    border-bottom: 1px solid var(--line);
  }}
  h1 {{ margin: 0 0 4px; font-size: 22px; letter-spacing: -0.01em; }}
  .subtitle {{ color: var(--muted); font-size: 13px; }}
  main {{ padding: 24px 32px 64px; max-width: 1400px; margin: 0 auto; }}
  section {{
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 20px 24px;
    margin-bottom: 24px;
  }}
  section h2 {{
    margin: 0 0 16px; font-size: 15px; font-weight: 600;
    color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em;
  }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }}
  .kpi {{
    background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
    padding: 18px 20px;
  }}
  .kpi .n {{ font-size: 28px; font-weight: 600; line-height: 1.1; }}
  .kpi .label {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 4px; }}
  .chart-wrap {{ position: relative; height: 360px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{
    padding: 8px 10px; text-align: left; vertical-align: top;
    border-bottom: 1px solid var(--line); white-space: nowrap;
  }}
  th {{
    background: #f9fafb; font-weight: 600; color: var(--muted);
    text-transform: uppercase; font-size: 11px; letter-spacing: 0.04em;
    position: sticky; top: 0;
  }}
  tbody tr:hover {{ background: #f9fafb; }}
  td.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .badge {{
    display: inline-block; padding: 2px 8px; border-radius: 999px;
    color: #fff; font-size: 11px; font-weight: 600; letter-spacing: 0.02em;
  }}
  .table-scroll {{ max-height: 520px; overflow: auto; border: 1px solid var(--line); border-radius: 8px; }}
  .toolbar {{ display: flex; gap: 12px; align-items: center; margin-bottom: 12px; }}
  .toolbar input {{
    flex: 1; padding: 8px 12px; border: 1px solid var(--line); border-radius: 8px; font: inherit;
  }}
  .toolbar .count {{ color: var(--muted); font-size: 12px; }}
  .cell-wrap {{ white-space: pre-line; max-width: 260px; }}
</style>
</head>
<body>
<header>
  <h1>Sinokor Schedule Dashboard</h1>
  <div class="subtitle">Generated {generated} — source: <code>{indir}</code></div>
</header>
<main>

<section>
  <h2>Summary</h2>
  <div class="kpis">
    <div class="kpi"><div class="n">{n_routes}</div><div class="label">Routes</div></div>
    <div class="kpi"><div class="n">{n_sailings}</div><div class="label">Total sailings</div></div>
    <div class="kpi"><div class="n">{n_weeks}</div><div class="label">Weeks covered</div></div>
    <div class="kpi"><div class="n">{first_week} → {last_week}</div><div class="label">Date range (ETD)</div></div>
  </div>
</section>

<section>
  <h2>Weekly sailings per route</h2>
  <div class="chart-wrap"><canvas id="chart"></canvas></div>
</section>

<section>
  <h2>Weekly totals</h2>
  <div class="table-scroll">
    <table>
      <thead>
        <tr>
          <th>Week (Mon)</th>
          {weekly_th}
          <th class="n">Total</th>
        </tr>
      </thead>
      <tbody>{weekly_tbody}</tbody>
    </table>
  </div>
</section>

<section>
  <h2>Raw schedule ({n_sailings})</h2>
  <div class="toolbar">
    <input id="q" placeholder="Filter — search vessel, service, terminal, route…">
    <span class="count" id="count"></span>
  </div>
  <div class="table-scroll">
    <table id="raw">
      <thead><tr>{raw_th}</tr></thead>
      <tbody>{raw_tbody}</tbody>
    </table>
  </div>
</section>

</main>

<script>
const CHART_DATA = {chart_json};
const ctx = document.getElementById('chart').getContext('2d');
new Chart(ctx, {{
  type: 'line',
  data: CHART_DATA,
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ boxWidth: 12, padding: 12 }} }},
      tooltip: {{ padding: 10 }}
    }},
    scales: {{
      y: {{ beginAtZero: true, ticks: {{ precision: 0 }}, title: {{ display: true, text: 'Sailings' }} }},
      x: {{ title: {{ display: true, text: 'Week starting (Mon)' }} }}
    }}
  }}
}});

// Simple, dependency-free client-side filter over the Raw table.
const q = document.getElementById('q');
const tbody = document.querySelector('#raw tbody');
const count = document.getElementById('count');
const rows = Array.from(tbody.rows);
const total = rows.length;
function refresh() {{
  const term = q.value.trim().toLowerCase();
  let shown = 0;
  for (const r of rows) {{
    const hit = !term || r.textContent.toLowerCase().includes(term);
    r.style.display = hit ? '' : 'none';
    if (hit) shown++;
  }}
  count.textContent = shown + ' / ' + total + ' rows';
}}
q.addEventListener('input', refresh);
refresh();
</script>
</body>
</html>
"""


def _esc(v) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def render(indir: Path, out_path: Path) -> None:
    raw, routes, weeks = _collect(indir)
    if not raw:
        print("[warn] no rows found — dashboard will be empty", file=sys.stderr)

    grid = _weekly_matrix(raw, routes, weeks)

    # Chart.js data structure
    chart_data = {
        "labels": [w.isoformat() for w in weeks],
        "datasets": [
            {
                "label": route,
                "data": [grid[wi][ri] for wi in range(len(weeks))],
                "borderColor": PALETTE[ri % len(PALETTE)],
                "backgroundColor": PALETTE[ri % len(PALETTE)] + "22",
                "tension": 0.25,
                "fill": False,
                "pointRadius": 3,
                "borderWidth": 2,
            }
            for ri, route in enumerate(routes)
        ],
    }

    # Weekly totals table
    weekly_th = "".join(
        f'<th class="n"><span class="badge" style="background:{PALETTE[i % len(PALETTE)]}">'
        f"{_esc(r)}</span></th>"
        for i, r in enumerate(routes)
    )
    weekly_tbody_parts = []
    for wi, w in enumerate(weeks):
        cells = "".join(f'<td class="n">{grid[wi][ri]}</td>' for ri in range(len(routes)))
        total = sum(grid[wi])
        weekly_tbody_parts.append(
            f"<tr><td>{w.isoformat()}</td>{cells}<td class=\"n\"><b>{total}</b></td></tr>"
        )
    # Grand-total row
    if weeks:
        grand = [sum(grid[wi][ri] for wi in range(len(weeks))) for ri in range(len(routes))]
        cells = "".join(f'<td class="n"><b>{v}</b></td>' for v in grand)
        weekly_tbody_parts.append(
            f'<tr style="background:#f3f4f6"><td><b>Total</b></td>{cells}'
            f'<td class="n"><b>{sum(grand)}</b></td></tr>'
        )
    weekly_tbody = "".join(weekly_tbody_parts)

    # Raw table
    raw_th = "".join(f"<th>{_esc(c)}</th>" for c in RAW_COLUMNS)
    raw_tbody_parts = []
    for row in raw:
        cells = []
        for c in RAW_COLUMNS:
            v = row.get(c, "")
            cell_class = ' class="cell-wrap"' if "\n" in str(v) else ""
            cells.append(f"<td{cell_class}>{_esc(v)}</td>")
        raw_tbody_parts.append(f"<tr>{''.join(cells)}</tr>")
    raw_tbody = "".join(raw_tbody_parts)

    week_first = weeks[0].isoformat() if weeks else "—"
    week_last = weeks[-1].isoformat() if weeks else "—"

    html_doc = HTML_TEMPLATE.format(
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        indir=_esc(indir),
        n_routes=len(routes),
        n_sailings=len(raw),
        n_weeks=len(weeks),
        first_week=week_first,
        last_week=week_last,
        weekly_th=weekly_th,
        weekly_tbody=weekly_tbody,
        raw_th=raw_th,
        raw_tbody=raw_tbody,
        chart_json=json.dumps(chart_data),
    )
    out_path.write_text(html_doc, encoding="utf-8")
    print(f"[OK]  Wrote {out_path}  ({len(raw)} rows, {len(routes)} routes, {len(weeks)} weeks)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Render Dashboard.html from schedule-daily/*.xlsx")
    ap.add_argument("--indir", default=str(DEFAULT_INDIR),
                    help="Folder with per-route Excel files "
                         "(default: <script-dir>/output/schedule-daily)")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="Output HTML file "
                         "(default: <script-dir>/output/Dashboard.html)")
    args = ap.parse_args()

    indir = Path(args.indir)
    if not indir.is_dir():
        print(f"[fatal] input folder not found: {indir}", file=sys.stderr)
        sys.exit(2)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    render(indir, out_path)


if __name__ == "__main__":
    main()
