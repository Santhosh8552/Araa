# ARAABOT – COMPLETE API & FRONTEND MAPPING SPECIFICATION

This document details the exact contract between Frontend Panels, Authorization Gates, API Routes, and Database Handlers.

---

## 1. ADMIN PANEL MAPPING (`/admin/`)

| Section | UI Element / Trigger | Method | API Endpoint | RBAC Guard | DB Table / Backend Service |
| :--- | :--- | :---: | :--- | :--- | :--- |
| **System Diagnostics** | ⚡ Run Diagnostics | `GET` | `/api/admin/system/health` | `SUPER_ADMIN`, `ADMIN` | `SystemMonitoringEngine.run_backend_health_diagnostics` |
| **Update History** | Load Updates | `GET` | `/api/admin/system/updates` | `SUPER_ADMIN`, `ADMIN` | `git rev-parse` / `program_update_events` |
| **Automated Validation**| 🎭 Execute Playwright | `POST` | `/api/admin/system/validation/run` | `SUPER_ADMIN`, `ADMIN` | `system_monitoring_runs` |
| **Validation History** | Test Run History | `GET` | `/api/admin/system/validation/history` | `SUPER_ADMIN`, `ADMIN` | `system_monitoring_runs` |
| **Database Health** | DB Telemetry Bento | `GET` | `/api/admin/system/database` | `SUPER_ADMIN`, `ADMIN` | SQLite WAL / Connection stats |
| **Integration Health** | Broker Integrations | `GET` | `/api/admin/system/integrations` | `SUPER_ADMIN`, `ADMIN` | CoinDCX / Zerodha API health |
| **Security Audit** | 🛡️ Audit Integration | `GET` | `/api/admin/system/security` | `SUPER_ADMIN`, `ADMIN` | RBAC / Double-entry audit checks |
| **Production Readiness**| Readiness Score | `GET` | `/api/admin/system/readiness` | `SUPER_ADMIN`, `ADMIN` | `deployment_records` |
| **Release Sign-Off** | 🚀 Approve Deploy | `POST` | `/api/admin/monitoring/deployment/approve` | **SUPER_ADMIN Only** | `deployment_records` |

---

## 2. COMPANY PANEL MAPPING (`/company/`)

| Section | UI Element / Trigger | Method | API Endpoint | RBAC Guard | DB Table / Backend Service |
| :--- | :--- | :---: | :--- | :--- | :--- |
| **Employees & Access** | Employee Directory | `GET` | `/api/v1/company/employees` | `employees.view` | `company_users` |
| **Create Employee** | New Employee Form | `POST` | `/api/v1/company/employees` | `employees.manage` | `company_users`, `company_audit_logs` |
| **Update Employee** | Edit Employee / Role | `PATCH`| `/api/v1/company/employees/{id}` | `employees.manage` | `company_users` |
| **Revoke Sessions** | Revoke Access Button | `POST` | `/api/v1/company/employees/{id}/revoke-sessions` | `employees.manage` | `company_sessions` |
| **Capital Pools** | Pool Overview | `GET` | `/api/v1/company/capital-pools` | `capital.view` | `company_capital_pools` |
| **Capital Allocation** | Strategy Allocator | `POST` | `/api/v1/company/capital-pools/{id}/allocate` | `capital.allocate` | `capital_allocations` |
| **Capital Movement** | Deposit / Transfer | `POST` | `/api/v1/company/capital-pools` | `capital.move` | `company_capital_movements` |
| **Zerodha Desk** | Connect & Sync | `POST` | `/api/v1/brokers/zerodha/sync` | `brokers.manage` | `broker_accounts`, `ZerodhaKiteAdapter` |
| **CoinDCX Spot Desk** | Spot Balances & Sync | `POST` | `/api/v1/brokers/coindcx/sync` | `brokers.manage` | `CoinDCXSpotAdapter` |
| **16-State OMS** | Order Book | `GET` | `/api/v1/company/orders` | `company.view` | `broker_orders`, `order_intents` |
| **Order Intent** | Propose & Submit | `POST` | `/api/v1/company/orders/intent` | `orders.create` | `CompanyOMS.submit_order_intent` |
| **Live Positions** | Positions Grid | `GET` | `/api/v1/company/positions` | `company.view` | `company_positions` |
| **Emergency Flatten** | Flatten Confirm | `POST` | `/api/v1/company/trading/flatten-confirm` | `risk.emergency_stop` | `CompanyOMS.flatten_confirm` |
| **Financial Ledger** | Ledger Entries | `GET` | `/api/v1/company/ledger` | `audit.view` | `company_ledger_entries` |
| **Reconciliation** | Run Auto Recon | `POST` | `/api/v1/company/reconciliation/run` | `reconciliation.run` | `reconciliation_runs` |
| **Risk Guardian** | Risk Policies | `GET` | `/api/v1/company/risk/policies` | `risk.view` | `company_risk_policies` |
| **Operational Health** | Telemetry Panel | `GET` | `/api/v1/company/monitoring/overview` | `Company User` | `SystemMonitoringEngine` |

---

## 3. USER PANEL STRICT ISOLATION (`/`)

- Customer-facing trading workspace: Live Chart, Auto Scalping, Order Execution, Portfolio, P&L, Bot Settings, Notifications.
- **Zero** company employee management, internal capital pools, financial journals, broker credentials, or admin diagnostics exposed.
- Manual access attempts to `/api/admin/*`, `/api/v3/admin/*`, or `/api/v1/company/*` strictly return **HTTP 403 Forbidden**.
