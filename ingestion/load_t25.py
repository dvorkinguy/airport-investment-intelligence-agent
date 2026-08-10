"""Idempotent T2.5 loader: applies db/views_t25.sql (additive - never touches
db/schema.sql or db/views.sql, the gate-critical Tier 1 objects), then COPYs
data/airport_financials.csv into the freshly (re)created table.

Reads DATABASE_URL from .env at repo root (never printed, never logged).
Usage: uv run python ingestion/load_t25.py
"""

import sys
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = REPO_ROOT / "db"
DATA_DIR = REPO_ROOT / "data"


def load_env():
    env = {}
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        sys.exit(f"Missing {env_path}")
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    if "DATABASE_URL" not in env:
        sys.exit("DATABASE_URL not set in .env")
    return env


def main():
    env = load_env()
    with psycopg.connect(env["DATABASE_URL"], connect_timeout=15) as conn:
        with conn.cursor() as cur:
            sql = (DB_DIR / "views_t25.sql").read_text(encoding="utf-8")
            cur.execute(sql)
            print("Applied db/views_t25.sql")

            csv_path = DATA_DIR / "airport_financials.csv"
            with open(csv_path, "rb") as f, cur.copy(
                "COPY airport_financials FROM STDIN WITH (FORMAT csv, HEADER true)"
            ) as copy:
                while chunk := f.read(1024 * 1024):
                    copy.write(chunk)
            cur.execute("SELECT COUNT(*) FROM airport_financials")
            print(f"Loaded airport_financials: {cur.fetchone()[0]} rows")
        conn.commit()
    print("T2.5 load complete.")


if __name__ == "__main__":
    main()
