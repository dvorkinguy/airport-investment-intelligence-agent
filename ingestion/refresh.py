"""Scheduled-ingestion orchestrator (ADR-005: docs/adr/ADR-005-scheduled-ingestion.md).

Wraps the existing build_*.py / load.py / load_t25.py scripts in a
probe -> build -> validate -> load pipeline so an unattended weekly run can
never reach `load` on a bad build. `ingestion/load.py` gets its idempotency
from `db/schema.sql` itself (DROP TABLE IF EXISTS ... CREATE TABLE) - safe
run by hand and watched, dangerous run unattended: a half-failed build would
still reach `load`, drop the live tables, fail to repopulate them, and leave
the public site answering confidently from an empty database. This script
makes that impossible by never calling `load` unless the build already
succeeded and its output cleared a row-count floor.

Every run is recorded in `data_refresh_runs` (db/schema_refresh.sql) so a
crashed run is visible as `failed`, never left lying as `running` forever.

Reads DATABASE_URL the same way ingestion/load.py does.
Usage: uv run python -m ingestion.refresh --trigger manual
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import psycopg
from psycopg.types.json import Json

from ingestion.load import load_env

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = REPO_ROOT / "db"
DATA_DIR = REPO_ROOT / "data"

TABLES = ["airports", "bts_t100", "bts_ontime", "airport_financials"]

CSV_OUTPUTS = {
    "airports": DATA_DIR / "airports.csv",
    "bts_t100": DATA_DIR / "bts_t100.csv",
    "bts_ontime": DATA_DIR / "bts_ontime.csv",
    "airport_financials": DATA_DIR / "airport_financials.csv",
}

FLOOR_RATIO = 0.9  # a refresh should add rows, not remove them - see ADR-005


class BuildFailed(Exception):
    """A builder raised, or exited non-zero."""


class ValidationFailed(Exception):
    """An output CSV fell below its row-count floor."""


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path, encoding="utf-8", newline="") as f:
        return max(sum(1 for _ in f) - 1, 0)  # minus header


# ---------------------------------------------------------------------------
# The moving year window (ADR-005 "The window has to move, or the schedule is
# theatre").
#
# The builders used to carry a hardcoded YEARS tuple. On a schedule that is
# fatal: the job would rebuild the identical window every week forever and
# report success while the data never advanced. The window is therefore
# computed from the calendar and the published reporting lag, and handed to the
# builders through the environment.
#
# COMPLETE CALENDAR YEARS ONLY. The scoring aggregates by airport-year -
# v_carrier_concentration is HHI per airport-year and v_roi_proxy joins on it -
# so a partial year would distort every year-over-year comparison in the
# product. ADR-004 reasoned the same way about FAA FY2025. A year is admitted
# only once its December has published.
# ---------------------------------------------------------------------------

# Display names for the public /freshness endpoint. The run row is read by a
# surface a reviewer can open, so it carries the names of the actual
# publications rather than our table names.
SOURCE_DISPLAY = [
    "BTS T-100 Segment",
    "BTS On-Time Performance",
    "FAA Form 127 (CATS)",
    "OurAirports",
]

FIRST_BTS_YEAR = 2023
FIRST_FAA_YEAR = 2023
BTS_LAG_MONTHS = 3   # docs/design.md:131 - "Reporting lags ~2-3 months"
FAA_LAG_YEARS = 2    # ADR-004 - FY2024 filings still arriving 2026-02

OURAIRPORTS_FILES = {
    "airports.csv": "https://davidmegginson.github.io/ourairports-data/airports.csv",
    "runways.csv": "https://davidmegginson.github.io/ourairports-data/runways.csv",
}

HTTP_TIMEOUT = 60


def _shift_months(d: date, months: int) -> date:
    total = (d.year * 12 + (d.month - 1)) + months
    return date(total // 12, total % 12 + 1, 1)


def bts_year_window(today: date | None = None) -> tuple[int, ...]:
    """Complete calendar years of BTS data that should exist by `today`."""
    today = today or date.today()
    published_through = _shift_months(today, -BTS_LAG_MONTHS)
    newest_complete = (
        published_through.year if published_through.month == 12
        else published_through.year - 1
    )
    return tuple(range(FIRST_BTS_YEAR, newest_complete + 1))


def faa_year_window(today: date | None = None) -> tuple[int, ...]:
    """FAA Form 127 fiscal years plausibly filed by `today`."""
    today = today or date.today()
    return tuple(range(FIRST_FAA_YEAR, today.year - FAA_LAG_YEARS + 1))


def apply_year_windows(today: date | None = None) -> dict:
    """Publish the windows to the environment BEFORE any builder is imported.

    The builders read their YEARS at import time, so this must run first -
    that is why every builder import in this module is deliberately lazy.
    """
    bts = bts_year_window(today)
    faa = faa_year_window(today)
    os.environ["INGEST_YEARS"] = ",".join(str(y) for y in bts)
    os.environ["INGEST_FAA_YEARS"] = ",".join(str(y) for y in faa)
    return {"bts_years": list(bts), "faa_years": list(faa)}


def http_status(url: str) -> int | None:
    """HEAD a URL. None means the request itself failed - which is NOT the
    same as 404 and must never be read as 'nothing published'."""
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def fetch_ourairports(raw_dir: Path) -> dict:
    """build_airports.py has no fetch step of its own - it transforms whatever
    is already in data/raw/. On a schedule, in a fresh container, data/raw/ is
    empty, so nothing would rebuild. This supplies the two source files."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    fetched = {}
    for name, url in OURAIRPORTS_FILES.items():
        dest = raw_dir / name
        if dest.exists() and dest.stat().st_size > 500_000:
            fetched[name] = "cached"
            continue
        tmp = dest.with_suffix(dest.suffix + ".part")
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as resp, open(tmp, "wb") as f:
            while chunk := resp.read(1024 * 1024):
                f.write(chunk)
        tmp.replace(dest)
        fetched[name] = "downloaded"
    return fetched


