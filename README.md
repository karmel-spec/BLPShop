# BLP Shop Reports

Brigham Larson Pianos — technician Friday reports webapp. A live view over
the weekly report Google Sheet (technician rows × Friday columns, one tab
per year, 2017–present) that also writes back to it, so the sheet stays the
source of truth.

**Design:** "The Showroom" — matches brighamlarsonpianos.com (piano black,
white, signature red #B43333), with the Ebony & Ivory sidebar, Workbench
week cards, and Ledger-style searchable history.

## What's inside

| View | What it does |
|---|---|
| Shop Dashboard | Who's reported this week, 12-week submission rate per tech, hours logged, latest activity |
| Assignment Planner | Per-technician carry-overs extracted from this week's reports — draft material for next week's calendar assignments |
| My Week | The technician's work-item cards, seeded from last week's carry-overs |
| My Friday Report | Piano chips (deep-linked to the Piano Log app), Completed / Carry-over toggles, notes, per-piano hours, live preview of the sheet text |
| History | Full-text search over every report since 2017 (4,500+), with per-piano summary |
| Pianos | Auto-detected make + serial mentions, hours totals, links to [pianologapp.netlify.app](https://pianologapp.netlify.app/) |
| Calendars | Google Calendar assigned-vs-reported comparison (owner sees all technicians) |

## Run it

It's a static app — serve the repo root any way you like:

```
python3 -m http.server 4180
```

Works immediately with the bundled data snapshot plus a live pull of the
current-year sheet tab. Two optional setup steps (one-click submissions via
Apps Script, Google login + Calendars via an OAuth client ID) are in
[docs/setup.md](docs/setup.md).

## Files

- `index.html` — the whole app (no build step)
- `data/report-history.json` — imported history snapshot (2017–2026); regenerate with `scripts/fetch_history.py`
- `apps-script/Code.gs` — Apps Script web app that writes submissions into the report sheet
- `docs/setup.md` — setup for submissions, Google login, and calendars

This app also ships as a module of the BLP operations mega-app
(`BLPOperationsWebApp/BLPMegaApp03/modules/shop-reports/`); this repo is the
standalone deployment. Work on branches; never commit credentials or
customer data.
