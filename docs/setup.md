# Shop Reports module — setup

The module at this repo replaces the weekly technician report
spreadsheet with a webapp, while continuing to **read from and write to that
same spreadsheet** — no data migration, and Brigham's existing sheet keeps
working exactly as before.

Spreadsheet: `11RoeVRETag5rZYX6_tEH-rf6x8JL0JeZU0P5AT0WI-I`
(technician rows × Friday-date columns, one tab per year, 2017–2026).

## Works out of the box (no setup)

- **Dashboard** — who has / hasn't reported this week, per-tech submission
  rate over the last 12 weeks, latest activity. Data comes live from the
  public sheet (gviz CSV), with a bundled snapshot
  (`data/report-history.json`, 4,538 entries) as fallback.
- **History** — full-text search over every report since 2017, filterable by
  technician and year.
- **Pianos** — auto-detected make + serial mentions with per-piano work
  timelines, cross-linked to the Piano Log module.
- **Friday Report portal** — piano chips (with ↗ links into the Piano Log
  module) and "+ add piano"; per-piano work items with **Completed / Carry
  over** toggles, notes, and an **hours tracker**; a live preview of the exact
  text that lands on the sheet; autosaving drafts; "Copy for spreadsheet"
  fallback until step 1 below is done.
- **My Week** — Workbench-style cards of the technician's work items (seeded
  from last week's carry-overs), status-synced with the Friday report.
- **Assignment Planner** — for Brigham: per-technician carry-overs extracted
  from this week's reports (falling back to last week's) as draft material for
  next week's calendar assignments, with a copy-full-plan button. Fills in
  live as Friday reports arrive.
- **Hour tracking** — "N hrs" is parsed from report text (new reports write it
  in a consistent format), totaled per piano on the Pianos tab and dashboard.

## Step 1 — Enable one-click submission (Apps Script, ~5 min)

1. Open the report spreadsheet → **Extensions → Apps Script**.
2. Paste the contents of `apps-script/Code.gs`
   into `Code.gs` and save.
3. (Recommended) **Project Settings → Script Properties** → add
   `SHARED_SECRET` = a long random string.
4. **Deploy → New deployment → Web app**, Execute as **Me**, access
   **Anyone**. Copy the `/exec` URL.
5. In `index.html`, set `CONFIG.APPS_SCRIPT_URL` to that
   URL. Submissions now append into the correct (tech row, Friday column)
   cell — never overwriting existing text.

## Step 2 — Google login + Calendar comparison

1. In [Google Cloud Console](https://console.cloud.google.com/), create an
   OAuth 2.0 **Web application** client. Add the Netlify domain (and
   `http://localhost:4180` for dev) to authorized JavaScript origins.
2. Set `CONFIG.GOOGLE_CLIENT_ID` in `index.html`.

Once the client ID is set, the sidebar's name picker is replaced by a
**Sign in with Google** button:
- A technician signing in is matched to their technician row automatically
  (given name or email prefix vs. the roster) and lands in their own view.
- Owner accounts (brighamlarson@gmail.com, brigham@/walter@/karmel@
  brighamlarsonpianos.com — the `OWNERS` list in index.html) get the Owner
  role plus an "Acting as technician" picker to see any tech's screens.
- Unmatched accounts are asked to pick their technician name once.
The picker remains as the fallback while `GOOGLE_CLIENT_ID` is blank, so the
app works today.
3. On the Calendars tab, **Connect Google Calendar**:
   - Signed in as an owner account that has all technician calendars
     connected (brighamlarson@gmail.com or walter@brighamlarsonpianos.com),
     the app matches calendars to the roster by name and shows **every
     technician's Mon–Fri assignments** against their reports.
   - Signed in as a technician, it shows their own primary calendar.
   Events whose words never appear in the report are flagged "Not in report."

Scope used: `calendar.readonly` only. Nothing is written to calendars.

## Refresh the bundled history snapshot

The snapshot only matters as an offline/CORS fallback; regenerate it
occasionally (or before deploys) by re-running the import script against the
sheet — it fetches every year tab's CSV export and rewrites
`data/report-history.json`.

## Notes / conventions

- The 2017 tab has no date header row; its entries carry synthesized Friday
  dates and are flagged `approx` (shown as "approx. week" in search results).
- "Active technician" = anyone with a report in the last 8 weeks or any entry
  this year (`CONFIG.ACTIVE_WEEKS`).
- Never commit credentials; the Apps Script secret lives in Script
  Properties, not in the repo.
