# ARAA Company Proprietary Trading — Production Readiness Checklist (`PRODUCTION_READINESS.md`)

Run `.venv/bin/python scripts/preflight_check.py` before switching `TRADING_MODE=PAPER` -> `TRADING_MODE=LIVE`.

## Mandatory Gates Before Controlled Live Pilot
1. **Security & Proprietary Isolation**
   - [ ] `AUTH_STRICT=1` enabled (legacy test user fallback disabled)
   - [ ] `COMPANY_ONLY_MODE=1` enabled (customer deposits, withdrawals, UPI, Razorpay, wallets blocked with HTTP `403`)
   - [ ] `REQUIRE_ENCRYPTION=1` + high-entropy `SECRETS_KEY` safely backed up off-host
   - [ ] `SEED_DEMO_USERS=0`
   - [ ] Initial `COMPANY_DIRECTOR` created via `/company/` and **RFC-6238 TOTP MFA** enabled on every staff account
2. **Infrastructure & Database**
   - [ ] PostgreSQL 16 provisioned from `deploy/postgres_schema.sql` (`DATABASE_URL=postgresql://...`)
   - [ ] HTTPS TLS active in front of Gunicorn via `deploy/nginx.conf`
   - [ ] Automated daily backup cron running `./scripts/backup_db.sh` and tested with `./scripts/restore_db.sh`
3. **Broker & Exchange Credentials**
   - [ ] Zerodha corporate Kite Connect app approved, static egress IP whitelisted, daily OAuth login verified (`POOL_INDIA_INR`)
   - [ ] CoinDCX Spot-only company API key verified with **Withdrawals Disabled** (`POOL_CRYPTO_SPOT`)
4. **Risk Guardian & Reconciliation Controls**
   - [ ] Pool caps, max order value, max daily loss, and mandatory stop-loss confirmed in **Risk Guardian**
   - [ ] Initial reconciliation run returns `MATCHED` (`0` open discrepancies) on both pools
   - [ ] Dual-control Maker-Checker approval (`LIVE_ACTIVATION`) signed by two authorized officers
5. **Corporate, Regulatory & Legal Review**
   - [ ] Corporate proprietorship / company incorporation records recorded in **Company & Compliance**
   - [ ] SEBI algorithmic trading / exchange permissions (Zerodha India equities) verified by counsel
   - [ ] FIU-IND VDA / tax / GST compliance verified by counsel
   - [ ] Start Live Pilot with strict minimal capital caps per pool and monitor `Reconciliation Inspector` & `Audit Logs`.

