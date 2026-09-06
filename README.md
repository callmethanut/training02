# Heung-A Line Schedule Scraper

Scrapes container-sailing schedules from Heung-A Line's e-service
(`ebiz.heungaline.com`) into CSV files, then renders them as a single
self-contained HTML dashboard.

Direct HTTP with `requests` — no browser automation, no login, no API
key. Fast (seconds per month) and low-maintenance.

Outputs land in `Method01-Chrome/output/`, which is gitignored.

---

## Prerequisites

- **Python 3.8 or newer**
- **Git** to clone the repo

Check yours:
```
python --version
```

---

## Install

```
pip install -r Method01-Chrome\requirements.txt
```

Only one dependency: `requests`.

---

## Scrape

All commands below assume you're at the repo root (`E:\training02`).

```
# Current month, default route (Laem Chabang -> Busan, outbound)
python Method01-Chrome\heunga_schedule_scraper.py

# Single specific month
python Method01-Chrome\heunga_schedule_scraper.py --month 2026-02

# Month range (recommended for a real dataset)
python Method01-Chrome\heunga_schedule_scraper.py --start 2026-01 --end 2026-06

# Non-contiguous months
python Method01-Chrome\heunga_schedule_scraper.py --months 2026-01 2026-03 2026-06

# Different route: Busan -> Laem Chabang, inbound view
python Method01-Chrome\heunga_schedule_scraper.py --pol KRPUS --pod THLCH --direction I --start 2026-01 --end 2026-03

# Custom output filename
python Method01-Chrome\heunga_schedule_scraper.py --start 2026-01 --end 2026-06 --output Method01-Chrome\output\lch_pus_h1.csv

# Be gentler on the server (3 s between month requests)
python Method01-Chrome\heunga_schedule_scraper.py --start 2026-01 --end 2026-12 --delay 3
```

### Flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--pol` | `THLCH` | Origin port UN/LOCODE |
| `--pod` | `KRPUS` | Destination port UN/LOCODE |
| `--direction` | `O` | `O` = outbound/ETD, `I` = inbound/ETA |
| `--month` | current month | Scrape one month |
| `--months` | — | Scrape a list of months |
| `--start` + `--end` | — | Scrape a contiguous range |
| `--output` | `output/heunga_schedule.csv` | CSV path |
| `--delay` | `1.0` | Seconds between month requests |

**Finding port codes:** open `https://ebiz.heungaline.com/Schedule`, pick
the port in the origin/destination boxes, then read the `pol`/`pod`
hidden input values in dev tools.

---

## Build the dashboard

```
# Combine every CSV in output/ into output/dashboard.html
python Method01-Chrome\heunga_dashboard.py

# Only specific files
python Method01-Chrome\heunga_dashboard.py --files Method01-Chrome\output\lch_pus_h1.csv --output Method01-Chrome\output\h1_dashboard.html
```

Open the resulting HTML in a browser (double-click the file in Explorer).

Dashboard includes: KPI cards, sailings-per-month bars, per-service
breakdown, top-10 vessels, transit-time histogram, terminal breakdowns,
and a filterable + sortable table. Uses Chart.js from CDN, no build
step, no local server.

---

## Typical end-to-end run

```
pip install -r Method01-Chrome\requirements.txt
python Method01-Chrome\heunga_schedule_scraper.py --start 2026-01 --end 2026-06
python Method01-Chrome\heunga_dashboard.py
```

Open `Method01-Chrome\output\dashboard.html` in a browser.

---

## Notes for redistributing

- The `output/` folder is **gitignored** — cloners get the code but not
  the previously-scraped data. They generate their own on first run.
- All defaults are computed from the script's own location, so you can
  run from any working directory (repo root, `Method01-Chrome\`, or
  elsewhere) and outputs still land in `Method01-Chrome\output\`.
- No login or API keys — uses the public web schedule page as a browser
  would.

## Maintenance

The scraper depends on the shape of the `var schedules = [...]` array
embedded in Heung-A's response HTML. If they switch to a JSON API or
change the variable name, `SCHEDULES_START_RE` in
`heunga_schedule_scraper.py` will need updating.
