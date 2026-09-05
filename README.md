# Shipping Schedule Scrapers

Two independent methods for pulling container-sailing schedules off Korean
carrier e-services and turning them into a browsable HTML dashboard.

| Method | Carrier | Approach | Speed | Fragility |
|--------|---------|----------|-------|-----------|
| **Method01-Chrome** | Heung-A Line (`ebiz.heungaline.com`) | Direct HTTP with `requests` — reverse-engineered the form POST | Fast (seconds per month) | Low (no browser to maintain) |
| **Method02-Code** | Sinokor (`ebiz.sinokor.co.kr`) | Real Chromium via Playwright — types into the search form and reads the rendered table | Slow (~30 s per route) | Medium (breaks if the site's CSS selectors change) |

Both write their outputs into `<method-folder>/output/`, which is gitignored.

---

## Prerequisites (both methods)

- **Python 3.10 or newer** (Method02 uses `X | None` union syntax).
- **Git** to clone the repo.

Check yours:
```
python --version
```

---

## Method01-Chrome — Heung-A Line (requests-based)

### Install
```
cd Method01-Chrome
pip install -r requirements.txt
```

### Run the scraper
```
# One month
python heunga_schedule_scraper.py --month 2026-01

# Range of months
python heunga_schedule_scraper.py --start 2026-01 --end 2026-06

# Different route (Busan -> Laem Chabang, inbound view)
python heunga_schedule_scraper.py --pol KRPUS --pod THLCH --direction I \
    --start 2026-01 --end 2026-03 --output output/busan_lch_inbound.csv
```

Every CSV lands in `Method01-Chrome/output/`.

### Build the dashboard
```
python heunga_dashboard.py
```

Reads every CSV in `output/`, dedupes across files, and writes
`output/dashboard.html` — one self-contained HTML file (Chart.js from CDN,
no build step). Open it in any browser.

---

## Method02-Code — Sinokor (Playwright-based)

### Install
```
cd Method02-Code
pip install -r requirements.txt
python -m playwright install chromium
```

The second command downloads the ~150 MB Chromium binary Playwright drives.
It only needs to happen once per machine.

### Run the scraper
```
# One route per --routes entry. Names are matched against the site's
# own autocomplete, so full port names are safest.
python daily_schedule_scraper.py \
    --routes "LAEM CHABANG->BUSAN" "BANGKOK->BUSAN"
```

Each route produces one `.xlsx` in `Method02-Code/output/schedule-daily/`,
timestamped with today's date so daily runs stack up. If a step times out,
a screenshot lands in `output/schedule-daily/_errors/` and the script moves
on to the next route.

### Build the dashboards
```
# Interactive HTML dashboard (open in browser)
python build_dashboard_html.py

# Excel workbook with charts
python build_dashboard.py
```

Both read every `.xlsx` in `output/schedule-daily/` and write into
`Method02-Code/output/`.

---

## Notes for redistributing

- The `output/` folders are **gitignored** — cloners get the code but not
  the previously-scraped data. They generate their own on first run.
- All defaults are computed from each script's own location, so you can
  run them from any working directory (repo root, method folder, or
  elsewhere) and outputs still land in the right place.
- Neither carrier requires login or API keys. Both scrapers use the public
  web schedule pages as a real browser would.

## Maintenance

Method02's Playwright selectors were verified against the live Sinokor
DOM on 2026-09-06. If Sinokor redesigns the schedule page, the selectors
listed at the top of `daily_schedule_scraper.py` will need re-verifying
against the new DOM.

Method01 depends on the shape of the `var schedules = [...]` array
embedded in Heung-A's response HTML. If they switch to a JSON API or
change the variable name, `SCHEDULES_START_RE` in
`heunga_schedule_scraper.py` will need updating.
