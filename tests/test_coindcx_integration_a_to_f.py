"""Comprehensive Integration Tests for AraaBot CoinDCX + StrategyEngine (A-F)."""

import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import database
from database import init_schema as init_db, query_one, write
from coindcx_adapter import CoinDCXExecutionAdapter, sanitize_request
from strategy_engine import StrategyEngine


class FakeCoinDCXFutures:
    def __init__(self, eligible=True, order_ok=True, partial=False, tpsl_ok=True, err_msg=""):
        self.eligible = eligible
        self.order_ok = order_ok
        self.partial = partial
        self.tpsl_ok = tpsl_ok
        self.err_msg = err_msg
        self.orders_submitted = 0
        self.cancelled = False

    def check_eligibility(self):
        if not self.eligible:
            return {"eligible": False, "reason": "Futures trading permission disabled on API key"}
        return {"eligible": True}

    def resolve_leverage(self, symbol, req, side="buy"):
        return min(20.0, float(req or 20.0))

    def to_futures_pair(self, symbol):
        s = symbol.upper()
        if s.endswith("USDT"):
            return f"B-{s[:-4]}_USDT"
        return s

    def get_instrument(self, symbol):
        return {"last_price": 80000.0, "price_increment": 0.1}

    def get_available_futures_margin_usdt(self):
        return 50.0

    def get_positions(self):
        return True, [{"id": "cdx_pos_uuid_1", "pair": "B-BTC_USDT", "active_pos": 0.002, "avg_price": 80000.0, "leverage": 20.0}]

    def get_orders(self):
        return True, []

    def find_open_position(self, symbol):
        return {"id": "cdx_pos_uuid_1", "pair": self.to_futures_pair(symbol), "active_pos": 0.002}

    def place_futures_order(self, symbol, side, quantity, leverage=20.0, order_type="market_order", price=None, stop_loss=None, take_profit=None, client_order_id=None):
        self.orders_submitted += 1
        if not self.order_ok:
            return False, {"message": self.err_msg or "Insufficient margin in CoinDCX Futures wallet"}
        filled = round(quantity * 0.5, 6) if self.partial else quantity
        return True, {
            "id": f"cdx_ord_{self.orders_submitted}",
            "status": "partially_filled" if self.partial else "filled",
            "total_quantity": quantity,
            "filled_quantity": filled,
            "avg_price": float(price or 80000.0),
            "fee_amount": round(filled * float(price or 80000.0) * 0.0005, 4),
        }

    def _call(self, path, body=None, attempts=1):
        if "create_tpsl" in path:
            if not self.tpsl_ok:
                return False, {"message": "Take profit price rejected by CoinDCX"}
            return True, {"stop_loss_order_id": "sl_1", "take_profit_order_id": "tp_1"}
        if "cancel" in path:
            self.cancelled = True
            return True, {}
        return True, {}


class FakeCoinDCXClient:
    def __init__(self, offline=False, eligible=True, order_ok=True, partial=False, tpsl_ok=True, err_msg=""):
        self.is_offline = offline
        self.futures = FakeCoinDCXFutures(eligible=eligible, order_ok=order_ok, partial=partial, tpsl_ok=tpsl_ok, err_msg=err_msg)
        self.cancelled_all = False

    def get_balances(self):
        return True, {"usdt_free": 50.0, "total_portfolio_usd": 75.0}

    def cancel_all_orders(self):
        self.cancelled_all = True
        return 1


