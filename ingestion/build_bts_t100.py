"""Download BTS T-100 Segment (All Carriers) data for 2023-2025 and build
data/bts_t100.csv.

No static prezip URL exists for current-year T-100 data (unlike on-time
performance). The selection UI at DL_SelectFields.aspx is a classic ASP.NET
WebForms page: GET it, harvest the __VIEWSTATE/__VIEWSTATEGENERATOR/
__EVENTVALIDATION hidden fields, POST back with year/period/geography
selections. Confirmed live 2026-08-10: cboYear=<year>, cboPeriod=All,
cboGeography=All in ONE request returns a zip covering all 12 months AND
domestic+international together (DATA_SOURCE values DU/DF/IU/IF all present) -
no need for 36 separate requests or a domestic/international split.

CLASS filter: T-100's CLASS field distinguishes scheduled passenger service
(F) from scheduled all-cargo (G), nonscheduled cargo (P), and nonscheduled/
charter passenger (L). Verified on the real 2023 file: CLASS=F carries 1.06B
of ~1.07B total passengers (99.6%) across 9.3M departures; CLASS=G carries
601K departures on only 249 total passengers (bulk cargo, no passenger
relevance) - including it would inject cargo-only departure volume into
long_haul_pct / flight-growth for cargo-heavy airports (e.g. ANC) with no
passenger signal to justify it. Filtered to CLASS='F' only, consistent with
data/airports.csv's own scheduled_service scoping.

Origin filter: kept only if ORIGIN is one of the ~679 tracked airports in
data/airports.csv. v_airport_metrics measures activity as origin-based
segments (see db/views.sql), so a row only matters if its origin is tracked;
the destination can be anything (a foreign airport, a small non-tracked US
field) and still correctly counts as outbound activity FROM the tracked
origin. This does not undercount inbound international service: carriers
serving a tracked US airport from abroad also report the reverse (outbound)
leg from that same US airport, which survives this filter on its own row.

Grain: raw rows are year/month/origin/dest/carrier/AIRCRAFT_TYPE (a carrier
flying two aircraft types on the same route in the same month reports two
rows). Our schema has no aircraft_type column, so duplicates are SUMMED into
one (year, month, origin, dest, carrier) row; distance_miles takes MAX across
duplicates (physically the same route - should already be identical, MAX is
just a defensive tie-break).

Usage: uv run --with requests python ingestion/build_bts_t100.py
(requests is NOT added to pyproject.toml - ad-hoc via --with, since that file
is owned by the parallel agent-backend worker on this repo.)
"""

import csv
import io
import re
import zipfile
from collections import defaultdict
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
AIRPORTS_CSV = REPO_ROOT / "data" / "airports.csv"
OUT_PATH = REPO_ROOT / "data" / "bts_t100.csv"

FORM_URL = (
    "https://www.transtats.bts.gov/DL_SelectFields.aspx"
    "?gnoyr_VQ=FMG&QO_fu146_anzr=Nv4%20Pn44vr45"
)
HIDDEN_FIELDS = ["__EVENTTARGET", "__EVENTARGUMENT", "__LASTFOCUS",
                 "__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"]
DATA_FIELDS = [
    "ORIGIN_AIRPORT_ID", "ORIGIN_AIRPORT_SEQ_ID", "ORIGIN_CITY_MARKET_ID", "ORIGIN",
    "ORIGIN_CITY_NAME", "ORIGIN_STATE_ABR", "ORIGIN_STATE_FIPS", "ORIGIN_STATE_NM",
    "ORIGIN_COUNTRY", "ORIGIN_COUNTRY_NAME", "ORIGIN_WAC",
    "DEST_AIRPORT_ID", "DEST_AIRPORT_SEQ_ID", "DEST_CITY_MARKET_ID", "DEST",
    "DEST_CITY_NAME", "DEST_STATE_ABR", "DEST_STATE_FIPS", "DEST_STATE_NM",
    "DEST_COUNTRY", "DEST_COUNTRY_NAME", "DEST_WAC",
    "AIRCRAFT_GROUP", "AIRCRAFT_TYPE", "AIRCRAFT_CONFIG",
    "YEAR", "QUARTER", "MONTH",
    "DISTANCE_GROUP", "CLASS", "DATA_SOURCE",
    "UNIQUE_CARRIER", "AIRLINE_ID", "UNIQUE_CARRIER_NAME", "UNIQUE_CARRIER_ENTITY",
    "REGION", "CARRIER", "CARRIER_NAME", "CARRIER_GROUP", "CARRIER_GROUP_NEW",
    "DEPARTURES_SCHEDULED", "DEPARTURES_PERFORMED", "PAYLOAD", "SEATS", "PASSENGERS",
    "FREIGHT", "MAIL", "DISTANCE", "RAMP_TO_RAMP", "AIR_TIME",
]
YEARS = (2023, 2024, 2025)


