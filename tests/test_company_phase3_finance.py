"""
ARAA Company Trading Platform — Phase 3 Tests:
- Migration 002 & Two Strictly Isolated Capital Pools (India INR vs. Crypto Spot)
- Exact Integer Paise / Decimal Arithmetic (No Float Drift)
- Zero Cross-Pool Access or Automatic Transfers
- Accounting Capital Movements vs. Broker-Confirmed Equity Distinction
- Single-Pool Strategy Allocation Ceiling
- Company Trading Account Secret Encryption & Capability Enforcement
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
os.environ.setdefault("SECRETS_KEY", "phase3-test-fernet-secrets-key-0123456789abcdef")

from app import api
from company_auth import CompanyAuthService
from company_finance import (
    POOL_CRYPTO_SPOT,
    POOL_INDIA_INR,
    CompanyAccountManager,
    CompanyCapitalManager,
    paise_to_inr_str,
    quantize_decimal_str,
    to_paise,
)
from database import init_schema, query_one, write
from migrations import list_applied_migrations


class TestCompanyPhase3Finance(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_schema()
        cls.company = CompanyAuthService.get_default_company()
        cls.cid = cls.company["id"]
        cls.emails = ["finance_p3@araa.ai", "tech_p3@araa.ai", "auditor_p3@araa.ai"]
        cls._cleanup()

        CompanyAuthService.create_employee(cls.cid, "finance_p3@araa.ai", "Finance Officer", "FinPass!2026", "FINANCE_ADMIN")
        CompanyAuthService.create_employee(cls.cid, "tech_p3@araa.ai", "Tech Officer", "TechPass!2026", "TECHNICAL_ADMIN")
        CompanyAuthService.create_employee(cls.cid, "auditor_p3@araa.ai", "Audit Officer", "AudPass!2026", "AUDITOR")

        # Reset test company pools to 0 paise for clean accounting assertions
        write(
            "UPDATE company_capital_pools SET allocated_capital_paise=0, broker_confirmed_equity_paise=0, "
            "free_funds_paise=0, locked_funds_paise=0, fees_paise=0, taxes_expenses_paise=0, "
            "available_risk_budget_paise=0, account_id='' WHERE company_id=?",
            (cls.cid,),
        )
        write("DELETE FROM capital_allocations WHERE company_id=?", (cls.cid,))
        write("DELETE FROM company_capital_movements WHERE company_id=?", (cls.cid,))

    @classmethod
    def _cleanup(cls):
        for email in cls.emails:
            row = query_one("SELECT id FROM company_users WHERE email=?", (email,))
            if row:
                uid = row["id"]
                write("DELETE FROM company_sessions WHERE company_user_id=?", (uid,))
                write("DELETE FROM company_audit_logs WHERE actor_user_id=?", (uid,))
                write("DELETE FROM company_users WHERE id=?", (uid,))
        write("DELETE FROM broker_account_secrets WHERE account_id IN (SELECT account_id FROM company_trading_accounts WHERE company_id=?)", (cls.cid,))
        write("DELETE FROM broker_capabilities WHERE account_id IN (SELECT account_id FROM company_trading_accounts WHERE company_id=?)", (cls.cid,))
        write("DELETE FROM company_trading_accounts WHERE company_id=?", (cls.cid,))
        write("DELETE FROM capital_allocations WHERE company_id=?", (cls.cid,))
        write("DELETE FROM company_capital_movements WHERE company_id=?", (cls.cid,))
        write(
            "UPDATE company_capital_pools SET allocated_capital_paise=0, broker_confirmed_equity_paise=0, "
            "free_funds_paise=0, locked_funds_paise=0, fees_paise=0, taxes_expenses_paise=0, "
            "available_risk_budget_paise=0, account_id='' WHERE company_id=?",
            (cls.cid,),
        )

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    def _login(self, client, email, password):
        res = client.post("/api/v1/company/auth/login", json={"email": email, "password": password})
        self.assertEqual(res.status_code, 200)
        return res.get_json()["token"]

    def test_1_exact_paise_and_decimal_arithmetic(self):
        self.assertEqual(to_paise("0.10") + to_paise("0.20"), 30)
        self.assertEqual(paise_to_inr_str(30), "0.30")
        self.assertEqual(to_paise("150000.75"), 15000075)
        self.assertEqual(paise_to_inr_str(15000075), "150000.75")
        self.assertEqual(quantize_decimal_str("0.123456789", 8), "0.12345679")

    def test_2_migration_002_and_strict_pool_isolation(self):
        migs = {m["version"] for m in list_applied_migrations()}
        self.assertIn("002", migs)

        pools = CompanyCapitalManager.list_pools(self.cid)
        pool_ids = {p["pool_id"] for p in pools}
        self.assertTrue({POOL_INDIA_INR, POOL_CRYPTO_SPOT}.issubset(pool_ids))

        # India strategy / Zerodha cannot touch Crypto pool & vice versa
        with self.assertRaises(PermissionError):
            CompanyCapitalManager.assert_pool_isolation(POOL_INDIA_INR, market_scope="CRYPTO")
        with self.assertRaises(PermissionError):
            CompanyCapitalManager.assert_pool_isolation(POOL_CRYPTO_SPOT, provider="ZERODHA")

    def test_3_capital_movements_and_no_cross_pool_transfer(self):
        client = api.test_client()
        fin_tok = self._login(client, "finance_p3@araa.ai", "FinPass!2026")
        aud_tok = self._login(client, "auditor_p3@araa.ai", "AudPass!2026")

        # Auditor cannot add capital
        forbidden = client.post(
            "/api/v1/company/capital-pools",
            json={"pool_id": POOL_INDIA_INR, "movement_type": "CAPITAL_ADDITION", "amount_inr": "50000.00"},
            headers={"X-Company-Token": aud_tok},
        )
        self.assertEqual(forbidden.status_code, 403)

        # Finance admin adds 1,00,000.50 INR to India pool & 40,000.00 INR to Crypto pool
        add_in = client.post(
            "/api/v1/company/capital-pools",
            json={"pool_id": POOL_INDIA_INR, "movement_type": "CAPITAL_ADDITION", "amount_inr": "100000.50", "reference_no": "BANK-NEFT-001"},
            headers={"X-Company-Token": fin_tok},
        )
        self.assertEqual(add_in.status_code, 200)
        self.assertEqual(add_in.get_json()["source_classification"], "ACCOUNTING_RECORD")
        # Broker confirmed equity MUST remain 0 until real broker sync!
        self.assertEqual(add_in.get_json()["pool"]["broker_confirmed_equity_paise"], 0)
        self.assertEqual(add_in.get_json()["pool"]["allocated_capital_inr"], "100000.50")

        add_cr = client.post(
            "/api/v1/company/capital-pools",
            json={"pool_id": POOL_CRYPTO_SPOT, "movement_type": "CAPITAL_ADDITION", "amount_inr": "40000.00", "reference_no": "BANK-IMPS-002"},
            headers={"X-Company-Token": fin_tok},
        )
        self.assertEqual(add_cr.status_code, 200)

        # Cross-pool transfer MUST fail
        xfer = client.post(
            "/api/v1/company/capital-pools",
            json={"pool_id": POOL_INDIA_INR, "target_pool_id": POOL_CRYPTO_SPOT, "movement_type": "CAPITAL_ADDITION", "amount_inr": "5000"},
            headers={"X-Company-Token": fin_tok},
        )
        self.assertEqual(xfer.status_code, 400)
        self.assertIn("CROSS_POOL_TRANSFER_FORBIDDEN", xfer.get_json()["error"])

        # Strategy allocation inside India pool works within 100000.50, CANNOT borrow from Crypto pool's 40000
        ok_alc = client.post(
            "/api/v1/company/capital-pools/allocate",
            json={"pool_id": POOL_INDIA_INR, "strategy_code": "NSE_MOMENTUM_V1", "amount_inr": "60000.00"},
            headers={"X-Company-Token": fin_tok},
        )
        self.assertEqual(ok_alc.status_code, 200)

        over_alc = client.post(
            "/api/v1/company/capital-pools/allocate",
            json={"pool_id": POOL_INDIA_INR, "strategy_code": "NSE_BREAKOUT_V1", "amount_inr": "50000.00"},
            headers={"X-Company-Token": fin_tok},
        )
        self.assertEqual(over_alc.status_code, 400)
        self.assertIn("exceeds POOL_INDIA_INR", over_alc.get_json()["error"])

        # Combined portfolio reporting summary is exact INR sum & marked reporting_only
        pf = client.get("/api/v1/company/portfolio", headers={"X-Company-Token": fin_tok}).get_json()["portfolio"]
        self.assertTrue(pf["reporting_only"])
        self.assertFalse(pf["cross_pool_transfers_allowed"])
        self.assertEqual(pf["total_allocated_capital_inr"], "140000.50")

        # CSV export works
        csv_res = client.get("/api/v1/company/finance/report?format=csv", headers={"X-Company-Token": fin_tok})
        self.assertEqual(csv_res.status_code, 200)
        self.assertIn("BANK-NEFT-001", csv_res.data.decode("utf-8"))

    def test_4_company_account_encrypted_secrets_and_coindcx_spot_only(self):
        client = api.test_client()
        tech_tok = self._login(client, "tech_p3@araa.ai", "TechPass!2026")

        res = client.post(
            "/api/v1/company/accounts",
            json={
                "provider": "COINDCX",
                "account_name": "ARAA CoinDCX Prop Spot #1",
                "api_key": "cdx_test_company_key_abc",
                "api_secret": "cdx_test_company_secret_xyz",
                "static_egress_ip": "13.232.10.20",
                "withdrawal_disabled": True,
            },
            headers={"X-Company-Token": tech_tok},
        )
        self.assertEqual(res.status_code, 200)
        acc = res.get_json()["account"]
        acc_id = acc["account_id"]

        # Capabilities strictly Spot-only, no futures, no leverage
        self.assertEqual(acc["capabilities"]["supports_spot"], 1)
        self.assertEqual(acc["capabilities"]["supports_futures"], 0)
        self.assertEqual(acc["capabilities"]["leverage_allowed"], 0)

        # Response never exposes raw API secrets
        self.assertNotIn("api_key", acc)
        self.assertNotIn("api_secret", acc)
        self.assertNotIn("cdx_test_company_secret_xyz", str(acc))

        # Secrets in DB are Fernet-encrypted with enc1:
        sec_row = query_one("SELECT api_key_enc, api_secret_enc FROM broker_account_secrets WHERE account_id=?", (acc_id,))
        self.assertTrue(sec_row["api_key_enc"].startswith("enc1:"))
        self.assertTrue(sec_row["api_secret_enc"].startswith("enc1:"))

        # Internal resolver decrypts cleanly
        resolved = CompanyAccountManager.resolve_decrypted_credentials(self.cid, acc_id)
        self.assertEqual(resolved["api_secret"], "cdx_test_company_secret_xyz")


if __name__ == "__main__":
    unittest.main()

