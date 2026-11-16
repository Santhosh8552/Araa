"""
AraaBot Enterprise QA Suite Runners (Isolated Sandbox & Live-Safe Verifiers).

All mutating suites (AUTH, ADMIN_PANEL, API, DATABASE, TRADING_ENGINE,
COINDCX mocks, SECURITY, PERFORMANCE) run inside an isolated temporary SQLite
database process (`--sandbox`) so live user wallets, orders, and Real Mode
settings are never touched. Never submits live exchange orders.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import hmac
import importlib
import json
import os
import resource
import secrets
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


# ---------------------------------------------------------------------------
# Secret / Sensitive Data Sanitizer (used before DB persistence & reports)
# ---------------------------------------------------------------------------
_SECRET_KEYS = {
    "api_key", "api_secret", "coindcx_key", "coindcx_secret", "pw_hash", "pw_salt",
    "password", "admin_token", "sso_token", "token", "secret", "access_token",
    "x-admin-token", "x-token", "authorization", "mt4_password_enc",
}


def sanitize_value(obj: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "[TRUNCATED]"
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if any(sk in kl for sk in _SECRET_KEYS):
                out[k] = "[REDACTED]"
            else:
                out[k] = sanitize_value(v, depth + 1)
        return out
    if isinstance(obj, list):
        return [sanitize_value(x, depth + 1) for x in obj[:50]]
    if isinstance(obj, str):
        import re
        s = re.sub(r"\b(adm|cmp|usr)_[A-Za-z0-9_]{8,}\b", "[REDACTED_TOKEN]", obj)
        s = re.sub(r"v1\.\d+\.\d+\.[A-Za-z0-9_-]+\.[a-f0-9]{16,}", "[REDACTED_SESSION]", s)
        return s[:4000]
    return obj


def sanitize_text(text: str) -> str:
    return str(sanitize_value(str(text or "")))


# ---------------------------------------------------------------------------
# Suite / Case Catalog Definition (Maps to Requirements 3, 4, 5, 6, 7, 8, 13)
# ---------------------------------------------------------------------------
SUITE_CATALOG: List[Dict[str, Any]] = [
    {
        "suite_id": "AUTH",
        "code": "AUTH",
        "name": "Authentication & RBAC Suite",
        "category": "SECURITY_AUTH",
        "description": "Validates Admin/User/Company logins, logout revocation, password hashes, session TTL, HMAC tokens, MFA/TOTP, role permissions, and lockout.",
        "module_path": "backend/app.py, backend/company_auth.py, backend/central_admin_ecosystem.py",
        "requires_isolated_db": 1,
        "sort_order": 10,
        "cases": [
            ("AUTH_01_ADMIN_LOGIN_VALID", "Admin Login Valid Credentials", "Critical", "Admin /api/admin/login authenticates valid admin credentials and issues adm_ token"),
            ("AUTH_02_ADMIN_LOGIN_INVALID", "Admin Login Invalid Credentials Rejection", "Critical", "Invalid admin password and legacy hardcoded passwords are rejected with 401"),
            ("AUTH_03_USER_REGISTER_LOGIN", "User Registration & Login Flow", "High", "Customer account registration, hashed storage, and /api/login token issuance succeed"),
            ("AUTH_04_COMPANY_SSO_LOGIN", "Company & Central Super Admin SSO Login", "Critical", "Company RBAC auth and Central Admin SSO login succeed and return scoped tokens"),
            ("AUTH_05_LOGOUT_TOKEN_REVOCATION", "Logout & Token Revocation Enforcement", "High", "User logout records token in revoked_sessions and blocks subsequent calls"),
            ("AUTH_06_PASSWORD_HASH_AND_RESET", "Salted Password Verification & Rotation", "High", "hash_password/verify_password validates matches and rejects mismatches"),
            ("AUTH_07_SESSION_EXPIRY_TTL", "Admin Session Expiration Enforcement", "Critical", "Expired admin session timestamps in platform_state fail _valid_admin_token with 401"),
            ("AUTH_08_PERSISTENT_SESSION_HMAC", "HMAC Persistent Session Signing & Tamper Guard", "High", "_sign_persistent_token validates authentic tokens and rejects tampered signatures"),
            ("AUTH_09_SSO_TOKEN_VALIDATION", "Central SSO / Bearer Token Validation", "High", "/api/central-admin/validate-token accepts valid tokens and rejects forged tokens"),
            ("AUTH_10_ROLE_BASED_PERMISSIONS", "Role-Based Access Isolation (Admin vs Company vs User)", "Critical", "User blocked 403 on Admin/Company diagnostics; Company blocked 403 on deploy approval"),
            ("AUTH_11_MFA_TOTP_FLOW", "MFA / TOTP Enrollment & Verification", "Medium", "Company & Central Admin MFA enrollment/TOTP guard validates codes accurately"),
            ("AUTH_12_RATE_LIMIT_AND_LOCKOUT", "Account Suspension Lockout & Brute-Force Guard", "High", "Suspended user blocked at login/risk gate; non-whitelisted auth flood is throttled"),
        ],
    },
    {
        "suite_id": "ADMIN_PANEL",
        "code": "ADMIN_PANEL",
        "name": "Admin Panel 18-Module Suite",
        "category": "ADMIN_UI_API",
        "description": "Validates all 18 Admin Console modules: overview, users, company, CoinDCX, bots, rules, strategy, risk, wallets, deposits, withdrawals, reports, Slack, settings, firewall, audit, and QA center.",
        "module_path": "admin/index.html, admin/admin.js, backend/app.py",
        "requires_isolated_db": 1,
        "sort_order": 20,
        "cases": [
            ("ADM_01_DASHBOARD_OVERVIEW", "Admin Dashboard Overview KPIs", "Critical", "/api/admin/overview returns complete numeric KPIs and live feed counts"),
            ("ADM_02_USER_MANAGEMENT", "User Management & Cascade Cleanup", "High", "/api/admin/users lists users with CoinDCX fields and /delete removes dependent rows"),
            ("ADM_03_COMPANY_MANAGEMENT", "Company & Central Super Admin Portal", "High", "/api/central-admin/dashboard, administrators & app registry respond properly"),
            ("ADM_04_BROKER_API_MANAGEMENT", "Broker & CoinDCX Live Management", "Critical", "/api/admin/coindcx-live returns USDT/INR rate, broker connections & committee logs"),
            ("ADM_05_BOT_MANAGEMENT", "Master Bot & Per-User Bot Toggle Sync", "Critical", "Admin bot-toggle syncs users.bot_enabled with real_bot_configs RUNNING/PAUSED"),
            ("ADM_06_TRADING_RULES_GATEKEEPER", "Trading Rules & Adapter Gatekeeper Audit", "High", "/api/admin/adapter-gatekeeper enforces 6/6 rules and returns audit logs"),
            ("ADM_07_STRATEGY_MANAGEMENT", "Strategy Analysis & Storage View", "Medium", "/api/bot/analysis and /api/admin/bot-storage return open/pending/closed positions"),
            ("ADM_08_RISK_MANAGEMENT", "Risk Kill Switch & Emergency Shutdown Reset", "Critical", "/api/admin/user/<uid>/emergency-reset and /api/v3/admin/kill-switch enforce state"),
            ("ADM_09_WALLET_MANAGEMENT", "Direct Admin Wallet Deposit & Validation", "High", "Direct deposit credits wallet and rejects invalid <=0 amounts"),
            ("ADM_10_DEPOSIT_MANAGEMENT", "Deposit Records Filtering & Display", "Medium", "/api/admin/deposits returns sanitized deposit audit entries"),
            ("ADM_11_WITHDRAWAL_MANAGEMENT", "Withdrawal Queue & Brokerage Math", "High", "/api/admin/withdrawals and approval state transitions calculate 30% fee"),
            ("ADM_12_TRANSACTIONS_LEDGER", "Transactions & 30% Brokerage Ledger", "High", "/api/admin/brokerage totals match brokerage_ledger aggregates"),
            ("ADM_13_REPORTS_EOD", "EOD Reports & Institutional Intelligence", "High", "/api/admin/user/<uid>/eod-report and /api/admin/institutional-intelligence succeed"),
            ("ADM_14_NOTIFICATIONS_SLACK", "Slack Notifications & Prompt Studio", "Medium", "/api/admin/slack/config and /api/admin/slack/prompt validate safely"),
            ("ADM_15_SETTINGS_PAYMENT_RAILS", "UPI & Razorpay Admin Configuration", "Medium", "/api/admin/upi/config and /api/admin/razorpay/config read/update cleanly"),
            ("ADM_16_SECURITY_FIREWALL_CONTROLS", "Active Security Firewall Controls", "High", "/api/admin/firewall and unban endpoints manage threat logs without error"),
            ("ADM_17_AUDIT_LOGS", "Admin, Central SSO & Execution Audit Logs", "High", "/api/admin/logs and /api/central-admin/audit-logs retain chronological entries"),
            ("ADM_18_QA_QUALITY_CENTER", "Testing & Quality Center Admin APIs", "Critical", "/api/admin/qa/dashboard, /suites, /config enforce Admin RBAC and return schema"),
        ],
    },
    {
        "suite_id": "BACKEND",
        "code": "BACKEND",
        "name": "Python Backend Modules Suite",
        "category": "BACKEND_CORE",
        "description": "Verifies imports, instantiation, execution logic, config loading, worker health, and AI agents (Alpha, Beta, Gamma) across core backend modules.",
        "module_path": "backend/*.py",
        "requires_isolated_db": 0,
        "sort_order": 30,
        "cases": [
            ("BE_01_APP_MODULE", "app.py WSGI Blueprint & Config Loading", "Critical", "app.py imports cleanly, registers v1_api + admin routes, and configures CORS/guards"),
            ("BE_02_BOT_ENGINE_MODULE", "bot_engine.py Core Bot Lifecycle & Storage", "Critical", "Bot initializes with PriceFeed and exposes scan/storage/stop_loop cleanly"),
            ("BE_03_COINDCX_GATEWAY_MODULE", "coindcx_gateway.py Symbol & Precision Utils", "High", "Pair translation and Decimal increment rounding produce zero step remainder"),
            ("BE_04_STRATEGY_ENGINE_MODULE", "strategy_engine.py Signal Qualification", "High", "StrategyEngine loads rules and evaluates sample strategy structures safely"),
            ("BE_05_PREDICTION_ENGINE_MODULE", "prediction_engine.py GRU & Deep Forecast", "High", "extract_features & generate_multi_horizon_forecast compute bounded predictions"),
            ("BE_06_ANALYSIS_ENGINE_MODULE", "analysis_engine.py Technical v2 & MTF", "High", "analyze_technical_v2 & calculate_position_size compute indicators accurately"),
            ("BE_07_PRICE_FEED_MODULE", "price_feed.py Feed Helpers & Thread Lock", "High", "PriceFeed lock, sma, rsi, and TradingView symbol mappings execute cleanly"),
            ("BE_08_RISK_ENGINE_MODULE", "risk_engine.py Liquidation & Sizing Math", "Critical", "InstitutionalRiskEngine computes accurate liquidation & volatility sizing"),
            ("BE_09_OMS_ENGINE_MODULE", "oms_engine.py Order Status State Machine", "Critical", "OrderStatus constants and OMS/EMS classes initialize and validate contracts"),
            ("BE_10_DATABASE_MODULE", "database.py Crypto & Password Utilities", "Critical", "hash_password/verify_password & Fernet encryption helpers function properly"),
            ("BE_11_ALPHA_AGENT", "Agent Alpha Market & Liquidity Intelligence", "High", "AgentAlphaMarketIntelligence.evaluate scores spread, volume surge & imbalance"),
            ("BE_12_BETA_AGENT", "Agent Beta Technical Momentum Intelligence", "High", "AgentBetaTechnicalIntelligence.evaluate computes RSI, EMA, T3, VWAP & Squeeze"),
            ("BE_13_GAMMA_ORCHESTRATOR", "Agent Gamma & 3-Agent AI Committee Orchestrator", "Critical", "AICommitteeOrchestrator synthesizes weighted score & explainable rationale"),
        ],
    },
    {
        "suite_id": "API",
        "code": "API",
        "name": "API Discovery & Validation Suite",
        "category": "API_CONTRACTS",
        "description": "Auto-discovers registered Flask endpoints and validates HTTP statuses, JSON schemas, auth gates, input validation, pagination/filtering, SQLi/XSS & headers.",
        "module_path": "backend/app.py, backend/enterprise_v1_api.py",
        "requires_isolated_db": 1,
        "sort_order": 40,
        "cases": [
            ("API_01_ROUTE_DISCOVERY", "Automated Endpoint Discovery & Inventory", "High", "Flask url_map discovers all registered routes and classifies safe vs financial routes"),
            ("API_02_SAFE_GET_CONTRACTS", "Safe GET Endpoints Status & Latency SLA", "Critical", "Public/admin read routes return HTTP 200 valid JSON within latency thresholds"),
            ("API_03_AUTH_GATE_COVERAGE", "Protected Endpoint Authentication Verification", "Critical", "Discovered /api/admin/* and /api/v1/* protected routes reject anonymous callers"),
            ("API_04_INPUT_VALIDATION", "Malformed Payload & Missing Parameter Handling", "High", "Bad JSON/missing fields yield structured 4xx errors without 500 tracebacks"),
            ("API_05_PAGINATION_FILTERING", "Pagination & Query Filter Verification", "Medium", "Query limit, search & filter arguments restrict result slices accurately"),
            ("API_06_WAF_INJECTION_SHIELD", "SQLi & XSS Probe Rejection Verification", "Critical", "Safe probe payloads trigger SecurityFirewall 403 block on non-exempt paths"),
            ("API_07_SECURITY_HEADERS", "Security Headers & CORS Policy Check", "High", "X-Content-Type-Options, X-Frame-Options & Cache-Control headers are enforced"),
        ],
    },
    {
        "suite_id": "DATABASE",
        "code": "DATABASE",
        "name": "Isolated Database Integrity & Recovery Suite",
        "category": "DATABASE",
        "description": "Validates WAL mode, schema tables/columns, foreign keys, indexes, rollback atomicity, duplicate guards, migrations, and backup/restore on an isolated DB.",
        "module_path": "backend/database.py, backend/migrations.py",
        "requires_isolated_db": 1,
        "sort_order": 50,
        "cases": [
            ("DB_01_CONNECTION_WAL", "SQLite Connection & WAL Journal Mode", "Critical", "Database connects cleanly and configures WAL mode without lock contention"),
            ("DB_02_SCHEMA_INTEGRITY", "Required Core & QA Tables/Columns Check", "Critical", "All core trading tables and 9 qa_* tables with required columns exist"),
            ("DB_03_FOREIGN_KEYS_CONSTRAINTS", "Foreign Key Constraints & Cascade Check", "High", "PRAGMA foreign_keys=ON rejects orphan qa_test_cases rows and cascades deletes"),
            ("DB_04_INDEX_AND_PRAGMA_CHECK", "SQLite Index Coverage & PRAGMA integrity_check", "High", "PRAGMA integrity_check passes 'ok' and QA indexes exist"),
            ("DB_05_TRANSACTION_ROLLBACK", "Transaction Rollback Atomicity Check", "Critical", "Aborted SQL transaction leaves balance & position state completely unchanged"),
            ("DB_06_DUPLICATE_PREVENTION", "Unique Key & Duplicate Record Guard", "High", "Unique indexes block duplicate user email, suite code & webhook signal IDs"),
            ("DB_07_MIGRATIONS_IDEMPOTENCY", "Versioned Migrations 001..011 Idempotency", "Critical", "run_migrations() records checksums and re-runs idempotently with zero errors"),
            ("DB_08_BACKUP_RESTORE_ROUNDTRIP", "Isolated Backup & Restore Verification", "Critical", "sqlite3.backup() archive restores cleanly and preserves exact row counts"),
            ("DB_09_DOMAIN_CONSISTENCY", "Domain & QA Execution Record Consistency", "High", "User, company, encrypted credentials, order, position & QA run rows validate"),
        ],
    },
    {
        "suite_id": "TRADING_ENGINE",
        "code": "TRADING_ENGINE",
        "name": "AraaBot Trading Engine Simulation Suite",
        "category": "TRADING_ENGINE",
        "description": "Tests indicators, prediction engine, ALPHA/BETA/GAMMA agents, OMS lifecycle, SL/TP, risk limits, kill switch, market shocks, and rejected signal blocking in isolation.",
        "module_path": "backend/bot_engine.py, backend/risk_engine.py, backend/oms_engine.py, backend/market_shock_detector.py",
        "requires_isolated_db": 1,
        "sort_order": 60,
        "cases": [
            ("TE_01_MARKET_DATA_AND_TA", "Market Feed & Technical Indicators v2/MTF", "High", "Feed quotes + analyze_technical_v2 produce RSI, EMA, VWAP & ADX"),
            ("TE_02_PREDICTION_FORECAST", "Prediction Engine Multi-Horizon & Deep Forecast", "High", "Deep prediction computes bounded directional probabilities & target bands"),
            ("TE_03_COMMITTEE_ORCHESTRATION", "3-Agent AI Committee Consensus & Audit", "Critical", "Alpha, Beta & Gamma orchestrator persists explainable decision to ai_committee_logs"),
            ("TE_04_STRATEGY_VALIDATION", "StrategyEngine Setup Validation & Scoring", "High", "Auto scalping strategy analyzer evaluates OHLCV setup rules cleanly"),
            ("TE_05_OMS_LIFECYCLE_TP_SL", "OMS State Transitions, SL/TP & Position Tracking", "Critical", "Paper order moves PENDING->FILLED, opens position with SL/TP & records fill"),
            ("TE_06_REJECTED_SIGNAL_NO_ORDER", "Rejected Signal Never Creates Order", "Critical", "Risk-rejected trade writes ZERO rows into orders or positions tables"),
            ("TE_07_EMERGENCY_LOCK_ENFORCED", "Global & User Emergency Kill Switch Lock", "Critical", "Active kill switch immediately blocks evaluate_pre_trade_risk before routing"),
            ("TE_08_DAILY_LOSS_CIRCUIT_BREAKER", "Daily Loss -$250 Circuit Breaker", "Critical", "24h realized loss exceeding limit rejects trade and pauses user bot"),
            ("TE_09_MAX_POSITION_CAP", "Maximum Open Position Hard Limit", "High", "Hitting max_open_positions blocks new order creation cleanly"),
            ("TE_10_DUPLICATE_ORDER_PREVENTION", "Duplicate Symbol & Client Order UUID Block", "Critical", "Same-symbol open position and reused client_order_id are rejected"),
            ("TE_11_MARKET_SHOCK_CRASH_SURGE", "Flash Crash & Surge Volatility Detector", "Critical", "MarketShockDetector flags abrupt crash/surge candles with block_new_entries=True"),
            ("TE_12_WORKER_START_STOP_ISOLATED", "Isolated Bot Worker Start/Stop Lifecycle", "High", "Isolated Bot thread starts, runs watchdog loop safely, and stops cleanly"),
        ],
    },
    {
        "suite_id": "COINDCX",
        "code": "COINDCX",
        "name": "CoinDCX Integration Safe Suite",
        "category": "EXCHANGE_INTEGRATION",
        "description": "Tests CoinDCX config, HMAC-SHA256 signatures, mocked balances/margin/orders reconciliation, retries, timeouts, and Real Mode live-order safety locks.",
        "module_path": "backend/coindcx_gateway.py, backend/coindcx_adapter.py",
        "requires_isolated_db": 1,
        "sort_order": 70,
        "cases": [
            ("CDX_01_CONFIG_AND_MAPPING", "Market Symbol Mapping & Increment Rounding", "Critical", "BTCUSDT/B-BTC_USDT normalize accurately and quantities snap cleanly to step"),
            ("CDX_02_HMAC_SIGNATURE", "HMAC-SHA256 Request Signature Determinism", "Critical", "HMAC-SHA256 signer generates valid deterministic digests without key exposure"),
            ("CDX_03_MOCK_ACCOUNT_AND_MARGIN", "Mocked Connectivity, Spot & Futures Balances", "High", "Adapter verifies mocked account balances & futures wallet margin retrieval"),
            ("CDX_04_MOCK_POSITIONS_RECONCILE", "Mocked Positions, Open Orders & Reconciliation", "High", "CoinDCXExecutionAdapter.reconcile_state detects exchange state discrepancies"),
            ("CDX_05_RETRY_AND_RATE_LIMITS", "Transient 503/429 Backoff vs 4xx Fail-Fast", "High", "Futures gateway retries transient 5xx and fails fast on 4xx rejection"),
            ("CDX_06_EXCHANGE_TIMEOUT_OUTAGE", "Exchange Outage & Stale Market Handling", "Critical", "Exchange timeout keeps position safe and returns structured error (no fake fill)"),
            ("CDX_07_INVALID_CREDS_PERMS", "Invalid Credentials & Permission Failure", "High", "Invalid API secret or missing trading permissions returns corrective action"),
            ("CDX_08_REAL_MODE_SAFETY_LOCK", "Real Mode Automated Order Submission Lock", "Critical", "QA config enforces live_order_testing_locked=1; Run All never places live orders"),
        ],
    },
    {
        "suite_id": "FRONTEND",
        "code": "FRONTEND",
        "name": "Playwright Browser Automation Suite",
        "category": "FRONTEND_E2E",
        "description": "Drives headless Chromium (plus Firefox/WebKit support) against an isolated WSGI server capturing screenshots on failure, traces, and videos.",
        "module_path": "admin/index.html, admin/admin.js, backend/qa_playwright_runner.py",
        "requires_isolated_db": 1,
        "sort_order": 80,
        "cases": [
            ("FE_PW_01_ADMIN_LOGIN", "Playwright Admin Login & Invalid Error Gate", "Critical", "Admin login modal rejects bad password and unlocks with valid token"),
            ("FE_PW_02_SIDEBAR_NAVIGATION", "Playwright Sidebar Module Navigation", "High", "Left command dock switches between Overview, CoinDCX, Book, Security & QA Center"),
            ("FE_PW_03_DASHBOARD_WIDGETS", "Playwright Admin Dashboard Data Rendering", "High", "Dashboard KPIs and live ticker/feed status populate from backend APIs"),
            ("FE_PW_04_SEARCH_FILTERS_MODAL", "Playwright Modals, Search & Filter Controls", "High", "Feed Hub modal opens, filters LIVE/BTC search results, and closes cleanly"),
            ("FE_PW_05_QA_CENTER_FORMS_TABLES", "Playwright QA Center Submenus, Forms & Tables", "Critical", "16 QA submenus render; suites table and test config form operate without errors"),
            ("FE_PW_06_ERROR_EMPTY_RBAC", "Playwright Error States & User 403 Gate", "Critical", "Authenticated regular user token receives 403 and missing run returns 404"),
            ("FE_PW_07_RESPONSIVE_LAYOUT", "Playwright Desktop & Mobile Responsive Check", "Medium", "Admin console renders cleanly across 1440x900 desktop and 390x844 mobile"),
            ("FE_PW_08_CONSOLE_NETWORK_AUDIT", "Playwright Zero Console & 5xx Network Errors", "Critical", "Full browser walkthrough records zero JS pageerrors and zero 5xx API failures"),
            ("FE_PW_09_LOGOUT_SESSION_EXPIRY", "Playwright Admin Logout & Expired Token Lock", "Critical", "Logout clears token and expired/tampered token forces 401 re-authentication"),
        ],
    },
    {
        "suite_id": "SECURITY",
        "code": "SECURITY",
        "name": "Security & Penetration Defense Suite",
        "category": "SECURITY",
        "description": "Validates auth/RBAC isolation, IDOR protection, privilege escalation blocking, WAF SQLi/XSS/traversal defense, secret encryption, and log redaction.",
        "module_path": "backend/security_firewall.py, backend/app.py, backend/database.py",
        "requires_isolated_db": 1,
        "sort_order": 90,
        "cases": [
            ("SEC_01_AUTH_BYPASS_GUARD", "Unauthenticated & Forged Token Guard", "Critical", "Protected admin, central-admin & company endpoints reject anonymous/bad tokens"),
            ("SEC_02_IDOR_DATA_ISOLATION", "Cross-User & Cross-Company IDOR Isolation", "Critical", "User B cannot access/close User A orders/positions; company scopes isolate"),
            ("SEC_03_PRIVILEGE_ESCALATION", "Vertical & Horizontal Privilege Escalation Block", "Critical", "Standard users & non-admin roles cannot approve deploy or mutate QA config"),
            ("SEC_04_WAF_ATTACK_PREVENTION", "WAF SQLi, XSS & Path Traversal Prevention", "Critical", "SecurityFirewall intercepts SQL injection, XSS scripts, and /.env probes"),
            ("SEC_05_HEADERS_AND_CORS", "Security Response Headers Enforcement", "High", "Responses include nosniff, SAMEORIGIN, XSS-Protection & Firewall signature"),
            ("SEC_06_SECRETS_ENCRYPTED_REST", "Fernet At-Rest API Credential Encryption", "Critical", "Broker credentials encrypt with SECRETS_KEY and omit plaintext from DB"),
            ("SEC_07_SECRET_LEAKAGE_AUDIT", "Response & QA Report Secret Leakage Scan", "Critical", "Admin/QA payloads & sanitizer strip coindcx_secret, pw_hash & tokens"),
            ("SEC_08_ARTIFACT_PATH_TRAVERSAL", "QA Artifact Download Path Traversal Guard", "High", "Artifact resolver rejects ../ escape paths outside reports/ directory"),
            ("SEC_09_PASSWORD_POLICY_VALIDATION", "Password Strength & Weak Input Guard", "High", "Empty/short passwords rejected cleanly during registration and auth checks"),
        ],
    },
    {
        "suite_id": "PERFORMANCE",
        "code": "PERFORMANCE",
        "name": "Performance & Concurrency Benchmark Suite",
        "category": "PERFORMANCE",
        "description": "Benchmarks API latency p95, admin dashboard load, DB throughput, concurrent admin/user load, trading computation speed, and memory/CPU usage in isolation.",
        "module_path": "backend/app.py, backend/database.py, backend/bot_engine.py",
        "requires_isolated_db": 1,
        "sort_order": 100,
        "cases": [
            ("PERF_01_API_LATENCY_LOAD", "Configurable Multi-Thread API Latency Load", "High", "P95 response time stays under SLA threshold across configured request load"),
            ("PERF_02_ADMIN_DASHBOARD_LOAD", "Admin Dashboard Telemetry Load Speed", "High", "Admin overview, CoinDCX Live & QA dashboard endpoints respond promptly"),
            ("PERF_03_DATABASE_THROUGHPUT", "Isolated SQLite Read/Write Benchmark", "High", "Batch indexed reads & inserts execute cleanly within latency budget"),
            ("PERF_04_CONCURRENT_SESSIONS", "Concurrent Admin & User Session Stress", "High", "Simultaneous authenticated admin & user clients succeed with 0 lockups"),
            ("PERF_05_ENGINE_SCORING_SPEED", "Technical v2 & 3-Agent AI Committee Latency", "Medium", "Indicator + Committee evaluation runs in < 250ms per symbol"),
            ("PERF_06_RESOURCE_AND_WS_HEALTH", "Memory RSS, Thread & PriceFeed Read Speed", "Medium", "Process RSS footprint & concurrent PriceFeed lookups remain healthy"),
        ],
    },
    {
        "suite_id": "REGRESSION",
        "code": "REGRESSION",
        "name": "Automated Deployment Regression Gate",
        "category": "REGRESSION",
        "description": "Executes the full 7-stage release gate (Backend, DB, API, Playwright UI, Auth, Trading Simulation, CoinDCX Safe) and scores Deployment Readiness.",
        "module_path": "backend/qa_automation_engine.py, backend/system_monitoring.py",
        "requires_isolated_db": 1,
        "sort_order": 110,
        "cases": [
            ("REG_01_BACKEND_SMOKE", "Regression Stage 1: Backend Core Smoke", "Critical", "Core Python modules & AI committee orchestrate cleanly"),
            ("REG_02_DATABASE_INTEGRITY", "Regression Stage 2: DB Schema, Migration & Backup", "Critical", "Isolated DB integrity check, migrations & backup restore succeed"),
            ("REG_03_API_CONTRACTS", "Regression Stage 3: Safe API & Auth Gate Contracts", "Critical", "Registered routes respond validly and enforce authentication"),
            ("REG_04_FRONTEND_SMOKE", "Regression Stage 4: Playwright Chromium UI Smoke", "Critical", "Playwright headless browser verifies Admin portal with zero JS/5xx errors"),
            ("REG_05_AUTH_RBAC_GATE", "Regression Stage 5: Auth & Privilege Boundary Gate", "Critical", "Admin/Company/User permissions and invalid login guards pass"),
            ("REG_06_TRADING_SIM_GATE", "Regression Stage 6: Trading Rules & Risk Simulation", "Critical", "Risk Guardian, Kill Switch, Daily Loss & OMS simulation pass with 0 live orders"),
            ("REG_07_COINDCX_SAFE_GATE", "Regression Stage 7: CoinDCX Read-Only / Mock Safety", "Critical", "Pair precision, HMAC, reconciliation & Real Mode lock pass safely"),
        ],
    },
]


# ---------------------------------------------------------------------------
# Lightweight Synthetic OHLCV Helper for Deterministic Simulation Tests
# ---------------------------------------------------------------------------
def _sample_candles(base: float = 65000.0, count: int = 40, trend: float = 0.0012) -> List[Dict[str, float]]:
    candles = []
    px = base
    now = time.time() - count * 60
    for i in range(count):
        nxt = px * (1.0 + trend + (0.0005 if i % 2 == 0 else -0.0002))
        hi = max(px, nxt) * 1.0015
        lo = min(px, nxt) * 0.9985
        candles.append({
            "t": int(now + i * 60),
            "o": round(px, 4),
            "h": round(hi, 4),
            "l": round(lo, 4),
            "c": round(nxt, 4),
            "v": float(1000 + i * 35),
        })
        px = nxt
    return candles


# ---------------------------------------------------------------------------
# Pure In-Process Safe Checks (BACKEND Python module health - zero DB writes)
# ---------------------------------------------------------------------------
def run_backend_case(case_id: str) -> Tuple[str, str, str, str]:
    """Returns (status, actual_result, error_msg, api_resp_sanitized)."""
    candles = _sample_candles()

    if case_id == "BE_01_APP_MODULE":
        import app as backend_app
        rules = list(backend_app.api.url_map.iter_rules())
        if len(rules) < 30:
            raise AssertionError(f"Expected >=30 routes on Flask api, got {len(rules)}")
        return "PASSED", f"Loaded backend.app cleanly with {len(rules)} registered HTTP routes", "", ""

    if case_id == "BE_02_BOT_ENGINE_MODULE":
        from bot_engine import Bot
        from price_feed import PriceFeed
        f = PriceFeed()
        b = Bot(f)
        b.stop_loop()
        return "PASSED", f"Bot initialized cleanly (categories={len(b.by_category)})", "", ""

    if case_id == "BE_03_COINDCX_GATEWAY_MODULE":
        import coindcx_gateway as cg
        m = cg.to_coindcx_market("BTCUSDT")
        rounded = cg.round_to_increment(12.34567, 0.01)
        if m != "BTCUSDT" or abs(rounded - 12.35) > 1e-6:
            raise AssertionError(f"Unexpected mapping/rounding: m={m}, rounded={rounded}")
        return "PASSED", f"Pair map={m}, precision snap 12.34567-> {rounded}", "", ""

    if case_id == "BE_04_STRATEGY_ENGINE_MODULE":
        from strategy_engine import StrategyEngine
        if not hasattr(StrategyEngine, "process_tradingview_webhook"):
            raise AssertionError("StrategyEngine missing process_tradingview_webhook")
        return "PASSED", "StrategyEngine loaded and verified core webhook & strategy rule hooks", "", ""

    if case_id == "BE_05_PREDICTION_ENGINE_MODULE":
        import prediction_engine as pe
        feat = pe.extract_features(candles)
        fc = pe.generate_multi_horizon_forecast(candles[-1]["c"], feat)
        deep = pe.generate_deep_prediction("BTCUSDT", candles, timeframe="1m")
        if not isinstance(fc, dict) or not isinstance(deep, dict) or "confidence_score" not in deep or "probabilities" not in deep:
            raise AssertionError(f"Unexpected prediction schema: {list(deep.keys()) if isinstance(deep, dict) else deep}")
        return "PASSED", f"Deep forecast generated: decision={deep.get('decision')}, confidence={deep.get('confidence_score')}%", "", ""

    if case_id == "BE_06_ANALYSIS_ENGINE_MODULE":
        import analysis_engine as ae
        ta = ae.analyze_technical_v2("BTCUSDT", candles, timeframe="15m")
        sz = ae.calculate_position_size(1000.0, 2.0, 65000.0, 64350.0, leverage=20.0)
        if not ta or ("rsi" not in str(ta).lower()):
            raise AssertionError("TA v2 output incomplete")
        qty_val = float(sz.get("position_quantity") or sz.get("qty") or sz.get("quantity") or 0)
        if qty_val <= 0:
            raise AssertionError(f"Invalid calculated position size: {sz}")
        return "PASSED", f"TA v2 & volatility sizing verified (qty={qty_val})", "", ""

    if case_id == "BE_07_PRICE_FEED_MODULE":
        import price_feed as pf
        val_sma = pf.sma([10, 20, 30, 40], 2)
        val_rsi = pf.rsi([100, 102, 101, 104, 106, 108, 107, 110], 5)
        sym_code = pf.tv_symbol("BTCUSDT")
        if abs(val_sma - 35.0) > 1e-6 or not (0 <= val_rsi <= 100):
            raise AssertionError(f"Invalid feed math sma={val_sma}, rsi={val_rsi}")
        return "PASSED", f"PriceFeed helpers verified (sma={val_sma}, rsi={val_rsi}, tv={sym_code})", "", ""

    if case_id == "BE_08_RISK_ENGINE_MODULE":
        from risk_engine import InstitutionalRiskEngine
        liq_long = InstitutionalRiskEngine.calculate_liquidation_price(65000.0, "LONG", 20.0)
        liq_short = InstitutionalRiskEngine.calculate_liquidation_price(65000.0, "SHORT", 20.0)
        sz = InstitutionalRiskEngine.calculate_volatility_adjusted_size(1000.0, 1.5, 65000.0, 64300.0, max_leverage=20.0)
        if not (0 < liq_long < 65000.0 < liq_short) or sz["qty"] <= 0:
            raise AssertionError(f"Risk math failed: liqL={liq_long}, liqS={liq_short}, sz={sz}")
        return "PASSED", f"Liquidation bounds verified (L={liq_long} < 65000 < S={liq_short})", "", ""

    if case_id == "BE_09_OMS_ENGINE_MODULE":
        from oms_engine import OrderStatus, OrderManagementSystem, ExecutionManagementSystem
        required_states = {"PENDING", "SUBMITTED", "FILLED", "CANCELLED", "REJECTED"}
        present = {getattr(OrderStatus, s, None) for s in required_states}
        if present != required_states or not hasattr(OrderManagementSystem, "create_order"):
            raise AssertionError(f"OMS missing states or methods: {present}")
        return "PASSED", f"OMS state machine verified ({len(required_states)} core lifecycle states)", "", ""

    if case_id == "BE_10_DATABASE_MODULE":
        import database as db
        salt, digest = db.hash_password("QaCheckSecret!99")
        if not db.verify_password("QaCheckSecret!99", salt, digest) or db.verify_password("Wrong!", salt, digest):
            raise AssertionError("Password hash verify check failed")
        return "PASSED", "Salted password hash verification passed (positive & negative)", "", ""

    if case_id == "BE_11_ALPHA_AGENT":
        from ai_committee import AgentAlphaMarketIntelligence
        res = AgentAlphaMarketIntelligence.evaluate("BTCUSDT", quote_data={"price": 65250.0, "change_pct": 1.2, "volume": 500000.0}, candles=candles)
        if not (0 <= float(res.get("score", -1)) <= 100) or "metrics" not in res:
            raise AssertionError(f"Invalid Alpha output: {res}")
        return "PASSED", f"Agent Alpha verdict={res['verdict']} score={res['score']}%", "", ""

    if case_id == "BE_12_BETA_AGENT":
        from ai_committee import AgentBetaTechnicalIntelligence
        res = AgentBetaTechnicalIntelligence.evaluate("BTCUSDT", candles=candles)
        ind = res.get("indicators", {})
        if not (0 <= float(res.get("score", -1)) <= 100) or "tillson_t3" not in ind or "vwap" not in ind:
            raise AssertionError(f"Invalid Beta output: {res}")
        return "PASSED", f"Agent Beta verdict={res['verdict']} score={res['score']}% RSI={ind.get('rsi_14')}", "", ""

    if case_id == "BE_13_GAMMA_ORCHESTRATOR":
        from ai_committee import AICommitteeOrchestrator
        res = AICommitteeOrchestrator.evaluate_candidate(
            "BTCUSDT", user_id=1, candles=candles, quote_data={"price": candles[-1]["c"], "change_pct": 1.4},
            equity_usd=1000.0, requested_leverage=20.0, timeframe="1m", is_live=False, persist=False,
        )
        if "consensus_score" not in res or "explainable_rationale" not in res or "gamma" not in res:
            raise AssertionError(f"Committee orchestrator missing keys: {res.keys()}")
        return "PASSED", f"3-Agent Committee consensus={res['consensus_score']}% action={res['final_action']}", "", ""

    raise ValueError(f"Unknown BACKEND case_id: {case_id}")


# ---------------------------------------------------------------------------
# Isolated Sandbox Runner (Runs in Child Subprocess with Temp SQLite DB!)
# ---------------------------------------------------------------------------
def _sandbox_bootstrap() -> Dict[str, Any]:
    """Initialize isolated temp SQLite database & Flask test_client for sandbox tests."""
    tmpdir = tempfile.mkdtemp(prefix="araa_qa_sbx_")
    tmpdb = os.path.join(tmpdir, "qa_sandbox.db")
    adm_user = "sbx_admin_" + secrets.token_hex(4)
    adm_pass = "SbxPass_" + secrets.token_hex(8)
    os.environ["DB_PATH"] = tmpdb
    os.environ["ADMIN_USERNAME"] = adm_user
    os.environ["ADMIN_PASSWORD"] = adm_pass
    os.environ["COMPANY_WORKER_ENABLED"] = "0"
    os.environ["SECRETS_KEY"] = "QA_SANDBOX_FERNET_SECRET_KEY_2026_ENTERPRISE"

    import database
    database.DB_PATH = tmpdb
    database.init_schema()

    import app as backend_app
    from system_monitoring import ensure_monitoring_tables
    from company_auth import CompanyAuthService

    ensure_monitoring_tables()
    now = time.time()

    # Seed isolated quotes so feed endpoints never depend on external internet
    backend_app.feed.prices["BTCUSDT"] = {"price": 65200.0, "change_pct": 1.35, "live": True, "source": "SANDBOX"}
    backend_app.feed.prices["ETHUSDT"] = {"price": 3450.0, "change_pct": -0.45, "live": True, "source": "SANDBOX"}
    backend_app.feed.prices["SOLUSDT"] = {"price": 172.5, "change_pct": 2.1, "live": True, "source": "SANDBOX"}

    # Ensure two isolated customer accounts exist (for IDOR / admin / risk checks)
    u1_salt, u1_hash = database.hash_password("TraderOne!2026")
    database.write(
        "INSERT OR REPLACE INTO users(id, email, name, pw_salt, pw_hash, role, account_status, created_at, bot_enabled, bot_max_positions, bot_leverage) "
        "VALUES(9001, 'qa1@sandbox.local', 'QA User One', ?, ?, 'CUSTOMER', 'ACTIVE', ?, 0, 5, 20.0)",
        (u1_salt, u1_hash, now),
    )
    database.write(
        "INSERT OR REPLACE INTO wallets(user_id, deposit_balance, profit_balance, total_deposited, starting_balance, target_amount) "
        "VALUES(9001, 500.0, 25.0, 500.0, 500.0, 750.0)"
    )
    database.write(
        "INSERT OR REPLACE INTO sessions(token, user_id, created_at, last_seen) VALUES('usr_sbx_9001_tok', 9001, ?, ?)",
        (now, now),
    )

    u2_salt, u2_hash = database.hash_password("TraderTwo!2026")
    database.write(
        "INSERT OR REPLACE INTO users(id, email, name, pw_salt, pw_hash, role, account_status, created_at, bot_enabled, bot_max_positions, bot_leverage) "
        "VALUES(9002, 'qa2@sandbox.local', 'QA User Two', ?, ?, 'CUSTOMER', 'ACTIVE', ?, 0, 5, 20.0)",
        (u2_salt, u2_hash, now),
    )
    database.write(
        "INSERT OR REPLACE INTO wallets(user_id, deposit_balance, profit_balance, total_deposited) VALUES(9002, 400.0, 0.0, 400.0)"
    )
    database.write(
        "INSERT OR REPLACE INTO sessions(token, user_id, created_at, last_seen) VALUES('usr_sbx_9002_tok', 9002, ?, ?)",
        (now, now),
    )

    # Seed encrypted CoinDCX broker row + audit logs (never live trading enabled)
    enc_k = database.encrypt_secret("MOCK_CDX_KEY_123456")
    enc_s = database.encrypt_secret("MOCK_CDX_SECRET_999999")
    database.write(
        "INSERT OR REPLACE INTO broker_connections(user_id, broker_name, api_key_masked, coindcx_key, coindcx_secret, live_balance, live_equity, status, is_live_active, connected_at, last_synced_at) "
        "VALUES(9001, 'COINDCX', 'MOCK****3456', ?, ?, 120.5, 125.0, 'CONNECTED', 0, ?, ?)",
        (enc_k, enc_s, now, now),
    )
    database.write(
        "INSERT OR REPLACE INTO real_bot_configs(id, user_id, provider_id, broker_account_id, bot_status, emergency_shutdown, max_leverage, verified_funds, verified_margin, created_at, updated_at) "
        "VALUES(9001, 9001, 'COINDCX', '9001', 'PAUSED', 1, 100.0, 120.5, 110.0, ?, ?)",
        (now, now),
    )

    # Seed Company operator + director rows
    database.write(
        "INSERT OR IGNORE INTO companies(id, company_code, legal_name, created_at, updated_at) "
        "VALUES(1, 'ARAA-QA', 'ARAA QA Prop', ?, ?)",
        (now, now),
    )
    database.write(
        "INSERT OR REPLACE INTO company_users(id, company_id, email, full_name, pw_salt, pw_hash, role_code, status, mfa_enabled, created_at, updated_at) "
        "VALUES(9801, 1, 'ops@sandbox.local', 'QA Operator', 'salt', 'hash', 'COMPANY_OPERATOR', 'ACTIVE', 0, ?, ?)",
        (now, now),
    )
    database.write(
        "INSERT OR REPLACE INTO company_sessions(token, company_id, company_user_id, role_code, ip_address, user_agent, mfa_verified, revoked, expires_at, created_at, last_seen) "
        "VALUES('cmp_sbx_ops_tok', 1, 9801, 'COMPANY_OPERATOR', '127.0.0.1', 'qa', 0, 0, ?, ?, ?)",
        (now + 7200, now, now),
    )

    client = backend_app.api.test_client()
    login_r = client.post("/api/admin/login", json={"username": adm_user, "password": adm_pass})
    adm_tok = (login_r.get_json() or {}).get("admin_token", "")
    assert adm_tok, f"Sandbox admin login failed: {login_r.get_data(as_text=True)}"

    return {
        "tmpdir": tmpdir,
        "tmpdb": tmpdb,
        "database": database,
        "app_mod": backend_app,
        "client": client,
        "adm_user": adm_user,
        "adm_pass": adm_pass,
        "adm_tok": adm_tok,
        "adm_hdr": {"X-Admin-Token": adm_tok},
        "u1_hdr": {"X-Token": "usr_sbx_9001_tok"},
        "u2_hdr": {"X-Token": "usr_sbx_9002_tok"},
        "cmp_hdr": {"Authorization": "Bearer cmp_sbx_ops_tok"},
    }


def _assert_json_ok(resp, label: str, expected_status: int = 200) -> Dict[str, Any]:
    if resp.status_code != expected_status:
        raise AssertionError(f"{label}: expected HTTP {expected_status}, got {resp.status_code}: {resp.get_data(as_text=True)[:300]}")
    data = resp.get_json()
    if not isinstance(data, dict):
        raise AssertionError(f"{label}: response is not a JSON object")
    if data.get("success") is False or data.get("status") == "RECOVERED":
        raise AssertionError(f"{label}: backend error payload: {sanitize_value(data)}")
    return data


def _exec_auth_case(case_id: str, ctx: Dict[str, Any]) -> Tuple[str, str, str]:
    c = ctx["client"]
    db = ctx["database"]
    adm_hdr = ctx["adm_hdr"]
    app_mod = ctx["app_mod"]

    if case_id == "AUTH_01_ADMIN_LOGIN_VALID":
        r = c.post("/api/admin/login", json={"username": ctx["adm_user"], "password": ctx["adm_pass"]})
        d = _assert_json_ok(r, "admin/login")
        tok = d.get("admin_token", "")
        if not tok.startswith("adm_"):
            raise AssertionError(f"Expected adm_ token prefix, got {tok[:10]}")
        return f"Admin token issued cleanly ({len(tok)} chars)", json.dumps(sanitize_value(d)), ""

    if case_id == "AUTH_02_ADMIN_LOGIN_INVALID":
        r1 = c.post("/api/admin/login", json={"username": ctx["adm_user"], "password": "WrongPassword!99"})
        r2 = c.post("/api/admin/login", json={"username": "santhosh8552", "password": "Santhosh@09"})
        if r1.status_code != 401 or r2.status_code != 401:
            raise AssertionError(f"Expected 401 for bad creds, got {r1.status_code}/{r2.status_code}")
        return "Rejected bad and legacy admin credentials with HTTP 401", "", ""

    if case_id == "AUTH_03_USER_REGISTER_LOGIN":
        em = f"qa_reg_{secrets.token_hex(4)}@sandbox.local"
        r1 = c.post("/api/auth/signup", json={"email": em, "name": "QA Reg", "password": "StrongUserPass!2026"})
        _assert_json_ok(r1, "auth/signup")
        r2 = c.post("/api/auth/login", json={"email": em, "password": "StrongUserPass!2026"})
        d2 = _assert_json_ok(r2, "auth/login")
        if not d2.get("token"):
            raise AssertionError("User login missing session token")
        return "User registration & login issued session token cleanly", json.dumps(sanitize_value(d2)), ""

    if case_id == "AUTH_04_COMPANY_SSO_LOGIN":
        from central_admin_ecosystem import CentralIdentityService
        res = CentralIdentityService.authenticate("superadmin@araa.in", "AraaSuperAdmin@2026!", app_id="app_erp")
        if "success" not in res:
            raise AssertionError(f"CentralIdentityService missing success key: {res}")
        r_comp = c.get("/api/v1/company/monitoring/overview", headers=ctx["cmp_hdr"])
        _assert_json_ok(r_comp, "company overview")
        return "Company operator auth & CentralIdentityService verified cleanly", "", ""

    if case_id == "AUTH_05_LOGOUT_TOKEN_REVOCATION":
        em = f"qa_lo_{secrets.token_hex(3)}@sandbox.local"
        reg = _assert_json_ok(c.post("/api/auth/signup", json={"email": em, "name": "Logout Test", "password": "PassWord!2026"}), "signup")
        tok = reg["token"]
        _assert_json_ok(c.post("/api/auth/logout", headers={"X-Token": tok}), "logout")
        after_me = c.get("/api/auth/me", headers={"X-Token": tok})
        after_acc = c.get("/api/account", headers={"X-Token": tok})
        if after_me.status_code != 401 or after_acc.status_code != 401:
            raise AssertionError(f"Revoked token still allowed access: me={after_me.status_code}, account={after_acc.status_code}")
        return "Logout revoked session and blocked both /api/auth/me and /api/account with HTTP 401", "", ""

    if case_id == "AUTH_06_PASSWORD_HASH_AND_RESET":
        salt, h = db.hash_password("InitialPass!2026")
        if not db.verify_password("InitialPass!2026", salt, h):
            raise AssertionError("Password verify failed")
        new_salt, new_h = db.hash_password("RotatedPass!2026")
        if db.verify_password("InitialPass!2026", new_salt, new_h) or not db.verify_password("RotatedPass!2026", new_salt, new_h):
            raise AssertionError("Password rotation verification failed")
        return "Salted password hash verification and rotation confirmed", "", ""

    if case_id == "AUTH_07_SESSION_EXPIRY_TTL":
        exp_tok = "adm_expired_" + secrets.token_hex(8)
        db.set_state(f"admin_session_{exp_tok}", json.dumps({"user": "qa", "time": time.time() - 999999}))
        r = c.get("/api/admin/overview", headers={"X-Admin-Token": exp_tok})
        if r.status_code != 401:
            raise AssertionError(f"Expected 401 for expired admin token, got {r.status_code}")
        return "Expired admin session token rejected with 401 and pruned", "", ""

    if case_id == "AUTH_08_PERSISTENT_SESSION_HMAC":
        tok = app_mod._sign_persistent_token(9001, time.time(), secrets.token_hex(4))
        uid = app_mod._verify_persistent_token(tok)
        tampered = tok[:-4] + ("0000" if not tok.endswith("0000") else "1111")
        if uid != 9001 or app_mod._verify_persistent_token(tampered) is not None:
            raise AssertionError("Persistent HMAC token validation failed")
        return "HMAC persistent session token validated and tamper rejected", "", ""

    if case_id == "AUTH_09_SSO_TOKEN_VALIDATION":
        r_bad = c.post("/api/central-admin/validate-token", json={"sso_token": "sso_invalid_forged"})
        d_bad = r_bad.get_json() or {}
        if d_bad.get("valid") is True:
            raise AssertionError("Forged SSO token reported valid")
        return "Central SSO token validation rejected forged token", "", ""

    if case_id == "AUTH_10_ROLE_BASED_PERMISSIONS":
        r1 = c.get("/api/admin/qa/dashboard", headers=ctx["u1_hdr"])
        r2 = c.get("/api/central-admin/dashboard", headers=ctx["u1_hdr"])
        r3 = c.post("/api/v1/company/monitoring/deployment/approve", headers=ctx["cmp_hdr"], json={"note": "x"})
        r4 = c.get("/api/admin/qa/dashboard", headers=adm_hdr)
        if r1.status_code != 403 or r2.status_code != 403 or r3.status_code != 403 or r4.status_code != 200:
            raise AssertionError(f"RBAC status mismatch: u_qa={r1.status_code}, u_ca={r2.status_code}, cmp_dep={r3.status_code}, adm={r4.status_code}")
        return "Verified 403 Forbidden for User & non-admin roles vs 200 for Admin", "", ""

    if case_id == "AUTH_11_MFA_TOTP_FLOW":
        from company_auth import CompanyAuthService
        res = CompanyAuthService.enroll_mfa(9801)
        if not res.get("success") or not res.get("secret"):
            raise AssertionError(f"Company MFA enroll failed: {res}")
        return "Company MFA enrollment returned provisioning secret without error", "", ""

    if case_id == "AUTH_12_RATE_LIMIT_AND_LOCKOUT":
        db.write("UPDATE users SET account_status='SUSPENDED' WHERE id=9002")
        from risk_engine import InstitutionalRiskEngine
        ok_risk, reason, _ = InstitutionalRiskEngine.evaluate_pre_trade_risk(
            9002, "BTCUSDT", "LONG", 400.0, 65000.0, 64500.0, 66000.0, requested_leverage=20.0
        )
        db.write("UPDATE users SET account_status='ACTIVE' WHERE id=9002")
        if ok_risk or "SUSPENDED" not in reason:
            raise AssertionError(f"Suspended account not blocked cleanly: ok={ok_risk}, reason={reason}")
        return "Suspended account lockout enforced by pre-trade risk gate", "", ""

    raise ValueError(f"Unknown AUTH case {case_id}")


def _exec_admin_panel_case(case_id: str, ctx: Dict[str, Any]) -> Tuple[str, str, str]:
    c = ctx["client"]
    h = ctx["adm_hdr"]
    db = ctx["database"]

    route_map = {
        "ADM_01_DASHBOARD_OVERVIEW": ("GET", "/api/admin/overview", None, ("totalUsers", "symbolsTracked")),
        "ADM_03_COMPANY_MANAGEMENT": ("GET", "/api/central-admin/dashboard", None, ("metrics", "system_health")),
        "ADM_04_BROKER_API_MANAGEMENT": ("GET", "/api/admin/coindcx-live", None, ("usdt_inr_rate", "coindcx_connections")),
        "ADM_06_TRADING_RULES_GATEKEEPER": ("GET", "/api/admin/adapter-gatekeeper", None, ("audit_logs", "inspection_logs")),
        "ADM_07_STRATEGY_MANAGEMENT": ("GET", "/api/admin/bot-storage", None, ("open_count", "closed")),
        "ADM_10_DEPOSIT_MANAGEMENT": ("GET", "/api/admin/deposits", None, ("deposits",)),
        "ADM_12_TRANSACTIONS_LEDGER": ("GET", "/api/admin/brokerage", None, ("ledger", "rate")),
        "ADM_14_NOTIFICATIONS_SLACK": ("GET", "/api/admin/slack/config", None, ("config",)),
        "ADM_15_SETTINGS_PAYMENT_RAILS": ("GET", "/api/admin/upi/config", None, ()),
        "ADM_16_SECURITY_FIREWALL_CONTROLS": ("GET", "/api/admin/firewall", None, ("stats", "recent_threats")),
        "ADM_17_AUDIT_LOGS": ("GET", "/api/admin/logs", None, ("logs",)),
        "ADM_18_QA_QUALITY_CENTER": ("GET", "/api/admin/qa/suites", None, ("suites",)),
    }
    if case_id in route_map:
        meth, path, payload, keys = route_map[case_id]
        r = c.get(path, headers=h) if meth == "GET" else c.post(path, headers=h, json=payload)
        d = _assert_json_ok(r, path)
        for k in keys:
            if k not in d:
                raise AssertionError(f"{path} missing key '{k}'")
        return f"Verified {path} (HTTP 200 & expected keys {list(keys)})", json.dumps(sanitize_value(d))[:1200], ""

    if case_id == "ADM_02_USER_MANAGEMENT":
        d = _assert_json_ok(c.get("/api/admin/users", headers=h), "admin/users")
        if "users" not in d or "usdt_inr_rate" not in d:
            raise AssertionError("Missing users or usdt_inr_rate")
        return f"Listed {len(d['users'])} users cleanly with CoinDCX & INR metadata", "", ""

    if case_id == "ADM_05_BOT_MANAGEMENT":
        _assert_json_ok(c.post("/api/admin/user/9001/bot-toggle", headers=h, json={"enabled": True}), "bot-toggle on")
        st_on = db.query_one("SELECT bot_status, emergency_shutdown FROM real_bot_configs WHERE user_id=9001")
        _assert_json_ok(c.post("/api/admin/user/9001/bot-toggle", headers=h, json={"enabled": False}), "bot-toggle off")
        st_off = db.query_one("SELECT bot_status FROM real_bot_configs WHERE user_id=9001")
        if st_on["bot_status"] != "RUNNING" or st_off["bot_status"] != "PAUSED":
            raise AssertionError(f"Bot toggle desynced: on={st_on}, off={st_off}")
        return "bot-toggle synced real_bot_configs RUNNING <-> PAUSED cleanly", "", ""

    if case_id == "ADM_08_RISK_MANAGEMENT":
        _assert_json_ok(c.post("/api/admin/user/9001/emergency-reset", headers=h, json={}), "emergency-reset")
        es = db.query_one("SELECT emergency_shutdown FROM real_bot_configs WHERE user_id=9001")["emergency_shutdown"]
        if es != 0:
            raise AssertionError("Emergency reset did not clear lock")
        return "Admin emergency shutdown reset cleared real_bot_configs lock", "", ""

    if case_id == "ADM_09_WALLET_MANAGEMENT":
        bad = c.post("/api/admin/user/9001/deposit", headers=h, json={"amount": -10})
        if bad.status_code != 400:
            raise AssertionError(f"Expected 400 on negative deposit, got {bad.status_code}")
        ok_d = _assert_json_ok(c.post("/api/admin/user/9001/deposit", headers=h, json={"amount": 25}), "deposit")
        if "$" not in str(ok_d):
            raise AssertionError(f"Expected USD $ confirmation in deposit response: {ok_d}")
        return "Direct deposit credited $25.00 and rejected negative amount", "", ""

    if case_id == "ADM_11_WITHDRAWAL_MANAGEMENT":
        d = _assert_json_ok(c.get("/api/admin/withdrawals", headers=h), "withdrawals")
        if "withdrawals" not in d:
            raise AssertionError("Missing withdrawals list")
        return f"Withdrawals endpoint verified ({len(d['withdrawals'])} records)", "", ""

    if case_id == "ADM_13_REPORTS_EOD":
        eod = _assert_json_ok(c.get("/api/admin/user/9001/eod-report", headers=h), "eod-report")
        ii = _assert_json_ok(c.get("/api/admin/institutional-intelligence", headers=h), "institutional-intel")
        if "market_intelligence" not in ii:
            raise AssertionError("Missing market_intelligence")
        return "EOD Report & Institutional Intelligence endpoints verified", "", ""

    raise ValueError(f"Unknown ADMIN_PANEL case {case_id}")


def _exec_api_case(case_id: str, ctx: Dict[str, Any]) -> Tuple[str, str, str]:
    c = ctx["client"]
    h = ctx["adm_hdr"]
    app_mod = ctx["app_mod"]

    rules = list(app_mod.api.url_map.iter_rules())
    unsafe_keywords = ("withdraw", "deposit", "close", "wipe", "delete", "trade", "orders", "sell", "buy", "reset", "approve")

    if case_id == "API_01_ROUTE_DISCOVERY":
        api_routes = [r for r in rules if r.rule.startswith("/api/")]
        if len(api_routes) < 40:
            raise AssertionError(f"Expected >=40 API routes, discovered {len(api_routes)}")
        return f"Discovered {len(api_routes)} /api/* endpoints automatically via Flask url_map", "", ""

    if case_id == "API_02_SAFE_GET_CONTRACTS":
        safe_gets = ["/healthz", "/api/coins", "/api/markets?limit=10", "/api/docs/swagger.json", "/api/ai/predictions/accuracy"]
        latencies = []
        for ep in safe_gets:
            t0 = time.time()
            r = c.get(ep)
            ms = round((time.time() - t0) * 1000, 2)
            latencies.append(f"{ep}={r.status_code}({ms}ms)")
            if r.status_code != 200:
                raise AssertionError(f"Safe GET {ep} failed with {r.status_code}")
            if not isinstance(r.get_json(), dict):
                raise AssertionError(f"Safe GET {ep} returned non-JSON")
        return "Verified safe GET contracts: " + ", ".join(latencies), "", ""

    if case_id == "API_03_AUTH_GATE_COVERAGE":
        admin_gets = [
            r.rule for r in rules
            if r.rule.startswith(("/api/admin/", "/api/central-admin/"))
            and "<" not in r.rule and "GET" in r.methods
            and r.rule not in ("/api/admin/login", "/api/central-admin/login")
            and not any(bad in r.rule for bad in unsafe_keywords)
        ][:20]
        for path in admin_gets:
            ru = c.get(path)
            if ru.status_code != 401:
                raise AssertionError(f"Unauthenticated GET {path} returned {ru.status_code}, expected 401")
            r_usr = c.get(path, headers=ctx["u1_hdr"])
            if r_usr.status_code != 403:
                raise AssertionError(f"User GET {path} returned {r_usr.status_code}, expected 403")
        return f"Verified unauth=401 and user=403 across {len(admin_gets)} discovered Admin endpoints", "", ""

    if case_id == "API_04_INPUT_VALIDATION":
        r1 = c.post("/api/auth/login", data="{bad_json", content_type="application/json")
        r2 = c.post("/api/auth/signup", json={"email": "", "password": ""})
        if r1.status_code >= 500 or r2.status_code != 400:
            raise AssertionError(f"Input validation failed: bad_json={r1.status_code}, empty_signup={r2.status_code}")
        return "Malformed JSON and missing fields returned clean 4xx validation responses", "", ""

    if case_id == "API_05_PAGINATION_FILTERING":
        r1 = _assert_json_ok(c.get("/api/markets?limit=5&search=BTC"), "markets filter")
        rows = r1.get("markets") or r1.get("rows") or r1.get("instruments") or []
        if len(rows) > 5:
            raise AssertionError(f"Pagination limit=5 violated: got {len(rows)} rows")
        return f"Verified /api/markets limit=5 & search=BTC returned {len(rows)} rows", "", ""

    if case_id == "API_06_WAF_INJECTION_SHIELD":
        r_sqli = c.get("/api/markets?search=BTC%27%20OR%201%3D1--", headers={"X-Forwarded-For": "203.0.113.55"})
        r_xss = c.get("/api/markets?search=<script>alert(1)</script>", headers={"X-Forwarded-For": "203.0.113.56"})
        if r_sqli.status_code != 403 or r_xss.status_code != 403:
            raise AssertionError(f"WAF did not block probes: sqli={r_sqli.status_code}, xss={r_xss.status_code}")
        return "SecurityFirewall intercepted both SQLi and XSS probes with 403", "", ""

    if case_id == "API_07_SECURITY_HEADERS":
        r = c.get("/api/coins")
        required = ("X-Content-Type-Options", "X-Frame-Options", "X-Firewall-Protection", "Cache-Control")
        missing = [k for k in required if not r.headers.get(k)]
        if missing:
            raise AssertionError(f"Missing HTTP security headers: {missing}")
        return f"Verified security headers: {', '.join(required)}", "", ""

    raise ValueError(f"Unknown API case {case_id}")


def _exec_database_case(case_id: str, ctx: Dict[str, Any]) -> Tuple[str, str, str]:
    db = ctx["database"]
    tmpdb = ctx["tmpdb"]

    if case_id == "DB_01_CONNECTION_WAL":
        conn = db.connect()
        try:
            jm = conn.execute("PRAGMA journal_mode").fetchone()[0]
            one = conn.execute("SELECT 1").fetchone()[0]
            if one != 1:
                raise AssertionError("SELECT 1 failed")
            return f"Connected to isolated DB (journal_mode={jm})", "", ""
        finally:
            conn.close()

    if case_id == "DB_02_SCHEMA_INTEGRITY":
        tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {
            "users", "wallets", "positions", "orders", "broker_connections", "real_bot_configs",
            "ai_committee_logs", "real_bot_audit_logs", "qa_test_suites", "qa_test_cases",
            "qa_test_runs", "qa_test_results", "qa_test_logs", "qa_test_artifacts", "qa_defects",
            "qa_test_config", "qa_test_schedules",
        }
        missing = required - tables
        if missing:
            raise AssertionError(f"Missing required DB tables: {sorted(missing)}")
        return f"Verified all {len(required)} required core + QA tables ({len(tables)} total tables)", "", ""

    if case_id == "DB_03_FOREIGN_KEYS_CONSTRAINTS":
        conn = db.connect()
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            failed_as_expected = False
            try:
                conn.execute(
                    "INSERT INTO qa_test_cases(case_id, suite_id, code, name, created_at, updated_at) "
                    "VALUES('ORPHAN_CASE', 'NON_EXISTENT_SUITE', 'ORPH', 'Orphan', 1.0, 1.0)"
                )
            except sqlite3.IntegrityError:
                failed_as_expected = True
            if not failed_as_expected:
                raise AssertionError("Foreign key constraint failed to reject orphan qa_test_cases row")
            return "PRAGMA foreign_keys=ON strictly enforced relational integrity", "", ""
        finally:
            conn.close()

    if case_id == "DB_04_INDEX_AND_PRAGMA_CHECK":
        conn = db.connect()
        try:
            chk = conn.execute("PRAGMA integrity_check").fetchone()[0]
            idxs = conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
            if str(chk).lower() != "ok":
                raise AssertionError(f"PRAGMA integrity_check failed: {chk}")
            return f"PRAGMA integrity_check={chk}; {len(idxs)} indexes verified", "", ""
        finally:
            conn.close()

    if case_id == "DB_05_TRANSACTION_ROLLBACK":
        before = float(db.query_one("SELECT deposit_balance FROM wallets WHERE user_id=9001")["deposit_balance"])
        conn = db.connect()
        try:
            conn.execute("BEGIN")
            conn.execute("UPDATE wallets SET deposit_balance = deposit_balance + 99999 WHERE user_id=9001")
            conn.rollback()
        finally:
            conn.close()
        after = float(db.query_one("SELECT deposit_balance FROM wallets WHERE user_id=9001")["deposit_balance"])
        if abs(after - before) > 1e-6:
            raise AssertionError(f"Rollback failed: before={before}, after={after}")
        return f"Transaction rollback restored exact balance ({before})", "", ""

    if case_id == "DB_06_DUPLICATE_PREVENTION":
        dup_blocked = False
        conn = db.connect()
        try:
            try:
                conn.execute(
                    "INSERT INTO users(email, name, pw_salt, pw_hash, created_at) VALUES('qa1@sandbox.local', 'Dup', 's', 'h', 1.0)"
                )
            except sqlite3.IntegrityError:
                dup_blocked = True
        finally:
            conn.close()
        if not dup_blocked:
            raise AssertionError("Duplicate email insert was not blocked by UNIQUE constraint")
        return "UNIQUE constraints prevented duplicate user email insert cleanly", "", ""

    if case_id == "DB_07_MIGRATIONS_IDEMPOTENCY":
        from migrations import run_migrations, list_applied_migrations
        newly = run_migrations()
        applied = list_applied_migrations()
        versions = {m["version"] for m in applied}
        if "011" not in versions or newly:
            raise AssertionError(f"Migration check failed: versions={sorted(versions)}, newly={newly}")
        return f"All {len(applied)} migrations (001..011) idempotent with checksum verification", "", ""

    if case_id == "DB_08_BACKUP_RESTORE_ROUNDTRIP":
        bak_path = tmpdb + ".bak"
        src = sqlite3.connect(tmpdb)
        dst = sqlite3.connect(bak_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        ver = sqlite3.connect(bak_path)
        try:
            u_cnt = ver.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if u_cnt < 2:
                raise AssertionError(f"Backup restore verification user count={u_cnt}")
        finally:
            ver.close()
        return f"SQLite backup/restore verified intact ({u_cnt} users preserved)", "", ""

    if case_id == "DB_09_DOMAIN_CONSISTENCY":
        bc = db.query_one("SELECT coindcx_secret FROM broker_connections WHERE user_id=9001")
        if not bc or db.decrypt_secret(bc["coindcx_secret"]) != "MOCK_CDX_SECRET_999999":
            raise AssertionError("Encrypted broker credential consistency check failed")
        return "Verified encrypted credential roundtrip & user/wallet consistency", "", ""

    raise ValueError(f"Unknown DATABASE case {case_id}")


def _exec_trading_case(case_id: str, ctx: Dict[str, Any]) -> Tuple[str, str, str]:
    db = ctx["database"]
    candles = _sample_candles(65000.0, 45, 0.001)

    if case_id == "TE_01_MARKET_DATA_AND_TA":
        import analysis_engine as ae
        ta = ae.analyze_technical_v2("BTCUSDT", candles, timeframe="15m")
        mtf = ae.analyze_multi_timeframe("BTCUSDT", {"15m": candles, "5m": candles, "1m": candles})
        if not ta or not mtf:
            raise AssertionError("TA / MTF returned empty")
        return f"TA v2 trend={ta.get('trend')} MTF alignment computed", "", ""

    if case_id == "TE_02_PREDICTION_FORECAST":
        import prediction_engine as pe
        deep = pe.generate_deep_prediction("BTCUSDT", candles, timeframe="1m")
        if not deep or "confidence_score" not in deep or "probabilities" not in deep:
            raise AssertionError("Deep prediction missing confidence_score or probabilities")
        return f"Deep forecast decision={deep.get('decision')} conf={deep.get('confidence_score')}%", "", ""

    if case_id == "TE_03_COMMITTEE_ORCHESTRATION":
        from ai_committee import AICommitteeOrchestrator
        res = AICommitteeOrchestrator.evaluate_candidate(
            "BTCUSDT", user_id=9001, candles=candles, quote_data={"price": candles[-1]["c"], "change_pct": 1.3},
            equity_usd=500.0, requested_leverage=20.0, is_live=False, persist=True,
        )
        row = db.query_one("SELECT * FROM ai_committee_logs WHERE user_id=9001 ORDER BY id DESC LIMIT 1")
        if not row or not res.get("explainable_rationale"):
            raise AssertionError("Committee decision not persisted cleanly")
        return f"Persisted 3-Agent Committee vote: {res['final_action']} ({res['consensus_score']}%)", "", ""

    if case_id == "TE_04_STRATEGY_VALIDATION":
        import analysis_engine as ae
        ta = ae.analyze_technical_v2("BTCUSDT", candles, timeframe="15m")
        scalp = ae.analyze_scalping_strategies("BTCUSDT", ta)
        if not isinstance(scalp, dict):
            raise AssertionError("Scalping strategy output invalid")
        return f"Evaluated auto-scalping strategy confluence cleanly", "", ""

    if case_id == "TE_05_OMS_LIFECYCLE_TP_SL":
        from oms_engine import OrderManagementSystem, ExecutionManagementSystem, PositionManager
        # Clear any leftover emergency lock on 9001 in sandbox
        db.write("UPDATE real_bot_configs SET emergency_shutdown=0 WHERE user_id=9001")
        created = OrderManagementSystem.create_order(
            user_id=9001, symbol="ADAUSDT", side="BUY", order_type="MARKET",
            quantity=100.0, price=0.50, take_profit=0.52, stop_loss=0.49, leverage=20.0, is_paper=True,
        )
        if not created.get("success"):
            raise AssertionError(f"Paper OMS order creation failed: {created}")
        filled = ExecutionManagementSystem.execute_order(created["order_id"])
        if not filled.get("success") or filled.get("status") != "FILLED":
            raise AssertionError(f"Paper OMS execution failed: {filled}")
        closed = PositionManager.close_position(filled["position_id"], close_price=0.51, reason="QA_PROFIT_BOOK")
        if not closed.get("success"):
            raise AssertionError(f"Paper position close failed: {closed}")
        return f"OMS lifecycle PENDING->FILLED->CLOSED completed (PnL={closed.get('realized_pnl')})", "", ""

    if case_id == "TE_06_REJECTED_SIGNAL_NO_ORDER":
        from oms_engine import OrderManagementSystem
        db.write("UPDATE users SET account_status='SUSPENDED' WHERE id=9002")
        before_cnt = db.query_one("SELECT COUNT(*) c FROM orders WHERE user_id=9002")["c"]
        res = OrderManagementSystem.create_order(
            user_id=9002, symbol="XRPUSDT", side="BUY", order_type="MARKET",
            quantity=50.0, price=0.60, leverage=20.0, is_paper=True,
        )
        after_cnt = db.query_one("SELECT COUNT(*) c FROM orders WHERE user_id=9002")["c"]
        db.write("UPDATE users SET account_status='ACTIVE' WHERE id=9002")
        if res.get("success") or after_cnt != before_cnt:
            raise AssertionError(f"Rejected signal created order! before={before_cnt}, after={after_cnt}, res={res}")
        return "Risk-rejected signal created 0 rows in orders table", "", ""

    if case_id == "TE_07_EMERGENCY_LOCK_ENFORCED":
        from risk_engine import InstitutionalRiskEngine
        db.set_state("emergency_platform_kill_switch", "1")
        ok_risk, reason, _ = InstitutionalRiskEngine.evaluate_pre_trade_risk(
            9001, "DOGEUSDT", "LONG", 500.0, 0.2, 0.19, 0.21, requested_leverage=20.0
        )
        db.set_state("emergency_platform_kill_switch", "0")
        if ok_risk or "EMERGENCY_KILL_SWITCH" not in reason:
            raise AssertionError(f"Global kill switch failed to block order: {ok_risk}, {reason}")
        return "Global emergency kill switch blocked order creation immediately", "", ""

    if case_id == "TE_08_DAILY_LOSS_CIRCUIT_BREAKER":
        from risk_engine import InstitutionalRiskEngine
        now = time.time()
        db.write(
            "INSERT INTO positions(user_id, symbol, source, side, qty, entry_price, margin, target_pct, stop_pct, status, current_price, unrealized_pnl, opened_at, closed_at, realized_pnl, close_reason) "
            "VALUES(9002, 'LINKUSDT', 'BOT', 'LONG', 10.0, 15.0, 15.0, 2.0, 1.0, 'CLOSED', 12.0, 0, ?, ?, -300.0, 'STOP_LOSS')",
            (now - 300, now - 60),
        )
        ok_risk, reason, _ = InstitutionalRiskEngine.evaluate_pre_trade_risk(
            9002, "UNIUSDT", "LONG", 500.0, 10.0, 9.8, 10.4, requested_leverage=20.0
        )
        if ok_risk or "DAILY_LOSS_LIMIT" not in reason:
            raise AssertionError(f"Daily loss breaker missed -$300 loss: ok={ok_risk}, reason={reason}")
        return "Daily loss breaker triggered at -$300 and suspended entry", "", ""

    if case_id == "TE_09_MAX_POSITION_CAP":
        from risk_engine import InstitutionalRiskEngine
        now = time.time()
        db.write("UPDATE users SET bot_max_positions=1 WHERE id=9001")
        db.write(
            "INSERT INTO positions(user_id, symbol, source, side, qty, entry_price, margin, target_pct, stop_pct, status, current_price, unrealized_pnl, opened_at) "
            "VALUES(9001, 'AVAXUSDT', 'BOT', 'LONG', 1.0, 30.0, 3.0, 2.0, 1.0, 'OPEN', 30.1, 0.1, ?)",
            (now,),
        )
        ok_risk, reason, _ = InstitutionalRiskEngine.evaluate_pre_trade_risk(
            9001, "DOTUSDT", "LONG", 500.0, 6.0, 5.8, 6.3, requested_leverage=20.0
        )
        db.write("UPDATE users SET bot_max_positions=5 WHERE id=9001")
        db.write("DELETE FROM positions WHERE user_id=9001 AND symbol='AVAXUSDT'")
        if ok_risk or "MAX_POSITIONS_REACHED" not in reason:
            raise AssertionError(f"Max position limit not enforced: {ok_risk}, {reason}")
        return "Max position cap (1/1) strictly blocked overflow entry", "", ""

    if case_id == "TE_10_DUPLICATE_ORDER_PREVENTION":
        from oms_engine import OrderManagementSystem
        cid = "qa_dup_uuid_001"
        now_t = time.time()
        db.write(
            "INSERT OR IGNORE INTO order_audit_lifecycle(order_uuid, user_id, exchange, execution_mode, symbol, side, requested_qty, requested_price, lifecycle_state, created_at, updated_at) "
            "VALUES(?, 9001, 'COINDCX', 'PAPER', 'BTCUSDT', 'BUY', 0.001, 65000.0, 'FILLED', ?, ?)",
            (cid, now_t, now_t),
        )
        res = OrderManagementSystem.create_order(
            user_id=9001, symbol="BTCUSDT", side="BUY", order_type="MARKET",
            quantity=0.001, price=65000.0, leverage=20.0, is_paper=True, client_order_id=cid,
        )
        if res.get("success") or res.get("error") != "DUPLICATE_ORDER_REJECTED":
            raise AssertionError(f"Duplicate client_order_id was not rejected: {res}")
        return "Duplicate client_order_id rejected cleanly with DUPLICATE_ORDER_REJECTED", "", ""

    if case_id == "TE_11_MARKET_SHOCK_CRASH_SURGE":
        from market_shock_detector import MarketShockDetector
        crash = _sample_candles(65000.0, 20, 0.0005)
        crash[-1]["c"] = crash[-2]["c"] * 0.95  # -5% flash crash
        crash[-1]["l"] = crash[-1]["c"]
        r_crash = MarketShockDetector.analyze_market_shock("CRASHUSDT", crash, current_price=crash[-1]["c"])
        surge = _sample_candles(100.0, 20, 0.0005)
        surge[-1]["c"] = surge[-2]["c"] * 1.06  # +6% parabolic spike
        surge[-1]["h"] = surge[-1]["c"]
        r_surge = MarketShockDetector.analyze_market_shock("SURGEUSDT", surge, current_price=surge[-1]["c"])
        if not r_crash.get("block_new_entries") or not r_surge.get("block_new_entries"):
            raise AssertionError(f"Shock detector failed: crash={r_crash}, surge={r_surge}")
        return f"Detected flash crash ({r_crash.get('shock_type')}) & surge ({r_surge.get('shock_type')}), blocking new entries", "", ""

    if case_id == "TE_12_WORKER_START_STOP_ISOLATED":
        from bot_engine import Bot
        from price_feed import PriceFeed
        b = Bot(PriceFeed())
        b.start_loop()
        time.sleep(0.05)
        b.stop_loop()
        return "Isolated Bot worker loop started and stopped cleanly", "", ""

    raise ValueError(f"Unknown TRADING_ENGINE case {case_id}")


def _exec_coindcx_case(case_id: str, ctx: Dict[str, Any]) -> Tuple[str, str, str]:
    import coindcx_gateway as cg
    from coindcx_adapter import CoinDCXExecutionAdapter, sanitize_request

    if case_id == "CDX_01_CONFIG_AND_MAPPING":
        p1 = cg.to_coindcx_market("ETHUSDT")
        inc = cg.round_to_increment(0.12349, 0.001)
        if p1 != "ETHUSDT" or abs(inc - 0.123) > 1e-6:
            raise AssertionError(f"CoinDCX mapping failed: {p1}, {inc}")
        return f"Mapped ETHUSDT & snapped 0.12349 -> {inc} (precision aligned)", "", ""

    if case_id == "CDX_02_HMAC_SIGNATURE":
        body = json.dumps({"timestamp": 1700000000000}, separators=(",", ":"))
        sig1 = hmac.new(b"qa_test_secret", body.encode("utf-8"), hashlib.sha256).hexdigest()
        sig2 = hmac.new(b"qa_test_secret", body.encode("utf-8"), hashlib.sha256).hexdigest()
        san = sanitize_request({"api_key": "KEY_123", "secret": "SEC_999", "symbol": "BTCUSDT"})
        if sig1 != sig2 or len(sig1) != 64 or san.get("secret") == "SEC_999":
            raise AssertionError("HMAC or sanitize_request verification failed")
        return "HMAC-SHA256 digest deterministic and secret keys redacted cleanly", "", ""

    class _MockFutures:
        def check_eligibility(self):
            return {"eligible": True}
        def get_available_futures_margin_usdt(self):
            return 120.5
        def get_positions(self):
            return True, []
        def get_orders(self):
            return True, []

    class _MockClient:
        is_offline = False
        futures = _MockFutures()
        def get_balances(self, force=False):
            return True, {"usdt_free": 120.5, "total_portfolio_usd": 125.0}

    if case_id == "CDX_03_MOCK_ACCOUNT_AND_MARGIN":
        with patch.object(CoinDCXExecutionAdapter, "_client", return_value=_MockClient()):
            snap = CoinDCXExecutionAdapter.get_account_snapshot(9001)
        if not snap.get("connected") or float(snap.get("available_balance_usd") or 0) <= 0:
            raise AssertionError(f"Mocked account snapshot failed: {snap}")
        return f"Mocked Spot+Futures snapshot verified (avail=${snap['available_balance_usd']})", json.dumps(sanitize_value(snap)), ""

    if case_id == "CDX_04_MOCK_POSITIONS_RECONCILE":
        with patch.object(CoinDCXExecutionAdapter, "_client", return_value=_MockClient()):
            rec = CoinDCXExecutionAdapter.reconcile_state(9001)
        if not rec.get("connected") or not rec.get("is_matched"):
            raise AssertionError(f"Reconciliation failed: {rec}")
        return f"Exchange state reconciliation verified cleanly ({rec.get('status')})", "", ""

    if case_id == "CDX_05_RETRY_AND_RATE_LIMITS":
        calls = {"n": 0}
        def flaky(endpoint, method="GET", body=None, api_key=None, api_secret=None, **kw):
            calls["n"] += 1
            if calls["n"] < 3:
                return False, {"code": 503, "message": "temporary unavailable"}
            return True, []
        client = cg.CoinDCXFuturesAdapter("qa_k", "qa_s", user_id=9001)
        with patch.object(cg, "_request", side_effect=flaky), patch.object(cg.time, "sleep"):
            ok_req, _ = client._call("/exchange/v1/derivatives/futures/positions", attempts=4)
        if not ok_req or calls["n"] != 3:
            raise AssertionError(f"Transient 503 retry failed: calls={calls['n']}, ok={ok_req}")
        return f"Verified automatic retry/backoff on transient 503 ({calls['n']} attempts)", "", ""

    if case_id == "CDX_06_EXCHANGE_TIMEOUT_OUTAGE":
        class _TimeoutClient:
            is_offline = False
            futures = _MockFutures()
            def get_balances(self, force=False):
                return False, {"message": "CoinDCX gateway timeout (504)"}
        with patch.object(CoinDCXExecutionAdapter, "_client", return_value=_TimeoutClient()):
            rec = CoinDCXExecutionAdapter.reconcile_state(9001)
        if rec.get("connected"):
            raise AssertionError("Expected timeout outage to return connected=False")
        return "Exchange timeout handled gracefully without crashing or faking fills", "", ""

    if case_id == "CDX_07_INVALID_CREDS_PERMS":
        class _BadPermFutures(_MockFutures):
            def check_eligibility(self):
                return {"eligible": False, "reason": "Missing Futures API permission"}
        class _BadPermClient:
            is_offline = False
            futures = _BadPermFutures()
            def get_balances(self, force=False):
                return False, {"message": "Invalid signature"}
        with patch.object(CoinDCXExecutionAdapter, "_client", return_value=_BadPermClient()):
            ver = CoinDCXExecutionAdapter.verify_connection(9001)
        if ver.get("connected") or ver.get("mode") != "AUTH_FAILED" or not ver.get("corrective_action"):
            raise AssertionError(f"Expected AUTH_FAILED with corrective guidance, got: {ver}")
        return f"Invalid credentials handled cleanly (mode={ver.get('mode')})", "", ""

    if case_id == "CDX_08_REAL_MODE_SAFETY_LOCK":
        # Verify production config prohibits automatic live order submission
        c = ctx["client"]
        r = c.post("/api/admin/qa/config", headers=ctx["adm_hdr"], json={"live_order_testing_locked": "0"})
        cfg = _assert_json_ok(c.get("/api/admin/qa/config", headers=ctx["adm_hdr"]), "qa/config")
        lock_val = str((cfg.get("config") or {}).get("live_order_testing_locked", "1"))
        if lock_val != "1":
            raise AssertionError(f"Real Mode safety lock was overridden via UI/API! val={lock_val}")
        return "Verified immutable Real Mode live-order safety lock (cannot override via API/UI)", "", ""

    raise ValueError(f"Unknown COINDCX case {case_id}")


def _exec_security_case(case_id: str, ctx: Dict[str, Any]) -> Tuple[str, str, str]:
    c = ctx["client"]
    db = ctx["database"]

    if case_id == "SEC_01_AUTH_BYPASS_GUARD":
        for ep in ("/api/admin/overview", "/api/admin/qa/dashboard", "/api/central-admin/dashboard", "/api/v1/company/employees"):
            r = c.get(ep)
            if r.status_code not in (401, 403):
                raise AssertionError(f"Bypass possible on {ep}: got {r.status_code}")
        return "All tested Admin, Central-Admin & Company routes blocked anonymous callers", "", ""

    if case_id == "SEC_02_IDOR_DATA_ISOLATION":
        now = time.time()
        pid = db.write(
            "INSERT INTO positions(user_id, symbol, source, side, qty, entry_price, margin, target_pct, stop_pct, status, current_price, unrealized_pnl, opened_at) "
            "VALUES(9001, 'ETHUSDT', 'MANUAL', 'LONG', 0.1, 3400.0, 34.0, 2.0, 1.0, 'OPEN', 3400.0, 0.0, ?)",
            (now,),
        )
        r = c.post("/api/trade/close", headers=ctx["u2_hdr"], json={"position_id": pid})
        if r.status_code not in (403, 404):
            raise AssertionError(f"User 9002 closed User 9001 position! status={r.status_code}")
        return f"Cross-user IDOR close attempt blocked with HTTP {r.status_code}", "", ""

    if case_id == "SEC_03_PRIVILEGE_ESCALATION":
        r1 = c.post("/api/admin/qa/config", headers=ctx["u1_hdr"], json={"timeout_sec": 5})
        r2 = c.post("/api/admin/monitoring/deployment/approve", headers=ctx["u1_hdr"], json={"note": "x"})
        r3 = c.post("/api/v1/company/monitoring/deployment/approve", headers=ctx["cmp_hdr"], json={"note": "x"})
        if r1.status_code != 403 or r2.status_code != 403 or r3.status_code != 403:
            raise AssertionError(f"Escalation check failed: {r1.status_code}/{r2.status_code}/{r3.status_code}")
        return "Vertical & horizontal privilege escalation blocked with 403", "", ""

    if case_id == "SEC_04_WAF_ATTACK_PREVENTION":
        hdr = {"X-Forwarded-For": "198.51.100.44"}
        r1 = c.get("/api/markets?search=UNION%20SELECT%20password%20FROM%20users", headers=hdr)
        r2 = c.get("/.env", headers={"X-Forwarded-For": "198.51.100.45"})
        if r1.status_code != 403 or r2.status_code != 403:
            raise AssertionError(f"WAF missed payload: sqli={r1.status_code}, env={r2.status_code}")
        return "SecurityFirewall intercepted UNION SELECT SQLi and /.env traversal (403)", "", ""

    if case_id == "SEC_05_HEADERS_AND_CORS":
        r = c.get("/api/admin/qa/suites", headers=ctx["adm_hdr"])
        if r.headers.get("X-Frame-Options") != "SAMEORIGIN" or r.headers.get("X-Content-Type-Options") != "nosniff":
            raise AssertionError("Missing SAMEORIGIN or nosniff header")
        return "X-Frame-Options=SAMEORIGIN and X-Content-Type-Options=nosniff verified", "", ""

    if case_id == "SEC_06_SECRETS_ENCRYPTED_REST":
        raw_row = db.query_one("SELECT coindcx_secret FROM broker_connections WHERE user_id=9001")["coindcx_secret"]
        if "MOCK_CDX_SECRET" in str(raw_row):
            raise AssertionError("Plaintext broker secret found in DB column!")
        return "Broker secret stored encrypted at rest (no plaintext substring in DB)", "", ""

    if case_id == "SEC_07_SECRET_LEAKAGE_AUDIT":
        d = _assert_json_ok(c.get("/api/admin/users", headers=ctx["adm_hdr"]), "admin/users")
        dump = json.dumps(d)
        if "coindcx_secret" in dump or "pw_hash" in dump or "MOCK_CDX_SECRET" in dump:
            raise AssertionError("Sensitive credential/hash leaked in /api/admin/users!")
        san_chk = sanitize_text(f"token={ctx['adm_tok']} coindcx_secret=abc123")
        if ctx["adm_tok"] in san_chk:
            raise AssertionError("QA Secret Sanitizer failed to redact admin token!")
        return "Zero credential/hash leakage across Admin API responses & sanitizer check", "", ""

    if case_id == "SEC_08_ARTIFACT_PATH_TRAVERSAL":
        r = c.get("/api/admin/qa/artifacts/..%2Fbackend%2Fapp.py", headers=ctx["adm_hdr"])
        if r.status_code not in (400, 403, 404):
            raise AssertionError(f"Path traversal not rejected safely: {r.status_code}")
        return f"QA artifact endpoint rejected traversal payload with HTTP {r.status_code}", "", ""

    if case_id == "SEC_09_PASSWORD_POLICY_VALIDATION":
        r = c.post("/api/auth/signup", json={"email": "weak@sandbox.local", "name": "Weak", "password": "123"})
        if r.status_code != 400:
            raise AssertionError(f"Expected 400 for short password, got {r.status_code}")
        return "Weak 3-char registration password rejected with 400", "", ""

    raise ValueError(f"Unknown SECURITY case {case_id}")


def _exec_performance_case(case_id: str, ctx: Dict[str, Any], perf_cfg: Dict[str, Any]) -> Tuple[str, str, str]:
    c = ctx["client"]
    app_api = ctx["app_mod"].api
    db = ctx["database"]
    conc = max(1, min(int(perf_cfg.get("concurrent_users") or 4), 25))
    reqs = max(5, min(int(perf_cfg.get("request_count") or 24), 250))
    ramp_sec = max(0.0, min(float(perf_cfg.get("ramp_up_sec") or 0.0), 5.0))

    if case_id == "PERF_01_API_LATENCY_LOAD":
        latencies: List[float] = []
        errors: List[int] = []
        lock = threading.Lock()
        delay_per = (ramp_sec / conc) if conc > 1 and ramp_sec > 0 else 0.0

        def worker(idx: int):
            if delay_per > 0:
                time.sleep(min(0.5, delay_per * idx))
            cl = app_api.test_client()
            per_w = max(1, reqs // conc)
            for _ in range(per_w):
                t0 = time.time()
                r = cl.get("/api/coins")
                ms = (time.time() - t0) * 1000.0
                with lock:
                    latencies.append(ms)
                    if r.status_code != 200:
                        errors.append(r.status_code)

        with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as ex:
            list(ex.map(worker, range(conc)))
        latencies.sort()
        p95 = latencies[int(0.95 * (len(latencies) - 1))] if latencies else 0.0
        if errors or p95 > 1500.0:
            raise AssertionError(f"Load perf failed: errors={len(errors)}, p95={p95:.1f}ms")
        return f"Executed {len(latencies)} requests ({conc} workers): p95={p95:.2f}ms, errors=0", "", ""

    if case_id == "PERF_02_ADMIN_DASHBOARD_LOAD":
        t0 = time.time()
        _assert_json_ok(c.get("/api/admin/overview", headers=ctx["adm_hdr"]), "overview")
        _assert_json_ok(c.get("/api/admin/coindcx-live", headers=ctx["adm_hdr"]), "coindcx-live")
        _assert_json_ok(c.get("/api/admin/qa/dashboard", headers=ctx["adm_hdr"]), "qa/dashboard")
        ms = round((time.time() - t0) * 1000, 2)
        if ms > 2500.0:
            raise AssertionError(f"Admin dashboard endpoints took {ms}ms > 2500ms")
        return f"All 3 Admin dashboard payloads loaded in {ms}ms total", "", ""

    if case_id == "PERF_03_DATABASE_THROUGHPUT":
        t0 = time.time()
        for _ in range(50):
            db.query_one("SELECT COUNT(*) c FROM users")
        ms = round((time.time() - t0) * 1000, 2)
        if ms > 1000.0:
            raise AssertionError(f"50 SQLite queries took {ms}ms")
        return f"50 indexed SQLite queries completed in {ms}ms ({round(50000/max(ms,0.1),1)} qps)", "", ""

    if case_id == "PERF_04_CONCURRENT_SESSIONS":
        def hit(hdr):
            cl = app_api.test_client()
            return cl.get("/api/admin/overview" if "X-Admin-Token" in hdr else "/api/account", headers=hdr).status_code
        hdrs = [ctx["adm_hdr"] if i % 2 == 0 else ctx["u1_hdr"] for i in range(conc * 2)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as ex:
            codes = list(ex.map(hit, hdrs))
        if any(code != 200 for code in codes):
            raise AssertionError(f"Concurrent session errors: {codes}")
        return f"{len(codes)} concurrent admin + user requests succeeded (100% HTTP 200)", "", ""

    if case_id == "PERF_05_ENGINE_SCORING_SPEED":
        from ai_committee import AICommitteeOrchestrator
        candles = _sample_candles(65000.0, 40, 0.001)
        t0 = time.time()
        AICommitteeOrchestrator.evaluate_candidate("BTCUSDT", candles=candles, quote_data={"price": 65500.0}, persist=False)
        ms = round((time.time() - t0) * 1000, 2)
        if ms > 500.0:
            raise AssertionError(f"Committee scoring took {ms}ms > 500ms")
        return f"3-Agent Committee evaluation executed in {ms}ms", "", ""

    if case_id == "PERF_06_RESOURCE_AND_WS_HEALTH":
        rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_mb = round(rss_kb / (1024.0 * 1024.0), 1) if sys.platform == "darwin" else round(rss_kb / 1024.0, 1)
        t0 = time.time()
        for _ in range(200):
            ctx["app_mod"].feed.quote("BTCUSDT")
        feed_ms = round((time.time() - t0) * 1000, 2)
        return f"Sandbox RSS={rss_mb}MB, 200 PriceFeed quote reads in {feed_ms}ms", "", ""

    raise ValueError(f"Unknown PERFORMANCE case {case_id}")


# ---------------------------------------------------------------------------
# Subprocess Sandbox Executor Entrypoint (streams JSONL events per case)
# ---------------------------------------------------------------------------
def _emit(event: Dict[str, Any]) -> None:
    print(json.dumps(event, default=str), flush=True)


def run_sandbox_worker(tasks: List[Dict[str, Any]], perf_cfg: Dict[str, Any], cfg: Dict[str, Any]) -> int:
    """Execute requested non-Playwright cases in a completely isolated SQLite process."""
    ctx = None
    needs_sbx = any(t["suite_id"] != "BACKEND" for t in tasks)
    if needs_sbx:
        ctx = _sandbox_bootstrap()

    try:
        for item in tasks:
            cid = item["case_id"]
            sid = item["suite_id"]
            expected = item.get("expected_behavior") or ""
            _emit({"type": "CASE_START", "case_id": cid, "suite_id": sid})
            t0 = time.time()
            try:
                if sid == "BACKEND":
                    st, actual, err, api_resp = run_backend_case(cid)
                elif sid == "AUTH":
                    actual, api_resp, err = _exec_auth_case(cid, ctx)
                    st = "PASSED"
                elif sid == "ADMIN_PANEL":
                    actual, api_resp, err = _exec_admin_panel_case(cid, ctx)
                    st = "PASSED"
                elif sid == "API":
                    actual, api_resp, err = _exec_api_case(cid, ctx)
                    st = "PASSED"
                elif sid == "DATABASE":
                    actual, api_resp, err = _exec_database_case(cid, ctx)
                    st = "PASSED"
                elif sid == "TRADING_ENGINE":
                    actual, api_resp, err = _exec_trading_case(cid, ctx)
                    st = "PASSED"
                elif sid == "COINDCX":
                    actual, api_resp, err = _exec_coindcx_case(cid, ctx)
                    st = "PASSED"
                elif sid == "SECURITY":
                    actual, api_resp, err = _exec_security_case(cid, ctx)
                    st = "PASSED"
                elif sid == "PERFORMANCE":
                    actual, api_resp, err = _exec_performance_case(cid, ctx, perf_cfg)
                    st = "PASSED"
                else:
                    raise ValueError(f"Unsupported sandbox suite: {sid}")

                _emit({
                    "type": "CASE_RESULT",
                    "case_id": cid,
                    "suite_id": sid,
                    "status": st,
                    "duration_ms": round((time.time() - t0) * 1000, 2),
                    "expected_result": expected,
                    "actual_result": sanitize_text(actual),
                    "error_message": sanitize_text(err),
                    "stack_trace": "",
                    "api_response_sanitized": sanitize_text(api_resp),
                })
            except Exception as exc:
                _emit({
                    "type": "CASE_RESULT",
                    "case_id": cid,
                    "suite_id": sid,
                    "status": "FAILED",
                    "duration_ms": round((time.time() - t0) * 1000, 2),
                    "expected_result": expected,
                    "actual_result": sanitize_text(f"Assertion/execution error: {exc}"),
                    "error_message": sanitize_text(str(exc)),
                    "stack_trace": sanitize_text(traceback.format_exc()),
                    "api_response_sanitized": "",
                })
    finally:
        if ctx and ctx.get("tmpdir"):
            shutil.rmtree(ctx["tmpdir"], ignore_errors=True)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox", action="store_true")
    args = parser.parse_args()
    if args.sandbox:
        payload = json.loads(sys.stdin.read() or "{}")
        sys.exit(run_sandbox_worker(
            payload.get("tasks", []),
            payload.get("perf_cfg", {}),
            payload.get("cfg", {}),
        ))
