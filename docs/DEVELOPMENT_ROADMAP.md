# ARAA Company Trading Platform — Implementation & Development Roadmap (`DEVELOPMENT_ROADMAP.md`)

**Execution Strategy:** 4 Practical Stages organized into the 12 Phases required by the Company Platform Architecture. Every phase ends with automated tests (`unittest`), zero broken regressions, and a `COMPLETE / PARTIAL / NOT IMPLEMENTED` verification report.

---

## Pre-Phase 2 Architecture Decisions Required
Before modifying runtime backend/UI code in Phase 2:
1. **SaaS Legacy Isolation:** Confirm moving all customer-facing SaaS tables/endpoints (`deposits`, `withdrawals`, `profit_links`, `upi_gateway`, `razorpay_gateway`, `saas_manager`) to disabled/archived status so ARAA operates **100% as a company-owned proprietary platform**.
2. **Frontend Stack Decision:** Recommended path is **extending the existing Vanilla HTML/CSS/JS frontend + Admin Panel** with the White Theme + Dark Navy Sidebar (preserving `app.js`, TradingView widgets, and modals with zero rewrite risk), rather than rewriting 20+ screens in React from scratch. *(Can add a React build only if explicitly requested.)*

---

## Stage 1 — Audit, Security Repair, Company RBAC & Capital Pools

### Phase 1 — Existing Project Audit & Security Repair *(Current Phase — Audit Complete, Repair Next)*
- **Completed:**
  - Inspected all backend, frontend, admin, gateway, deployment, and test files.
  - Created `docs/PROJECT_AUDIT.md`, `docs/EXISTING_FEATURES.md`, `docs/MISSING_FEATURES.md`, `docs/SECURITY_AUDIT.md`, `docs/DEVELOPMENT_ROADMAP.md`.
- **Code Repair Tasks (Next immediate step before Phase 2):**
  - Remove hardcoded `UNIVERSAL_KEY` literal in `backend/gemini_advisor.py` and default signing/merchant key literals in `backend/saas_manager.py` / `backend/upi_gateway.py`.
  - Remove unauthenticated user fallback in `backend/enterprise_v1_api.py` (update unit tests to pass explicit test `X-Token` / `X-Admin-Token` headers).
  - Enforce mandatory `SECRETS_KEY` in `LIVE` mode and set `SEED_DEMO_USERS` default to `"0"`.
  - Disable `fallback_to_paper` inside `backend/real_broker.py`.

### Phase 2 — Company Architecture, Roles, MFA & Versioned Database Migrations
- Create versioned SQL migration runner (`backend/migrations/` supporting SQLite local dev and PostgreSQL production dialect abstraction).
- Add core company & RBAC tables: `companies`, `company_users`, `roles`, `permissions`, `trading_approvals`, `audit_logs`, `system_events`.
- Seed the 7 company roles (`COMPANY_DIRECTOR`, `SUPER_ADMIN`, `FINANCE_ADMIN`, `TRADING_ADMIN`, `RISK_MANAGER`, `TECHNICAL_ADMIN`, `AUDITOR`).
- Add TOTP MFA (`pyotp`), session management & revocation, and `@require_role` / `@require_permission` route guards.
- Implement `GET /api/v1/company/profile` and company employee management APIs.

### Phase 3 — Company Finance & Independent Capital Pools
- Add tables: `company_trading_accounts`, `broker_account_secrets`, `broker_capabilities`, `company_capital_pools`, `capital_allocations`.
- Implement **strictly isolated pools**:
  - `POOL_INDIA_INR` (Zerodha Kite Connect, INR stored as integer `paise`).
  - `POOL_CRYPTO_SPOT` (CoinDCX Spot, `Decimal` precision accounting).
- Hard-block any cross-pool capital read, cross-pool allocation, or automatic transfer.
- Implement `GET/POST /api/v1/company/capital-pools` and `GET /api/v1/company/portfolio`.

---

## Stage 2 — Broker Adapters (Zerodha + CoinDCX Spot)

### Phase 4 — Universal Broker Manager & Zerodha Kite Connect Integration
- Upgrade `backend/exchange_adapter.py` into `UniversalBrokerManager` + abstract 14-method `BrokerAdapter` interface (`verify_connection`, `get_profile`, `get_balances`, `get_positions`, `get_open_orders`, `get_instruments`, `get_quote`, `validate_instrument`, `calculate_margin`, `place_order`, `get_order_status`, `get_trades`, `cancel_order`, `disconnect`), resolving isolated per-account encrypted secrets.
- Build `backend/zerodha_adapter.py` implementing Kite Connect v3:
  - OAuth login URL & request-token -> access-token checksum exchange.
  - Daily token expiration tracking & renewal alerts.
  - NSE/BSE instrument master sync, LTP/OHLC quotes, funds/margins, holdings, positions, orders, trades, and order placement/modification/cancellation.
  - Build `MockZerodhaAdapter` for deterministic integration & acceptance testing.
- API routes: `/api/v1/brokers/zerodha/{connect,callback,verify,status,sync}`.

### Phase 5 — CoinDCX Company Spot-Only Integration
- Build `backend/coindcx_spot_adapter.py` wrapping official CoinDCX Spot REST APIs (`https://docs.coindcx.com/`):
  - Spot pairs only (**explicitly block futures, margin, perpetuals, leverage > 1x, and withdrawals**).
  - Official market metadata sync (min order size, step size, tick size precision).
  - Verify withdrawal permissions are disabled / reject unsafe credentials.
  - Exact balance (available + locked), order status, fill/trade history, and fee parsing.
  - Build `MockCoinDCXSpotAdapter` for automated testing.
