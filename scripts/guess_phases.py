#!/usr/bin/env python3
"""Best-guess the CURRENT PHASE (col DO) for every active piano in the Piano Log.

Fills only pianos whose phase cell is blank — never overwrites a phase a human
(or the Shop Manager app) already set. Combines four evidence sources, roughly
strongest-first:

  1. Section the piano sits in on the Piano Log (showroom → For Sale, pre-sale →
     In Queue, NEW/QUESTIONS → New Arrival, consignment-on-hold → Paused, and the
     shop sections → an actual pipeline phase).
  2. The KEYWORK…QC progress columns (AZ–BG): the first in-progress milestone,
     or the next empty one after the completed ones.
  3. The most recent Friday report mentioning that serial (keyword → phase); a
     report newer than the progress columns wins, since the columns lag.
  4. The refinishing queue sheet.

Dry-run by default; pass --write to push to the sheet.

    python3 scripts/guess_phases.py            # preview a summary + per-row table
    python3 scripts/guess_phases.py --write     # write blanks in DO6:DO400

Requires the `gog` CLI authenticated for an account with edit access to the
Piano Log (e.g. karmel@brighamlarsonpianos.com).
"""
import argparse, csv, datetime, io, json, re, subprocess, sys, urllib.request

PLOG_ID = "1ZunbPKygpQlcXfTyPowDHdUE9spJ3uV1XA4iX1eoKRc"
REPORT_ID = "11RoeVRETag5rZYX6_tEH-rf6x8JL0JeZU0P5AT0WI-I"
REPORT_2026_GID = "1842144147"
REFINISH_ID = "1bfF4pmuGv7TefVlDG4lo_04gRjiX9QYerK4o9qih6kc"
ACCOUNT = "karmel@brighamlarsonpianos.com"

FIRST_ROW = 6          # data starts at sheet row 6
LAST_ROW = 400         # just above the SOLD divider — active inventory only
PHASE_COL = "DO"

# --- Piano Log section name -> handling -------------------------------------
FORSALE_SECS = {"SHOWROOM", "USED SHOWROOM", "GRAND PIANOS", "REBUILT UPRIGHT ANTIQUE",
    "UPRIGHT PIANOS", "USED VESTIBULE SHOWROOM", "BALCONY SHOWROOM", "CONSIGNMENT SHOWROOM",
    "NEW SHOWROOM", "NEW GRAND PIANOS", "NEW UPRIGHT PIANOS", "NEW VESTIBULE", "NEW", "USED"}
SHOP_SECS = {"CUSTOM SHOPWORK", "JANE LARSEN", "CURRENT SHOPWORK (SPEC)",
    "CURTIS HARPER'S SHOP", "JULIO'S SHOP", "TECHNOLOGY SHOP & QUEUE (TECH ON DECK)"}
QUEUE_SECS = {"PRE-SALE BALCONY SHOWROOM", "PRE-SALE RENTALS", "PRE-SALE HOLDING ROOM"}
PAUSE_SECS = {"CONSIGNMENT ON HOLD"}
NEWARR_SECS = {"NEW / QUESTIONS"}
# everything else (storage, rentals, residences) gets no pipeline phase

# progress columns AZ..BG in order, mapped to the phase they represent
PROG_COLS = [("KEYWORK", "CAP"), ("CAP", "CAP"), ("SOUNDBOARD/BRIDGE", "PRSB"),
    ("RESTRINGING", "PRSB"), ("DHRT", "DHRT"), ("REFINISHING", "Refinishing"),
    ("PLATING", "Final Assembly"), ("QC", "QC")]
ORDER = {"Assessment": -2, "Teardown": -1, "PRSB": 0, "CAP": 1, "Refinishing": 2,
         "Final Assembly": 3, "DHRT": 4, "Tuning": 5, "QC": 6}
DONE_RE = re.compile(r"done|✓|√|n[\\/]?a|complete|^x$", re.I)


def gog_get(sheet_id, rng):
    out = subprocess.run(["gog", "-a", ACCOUNT, "--json", "sheets", "get", sheet_id, rng],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out).get("values", [])


