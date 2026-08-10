"""Download FAA Form 127 (Operating and Financial Summary) bulk CSVs for FY2023
and FY2024, and build data/airport_financials.csv.

Source: FAA CATS (Certification Activity Tracking System), cats.airports.faa.gov.
No API - a ColdFusion form, but simpler than BTS T-100's ASP.NET viewstate flow:
the "Individual Airports" search form (fields: year, yearToCompare, region,
state, loc_id, airportID, exportToCSV) POSTs to /reports/form_127/. Its own
page copy says the airport field is "Required unless exporting to CSV" -
confirmed live 2026-08-10: a GET with exportToCSV=true and every other field
left empty returns a bulk CSV of EVERY airport that filed for that year, not
just one. No hidden tokens/session needed beyond a cookie jar (site sets
AWSALB* cookies but a fresh request without them also works - kept for
politeness, not because it's required).

Confirmed live: https://cats.airports.faa.gov/reports/form_127/
    ?year={YEAR}&yearToCompare=&region=&state=&loc_id=&airportID=&exportToCSV=true

The "All Airports" report (form_127_all_airports/) is a NATIONAL ROLLUP (one
row per line-item, one column per year) - not per-airport data. Do not use it
for this table; it was the first thing tried and is a dead end for this
purpose (kept working for the differentiator's national-context framing, not
for per-airport rows).

Column mapping (raw CSV -> table, 0-indexed positions in the 83-column
export, confirmed live 2026-08-10 - re-verify if FAA changes the form,
column order is not guaranteed stable across form versions):
    0  Year          -> fy
    4  Location ID   -> locid
    32 Total Operating Revenue  -> op_revenue
    41 Total Operating Expenses -> op_expenses
    73 Enplanements  -> enplanements
net_rev_per_enplanement = (op_revenue - op_expenses) / enplanements, computed
here (not by FAA) - NULL when enplanements is 0/blank (a real "can't compute"
case, not a zero).

Usage: uv run python ingestion/build_faa_form127.py
"""

import csv
import io
from pathlib import Path
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
OUT_PATH = REPO_ROOT / "data" / "airport_financials.csv"

URL_TEMPLATE = (
    "https://cats.airports.faa.gov/reports/form_127/"
    "?year={year}&yearToCompare=&region=&state=&loc_id=&airportID=&exportToCSV=true"
)
YEARS = (2023, 2024)

COL_YEAR = 0
COL_LOCID = 4
COL_OP_REVENUE = 32
COL_OP_EXPENSES = 41
COL_ENPLANEMENTS = 73

OUT_FIELDS = ["locid", "fy", "op_revenue", "op_expenses", "enplanements",
              "net_rev_per_enplanement"]


def raw_path(year: int) -> Path:
    return RAW_DIR / f"form127_{year}.csv"


def download_year(year: int) -> None:
    dest = raw_path(year)
    if dest.exists() and dest.stat().st_size > 10_000:
        print(f"  {year}: already have {dest.name} ({dest.stat().st_size:,} bytes)")
        return
    url = URL_TEMPLATE.format(year=year)
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    })
    with urlopen(req, timeout=120) as resp:
        content = resp.read()
    if b"Location ID" not in content[:5000]:
        raise RuntimeError(f"{year}: response doesn't look like the expected CSV "
                            f"(missing 'Location ID' header) - form may have changed")
    dest.write_bytes(content)
    print(f"  {year}: downloaded {dest.name} ({len(content):,} bytes)")


def parse_year(year: int) -> list[dict]:
    text = raw_path(year).read_text(encoding="utf-8")
    # First two lines are a title + timestamp, third is blank, header is line 4.
    lines = text.splitlines()
    header_idx = next(i for i, l in enumerate(lines) if l.startswith('"Year"'))
    reader = csv.reader(lines[header_idx:])
    header = next(reader)
    assert header[COL_LOCID] == "Location ID", header[COL_LOCID]
    assert header[COL_OP_REVENUE] == "Total Operating Revenue", header[COL_OP_REVENUE]
    assert header[COL_OP_EXPENSES] == "Total Operating Expenses", header[COL_OP_EXPENSES]
    assert header[COL_ENPLANEMENTS] == "Enplanements", header[COL_ENPLANEMENTS]

    def num(s: str):
        s = s.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None

    rows = []
    seen = set()
    duplicates = 0
    for row in reader:
        if len(row) <= COL_ENPLANEMENTS:
            continue
        locid = row[COL_LOCID].strip()
        fy = row[COL_YEAR].strip()
        if not locid or not fy:
            continue
        key = (locid, fy)
        if key in seen:
            # FAA CATS export has occasional exact-duplicate filing rows for
            # the same (locid, fy) - confirmed live 2026-08-10 (DBQ/2023).
            # Consistent with GAO-26-107938 "FAA Should Implement Controls
            # to Improve Data Quality". Keep first occurrence, drop the rest.
            duplicates += 1
            continue
        seen.add(key)
        op_revenue = num(row[COL_OP_REVENUE])
        op_expenses = num(row[COL_OP_EXPENSES])
        enplanements = num(row[COL_ENPLANEMENTS])
        net_rev_per_enplanement = None
        if op_revenue is not None and op_expenses is not None and enplanements:
            net_rev_per_enplanement = round((op_revenue - op_expenses) / enplanements, 2)
        rows.append({
            "locid": locid, "fy": int(fy),
            "op_revenue": op_revenue, "op_expenses": op_expenses,
            "enplanements": enplanements,
            "net_rev_per_enplanement": net_rev_per_enplanement,
        })
    if duplicates:
        print(f"  WARN: {duplicates} duplicate (locid, fy) row(s) dropped (kept first)")
    return rows


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    all_rows = []
    for year in YEARS:
        download_year(year)
        rows = parse_year(year)
        print(f"  {year}: {len(rows)} airport financial reports")
        all_rows.extend(rows)

    all_rows.sort(key=lambda r: (r["fy"], r["locid"]))
    with open(OUT_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"Wrote {OUT_PATH}: {len(all_rows)} rows")


if __name__ == "__main__":
    main()
