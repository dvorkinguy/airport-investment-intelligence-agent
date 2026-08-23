"""The moving year window, the container env fallback, and the probe decision.

These guard failures that are silent by construction. A hardcoded year window
would let the scheduled job run weekly forever, rebuild the identical years
every time and report success while the data never advanced - nothing
observable would complain. A probe that reads local disk instead of Neon would
re-download 1.1 GB every week in a container that always starts with a cold
cache, while the public endpoint claimed it only refreshes when something new
has published.

Both are the same class of defect: a thing that looks built, reports healthy,
and is not true. See docs/adr/ADR-005-scheduled-ingestion.md.
"""

import importlib
import os
from datetime import date

import pytest

from ingestion import refresh


# ---------------------------------------------------------------------------
# Year window
# ---------------------------------------------------------------------------


def test_bts_window_admits_complete_calendar_years_only():
    # 2026-08 minus the 3-month reporting lag lands in 2026-05, so 2026 is not
    # yet complete. Scoring aggregates by airport-year, so a partial year would
    # distort every year-over-year comparison in the product.
    assert refresh.bts_year_window(date(2026, 8, 23)) == (2023, 2024, 2025)


def test_bts_window_advances_once_december_has_published():
    # 2027-04 minus 3 months is 2027-01, so December 2026 has published and
    # 2026 becomes admissible. This is the assertion that proves the scheduler
    # is not theatre.
    window = refresh.bts_year_window(date(2027, 4, 1))
    assert 2026 in window
    assert window == (2023, 2024, 2025, 2026)


def test_bts_window_still_advancing_years_later():
    assert 2029 in refresh.bts_year_window(date(2030, 6, 1))


def test_faa_window_lags_two_years():
    # ADR-004 recorded FY2024 filings still arriving in February 2026.
    assert refresh.faa_year_window(date(2026, 8, 23)) == (2023, 2024)
    assert refresh.faa_year_window(date(2028, 1, 1)) == (2023, 2024, 2025, 2026)


def test_apply_year_windows_publishes_both_env_vars(monkeypatch):
    monkeypatch.delenv("INGEST_YEARS", raising=False)
    monkeypatch.delenv("INGEST_FAA_YEARS", raising=False)
    applied = refresh.apply_year_windows(date(2027, 4, 1))
    assert os.environ["INGEST_YEARS"] == "2023,2024,2025,2026"
    assert os.environ["INGEST_FAA_YEARS"] == "2023,2024,2025"
    assert applied["bts_years"][-1] == 2026


def test_builders_read_the_published_window(monkeypatch):
    """Builders read YEARS at import time, which is exactly why every builder
    import inside refresh.py is lazy. Guard that contract - if someone hoists
    those imports to module level the window silently stops moving."""
    monkeypatch.setenv("INGEST_YEARS", "2023,2024,2025,2026")
    from ingestion import build_bts_t100

    importlib.reload(build_bts_t100)
    assert 2026 in build_bts_t100.YEARS

    monkeypatch.setenv("INGEST_YEARS", "2023,2024,2025")
    importlib.reload(build_bts_t100)
    assert build_bts_t100.YEARS == (2023, 2024, 2025)


# ---------------------------------------------------------------------------
# load_env - a container has no .env file
# ---------------------------------------------------------------------------


def test_load_env_falls_back_to_the_environment(monkeypatch, tmp_path):
    """Before this, the scheduled job exited on startup no matter how
    correctly the Secret Manager reference was configured."""
    from ingestion import load

    monkeypatch.setattr(load, "REPO_ROOT", tmp_path)  # no .env here
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/db")
    assert load.load_env()["DATABASE_URL"] == "postgresql://example/db"


def test_load_t25_env_falls_back_to_the_environment(monkeypatch, tmp_path):
    from ingestion import load_t25

    monkeypatch.setattr(load_t25, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/db")
    assert load_t25.load_env()["DATABASE_URL"] == "postgresql://example/db"


def test_load_env_still_exits_when_nothing_supplies_it(monkeypatch, tmp_path):
    from ingestion import load

    monkeypatch.setattr(load, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit):
        load.load_env()


# ---------------------------------------------------------------------------
# The probe decides on Neon coverage, not on local disk
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_local(monkeypatch):
    monkeypatch.setattr(refresh, "_local_airports", lambda rows: {"changed": False})
    monkeypatch.setattr(refresh, "_local_bts_t100", lambda: {})
    monkeypatch.setattr(refresh, "_local_bts_ontime", lambda: {})
    monkeypatch.setattr(refresh, "_local_airport_financials", lambda: {})
    monkeypatch.setattr(refresh, "faa_year_window", lambda *_: (2023, 2024))


COVERAGE_2023_2025 = {
    "bts_t100_years": [2023, 2024, 2025],
    "bts_ontime_years": [2023, 2024, 2025],
    "airport_financials_years": [2023, 2024],
}


def test_no_change_when_neon_already_covers_the_window(monkeypatch, stub_local):
    """A cold local cache must not read as 'new data'. In a container
    data/raw/ is always empty; only Neon coverage decides."""
    monkeypatch.setattr(refresh, "bts_year_window", lambda *_: (2023, 2024, 2025))

    def fail_if_called(url):
        raise AssertionError("no upstream request when Neon already covers the window")

    monkeypatch.setattr(refresh, "http_status", fail_if_called)

    sources = refresh.probe_sources({"airports": 679}, COVERAGE_2023_2025)
    assert refresh.any_changed(sources) is False


def test_probe_believes_the_publisher_over_the_calendar(monkeypatch, stub_local):
    """The window says the year should exist; the source says it does not.
    Believe the source rather than starting a download that cannot succeed."""
    monkeypatch.setattr(refresh, "bts_year_window", lambda *_: (2023, 2024, 2025, 2026))
    monkeypatch.setattr(refresh, "http_status", lambda url: 404)

    sources = refresh.probe_sources({"airports": 679}, COVERAGE_2023_2025)
    assert sources["bts_t100"]["changed"] is False
    assert sources["bts_ontime"]["changed"] is False
    assert sources["upstream_check"]["status"] == 404


def test_probe_proceeds_when_the_upstream_check_itself_fails(monkeypatch, stub_local):
    """A failed HEAD is not evidence that nothing published. A network blip
    must never masquerade as 'up to date'."""
    monkeypatch.setattr(refresh, "bts_year_window", lambda *_: (2023, 2024, 2025, 2026))
    monkeypatch.setattr(refresh, "http_status", lambda url: None)

    sources = refresh.probe_sources({"airports": 679}, COVERAGE_2023_2025)
    assert sources["bts_t100"]["changed"] is True
    assert refresh.any_changed(sources) is True


def test_probe_detects_a_genuinely_new_year(monkeypatch, stub_local):
    monkeypatch.setattr(refresh, "bts_year_window", lambda *_: (2023, 2024, 2025, 2026))
    monkeypatch.setattr(refresh, "http_status", lambda url: 200)

    sources = refresh.probe_sources({"airports": 679}, COVERAGE_2023_2025)
    assert sources["bts_t100"]["missing_years"] == [2026]
    assert refresh.any_changed(sources) is True


def test_probe_publishes_display_names_for_the_public_endpoint(stub_local):
    sources = refresh.probe_sources({"airports": 679}, COVERAGE_2023_2025)
    assert "BTS T-100 Segment" in sources["display"]
    assert "FAA Form 127 (CATS)" in sources["display"]
