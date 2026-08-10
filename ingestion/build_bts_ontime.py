"""Download BTS "On-Time Reporting Carrier On-Time Performance" monthly zips for
2023-2025, aggregate arrival-delay stats per (year, month, destination airport), and
write data/bts_ontime.csv.

Source: https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{YEAR}_{MONTH}.zip
(MONTH has no leading zero, e.g. `_2023_1.zip` for January). Each zip holds exactly one
CSV (110 columns) plus a readme.html (ignored). Files run ~25-31MB each; 36 files total
(2023-2025, months 1-12).

Grain: one row per (year, month, destination airport) - this is ARRIVAL data, grouped by
Dest, not Origin. A flight lands (arrives) at its Dest airport; that's the airport whose
congestion this measures.

Filter (applied per raw row, before aggregating): skip if Cancelled == '1.00' or
ArrDel15 == ''. Cancelled flights never arrived, so they have no meaningful delay figure.
Empty ArrDel15 also catches diverted flights (Cancelled == '0.00' but ArrDel15 == '') -
verified live against the 2023-01 sample: 10,295 cancelled rows, 11,640 empty-ArrDel15
rows, all 10,295 cancelled rows a subset of the empty set. Including either would either
miscount arrivals or crash float() on an empty string.

Idempotent/re-runnable: skips zips already present in data/raw/ that pass a completeness
check (size floor + valid zip signature), and always rebuilds bts_ontime.csv from
whatever's currently in data/raw/. Downloads run concurrently (ThreadPoolExecutor) with
per-file retries, then a slower-concurrency second pass for anything still failing.

Usage: uv run ingestion/build_bts_ontime.py
"""

import csv
import io
import time
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
OUT_PATH = REPO_ROOT / "data" / "bts_ontime.csv"

URL_TEMPLATE = (
    "https://transtats.bts.gov/PREZIP/"
    "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip"
)
CSV_NAME_TEMPLATE = (
    "On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_{year}_{month}.csv"
)
YEARS = (2023, 2024, 2025)
MONTHS = range(1, 13)
TARGETS = [(y, m) for y in YEARS for m in MONTHS]

MIN_ZIP_SIZE = 10_000_000  # bytes; real files run 25-31MB, floor catches truncated downloads
FIRST_PASS_WORKERS = 6
RETRY_PASS_WORKERS = 2
MAX_RETRIES = 3
REQUEST_TIMEOUT = 120  # seconds, per blocking read
USER_AGENT = "Mozilla/5.0 (compatible; airport-intel-agent/0.1 data ingestion)"

OUT_FIELDS = ["year", "month", "airport_iata", "arr_flights", "arr_del15", "arr_delay_min"]


def zip_path(year: int, month: int) -> Path:
    return RAW_DIR / f"ontime_{year}_{month}.zip"


def is_complete(path: Path) -> bool:
    """A zip counts as already-downloaded only if it exists, clears a size floor well
    below the real ~25-31MB range (catches truncated/failed downloads), and parses as a
    valid zip (catches corrupt files)."""
    if not path.exists() or path.stat().st_size < MIN_ZIP_SIZE:
        return False
    try:
        return zipfile.is_zipfile(path)
    except OSError:
        return False


def download_one(year: int, month: int) -> tuple[int, int, str | None]:
    """Returns (year, month, error) - error is None on success."""
    dest = zip_path(year, month)
    if is_complete(dest):
        return (year, month, None)

    url = URL_TEMPLATE.format(year=year, month=month)
    tmp = dest.parent / (dest.name + ".part")
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=REQUEST_TIMEOUT) as resp, open(tmp, "wb") as f:
                while chunk := resp.read(1024 * 1024):
                    f.write(chunk)
            if not is_complete(tmp):
                size = tmp.stat().st_size if tmp.exists() else 0
                raise OSError(f"failed completeness check after download ({size} bytes)")
            tmp.replace(dest)
            return (year, month, None)
        except (URLError, HTTPError, OSError, TimeoutError) as e:
            last_err = str(e)
            tmp.unlink(missing_ok=True)
            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)
    return (year, month, last_err)


