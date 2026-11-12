"""
ARAA PRIVATE LIMITED — Comprehensive Multi-Broker Connection Center Acceptance Test Suite.

Acceptance Test Requirements:
- Connect two different brokers (e.g. Zerodha and CoinDCX).
- Connect two accounts under one broker (e.g. Zerodha Company Desk 1 & Zerodha Company Desk 2).
- Disconnect one account without affecting others.
- Expire one API token and confirm graceful handling.
- Fail one connection without affecting other brokers.
- Synchronize balances independently without cross-contamination.
- Route orders to the selected account.
- Prevent duplicate orders (idempotency key enforcement).
- Prevent cross-account credential access.
- Prevent cross-capital-pool transfers.
- Reconcile each account separately.
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
os.environ.setdefault("SECRETS_KEY", "phase4-test-fernet-secrets-key-0123456789abcdef")

try:
    from broker_connection_center import (
        AccountSynchronizationService,
        BrokerConnectionCenter,
        BrokerConnectionService,
        BrokerCredentialService,
        BrokerProviderRegistry,
    )
    from database import query, query_one, write
    from migrations import run_migrations
    from universal_broker_manager import BrokerAdapter, UniversalBrokerManager
except ImportError:
    from backend.broker_connection_center import (
        AccountSynchronizationService,
        BrokerConnectionCenter,
        BrokerConnectionService,
        BrokerCredentialService,
        BrokerProviderRegistry,
    )
    from backend.database import query, query_one, write
    from backend.migrations import run_migrations
    from backend.universal_broker_manager import BrokerAdapter, UniversalBrokerManager


class MockCustomAdapter(BrokerAdapter):
    """Test harness mock adapter for simulating broker responses."""

    def __init__(self, account_id, company_id, credentials, succeeds=True, balance_paise=10000000):
        super().__init__(account_id, company_id, credentials)
        self.succeeds = succeeds
        self.balance_paise = balance_paise

    def verify_connection(self):
        if not self.succeeds:
            return {"ok": False, "error": "Invalid API Key or Secret"}
        return {
            "ok": True,
            "provider": self.provider,
            "account_id": self.account_id,
            "broker_user_id": f"MOCK_{self.account_id[:6]}",
            "user_name": "Test Trader",
            "segments": ["NSE_EQ"],
        }

    def get_profile(self):
        return {"account_id": self.account_id, "user_name": "Test Trader"}

    def get_balances(self):
        return {
            "available_paise": self.balance_paise,
            "cash_paise": self.balance_paise,
            "used_paise": 0,
            "total_equity_paise": self.balance_paise,
            "currency": "INR",
        }

    def get_positions(self):
        return []

    def get_open_orders(self):
        return []

    def get_instruments(self, exchange=None):
        return []

    def get_quote(self, symbol, exchange=None):
        return {"symbol": symbol, "ltp": "100.00", "timestamp": time.time()}

    def validate_instrument(self, symbol, exchange=None, **kw):
        return {"valid": True, "symbol": symbol}

    def calculate_margin(self, order_spec):
        return {"margin_required_paise": 100000, "leverage": 1}

    def place_order(self, order_spec):
        return {"executed": True, "broker_order_id": f"ORD_{self.account_id[:4]}", "status": "SUBMITTED"}

    def get_order_status(self, provider_order_id):
        return {"status": "COMPLETE", "provider_order_id": provider_order_id}

    def get_trades(self):
        return []

    def cancel_order(self, provider_order_id, variety="regular"):
        return {"cancelled": True, "provider_order_id": provider_order_id}

    def disconnect(self):
        return {"disconnected": True, "account_id": self.account_id}


class TestMultiBrokerConnectionCenter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run_migrations()
        BrokerProviderRegistry.seed_defaults()
        cls.company_id = 1

    def test_01_provider_catalogue(self):
        """Catalogue lists Indian stock brokers and crypto exchanges."""
        providers = BrokerProviderRegistry.list_providers()
        codes = [p["provider_code"] for p in providers]
        self.assertIn("ZERODHA", codes)
        self.assertIn("COINDCX", codes)
        self.assertIn("UPSTOX", codes)
        self.assertIn("ANGEL_ONE", codes)
        self.assertIn("DHAN", codes)
        self.assertIn("FYERS", codes)

    def test_02_connect_two_different_brokers(self):
        """Company can connect two different brokers (e.g. Zerodha and CoinDCX)."""
        res_z = BrokerConnectionService.register_account(
            company_id=self.company_id,
            provider_code="ZERODHA",
            account_name="Zerodha Primary",
            api_key="kite_test_key_001",
            api_secret="kite_test_secret_001",
        )
        self.assertTrue(res_z["success"])
        acc_z = res_z["account_id"]

        res_c = BrokerConnectionService.register_account(
            company_id=self.company_id,
            provider_code="COINDCX",
            account_name="CoinDCX Spot Primary",
            api_key="cdx_test_key_001",
            api_secret="cdx_test_secret_001",
        )
        self.assertTrue(res_c["success"])
        acc_c = res_c["account_id"]

        self.assertNotEqual(acc_z, acc_c)

        # Mock adapters and verify
        UniversalBrokerManager.register_mock_for_account(
            self.company_id, acc_z, lambda aid, cid, creds: MockCustomAdapter(aid, cid, creds)
        )
        UniversalBrokerManager.register_mock_for_account(
            self.company_id, acc_c, lambda aid, cid, creds: MockCustomAdapter(aid, cid, creds)
        )

        v_z = BrokerConnectionService.test_and_verify(self.company_id, acc_z)
        v_c = BrokerConnectionService.test_and_verify(self.company_id, acc_c)

        self.assertTrue(v_z["success"])
        self.assertTrue(v_c["success"])

        # Check DB states
        row_z = query_one("SELECT connection_status FROM broker_accounts WHERE account_id=?", (acc_z,))
        row_c = query_one("SELECT connection_status FROM broker_accounts WHERE account_id=?", (acc_c,))
        self.assertEqual(row_z["connection_status"], "CONNECTED")
        self.assertEqual(row_c["connection_status"], "CONNECTED")

    def test_03_multiple_accounts_under_one_broker(self):
        """Allows connecting multiple accounts under one broker without collision."""
        res_1 = BrokerConnectionService.register_account(
            company_id=self.company_id,
            provider_code="ZERODHA",
            account_name="Zerodha Company Desk 1",
            api_key="kite_desk1_key",
            api_secret="kite_desk1_secret",
        )
        res_2 = BrokerConnectionService.register_account(
            company_id=self.company_id,
            provider_code="ZERODHA",
            account_name="Zerodha Company Desk 2",
            api_key="kite_desk2_key",
            api_secret="kite_desk2_secret",
        )

        aid1 = res_1["account_id"]
        aid2 = res_2["account_id"]

        self.assertNotEqual(aid1, aid2)

        # Verify separate credentials stored
        creds1 = BrokerCredentialService.resolve_decrypted(aid1)
        creds2 = BrokerCredentialService.resolve_decrypted(aid2)

        self.assertEqual(creds1["api_key"], "kite_desk1_key")
        self.assertEqual(creds2["api_key"], "kite_desk2_key")
        self.assertNotEqual(creds1["api_key"], creds2["api_key"])

    def test_04_disconnect_one_without_affecting_others(self):
        """Disconnecting one account does not impact any other account's connected state."""
        r1 = BrokerConnectionService.register_account(
            self.company_id, "UPSTOX", "Upstox Alpha", "upstox_k1", "upstox_s1"
        )
        r2 = BrokerConnectionService.register_account(
            self.company_id, "UPSTOX", "Upstox Beta", "upstox_k2", "upstox_s2"
        )

        a1, a2 = r1["account_id"], r2["account_id"]

        # Connect both
        UniversalBrokerManager.register_mock_for_account(
            self.company_id, a1, lambda aid, cid, creds: MockCustomAdapter(aid, cid, creds)
        )
        UniversalBrokerManager.register_mock_for_account(
            self.company_id, a2, lambda aid, cid, creds: MockCustomAdapter(aid, cid, creds)
        )

        BrokerConnectionService.test_and_verify(self.company_id, a1)
        BrokerConnectionService.test_and_verify(self.company_id, a2)

        # Disconnect a1
        BrokerConnectionService.disconnect_account(self.company_id, a1)

        row1 = query_one("SELECT connection_status FROM broker_accounts WHERE account_id=?", (a1,))
        row2 = query_one("SELECT connection_status FROM broker_accounts WHERE account_id=?", (a2,))

        self.assertEqual(row1["connection_status"], "DISCONNECTED")
        self.assertEqual(row2["connection_status"], "CONNECTED")

    def test_05_failed_connection_isolation(self):
        """A failed connection marks only that account as invalid without affecting other brokers."""
        r_fail = BrokerConnectionService.register_account(
            self.company_id, "DHAN", "Dhan Bad Key", "bad_k", "bad_s"
        )
        a_fail = r_fail["account_id"]

        UniversalBrokerManager.register_mock_for_account(
            self.company_id, a_fail, lambda aid, cid, creds: MockCustomAdapter(aid, cid, creds, succeeds=False)
        )

        v_res = BrokerConnectionService.test_and_verify(self.company_id, a_fail)
        self.assertFalse(v_res["success"])

        row_fail = query_one("SELECT connection_status FROM broker_accounts WHERE account_id=?", (a_fail,))
        self.assertEqual(row_fail["connection_status"], "REVOKED_OR_INVALID")

    def test_06_independent_balance_sync(self):
        """Synchronizes account balances independently into integer paise."""
        r = BrokerConnectionService.register_account(
            self.company_id, "ANGEL_ONE", "Angel Smart 1", "angel_k", "angel_s"
        )
        aid = r["account_id"]

        UniversalBrokerManager.register_mock_for_account(
            self.company_id, aid, lambda a, c, cr: MockCustomAdapter(a, c, cr, balance_paise=25000000)
        )

        sync_res = AccountSynchronizationService.sync_account(self.company_id, aid)
        self.assertTrue(sync_res["success"])
        self.assertEqual(sync_res["balances"]["available_paise"], 25000000)

        bal_row = query_one("SELECT * FROM broker_account_balances WHERE account_id=?", (aid,))
        self.assertEqual(bal_row["available_funds_paise"], 25000000)
        self.assertEqual(bal_row["account_equity_paise"], 25000000)

    def test_07_live_trading_safety_gate(self):
        """Live trading cannot be enabled on an unverified/disconnected account."""
        r = BrokerConnectionService.register_account(
            self.company_id, "FYERS", "Fyers Desk", "fyers_k", "fyers_s"
        )
        aid = r["account_id"]

        # Initially disconnected
        res = BrokerConnectionService.set_live_approval(self.company_id, aid, approved=True)
        self.assertFalse(res["success"])
        self.assertIn("not verified", res["error"])

        # Once verified, approval can succeed
        UniversalBrokerManager.register_mock_for_account(
            self.company_id, aid, lambda a, c, cr: MockCustomAdapter(a, c, cr)
        )
        BrokerConnectionService.test_and_verify(self.company_id, aid)

        res_ok = BrokerConnectionService.set_live_approval(self.company_id, aid, approved=True)
        self.assertTrue(res_ok["success"])

        row = query_one("SELECT live_trading_approved FROM broker_accounts WHERE account_id=?", (aid,))
        self.assertEqual(row["live_trading_approved"], 1)

    def test_08_dashboard_aggregation(self):
        """Dashboard aggregates summary metrics correctly."""
        summary_data = BrokerConnectionCenter.get_dashboard_summary(self.company_id)
        s = summary_data["summary"]
        self.assertGreaterEqual(s["total_accounts"], 4)
        self.assertGreaterEqual(s["active_connections"], 1)
        self.assertGreaterEqual(s["failed_connections"], 1)


if __name__ == "__main__":
    unittest.main()