def cell(rows, i, j=0):
    r = rows[i] if i < len(rows) else []
    return (r[j] if len(r) > j else "").strip()


def kw_phase(text):
    s = text.lower()
    if re.search(r"dhrt|regulat|voic", s): return "DHRT"
    if re.search(r"restring|prsb|soundboard|bridge|pinblock|downbearing|belly", s): return "PRSB"
    if re.search(r"refinish|lacquer|stain|sanding|sprayed|filler|buff", s): return "Refinishing"
    if re.search(r"assembl", s): return "Final Assembly"
    if re.search(r"\bcap\b|action prep|hammer|keytop|keys\b", s): return "CAP"
    if re.search(r"teardown|tear down", s): return "Teardown"
    if re.search(r"\btun(e|ed|ing)\b", s): return "Tuning"
    if re.search(r"\bqc\b|quality", s): return "QC"
    if re.search(r"assess", s): return "Assessment"
    return None


def load_report_index():
    """serial -> (latest date, snippet around the mention). History snapshot + live 2026."""
    entries = []
    try:
        hist = json.load(open("data/report-history.json"))
        entries = [e for e in hist["entries"] if e.get("date") and e.get("year") != 2026]
    except Exception:
        pass
    try:
        url = (f"https://docs.google.com/spreadsheets/d/{REPORT_ID}"
               f"/gviz/tq?tqx=out:csv&gid={REPORT_2026_GID}")
        rows = list(csv.reader(io.StringIO(
            urllib.request.urlopen(url, timeout=30).read().decode())))
        dates = rows[0][1:]
        for r in rows[1:]:
            tech = (r[0] or "").strip()
            if not tech:
                continue
            for i, c in enumerate(r[1:]):
                c = (c or "").strip()
                if not c or re.fullmatch(r"n/?a", c, re.I):
                    continue
                m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", (dates[i] or "").strip())
                if not m:
                    continue
                y = ("20" + m.group(3)) if len(m.group(3)) == 2 else m.group(3)
                entries.append({"date": f"{y}-{int(m.group(1)):02d}-{int(m.group(2)):02d}",
                                "text": c})
    except Exception as ex:
        print(f"(live report refresh failed: {ex})", file=sys.stderr)
    rep = {}
    serial_re = re.compile(r"\b(\d{4,7})\b")
    for e in sorted(entries, key=lambda e: e["date"]):
        for m in serial_re.finditer(e["text"]):
            i = m.start()
            rep[m.group(1)] = (e["date"], e["text"][max(0, i - 120):i + 200])
    return rep


def load_refinish():
    serials = set()
    try:
        url = f"https://docs.google.com/spreadsheets/d/{REFINISH_ID}/gviz/tq?tqx=out:csv&gid=0"
        for r in csv.reader(io.StringIO(urllib.request.urlopen(url, timeout=30).read().decode())):
            if len(r) > 2 and re.fullmatch(r"\d{3,8}", (r[2] or "").strip()):
                serials.add(r[2].strip())
    except Exception as ex:
        print(f"(refinish sheet fetch failed: {ex})", file=sys.stderr)
    return serials


