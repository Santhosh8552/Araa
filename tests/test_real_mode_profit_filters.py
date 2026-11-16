"""Regression tests for CoinDCX Real Mode profitability, spread/liquidity gating, safe leverage cap, and adaptive cooldown."""
import os
import sys
import tempfile
import time
import unittest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test_real_profit_filters.db"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from database import init_schema, write
from bot_engine import Bot
from quantum_engine import SMCDNAEngine


class RealModeProfitFiltersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_schema()

    def setUp(self):
        now = time.time()
        self.uid = write(
            "INSERT INTO users(email, name, pw_salt, pw_hash, bot_enabled, bot_leverage, created_at) VALUES(?,?,?,?,?,?,?)",
            (f"realprofit_{now}@araabot.in", "RealProfitUser", "s", "h", 1, 100.0, now),
        )
        self.bot = Bot.__new__(Bot)
        self.bot._symbol_cooldown = {}
        self.bot._smc_exit_cache = {}
        self.bot._candle_cache = {}

    def test_1_analyse_exposes_volume_and_spread_for_ranking(self):
        base_t = 1794800000
        up_ticks = [83.00 + i * 0.08 for i in range(30)]
        up_candles = [
            {"t": base_t + i * 60, "o": 83.0 + i * 0.06, "h": 83.12 + i * 0.06, "l": 82.98 + i * 0.06, "c": 83.09 + i * 0.06, "v": 1500}
            for i in range(25)
        ]
        last_px = up_ticks[-1]
        sol_row = {
            "category": "CRYPTO",
            "live": True,
            "price": last_px,
            "bid": round(last_px - 0.01, 4),
            "ask": round(last_px + 0.01, 4),
            "high": 88.50,
            "low": 81.20,
            "change_pct": 1.40,
            "volume": 250_000_000.0,
            "tv_rec_1m": 0.42,
            "tv_rec_5m": 0.31,
            "tv_recommend": 0.35,
            "tv_ma_1m": 0.50,
            "tv_ma_5m": 0.38,
            "tv_rsi_1m": 58.5,
            "tv_ema20_1m": last_px - 0.15,
            "tv_ema50_1m": last_px - 0.35,
        }

        class _FakeFeed:
            def ticks(self, sym, n=40):
                return up_ticks[-n:]

            def candles(self, sym, interval="1m", limit=30):
                return up_candles[-limit:]

            def quote(self, sym):
                return dict(sol_row)

        self.bot.feed = _FakeFeed()
        self.bot._trainer_state = {}
        self.bot._leader_impulse = {}
        out = self.bot.analyse("SOLUSDT", sol_row, mode="SCALP")
        self.assertIsNotNone(out)
        self.assertEqual(out["volume"], 250_000_000.0)
        self.assertIsNotNone(out["spread_pct"])
        self.assertGreater(out["spread_pct"], 0.0)
        self.assertLess(out["spread_pct"], 0.05)

    def test_2_coindcx_spread_liquidity_and_positive_expectancy_filter(self):
        t_map = {
            "COOKIEUSDT": {"market": "COOKIEUSDT", "bid": 0.00830, "ask": 0.00832, "volume": 421_000.0},
            "B-BTC_USDT": {"market": "B-BTC_USDT", "bid": 64670.0, "ask": 64672.0, "volume": 1_240_000_000.0},
            "B-INJ_USDT": {"market": "B-INJ_USDT", "bid": 6.670, "ask": 6.672, "volume": 18_500_000.0},
        }
        # Wide-spread + low-liquidity micro-cap rejected at 35x
        cookie_cand = {"symbol": "COOKIEUSDT", "target_pct": 0.50, "volume": 421_000.0}
        _, c_spr, c_vol = self.bot._cdx_ticker_for_symbol(t_map, cookie_cand)
        ok_cookie, msg_cookie = self.bot._evaluate_coindcx_entry_quality(cookie_cand, c_spr, c_vol, eff_lev_est=35.0)
        self.assertFalse(ok_cookie)
        self.assertIn("Spread", msg_cookie)

        # Low-volume micro-cap even with tight spread rejected under $1.5M floor at 30x
        thin_cand = {"symbol": "COOKIEUSDT", "target_pct": 0.50, "volume": 421_000.0}
        ok_thin, msg_thin = self.bot._evaluate_coindcx_entry_quality(thin_cand, 0.02, 421_000.0, eff_lev_est=30.0)
        self.assertFalse(ok_thin)
        self.assertIn("1.5M", msg_thin)

        # Tight-spread liquid pair passes and scales TP to cover 2.5x (fee+spread)
        btc_cand = {"symbol": "BTCUSDT", "target_pct": 0.30, "volume": 1_240_000_000.0}
        _, b_spr, b_vol = self.bot._cdx_ticker_for_symbol(t_map, btc_cand)
        ok_btc, _ = self.bot._evaluate_coindcx_entry_quality(btc_cand, b_spr, b_vol, eff_lev_est=50.0)
        self.assertTrue(ok_btc)
        self.assertGreaterEqual(btc_cand["target_pct"], 0.45)

    def test_3_high_leverage_exit_floor_prevents_100x_asymmetric_penny_scalp(self):
        self.bot._smc_dna_snapshot = lambda sym, price: None
        pos_100x = {
            "id": 501,
            "symbol": "INJUSDT",
            "side": "SHORT",
            "margin": 5.30,
            "leverage": 100.0,
            "target_pct": 0.50,
            "stop_pct": 0.28,
            "is_live": 1,
        }
        # +$1.03 gross (~$0.29 net after $0.742 CoinDCX RT fee): MUST NOT cut winner prematurely at 100x!
        early = self.bot._evaluate_bot_exit_signal(pos_100x, price=6.664, raw_pnl=1.03, move_pct=0.195, peak_cash=1.03, peak_pct=0.195, time_held=220.0)
        self.assertIsNone(early)

        # +$1.40 gross (~+$0.66 clean net profit after $0.742 fee): triggers SCALP_TARGET_$1_HIT
        good = self.bot._evaluate_bot_exit_signal(pos_100x, price=6.658, raw_pnl=1.40, move_pct=0.264, peak_cash=1.40, peak_pct=0.264, time_held=240.0)
        self.assertIsNotNone(good)
        self.assertIn("SCALP_TARGET_$1_HIT", good)

    def test_4_small_account_safe_leverage_cap_and_consecutive_loss_cooldown(self):
        self.assertEqual(self.bot._cap_live_coindcx_leverage("INJUSDT", 100.0, 30.63), 35.0)
        self.assertEqual(self.bot._cap_live_coindcx_leverage("COOKIEUSDT", 100.0, 30.63), 35.0)
        self.assertEqual(self.bot._cap_live_coindcx_leverage("BTCUSDT", 100.0, 30.63), 50.0)
        self.assertEqual(self.bot._cap_live_coindcx_leverage("BTCUSDT", 100.0, 150.0), 100.0)

        now = time.time()
        # Two consecutive recent real-mode losses on COOKIEUSDT -> 30m cooldown triggers
        for offset in (300.0, 120.0):
            write(
                "INSERT INTO positions(user_id, symbol, source, category, side, entry_price, current_price, qty, margin, leverage, "
                "stop_pct, target_pct, status, is_live, realized_pnl, opened_at, closed_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'CLOSED', 1, ?, ?, ?)",
                (self.uid, "COOKIEUSDT", "BOT", "CRYPTO", "LONG", 0.0083, 0.0082, 1000.0, 5.0, 30.0, 0.3, 0.6, -1.25, now - offset - 60, now - offset),
            )
        # SOLUSDT had an older loss then a recent win -> no cooldown
        write(
            "INSERT INTO positions(user_id, symbol, source, category, side, entry_price, current_price, qty, margin, leverage, "
            "stop_pct, target_pct, status, is_live, realized_pnl, opened_at, closed_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'CLOSED', 1, ?, ?, ?)",
            (self.uid, "SOLUSDT", "BOT", "CRYPTO", "LONG", 71.0, 70.8, 1.0, 5.0, 30.0, 0.3, 0.6, -0.80, now - 400, now - 300),
        )
        write(
            "INSERT INTO positions(user_id, symbol, source, category, side, entry_price, current_price, qty, margin, leverage, "
            "stop_pct, target_pct, status, is_live, realized_pnl, opened_at, closed_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'CLOSED', 1, ?, ?, ?)",
            (self.uid, "SOLUSDT", "BOT", "CRYPTO", "LONG", 71.2, 71.9, 1.0, 5.0, 30.0, 0.3, 0.6, 1.40, now - 180, now - 90),
        )
        cooled = self.bot._live_loss_cooldown_symbols(self.uid, now)
        self.assertIn("COOKIEUSDT", cooled)
        self.assertIn("B-COOKIE_USDT", cooled)
        self.assertNotIn("SOLUSDT", cooled)

    def test_5_smcdna_15m_downtrend_exposes_exact_bear_bias_keys(self):
        base_t = int(time.time()) - 40 * 900
        bear_15m = [
            {"t": base_t + i * 900, "o": 100.0 - i * 0.4, "h": 100.1 - i * 0.4, "l": 99.5 - i * 0.4, "c": 99.6 - i * 0.4, "v": 4000.0 + i * 30}
            for i in range(35)
        ]
        res = SMCDNAEngine.analyze_candles("ETHUSDT", bear_15m, "15m", bear_15m[-1]["c"])
        self.assertEqual(res["all_indicators"]["supertrend"], "BEAR")
        self.assertEqual(res["dna"]["historical_bias"], "BEARISH")


if __name__ == "__main__":
    unittest.main()
