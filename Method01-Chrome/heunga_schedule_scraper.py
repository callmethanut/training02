#!/usr/bin/env python3
"""
Heung-A Line schedule scraper.

Scrapes the "listing view" schedule table from
https://ebiz.heungaline.com/Schedule for a given POL/POD pair, for one
month, a list of months, or a month range, and saves the results to CSV.

How it works
------------
The schedule page is a plain HTML form that POSTs to /Schedule with:
    bnd   = "O" (Outbound / ETD) or "I" (Inbound / ETA)
    pol   = origin port code (e.g. "THLCH" = Laem Chabang)
    pod   = destination port code (e.g. "KRPUS" = Busan)
    month = "YYYY-MM"
    div   = "L"  (list view)
    popup = "N"

The returned HTML embeds the full table's data as a JS array:
    var schedules = [ {...}, {...}, ... ];
This script requests that page for each month you ask for, extracts and
parses that JSON array, and writes the combined rows to a CSV file.

No login/cookies are required - this is public schedule data.

Usage examples
---------------
    # Single month
    python heunga_schedule_scraper.py --month 2026-01

    # Multiple specific months
    python heunga_schedule_scraper.py --months 2026-01 2026-02 2026-06

    # A contiguous range of months
    python heunga_schedule_scraper.py --start 2026-01 --end 2026-06

    # Different route / direction / output file
    python heunga_schedule_scraper.py --pol THLCH --pod KRPUS --direction O \
        --start 2026-01 --end 2026-03 --output laemchabang_busan.csv

Finding other port codes
-------------------------
This script doesn't include a port lookup. The easiest way to find a code
is to open https://ebiz.heungaline.com/Schedule in a browser, pick the
port in the origin/destination boxes, and read the resulting `pol`/`pod`
hidden input values (e.g. via dev tools), or watch the network request
this script itself makes/receives.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Iterable, List, Dict, Optional

import requests

BASE_URL = "https://ebiz.heungaline.com/Schedule"

# All outputs default to <script folder>/output/ so the script produces
# the same result regardless of the working directory it was launched from.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
DEFAULT_OUTPUT_FILE = os.path.join(DEFAULT_OUTPUT_DIR, "heunga_schedule.csv")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE_URL,
}

POST_HEADERS = {
    **BROWSER_HEADERS,
    "Content-Type": "application/x-www-form-urlencoded",
}

SCHEDULES_START_RE = re.compile(r"var\s+schedules\s*=\s*\[", re.DOTALL)

# Columns written to the CSV, in the same order as the on-site listing table
# (plus a few extra useful raw fields at the end).
CSV_FIELDS = [
    "Month",
    "T/S",
    "Service",
    "Vessel",
    "Voyage",
    "POL",
    "POL_Terminal",
    "POD",
    "POD_Terminal",
    "ETD",
    "ETA",
    "Transit_Time",
    "POL_Code",
    "POD_Code",
    "Vessel_Code",
    "Doc_Cutoff",
    "Cargo_Cutoff",
    "VGM_Cutoff",
    "AFR_Cutoff",
]


def warmup_session(session: requests.Session, timeout: int = 30) -> None:
    """Prime the session so the site issues ASP.NET_SessionId + guest cookies.
    Without this the schedule endpoint returns HTTP 500."""
    session.get("https://ebiz.heungaline.com/Main",
                headers=BROWSER_HEADERS, timeout=timeout)
    session.get(BASE_URL, headers=BROWSER_HEADERS, timeout=timeout)


def fetch_month_html(pol: str, pod: str, direction: str, month: str,
                      session: requests.Session, timeout: int = 30) -> str:
    """POST to the schedule page for a given route/direction/month and
    return the raw HTML response. This is equivalent to selecting the
    month and clicking the on-site Search button (list view, div=L)."""
    payload = {
        "bnd": direction,
        "pol": pol,
        "pod": pod,
        "month": month,
        "div": "L",     # L = list view (as opposed to C = calendar view)
        "popup": "N",
    }
    resp = session.post(BASE_URL, data=payload, headers=POST_HEADERS,
                         timeout=timeout)
    resp.raise_for_status()
    return resp.text


def extract_schedules(html: str) -> List[Dict]:
    """Pull the server-rendered `var schedules = [...]` JSON array out of
    the page HTML. Uses a bracket-matching JSON decoder so records that
    contain nested arrays/objects don't break parsing."""
    match = SCHEDULES_START_RE.search(html)
    if not match:
        return []
    start = match.end() - 1  # position of the opening '['
    decoder = json.JSONDecoder()
    try:
        data, _ = decoder.raw_decode(html, idx=start)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse schedules JSON: {exc}") from exc
    if not isinstance(data, list):
        return []
    return data


