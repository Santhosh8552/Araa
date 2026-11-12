"""
ARAA Company Trading Platform — Phase 4 Tests:
- UniversalBrokerManager Account Isolation (No Global Mutable Client)
- Zerodha Kite Connect v3 OAuth URL, Checksum Exchange & Daily Session Expiry
- Static Egress IP Enforcement & Timeout -> UNKNOWN (Zero Duplicate Retry)
- Authorized Exchange/Segment Enforcement (NSE/BSE only; no NFO/MCX assumption)
- MockZerodhaAdapter Full Sync -> POOL_INDIA_INR Isolation Verification
"""

import hashlib
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
os.environ.setdefault("SECRETS_KEY", "phase4-test-fernet-secrets-key-0123456789abcdef")

from app import api
from company_auth import CompanyAuthService
from company_finance import POOL_CRYPTO_SPOT, POOL_INDIA_INR, CompanyAccountManager
from database import init_schema, query_one, write
from universal_broker_manager import UniversalBrokerManager
from zerodha_adapter import MockZerodhaAdapter, ZerodhaKiteAdapter, compute_next_kite_expiry_ts


class TestCompanyPhase4Zerodha(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_schema()
        cls.company = CompanyAuthService.get_default_company()
        cls.cid = cls.company["id"]
        cls.emails = ["tech_p4@araa.ai"]
        cls._cleanup()
        CompanyAuthService.create_employee(cls.cid, "tech_p4@araa.ai", "Tech Lead P4", "TechPass!2026", "TECHNICAL_ADMIN")

    @classmethod
    def _cleanup(cls):
        for email in cls.emails:
            row = query_one("SELECT id FROM company_users WHERE email=?", (email,))
            if row:
                uid = row["id"]
                write("DELETE FROM company_sessions WHERE company_user_id=?", (uid,))
                write("DELETE FROM company_audit_logs WHERE actor_user_id=?", (uid,))
                write("DELETE FROM company_users WHERE id=?", (uid,))
        for acc_row in query_one("SELECT account_id FROM company_trading_accounts WHERE company_id=?", (cls.cid,)) or []:
            pass
        accs = [r["account_id"] for r in (query_one("SELECT 1") and __import__("database").query("SELECT account_id FROM company_trading_accounts WHERE company_id=?", (cls.cid,)))]
        for aid in accs:
            UniversalBrokerManager.clear_mock_for_account(cls.cid, aid)
        write("DELETE FROM broker_account_secrets WHERE account_id IN (SELECT account_id FROM company_trading_accounts WHERE company_id=?)", (cls.cid,))
        write("DELETE FROM broker_capabilities WHERE account_id IN (SELECT account_id FROM company_trading_accounts WHERE company_id=?)", (cls.cid,))
        write("DELETE FROM company_trading_accounts WHERE company_id=?", (cls.cid,))
        write(
            "UPDATE company_capital_pools SET allocated_capital_paise=0, broker_confirmed_equity_paise=0, "
            "free_funds_paise=0, locked_funds_paise=0, open_positions_count=0, pending_orders_count=0, account_id='' "
            "WHERE company_id=?",
            (cls.cid,),
        )

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    def _login(self, client):
        res = client.post("/api/v1/company/auth/login", json={"email": "tech_p4@araa.ai", "password": "TechPass!2026"})
        self.assertEqual(res.status_code, 200)
        return res.get_json()["token"]

    def test_1_zerodha_oauth_url_checksum_and_session_exchange(self):
        client = api.test_client()
        tok = self._login(client)

        reg = client.post(
            "/api/v1/company/accounts",
            json={
                "provider": "ZERODHA",
                "account_name": "ARAA Zerodha Prop #1",
                "api_key": "kite_key_001",
                "api_secret": "kite_secret_001",
                "static_egress_ip": "13.200.45.10",
            },
            headers={"X-Company-Token": tok},
        )
        self.assertEqual(reg.status_code, 200)
        aid = reg.get_json()["account"]["account_id"]

        # Connect login URL check
        conn = client.get(f"/api/v1/brokers/zerodha/connect?account_id={aid}", headers={"X-Company-Token": tok})
        self.assertEqual(conn.status_code, 200)
        self.assertIn("https://kite.trade/connect/login", conn.get_json()["login_url"])
        self.assertIn("api_key=kite_key_001", conn.get_json()["login_url"])

        # Mock /session/token HTTP exchange to verify SHA-256 checksum & encrypted storage
        expected_checksum = hashlib.sha256(b"kite_key_001req_tok_999kite_secret_001").hexdigest()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "data": {
                "user_id": "ZR_ARAA_01",
                "user_name": "ARAA Prop Desk",
                "email": "desk@araa.ai",
                "access_token": "kite_access_tok_secret_value",
                "exchanges": ["NSE", "BSE"],
                "products": ["CNC", "MIS"],
                "order_types": ["MARKET", "LIMIT", "SL", "SL-M"],
            },
        }

        with patch("requests.Session.post", return_value=mock_resp) as post_spy:
            cb = client.post(
                "/api/v1/brokers/zerodha/callback",
                json={"account_id": aid, "request_token": "req_tok_999"},
                headers={"X-Company-Token": tok},
            )
            self.assertEqual(cb.status_code, 200)
            self.assertTrue(cb.get_json()["ok"])
            self.assertEqual(cb.get_json()["broker_user_id"], "ZR_ARAA_01")
            called_data = post_spy.call_args.kwargs["data"]
            self.assertEqual(called_data["checksum"], expected_checksum)

        # Verify encrypted access token at rest
        sec = query_one("SELECT access_token_enc FROM broker_account_secrets WHERE account_id=?", (aid,))
        self.assertTrue(sec["access_token_enc"].startswith("enc1:"))
        resolved = CompanyAccountManager.resolve_decrypted_credentials(self.cid, aid)
        self.assertEqual(resolved["access_token"], "kite_access_tok_secret_value")

        # Verify next expiry computation is strictly in the future
        self.assertGreater(compute_next_kite_expiry_ts(), __import__("time").time())

    def test_2_static_ip_and_timeout_unknown_safety(self):
        # Adapter WITHOUT static_egress_ip MUST refuse order placement
        ad_no_ip = ZerodhaKiteAdapter(
            "ACC-ZERO-NOIP", self.cid, {"api_key": "k1", "api_secret": "s1", "access_token": "t1", "static_egress_ip": ""}
        )
        no_ip_res = ad_no_ip.place_order({"symbol": "RELIANCE", "exchange": "NSE", "side": "BUY", "quantity": 1})
        self.assertFalse(no_ip_res["ok"])
        self.assertEqual(no_ip_res["status"], "REJECTED")
        self.assertIn("static_egress_ip", no_ip_res["error"])

        # Adapter WITH static IP experiencing timeout MUST return UNKNOWN & NEVER retry blindly
        ad_timeout = ZerodhaKiteAdapter(
            "ACC-ZERO-TMO", self.cid, {"api_key": "k1", "api_secret": "s1", "access_token": "t1", "static_egress_ip": "13.200.45.10"}
        )
        with patch.object(ad_timeout._session, "request", side_effect=__import__("requests").Timeout("read timeout")) as req_spy:
            tmo_res = ad_timeout.place_order({"symbol": "RELIANCE", "exchange": "NSE", "side": "BUY", "quantity": 1})
            self.assertFalse(tmo_res["ok"])
            self.assertEqual(tmo_res["status"], "UNKNOWN")
            # Must be called EXACTLY ONCE (zero automatic retry!)
            self.assertEqual(req_spy.call_count, 1)

    def test_3_mock_zerodha_sync_pool_isolation_and_order_flow(self):
        client = api.test_client()
        tok = self._login(client)

        reg = client.post(
            "/api/v1/company/accounts",
            json={
                "provider": "ZERODHA",
                "account_name": "ARAA Zerodha Mock Sync",
                "api_key": "mock_key_1",
                "api_secret": "mock_sec_1",
                "static_egress_ip": "13.200.45.11",
            },
            headers={"X-Company-Token": tok},
        )
        aid = reg.get_json()["account"]["account_id"]

        # Register isolated MockZerodhaAdapter specifically for `aid`
        mock_instance = MockZerodhaAdapter(aid, self.cid, {"api_key": "mock_key_1"}, cash_inr="250000.00")
        UniversalBrokerManager.register_mock_for_account(self.cid, aid, lambda a, c, cr: mock_instance)

        # Verify & Sync into POOL_INDIA_INR
        sync_res = client.post(
            "/api/v1/brokers/zerodha/sync",
            json={"account_id": aid},
            headers={"X-Company-Token": tok},
        )
        self.assertEqual(sync_res.status_code, 200)
        status_res = client.get(f"/api/v1/brokers/zerodha/status?account_id={aid}", headers={"X-Company-Token": tok})
        self.assertEqual(status_res.status_code, 200)
        pool = status_res.get_json()["pool"]
        self.assertEqual(pool["pool_id"], POOL_INDIA_INR)
        self.assertEqual(pool["broker_confirmed_equity_inr"], "250000.00")

        # Crypto pool MUST stay isolated at 0.00
        cr_pool = query_one("SELECT broker_confirmed_equity_paise FROM company_capital_pools WHERE company_id=? AND pool_id=?", (self.cid, POOL_CRYPTO_SPOT))
        self.assertEqual(cr_pool["broker_confirmed_equity_paise"], 0)

        # Cross-pool routing check: routing Zerodha order through POOL_CRYPTO_SPOT MUST raise PermissionError
        with self.assertRaises(PermissionError):
            UniversalBrokerManager.route_order_for_account(
                self.cid, aid, POOL_CRYPTO_SPOT, {"symbol": "RELIANCE", "exchange": "NSE", "side": "BUY", "quantity": 1}
            )

        # Valid NSE order routes cleanly via UniversalBrokerManager
        ord_res = UniversalBrokerManager.route_order_for_account(
            self.cid, aid, POOL_INDIA_INR, {"symbol": "RELIANCE", "exchange": "NSE", "side": "BUY", "quantity": 2, "order_type": "MARKET"}
        )
        self.assertTrue(ord_res["ok"])
        oid = ord_res["provider_order_id"]

        # Order status & trade history verifiable
        st = mock_instance.get_order_status(oid)
        self.assertEqual(st["status"], "COMPLETE")
        self.assertEqual(len(mock_instance.get_trades()), 1)

        # Unauthorized segment / unknown symbol rejected cleanly
        bad_seg = UniversalBrokerManager.route_order_for_account(
            self.cid, aid, POOL_INDIA_INR, {"symbol": "GOLD", "exchange": "MCX", "side": "BUY", "quantity": 1, "order_type": "MARKET"}
        )
        self.assertFalse(bad_seg["ok"])

        # Limit order + cancel
        lim = UniversalBrokerManager.route_order_for_account(
            self.cid, aid, POOL_INDIA_INR, {"symbol": "TCS", "exchange": "NSE", "side": "BUY", "quantity": 1, "order_type": "LIMIT", "price": 4000.0}
        )
        self.assertTrue(lim["ok"])
        can = mock_instance.cancel_order(lim["provider_order_id"])
        self.assertTrue(can["ok"])

        # Disconnect leaves account cleanly DISCONNECTED
        disc = client.post("/api/v1/brokers/zerodha/disconnect", json={"account_id": aid}, headers={"X-Company-Token": tok})
        self.assertEqual(disc.status_code, 200)
        self.assertEqual(disc.get_json()["connection_status"], "DISCONNECTED")


if __name__ == "__main__":
    unittest.main()