def zip_path(year: int) -> Path:
    return RAW_DIR / f"t100_segment_{year}.zip"


def is_complete(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 1_000_000:
        return False
    try:
        return zipfile.is_zipfile(path)
    except OSError:
        return False


def extract_hidden(html: str) -> dict:
    vals = {}
    for name in HIDDEN_FIELDS:
        m = re.search(r'id="%s"\s+value="([^"]*)"' % re.escape(name), html)
        if not m:
            m = re.search(r'name="%s"[^>]*value="([^"]*)"' % re.escape(name), html)
        vals[name] = m.group(1) if m else ""
    return vals


def download_year(year: int) -> None:
    dest = zip_path(year)
    if is_complete(dest):
        print(f"  {year}: already have {dest.name} ({dest.stat().st_size:,} bytes)")
        return

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    })
    r1 = sess.get(FORM_URL, timeout=60)
    r1.raise_for_status()

    payload = extract_hidden(r1.text)
    payload["cboGeography"] = "All"
    payload["cboYear"] = str(year)
    payload["cboPeriod"] = "All"
    for f in DATA_FIELDS:
        payload[f] = "on"
    payload["chkAllVars"] = "on"
    payload["chkDownloadZip"] = "on"
    payload["btnDownload"] = "Download"

    print(f"  {year}: submitting form (viewstate_len={len(payload.get('__VIEWSTATE', ''))})...")
    r2 = sess.post(FORM_URL, data=payload, timeout=300,
                    headers={"Referer": FORM_URL, "Origin": "https://www.transtats.bts.gov"})
    r2.raise_for_status()
    if r2.content[:4] != b"PK\x03\x04":
        raise RuntimeError(
            f"{year}: response is not a zip ({len(r2.content)} bytes) - form fields "
            f"may have changed, inspect the response manually"
        )
    dest.write_bytes(r2.content)
    print(f"  {year}: downloaded {dest.name} ({len(r2.content):,} bytes)")


def load_tracked_airports() -> set:
    with open(AIRPORTS_CSV, encoding="utf-8", newline="") as f:
        return {row["iata"] for row in csv.DictReader(f)}


def aggregate(tracked: set) -> dict:
    agg = defaultdict(lambda: [0, 0, 0, 0.0])  # passengers, seats, departures, max_distance
    for year in YEARS:
        zpath = zip_path(year)
        if not is_complete(zpath):
            print(f"  WARN: {zpath.name} missing/incomplete, skipping {year}")
            continue
        with zipfile.ZipFile(zpath) as zf:
            candidates = [n for n in zf.namelist()
                          if n.upper() == "T_T100_SEGMENT_ALL_CARRIER.CSV"]
            if not candidates:
                print(f"  WARN {year}: expected data CSV not found in {zpath.name}, "
                      f"members={zf.namelist()}, skipping")
                continue
            with zf.open(candidates[0]) as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))
                rows_in = 0
                rows_kept = 0
                for row in reader:
                    rows_in += 1
                    if row["CLASS"] != "F" or row["ORIGIN"] not in tracked:
                        continue
                    rows_kept += 1
                    key = (int(row["YEAR"]), int(row["MONTH"]), row["ORIGIN"],
                           row["DEST"], row["UNIQUE_CARRIER"])
                    bucket = agg[key]
                    bucket[0] += int(float(row["PASSENGERS"]))
                    bucket[1] += int(float(row["SEATS"]))
                    bucket[2] += int(float(row["DEPARTURES_PERFORMED"]))
                    bucket[3] = max(bucket[3], float(row["DISTANCE"]))
        print(f"  {year}: {rows_in} raw rows -> {rows_kept} kept (CLASS=F, origin tracked)")
    return agg


def write_csv(agg: dict) -> int:
    rows = []
    for (year, month, origin, dest, carrier), (pax, seats, deps, dist) in agg.items():
        rows.append({
            "year": year, "month": month, "origin_iata": origin, "dest_iata": dest,
            "carrier": carrier, "passengers": pax, "seats": seats, "departures": deps,
            "distance_miles": dist,
        })
    rows.sort(key=lambda r: (r["year"], r["month"], r["origin_iata"], r["dest_iata"], r["carrier"]))
    fields = ["year", "month", "origin_iata", "dest_iata", "carrier", "passengers",
              "seats", "departures", "distance_miles"]
    with open(OUT_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {OUT_PATH}: {len(rows)} rows")
    return len(rows)


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    tracked = load_tracked_airports()
    print(f"Tracked airports: {len(tracked)}")

    print("Downloading T-100 Segment zips (one request per year, All months, All geography)...")
    for year in YEARS:
        download_year(year)

    print("Aggregating (CLASS=F only, origin in tracked set, summed across aircraft types)...")
    agg = aggregate(tracked)
    write_csv(agg)


if __name__ == "__main__":
    main()
