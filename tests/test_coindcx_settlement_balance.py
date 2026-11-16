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

    def test_7_settlement_ignores_entry_margin_debit_and_unposted_exit(self):
        # 1) Unposted exit: ONLY "default" margin debit row present -> MUST return None (never -margin!)
        def only_default_req(endpoint, method="GET", body=None, **kw):
            return True, [{"stage": "default", "amount": -6.11, "fee_amount": 0.09, "settlement_amount": -6.20}]

        fut = coindcx_gateway.CoinDCXFuturesAdapter("k", "s", user_id=self.uid, is_offline=False)
        with patch.object(coindcx_gateway, "_request", side_effect=only_default_req):
            self.assertIsNone(fut.get_position_settlement("pos_cookie_1"))

        # 2) Both default margin debit (-6.11) AND Exit (+0.35 gross, 0.09 fee) -> ignores -6.11!
        def default_plus_exit_req(endpoint, method="GET", body=None, **kw):
            return True, [
                {"stage": "default", "amount": -6.11, "fee_amount": 0.09, "settlement_amount": -6.20},
                {"stage": "Exit", "amount": 0.35, "fee_amount": 0.09, "settlement_amount": 0.26},
            ]

        with patch.object(coindcx_gateway, "_request", side_effect=default_plus_exit_req):
            settle = fut.get_position_settlement("pos_cookie_1")
            self.assertIsNotNone(settle)
            self.assertAlmostEqual(settle["net_pnl"], 0.17, places=2)
            self.assertAlmostEqual(settle["fee_usd"], 0.18, places=2)

        # 3) INR-margined transaction rows are converted to USDT instead of treated 1:1 as USD
        def inr_rows_req(endpoint, method="GET", body=None, **kw):
            return True, [
                {"stage": "default", "margin_currency_short_name": "INR", "amount": -550.0, "fee_amount": 9.0, "settlement_amount": -559.0},
                {"stage": "Exit", "margin_currency_short_name": "INR", "amount": 270.0, "fee_amount": 9.0, "settlement_amount": 261.0},
            ]

        with patch.object(coindcx_gateway, "_request", side_effect=inr_rows_req):
            settle_inr = fut.get_position_settlement("pos_inr_1", usdt_inr_rate=90.0)
            self.assertIsNotNone(settle_inr)
            self.assertAlmostEqual(settle_inr["net_pnl"], 2.80, places=2)

    def test_8_profitable_manual_close_never_books_minus_100pct_margin_loss(self):
        now = time.time()
        qty_cookie = round((6.11 * 30.0) / 0.00833, 4)
        pid = write(
            """INSERT INTO positions(
                 user_id, symbol, source, side, qty, entry_price, margin,
                 target_pct, stop_pct, status, current_price, unrealized_pnl,
                 opened_at, is_live, leverage, magic_id
               ) VALUES(?, 'COOKIEUSDT', 'COINDCX', 'LONG', ?, 0.00833, 6.11, 0.5, 0.3, 'OPEN', 0.008334, 0.09, ?, 1, 30.0, 'pos_cookie_live')""",
            (self.uid, qty_cookie, now - 65.0),
        )
        pos_row = query_one("SELECT * FROM positions WHERE id=?", (pid,))
        bot = Bot(PriceFeed())

        # Case A: Exchange closes via close_real_order and ledger has anomalous -margin (-6.11) on a +0.05% exit
        with patch.object(
            real_broker,
            "close_real_order",
            return_value={
                "mode": "LIVE_REAL",
                "closed": True,
                "exchange": "COINDCX",
                "market_type": "FUTURES",
                "exchange_settled": True,
                "realized_pnl": -6.11,
                "fee_usd": 0.18,
                "liquidated": False,
            },
        ), patch.object(coindcx_gateway, "get_user_coindcx_client", return_value=None):
            net = bot.close(pos_row, 0.008334, "MANUAL_CLOSE")
            self.assertGreater(net, -0.50)
            self.assertNotAlmostEqual(net, -6.11, places=1)

    def test_9_auto_scalping_live_fee_gate_and_full_exit_via_close_real_order(self):
        from strategy_engine import StrategyEngine

        # Sub-fee live move must NOT trigger TAKE_PROFIT premature loss-making exit
        live_pos = {
            "id": 888,
            "user_id": self.uid,
            "symbol": "BTCUSDT",
            "side": "LONG",
            "entry_price": 80000.0,
            "current_sl_price": 79760.0,
            "stop_pct": 0.30,
            "target_pct": 0.15,
            "qty": 0.0125,  # $1000 notional -> margin=$10 @ 100x -> est_fee=$1.40
            "margin": 10.0,
            "leverage": 100.0,
            "partial_tp_booked": 0,
            "is_live": 1,
        }
        # +0.15% = +$1.50 gross on $1000 notional, est_fee=$1.40, min_live_profit=$1.61 -> must NOT close or partial-exit!
        dec_sub = StrategyEngine.evaluate_v2_smart_profit_and_exit(self.uid, live_pos, current_price=80120.0)
        self.assertNotIn(dec_sub["action"], ("FULL_EXIT", "PARTIAL_EXIT"))
        # +0.05% = +$0.50 gross (<0.5R, below fee) -> holds cleanly!
        dec_small = StrategyEngine.evaluate_v2_smart_profit_and_exit(self.uid, live_pos, current_price=80040.0)
        self.assertEqual(dec_small["action"], "HOLD")
        # Stop-loss still fires immediately regardless of fee floor
        dec_sl = StrategyEngine.evaluate_v2_smart_profit_and_exit(self.uid, live_pos, current_price=79750.0)
        self.assertEqual(dec_sl["action"], "FULL_EXIT")
        self.assertEqual(dec_sl["exit_reason"], "STOP_LOSS")

        # Full live auto-exit must route via close_real_order (not submit_order) and cancel protections
        now = time.time()
        pid = write(
            """INSERT INTO positions(
                 user_id, symbol, source, side, qty, entry_price, margin,
                 target_pct, stop_pct, status, current_price, unrealized_pnl,
                 opened_at, is_live, leverage, magic_id
               ) VALUES(?, 'BTCUSDT', 'COINDCX_ARAA_SCALP', 'LONG', 0.01, 80000.0, 8.0, 0.6, 0.3, 'OPEN', 80480.0, 4.80, ?, 1, 100.0, 'pos_scalp_uuid')""",
            (self.uid, now - 30.0),
        )
        close_calls = []

        def fake_close_real(**kw):
            close_calls.append(kw)
            return {
                "mode": "LIVE_REAL",
                "closed": True,
                "exchange": "COINDCX",
                "market_type": "FUTURES",
                "order_id": "ord_exit_1",
                "exchange_settled": True,
                "realized_pnl": 3.68,
                "fee_usd": 1.12,
                "liquidated": False,
            }

        with patch.object(real_broker, "close_real_order", side_effect=fake_close_real), \
             patch.object(CoinDCXExecutionAdapter, "cancel_obsolete_protection") as mock_cancel, \
             patch.object(coindcx_gateway, "get_user_coindcx_client", return_value=None):
            res = StrategyEngine.execute_auto_exit(
                self.uid,
                pid,
                {"action": "FULL_EXIT", "exit_reason": "TAKE_PROFIT", "close_qty": 0.01},
                80480.0,
            )
            self.assertTrue(res["success"], res)
            self.assertEqual(len(close_calls), 1)
            self.assertEqual(close_calls[0]["symbol"], "BTCUSDT")
            self.assertAlmostEqual(res["realized_pnl_usdt"], 3.68, places=2)
            mock_cancel.assert_called_once()

    def test_10_scalp_target_hit_never_books_minus_100pct_from_inr_fee_or_corrupt_liq_flag(self):
        # Exact INJUSDT SHORT scenario from live screenshot: entry=6.6770, exit=6.6640 (+0.19%), margin=$5.30 @ 100x (+$1.03 gross)
        now = time.time()
        qty_inj = round((5.30 * 100.0) / 6.6770, 8)
        pid = write(
            """INSERT INTO positions(
                 user_id, symbol, source, side, qty, entry_price, margin,
                 target_pct, stop_pct, status, current_price, unrealized_pnl,
                 opened_at, is_live, leverage, magic_id
               ) VALUES(?, 'INJUSDT', 'COINDCX LIVE', 'SHORT', ?, 6.6770, 5.30, 0.5, 0.3, 'OPEN', 6.6640, 1.03, ?, 1, 100.0, 'pos_inj_uuid')""",
            (self.uid, qty_inj, now - 243.0),
        )
        pos_row = query_one("SELECT * FROM positions WHERE id=?", (pid,))
        bot = Bot(PriceFeed())

        # Case A: Exchange returned INR-scaled fee_usd (56.2) & -55.17 net inside settlement -> MUST NOT subtract 56.2 USD!
        with patch.object(
            real_broker,
            "close_real_order",
            return_value={
                "mode": "LIVE_REAL",
                "closed": True,
                "exchange": "COINDCX",
                "market_type": "FUTURES",
                "exchange_settled": True,
                "realized_pnl": -55.17,
                "fee_usd": 56.2,
                "liquidated": False,
            },
        ), patch.object(coindcx_gateway, "get_user_coindcx_client", return_value=None):
            net_a = bot.close(dict(pos_row), 6.6640, "SCALP_TARGET_$1_HIT (+$1.03 | +19.5% ROI)")
            self.assertGreater(net_a, 0.0)
            self.assertAlmostEqual(net_a, 0.29, places=2)

        # Reset position OPEN for Case B: spurious liquidated=True with -5.30 on a +$1.03 SCALP_TARGET_$1_HIT close
        write("UPDATE positions SET status='OPEN', realized_pnl=0 WHERE id=?", (pid,))
        pos_row_b = query_one("SELECT * FROM positions WHERE id=?", (pid,))
        with patch.object(
            real_broker,
            "close_real_order",
            return_value={
                "mode": "LIVE_REAL",
                "closed": True,
                "exchange": "COINDCX",
                "market_type": "FUTURES",
                "exchange_settled": True,
                "realized_pnl": -5.30,
                "fee_usd": 0.74,
                "liquidated": True,
            },
        ), patch.object(coindcx_gateway, "get_user_coindcx_client", return_value=None):
            net_b = bot.close(dict(pos_row_b), 6.6640, "SCALP_TARGET_$1_HIT (+$1.03 | +19.5% ROI)")
            self.assertGreater(net_b, 0.0)
            self.assertAlmostEqual(net_b, 0.29, places=2)

        # Also verify get_position_settlement filters mismatched position_id rows and detects currency keys
        fut = coindcx_gateway.CoinDCXFuturesAdapter("k", "s", user_id=self.uid, is_offline=False)
        with patch.object(
            coindcx_gateway,
            "_request",
            return_value=(
                True,
                [
                    {"position_id": "other_pos", "stage": "Exit", "currency": "USDT", "amount": -50.0, "fee_amount": 5.0, "settlement_amount": -55.0},
                    {"position_id": "pos_inj_uuid", "stage": "default", "currency": "INR", "amount": -477.0, "fee_amount": 33.4, "settlement_amount": -510.4},
                    {"position_id": "pos_inj_uuid", "stage": "Exit", "currency": "INR", "amount": 92.7, "fee_amount": 33.4, "settlement_amount": 59.3},
                ],
            ),
        ):
            settle = fut.get_position_settlement("pos_inj_uuid", usdt_inr_rate=90.0)
            self.assertIsNotNone(settle)
            self.assertGreater(settle["net_pnl"], 0.0)
            self.assertAlmostEqual(settle["net_pnl"], round((59.3 - 33.4) / 90.0, 2), places=2)




if __name__ == "__main__":
    unittest.main()
