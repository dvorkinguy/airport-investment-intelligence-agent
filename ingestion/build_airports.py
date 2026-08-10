"""Build data/airports.csv from raw OurAirports snapshots in data/raw/.

Source: https://davidmegginson.github.io/ourairports-data/ (airports.csv, runways.csv).
Filter: US airports with an IATA code AND scheduled_service = 'yes' - the realistic
commercial-passenger universe that BTS T-100 / on-time data actually covers.

Re-run this after re-downloading data/raw/airports.csv + data/raw/runways.csv to refresh.
"""

import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_AIRPORTS = REPO_ROOT / "data" / "raw" / "airports.csv"
RAW_RUNWAYS = REPO_ROOT / "data" / "raw" / "runways.csv"
OUT_PATH = REPO_ROOT / "data" / "airports.csv"

OUT_FIELDS = [
    "iata", "icao", "name", "city", "state", "lat", "lon",
    "runways_count", "max_runway_length_ft",
]


def load_runway_stats():
    """ident -> (runways_count, max_runway_length_ft), excluding closed runways."""
    stats = {}
    with open(RAW_RUNWAYS, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("closed") == "1":
                continue
            ident = row["airport_ident"]
            length_raw = row.get("length_ft") or ""
            length = int(length_raw) if length_raw.strip().isdigit() else None
            count, max_len = stats.get(ident, (0, None))
            count += 1
            if length is not None and (max_len is None or length > max_len):
                max_len = length
            stats[ident] = (count, max_len)
    return stats


def main():
    runway_stats = load_runway_stats()

    kept = []
    total_us = 0
    with open(RAW_AIRPORTS, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["iso_country"] != "US":
                continue
            total_us += 1
            if not row["iata_code"] or row["scheduled_service"] != "yes":
                continue
            count, max_len = runway_stats.get(row["ident"], (0, None))
            state = row["iso_region"][3:] if row["iso_region"].startswith("US-") else row["iso_region"]
            kept.append({
                "iata": row["iata_code"],
                "icao": row["icao_code"],
                "name": row["name"],
                "city": row["municipality"],
                "state": state,
                "lat": row["latitude_deg"],
                "lon": row["longitude_deg"],
                "runways_count": count,
                "max_runway_length_ft": max_len if max_len is not None else "",
            })

    with open(OUT_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        writer.writeheader()
        writer.writerows(kept)

    no_runway = sum(1 for r in kept if r["runways_count"] == 0)
    print(f"US rows scanned: {total_us}")
    print(f"Kept (IATA + scheduled_service=yes): {len(kept)}")
    print(f"...with zero matched runway rows: {no_runway}")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