# ---------------------------------------------------------------------------
# Probing - see ADR-005 "Cadence: weekly poll, monthly effective refresh".
#
# None of the four sources exposes a true live freshness check the way a
# static file with a Last-Modified header would: three of them (T-100,
# on-time, FAA Form 127) download a hardcoded set of years into data/raw/ and
# already skip anything complete; airports has no fetch step in this repo at
# all (a person refreshes its raw CSVs by hand, per ADR-001). So the honest
# cheap probe available to this pipeline, per source, is "is there anything
# within this builder's own configured scope that it hasn't already
# fetched" - reusing each build_*.py's own completeness check rather than
# re-implementing one. That correctly reports unchanged once a configured
# range is fully cached (today's case - see the module docstring's expected
# `no_change` result), and correctly flips to changed the moment someone
# extends a YEARS constant to chase a newer period.
# ---------------------------------------------------------------------------


def _local_airports(rows_before: dict) -> dict:
    """build_airports.py has no fetch step - it transforms whatever is
    already in data/raw/{airports,runways}.csv. The only signal available
    here is whether the already-committed data/airports.csv still matches
    what Neon holds; a mismatch means the snapshot moved without a load,
    which is itself worth catching and rebuilding."""
    local_rows = count_csv_rows(CSV_OUTPUTS["airports"])
    neon_rows = rows_before.get("airports", 0)
    return {
        "probed": True,
        "method": "local processed CSV vs Neon row count (no fetch step upstream)",
        "local_rows": local_rows,
        "neon_rows": neon_rows,
        "changed": local_rows != neon_rows,
    }


