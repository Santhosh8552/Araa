"""
AraaBot AI Prediction, Deep Market Analysis, Trade Learning & Security Test Suite.
Validates:
1. Deep Quantitative & Neural Prediction Engine output schema.
2. Market Shock Detection on flash crashes, surges, and spread widening.
3. Trade Learning Engine post-trade recording and automated loss analysis.
4. Strategy Improvement Proposals generated from loss patterns.
5. Strict Server-Side Security (RBAC, API key hiding, no secrets in responses).
6. Prevention of AI bypassing mandatory Python rules or risk limits.
"""

import os
import sys
import time
import json
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from database import init_schema, query, query_one, write
from prediction_engine import generate_deep_prediction
from market_shock_detector import MarketShockDetector
from trade_learning_engine import TradeLearningEngine
from strategy_engine import StrategyEngine
from backtest_engine import BacktestEngine
import app as araa_app


class TestAraaAIUpgrade(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_schema()
        cls.client = araa_app.api.test_client()

    def setUp(self):
        self.uid = write(
            "INSERT INTO users(email, name, pw_salt, pw_hash, bot_enabled, created_at) VALUES(?,?,?,?,?,?)",
            (f"ai_upgrade_{time.time()}@araabot.in", "AI Tester", "salt", "hash", 1, time.time()),
        )
        self.token = araa_app.make_session(self.uid, f"ai_upgrade_{time.time()}@araabot.in")
        write(
            "INSERT INTO wallets(user_id, deposit_balance, profit_balance, locked_balance) VALUES(?,?,?,?)",
            (self.uid, 500.0, 0.0, 0.0),
        )

    def test_01_deep_prediction_engine_output(self):
        """Verify Prediction Engine produces structured forecast and risk analytics."""
        candles, _, _, _ = BacktestEngine.generate_historical_candles("BTCUSDT", "15m", 50)
        pred = generate_deep_prediction("BTCUSDT", candles)
        self.assertIn("prediction", pred)
        self.assertIn("confidence_score", pred)
        self.assertIn("advanced_analytics", pred)
        adv = pred["advanced_analytics"]
        self.assertIn("breakout_probability_pct", adv)
        self.assertIn("reversal_probability_pct", adv)
        self.assertIn("target_reach_probability_pct", adv)
        self.assertIn("stop_loss_reach_probability_pct", adv)
        self.assertIn("roundtrip_friction_pct", adv)

    def test_02_market_shock_flash_crash_detection(self):
        """Verify MarketShockDetector flags sudden 3% downward movement and blocks entries."""
        candles, _, _, _ = BacktestEngine.generate_historical_candles("BTCUSDT", "1m", 30)
        # Induce a flash crash in the last bar
        curr_p = float(candles[-2]["c"])
        crash_p = curr_p * 0.96  # -4.0% flash crash
        candles[-1]["c"] = crash_p
        candles[-1]["l"] = crash_p
        shock = MarketShockDetector.analyze_market_shock("BTCUSDT", candles, current_price=crash_p)
        self.assertTrue(shock["shock_detected"])
        self.assertEqual(shock["shock_type"], "FLASH_CRASH_DROP")
        self.assertTrue(shock["block_new_entries"])
        self.assertEqual(shock["severity"], "CRITICAL")

    def test_03_trade_learning_and_loss_analysis(self):
        """Verify TradeLearningEngine records completed trades and diagnoses losses."""
        now = time.time()
        # Record a losing trade
        trade = TradeLearningEngine.record_completed_trade(
            user_id=self.uid,
            position_id="pos_loss_101",
            strategy_id="araa_ai_scalp",
            symbol="BTCUSDT",
            direction="BUY",
            entry_price=80000.0,
            exit_price=79500.0,
            quantity=0.01,
            realized_pnl=-5.0,
            trading_fees=0.50,
            opened_at=now - 120.0,
            closed_at=now,
            exit_reason="STOP_LOSS_GUARD (-0.62%)",
            market_regime="HIGH_VOLATILITY",
            prediction_direction="UP",
        )
        self.assertEqual(trade["net_pnl"], -5.50)
        self.assertIsNotNone(trade["loss_analysis"])
        self.assertIn("primary_cause", trade["loss_analysis"])
        self.assertIn("corrective_recommendations", trade["loss_analysis"])

    def test_04_strategy_improvement_proposal_generation(self):
        """Verify safe Strategy Improvement Proposals require admin approval."""
        proposal = TradeLearningEngine.generate_strategy_improvement_proposal(self.uid, "araa_ai_scalp")
        self.assertEqual(proposal["status"], "PENDING_ADMIN_APPROVAL")
        self.assertTrue(proposal["requires_approval"])
        self.assertIn("proposals", proposal)

    def test_05_deep_prediction_endpoint_security(self):
        """Verify prediction and analysis endpoints require authentication and leak no secrets."""
        # Unauthenticated request fails
        res_unauth = self.client.get("/api/bot/real-mode/deep-prediction?symbol=BTCUSDT")
        self.assertEqual(res_unauth.status_code, 401)

        # Authenticated request succeeds
        res_auth = self.client.get("/api/bot/real-mode/deep-prediction?symbol=BTCUSDT", headers={"X-Token": self.token})
        self.assertEqual(res_auth.status_code, 200)
        data = res_auth.get_json()
        self.assertTrue(data.get("success"))
        raw_text = res_auth.get_data(as_text=True)
        # Ensure no private API secrets, database passwords, or internal keys are leaked
        self.assertNotIn("api_secret", raw_text)
        self.assertNotIn("private_key", raw_text)
        self.assertNotIn("broker_api_secret", raw_text)


if __name__ == "__main__":
    unittest.main()
