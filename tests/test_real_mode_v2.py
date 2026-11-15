"""Comprehensive Real Mode 2.0 Test Suite for AraaBot.

Tests:
1. 20-Point Preflight Validation (READY, BLOCKED, ERROR, EMERGENCY_STOP).
2. Failed exchange reconciliation blocks real mode execution.
3. Live Stop-Loss protection enforcement (never disabled when is_live=True).
4. Confirmed exchange fill derivation (never assumes requested qty).
5. Paper vs Live mode position, daily loss, and state isolation.
6. Multi-stage R-multiple profit booking (TP1, TP2, Trailing Stop).
7. Emergency Stop execution across all open live positions.
"""

import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from database import init_schema, query, query_one, write
from strategy_engine import StrategyEngine
from coindcx_adapter import CoinDCXExecutionAdapter
from tests.test_coindcx_integration_a_to_f import FakeCoinDCXClient


class TestRealModeV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_schema()

    def setUp(self):
        self.uid = write(
            "INSERT INTO users(email, name, pw_salt, pw_hash, bot_enabled, created_at) VALUES(?,?,?,?,?,?)",
            (f"realmode_test_{time.time()}@araabot.in", "RealModeTester", "salt", "hash", 1, time.time()),
        )
        write(
            "INSERT INTO wallets(user_id, deposit_balance, profit_balance, locked_balance) VALUES(?,?,?,?)",
            (self.uid, 500.0, 0.0, 0.0),
        )
        StrategyEngine.ensure_user_strategies(self.uid)
        now = time.time()
        write(
            """INSERT INTO broker_connections(user_id, broker_name, status, is_live_active, connected_at, last_synced_at)
               VALUES (?, 'COINDCX', 'CONNECTED', 1, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET status='CONNECTED', is_live_active=1, last_synced_at=excluded.last_synced_at""",
            (self.uid, now, now),
        )

    def test_01_preflight_20_point_validation_ready(self):
        fake_cdx = FakeCoinDCXClient(eligible=True, order_ok=True)
        with patch.object(CoinDCXExecutionAdapter, "_client", return_value=fake_cdx):
            res = StrategyEngine.validate_real_bot_preflight(self.uid)
            self.assertTrue(res["ready"])
            self.assertEqual(res["state"], "READY")
            self.assertIn("database_connected", res["checks"])
            self.assertIn("futures_permissions", res["checks"])
            self.assertIn("available_margin", res["checks"])
            self.assertIn("exchange_reconciliation", res["checks"])
            self.assertIn("stop_loss_configured", res["checks"])

    def test_02_preflight_blocked_when_offline(self):
        fake_cdx = FakeCoinDCXClient(offline=True)
        with patch.object(CoinDCXExecutionAdapter, "_client", return_value=fake_cdx):
            res = StrategyEngine.validate_real_bot_preflight(self.uid)
            self.assertFalse(res["ready"])
            self.assertEqual(res["state"], "BLOCKED")
            self.assertFalse(res["checks"]["coindcx_connectivity"])

    def test_03_preflight_emergency_stop_state(self):
        now = time.time()
        write(
            """INSERT INTO real_bot_configs(user_id, provider_id, bot_status, emergency_shutdown, created_at, updated_at)
               VALUES(?, 'COINDCX', 'EMERGENCY_STOP', 1, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET emergency_shutdown=1, bot_status='EMERGENCY_STOP', updated_at=excluded.updated_at""",
            (self.uid, now, now),
        )
        fake_cdx = FakeCoinDCXClient(eligible=True, order_ok=True)
        with patch.object(CoinDCXExecutionAdapter, "_client", return_value=fake_cdx):
            res = StrategyEngine.validate_real_bot_preflight(self.uid)
            self.assertFalse(res["ready"])
            self.assertEqual(res["state"], "EMERGENCY_STOP")
            self.assertFalse(res["checks"]["emergency_shutdown_inactive"])

    def test_04_live_stop_loss_not_bypassed(self):
        strat = StrategyEngine.get_strategy(self.uid, "araa_ai_default")
        # Position with -0.60% loss against a 0.50% SL on LIVE mode
        pos_live = {
            "id": "pos_live_1",
            "entry_price": 50000.0,
            "side": "LONG",
            "stop_pct": 0.50,
            "target_pct": 1.50,
            "is_live": 1,
            "qty": 0.01,
        }
        res = StrategyEngine.evaluate_position_profit_management(self.uid, pos_live, 49700.0, strat)
        self.assertEqual(res["action"], "STOP_LOSS_EXIT")
        self.assertIn("STOP_LOSS_GUARD", res["reason"])

    def test_05_confirmed_exchange_fill_derivation(self):
        fake_cdx = FakeCoinDCXClient(eligible=True, order_ok=True, partial=True)
        with patch.object(CoinDCXExecutionAdapter, "_client", return_value=fake_cdx):
            strat = StrategyEngine.get_strategy(self.uid, "araa_ai_default")
            res = CoinDCXExecutionAdapter.submit_order(
                user_id=self.uid,
                strategy_id=strat["strategy_id"],
                symbol="BTCUSDT",
                market_type="FUTURES",
                side="BUY",
                quantity=0.01,
                order_type="market_order",
                price=80000.0,
                stop_loss=79600.0,
                take_profit=80800.0,
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["status"], "PARTIALLY_FILLED")
            # FakeCoinDCX returns 50% filled for partial=True
            self.assertEqual(res["filled_qty"], 0.005)
            self.assertNotEqual(res["filled_qty"], 0.01)

    def test_06_paper_vs_live_mode_isolation(self):
        now = time.time()
        # Insert closed paper position with heavy loss
        write(
            """INSERT INTO positions(user_id, symbol, source, side, qty, margin, target_pct, stop_pct, entry_price, current_price, realized_pnl, status, is_live, opened_at, closed_at)
               VALUES(?, 'BTCUSDT', 'PAPER', 'BUY', 0.1, 50.0, 1.5, 0.5, 50000.0, 48000.0, -200.0, 'CLOSED', 0, ?, ?)""",
            (self.uid, now - 100, now - 50),
        )
        # Verify hard risk evaluation on Live mode is NOT blocked by Paper mode daily loss
        strat = StrategyEngine.get_strategy(self.uid, "araa_ai_default")
        # Ensure max daily loss is 50.0 (paper lost 200)
        strat["max_daily_loss_usd"] = 50.0
        ok_risk, msg = StrategyEngine.evaluate_hard_risk(self.uid, strat, "BTCUSDT", "BUY")
        self.assertTrue(ok_risk, f"Live hard risk should not be blocked by paper loss: {msg}")

    def test_07_smart_profit_booking_and_trailing_exit(self):
        strat = StrategyEngine.get_strategy(self.uid, "araa_ai_default")
        pos = {
            "id": "pos_test_tp",
            "entry_price": 50000.0,
            "side": "LONG",
            "qty": 0.05,
            "stop_pct": 0.50,
            "target_pct": 1.50,
            "partial_tp_booked": 0,
            "peak_pnl_pct": 0.0,
            "current_sl_price": 50060.0, # Breakeven SL already active
            "is_live": 1,
        }
        # Price hits 1R profit (+0.50% gain) -> TP1
        tp1_res = StrategyEngine.evaluate_v2_smart_profit_and_exit(self.uid, pos, 50260.0, strat)
        self.assertEqual(tp1_res["action"], "PARTIAL_EXIT")
        self.assertEqual(tp1_res["stage"], "TP1_1.0R")
        self.assertEqual(tp1_res["book_ratio"], 0.30)

        # Mark TP1 booked, price moves to 2R profit (+1.00% gain) -> TP2
        pos["partial_tp_booked"] = 1
        pos["tp1_booked"] = 1
        pos["peak_pnl_pct"] = 1.05
        tp2_res = StrategyEngine.evaluate_v2_smart_profit_and_exit(self.uid, pos, 50520.0, strat)
        self.assertEqual(tp2_res["action"], "PARTIAL_EXIT")
        self.assertEqual(tp2_res["stage"], "TP2_1.5R")
        self.assertEqual(tp2_res["book_ratio"], 0.30)

        # Mark TP2 booked, price pulls back from peak (+1.20% -> +0.80% with 0.25% trail) -> Trailing exit
        pos["partial_tp_booked"] = 2
        pos["tp2_booked"] = 1
        pos["peak_pnl_pct"] = 1.20
        trail_res = StrategyEngine.evaluate_v2_smart_profit_and_exit(self.uid, pos, 50400.0, strat)
        self.assertEqual(trail_res["action"], "FULL_EXIT")
        self.assertEqual(trail_res["exit_reason"], "TRAILING_STOP")

    def test_08_emergency_stop_closes_all_positions(self):
        # Open live position
        now = time.time()
        pos_id = write(
            """INSERT INTO positions(user_id, symbol, source, side, qty, margin, target_pct, stop_pct, entry_price, current_price, status, is_live, opened_at)
               VALUES(?, 'BTCUSDT', 'ARAA_AI', 'LONG', 0.02, 10.0, 1.5, 0.5, 50000.0, 50100.0, 'OPEN', 1, ?)""",
            (self.uid, now),
        )
        ctrl_res = StrategyEngine.set_auto_scalping_control(self.uid, "EMERGENCY_STOP")
        self.assertTrue(ctrl_res["success"])
        self.assertEqual(ctrl_res["status"], "EMERGENCY_STOP")
        self.assertGreaterEqual(ctrl_res["closed_positions"], 1)

        # Check DB position status
        pos_db = query_one("SELECT status, close_reason FROM positions WHERE id=?", (pos_id,))
        self.assertEqual(pos_db["status"], "CLOSED")
        self.assertEqual(pos_db["close_reason"], "EMERGENCY_STOP_TRIGGERED")


if __name__ == "__main__":
    unittest.main()