def _local_bts_t100() -> dict:
    """build_bts_t100.py's own docstring: no static prezip URL exists for
    T-100 - it drives a scripted ASP.NET WebForms POST flow, so there is no
    HEAD/Last-Modified check against the live source. The cheap check that
    IS available: is every year in its own hardcoded YEARS already
    downloaded and complete on disk?"""
    from ingestion import build_bts_t100 as mod

    missing = [y for y in mod.YEARS if not mod.is_complete(mod.zip_path(y))]
    return {
        "probed": True,
        "method": (
            "local target-file completeness (scripted ASP.NET form POST - no "
            "static URL exists to HEAD, per build_bts_t100.py)"
        ),
        "configured_years": list(mod.YEARS),
        "missing_years": missing,
        "changed": bool(missing),
    }


def _local_bts_ontime() -> dict:
    """build_bts_ontime.py downloads from a predictable static URL per
    (year, month) - the one source shaped for a real HEAD/URL-existence
    probe. Its own hardcoded YEARS/MONTHS already caps the range this
    pipeline will ever request; while every target zip in that range is
    already complete there is nothing to probe for. A live probe only
    becomes meaningful once someone extends YEARS past what is already
    cached - the predictable-URL machinery (zip_path) is reused as-is so
    that extension needs no change here."""
    from ingestion import build_bts_ontime as mod

    missing = [(y, m) for y, m in mod.TARGETS if not mod.is_complete(mod.zip_path(y, m))]
    return {
        "probed": True,
        "method": (
            "local target-file completeness against predictable per-month URLs "
            "(zip_path); nothing left in the configured range to probe live"
        ),
        "configured_targets": len(mod.TARGETS),
        "missing_targets": [f"{y}-{m:02d}" for y, m in missing],
        "changed": bool(missing),
    }


def _local_airport_financials() -> dict:
    """build_faa_form127.py downloads one bulk CSV per fiscal year in its
    hardcoded YEARS from a ColdFusion export with no static URL to HEAD.
    Same shape as the two BTS sources: a complete local cache for the
    configured years means nothing new to fetch without a code change."""
    from ingestion import build_faa_form127 as mod

    missing = [
        year
        for year in mod.YEARS
        if not (mod.raw_path(year).exists() and mod.raw_path(year).stat().st_size > 10_000)
    ]
    return {
        "probed": True,
        "method": "local target-file completeness (ColdFusion export, no static URL to HEAD)",
        "configured_years": list(mod.YEARS),
        "missing_years": missing,
        "changed": bool(missing),
    }