class TestCoinDCXIntegrationAToF(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        # Create isolated test user
        self.uid = write(
            "INSERT INTO users(email, name, pw_salt, pw_hash, bot_enabled, created_at) VALUES(?,?,?,?,?,?)",
            (f"tvtest_{time.time()}@araabot.in", "TestUser", "s", "h", 1, time.time()),
        )
        write(
            "INSERT INTO wallets(user_id, deposit_balance, profit_balance, locked_balance) VALUES(?,?,?,?)",
            (self.uid, 100.0, 0.0, 0.0),
        )
        StrategyEngine.ensure_user_strategies(self.uid)

    def _enable_real_mode(self):
        now = time.time()
        write(
            """INSERT INTO broker_connections(user_id, broker_name, status, is_live_active, connected_at, last_synced_at)
               VALUES (?, 'COINDCX', 'CONNECTED', 1, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET status='CONNECTED', is_live_active=1, last_synced_at=excluded.last_synced_at""",
            (self.uid, now, now),
        )

    def test_1_custom_strategy_triggers_paper_trade(self):
        strat = StrategyEngine.save_strategy(self.uid, {
            "strategy_id": "custom_scalp",
            "enabled": 1,
            "position_size_usd": 10.0,
            "stop_loss_pct": 0.5,
            "take_profit_pct": 1.2,
            "cooldown_seconds": 0.0,
        })
        res = StrategyEngine.execute_order_intent(
            user_id=self.uid, strategy=strat, symbol="BTCUSDT", side="BUY", ref_price=80000.0
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["mode"], "PAPER")
        self.assertEqual(res["status"], "EXECUTED_PAPER")
        self.assertTrue(res["protection"]["protection_verified"])

    def test_2_tradingview_webhook_triggers_paper_trade_and_blocks_duplicate_and_expired(self):
        sec = StrategyEngine.get_or_create_webhook_secret(self.uid)
        payload = {
            "secret": sec,
            "user_id": self.uid,
            "strategy_id": "tv_pine_default",
            "ticker": "ETHUSDT",
            "action": "BUY",
            "price": 2500.0,
            "timestamp": time.time(),
            "signal_id": f"sig_{int(time.time()*1000)}",
        }
        code, res = StrategyEngine.process_tradingview_webhook(payload)
        self.assertEqual(code, 200)
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "EXECUTED_PAPER")

        # Duplicate signal must be ignored
        code_dup, res_dup = StrategyEngine.process_tradingview_webhook(payload)
        self.assertEqual(code_dup, 200)
        self.assertEqual(res_dup["status"], "IGNORED_DUPLICATE")

        # Expired signal must be rejected
        old_payload = dict(payload, signal_id="sig_old", timestamp=time.time() - 500)
        code_exp, res_exp = StrategyEngine.process_tradingview_webhook(old_payload)
        self.assertEqual(code_exp, 400)
        self.assertEqual(res_exp["status"], "REJECTED_EXPIRED")

        # Bad auth must be rejected
        bad_auth = dict(payload, secret="wrong_secret", signal_id="sig_badauth")
        code_auth, res_auth = StrategyEngine.process_tradingview_webhook(bad_auth)
        self.assertEqual(code_auth, 401)
        self.assertEqual(res_auth["status"], "REJECTED_AUTH")

    def test_3_valid_live_signal_executes_coindcx_and_verifies_tpsl(self):
        self._enable_real_mode()
        fake_cdx = FakeCoinDCXClient(eligible=True, order_ok=True, tpsl_ok=True)
        strat = StrategyEngine.save_strategy(self.uid, {"strategy_id": "araa_ai_default", "cooldown_seconds": 0.0})
        with patch.object(CoinDCXExecutionAdapter, "_client", return_value=fake_cdx):
            res = StrategyEngine.execute_order_intent(
                user_id=self.uid, strategy=strat, symbol="BTCUSDT", side="BUY", ref_price=80000.0,
                client_order_id=f"live_idem_{self.uid}",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["mode"], "REAL")
            self.assertEqual(res["status"], "EXECUTED_LIVE")
            self.assertTrue(res["protection"]["protection_verified"])
            self.assertEqual(res["protection"]["protection_status"], "VERIFIED")
            self.assertGreater(res["fee_usd"], 0.0)

            # Idempotent retry must NOT submit a second live order
            res_replay = CoinDCXExecutionAdapter.submit_order(
                self.uid, symbol="BTCUSDT", side="BUY", market_type="FUTURES",
                quantity=0.002, client_order_id=f"live_idem_{self.uid}",
            )
            self.assertTrue(res_replay.get("idempotent_replay"))
            self.assertEqual(fake_cdx.futures.orders_submitted, 1)

    def test_4_rejected_live_order_exposes_exact_diagnostics_no_silent_paper_fallback(self):
        self._enable_real_mode()
        fake_cdx = FakeCoinDCXClient(eligible=True, order_ok=False, err_msg="Insufficient balance in Futures wallet")
        strat = StrategyEngine.save_strategy(self.uid, {"strategy_id": "araa_ai_default", "cooldown_seconds": 0.0})
        with patch.object(CoinDCXExecutionAdapter, "_client", return_value=fake_cdx):
            res = StrategyEngine.execute_order_intent(
                user_id=self.uid, strategy=strat, symbol="BTCUSDT", side="BUY", ref_price=80000.0
            )
            self.assertFalse(res["success"])
            self.assertEqual(res["mode"], "REAL")  # Never silently falls back to PAPER
            self.assertEqual(res["status"], "REJECTED_BY_EXCHANGE")
            self.assertIn("Insufficient balance", res["error"])
            self.assertIn("/exchange/v1/derivatives/futures/orders/create", res["endpoint"])
            self.assertTrue(res["corrective_action"])

    def test_5_partial_fill_and_failed_tpsl_protection_visible(self):
        self._enable_real_mode()
        fake_cdx = FakeCoinDCXClient(eligible=True, order_ok=True, partial=True, tpsl_ok=False)
        strat = StrategyEngine.save_strategy(self.uid, {"strategy_id": "araa_ai_default", "cooldown_seconds": 0.0})
        with patch.object(CoinDCXExecutionAdapter, "_client", return_value=fake_cdx):
            res = StrategyEngine.execute_order_intent(
                user_id=self.uid, strategy=strat, symbol="BTCUSDT", side="BUY", ref_price=80000.0, quantity=0.004
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["order_status"], "PARTIALLY_FILLED")
            self.assertAlmostEqual(res["filled_qty"], 0.002, places=6)
            self.assertFalse(res["protection"]["protection_verified"])
            self.assertEqual(res["protection"]["protection_status"], "FAILED")
            self.assertIn("rejected", res["protection"]["failure_reason"].lower())

    def test_6_edge_cases_disconnected_invalid_symbol_permission_emergency_stop_restart(self):
        self._enable_real_mode()
        # Disconnected API
        with patch.object(CoinDCXExecutionAdapter, "_client", return_value=None):
            res = CoinDCXExecutionAdapter.submit_order(self.uid, symbol="BTCUSDT", side="BUY", quantity=0.001)
            self.assertFalse(res["success"])
            self.assertIn("disconnected", res["error"].lower())

        # API permission failure
        no_perm = FakeCoinDCXClient(eligible=False)
        with patch.object(CoinDCXExecutionAdapter, "_client", return_value=no_perm):
            res_perm = CoinDCXExecutionAdapter.submit_order(self.uid, symbol="BTCUSDT", side="BUY", quantity=0.001)
            self.assertFalse(res_perm["success"])
            self.assertIn("permission", res_perm["error"].lower())

        # Invalid symbol via TradingView
        sec = StrategyEngine.get_or_create_webhook_secret(self.uid)
        c_sym, r_sym = StrategyEngine.process_tradingview_webhook({
            "secret": sec, "user_id": self.uid, "ticker": "BAD", "action": "BUY", "timestamp": time.time(), "signal_id": "bad_sym_1"
        })
        self.assertEqual(c_sym, 400)
        self.assertEqual(r_sym["status"], "REJECTED_SYMBOL")

        # Emergency stop blocks execution
        write(
            "INSERT INTO real_bot_configs(user_id, provider_id, emergency_shutdown, bot_status, created_at, updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET emergency_shutdown=1",
            (self.uid, "COINDCX", 1, "STOPPED", time.time(), time.time()),
        )
        strat = StrategyEngine.get_strategy(self.uid, "araa_ai_default")
        res_em = StrategyEngine.execute_order_intent(
            user_id=self.uid, strategy=strat, symbol="BTCUSDT", side="BUY", ref_price=80000.0
        )
        self.assertFalse(res_em["success"])
        self.assertEqual(res_em["status"], "REJECTED_BY_RISK")

        # Sanitization never leaks secrets
        san = sanitize_request({"api_key": "123", "secret": "abc", "symbol": "BTCUSDT"})
        self.assertEqual(san["api_key"], "***REDACTED***")
        self.assertEqual(san["secret"], "***REDACTED***")
        self.assertEqual(san["symbol"], "BTCUSDT")

        # Restart reconciliation check
        with patch.object(CoinDCXExecutionAdapter, "_client", return_value=FakeCoinDCXClient()):
            rec = CoinDCXExecutionAdapter.reconcile_state(self.uid)
            self.assertTrue(rec["connected"])

    def test_7_persistent_login_session_survives_restart_until_logout(self):
        import app as araa_app
        tok = araa_app.make_session(self.uid, f"u{self.uid}@test.in")
        self.assertTrue(tok.startswith("v1."))
        # Simulate container/DB session table reset while user did NOT click logout
        write("DELETE FROM sessions WHERE user_id=?", (self.uid,))
        with araa_app.api.test_request_context("/api/auth/me", headers={"X-Token": tok}):
            u = araa_app.current_user()
            self.assertIsNotNone(u)
            self.assertEqual(u["id"], self.uid)
        # Now simulate explicit user logout
        with araa_app.api.test_request_context("/api/auth/logout", method="POST", headers={"X-Token": tok}):
            araa_app.logout()
        with araa_app.api.test_request_context("/api/auth/me", headers={"X-Token": tok}):
            self.assertIsNone(araa_app.current_user())

    def test_8_real_bot_controller_extended_risk_profit_management_and_usd_dashboard(self):
        # 1. Controller state & preflight check
        self._enable_real_mode()
        fake_cdx = FakeCoinDCXClient(eligible=True, order_ok=True)
        with patch.object(CoinDCXExecutionAdapter, "_client", return_value=fake_cdx):
            preflight = StrategyEngine.validate_real_bot_preflight(self.uid)
            self.assertTrue(preflight["ready"])
            self.assertEqual(preflight["state"], "READY")

            # Execute a live trade and verify USD profit dashboard
            strat = StrategyEngine.save_strategy(self.uid, {
                "strategy_id": "araa_ai_default",
                "cooldown_seconds": 0.0,
                "stop_loss_pct": 0.50,
                "take_profit_pct": 1.20,
                "entry_rules": {"min_risk_reward": 1.8, "max_spread_pct": 0.25},
                "exit_rules": {"breakeven_trigger_pct": 0.45, "partial_tp_trigger_pct": 0.75},
            })
            # Spread protection rejection
            ok_sp, msg_sp = StrategyEngine.evaluate_hard_risk(
                self.uid, strat, "BTCUSDT", "BUY", market_context={"spread_pct": 0.40}
            )
            self.assertFalse(ok_sp)
            self.assertIn("spread", msg_sp.lower())

            # Profit management evaluation (partial TP, trailing, full TP)
            pos = {"entry_price": 80000.0, "side": "LONG", "target_pct": 1.20, "stop_pct": 0.50, "trailing_stop_pct": 0.20, "peak_pnl_pct": 0.85, "partial_tp_booked": 0, "is_live": 1}
            pm_part = StrategyEngine.evaluate_position_profit_management(self.uid, pos, 80640.0, strat)
            self.assertEqual(pm_part["action"], "PARTIAL_EXIT")
            pos["partial_tp_booked"] = 1
            pm_trail = StrategyEngine.evaluate_position_profit_management(self.uid, pos, 80450.0, strat)
            self.assertEqual(pm_trail["action"], "TRAILING_EXIT")

            # USD Profit Dashboard calculation
            dash = CoinDCXExecutionAdapter.compute_usd_profit_dashboard(self.uid)
            self.assertEqual(dash["currency"], "USDT")
            self.assertGreaterEqual(dash["available_balance_usdt"], 50.0)
            self.assertIn("net_profit_usdt", dash)
            self.assertIn("total_trading_fees_usdt", dash)


if __name__ == "__main__":
    unittest.main()
