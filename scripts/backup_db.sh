#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${1:-./backups}"
TS="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

if [[ -n "${DATABASE_URL:-}" ]]; then
  OUT_FILE="${BACKUP_DIR}/araa_postgres_${TS}.dump"
  echo "[BACKUP] Dumping PostgreSQL to ${OUT_FILE}..."
  pg_dump --format=custom --no-owner --file="$OUT_FILE" "$DATABASE_URL"
  echo "[BACKUP] PostgreSQL backup complete: ${OUT_FILE}"
else
  DB_FILE="${DB_PATH:-./backend/tradepro.db}"
  OUT_FILE="${BACKUP_DIR}/araa_sqlite_${TS}.db"
  echo "[BACKUP] Creating online SQLite backup from ${DB_FILE} to ${OUT_FILE}..."
  python3 -c "import sqlite3; src=sqlite3.connect('${DB_FILE}'); dst=sqlite3.connect('${OUT_FILE}'); src.backup(dst); dst.close(); src.close()"
  python3 -c "import sqlite3; c=sqlite3.connect('${OUT_FILE}'); res=c.execute('PRAGMA integrity_check').fetchone()[0]; assert res=='ok', res; print('[BACKUP] SQLite integrity_check:', res)"
fi

