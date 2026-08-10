"""Run db/view_checks.sql against Neon. Each check is a SELECT that must
return zero rows to pass; any returned row is a violation and gets printed.

Reads DATABASE_URL from .env at repo root (never printed, never logged).
Usage: uv run python ingestion/run_view_checks.py
Exit code: 0 if all checks pass, 1 if any fail.
"""

import re
import sys
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKS_PATH = REPO_ROOT / "db" / "view_checks.sql"

CHECK_MARKER = re.compile(r"^--\s*CHECK:\s*(.+?)\s*$", re.MULTILINE)


def load_env() -> dict:
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


def parse_checks(sql_text: str) -> list[tuple[str, str]]:
    """Split on '-- CHECK: <name>' marker lines; returns [(name, sql), ...]."""
    matches = list(CHECK_MARKER.finditer(sql_text))
    if not matches:
        sys.exit(f"No '-- CHECK: <name>' markers found in {CHECKS_PATH}")
    checks = []
    for i, m in enumerate(matches):
        name = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(sql_text)
        body = sql_text[start:end].strip().rstrip(";").strip()
        checks.append((name, body))
    return checks


def main():
    env = load_env()
    sql_text = CHECKS_PATH.read_text(encoding="utf-8")
    checks = parse_checks(sql_text)

    failures = 0
    with psycopg.connect(env["DATABASE_URL"], connect_timeout=15) as conn:
        with conn.cursor() as cur:
            for name, body in checks:
                cur.execute(body)
                rows = cur.fetchall()
                cols = [d.name for d in cur.description] if cur.description else []
                if not rows:
                    print(f"PASS  {name}")
                else:
                    failures += 1
                    print(f"FAIL  {name}  ({len(rows)} violating row(s))")
                    print(f"      columns: {cols}")
                    for r in rows[:10]:
                        print(f"      {r}")
                    if len(rows) > 10:
                        print(f"      ... and {len(rows) - 10} more")

    print()
    if failures:
        print(f"{failures}/{len(checks)} checks FAILED.")
        sys.exit(1)
    else:
        print(f"All {len(checks)} checks PASSED.")


if __name__ == "__main__":
    main()
