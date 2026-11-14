# ARAABOT – IMPLEMENTATION CHANGELOG

## [v2.1.0-ENTERPRISE] - 2026-11-15

### Added
- **POOL_CRYPTO_FUTURES Capital Pool**:
  - Added third isolated pool `POOL_CRYPTO_FUTURES` in `backend/company_finance.py` and `backend/migrations.py`.
  - Configured independent risk policies and broker mappings (`COINDCX_FUTURES`).
- **REST API Endpoints & Aliases**:
  - `GET /api/v1/company/capital-pools/<pool_id>`
  - `POST /api/v1/company/capital-pools/<pool_id>/allocate`
  - `POST /api/v1/company/capital-pools/<pool_id>/deallocate`
  - `GET /api/v1/company/capital-pools/<pool_id>/transactions`
  - `GET /api/v1/company/capital-pools/<pool_id>/reconciliation`
  - `POST /api/v1/company/auth/refresh`
  - `POST /api/v1/company/employees/<emp_id>/roles`
  - `POST /api/v1/company/employees/<emp_id>/revoke-sessions`
  - `GET /api/v1/company/permissions`
  - `GET /api/v1/company/audit/permissions`
  - `GET /api/admin/system/health`
  - `GET /api/admin/system/modules`
  - `GET /api/admin/system/integrations`
  - `GET /api/admin/system/database`
  - `GET /api/admin/system/workers`
  - `GET /api/admin/system/security`
  - `GET /api/admin/system/updates`
  - `GET /api/admin/system/readiness`
  - `POST /api/admin/system/validation/run`
  - `GET /api/admin/system/validation/<run_id>`
  - `GET /api/admin/system/validation/history`
- **UI Mappings**:
  - Admin Panel: Integrated System Diagnostics, Playwright Automation, Update History, and Production Deployment Gate into `admin/index.html` and `admin/admin.js`.
  - Company Panel: Integrated Operational Diagnostics & Automated Test Status into `company/index.html` and `company/company.js`.
- **System Documentation**:
  - `docs/FEATURE_IMPLEMENTATION_MAPPING.md`
  - `docs/API_FRONTEND_MAPPING.md`
  - `docs/BACKEND_MISSING_FEATURES_REPORT.md`
  - `docs/PRODUCTION_READINESS_REPORT.md`
  - `docs/IMPLEMENTATION_CHANGELOG.md`

### Changed
- Mounted `enterprise_v1_api.v1_api` blueprint at both `/api/v1` and `/api` to support both versioned and legacy company API calls.
- Enforced strict server-side **HTTP 403 Forbidden** on `/api/admin/*`, `/api/v3/admin/*`, and `/api/v1/company/*` whenever a regular user session token is presented.

### Security
- Verified that production deployment approval is exclusively reserved for `SUPER_ADMIN`/`ADMIN` and fails with 403 if called by any company employee or customer user.