def run_batch(targets: list[tuple[int, int]], workers: int) -> list[tuple[int, int]]:
    """Downloads targets concurrently; returns the list of (year, month) that failed."""
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_one, y, m): (y, m) for y, m in targets}
        for fut in as_completed(futures):
            y, m, err = fut.result()
            if err:
                print(f"  FAILED {y}-{m:02d}: {err}")
                failures.append((y, m))
            else:
                print(f"  OK {y}-{m:02d}")
    return failures


def download_all() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # Clean up any stray partial files from a previous interrupted run.
    for stray in RAW_DIR.glob("*.zip.part"):
        stray.unlink(missing_ok=True)

    to_fetch = [(y, m) for y, m in TARGETS if not is_complete(zip_path(y, m))]
    already = len(TARGETS) - len(to_fetch)
    print(f"Zips present+complete: {already}/{len(TARGETS)}. Downloading {len(to_fetch)}...")
    if not to_fetch:
        return

    failures = run_batch(to_fetch, FIRST_PASS_WORKERS)
    if failures:
        print(f"Retrying {len(failures)} failed month(s) at lower concurrency...")
        failures = run_batch(failures, RETRY_PASS_WORKERS)
    if failures:
        print(f"Still failing after retries: {[f'{y}-{m:02d}' for y, m in failures]}")


def aggregate() -> tuple[dict, set]:
    """Returns (agg, found_months). agg maps (year, month, dest) -> [arr_flights,
    arr_del15, arr_delay_min]. found_months is the set of (year, month) actually parsed."""
    agg = defaultdict(lambda: [0, 0, 0.0])
    found_months = set()

    for year, month in TARGETS:
        zpath = zip_path(year, month)
        if not is_complete(zpath):
            continue

        csv_name = CSV_NAME_TEMPLATE.format(year=year, month=month)
        with zipfile.ZipFile(zpath) as zf:
            names = zf.namelist()
            if csv_name not in names:
                candidates = [n for n in names if n.lower().endswith(".csv")]
                if len(candidates) != 1:
                    print(f"  WARN {year}-{month:02d}: expected CSV member not found "
                          f"(candidates={candidates}), skipping")
                    continue
                csv_name = candidates[0]

            rows_in = 0
            with zf.open(csv_name) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
                for row in csv.DictReader(text):
                    rows_in += 1
                    if row["Cancelled"] == "1.00" or row["ArrDel15"] == "":
                        continue
                    key = (int(row["Year"]), int(row["Month"]), row["Dest"])
                    bucket = agg[key]
                    bucket[0] += 1
                    if row["ArrDel15"] == "1.00":
                        bucket[1] += 1
                    bucket[2] += float(row["ArrDelayMinutes"])

        found_months.add((year, month))
        print(f"  aggregated {year}-{month:02d} ({rows_in} raw rows)")

    return agg, found_months


def write_csv(agg: dict) -> int:
    rows = []
    for (year, month, dest), (flights, del15, delay_min) in agg.items():
        rows.append({
            "year": year,
            "month": month,
            "airport_iata": dest,
            "arr_flights": flights,
            "arr_del15": del15,
            "arr_delay_min": round(delay_min, 2),
        })
    rows.sort(key=lambda r: (r["year"], r["month"], r["airport_iata"]))

    with open(OUT_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {OUT_PATH}: {len(rows)} rows")
    return len(rows)


def main():
    download_all()
    agg, found_months = aggregate()
    write_csv(agg)

    missing = [(y, m) for y, m in TARGETS if (y, m) not in found_months]
    if missing:
        print(f"MISSING MONTHS ({len(missing)}/{len(TARGETS)}): "
              f"{[f'{y}-{m:02d}' for y, m in missing]}")
    else:
        print(f"All {len(TARGETS)} months present (2023-01 through 2025-12).")


if __name__ == "__main__":
    main()
