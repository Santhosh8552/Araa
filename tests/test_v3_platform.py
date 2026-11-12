import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import database as db
from risk_engine import InstitutionalRiskEngine, OrderLifecycleManager
from ai_committee import AICommitteeOrchestrator, AgentAlphaMarketIntelligence, AgentBetaTechnicalIntelligence
from backtest_engine import BacktestEngine
from saas_manager import SubscriptionManager, AuthSecurityManager, AnalyticsAndReportEngine
from exchange_adapter import ExchangeConnectionManager


class TestAraaBotV3Platform(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_schema()
        if not db.query_one("SELECT id FROM users LIMIT 1"):
            db.seed_users()
        u = db.query_one("SELECT id FROM users ORDER BY id ASC LIMIT 1")
        cls.uid = u["id"] if u else 1
        # Ensure clean open positions for test user
        db.write("UPDATE positions SET status='CLOSED' WHERE user_id=? AND status IN ('OPEN','PENDING_BROKER')", (cls.uid,))
        InstitutionalRiskEngine.set_global_kill_switch(False, "TEST_INIT")

    def test_01_subscription_plans_seeded_and_verified_payment(self):
        plans = SubscriptionManager.get_all_plans()
        codes = {p["plan_code"] for p in plans}
        self.assertTrue({"STARTER", "PRO", "PREMIUM", "ENTERPRISE"}.issubset(codes))

        # Test checkout & cryptographic HMAC signature verification
        order = SubscriptionManager.create_checkout_order(
            user_id=self.uid, plan_code="PRO", billing_cycle="MONTHLY", payment_method="UPI"
        )
        self.assertTrue(order["ok"])
        inv_no = order["invoice_no"]
        sb = order["sandbox_verification_payload"]

        # Forged signature must be strictly rejected
        bad_verify = SubscriptionManager.verify_and_activate_subscription(
            user_id=self.uid,
            invoice_no=inv_no,
            provider_order_id=sb["provider_order_id"],
            provider_payment_id=sb["provider_payment_id"],
            provider_signature="forged_invalid_signature_000",
        )
        self.assertFalse(bad_verify["ok"])

        # Valid HMAC-SHA256 signature activates subscription
        good_verify = SubscriptionManager.verify_and_activate_subscription(
            user_id=self.uid,
            invoice_no=inv_no,
            provider_order_id=sb["provider_order_id"],
            provider_payment_id=sb["provider_payment_id"],
            provider_signature=sb["provider_signature"],
        )
        self.assertTrue(good_verify["ok"])
        self.assertEqual(good_verify["status"], "PAID_VERIFIED")
        self.assertEqual(good_verify["plan_code"], "PRO")

    def test_02_independent_risk_engine_and_order_lifecycle(self):
        InstitutionalRiskEngine.set_global_kill_switch(False)
        ok_risk, reason, details = InstitutionalRiskEngine.evaluate_pre_trade_risk(
            user_id=self.uid,
            symbol="BTCUSDT",
            side="LONG",
            equity_usd=1000.0,
            entry_price=90000.0,
            stop_price=89100.0,
            take_profit_price=92000.0,
            requested_leverage=10.0,
            is_live=False,
        )
        self.assertTrue(ok_risk, f"Expected risk approval, got: {reason}")
        self.assertLessEqual(details["limits"]["max_open_positions"], 50)  # Unlimited bypass prevented

        # Global kill switch must block trade immediately
        InstitutionalRiskEngine.set_global_kill_switch(True, "TEST_HALT")
        blocked_ok, blocked_reason, _ = InstitutionalRiskEngine.evaluate_pre_trade_risk(
            user_id=self.uid, symbol="BTCUSDT", side="LONG", equity_usd=1000.0,
            entry_price=90000.0, stop_price=89100.0, take_profit_price=92000.0
        )
        self.assertFalse(blocked_ok)
        self.assertIn("KILL_SWITCH", blocked_reason)
        InstitutionalRiskEngine.set_global_kill_switch(False, "TEST_RESUME")

        # Unique Order UUID & execution lifecycle
        ord_uuid = OrderLifecycleManager.create_order_record(
            user_id=self.uid, symbol="BTCUSDT", side="LONG", order_type="MARKET",
            requested_price=90000.0, qty=0.05, leverage=10.0, is_live=False
        )
        self.assertTrue(ord_uuid.startswith("ORD-"))
        fill = OrderLifecycleManager.confirm_order_fill(
            order_uuid=ord_uuid, executed_price=90018.0, qty=0.05, is_live=False
        )
        self.assertEqual(fill["status"], "FILLED_SIMULATED")
        self.assertGreater(fill["fee_usd"], 0.0)

    def test_03_three_agent_ai_committee_and_explainable_logs(self):
        candles, _, _, _ = BacktestEngine.generate_historical_candles("BTCUSDT", "15m", count=60)
        res = AICommitteeOrchestrator.evaluate_candidate(
            symbol="BTCUSDT",
            user_id=self.uid,
            candles=candles,
            quote_data={"price": candles[-1]["c"], "change_pct": 1.2, "volume": 500000.0},
            equity_usd=1000.0,
            requested_leverage=10.0,
            timeframe="15m",
            is_live=False,
            persist=True,
        )
        self.assertIn("alpha", res)
        self.assertIn("beta", res)
        self.assertIn("gamma", res)
        self.assertIn("rsi_14", res["beta"]["indicators"])
        self.assertIn("tillson_t3", res["beta"]["indicators"])
        self.assertIn("vwap", res["beta"]["indicators"])
        self.assertIn("explainable_rationale", res)
        self.assertIn("not guaranteed win outcomes", res["explainable_rationale"])

    def test_04_historical_backtest_engine(self):
        bt = BacktestEngine.run_backtest(
            user_id=self.uid,
            symbol="BTCUSDT",
            strategy_mode="COMMITTEE_HYBRID",
            timeframe="15m",
            initial_capital=1000.0,
            leverage=10.0,
            risk_per_trade_pct=2.0,
        )
        self.assertEqual(bt["symbol"], "BTCUSDT")
        self.assertGreaterEqual(bt["total_trades"], 1)
        self.assertGreater(len(bt["equity_curve"]), 1)
        self.assertIn("sharpe_ratio", bt)
        self.assertIn("profit_factor", bt)
        self.assertIn("max_drawdown_pct", bt)

    def test_05_auth_2fa_exchange_adapter_and_csv_export(self):
        tok = AuthSecurityManager.generate_otp_token(user_id=self.uid, purpose="2FA_VERIFY")
        self.assertEqual(len(tok["otp_code"]), 6)
        ver = AuthSecurityManager.verify_otp_token(user_id=self.uid, code=tok["otp_code"], purpose="2FA_VERIFY")
        self.assertTrue(ver["ok"])

        ex_list = ExchangeConnectionManager.list_supported_exchanges()
        self.assertEqual(ex_list[0]["exchange_id"], "COINDCX")
        self.assertFalse(ex_list[0]["withdrawal_permission_required"])

        csv_data = AnalyticsAndReportEngine.export_trades_csv(user_id=self.uid)
        self.assertIn("Order_UUID", csv_data)

    def test_06_v3_flask_api_endpoints(self):
        from backend.app import api
        client = api.test_client()

        r_plans = client.get("/api/v3/subscriptions/plans")
        self.assertEqual(r_plans.status_code, 200)
        d_plans = r_plans.get_json()
        self.assertTrue(d_plans["ok"])
        self.assertEqual(len(d_plans["plans"]), 4)

        r_comm = client.get("/api/v3/committee/evaluate?symbol=BTCUSDT&timeframe=15m")
        self.assertEqual(r_comm.status_code, 200)
        d_comm = r_comm.get_json()
        self.assertTrue(d_comm["ok"])
        self.assertIn("consensus_score", d_comm)

        r_bt = client.post("/api/v3/backtest/run", json={
            "symbol": "ETHUSDT",
            "strategy_mode": "COMMITTEE_HYBRID",
            "timeframe": "15m",
            "initial_capital": 1000.0,
            "leverage": 10.0,
        })
        self.assertEqual(r_bt.status_code, 200)
        d_bt = r_bt.get_json()
        self.assertTrue(d_bt["ok"])
        self.assertEqual(d_bt["symbol"], "ETHUSDT")

        r_adm = client.get("/api/v3/admin/overview")
        self.assertEqual(r_adm.status_code, 200)
        d_adm = r_adm.get_json()
        self.assertTrue(d_adm["ok"])
        self.assertIn("total_registered_users", d_adm["metrics"])
        # Ensure no raw API secret is ever present in admin overview payload
        self.assertNotIn("api_secret", str(d_adm))


if __name__ == "__main__":
    unittest.main()
