import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test_v21_scalping.db"))

import app as backend_app
from analysis_engine import (
    analyze_technical_v2,
    analyze_multi_timeframe,
    analyze_scalping_strategies,
    generate_araa_ai_analysis,
)
from backtest_engine import BacktestEngine
from coindcx_adapter import CoinDCXExecutionAdapter
from database import init_schema as init_db, query_one, write
from strategy_engine import StrategyEngine


class TestAraaBotV21AutoScalping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = backend_app.api.test_client()

        # Create test user & wallet & broker connection
        u = query_one("SELECT id FROM users WHERE email='scalper_v21@test.com'")
        if not u:
            cls.uid = write(
                "INSERT INTO users(email, name, pw_salt, pw_hash, created_at, last_login_at, bot_enabled, bot_mode) "
                "VALUES('scalper_v21@test.com', 'Scalper Tester', 'salt', 'hash', ?, ?, 1, 'SCALP')",
                (time.time(), time.time()),
            )
            write(
                "INSERT INTO wallets(user_id, deposit_balance, locked_balance, profit_balance, total_deposited) "
                "VALUES(?, 5000.0, 0.0, 0.0, 5000.0)",
                (cls.uid,),
            )
            write(
                "INSERT INTO broker_connections(user_id, broker_name, status, is_live_active, live_balance, connected_at, last_synced_at) "
                "VALUES(?, 'COINDCX', 'CONNECTED', 1, 5000.0, ?, ?)",
                (cls.uid, time.time(), time.time()),
            )
            write(
                "INSERT INTO real_bot_configs(user_id, provider_id, bot_status, emergency_shutdown, max_daily_loss, max_positions, created_at, updated_at) "
                "VALUES(?, 'coindcx_real', 'RUNNING', 0, 150.0, 1, ?, ?)",
                (cls.uid, time.time(), time.time()),
            )
        else:
            cls.uid = u["id"]

        cls.token = f"test_scalp_token_{cls.uid}_{int(time.time())}"
        write(
            "INSERT INTO sessions(token, user_id, created_at, last_seen) VALUES(?, ?, ?, ?)",
            (cls.token, cls.uid, time.time(), time.time()),
        )

    def setUp(self):
        self.uid = self.__class__.uid
        self.token = self.__class__.token
        self.client = self.__class__.client

    def _headers(self):
        return {"X-Token": self.token}

    def test_01_scalping_strategies_evaluation(self):
        """Test the 5 Scalping Strategies: EMA, RSI, MACD, Breakout, and Araa AI."""
        # Generate 65 candles with upward momentum
        candles, _, _, _ = BacktestEngine.generate_historical_candles(symbol="BTCUSDT", timeframe="1m", count=65)
        ta = analyze_technical_v2("BTCUSDT", candles, timeframe="1m", use_closed_candles_only=True)
        self.assertTrue(ta["valid"])

        mtf = analyze_multi_timeframe("BTCUSDT", {"1m": candles, "5m": candles, "15m": candles})
        self.assertIn("dominant_direction", mtf)

        # Analyze all 5 strategies
        scalp_res = analyze_scalping_strategies("BTCUSDT", ta, mtf_result=mtf, custom_scalp_cfg={"active_scalping_strategy": "ARAA_AI_SCALPING"})
        self.assertTrue(scalp_res["valid"])
        strategies = scalp_res["strategies"]

        # 1. EMA Momentum Scalping
        self.assertIn("EMA_MOMENTUM_SCALPING", strategies)
        ema_strat = strategies["EMA_MOMENTUM_SCALPING"]
        self.assertIn("ema9", ema_strat)
        self.assertIn("ema21", ema_strat)
        self.assertIn("ema50", ema_strat)

        # 2. RSI Momentum Scalping
        self.assertIn("RSI_MOMENTUM_SCALPING", strategies)
        rsi_strat = strategies["RSI_MOMENTUM_SCALPING"]
        self.assertIn("rsi14", rsi_strat)
        self.assertIn("trend_filter_passed", rsi_strat)

        # 3. MACD Scalping
        self.assertIn("MACD_SCALPING", strategies)
        macd_strat = strategies["MACD_SCALPING"]
        self.assertIn("macd", macd_strat)
        self.assertIn("signal_line", macd_strat)
        self.assertIn("histogram", macd_strat)

        # 4. Breakout Scalping
        self.assertIn("BREAKOUT_SCALPING", strategies)
        breakout_strat = strategies["BREAKOUT_SCALPING"]
        self.assertIn("supports", breakout_strat)
        self.assertIn("resistances", breakout_strat)

        # 5. Araa AI Scalping
        self.assertIn("ARAA_AI_SCALPING", strategies)
        ai_strat = strategies["ARAA_AI_SCALPING"]
        self.assertIn("entry_proposal", ai_strat)
        self.assertIn("exit_proposal", ai_strat)

    def test_02_python_rules_control_every_entry(self):
        """Verify that Python rules strictly approve or reject entries, never letting AI bypass."""
        candles, _, _, _ = BacktestEngine.generate_historical_candles(symbol="BTCUSDT", timeframe="1m", count=65)
        # Even if AI proposes an entry, if a required rule fails (e.g. invalid stablecoin or huge spread), Python rejects
        rule_res = StrategyEngine.evaluate_v2_rule_pipeline(
            user_id=self.uid,
            symbol="USDCUSDT",  # Blocked stablecoin
            side="LONG",
            strategy_id="araa_ai_scalp",
            candles=candles,
        )
        self.assertFalse(rule_res["approved"])
        self.assertEqual(rule_res["execution_approval"], "REJECTED")
        self.assertTrue(any("Instrument" in r for r in rule_res["rejection_reasons"]))

    def test_03_auto_scalp_cycle_execution(self):
        """Test full 16-step execute_auto_scalp_cycle method."""
        res = StrategyEngine.execute_auto_scalp_cycle(
            user_id=self.uid,
            symbol="BTCUSDT",
            strategy_code="ARAA_AI_SCALPING",
            timeframes={"entry": "1m", "setup": "5m", "trend": "15m"},
        )
        self.assertTrue(res["success"])
        self.assertIn("scalp_analysis", res or res.get("rule_evaluation", {}))

    def test_04_smart_partial_profit_booking_tp1_tp2_and_breakeven(self):
        """Verify TP1 (1R = 30%), TP2 (1.5R = 30%), and Breakeven Protection."""
        pos = {
            "id": 999,
            "user_id": self.uid,
            "symbol": "BTCUSDT",
            "side": "LONG",
            "entry_price": 80000.0,
            "current_sl_price": 79720.0,  # 0.35% SL distance = $280
            "stop_pct": 0.35,
            "target_pct": 0.70,
            "qty": 0.10,
            "partial_tp_booked": 0,
            "is_live": 0,
        }

        # 1. Price moves up by 1R ($80,280 = +0.35%) -> TP1 partial booking
        exit_tp1 = StrategyEngine.evaluate_v2_smart_profit_and_exit(
            user_id=self.uid,
            position=pos,
            current_price=80280.0,
        )
        self.assertEqual(exit_tp1["action"], "PARTIAL_EXIT")
        self.assertEqual(exit_tp1["exit_reason"], "PARTIAL_TAKE_PROFIT_TP1")
        self.assertAlmostEqual(exit_tp1["close_qty"], 0.03, places=3)
        self.assertGreaterEqual(exit_tp1["new_sl_price"], 80000.0)  # Stop tightened to BE

        # 2. Once TP1 is booked, price moves to 1.5R ($80,420 = +0.525%) -> TP2 partial booking
        pos["partial_tp_booked"] = 1
        pos["qty"] = 0.07
        exit_tp2 = StrategyEngine.evaluate_v2_smart_profit_and_exit(
            user_id=self.uid,
            position=pos,
            current_price=80420.0,
        )
        self.assertEqual(exit_tp2["action"], "PARTIAL_EXIT")
        self.assertEqual(exit_tp2["exit_reason"], "PARTIAL_TAKE_PROFIT_TP2")
        self.assertAlmostEqual(exit_tp2["close_qty"], 0.021, places=3)

    def test_05_auto_scalping_api_endpoints(self):
        """Test the REST API endpoints: status, control, cycle, and dashboard."""
        hdrs = self._headers()

        # 1. Status endpoint
        res = self.client.get("/api/v2/scalping/status", headers=hdrs)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("scalping_status", data)

        # 2. Control endpoint (PAUSE -> RESUME)
        res_ctrl = self.client.post("/api/v2/scalping/control", json={"action": "PAUSE"}, headers=hdrs)
        self.assertEqual(res_ctrl.status_code, 200)
        self.assertEqual(res_ctrl.get_json()["status"], "PAUSED")

        res_res = self.client.post("/api/v2/scalping/control", json={"action": "RESUME"}, headers=hdrs)
        self.assertEqual(res_res.status_code, 200)
        self.assertEqual(res_res.get_json()["status"], "RUNNING")

        # 3. Cycle endpoint
        res_cyc = self.client.post(
            "/api/v2/scalping/cycle",
            json={"symbol": "BTCUSDT", "strategy": "ARAA_AI_SCALPING"},
            headers=hdrs,
        )
        self.assertEqual(res_cyc.status_code, 200)
        self.assertTrue(res_cyc.get_json().get("success"))

        # 4. Full Dashboard endpoint
        res_dash = self.client.get("/api/v2/scalping/dashboard?symbol=BTCUSDT", headers=hdrs)
        self.assertEqual(res_dash.status_code, 200)
        dash_data = res_dash.get_json()
        self.assertTrue(dash_data.get("success"))
        self.assertIn("auto_scalping_panel", dash_data)
        self.assertIn("live_scalping_positions", dash_data)
        self.assertIn("scalping_performance", dash_data)
        asp = dash_data["auto_scalping_panel"]
        self.assertIn("indicators", asp)
        self.assertIn("current_signal", asp)
        self.assertIn("all_strategies", asp)


if __name__ == "__main__":
    unittest.main()