def guess():
    end = f"{LAST_ROW}"
    main = gog_get(PLOG_ID, f"'Piano Log'!A{FIRST_ROW}:X{end}")
    prog = gog_get(PLOG_ID, f"'Piano Log'!AZ{FIRST_ROW}:BG{end}")
    exitp = gog_get(PLOG_ID, f"'Piano Log'!CP{FIRST_ROW}:CP{end}")
    phase = gog_get(PLOG_ID, f"'Piano Log'!{PHASE_COL}{FIRST_ROW}:{PHASE_COL}{end}")
    rep = load_report_index()
    refin = load_refinish()
    recent_cut = (datetime.date.today() - datetime.timedelta(days=120)).isoformat()

    cur = None
    props = {}   # sheet row -> (phase, reason, label)
    for i in range(len(main)):
        b, c, d = cell(main, i, 1), cell(main, i, 2), cell(main, i, 3)
        if b and not c and not d and len(b) < 45:
            cur = re.sub(r"\s+", " ", b).strip().upper()
            continue
        if not c or cur is None or cell(phase, i):
            continue   # no serial, no section, or already has a phase
        status = cell(main, i, 18)
        label = re.sub(r"\s+", " ", f"{cell(main, i, 5)} {c}")[:40]
        row = FIRST_ROW + i
        sold = "sold" in status.lower() and "for sale" not in status.lower()
        ph = why = None
        if cur in PAUSE_SECS:
            ph, why = "Paused", "consignment on hold"
        elif cur in NEWARR_SECS:
            ph, why = "New Arrival", "NEW/QUESTIONS section"
        elif cur in FORSALE_SECS:
            ph, why = ("Admin Exit Prep", "sold / exit prep") if (sold or cell(exitp, i)) \
                else ("For Sale", "showroom section")
        elif cur in QUEUE_SECS:
            ph, why = "In Queue", "pre-sale queue"
        elif cur in SHOP_SECS:
            m = re.search(r"\d{4,8}", c)
            digits = m.group(0) if m else ""
            inprog, done, empty = [], [], []
            for j, (_, p) in enumerate(PROG_COLS):
                v = cell(prog, i, j)
                if not v or v.lower() == "assigned":
                    empty.append(p)
                elif DONE_RE.search(v):
                    done.append(p)
                else:
                    inprog.append(p)
            r2 = rep.get(digits)
            repph = kw_phase(r2[1]) if (r2 and r2[0] >= recent_cut) else None
            if cell(exitp, i) or ("QC" in done and "QC" not in inprog):
                ph, why = "Admin Exit Prep", "QC/exit prep marked"
            elif inprog:
                ph, why = sorted(inprog, key=lambda p: ORDER[p])[0], "progress col in work"
            elif done:
                nxt = sorted(set(empty), key=lambda p: ORDER[p])
                ph, why = (nxt[0], "next after completed cols") if nxt \
                    else ("Admin Exit Prep", "all cols done")
            elif repph:
                ph, why = repph, f"report {r2[0]}"
            elif r2 and r2[0] >= recent_cut:
                ph, why = "Assessment", f"mentioned {r2[0]}, no keywords"
            elif digits in refin:
                ph, why = "Refinishing", "refinishing queue"
            else:
                ph, why = "In Queue", "no recent activity"
            # a fresher report that is further along overrides lagging columns
            if repph and ORDER.get(repph, -9) > ORDER.get(ph, -9):
                ph, why = repph, f"report {r2[0]} (later than cols)"
            if ph == "In Queue" and digits in refin:
                ph, why = "Refinishing", "refinishing queue"
        else:
            continue
        props[row] = (ph, why, label)
    return props


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write to the sheet (else dry-run)")
    args = ap.parse_args()

    props = guess()
    from collections import Counter
    tally = Counter(v[0] for v in props.values())
    print(f"{sum(tally.values())} pianos would be filled: {dict(tally)}\n")
    for row in sorted(props):
        ph, why, label = props[row]
        print(f"  r{row:<4d} {label:42s} {ph:16s} {why}")

    if not args.write:
        print("\nDry run — pass --write to push to the sheet.")
        return
    existing = guess_existing()   # rows a human already filled — keep verbatim
    col = [[existing.get(row) or props.get(row, ("",))[0]]
           for row in range(FIRST_ROW, LAST_ROW + 1)]
    rng = f"'Piano Log'!{PHASE_COL}{FIRST_ROW}:{PHASE_COL}{LAST_ROW}"
    subprocess.run(["gog", "-a", ACCOUNT, "sheets", "update", PLOG_ID, rng,
                    "--values-json", json.dumps(col), "--input", "RAW", "-y"], check=True)
    print(f"\nWrote {rng}.")


def guess_existing():
    """Existing phase values keyed by row, so --write never clobbers them."""
    phase = gog_get(PLOG_ID, f"'Piano Log'!{PHASE_COL}{FIRST_ROW}:{PHASE_COL}{LAST_ROW}")
    out = {}
    for i, r in enumerate(phase):
        v = (r[0] if r else "").strip()
        if v:
            out[FIRST_ROW + i] = v
    return out


if __name__ == "__main__":
    main()