def probe_sources(rows_before: dict, coverage: dict | None = None) -> dict:
    """What matters is whether NEON is missing something, not whether the local
    disk cache is cold.

    The first implementation compared each builder's configured years against
    files already downloaded into data/raw/. That is correct on a laptop that
    keeps its cache and wrong in a container: a fresh Cloud Run task always has
    an empty data/raw/, so every source would read "changed" and the job would
    re-download 1.1 GB every single week while claiming to refresh only when
    something new published.

    So the decision is driven by Neon coverage against the computed window, and
    confirmed against the live source with a HEAD before committing to a heavy
    download. The old local checks are kept, renamed, as diagnostics on the run
    row - they are useful evidence, they are just not the decision.
    """
    coverage = coverage or {}
    windows = {
        "bts": bts_year_window(),
        "faa": faa_year_window(),
    }

    bts_have = set(coverage.get("bts_t100_years", []))
    ontime_have = set(coverage.get("bts_ontime_years", []))
    faa_have = set(coverage.get("airport_financials_years", []))

    t100_missing = sorted(set(windows["bts"]) - bts_have)
    ontime_missing = sorted(set(windows["bts"]) - ontime_have)
    faa_missing = sorted(set(windows["faa"]) - faa_have)

    # Confirm against the live source before committing to a download. BTS
    # publishes on-time and T-100 on the same monthly cycle, so the one
    # predictable per-month URL is a sound proxy for both. This is a decision,
    # not an assumption - T-100 drives a scripted ASP.NET form with no URL to
    # HEAD, so there is nothing cheaper available for it.
    upstream = None
    if t100_missing or ontime_missing:
        from ingestion import build_bts_ontime as ontime_mod

        year = (ontime_missing or t100_missing)[0]
        url = ontime_mod.URL_TEMPLATE.format(year=year, month=12)
        status = http_status(url)
        upstream = {"probed_url_year": year, "month": 12, "status": status}
        if status is not None and status >= 400:
            # The window says the year should exist; the publisher says it does
            # not. Believe the publisher and do nothing rather than start a
            # download that cannot succeed.
            t100_missing, ontime_missing = [], []
        # status is None means the probe itself failed - that is NOT evidence of
        # "nothing published", so the missing lists stand and the build proceeds.

    return {
        "display": SOURCE_DISPLAY,
        "windows": windows | {"bts": list(windows["bts"]), "faa": list(windows["faa"])},
        "upstream_check": upstream,
        # Airports is reference data and must NOT be able to trigger a rebuild
        # on its own. The original check compared the local processed CSV
        # against Neon, which is meaningful on a laptop that keeps data/ and
        # meaningless in a container, where the ephemeral disk starts empty:
        # local 0 vs Neon 679 reads as "changed" on every single scheduled
        # run, forever. That is what made the first real Cloud Run execution
        # download 1.1 GB it did not need.
        #
        # So the only condition that makes airports itself changed is Neon
        # having none at all - a cold database. Otherwise it rides along with
        # a BTS-driven rebuild, which regenerates it anyway. The local
        # comparison is kept as diagnostics on the run row, not as a decision.
        "airports": {
            "changed": rows_before.get("airports", 0) == 0,
            "neon_rows": rows_before.get("airports", 0),
            "local": _local_airports(rows_before),
        },
        "bts_t100": {"missing_years": t100_missing, "changed": bool(t100_missing),
                     "local": _local_bts_t100()},
        "bts_ontime": {"missing_years": ontime_missing, "changed": bool(ontime_missing),
                       "local": _local_bts_ontime()},
        "airport_financials": {"missing_years": faa_missing, "changed": bool(faa_missing),
                               "local": _local_airport_financials()},
    }


DECIDING_SOURCES = ("airports", "bts_t100", "bts_ontime", "airport_financials")


def any_changed(sources: dict) -> bool:
    # A source this pipeline could not evaluate is not a confirmed "unchanged" -
    # default to True so an unrecognized/no-probe result never masks real drift.
    return any(
        sources.get(name, {}).get("changed", True) for name in DECIDING_SOURCES
    )


# ---------------------------------------------------------------------------
# Build / validate / load
# ---------------------------------------------------------------------------


def run_builders() -> None:
    """Runs the four existing build_*.py scripts in-process, unmodified. Any
    exception, or a non-zero-code SystemExit, is wrapped as BuildFailed."""
    # build_airports.py has no fetch step of its own, so supply its inputs
    # before importing anything - in a fresh container data/raw/ is empty.
    try:
        fetch_ourairports(DATA_DIR / "raw")
    except Exception as e:
        raise BuildFailed(f"ourairports fetch: {e}") from e

    # Imported lazily and ONLY here: the builders read their YEARS at import
    # time, so apply_year_windows() must have run first.
    from ingestion import build_airports, build_bts_ontime, build_bts_t100, build_faa_form127

    for mod in (build_airports, build_bts_t100, build_bts_ontime, build_faa_form127):
        try:
            mod.main()
        except SystemExit as e:
            if e.code not in (None, 0):
                raise BuildFailed(f"{mod.__name__}: exited with {e.code!r}") from e
        except Exception as e:
            raise BuildFailed(f"{mod.__name__}: {e}") from e