def compute_transit_time(etd: Optional[str], eta: Optional[str]) -> str:
    """Reproduce the site's 'X Days Y Hours' transit time display."""
    if not etd or not eta:
        return ""
    try:
        etd_dt = datetime.strptime(etd, "%Y-%m-%d %H:%M")
        eta_dt = datetime.strptime(eta, "%Y-%m-%d %H:%M")
    except ValueError:
        return ""
    delta = eta_dt - etd_dt
    days = delta.days
    hours = delta.seconds // 3600
    return f"{days} Days {hours} Hours"


def row_from_record(rec: Dict, month: str) -> Dict:
    """Map one raw schedule JSON record to a CSV row matching the on-site table."""
    ts_gb = (rec.get("TS_GB") or "").strip()
    ts_label = "Direct" if not ts_gb else ts_gb

    return {
        "Month": month,
        "T/S": ts_label,
        "Service": rec.get("SVC") or "",
        "Vessel": rec.get("VSLNM") or "",
        "Voyage": rec.get("VYG") or "",
        "POL": (rec.get("POLNM") or "").strip(),
        "POL_Terminal": rec.get("POLWNM") or "",
        "POD": (rec.get("PODNM") or "").strip(),
        "POD_Terminal": rec.get("PODWNM") or "",
        "ETD": rec.get("ETD") or "",
        "ETA": rec.get("ETA") or "",
        "Transit_Time": compute_transit_time(rec.get("ETD"), rec.get("ETA")),
        "POL_Code": rec.get("POL") or "",
        "POD_Code": rec.get("POD") or "",
        "Vessel_Code": rec.get("VSL") or "",
        "Doc_Cutoff": rec.get("DOCUDATE") or "",
        "Cargo_Cutoff": rec.get("CNTRDATE") or "",
        "VGM_Cutoff": rec.get("VGMCLOSING") or "",
        "AFR_Cutoff": rec.get("AFRCLOSING") or "",
    }


def scrape_months(pol: str, pod: str, direction: str, months: Iterable[str],
                   delay: float = 1.0) -> List[Dict]:
    """Scrape one or more months and return combined CSV-ready rows."""
    rows: List[Dict] = []
    seen = set()  # de-dupe rows that may appear in more than one month fetch
    with requests.Session() as session:
        # One warm-up per run — reused across every month, same as a real
        # browser: open the page once, then click Search for each month.
        warmup_session(session)
        for i, month in enumerate(months):
            if i > 0 and delay:
                time.sleep(delay)
            print(f"Fetching {pol} -> {pod} ({direction}) for {month} ...",
                  file=sys.stderr)
            html = fetch_month_html(pol, pod, direction, month, session)
            records = extract_schedules(html)
            print(f"  -> {len(records)} sailings found", file=sys.stderr)
            for rec in records:
                row = row_from_record(rec, month)
                key = (row["Service"], row["Voyage"], row["ETD"], row["ETA"])
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
    return rows


def month_range(start: str, end: str) -> List[str]:
    """Generate inclusive list of 'YYYY-MM' strings from start to end."""
    start_dt = datetime.strptime(start, "%Y-%m")
    end_dt = datetime.strptime(end, "%Y-%m")
    if end_dt < start_dt:
        raise ValueError("--end must not be before --start")
    months = []
    year, month = start_dt.year, start_dt.month
    while (year, month) <= (end_dt.year, end_dt.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


def write_csv(rows: List[Dict], output_path: str) -> None:
    parent = os.path.dirname(os.path.abspath(output_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {output_path}", file=sys.stderr)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape Heung-A Line sailing schedules to CSV.")
    parser.add_argument("--pol", default="THLCH",
                         help="Origin port code (default: THLCH = Laem Chabang)")
    parser.add_argument("--pod", default="KRPUS",
                         help="Destination port code (default: KRPUS = Busan)")
    parser.add_argument("--direction", choices=["O", "I"], default="O",
                         help="O = Outbound/ETD (default), I = Inbound/ETA")

    month_group = parser.add_mutually_exclusive_group()
    month_group.add_argument("--month", help="Single month, e.g. 2026-01")
    month_group.add_argument("--months", nargs="+",
                              help="List of months, e.g. --months 2026-01 2026-02")

    parser.add_argument("--start", help="Range start month, e.g. 2026-01 "
                                         "(use with --end)")
    parser.add_argument("--end", help="Range end month, e.g. 2026-06 "
                                       "(use with --start)")

    parser.add_argument("--output", default=DEFAULT_OUTPUT_FILE,
                         help="Output CSV file path "
                              "(default: <script-dir>/output/heunga_schedule.csv)")
    parser.add_argument("--delay", type=float, default=1.0,
                         help="Seconds to wait between requests (default: 1.0)")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.month:
        months = [args.month]
    elif args.months:
        months = args.months
    elif args.start and args.end:
        months = month_range(args.start, args.end)
    elif args.start or args.end:
        parser.error("--start and --end must be used together")
    else:
        # Default: current month only
        months = [datetime.now().strftime("%Y-%m")]

    rows = scrape_months(args.pol, args.pod, args.direction, months, args.delay)
    write_csv(rows, args.output)


if __name__ == "__main__":
    main()
