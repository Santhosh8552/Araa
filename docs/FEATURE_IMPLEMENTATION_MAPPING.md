# ARAABOT – COMPLETE FEATURE IMPLEMENTATION MAPPING

## System Architecture Overview
AraaBot is an institutional-grade quantitative algorithmic trading platform uniting ARAA Quant AI v4.0, a 16-state Idempotent Order Management System (OMS), Pre-Trade Risk Guardian, Double-Entry Financial Ledger, and isolated broker connectivity.

---

## 1. Role-Based Access Control (RBAC) & Employee Governance
- **Feature Name**: Institutional Employee Authentication & 7-Role RBAC
- **Backend File**: `backend/company_auth.py`, `backend/enterprise_v1_api.py`
- **Backend Service**: `CompanyAuthService`
- **Database Tables**: `company_users`, `roles`, `company_permissions`, `role_permissions`, `company_sessions`, `company_audit_logs`
- **API Endpoints**:
  - `POST /api/v1/company/auth/login` (and `/api/company/auth/login`)
  - `POST /api/v1/company/auth/logout`
  - `POST /api/v1/company/auth/refresh`
  - `POST /api/v1/company/auth/mfa/enroll`
  - `POST /api/v1/company/auth/mfa/verify`
  - `GET /api/v1/company/auth/me`
  - `GET /api/v1/company/employees`
  - `POST /api/v1/company/employees`
  - `PATCH /api/v1/company/employees/{id}`
  - `POST /api/v1/company/employees/{id}/roles`
  - `POST /api/v1/company/employees/{id}/revoke-sessions`
  - `GET /api/v1/company/permissions`
  - `GET /api/v1/company/audit/permissions`
- **Frontend Component**: `EmployeeManagement`
- **Frontend Route**: `company/index.html` → `#view_employees`
- **Navigation Location**: Company Panel → Enterprise Admin → Employees, RBAC & MFA
- **Required Permission**: `employees.view`, `employees.manage`
- **Test File**: `tests/test_panel_access_restriction.py`, `tests/test_company_phases1_to_4_acceptance.py`
- **Test Status**: PASSED (100%)
- **Integration Status**: IMPLEMENTED

---

## 2. Independent Capital Pools
- **Feature Name**: Strictly Isolated Capital Pools (India INR, Crypto Spot, Crypto Futures)
- **Backend File**: `backend/company_finance.py`, `backend/enterprise_v1_api.py`
- **Backend Service**: `CompanyCapitalManager`
- **Database Tables**: `company_capital_pools`, `company_capital_movements`, `capital_allocations`, `company_risk_policies`
- **API Endpoints**:
  - `GET /api/v1/company/capital-pools`
  - `GET /api/v1/company/capital-pools/{pool_id}`
  - `POST /api/v1/company/capital-pools`
  - `POST /api/v1/company/capital-pools/{pool_id}/allocate`
  - `POST /api/v1/company/capital-pools/{pool_id}/deallocate`
  - `GET /api/v1/company/capital-pools/{pool_id}/transactions`
  - `GET /api/v1/company/capital-pools/{pool_id}/reconciliation`
- **Frontend Component**: `CapitalPoolManagement`
- **Frontend Route**: `company/index.html` → `#view_finance`
- **Navigation Location**: Company Panel → Finance & Governance → Capital Pools & Finance
- **Required Permission**: `capital.view`, `capital.move`, `capital.allocate`
- **Test File**: `tests/test_company_phases5_to_12_acceptance.py`
- **Test Status**: PASSED (100%)
- **Integration Status**: IMPLEMENTED

---

## 3. Universal Broker Manager & Adapters
- **Feature Name**: Account-Isolated Multi-Broker Orchestration & Credential Vault
- **Backend File**: `backend/universal_broker_manager.py`, `backend/zerodha_adapter.py`, `backend/coindcx_spot_adapter.py`, `backend/coindcx_gateway.py`
- **Backend Service**: `UniversalBrokerManager`
- **Database Tables**: `company_trading_accounts`, `broker_account_secrets`, `broker_capabilities`
- **API Endpoints**:
  - `GET /api/v1/company/accounts`
  - `POST /api/v1/company/accounts`
  - `POST /api/v1/brokers/zerodha/connect-url`
  - `POST /api/v1/brokers/zerodha/callback`
  - `POST /api/v1/brokers/zerodha/sync`
  - `POST /api/v1/brokers/zerodha/disconnect`
  - `POST /api/v1/brokers/coindcx/sync`
  - `POST /api/v1/brokers/coindcx/disconnect`
