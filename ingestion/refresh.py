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
import sys
import traceback
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


def probe_airports(rows_before: dict) -> dict:
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


def probe_bts_t100() -> dict:
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


def probe_bts_ontime() -> dict:
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


def probe_airport_financials() -> dict:
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


def probe_sources(rows_before: dict) -> dict:
    return {
        "airports": probe_airports(rows_before),
        "bts_t100": probe_bts_t100(),
        "bts_ontime": probe_bts_ontime(),
        "airport_financials": probe_airport_financials(),
    }


def any_changed(sources: dict) -> bool:
    # A source this pipeline could not evaluate is not a confirmed "unchanged" -
    # default to True so an unrecognized/no-probe result never masks real drift.
    return any(source.get("changed", True) for source in sources.values())


# ---------------------------------------------------------------------------
# Build / validate / load
# ---------------------------------------------------------------------------


def run_builders() -> None:
    """Runs the four existing build_*.py scripts in-process, unmodified. Any
    exception, or a non-zero-code SystemExit, is wrapped as BuildFailed."""
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
    orchestration in `run()` - and its tests - never need to speak SQL."""

    def __init__(self, cur):
        self._cur = cur

    def table_counts(self) -> dict:
        return {table: self._count(table) for table in TABLES}

    def _count(self, table: str) -> int:
        self._cur.execute(f"SELECT COUNT(*) FROM {table}")
        return self._cur.fetchone()[0]

    def latest_period(self) -> str | None:
        self._cur.execute(
            "SELECT to_char(GREATEST("
            "COALESCE((SELECT MAX(make_date(year, month, 1)) FROM bts_t100), DATE '0001-01-01'), "
            "COALESCE((SELECT MAX(make_date(year, month, 1)) FROM bts_ontime), DATE '0001-01-01')"
            "), 'YYYY-MM')"
        )
        row = self._cur.fetchone()
        return row[0] if row else None

    def open_run(self, trigger: str) -> int:
        self._cur.execute(
            "INSERT INTO data_refresh_runs (status, trigger) VALUES ('running', %s) RETURNING id",
            (trigger,),
        )
        return self._cur.fetchone()[0]

    def close_run(self, run_id: int, status: str, **fields) -> None:
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
        self._cur.execute(
            f"UPDATE data_refresh_runs SET {', '.join(columns)} WHERE id = %s", values
        )


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
        sources = probe_sources(rows_before)

        if not any_changed(sources):
            recorder.close_run(run_id, "no_change", sources=sources, rows_before=rows_before)
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
    with psycopg.connect(env["DATABASE_URL"], connect_timeout=15, autocommit=True) as conn:
        with conn.cursor() as cur:
            apply_schema_refresh(cur)
            recorder = RunRecorder(cur)
            return run_and_exit_code(recorder, args.trigger)


if __name__ == "__main__":
    sys.exit(main())