- API routes: `/api/v1/brokers/coindcx/{connect,status,verify,sync}`.

---

## Stage 3 — AI Intent Pipeline, Risk Guardian, OMS & Reconciliation

### Phase 6 — AI Trading Engine & Immutable Strategy Management
- Add tables: `strategies`, `strategy_versions`, `strategy_allocations`, `signals`.
- Wrap existing `analysis_engine.py`, `prediction_engine.py`, `ai_committee.py`, and `quantum_engine.py` into explainable **Signal Generators** producing structured proposals (direction, entry, stop-loss, target, R:R, confidence, strategy version, explanation).
- Lock strategy versions (`strategy_versions`) upon activation; track paper vs. live metrics separately.
- Disconnect any direct live-order execution from `bot_engine.py`.

### Phase 7 — Independent Risk Guardian
- Upgrade `backend/risk_engine.py` with `risk_policies` and `risk_events`:
  - Per-pool & per-strategy capital caps, max order value, max position size, daily loss / drawdown circuit breakers, quote freshness check, stop-loss mandatory rule, market-session trading windows (`09:15–15:30 IST` for NSE/BSE; `24/7` for CoinDCX Spot), duplicate-order suppression, and **reconciliation-mismatch auto-halt**.
- API routes: `/api/v1/risk/{policies,status,events}` and `/api/v1/trading/{start,pause,stop,emergency-stop,flatten-preview,flatten-confirm,status}`.

### Phase 8 — 16-State Order Management System (OMS) & Paper/Live Isolation
- Add tables: `order_intents`, `broker_orders`, `executions`, `company_positions`, `broker_webhook_events`, `trading_sessions`.
- Enforce the exact 16-state lifecycle (`CREATED -> RISK_PENDING -> APPROVED -> SUBMISSION_PENDING -> SUBMITTED -> ACKNOWLEDGED -> OPEN -> PARTIALLY_FILLED -> FILLED`, plus `RISK_REJECTED`, `CANCEL_PENDING`, `CANCELLED`, `REJECTED`, `UNKNOWN`, `RECONCILIATION_REQUIRED`, `FAILED`).
- Require unique `idempotency_key` on all `POST /api/v1/orders/intents`; timeout transitions to `UNKNOWN` (requiring status query + reconciliation, never blind retry).
- Guarantee **complete Paper vs. Live isolation** (no live-to-paper fallback; live requires all 10 readiness gates).

### Phase 9 — Company Ledger & Automated Reconciliation Engine
- Upgrade `backend/financial_ledger.py` using integer `paise` (INR) and `Decimal` strings (`company_ledger_entries`) with strict distinction between broker-confirmed settlements and manual adjustments.
- Build `backend/reconciliation_service.py` (`reconciliation_runs`, `reconciliation_differences`):
  - Compare local vs. broker balances, orders, fills, positions, and fees on connect, before live activation, after executions/cancellations, and periodically.
  - Preserve raw broker JSON payload, freeze new entries on affected account upon mismatch, and require operator verification before resuming.
- API routes: `/api/v1/reconciliation/run`, `/api/v1/reconciliation`, `/api/v1/company/ledger`.

---

## Stage 4 — Control Center UI, Backtest Upgrades, Security Tests & Production Deploy

### Phase 10 — Company Dashboard, Trading Control Center & 20-Page Admin Panel
- Upgrade UI to clean **White Fintech Theme + Dark Navy Sidebar** (preserving existing TradingView & terminal structure unless React SPA is explicitly commissioned):
  - **Company Dashboard**: Total valuation (reporting only) + separate India (INR) and Crypto (CoinDCX Spot) pool cards, P&L, broker health, reconciliation badges.
  - **Separate India & Crypto Trading Control Centers**: Start/Pause/Stop/Emergency Stop + 2-step Flatten preview/confirm.
  - **Admin & Compliance Pages (20 views)**: Company profile, Employee RBAC/MFA, Capital allocation, Zerodha daily login/status, CoinDCX status, Strategies, Risk policies, OMS orders, Executions, Positions, Ledger, Reconciliation inspector, Reports, Audit logs, System health, Compliance evidence checklist.

### Phase 11 — Backtesting Upgrades, Monitoring & Operational Alerts
- Add out-of-sample / walk-forward split, MAE/MFE, expectancy, NSE market-hours filtering, and strict separation of Backtest vs. Paper vs. Live reports.
- Wire broker health, feed staleness, reconciliation alerts, and daily reports to Slack/SMTP/Telegram/Admin alerts.

### Phase 12 — Full Acceptance/Security Tests, Postgres + Docker/Nginx & Controlled Live Pilot
- Implement all **Unit, Integration (`MockZerodhaAdapter`, `MockCoinDCXSpotAdapter`), Security, and 10 Acceptance Tests** (pool isolation, invalid key lock, rejected order safety, partial fill precision, timeout duplicate protection, reconciliation halt, paper/live separation, audit completeness).
- Upgrade `Dockerfile` & `docker-compose.yml` for **PostgreSQL + Redis + Backend + Worker + Nginx HTTPS**, backup/restore scripts (`pg_dump`), health checks, and runbooks (`INSTALLATION.md`, `BROKER_SETUP.md`, `ZERODHA_SETUP.md`, `COINDCX_SETUP.md`, `PRODUCTION_READINESS.md`).
- **Live Pilot Gate:** Test only with company static IP, registered Kite Connect app, withdrawal-disabled CoinDCX Spot API key, legal/compliance sign-off, and small initial capital limits.

