#!/usr/bin/env bash
set -euo pipefail

BACKUP_FILE="${1:-}"
if [[ -z "$BACKUP_FILE" || ! -f "$BACKUP_FILE" ]]; then
  echo "Usage: $0 <path-to-backup-file>"
  exit 1
fi

if [[ -n "${DATABASE_URL:-}" && "$BACKUP_FILE" == *.dump ]]; then
  echo "[RESTORE] Restoring PostgreSQL from ${BACKUP_FILE}..."
  pg_restore --clean --if-exists --no-owner --dbname="$DATABASE_URL" "$BACKUP_FILE"
  echo "[RESTORE] PostgreSQL restore complete."
else
  DB_FILE="${DB_PATH:-./backend/tradepro.db}"
  echo "[RESTORE] Verifying backup ${BACKUP_FILE} before restoring to ${DB_FILE}..."
  python3 -c "import sqlite3; c=sqlite3.connect('${BACKUP_FILE}'); res=c.execute('PRAGMA integrity_check').fetchone()[0]; assert res=='ok', res"
  cp "$BACKUP_FILE" "$DB_FILE"
  echo "[RESTORE] SQLite restore complete: ${DB_FILE}"
fi

