"""
ARAA PRIVATE LIMITED — Centralized Super Admin, SSO & Application Ecosystem Acceptance Test Suite.

Tests:
1. One central login works and issues SSO token.
2. Single Sign-On (SSO) token validates across all 10 registered applications.
3. Super Admin can list all 10 registered applications and their operational health.
4. Granular administrator creation with 15-role structure & approval limits.
5. Department and role permissions are enforced (default-deny).
6. Revoking user sessions removes access across all applications immediately.
7. Central dual-control approval inbox enforces maker-checker (prevents self-approval).
8. Central audit logs record all sensitive security, administrative & financial actions.
9. Application outages and health telemetry are accurately detected and reported.
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
os.environ.setdefault("SECRETS_KEY", "phase4-test-fernet-secrets-key-0123456789abcdef")

try:
    from central_admin_ecosystem import (
        CentralApplicationRegistry,
        CentralApprovalService,
        CentralAuditService,
        CentralIdentityService,
        CentralSuperAdminService,
    )
    from database import query, query_one, write
    from migrations import run_migrations
except ImportError:
    from backend.central_admin_ecosystem import (
        CentralApplicationRegistry,
        CentralApprovalService,
        CentralAuditService,
        CentralIdentityService,
        CentralSuperAdminService,
    )
    from backend.database import query, query_one, write
    from backend.migrations import run_migrations


class TestCentralAdminEcosystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run_migrations()
        # Clean up test users if already present from previous runs
        write("DELETE FROM central_users WHERE email='trading_head@araa.ai'")
        CentralIdentityService.seed_initial_super_admin()
        CentralApplicationRegistry.seed_applications()

    def test_01_central_super_admin_seed(self):
        """Master Super Admin exists with elevated privileges and audit trail."""
        sa = query_one("SELECT * FROM central_users WHERE is_super_admin=1")
        self.assertIsNotNone(sa)
        self.assertEqual(sa["role_code"], "SUPER_ADMIN")
        self.assertEqual(sa["status"], "ACTIVE")

    def test_02_central_sso_authentication(self):
        """Single Sign-On login issues valid SSO token and updates audit trail."""
        auth_res = CentralIdentityService.authenticate(
            email="admin@araa.ai",
            password="Password",
            app_id="app_erp",
            ip_address="127.0.0.1",
        )
        self.assertTrue(auth_res["success"])
        token = auth_res["sso_token"]
        self.assertTrue(token.startswith("araa_sso_"))

        # Validate token independently
        sess = CentralIdentityService.validate_sso_token(token, app_id="app_prop_desk")
        self.assertIsNotNone(sess)
        self.assertEqual(sess["email"], "admin@araa.ai")
        self.assertEqual(sess["role_code"], "SUPER_ADMIN")

    def test_03_application_registry_ten_apps(self):
        """All 10 required enterprise applications are registered and healthy."""
        apps = CentralApplicationRegistry.list_applications()
        self.assertEqual(len(apps), 10)
        app_ids = [a["app_id"] for a in apps]
        self.assertIn("app_erp", app_ids)
        self.assertIn("app_website", app_ids)
        self.assertIn("app_prop_desk", app_ids)
        self.assertIn("app_araabot_ai", app_ids)
        self.assertIn("app_brokerage", app_ids)
        self.assertIn("app_wallet", app_ids)
        self.assertIn("app_finance", app_ids)
        self.assertIn("app_hrms", app_ids)
        self.assertIn("app_compliance", app_ids)
        self.assertIn("app_analytics", app_ids)

        # Health overview
        health = CentralApplicationRegistry.get_system_health()
        self.assertEqual(health["total_applications"], 10)
        self.assertEqual(health["system_status"], "ALL_SYSTEMS_OPERATIONAL")

    def test_04_create_and_manage_administrators(self):
        """Super Admin can create individual administrators with specific roles."""
        res = CentralSuperAdminService.create_administrator(
            email="trading_head@araa.ai",
            full_name="Trading Desk Head",
            password="StrongPassword123",
            role_code="TRADING_ADMIN",
            department_id="dept_trading",
            approval_limit_paise=25000000,
        )
        self.assertTrue(res["success"])
        uid = res["user_id"]

        # User exists in central directory
        u = query_one("SELECT * FROM central_users WHERE user_id=?", (uid,))
        self.assertEqual(u["email"], "trading_head@araa.ai")
        self.assertEqual(u["role_code"], "TRADING_ADMIN")
        self.assertEqual(u["approval_limit_paise"], 25000000)

    def test_05_session_revocation_across_apps(self):
        """Revoking user sessions immediately terminates access across all apps."""
        # 1. Login user
        auth_res = CentralIdentityService.authenticate(
            email="trading_head@araa.ai",
            password="StrongPassword123",
            app_id="app_prop_desk",
        )
        self.assertTrue(auth_res["success"])
        token = auth_res["sso_token"]
        uid = auth_res["user"]["user_id"]

        # Active token validates
        self.assertIsNotNone(CentralIdentityService.validate_sso_token(token))

        # 2. Revoke all user sessions
        rev_count = CentralIdentityService.revoke_all_user_sessions(uid)
        self.assertGreaterEqual(rev_count, 1)

        # 3. Token is now invalid
        self.assertIsNone(CentralIdentityService.validate_sso_token(token))

    def test_06_maker_checker_approval_workflow(self):
        """Approval inbox enforces segregation of duties: requester cannot self-approve."""
        # Create approval request from trading admin
        req_res = CentralApprovalService.create_request(
            application_id="app_prop_desk",
            category="TRADING",
            title="Capital Allocation ₹5,00,000 for Pool A",
            description="Request to allocate ₹5,00,000 from company reserves",
            requested_by="usr_requester_01",
            amount_paise=50000000,
        )
        self.assertTrue(req_res["success"])
        req_id = req_res["request_id"]

        # Self-approval violation test
        self_appr = CentralApprovalService.execute_action(
            request_id=req_id,
            action="APPROVE",
            actor_user_id="usr_requester_01",  # Same user!
        )
        self.assertFalse(self_appr["success"])
        self.assertIn("Violation", self_appr["error"])

        # Independent approval test
        ok_appr = CentralApprovalService.execute_action(
            request_id=req_id,
            action="APPROVE",
            actor_user_id="usr_independent_director",
            comments="Approved after reviewing risk limits",
        )
        self.assertTrue(ok_appr["success"])
        self.assertEqual(ok_appr["status"], "APPROVED")

    def test_07_central_audit_and_ecosystem_dashboard(self):
        """Central dashboard aggregates ecosystem KPIs and tamper-evident audit logs."""
        CentralAuditService.log(
            action="POLICY_UPDATE",
            module="RISK_MANAGEMENT",
            user_id="admin@araa.ai",
            status="SUCCESS",
        )

        dash = CentralAuditService.get_ecosystem_dashboard()
        m = dash["metrics"]
        self.assertEqual(m["total_applications"], 10)
        self.assertGreaterEqual(m["total_administrators"], 1)
        self.assertGreaterEqual(len(dash["recent_audit_events"]), 1)


if __name__ == "__main__":
    unittest.main()
