# ARAA Company Trading Platform — Installation & Operations Guide (`INSTALLATION.md`)

## 1. Local Development (SQLite)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Generate strong SECRETS_KEY & set ADMIN_USERNAME / ADMIN_PASSWORD in .env
PORT=5050 .venv/bin/python -m backend.app
```
Open:
- Company Control Center: `http://localhost:5050/company`
- Trading Terminal: `http://localhost:5050/`
- Master Admin Panel: `http://localhost:5050/admin`
- OpenAPI / Swagger Docs: `http://localhost:5050/docs`

## 2. Production Stack (PostgreSQL 16 + Redis 7 + Nginx TLS)
1. Export clean PostgreSQL 16 DDL covering base tables and all versioned company migrations:
   ```bash
   .venv/bin/python scripts/export_postgres_schema.py
   ```
   Output: `deploy/postgres_schema.sql`.
2. Populate `.env` with strong secrets:
   - `SECRETS_KEY` (required when `REQUIRE_ENCRYPTION=1`)
   - `AUTH_STRICT=1`
   - `COMPANY_ONLY_MODE=1`
   - `TRADING_MODE=PAPER` (switch to `LIVE` only after completing `docs/PRODUCTION_READINESS.md`)
   - `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL`
   - `STATIC_EGRESS_IP`
3. Start services:
   ```bash
   docker compose --profile prod-tls up -d --build
   ```

## 3. Automated Backups & Restore Drills
- **Backup** (supports both SQLite online `.backup` + `PRAGMA integrity_check` and `pg_dump` when `DATABASE_URL` starts with `postgres`):
  ```bash
  ./scripts/backup_db.sh /var/backups/araa
  ```
- **Restore**:
  ```bash
  ./scripts/restore_db.sh /var/backups/araa/<backup_file>
  ```

## 4. Verification & Preflight
```bash
.venv/bin/python scripts/preflight_check.py
.venv/bin/python -m unittest discover -s tests -p "test_*.py" -v
```