def validate_outputs(rows_before: dict) -> None:
    """Every output CSV must hold at least FLOOR_RATIO of what Neon currently
    has for that table. This is the guard that stops a truncated download
    from reaching `load` and wiping the database - see the module docstring."""
    for table, csv_path in CSV_OUTPUTS.items():
        count = count_csv_rows(csv_path)
        floor = int(rows_before.get(table, 0) * FLOOR_RATIO)
        if count < floor:
            raise ValidationFailed(
                f"{table}: {csv_path.name} has {count} rows, below the {floor}-row "
                f"floor ({int(FLOOR_RATIO * 100)}% of {rows_before.get(table, 0)} in Neon)"
            )


def run_load() -> None:
    """Calls the two existing, tested loaders in-process. Not rewritten."""
    from ingestion import load, load_t25

    load.main()
    load_t25.main()


# ---------------------------------------------------------------------------
# Run-row bookkeeping
# ---------------------------------------------------------------------------


class RunRecorder:
    """Wraps data_refresh_runs bookkeeping behind counts/open/close so the
    orchestration in `run()` - and its tests - never need to speak SQL.

    Every method opens its OWN short-lived connection rather than sharing one
    held for the life of the run. That is not fastidiousness: the first real
    Cloud Run execution died on

        psycopg.errors.AdminShutdown: terminating connection due to
        administrator command

    because a single connection was opened, then held across a ten-minute
    download, and Neon suspended it in the meantime. The failure then
    cascaded - close_run() needed that same dead connection, so the run row
    was stranded as `running` forever, which is exactly the state ADR-005
    says must never exist because it makes /freshness lie.

    The rest of this codebase already knew: services/agent/db.py wraps queries
    in with_stale_retry and services/agent/checkpointer.py exists solely to
    survive this. The ingestion path had not learned it yet.
    """

    def __init__(self, dsn: str):
        self._dsn = dsn

    def _run(self, fn, *, retries: int = 1):
        """One short-lived connection per operation, with a single retry on a
        dropped/suspended connection. Autocommit: each call is its own unit,
        so a later failure can never roll back an already-recorded fact."""
        last: Exception | None = None
        for _ in range(retries + 1):
            try:
                with psycopg.connect(self._dsn, connect_timeout=15, autocommit=True) as conn:
                    with conn.cursor() as cur:
                        return fn(cur)
            except (psycopg.OperationalError, psycopg.errors.AdminShutdown) as e:
                last = e
        raise last  # type: ignore[misc]

    def table_counts(self) -> dict:
        def q(cur):
            out = {}
            for table in TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                out[table] = cur.fetchone()[0]
            return out

        return self._run(q)

    def coverage(self) -> dict:
        """Which years Neon actually holds. This is what the probe compares the
        computed window against - the local disk cache is not the question."""
        def q(cur):
            out = {}
            for table, column in (
                ("bts_t100", "year"),
                ("bts_ontime", "year"),
                ("airport_financials", "fy"),
            ):
                try:
                    cur.execute(f"SELECT DISTINCT {column} FROM {table} ORDER BY 1")
                    out[f"{table}_years"] = [r[0] for r in cur.fetchall()]
                except Exception:
                    out[f"{table}_years"] = []
            return out

        return self._run(q)

    def latest_period(self) -> str | None:
        def q(cur):
            cur.execute(
                "SELECT to_char(GREATEST("
                "COALESCE((SELECT MAX(make_date(year, month, 1)) FROM bts_t100), DATE '0001-01-01'), "
                "COALESCE((SELECT MAX(make_date(year, month, 1)) FROM bts_ontime), DATE '0001-01-01')"
                "), 'YYYY-MM')"
            )
            row = cur.fetchone()
            return row[0] if row else None

        return self._run(q)

    def open_run(self, trigger: str) -> int:
        def q(cur):
            cur.execute(
                "INSERT INTO data_refresh_runs (status, trigger) VALUES ('running', %s) "
                "RETURNING id",
                (trigger,),
            )
            return cur.fetchone()[0]

        return self._run(q)

    def close_run(self, run_id: int, status: str, **fields) -> None:
        def q(cur):
            columns = ["status = %s", "finished_at = now()"]
            values: list = [status]
            for name in ("sources", "rows_before", "rows_after"):
                if name in fields:
                    columns.append(f"{name} = %s")
                    values.append(Json(fields[name]))
            for name in ("latest_period", "error"):
                if name in fields:
                    columns.append(f"{name} = %s")
                    values.append(fields[name])
            values.append(run_id)
            cur.execute(
                f"UPDATE data_refresh_runs SET {', '.join(columns)} WHERE id = %s", values
            )

        # Two retries, not one: this is the last write of the run and the one
        # that must not be lost. A row left `running` is worse than a wrong
        # status - the freshness endpoint treats it as a live run.
        self._run(q, retries=2)


