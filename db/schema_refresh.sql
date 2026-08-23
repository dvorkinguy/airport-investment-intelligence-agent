-- Scheduled ingestion audit trail (ADR-005). ADDITIVE ONLY - never touches
-- db/schema.sql or db/views.sql (ADR-004 freeze). Applied by ingestion/refresh.py
-- at the start of every run, before it opens its own row here.

CREATE TABLE IF NOT EXISTS data_refresh_runs (
    id            BIGSERIAL PRIMARY KEY,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    status        TEXT NOT NULL CHECK (status IN ('running', 'success', 'no_change', 'failed')),
    trigger       TEXT NOT NULL CHECK (trigger IN ('scheduled', 'manual')),
    sources       JSONB,
    rows_before   JSONB,
    rows_after    JSONB,
    latest_period TEXT,
    error         TEXT
);

COMMENT ON TABLE data_refresh_runs IS
    'Audit trail for scheduled ingestion (ADR-005). One row per ingestion/refresh.py '
    'run: what each source''s freshness probe found (sources), row counts per table '
    'before/after (rows_before/rows_after), the newest period now in Neon '
    '(latest_period), and the outcome (status). A row left status=running is a bug, '
    'not a valid end state - see ingestion/refresh.py. The public /freshness endpoint '
    'and the landing page read the latest status=success row from here.';

-- "Last successful run" is the query the /freshness endpoint runs on every request.
CREATE INDEX IF NOT EXISTS idx_data_refresh_runs_status_started
    ON data_refresh_runs (status, started_at DESC);
