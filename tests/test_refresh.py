"""ingestion/refresh.py orchestration (ADR-005).

No database, no network, no real builders: `FakeRecorder` stands in for
`data_refresh_runs`, and `probe_sources` / `run_builders` / `run_load` /
`count_csv_rows` are monkeypatched at the module level. What's under real
test is the state machine in `refresh.run()` - the ordering that makes it
impossible to reach `load` on a bad or stale build.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ingestion import refresh

UNCHANGED_SOURCES = {
    "airports": {"changed": False},
    "bts_t100": {"changed": False},
    "bts_ontime": {"changed": False},
    "airport_financials": {"changed": False},
}

CHANGED_SOURCES = {
    "airports": {"changed": False},
    "bts_t100": {"changed": True},
    "bts_ontime": {"changed": False},
    "airport_financials": {"changed": False},
}

ROWS_BEFORE = {"airports": 100, "bts_t100": 200, "bts_ontime": 300, "airport_financials": 50}


class FakeRecorder:
    """In-memory stand-in for RunRecorder - same interface, no SQL."""

    def __init__(self, table_counts: dict, latest_period: str = "2026-02"):
        self._table_counts = dict(table_counts)
        self._latest_period = latest_period
        self.rows: dict[int, dict] = {}
        self._next_id = 1

    def coverage(self) -> dict:
        """Which years Neon holds. run() passes this to probe_sources so the
        decision is driven by the database rather than by local disk cache."""
        return {
            "bts_t100_years": [2023, 2024, 2025],
            "bts_ontime_years": [2023, 2024, 2025],
            "airport_financials_years": [2023, 2024],
        }

    def table_counts(self) -> dict:
        return dict(self._table_counts)

    def latest_period(self) -> str:
        return self._latest_period

    def open_run(self, trigger: str) -> int:
        run_id = self._next_id
        self._next_id += 1
        self.rows[run_id] = {"status": "running", "trigger": trigger}
        return run_id

    def close_run(self, run_id: int, status: str, **fields) -> None:
        self.rows[run_id]["status"] = status
        self.rows[run_id].update(fields)


def test_all_sources_unchanged_skips_load(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = FakeRecorder(ROWS_BEFORE)
    build_calls: list[int] = []
    load_calls: list[int] = []
    monkeypatch.setattr(refresh, "probe_sources", lambda rows_before, coverage=None: UNCHANGED_SOURCES)
    monkeypatch.setattr(refresh, "run_builders", lambda: build_calls.append(1))
    monkeypatch.setattr(refresh, "run_load", lambda: load_calls.append(1))

    exit_code = refresh.run_and_exit_code(recorder, "manual")

    assert exit_code == 0
    assert build_calls == []
    assert load_calls == []
    assert recorder.rows[1]["status"] == "no_change"
    assert recorder.rows[1]["rows_before"] == ROWS_BEFORE


def test_a_builder_raising_blocks_load(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = FakeRecorder(ROWS_BEFORE)
    load_calls: list[int] = []
    monkeypatch.setattr(refresh, "probe_sources", lambda rows_before, coverage=None: CHANGED_SOURCES)

    def boom() -> None:
        raise refresh.BuildFailed("build_bts_t100: form response was not a zip")

    monkeypatch.setattr(refresh, "run_builders", boom)
    monkeypatch.setattr(refresh, "run_load", lambda: load_calls.append(1))

    exit_code = refresh.run_and_exit_code(recorder, "manual")

    assert exit_code == 1
    assert load_calls == []
    assert recorder.rows[1]["status"] == "failed"
    assert "not a zip" in recorder.rows[1]["error"]


def test_a_csv_below_the_row_count_floor_blocks_load(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = FakeRecorder(ROWS_BEFORE)
    load_calls: list[int] = []
    monkeypatch.setattr(refresh, "probe_sources", lambda rows_before, coverage=None: CHANGED_SOURCES)
    monkeypatch.setattr(refresh, "run_builders", lambda: None)
    monkeypatch.setattr(refresh, "run_load", lambda: load_calls.append(1))

    # bts_t100 floor is int(200 * 0.9) == 180; 5 rows is a truncated-download shape.
    low_counts = {"airports": 100, "bts_t100": 5, "bts_ontime": 300, "airport_financials": 50}
    path_to_table = {path: table for table, path in refresh.CSV_OUTPUTS.items()}
    monkeypatch.setattr(
        refresh, "count_csv_rows", lambda path: low_counts[path_to_table[path]]
    )

    exit_code = refresh.run_and_exit_code(recorder, "manual")

    assert exit_code == 1
    assert load_calls == []
    assert recorder.rows[1]["status"] == "failed"
    assert "bts_t100" in recorder.rows[1]["error"]
    assert "180" in recorder.rows[1]["error"]  # the floor, named in the error


def test_happy_path_loads_once_and_records_after_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = FakeRecorder(ROWS_BEFORE)
    build_calls: list[int] = []
    load_calls: list[int] = []
    monkeypatch.setattr(refresh, "probe_sources", lambda rows_before, coverage=None: CHANGED_SOURCES)
    monkeypatch.setattr(refresh, "run_builders", lambda: build_calls.append(1))
    monkeypatch.setattr(refresh, "run_load", lambda: load_calls.append(1))
    monkeypatch.setattr(refresh, "count_csv_rows", lambda path: ROWS_BEFORE[
        {p: t for t, p in refresh.CSV_OUTPUTS.items()}[path]
    ])

    exit_code = refresh.run_and_exit_code(recorder, "scheduled")

    assert exit_code == 0
    assert build_calls == [1]
    assert load_calls == [1]
    assert recorder.rows[1]["status"] == "success"
    assert recorder.rows[1]["rows_after"] == ROWS_BEFORE
    assert recorder.rows[1]["latest_period"] == "2026-02"
    assert recorder.rows[1]["trigger"] == "scheduled"


def test_an_unhandled_exception_still_closes_the_row(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = FakeRecorder(ROWS_BEFORE)

    def boom(rows_before: dict, coverage: dict | None = None) -> dict:
        raise RuntimeError("neon connection dropped mid-probe")

    monkeypatch.setattr(refresh, "probe_sources", boom)

    exit_code = refresh.run_and_exit_code(recorder, "manual")

    assert exit_code == 1
    assert recorder.rows[1]["status"] == "failed"
    assert recorder.rows[1]["status"] != "running"
    assert "neon connection dropped" in recorder.rows[1]["error"]


def test_count_csv_rows_excludes_the_header(tmp_path: Path) -> None:
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("iata,name\nBOS,Logan\nSFO,SFO Intl\n", encoding="utf-8")

    assert refresh.count_csv_rows(csv_path) == 2


def test_count_csv_rows_missing_file_is_zero(tmp_path: Path) -> None:
    assert refresh.count_csv_rows(tmp_path / "nope.csv") == 0


def test_any_changed_treats_an_unrecognized_result_as_changed() -> None:
    # A source with no "changed" key (e.g. a bug in a future probe) must not
    # silently count as confirmed-unchanged.
    assert refresh.any_changed({"mystery": {"probed": False}}) is True
    assert refresh.any_changed(UNCHANGED_SOURCES) is False
    assert refresh.any_changed(CHANGED_SOURCES) is True