# ---------------------------------------------------------------------------
# Orchestration - the state machine under test. No SQL and no network calls
# of its own; everything DB/build/load happens through `recorder`,
# `probe_sources`, `run_builders`, `run_load`, `validate_outputs` - all
# monkeypatchable at the module level.
# ---------------------------------------------------------------------------


def run(recorder: RunRecorder, trigger: str) -> str:
    run_id = recorder.open_run(trigger)
    try:
        rows_before = recorder.table_counts()
        # Must precede probe_sources: the probes import the builders, and the
        # builders read their year window from the environment at import time.
        window = apply_year_windows()
        sources = probe_sources(rows_before, recorder.coverage())
        sources["applied_window"] = window

        if not any_changed(sources):
            # latest_period belongs on EVERY terminal path, not just success.
            # A no_change run is a successful check and the site must still be
            # able to state the vintage of the data it actually holds; omitting
            # it here left the public freshness line blank after a correct run.
            recorder.close_run(
                run_id,
                "no_change",
                sources=sources,
                rows_before=rows_before,
                latest_period=recorder.latest_period(),
            )
            return "no_change"

        try:
            run_builders()
        except BuildFailed as e:
            recorder.close_run(
                run_id, "failed", sources=sources, rows_before=rows_before, error=str(e)
            )
            raise

        try:
            validate_outputs(rows_before)
        except ValidationFailed as e:
            recorder.close_run(
                run_id, "failed", sources=sources, rows_before=rows_before, error=str(e)
            )
            raise

        run_load()

        rows_after = recorder.table_counts()
        latest_period = recorder.latest_period()
        recorder.close_run(
            run_id,
            "success",
            sources=sources,
            rows_before=rows_before,
            rows_after=rows_after,
            latest_period=latest_period,
        )
        return "success"
    except (BuildFailed, ValidationFailed):
        raise
    except Exception as e:
        # Anything else - including a bug in the orchestration above - still
        # closes the row. A row left `running` forever would make the
        # /freshness endpoint lie, which defeats the point of having one.
        recorder.close_run(run_id, "failed", error=f"{type(e).__name__}: {e}")
        raise


def run_and_exit_code(recorder: RunRecorder, trigger: str) -> int:
    try:
        status = run(recorder, trigger)
    except (BuildFailed, ValidationFailed) as e:
        print(f"refresh failed: {e}", file=sys.stderr)
        return 1
    except Exception:
        traceback.print_exc()
        return 1
    print(f"refresh: {status}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def apply_schema_refresh(cur) -> None:
    cur.execute((DB_DIR / "schema_refresh.sql").read_text(encoding="utf-8"))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scheduled ingestion orchestrator (ADR-005).")
    parser.add_argument("--trigger", choices=["scheduled", "manual"], default="manual")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    env = load_env()
    dsn = env["DATABASE_URL"]
    # Schema application gets its own connection and closes it immediately.
    # Nothing may hold a connection across the build - see RunRecorder.
    with psycopg.connect(dsn, connect_timeout=15, autocommit=True) as conn:
        with conn.cursor() as cur:
            apply_schema_refresh(cur)
    return run_and_exit_code(RunRecorder(dsn), args.trigger)


if __name__ == "__main__":
    sys.exit(main())
