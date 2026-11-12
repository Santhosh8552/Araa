"""
ARAA Company Trading Platform — Phase 2 Tests:
- Versioned Database Migrations & Seeding
- Fail-Closed Company Auth & Brute-Force Lockout
- 7-Role RBAC Enforcement & Permission Denial Audit Logging
- RFC-6238 TOTP MFA Enrollment, Verification & Session Revocation
- Dual-Control Maker-Checker Approval Workflow
- AUTH_STRICT=1 Legacy V1 Fallback Prevention
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

os.environ.setdefault("SECRETS_KEY", "phase2-test-fernet-secrets-key-0123456789abcdef")

from app import api
from company_auth import CompanyAuthService, totp_code
from database import init_schema, query, query_one, write
from migrations import list_applied_migrations


class TestCompanyPhase2RBAC(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_schema()
        cls.company = CompanyAuthService.get_default_company()
        cls.cid = cls.company["id"]
        cls.test_emails = [
            "director_p2@araa.ai",
            "auditor_p2@araa.ai",
            "trader_p2@araa.ai",
            "risk_p2@araa.ai",
            "emp_new_p2@araa.ai",
        ]
        cls._cleanup()

        # Bootstrap employees across distinct roles
        CompanyAuthService.create_employee(cls.cid, "director_p2@araa.ai", "Araa Director", "DirPass!2026", "COMPANY_DIRECTOR")
        CompanyAuthService.create_employee(cls.cid, "auditor_p2@araa.ai", "Compliance Auditor", "AudPass!2026", "AUDITOR")
        CompanyAuthService.create_employee(cls.cid, "trader_p2@araa.ai", "Trading Operator", "TrdPass!2026", "TRADING_ADMIN")
        CompanyAuthService.create_employee(cls.cid, "risk_p2@araa.ai", "Risk Officer", "RskPass!2026", "RISK_MANAGER")

    @classmethod
    def _cleanup(cls):
        for email in cls.test_emails:
            row = query_one("SELECT id FROM company_users WHERE email=?", (email,))
            if row:
                uid = row["id"]
                write("DELETE FROM company_sessions WHERE company_user_id=?", (uid,))
                write("DELETE FROM trading_approvals WHERE requested_by=? OR approved_by=?", (uid, uid))
                write("DELETE FROM company_audit_logs WHERE actor_user_id=?", (uid,))
                write("DELETE FROM company_users WHERE id=?", (uid,))

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    def test_1_versioned_migrations_and_7_roles_seeded(self):
        migs = list_applied_migrations()
        versions = {m["version"] for m in migs}
        self.assertIn("001", versions)

        roles = CompanyAuthService.list_roles()
        role_codes = {r["role_code"] for r in roles}
        expected = {
            "COMPANY_DIRECTOR", "SUPER_ADMIN", "FINANCE_ADMIN",
            "TRADING_ADMIN", "RISK_MANAGER", "TECHNICAL_ADMIN", "AUDITOR",
        }
        self.assertTrue(expected.issubset(role_codes))
        self.assertEqual(self.company["company_code"], "ARAA-PROP-01")
        self.assertEqual(self.company["proprietary_only"], 1)

    def test_2_fail_closed_unauthenticated_company_routes(self):
        client = api.test_client()
        for method, path in (
            ("GET", "/api/v1/company/profile"),
            ("GET", "/api/v1/company/employees"),
            ("GET", "/api/v1/company/audit-logs"),
            ("GET", "/api/v1/company/migrations"),
        ):
            res = client.open(path, method=method)
            self.assertEqual(res.status_code, 401, f"{path} did not fail closed with 401")

    def test_3_rbac_permission_enforcement_and_denial_audit(self):
        client = api.test_client()
        aud_login = client.post(
            "/api/v1/company/auth/login",
            json={"email": "auditor_p2@araa.ai", "password": "AudPass!2026"},
        )
        self.assertEqual(aud_login.status_code, 200)
        aud_tok = aud_login.get_json()["token"]

        # Auditor CAN read profile and audit logs
        prof = client.get("/api/v1/company/profile", headers={"X-Company-Token": aud_tok})
        self.assertEqual(prof.status_code, 200)
        self.assertEqual(prof.get_json()["company"]["company_code"], "ARAA-PROP-01")

        # Auditor CANNOT mutate company profile or create employees
        upd = client.put(
            "/api/v1/company/profile",
            json={"legal_name": "Tampered Corp"},
            headers={"X-Company-Token": aud_tok},
        )
        self.assertEqual(upd.status_code, 403)

        emp_try = client.post(
            "/api/v1/company/employees",
            json={"email": "emp_new_p2@araa.ai", "full_name": "Rogue", "password": "Password123!", "role_code": "SUPER_ADMIN"},
            headers={"X-Company-Token": aud_tok},
        )
        self.assertEqual(emp_try.status_code, 403)

        # Verify denial was recorded in immutable company_audit_logs
        denied = query_one(
            "SELECT * FROM company_audit_logs WHERE actor_email='auditor_p2@araa.ai' AND action='PERMISSION_DENIED' ORDER BY id DESC LIMIT 1"
        )
        self.assertIsNotNone(denied)

        # Director CAN create employee
        dir_login = client.post(
            "/api/v1/company/auth/login",
            json={"email": "director_p2@araa.ai", "password": "DirPass!2026"},
        )
        dir_tok = dir_login.get_json()["token"]
        created = client.post(
            "/api/v1/company/employees",
            json={"email": "emp_new_p2@araa.ai", "full_name": "New Analyst", "password": "Analyst!2026", "role_code": "FINANCE_ADMIN"},
            headers={"X-Company-Token": dir_tok},
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.get_json()["employee"]["role_code"], "FINANCE_ADMIN")

    def test_4_totp_mfa_enrollment_encrypted_secret_and_session_revocation(self):
        client = api.test_client()
        login_res = client.post(
            "/api/v1/company/auth/login",
            json={"email": "trader_p2@araa.ai", "password": "TrdPass!2026"},
        )
        self.assertEqual(login_res.status_code, 200)
        tok1 = login_res.get_json()["token"]

        # Enroll MFA
        enr = client.post("/api/v1/company/auth/mfa/enroll", headers={"X-Company-Token": tok1})
        self.assertEqual(enr.status_code, 200)
        secret = enr.get_json()["secret"]
        self.assertIn("otpauth://totp/", enr.get_json()["provisioning_uri"])

        # Secret must be encrypted at rest in DB
        raw_row = query_one("SELECT mfa_secret_enc FROM company_users WHERE email='trader_p2@araa.ai'")
        self.assertTrue(raw_row["mfa_secret_enc"].startswith("enc1:"))

        # Confirm MFA using live TOTP code
        otp = totp_code(secret)
        ver = client.post("/api/v1/company/auth/mfa/verify", json={"totp": otp}, headers={"X-Company-Token": tok1})
        self.assertEqual(ver.status_code, 200)
        self.assertTrue(ver.get_json()["mfa_enabled"])

        # Subsequent login without TOTP must be rejected with mfa_required=True
        no_otp_login = client.post(
            "/api/v1/company/auth/login",
            json={"email": "trader_p2@araa.ai", "password": "TrdPass!2026"},
        )
        self.assertEqual(no_otp_login.status_code, 401)
        self.assertTrue(no_otp_login.get_json()["mfa_required"])

        # Login with TOTP succeeds & logout revokes token
        ok_login = client.post(
            "/api/v1/company/auth/login",
            json={"email": "trader_p2@araa.ai", "password": "TrdPass!2026", "totp": totp_code(secret)},
        )
        self.assertEqual(ok_login.status_code, 200)
        tok2 = ok_login.get_json()["token"]
        self.assertTrue(ok_login.get_json()["mfa_verified"])

        # Revoke tok2 via logout -> must fail 401 afterward
        client.post("/api/v1/company/auth/logout", headers={"X-Company-Token": tok2})
        after_logout = client.get("/api/v1/company/auth/me", headers={"X-Company-Token": tok2})
        self.assertEqual(after_logout.status_code, 401)

    def test_5_dual_control_maker_checker_approval_and_lockout(self):
        client = api.test_client()
        # Request approval as Risk Manager? First use Director to request, verify self-approval is blocked
        dir_tok = client.post(
            "/api/v1/company/auth/login",
            json={"email": "director_p2@araa.ai", "password": "DirPass!2026"},
        ).get_json()["token"]
        rsk_tok = client.post(
            "/api/v1/company/auth/login",
            json={"email": "risk_p2@araa.ai", "password": "RskPass!2026"},
        ).get_json()["token"]

        req = client.post(
            "/api/v1/company/approvals",
            json={"approval_type": "LIVE_ACTIVATION", "target_ref": "COINDCX_SPOT", "payload": {"max_inr": 50000}},
            headers={"X-Company-Token": dir_tok},
        )
        self.assertEqual(req.status_code, 200)
        apr_id = req.get_json()["approval"]["approval_id"]

        # Self-approval attempt by requester MUST fail
        self_apr = client.post(
            f"/api/v1/company/approvals/{apr_id}/decide",
            json={"decision": "APPROVED", "note": "Self-try"},
            headers={"X-Company-Token": dir_tok},
        )
        self.assertEqual(self_apr.status_code, 400)
        self.assertIn("Dual-control", self_apr.get_json()["error"])

        # Distinct Risk Manager approves cleanly
        ok_apr = client.post(
            f"/api/v1/company/approvals/{apr_id}/decide",
            json={"decision": "APPROVED", "note": "Risk verified"},
            headers={"X-Company-Token": rsk_tok},
        )
        self.assertEqual(ok_apr.status_code, 200)
        self.assertEqual(ok_apr.get_json()["approval"]["status"], "APPROVED")

        # 5 wrong passwords lock auditor account
        for _ in range(5):
            r = client.post(
                "/api/v1/company/auth/login",
                json={"email": "auditor_p2@araa.ai", "password": "WrongPassword999"},
            )
        locked = client.post(
            "/api/v1/company/auth/login",
            json={"email": "auditor_p2@araa.ai", "password": "AudPass!2026"},
        )
        self.assertEqual(locked.status_code, 423)

    def test_6_auth_strict_blocks_legacy_user_fallback(self):
        client = api.test_client()
        prev = os.environ.get("AUTH_STRICT")
        os.environ["AUTH_STRICT"] = "1"
        try:
            res = client.get("/api/v1/bots")
            self.assertEqual(res.status_code, 401)
        finally:
            if prev is None:
                os.environ.pop("AUTH_STRICT", None)
            else:
                os.environ["AUTH_STRICT"] = prev


if __name__ == "__main__":
    unittest.main()

