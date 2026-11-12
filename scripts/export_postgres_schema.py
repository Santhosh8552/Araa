#!/usr/bin/env python3
"""Exports ARAA's SQLite schema and all versioned company migrations into deploy/postgres_schema.sql."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from pg_compat import export_postgres_sql_bundle  # noqa: E402


def main() -> None:
    out_path = os.path.join(ROOT, "deploy", "postgres_schema.sql")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    sql = export_postgres_sql_bundle()
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(sql)
    print(f"[PG_EXPORT] Wrote PostgreSQL 16 schema bundle ({len(sql)} bytes) -> {out_path}")


if __name__ == "__main__":
    main()

