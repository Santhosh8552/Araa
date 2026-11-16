"""Regression tests for CoinDCX settlement, fee-safe take profit, and TOTAL BALANCE sync."""
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test_cdx_settle.db"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from database import init_schema, query_one, write
import coindcx_gateway
from coindcx_adapter import CoinDCXExecutionAdapter
from bot_engine import Bot
from price_feed import PriceFeed
import real_broker
import app as backend_app


class CoinDCXSettlementAndBalanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_schema()

    def setUp(self):
        now = time.time()
        self.uid = write(
            "INSERT INTO users(email, name, pw_salt, pw_hash, bot_enabled, bot_leverage, created_at) VALUES(?,?,?,?,?,?,?)",
            (f"settle_{now}@araabot.in", "SettleUser", "s", "h", 1, 100.0, now),
        )
        write(
            "INSERT INTO wallets(user_id, deposit_balance, starting_balance, target_amount, profit_balance, locked_balance) VALUES(?,?,?,?,?,?)",
            (self.uid, 32.12, 32.12, 48.18, 0.0, 0.0),
        )
        write(
            """INSERT INTO broker_connections(
                 user_id, broker_name, api_key_masked, status, is_live_active,
                 live_balance, live_equity, free_margin, currency, connected_at, last_synced_at
               ) VALUES(?, 'COINDCX', '0505...72db', 'CONNECTED', 1, 32.12, 32.12, 32.12, 'USDT', ?, ?)""",
            (self.uid, now, now),
        )

    def test_1_futures_get_orders_and_settlement_transactions(self):
        calls = []

        def fake_req(endpoint, method="GET", body=None, api_key=None, api_secret=None, **kw):
            calls.append((endpoint, body))
            if endpoint.endswith("/futures/orders"):
                side = (body or {}).get("side")
                return True, [{"id": f"ord_{side}", "pair": "B-BTC_USDT", "status": "open", "side": side}]
            if endpoint.endswith("/futures/orders/cancel"):
                return True, {"status": "cancelled"}
            if endpoint.endswith("/futures/positions/transactions"):
                return True, [
                    {"stage": "default", "amount": 0.0, "fee_amount": 0.55, "settlement_amount": -0.55},
                    {"stage": "Exit", "amount": 2.95, "fee_amount": 0.55, "settlement_amount": 2.40},
                ]
            return False, {}

        fut = coindcx_gateway.CoinDCXFuturesAdapter("k", "s", user_id=self.uid)
        with patch.object(coindcx_gateway, "_request", side_effect=fake_req):
            ok_o, orders = fut.get_orders()
            self.assertTrue(ok_o)
            self.assertEqual(len(orders), 2)
            ok_c, _ = fut.cancel_order("ord_buy")
            self.assertTrue(ok_c)
            settle = fut.get_position_settlement("pos_uuid_1")
            self.assertIsNotNone(settle)
            self.assertAlmostEqual(settle["fee_usd"], 1.10, places=2)
            self.assertAlmostEqual(settle["net_pnl"], 1.85, places=2)

    def test_2_online_rejected_order_is_never_faked_as_autonomous_fill(self):
        def fake_reject(endpoint, method="GET", body=None, **kw):
            if "data/instrument" in endpoint:
                return True, {"instrument": {"max_leverage_long": 100, "quantity_increment": 0.001, "min_quantity": 0.001}}
            if endpoint.endswith("/futures/wallets"):
                return True, [{"currency_short_name": "USDT", "balance": "32.12", "locked_balance": "0.0"}]
            if endpoint.endswith("/futures/orders/create"):
                return False, {"code": 422, "message": "Quantity precision invalid / divisible by step"}
            return True, {"ok": 1}

        fut = coindcx_gateway.CoinDCXFuturesAdapter("k", "s", user_id=self.uid, is_offline=False)
        with patch.object(coindcx_gateway, "_request", side_effect=fake_reject):
            ok, res = fut.place_futures_order("BTCUSDT", "buy", 0.01, leverage=100.0, price=80000.0)
            self.assertFalse(ok)
            self.assertFalse(bool((res or {}).get("autonomous_adopted")))

    def test_3_fee_safe_live_tp_blocks_sub_fee_scalp_close(self):
        bot = Bot(PriceFeed())
        # Margin $10 at 100x = $1,000 notional -> est_fee = $1.40; +$1.00 gross must NOT close yet!
        pos = {"margin": 10.0, "leverage": 100.0, "is_live": 1, "target_pct": 0.50, "stop_pct": 0.30}
        sig_low = bot._evaluate_bot_exit_signal(pos, 80080.0, raw_pnl=1.00, move_pct=0.10, peak_cash=1.00, peak_pct=0.10, time_held=5.0)
        self.assertIsNone(sig_low)

        # At +$2.00 gross (strictly above $1.40 fee + net profit margin), TP fires!
        sig_ok = bot._evaluate_bot_exit_signal(pos, 80160.0, raw_pnl=2.00, move_pct=0.20, peak_cash=2.00, peak_pct=0.20, time_held=5.0)
        self.assertIsNotNone(sig_ok)
        self.assertIn("SCALP_TARGET", sig_ok)

    def test_4_live_close_settles_exchange_pnl_and_preserves_initial_capital(self):
        now = time.time()
        pid = write(
            """INSERT INTO positions(
                 user_id, symbol, source, side, qty, entry_price, margin,
                 target_pct, stop_pct, status, current_price, unrealized_pnl,
                 opened_at, is_live, leverage, magic_id
               ) VALUES(?, 'BTCUSDT', 'COINDCX LIVE', 'LONG', 0.01, 80000.0, 8.0, 0.5, 0.3, 'OPEN', 80320.0, 3.20, ?, 1, 100.0, 'pos_uuid_99')""",
            (self.uid, now - 10.0),
        )
        pos_row = query_one("SELECT * FROM positions WHERE id=?", (pid,))

        class _FakeFut:
            is_offline = False

            def get_positions(self):
                return True, [{"id": "pos_uuid_99", "pair": "B-BTC_USDT", "active_pos": 0.01}]

            def find_open_position(self, sym):
                return {"id": "pos_uuid_99", "pair": "B-BTC_USDT", "active_pos": 0.01}

            def to_futures_pair(self, sym):
                return "B-BTC_USDT"

            def exit_position_by_id(self, pid_arg):
                return True, {"id": "exit_ord_99"}

            def wait_for_position_flat(self, sym, pos_id="", timeout_sec=2.0):
                return True, None

            def get_position_settlement(self, pos_id):
                return {"net_pnl": 2.15, "fee_usd": 1.05, "gross_pnl": 3.20, "tx_count": 2}

            def get_orders(self):
                return True, [{"id": "tp_ord_1", "pair": "B-BTC_USDT", "status": "untriggered"}]

            def cancel_order(self, oid):
                return True, {"cancelled": oid}

        class _FakeClient:
            is_offline = False

            def __init__(self):
                self.futures = _FakeFut()
                self.cancelled_all = False

            def invalidate_balance_cache(self):
                pass

            def get_balances(self, force=False):
                return True, {
                    "total_portfolio_usd": 34.27,
                    "total_portfolio_inr": 3084.3,
                    "usdt_free": 34.27,
                    "usdt_inr_rate": 90.0,
                    "futures_wallets": [{"currency": "USDT", "free": 34.27, "locked": 0.0, "total": 34.27}],
                }

        fake_client = _FakeClient()
        bot = Bot(PriceFeed())
        with patch.object(coindcx_gateway, "get_user_coindcx_client", return_value=fake_client), \
             patch.object(CoinDCXExecutionAdapter, "_client", return_value=fake_client):
            net = bot.close(pos_row, 80320.0, "SCALP_TARGET_$1_HIT")
            self.assertAlmostEqual(net, 2.15, places=2)

        closed_pos = query_one("SELECT status, realized_pnl, fee_usd FROM positions WHERE id=?", (pid,))
        self.assertEqual(closed_pos["status"], "CLOSED")
        self.assertAlmostEqual(closed_pos["realized_pnl"], 2.15, places=2)
        self.assertAlmostEqual(closed_pos["fee_usd"], 1.05, places=2)

        bc = query_one("SELECT live_balance, free_margin FROM broker_connections WHERE user_id=?", (self.uid,))
        self.assertAlmostEqual(bc["live_balance"], 34.27, places=2)
        self.assertAlmostEqual(bc["free_margin"], 34.27, places=2)

        # portfolio() must show TOTAL BALANCE=$34.27 while Initial Capital remains $32.12 (+2.15 gain!)
        pf = backend_app.portfolio(self.uid)
        self.assertAlmostEqual(pf["goal"]["starting_balance"], 32.12, places=2)
        self.assertAlmostEqual(pf["goal"]["current_balance"], 34.27, places=2)
        self.assertAlmostEqual(pf["goal"]["gain"], 2.15, places=2)
        self.assertGreater(pf["goal"]["progress_pct"], 0.0)

    def test_5_real_mode_entry_isolated_from_paper_losses_and_micro_price_precision(self):
        from ai_committee import AICommitteeOrchestrator
        now = time.time()
        # Simulate 5 consecutive PAPER losses (is_live=0) — must NEVER block LIVE CoinDCX 100x entry!
        for idx in range(5):
            write(
                "INSERT INTO positions(user_id, symbol, source, side, qty, entry_price, margin, target_pct, stop_pct, status, current_price, realized_pnl, opened_at, closed_at, is_live, leverage) "
                "VALUES(?, 'BTCUSDT', 'BOT', 'LONG', 0.01, 80000.0, 10.0, 0.5, 0.3, 'CLOSED', 79800.0, -2.0, ?, ?, 0, 20.0)",
                (self.uid, now - 60 - idx, now - 10 - idx),
            )
        candles = [
            {"t": int(now) - (30 - i) * 60, "o": 0.0041 + i * 0.00001, "h": 0.00415 + i * 0.00001, "l": 0.00409 + i * 0.00001, "c": 0.00412 + i * 0.00001, "v": 2000.0}
            for i in range(30)
        ]
        res = AICommitteeOrchestrator.evaluate_candidate(
            symbol="WAXPUSDT",
            user_id=self.uid,
            candles=candles,
            quote_data={"price": 0.00442, "change_pct": 2.1, "volume": 5_000_000.0},
            equity_usd=17.40,
            requested_leverage=100.0,
            is_live=True,
            persist=False,
            intended_side="LONG",
        )
        self.assertTrue(res["approved"], res)
        self.assertEqual(res["direction"], "LONG")

    def test_6_futures_leverage_tier_fallback_retries_cleanly(self):
        seen_levs = []

        def fake_req(endpoint, method="GET", body=None, **kw):
            if "data/instrument" in endpoint:
                return True, {
                    "instrument": {
                        "max_leverage_long": 25,
                        "dynamic_position_leverage_details": {"100": {}, "50": {}, "25": {}},
                        "quantity_increment": 1,
                        "min_quantity": 10,
                    }
                }
            if endpoint.endswith("/futures/wallets"):
                return True, [{"currency_short_name": "USDT", "balance": "17.40", "locked_balance": "0.0"}]
            if endpoint.endswith("/futures/orders/create"):
                lev_sent = (body or {}).get("order", {}).get("leverage")
                seen_levs.append(lev_sent)
                if int(lev_sent) > 25:
                    return False, {"code": 422, "message": "Max allowed leverage for this order is 25x"}
                return True, [{"id": "ord_fb_25x", "status": "filled", "avg_price": 0.5, "total_quantity": 200, "leverage": 25}]
            return True, {"ok": 1}

        fut = coindcx_gateway.CoinDCXFuturesAdapter("k", "s", user_id=self.uid, is_offline=False)
        with patch.object(coindcx_gateway, "_request", side_effect=fake_req):
            ok, res = fut.place_futures_order("DOGEUSDT", "buy", 500, leverage=100.0, price=0.5)
            self.assertTrue(ok)
            self.assertEqual(seen_levs, [100, 25])
            self.assertEqual(float(res["leverage"]), 25.0)


if __name__ == "__main__":
    unittest.main()
