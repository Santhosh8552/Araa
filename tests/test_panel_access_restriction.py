"""
Test Suite: Strict Admin & Company Panel Only Access Restriction.
Verifies that:
1. USER role is strictly rejected with HTTP 403 Forbidden when calling Admin or Company diagnostic/playwright/monitoring endpoints.
2. ADMIN / SUPER_ADMIN has full access to update detection, health diagnostics, Playwright test execution, integration audit, and production deployment approval.
3. COMPANY_* users have authorized access to company operational monitoring and diagnostics.
4. Non-admin roles (COMPANY_DIRECTOR, etc.) are strictly forbidden (403) from approving production deployments.
"""

import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

import app as flask_app
from database import query_one, set_state, write
from system_monitoring import SystemMonitoringEngine, ensure_monitoring_tables


class TestPanelAccessRestriction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_monitoring_tables()
        cls.client = flask_app.api.test_client()

        # 1. Setup Admin session token in platform_state
        cls.admin_token = "adm_test_security_master_999"
        set_state(f"admin_session_{cls.admin_token}", json.dumps({"user": "admin_test", "time": time.time()}))

        # 2. Setup Company session token in company_sessions & company_users
        now = time.time()
        cls.company_token = "cmp_test_operator_token_777"
        cls.company_user_id = 99991
        cls.company_id = 1

        write(
            "INSERT OR REPLACE INTO company_users(id, company_id, email, full_name, pw_salt, pw_hash, role_code, status, mfa_enabled, created_at, updated_at) "
            "VALUES(?, ?, 'operator@araabot.in', 'Test Operator', 'salt', 'hash', 'COMPANY_OPERATOR', 'ACTIVE', 0, ?, ?)",
            (cls.company_user_id, cls.company_id, now, now),
        )
        write(
            "INSERT OR REPLACE INTO company_sessions(token, company_id, company_user_id, role_code, ip_address, user_agent, mfa_verified, revoked, expires_at, created_at, last_seen) "
            "VALUES(?, ?, ?, 'COMPANY_OPERATOR', '127.0.0.1', 'test_agent', 0, 0, ?, ?, ?)",
            (cls.company_token, cls.company_id, cls.company_user_id, now + 3600, now, now),
        )

        # 3. Setup regular USER token in sessions & users
        cls.user_token = "usr_test_token_555"
        cls.user_id = 88881
        write(
            "INSERT OR REPLACE INTO users(id, email, name, pw_salt, pw_hash, role, account_status, created_at) "
            "VALUES(?, 'trader@example.com', 'Regular User', 'salt', 'hash', 'CUSTOMER', 'ACTIVE', ?)",
            (cls.user_id, now),
        )
        write(
            "INSERT OR REPLACE INTO sessions(token, user_id, created_at, last_seen) "
            "VALUES(?, ?, ?, ?)",
            (cls.user_token, cls.user_id, now, now),
        )

    # -------------------------------------------------------------------------
    # PART 1: USER ROLE MUST RECEIVE 403 FORBIDDEN ON ALL MONITORING & DIAGNOSTIC ENDPOINTS
    # -------------------------------------------------------------------------
    def test_user_forbidden_from_admin_monitoring_updates(self):
        resp = self.client.get("/api/admin/monitoring/updates", headers={"X-Token": self.user_token})
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertFalse(data.get("success", True))
        self.assertIn("Forbidden", data.get("error", ""))

    def test_user_forbidden_from_admin_monitoring_health(self):
        resp = self.client.get("/api/admin/monitoring/health", headers={"X-Token": self.user_token})
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertFalse(data.get("success", True))
        self.assertIn("Forbidden", data.get("error", ""))

    def test_user_forbidden_from_admin_playwright_run(self):
        resp = self.client.post("/api/admin/monitoring/playwright/run", headers={"X-Token": self.user_token})
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertFalse(data.get("success", True))
        self.assertIn("Forbidden", data.get("error", ""))

    def test_user_forbidden_from_admin_audit_run(self):
        resp = self.client.post("/api/admin/monitoring/audit/run", headers={"X-Token": self.user_token})
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertFalse(data.get("success", True))
        self.assertIn("Forbidden", data.get("error", ""))

    def test_user_forbidden_from_admin_deployment_readiness(self):
        resp = self.client.get("/api/admin/monitoring/deployment/readiness", headers={"X-Token": self.user_token})
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertFalse(data.get("success", True))
        self.assertIn("Forbidden", data.get("error", ""))

    def test_user_forbidden_from_admin_deployment_approve(self):
        resp = self.client.post("/api/admin/monitoring/deployment/approve", headers={"X-Token": self.user_token}, json={"note": "hacked"})
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertFalse(data.get("success", True))
        self.assertIn("Forbidden", data.get("error", ""))

    def test_user_forbidden_from_company_monitoring_overview(self):
        resp = self.client.get("/api/v1/company/monitoring/overview", headers={"X-Token": self.user_token})
        self.assertIn(resp.status_code, (401, 403))
        data = resp.get_json()
        self.assertFalse(data.get("success", True))

    def test_user_forbidden_from_company_system_health(self):
        resp = self.client.get("/api/v1/company/system/health", headers={"X-Token": self.user_token})
        self.assertIn(resp.status_code, (401, 403))
        data = resp.get_json()
        self.assertFalse(data.get("success", True))

    # -------------------------------------------------------------------------
    # PART 2: ADMIN / SUPER_ADMIN HAS FULL ACCESS TO DIAGNOSTICS, PLAYWRIGHT & DEPLOYMENT
    # -------------------------------------------------------------------------
    def test_admin_access_program_updates(self):
        resp = self.client.get("/api/admin/monitoring/updates", headers={"X-Admin-Token": self.admin_token})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("current_commit", data)
        self.assertIn("branch", data)
        self.assertIn("recent_commits", data)
        self.assertEqual(data.get("version"), "2.1.0-ENTERPRISE")

    def test_admin_access_backend_health_diagnostics(self):
        resp = self.client.get("/api/admin/monitoring/health", headers={"X-Admin-Token": self.admin_token})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("system_status", data)
        self.assertIn("services", data)
        self.assertEqual(data["services"]["database"]["status"], "HEALTHY")
        self.assertEqual(data["services"]["coindcx_integration"]["status"], "HEALTHY")

    def test_admin_execute_playwright_tests(self):
        resp = self.client.post("/api/admin/monitoring/playwright/run", headers={"X-Admin-Token": self.admin_token})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "PASSED")
        self.assertGreater(data.get("total_tests", 0), 0)
        self.assertGreater(data.get("passed_tests", 0), 0)

    def test_admin_execute_integration_audit(self):
        resp = self.client.post("/api/admin/monitoring/audit/run", headers={"X-Admin-Token": self.admin_token})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "PASSED")
        self.assertIn("checks", data)

    def test_admin_deployment_readiness_and_approval(self):
        # 1. Readiness check
        resp = self.client.get("/api/admin/monitoring/deployment/readiness", headers={"X-Admin-Token": self.admin_token})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("environment"), "PRODUCTION")
        self.assertTrue(data.get("admin_deployment_gate_locked"))

        # 2. Production Deployment Approval
        resp = self.client.post(
            "/api/admin/monitoring/deployment/approve",
            headers={"X-Admin-Token": self.admin_token},
            json={"note": "Official v2.1.0 Production Sign-Off"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("status"), "PRODUCTION_DEPLOYMENT_APPROVED")
        self.assertEqual(data.get("approved_by_role"), "SUPER_ADMIN")

    # -------------------------------------------------------------------------
    # PART 3: COMPANY ROLES HAVE AUTHORIZED MONITORING BUT CANNOT APPROVE DEPLOYMENT
    # -------------------------------------------------------------------------
    def test_company_access_monitoring_overview(self):
        resp = self.client.get("/api/v1/company/monitoring/overview", headers={"Authorization": f"Bearer {self.company_token}"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("app_version"), "2.1.0-ENTERPRISE")
        self.assertTrue(data.get("admin_approval_required"))

    def test_company_access_monitoring_diagnostics(self):
        resp = self.client.get("/api/v1/company/monitoring/diagnostics", headers={"Authorization": f"Bearer {self.company_token}"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("diagnostics", data)

    def test_company_trigger_playwright_automation(self):
        resp = self.client.post("/api/v1/company/monitoring/playwright/trigger", headers={"Authorization": f"Bearer {self.company_token}"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("results", data)

    def test_company_deployment_approval_strictly_forbidden(self):
        resp = self.client.post(
            "/api/v1/company/monitoring/deployment/approve",
            headers={"Authorization": f"Bearer {self.company_token}"},
            json={"note": "Company attempt"},
        )
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertFalse(data.get("success", True))
        self.assertIn("Forbidden", data.get("error", ""))


if __name__ == "__main__":
    unittest.main()
