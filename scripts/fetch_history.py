#!/usr/bin/env python3
"""Fetch every tab of the BLP Friday-report spreadsheet and emit one JSON history file."""
import csv, io, json, re, sys, urllib.request

SHEET_ID = "11RoeVRETag5rZYX6_tEH-rf6x8JL0JeZU0P5AT0WI-I"
GIDS = ["0", "1196540417", "1842144147", "1874855568", "1970629263",
        "2066569220", "226021277", "363134503", "714100223", "88315093", "988732248"]

def fetch(gid):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read().decode("utf-8", "replace")

entries = []
tabs = {}
for gid in GIDS:
    try:
        text = fetch(gid)
    except Exception as e:
        print(f"gid {gid}: FAILED {e}", file=sys.stderr)
        continue
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows) < 2:
        print(f"gid {gid}: empty", file=sys.stderr)
        continue
    header = rows[0]
    dates = header[1:]
    # figure out the year from the first parseable date
    year = None
    for d in dates:
        m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$", d or "")
        if m:
            y = int(m.group(3))
            year = y + 2000 if y < 100 else y
            break
    approx = False
    if year is None:
        # gid 988732248 has no date header; by elimination it is the 2017 tab.
        # Synthesize Friday dates (first Friday of 2017 = Jan 6) and flag approximate.
        if gid == "988732248":
            import datetime
            year, approx = 2017, True
            d0 = datetime.date(2017, 1, 6)
            dates = [(d0 + datetime.timedelta(weeks=i)).strftime("%-m/%-d/%y")
                     for i in range(len(header) - 1)]
            rows = [header] + rows  # no header row: every row is data
        else:
            print(f"gid {gid}: no dates in header", file=sys.stderr)
            continue
    n = 0
    for row in rows[1:]:
        tech = (row[0] or "").strip()
        if not tech:
            continue
        for i, cell in enumerate(row[1:]):
            cell = (cell or "").strip()
            if not cell or cell.upper() in ("N/A", "NA", "-", "—"):
                continue
            d = (dates[i] or "").strip() if i < len(dates) else ""
            m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})$", d)
            if m:
                mo, dy, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                y = y + 2000 if y < 100 else y
                iso = f"{y:04d}-{mo:02d}-{dy:02d}"
            else:
                iso = None
            e = {"tech": tech, "date": iso, "week": d or None,
                 "year": year, "gid": gid, "text": cell}
            if approx:
                e["approx"] = True
            entries.append(e)
            n += 1
    tabs[gid] = {"year": year, "entries": n}
    print(f"gid {gid}: year {year}, {n} entries", file=sys.stderr)

entries.sort(key=lambda e: (e["date"] or f"{e['year']}-00-00", e["tech"]))
out = {"sheetId": SHEET_ID, "generated": "2026-07-16", "tabs": tabs, "entries": entries}
path = sys.argv[1] if len(sys.argv) > 1 else "report-history.json"
with open(path, "w") as f:
    json.dump(out, f, ensure_ascii=False)
print(f"wrote {path}: {len(entries)} entries", file=sys.stderr)
