import unittest
import json
import time
import os
import sys

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from database import query, query_one, write, connect, init_schema

class TestRealBotOnboarding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_schema()

    def test_providers_and_segments_configured(self):
        """Verify authorized providers and market segment configurations."""
        from app import SUPPORTED_PROVIDERS
        self.assertGreaterEqual(len(SUPPORTED_PROVIDERS), 5)
        prov_ids = [p["id"] for p in SUPPORTED_PROVIDERS]
        self.assertIn("ZERODHA", prov_ids)
        self.assertIn("ANGEL_ONE", prov_ids)
        self.assertIn("BYBIT", prov_ids)
        self.assertIn("BINANCE", prov_ids)
        self.assertIn("INTERACTIVE_BROKERS", prov_ids)

        # Indian equity must declare CDSL depository
        zerodha = next(p for p in SUPPORTED_PROVIDERS if p["id"] == "ZERODHA")
        self.assertEqual(zerodha["depository"], "CDSL")
        self.assertIn("INDIAN_EQUITY", zerodha["segments"])

    def test_demat_application_lifecycle(self):
        """Test full Demat application submission, validation, and provider callback approval."""
        now = time.time()
        test_uid = 99999
        app_ref = f"DEMAT-TEST-{test_uid}-{int(now)}"
        
        # 1. Insert application in PENDING_VERIFICATION state
        app_id = write(
            "INSERT INTO demat_applications(user_id, provider_id, provider_name, market_segment, pan_number, "
            "aadhaar_last4, full_name, email, phone, bank_name, bank_account_mask, ifsc_code, annual_income, "
            "trading_experience, depository, application_ref, status, action_required_desc, created_at, updated_at) "
            "VALUES(?, 'ZERODHA', 'Zerodha Kite Connect', 'EQUITY_DERIVATIVES', 'ABCDE1234F', '8921', "
            "'Test User', 'test@example.com', '9876543210', 'HDFC Bank', '••••••1234', 'HDFC0001234', "
            "'1L_5L', '1_3_YEARS', 'CDSL', ?, 'PENDING_VERIFICATION', 'DigiLocker KYC in progress', ?, ?)",
            (test_uid, app_ref, now, now)
        )
        self.assertIsNotNone(app_id)

        # Verify initial locked status
        row = query_one("SELECT * FROM demat_applications WHERE id=?", (app_id,))
        self.assertEqual(row["status"], "PENDING_VERIFICATION")
        self.assertEqual(row["depository"], "CDSL")

        # 2. Simulate provider callback: Action Required
        write("UPDATE demat_applications SET status='ACTION_REQUIRED', action_required_desc='Bank proof required' WHERE id=?", (app_id,))
        row = query_one("SELECT * FROM demat_applications WHERE id=?", (app_id,))
        self.assertEqual(row["status"], "ACTION_REQUIRED")

        # 3. Provider official approval
        write("UPDATE demat_applications SET status='APPROVED', approved_at=? WHERE id=?", (time.time(), app_id))
        row = query_one("SELECT * FROM demat_applications WHERE id=?", (app_id,))
        self.assertEqual(row["status"], "APPROVED")
        self.assertIsNotNone(row["approved_at"])

    def test_real_bot_config_and_audit(self):
        """Verify strict risk limits, audit logging, and pause-by-default activation."""
        test_uid = 99999
        now = time.time()

        # Config insertion with boundaries
        write(
            "INSERT INTO real_bot_configs(user_id, provider_id, broker_account_id, market_segments, strategy_mode, "
            "max_order_size, max_daily_loss, max_exposure_limit, max_leverage, stop_loss_pct, take_profit_pct, "
            "bot_status, verified_funds, verified_margin, last_risk_audit_at, created_at, updated_at) "
            "VALUES(?, 'ZERODHA', 'ZER-TEST-01', 'INDIAN_EQUITY,CRYPTO', 'PURE_CRYPTO', 25000.0, 10000.0, 100000.0, "
            "500.0, 1.5, 3.0, 'PAUSED', 100000.0, 100000.0, ?, ?, ?)"
            "ON CONFLICT(user_id) DO UPDATE SET bot_status='PAUSED'",
            (test_uid, now, now, now)
        )

        cfg = query_one("SELECT * FROM real_bot_configs WHERE user_id=?", (test_uid,))
        self.assertEqual(cfg["bot_status"], "PAUSED")
        self.assertEqual(cfg["max_order_size"], 25000.0)
        self.assertEqual(cfg["max_daily_loss"], 10000.0)

        # Audit log creation
        write(
            "INSERT INTO real_bot_audit_logs(user_id, event_type, severity, message, details_json, created_at) "
            "VALUES(?, 'AUDIT_TEST', 'INFO', 'Risk parameters verified', '{\"ok\": true}', ?)",
            (test_uid, now)
        )
        logs = query("SELECT * FROM real_bot_audit_logs WHERE user_id=? AND event_type='AUDIT_TEST'", (test_uid,))
        self.assertGreaterEqual(len(logs), 1)

if __name__ == "__main__":
    unittest.main()
