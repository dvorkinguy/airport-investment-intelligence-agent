"""Idempotent loader: applies db/schema.sql + db/views.sql to Neon, then COPYs the
processed snapshot CSVs in data/ into the freshly (re)created tables.

Idempotency comes from schema.sql itself (DROP TABLE IF EXISTS ... CREATE TABLE) -
running this script twice in a row produces the same end state both times.

Reads DATABASE_URL from .env at repo root (never printed, never logged).
Usage: uv run ingestion/load.py
"""

import sys
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = REPO_ROOT / "db"
DATA_DIR = REPO_ROOT / "data"

SNAPSHOTS = [
    ("airports", DATA_DIR / "airports.csv"),
    ("bts_t100", DATA_DIR / "bts_t100.csv"),
    ("bts_ontime", DATA_DIR / "bts_ontime.csv"),
]


def load_env():
    env = {}
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        sys.exit(f"Missing {env_path} - copy .env.example and fill in DATABASE_URL.")
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


def apply_sql_file(cur, path: Path):
    sql = path.read_text(encoding="utf-8")
    cur.execute(sql)
    print(f"Applied {path.relative_to(REPO_ROOT)}")


def copy_csv(cur, table: str, csv_path: Path):
    if not csv_path.exists():
        print(f"SKIP {table}: {csv_path.relative_to(REPO_ROOT)} not found (run its build script first)")
        return 0
    with open(csv_path, "rb") as f, cur.copy(
        f"COPY {table} FROM STDIN WITH (FORMAT csv, HEADER true)"
    ) as copy:
        while chunk := f.read(1024 * 1024):
            copy.write(chunk)
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    count = cur.fetchone()[0]
    print(f"Loaded {table}: {count} rows from {csv_path.relative_to(REPO_ROOT)}")
    return count


def main():
    env = load_env()
    with psycopg.connect(env["DATABASE_URL"], connect_timeout=15) as conn:
        with conn.cursor() as cur:
            apply_sql_file(cur, DB_DIR / "schema.sql")
            for table, csv_path in SNAPSHOTS:
                copy_csv(cur, table, csv_path)
            apply_sql_file(cur, DB_DIR / "views.sql")
        conn.commit()
    print("Load complete.")


if __name__ == "__main__":
    main()
