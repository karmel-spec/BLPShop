/**
 * BLP Shop Reports — Apps Script backend
 * Writes technician Friday reports into the weekly report spreadsheet
 * (the same sheet Brigham already uses), and serves history as JSON.
 *
 * SETUP (one time, ~5 minutes — full steps in docs/shop-reports-setup.md):
 *  1. Open the report spreadsheet → Extensions → Apps Script.
 *  2. Paste this file's contents into Code.gs.
 *  3. Project Settings → Script Properties → add SHARED_SECRET with a long
 *     random value (optional but recommended).
 *  4. Deploy → New deployment → Web app → Execute as: Me,
 *     Who has access: Anyone. Copy the /exec URL.
 *  5. Paste the URL into CONFIG.APPS_SCRIPT_URL in modules/shop-reports/index.html
 *     (and the secret into the request if you set one).
 */

var SHEET_ID = "11RoeVRETag5rZYX6_tEH-rf6x8JL0JeZU0P5AT0WI-I";

function doPost(e) {
  var out;
  try {
    var body = JSON.parse(e.postData.contents);
    var secret = PropertiesService.getScriptProperties().getProperty("SHARED_SECRET");
    if (secret && body.secret !== secret) throw new Error("bad secret");
    if (body.action !== "submit") throw new Error("unknown action");
    out = submitReport(String(body.tech || ""), String(body.date || ""), String(body.text || ""));
  } catch (err) {
    out = { ok: false, error: String(err && err.message || err) };
  }
  return ContentService.createTextOutput(JSON.stringify(out))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * Append `text` to the cell at (tech row, friday-date column) on the
 * current-year tab. Creates the tech row / date column if missing.
 * Never overwrites: existing cell content is preserved and appended to.
 */
function submitReport(tech, dateISO, text) {
  if (!tech) throw new Error("missing tech");
  if (!text) throw new Error("missing text");
  var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateISO);
  if (!m) throw new Error("bad date: " + dateISO);
  var year = m[1];
  var label = Number(m[2]) + "/" + Number(m[3]) + "/" + year.slice(2); // 7/17/26

  var ss = SpreadsheetApp.openById(SHEET_ID);
  var sheet = findYearSheet_(ss, year);
  if (!sheet) throw new Error("no tab found for year " + year);

  // find the date column on row 1
  var header = sheet.getRange(1, 1, 1, Math.max(sheet.getLastColumn(), 2)).getDisplayValues()[0];
  var col = -1;
  for (var c = 1; c < header.length; c++) {
    if (normDate_(header[c]) === normDate_(label)) { col = c + 1; break; }
  }
  if (col === -1) { col = header.length + 1; sheet.getRange(1, col).setValue(label); }

  // find the technician row in column A
  var names = sheet.getRange(1, 1, Math.max(sheet.getLastRow(), 2), 1).getDisplayValues();
  var row = -1;
  for (var r = 1; r < names.length; r++) {
    if (String(names[r][0]).trim().toLowerCase() === tech.trim().toLowerCase()) { row = r + 1; break; }
  }
  if (row === -1) { row = names.length + 1; sheet.getRange(row, 1).setValue(tech); }

  var cell = sheet.getRange(row, col);
  var existing = String(cell.getDisplayValue() || "").trim();
  var isPlaceholder = existing === "" || /^n\/?a$/i.test(existing);
  cell.setValue(isPlaceholder ? text : existing + "\n\n" + text);
  return { ok: true, appended: !isPlaceholder, row: row, col: col, sheet: sheet.getName() };
}

/** GET ?action=history returns every tab as JSON (webapp fallback data source). */
function doGet(e) {
  var action = e && e.parameter && e.parameter.action;
  var out;
  if (action === "history") {
    var ss = SpreadsheetApp.openById(SHEET_ID);
    out = ss.getSheets().map(function (sh) {
      return { name: sh.getName(), gid: sh.getSheetId(), values: sh.getDataRange().getDisplayValues() };
    });
  } else {
    out = { ok: true, service: "blp-shop-reports", time: new Date().toISOString() };
  }
  return ContentService.createTextOutput(JSON.stringify(out))
    .setMimeType(ContentService.MimeType.JSON);
}

/** Match a tab to the year: prefer a tab literally named the year, else a tab
 *  whose first dated header cell ends in that year. */
function findYearSheet_(ss, year) {
  var sheets = ss.getSheets();
  for (var i = 0; i < sheets.length; i++) {
    if (sheets[i].getName().indexOf(year) !== -1) return sheets[i];
  }
  var yy = year.slice(2);
  for (var j = 0; j < sheets.length; j++) {
    var hdr = sheets[j].getRange(1, 2, 1, 5).getDisplayValues()[0].join(" ");
    if (new RegExp("/" + yy + "\\b").test(hdr) || new RegExp("/" + year + "\\b").test(hdr)) return sheets[j];
  }
  return null;
}

function normDate_(s) {
  var m = /^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/.exec(String(s || "").trim());
  if (!m) return null;
  var y = m[3].length === 2 ? "20" + m[3] : m[3];
  return Number(m[1]) + "/" + Number(m[2]) + "/" + y;
}
