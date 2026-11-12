# ARAA Platform — Phase 1 Security Audit (`SECURITY_AUDIT.md`)

**Inspected Target:** `AraaBot-Online-Production-Ready`  
**Audit Date:** 2026-11-11  
**Classification Standard:** Findings below are directly verified from source files. Exact secret values are intentionally omitted from this report.

---

## 1. Security Findings Register

### CRITICAL Findings

| ID | Location | Finding | Impact | Required Remediation (Phase) |
| :--- | :--- | :--- | :--- | :--- |
| **SEC-01** | `backend/gemini_advisor.py:36,44` | Hardcoded API key assigned to `UNIVERSAL_KEY` and used as fallback when `GEMINI_API_KEY` env var is unset. | Exposed credential in source/ZIP archives; unauthorized quota usage if leaked. | **FIXED IN PHASE 1** (literal removed; reads `GEMINI_API_KEY` env / DB only). Operator should still rotate the previously exposed Google API key externally. |
| **SEC-02** | `backend/enterprise_v1_api.py:70-72` | `get_authenticated_user()` falls back to `SELECT * FROM users ORDER BY id DESC LIMIT 1` whenever no auth header/cookie is present. | Any unauthenticated HTTP request reaching `/api/v1/*` routes executes under the most recently created user's session in production if not blocked. | Remove unauthenticated fallback completely; fail closed with HTTP `401` unless valid session token (`X-Token` / `Bearer` / signed cookie / valid `X-Admin-Token`) is presented. (Phase 2) |
| **SEC-03** | `backend/real_broker.py:19-52,347` | Global mutable singleton `_EXCHANGE_CLIENT` / `_EXCHANGE_ID` reading global `BROKER_API_KEY` env/`platform_state`, plus `"fallback_to_paper": True` returned on live execution failure. | Cross-account credential leakage risk and silent misrepresentation of failed live trades as paper fallbacks. | **PARTIAL FIX IN PHASE 1** (`fallback_to_paper` set to `False`). Full replacement of global `_EXCHANGE_CLIENT` with isolated `UniversalBrokerManager` scheduled in Phases 4–5. |
| **SEC-04** | `backend/saas_manager.py:29-32` | Hardcoded fallback signing secret string (`PAYMENT_SIGNING_SECRET`) when `RAZORPAY_KEY_SECRET` and `JWT_SECRET` are unset. | Predictable HMAC payment signatures if deployed without env secrets. | **FIXED IN PHASE 1** (replaced static fallback literal with ephemeral `secrets.token_hex(32)` per process; module itself scheduled for archival in Phase 2). |

### HIGH Findings

| ID | Location | Finding | Impact | Required Remediation (Phase) |
| :--- | :--- | :--- | :--- | :--- |
| **SEC-05** | `backend/upi_gateway.py:30-31` | Hardcoded default PhonePe `phonepe_api_key` fallback UUID in source (`get_upi_config`). | UAT merchant key exposed in source control. | **FIXED IN PHASE 1** (replaced hardcoded UUID/MID defaults with `os.environ.get` / empty string; customer UPI module scheduled for archival in Phase 2). |
| **SEC-06** | `backend/database.py:1157-1171` | `encrypt_secret()` silently returns **plaintext** if `SECRETS_KEY` env var is unset or `cryptography` fails to load. | Company broker API secrets stored unencrypted in SQLite (`TradePro` fallback). | Enforce mandatory `SECRETS_KEY` on startup (`fail closed` in `LIVE`/prod modes) so plaintext broker secrets can never be written to DB. (Phase 2) |
| **SEC-07** | `backend/app.py:5742-5746, 6199-6204` | `SEED_DEMO_USERS` defaults to `"1"` on empty DB boot and prints default demo credentials (`demo1234`) to stdout logs. | Predictable default user accounts created automatically on fresh production deployment. | Set `SEED_DEMO_USERS` default to `"0"`, remove demo credential log printing, and seed initial company Super Admin securely via CLI bootstrap or env only. (Phase 2) |
| **SEC-08** | `backend/database.py` (all schema tables) | Binary floating-point `REAL` used for balances, P&L, fees, quantities, and prices. | Rounding drift across ledger reconciliation and balance checks. | Migrate financial ledger and company pool accounting to integer minor units (`paise` for INR) and `Decimal` precision representation. (Phase 3) |
| **SEC-09** | Repository distribution / `.env` hygiene | Live `.env` previously existed alongside distributed ZIP exports; ensure production archives exclude `.env` and `*.db`. | Credential exposure in archive files (`AraaBot-Online-Production-Ready.zip`). | Rotate any API keys ever saved inside historical `.env` or `.db` files; enforce secret scanning in CI/pre-release checks. (Phase 1 & 12) |

### MEDIUM Findings

| ID | Location | Finding | Impact | Required Remediation (Phase) |
| :--- | :--- | :--- | :--- | :--- |
| **SEC-10** | `backend/app.py` (CORS & CSRF) | Cookie/header SPA auth lacks explicit CSRF double-submit / SameSite enforcement if cookie sessions are introduced; wildcard/permissive CORS could expose APIs to unauthorized origins. | Cross-site request risk if browser cookies are enabled later. | Enforce strict `ALLOWED_ORIGINS` CORS allowlist, CSRF tokens on state-changing routes, and `HttpOnly; SameSite=Strict; Secure` cookie flags. (Phase 2 & 12) |
| **SEC-11** | `backend/security_firewall.py` | WAF (`ip_requests`, `banned_ips`, `threat_logs`) is purely in-memory (`defaultdict` / `list`). | State resets on server restart and does not share across multiple Gunicorn workers or containers. | Persist security events to `audit_logs` / `risk_events` and back rate-limiting with Redis in Phase 12. |
| **SEC-12** | Broker Static Egress IP | No egress IP validation / enforcement before order placement. | SEBI / NSE / Zerodha algo APIs reject orders from unregistered dynamic IPs; CoinDCX IP allowlists improve key safety. | Add configurable static IP health check & host egress documentation before enabling `LIVE` trading. (Phase 4 & 12) |
| **SEC-13** | Customer Auth & RBAC (`users`, `admin`) | No company role hierarchy, no TOTP 2FA on employees/admins, no admin activity audit log filtering by operator ID. | Single shared admin credential cannot distinguish between Finance, Risk, Trading, Technical, and Auditor operators. | Implement 7-role RBAC + TOTP MFA + immutable `audit_logs` recording `actor_user_id`, IP, action, before/after JSON. (Phase 2) |

---

## 2. Positive Security Controls Already Present
- `backend/database.py`: PBKDF2-HMAC-SHA256 (`210,000` iterations) salted password hashing with `secrets.compare_digest` verification.
- `backend/app.py:108-137`: Mandatory `X-Admin-Token` authentication guard on `/api/admin/*` routes with configurable `ADMIN_SESSION_TTL` (`43200s`), with no default fallback admin password.
- `backend/coindcx_gateway.py` & `backend/bot_engine.py`: Strict live-close safety verified by `tests/test_security_and_close.py` (`close_real_order` refuses to report `closed=True` when the exchange API fails).
- `backend/security_firewall.py`: Active inspection blocking SQLi, XSS, and `.env`/`.git` traversal probes.
- `.gitignore`: Properly ignores `.env`, `*.db`, `*.sqlite`, `.venv/`.
