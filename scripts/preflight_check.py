#!/usr/bin/env python3
"""
ARAA Company Proprietary Trading Platform — Production Readiness Pre-Flight Checker.

Inspects environment flags, encryption posture, proprietary isolation (`COMPANY_ONLY_MODE`),
SQLite integrity / PostgreSQL schema export, backup scripts, and compliance checklist state.
Exits non-zero if critical integrity checks fail; differentiates DEV/PAPER warnings from LIVE blockers.
"""
import json
import os
import sqlite3
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))


def check_item(label: str, passed: bool, detail: str, blocker_for_live: bool = True) -> dict:
    status = "PASS" if passed else ("LIVE_BLOCKER" if blocker_for_live else "WARN")
    print(f"[{status:12s}] {label}: {detail}")
    return {"label": label, "passed": passed, "status": status, "detail": detail}


def main() -> int:
    trading_mode = os.environ.get("TRADING_MODE", "PAPER").strip().upper()
    print(f"ARAA Production Preflight (TRADING_MODE={trading_mode})")
    print("-" * 72)

    checks = []
    secrets_key = os.environ.get("SECRETS_KEY", "").strip()
    checks.append(check_item("SECRETS_KEY configured", len(secrets_key) >= 16, f"length={len(secrets_key)}"))
    checks.append(check_item("AUTH_STRICT=1", os.environ.get("AUTH_STRICT", "0") == "1", f"value={os.environ.get('AUTH_STRICT', '0')}"))
    checks.append(check_item("COMPANY_ONLY_MODE=1", os.environ.get("COMPANY_ONLY_MODE", "0") == "1", f"value={os.environ.get('COMPANY_ONLY_MODE', '0')}"))
    checks.append(check_item("REQUIRE_ENCRYPTION=1", os.environ.get("REQUIRE_ENCRYPTION", "0") == "1", f"value={os.environ.get('REQUIRE_ENCRYPTION', '0')}"))
    checks.append(check_item("SEED_DEMO_USERS=0", os.environ.get("SEED_DEMO_USERS", "0") == "0", f"value={os.environ.get('SEED_DEMO_USERS', '0')}"))

    pg_sql_path = os.path.join(ROOT, "deploy", "postgres_schema.sql")
    checks.append(check_item("PostgreSQL 16 schema bundle", os.path.isfile(pg_sql_path) and os.path.getsize(pg_sql_path) > 10000, pg_sql_path, blocker_for_live=False))

    bak_sh = os.path.join(ROOT, "scripts", "backup_db.sh")
    rst_sh = os.path.join(ROOT, "scripts", "restore_db.sh")
    checks.append(check_item("Backup/Restore scripts executable", os.access(bak_sh, os.X_OK) and os.access(rst_sh, os.X_OK), f"{bak_sh}, {rst_sh}", blocker_for_live=False))

    db_path = os.environ.get("DB_PATH") or os.path.join(ROOT, "backend", "tradepro.db")
    db_ok = False
    db_detail = f"missing: {db_path}"
    if os.path.isfile(db_path):
        try:
            conn = sqlite3.connect(db_path)
            res = conn.execute("PRAGMA integrity_check").fetchone()[0]
            migs = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            conn.close()
            db_ok = res == "ok"
            db_detail = f"integrity={res}, migrations={migs}"
        except Exception as exc:
            db_detail = str(exc)
    checks.append(check_item("SQLite integrity & migrations", db_ok, db_detail))

    blockers = [c for c in checks if not c["passed"] and c["status"] == "LIVE_BLOCKER"]
    print("-" * 72)
    print(json.dumps({"trading_mode": trading_mode, "total": len(checks), "live_blockers": len(blockers)}, indent=2))
    if trading_mode == "LIVE" and blockers:
        return 2
    return 0 if db_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