- **Frontend Component**: `BrokerConnectionCenter`
- **Frontend Route**: `company/index.html` → `#view_india`, `#view_crypto`
- **Navigation Location**: Company Panel → Trading Desks → India Pool / Crypto Pool
- **Required Permission**: `brokers.view`, `brokers.manage`
- **Test File**: `tests/test_company_phases1_to_4_acceptance.py`
- **Test Status**: PASSED (100%)
- **Integration Status**: IMPLEMENTED

---

## 4. 16-State Order Management System (OMS) & Pre-Trade Risk
- **Feature Name**: Institutional 16-State OMS with Idempotent Deduplication
- **Backend File**: `backend/company_oms.py`, `backend/company_risk_guardian.py`
- **Backend Service**: `CompanyOMS`, `CompanyRiskGuardian`
- **Database Tables**: `order_intents`, `broker_orders`, `broker_executions`, `company_positions`, `company_risk_events`
- **API Endpoints**:
  - `GET /api/v1/company/orders`
  - `POST /api/v1/company/orders/intent`
  - `POST /api/v1/company/orders/{provider_order_id}/cancel`
  - `GET /api/v1/company/positions`
  - `POST /api/v1/company/trading/flatten-preview`
  - `POST /api/v1/company/trading/flatten-confirm`
- **Frontend Component**: `CompanyOrderManagement`
- **Frontend Route**: `company/index.html` → `#view_orders`, `#view_positions`
- **Navigation Location**: Company Panel → Trading Desks → 16-State OMS & Orders / Live Positions
- **Required Permission**: `orders.create`, `orders.cancel`, `trading.control`
- **Test File**: `tests/test_company_phases5_to_12_acceptance.py`
- **Test Status**: PASSED (100%)
- **Integration Status**: IMPLEMENTED

---

## 5. Automated Broker Reconciliation Engine
- **Feature Name**: Automated Multi-Asset Reconciliation & Discrepancy Halt
- **Backend File**: `backend/company_ledger_recon.py`
- **Backend Service**: `CompanyReconciliationService`
- **Database Tables**: `reconciliation_runs`, `reconciliation_differences`, `company_ledger_entries`
- **API Endpoints**:
  - `POST /api/v1/company/reconciliation/run`
  - `GET /api/v1/company/reconciliation/runs`
  - `GET /api/v1/company/reconciliation/differences`
  - `POST /api/v1/company/reconciliation/differences/{id}/resolve`
- **Frontend Component**: `ReconciliationCenter`
- **Frontend Route**: `company/index.html` → `#view_reconciliation`
- **Navigation Location**: Company Panel → Finance & Governance → Reconciliation Inspector
- **Required Permission**: `reconciliation.run`, `audit.view`
- **Test File**: `tests/test_company_phases5_to_12_acceptance.py`
- **Test Status**: PASSED (100%)
- **Integration Status**: IMPLEMENTED

---

## 6. Admin System Monitoring, Health & Playwright Automation Center
- **Feature Name**: Master Platform Telemetry, Git Update Detection & E2E Testing
- **Backend File**: `backend/system_monitoring.py`, `backend/app.py`
- **Backend Service**: `SystemMonitoringEngine`
- **Database Tables**: `system_monitoring_runs`, `program_update_events`, `deployment_records`
- **API Endpoints**:
  - `GET /api/admin/system/health` (and `/api/admin/monitoring/health`)
  - `GET /api/admin/system/modules`
  - `GET /api/admin/system/integrations`
  - `GET /api/admin/system/database`
  - `GET /api/admin/system/workers`
  - `GET /api/admin/system/security`
  - `GET /api/admin/system/updates` (and `/api/admin/monitoring/updates`)
  - `GET /api/admin/system/readiness` (and `/api/admin/monitoring/deployment/readiness`)
  - `POST /api/admin/system/validation/run` (and `/api/admin/monitoring/playwright/run`)
  - `GET /api/admin/system/validation/{run_id}`
  - `GET /api/admin/system/validation/history`
  - `POST /api/admin/monitoring/deployment/approve` (SUPER_ADMIN / ADMIN Only)
- **Frontend Component**: `AdminSystemDiagnostics`
- **Frontend Route**: `admin/index.html` → `[data-adm-sec="system-diagnostics"]`
- **Navigation Location**: Admin Panel → COMMAND MODULES → 🛠️ Diagnostics & Testing
- **Required Permission**: `SUPER_ADMIN`, `ADMIN` (Server-side 403 enforcement for USER)
- **Test File**: `tests/test_panel_access_restriction.py`
- **Test Status**: PASSED (100%)
- **Integration Status**: IMPLEMENTED
