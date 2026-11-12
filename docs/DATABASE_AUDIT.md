# ARAA PRIVATE LIMITED — DATABASE ARCHITECTURE & SCHEMA AUDIT (`DATABASE_AUDIT.md`)

**Audit Date:** 2026-11-12  
**Database Engines Inspected:** SQLite 3 (WAL mode, `backend/tradepro.db`) & PostgreSQL 16 (`deploy/postgres_schema.sql`, `backend/pg_compat.py`)  
**Migration Engine:** `backend/migrations.py` (`schema_migrations` with SHA-256 checksum verification)

---

## 1. Current Database Inventory

### A. Versioned Company & Prop Desk Tables (`backend/migrations.py` — Migrations `001` to `003`)
All monetary INR columns in these tables use **exact 64-bit integer `paise`** (`BIGINT` / `INTEGER`), and crypto quantities/prices use **exact `Decimal` strings** (`TEXT`), eliminating IEEE-754 floating-point drift:
1. `schema_migrations` — Tracks applied migration versions, timestamps, and SHA-256 checksums.
2. `companies` — Legal entity registration (`company_code`, `legal_name`, `cin_or_reg_no`, `pan`, `gstin`, `proprietary_only`, `compliance_status`).
3. `roles` — Role hierarchy (`role_code`, `role_name`, `hierarchy_level`).
4. `company_permissions` & `role_permissions` — Granular module permissions mapped to roles.
5. `company_users` — Employee accounts with PBKDF2-SHA256 password hashes, encrypted TOTP MFA secrets (`mfa_secret_enc`), single-use backup code hashes, and brute-force lockout counters.
6. `company_sessions` — Active operator sessions with IP, User-Agent, MFA verification flag, TTL, and instant revocation.
7. `trading_approvals` — Maker-checker dual-control approval records (`requested_by != approved_by`).
8. `company_audit_logs` — Immutable append-only audit log with `before_json` and `after_json`.
9. `system_events` — Infrastructure and security event log.
10. `company_trading_accounts` — Company-owned broker accounts (`ZERODHA`, `COINDCX`).
11. `broker_account_secrets` — Fernet-encrypted API keys, secrets, access tokens, key fingerprints, static egress IP, and `withdrawal_disabled` flags.
12. `broker_capabilities` — Per-account allowed segments (`NSE`, `BSE`, `COINDCX_SPOT`), order types, and zero-leverage locks.
13. `company_capital_pools` — Strictly isolated `POOL_INDIA_INR` and `POOL_CRYPTO_SPOT` pools in integer `paise`.
14. `capital_allocations` — Per-strategy capital allocations within a single pool.
15. `company_capital_movements` — Auditable capital additions, withdrawals, fee expenses, and tax expenses.
16. `company_strategies` & `company_strategy_versions` — Immutable version-locked strategy configurations.
17. `company_signals` — Explainable AI trade proposals (`entry`, `stop_loss`, `target`, `risk_reward_ratio`, `confidence_score`, `explanation`, `risk_assessment`).
18. `company_risk_policies` & `company_risk_events` — Independent pre-trade risk limits, IST session windows, pause/emergency-stop flags, and veto logs.
19. `order_intents` — Pre-submission order intents with mandatory unique `idempotency_key`.
20. `broker_orders` — 16-state OMS order records (`CREATED`..`RECONCILIATION_REQUIRED`).
21. `broker_executions` — Confirmed partial and full broker fills (`provider_trade_id`, `fill_qty_str`, `fill_price_str`, `fee_paise`, `tax_paise`).
22. `company_positions` — Open and closed positions strictly partitioned by `pool_id` and `execution_mode` (`PAPER` vs `LIVE`).
23. `company_ledger_entries` — Append-only double-entry financial ledger for `LIVE` broker-confirmed settlements and accounting adjustments.
24. `reconciliation_runs` & `reconciliation_differences` — Automated local-vs-broker state comparison and mismatch freeze records.
25. `compliance_records` — Regulatory and operational readiness evidence register.

### B. Legacy / Retail Tables (`backend/database.py` — 67 Base Tables)
Preserved for backward compatibility with existing tests and terminal features (`users`, `sessions`, `instruments`, `market_assets`, `market_prices`, `ai_models`, `ai_signals`, `ai_decisions`, `ai_committee_logs`, `backtest_runs`, `event_outbox`, `system_incidents`, etc.).

---

## 2. Database Gaps Identified & Scheduled for Migration `004`–`008`

To satisfy **Part 2 (Company ERP & Accounting)**, **Part 3 (Corporate Website & CMS)**, **Part 4 (Brokerage Platform)**, **Part 5 (Wallet Infrastructure)**, **Part 8 (10 Independent Ledgers)**, **Part 9 (Customer Platform)**, and **Part 13 (Section 29 Database Modules)**, the following versioned migrations are being added:

1. **Migration `004_company_erp_governance_hr_finance`:**
   - `directors`, `shareholders`, `share_capital_records`, `board_meetings`, `board_resolutions`, `shareholder_approvals`, `corporate_documents`, `statutory_registers`, `director_disclosures`, `compliance_calendar`, `company_bank_accounts`, `company_assets`, `vendors`, `purchase_orders`, `expense_records`, `departments`, `employees`, `recruitment_postings`, `payroll_records`, `leave_requests`, `internal_announcements`, `company_projects`, `accounting_chart_of_accounts`, `accounting_entries`, `financial_transactions`, `tax_records`, `bank_reconciliations`, `financial_reports`.
2. **Migration `005_corporate_website_cms`:**
   - `cms_theme_settings`, `cms_pages`, `cms_page_versions`, `cms_sections`, `cms_menus`, `cms_media`, `cms_news`, `cms_careers`, `cms_contact_enquiries`, `cms_analytics`, `cms_backups`.
3. **Migration `006_araa_brokerage_platform`:**
   - `service_authorization_register`, `brokerage_company_config`, `brokerage_products`, `customer_profiles`, `kyc_records_v2`, `aml_screenings`, `customer_permissions`, `brokerage_accounts`, `brokerage_orders`, `broker_routes`, `brokerage_fees`, `brokerage_disputes`, `customer_statements`, `regulatory_reports`.
4. **Migration `007_araa_wallet_infrastructure`:**
   - `wallet_accounts` (supporting `TREASURY_WALLET_A` and gated `CUSTOMER_WALLET_B`), `wallet_assets`, `wallet_networks`, `wallet_addresses`, `wallet_transactions` (11-state lifecycle), `wallet_ledger_entries` (immutable double-entry), `wallet_approvals`, `blockchain_events`, `wallet_key_policies`.
5. **Migration `008_autonomous_prop_bot_and_risk_extensions`:**
   - `company_autonomous_bots`, `company_bot_activity_logs`, `company_bot_daily_reports`, `risk_checks`, `trading_limits`, `kill_switch_events`, `authentication_events`, `security_alerts`, `approval_records`, `multi_ledger_registry`.

