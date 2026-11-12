"""
ARAA Company Trading Platform — PostgreSQL 16 Dialect Translation & Migration Export.

Provides:
1. Quote-aware SQL placeholder & DDL translation (`translate_sql_sqlite_to_postgres`)
   for running ARAA's SQLite schema and versioned migrations on PostgreSQL 16.
2. Full SQL bundle export (`export_postgres_sql_bundle`) covering base tables plus
   Phases 2-9 company tables (`MIGRATIONS` from `backend/migrations.py`).
"""

import re
from typing import Any, List, Tuple

try:
    from database import SCHEMA
    from migrations import MIGRATIONS
except ImportError:
    from backend.database import SCHEMA
    from backend.migrations import MIGRATIONS


def translate_sql_sqlite_to_postgres(sql: str) -> str:
    """Translates SQLite DDL & DML statements cleanly into PostgreSQL 16 syntax."""
    out = sql
    out = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "BIGSERIAL PRIMARY KEY", out, flags=re.IGNORECASE)
    out = re.sub(r"\bAUTOINCREMENT\b", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\bBLOB\b", "BYTEA", out, flags=re.IGNORECASE)
    out = re.sub(r"\bREAL\b", "DOUBLE PRECISION", out, flags=re.IGNORECASE)
    # Strip SQLite-only PRAGMA lines if present
    out = re.sub(r"(?im)^\s*PRAGMA\s+[^;]+;\s*$", "", out)

    # Convert INSERT OR IGNORE INTO tbl(...) VALUES(...) -> INSERT INTO tbl(...) VALUES(...) ON CONFLICT DO NOTHING
    def _replace_insert_ignore(match: re.Match) -> str:
        stmt = match.group(1)
        stmt = re.sub(r"(?i)^INSERT\s+OR\s+IGNORE\s+INTO\s+", "INSERT INTO ", stmt, count=1)
        return stmt.rstrip() + " ON CONFLICT DO NOTHING;"

    out = re.sub(r"(INSERT\s+OR\s+IGNORE\s+INTO\s+[^;]+);", _replace_insert_ignore, out, flags=re.IGNORECASE)
    return out


def convert_qmark_params(sql: str, params: Tuple[Any, ...]) -> Tuple[str, Tuple[Any, ...]]:
    """Converts `?` placeholders outside single/double quotes into `%s` for psycopg / Postgres."""
    res: List[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'" and not in_double:
            if in_single and i + 1 < n and sql[i + 1] == "'":
                res.append("''")
                i += 2
                continue
            in_single = not in_single
            res.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            res.append(ch)
        elif ch == "?" and not in_single and not in_double:
            res.append("%s")
        else:
            res.append(ch)
        i += 1
    return "".join(res), params


def export_postgres_sql_bundle() -> str:
    """Exports the complete SQLite base schema + Phase 2-9 company migrations as PostgreSQL 16 DDL."""
    chunks = [
        "-- ARAA Company Proprietary Trading Platform — PostgreSQL 16 Production Schema",
        "-- Generated automatically from backend/database.py + backend/migrations.py",
        "",
        "CREATE TABLE IF NOT EXISTS schema_migrations(",
        "  version TEXT PRIMARY KEY,",
        "  name TEXT NOT NULL,",
        "  applied_at DOUBLE PRECISION NOT NULL,",
        "  checksum TEXT NOT NULL",
        ");",
        "",
        "-- === BASE CORE SCHEMA ===",
        translate_sql_sqlite_to_postgres(SCHEMA),
    ]
    for version, name, script in MIGRATIONS:
        chunks.append(f"\n-- === MIGRATION {version}: {name} ===")
        chunks.append(translate_sql_sqlite_to_postgres(script))
    return "\n".join(chunks)

