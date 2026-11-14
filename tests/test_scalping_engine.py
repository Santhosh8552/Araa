import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test_scalping.db"))

import app as backend_app
from bot_engine import Bot, resolve_scalp_targets
from database import init_schema as init_db, query_one


class TestScalpingEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = backend_app.api.test_client()

    def setUp(self):
        self.bot = Bot.__new__(Bot)
        self.bot._symbol_cooldown = {}

    def test_resolve_scalp_targets_ignores_legacy_default_and_honors_custom_tight(self):
        tp_def, sl_def = resolve_scalp_targets("SCALP", leverage=20.0, tp_override=2.5, sl_override=1.5)
        self.assertLessEqual(tp_def, 0.80)
        self.assertLessEqual(sl_def, 0.45)

        tp_cust, sl_cust = resolve_scalp_targets("SCALP", leverage=20.0, tp_override=0.45, sl_override=0.25)
        self.assertAlmostEqual(tp_cust, 0.45, places=3)
        self.assertAlmostEqual(sl_cust, 0.25, places=3)

        tp_hi, sl_hi = resolve_scalp_targets("PURE_CRYPTO", leverage=100.0)
        self.assertLessEqual(tp_hi, 0.55)
        self.assertGreaterEqual(tp_hi, 0.35)
        self.assertLessEqual(sl_hi, 0.32)

    def test_live_scalp_closes_immediately_on_target_without_120s_wait(self):
        pos = {
            "id": 101,
            "symbol": "SOLUSDT",
            "side": "SHORT",
            "margin": 1.50,
            "leverage": 20.0,
            "target_pct": 0.55,
            "stop_pct": 0.28,
            "is_live": 1,
        }
        # +0.60% move on $1.50 @ 20x -> +$0.18 gross (est_fee $0.033), held only 12s
        reason = self.bot._evaluate_bot_exit_signal(
            pos, price=75.0, raw_pnl=0.18, move_pct=0.60, peak_cash=0.18, peak_pct=0.60, time_held=12.0
        )
        self.assertIsNotNone(reason)
        self.assertIn("STRATEGY_TAKE_PROFIT_HIT", reason)

    def test_live_scalp_profit_shield_and_fee_floor(self):
        pos = {
            "id": 102,
            "symbol": "BTCUSDT",
            "side": "SHORT",
            "margin": 6.00,
            "leverage": 20.0,
            "target_pct": 0.80,
            "stop_pct": 0.35,
            "is_live": 1,
        }
        # Below round-trip CoinDCX fee ($0.132): must NOT exit
        too_small = self.bot._evaluate_bot_exit_signal(
            pos, price=67000.0, raw_pnl=0.05, move_pct=0.04, peak_cash=0.08, peak_pct=0.07, time_held=10.0
        )
        self.assertIsNone(too_small)

        # Peaked at +14% ROI ($0.84), pulls back to net profit shield ($0.255): must lock green win
        shield = self.bot._evaluate_bot_exit_signal(
            pos, price=66850.0, raw_pnl=0.255, move_pct=0.21, peak_cash=0.84, peak_pct=0.70, time_held=12.0
        )
        self.assertIsNotNone(shield)
        self.assertTrue("PROFIT_SHIELD" in shield or "TRAILING_PROFIT_LOCKED" in shield or "BREAKEVEN" in shield)

    def test_profit_only_real_mode_never_auto_closes_red_position(self):
        pos = {
            "id": 103,
            "symbol": "ETHUSDT",
            "side": "LONG",
            "margin": 6.00,
            "leverage": 20.0,
            "target_pct": 0.60,
            "stop_pct": 0.30,
            "is_live": 1,
        }
        reason = self.bot._evaluate_bot_exit_signal(
            pos, price=1850.0, raw_pnl=-1.20, move_pct=-1.00, peak_cash=0.02, peak_pct=0.02, time_held=120.0
        )
        self.assertIsNone(reason)

    def test_bot_config_toggle_preserves_saved_scalp_tp_sl(self):
        email = f"scalptest_{int(time.time() * 1000)}@araabot.in"
        res = self.client.post("/api/auth/signup", json={"name": "ScalpTester", "email": email, "password": "Password123!"})
        self.assertEqual(res.status_code, 200)
        token = res.get_json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        save_res = self.client.post(
            "/api/bot/config",
            headers=headers,
            json={
                "enabled": True,
                "mode": "SCALP",
                "max_positions": 5,
                "risk_pct": 2.0,
                "leverage": 20,
                "take_profit_pct": 0.55,
                "stop_loss_pct": 0.28,
            },
        )
        self.assertEqual(save_res.status_code, 200)
        uid = save_res.get_json()["user"]["id"]

        # Toggle from topbar switch (omits take_profit_pct and stop_loss_pct)
        toggle_res = self.client.post(
            "/api/bot/config",
            headers=headers,
            json={"enabled": True, "mode": "SCALP", "max_positions": 5, "risk_pct": 2.0, "leverage": 20},
        )
        self.assertEqual(toggle_res.status_code, 200)
        rbc = query_one("SELECT take_profit_pct, stop_loss_pct FROM real_bot_configs WHERE user_id=?", (uid,))
        self.assertAlmostEqual(float(rbc["take_profit_pct"]), 0.55, places=2)
        self.assertAlmostEqual(float(rbc["stop_loss_pct"]), 0.28, places=2)

    def test_analyse_blocks_positive_slope_short_and_overbought_long(self):
        class _FakeFeed:
            def __init__(self, ticks_map, candles_map):
                self._ticks = ticks_map
                self._candles = candles_map

            def ticks(self, sym, n=40):
                return self._ticks.get(sym, [])[-n:]

            def candles(self, sym, interval="1m", limit=30):
                return self._candles.get(sym, [])[-limit:]

            def quote(self, sym):
                return None

        base_t = 1794000000
        # Rising ticks (positive slope_z) -> SHORT must be rejected
        up_ticks = [1.000 + i * 0.002 for i in range(30)]
        bear_candles = [{"t": base_t + i * 60, "o": 1.05, "h": 1.05, "l": 1.04, "c": 1.045, "v": 100} for i in range(25)]
        bot = Bot.__new__(Bot)
        bot.feed = _FakeFeed({"XRPUSDT": up_ticks}, {"XRPUSDT": bear_candles})
        bot._trainer_state = {}
        bot._leader_impulse = {}
        row_short = {
            "category": "CRYPTO",
            "price": up_ticks[-1],
            "high": 1.10,
            "low": 0.99,
            "change_pct": -2.5,
            "volume": 50_000_000,
            "tv_recommend": -0.20,
            "tv_rsi": 72.0,
        }
        self.assertIsNone(bot.analyse("XRPUSDT", row_short, mode="SCALP"))

        # Extreme RSI >= 78 blowoff spike -> LONG must be rejected
        up_candles = [{"t": base_t + i * 60, "o": 1.0 + i * 0.01, "h": 1.02 + i * 0.01, "l": 1.0 + i * 0.01, "c": 1.015 + i * 0.01, "v": 100} for i in range(25)]
        bot.feed = _FakeFeed({"SOPHUSDT": up_ticks}, {"SOPHUSDT": up_candles})
        row_long = {
            "category": "CRYPTO",
            "price": up_ticks[-1],
            "high": up_ticks[-1],
            "low": 0.95,
            "change_pct": 12.0,
            "volume": 50_000_000,
            "tv_recommend": 0.50,
            "tv_rsi": 91.0,
        }
        self.assertIsNone(bot.analyse("SOPHUSDT", row_long, mode="SCALP"))

    def test_tradingview_1m_5m_chart_consensus_controls_direction(self):
        class _FakeFeed:
            def __init__(self, ticks_map, candles_map):
                self._ticks = ticks_map
                self._candles = candles_map

            def ticks(self, sym, n=40):
                return self._ticks.get(sym, [])[-n:]

            def candles(self, sym, interval="1m", limit=30):
                return self._candles.get(sym, [])[-limit:]

            def quote(self, sym):
                return None

        base_t = 1794000000
        up_ticks = [83.00 + i * 0.08 for i in range(30)]
        up_candles = [
            {"t": base_t + i * 60, "o": 83.0 + i * 0.06, "h": 83.12 + i * 0.06, "l": 82.98 + i * 0.06, "c": 83.09 + i * 0.06, "v": 1500}
            for i in range(25)
        ]
        bot = Bot.__new__(Bot)
        bot.feed = _FakeFeed({"SOLUSDT": up_ticks}, {"SOLUSDT": up_candles})
        bot._trainer_state = {}
        bot._leader_impulse = {}

        # Even if 24h change is -4.6% (1D negative), when TradingView 1m + 5m are BUY, bot must produce LONG (never SHORT)
        sol_row = {
            "category": "CRYPTO",
            "live": True,
            "price": up_ticks[-1],
            "high": 88.50,
            "low": 81.20,
            "change_pct": -4.60,
            "volume": 120_000_000,
            "tv_rec_1m": 0.42,
            "tv_rec_5m": 0.31,
            "tv_recommend": 0.35,
            "tv_ma_1m": 0.50,
            "tv_ma_5m": 0.38,
            "tv_rsi_1m": 58.5,
            "tv_ema20_1m": up_ticks[-1] - 0.15,
            "tv_ema50_1m": up_ticks[-1] - 0.35,
        }
        setup = bot.analyse("SOLUSDT", sol_row, mode="SCALP")
        self.assertIsNotNone(setup)
        self.assertEqual(setup["side"], "LONG")
        self.assertIn(setup["tv_signal"], ("BUY", "STRONG_BUY"))

        # Conflicting 1m (+0.40 BUY) vs 5m (-0.35 SELL) must be rejected until timeframes align
        conflict_row = dict(sol_row, tv_rec_1m=0.40, tv_rec_5m=-0.35)
        self.assertIsNone(bot.analyse("SOLUSDT", conflict_row, mode="SCALP"))

    def test_no_opposite_trade_from_24h_vwap_when_1m_chart_rises_or_falls(self):
        from price_feed import PriceFeed
        pf = PriceFeed()
        # Case 1: XRPUSDT is -2.94% on 24h (below 24h VWAP), but rising on 1m klines -> must be BUY/LONG, NEVER SHORT
        rising_1m = [
            {"t": 1794000000 + i * 60, "o": 0.9850 + i * 0.0002, "h": 0.9854 + i * 0.0002, "l": 0.9849 + i * 0.0002, "c": 0.9853 + i * 0.0002, "v": 50000}
            for i in range(35)
        ]
        xrp_row = {
            "category": "CRYPTO",
            "live": True,
            "price": rising_1m[-1]["c"],
            "high": 1.0250,
            "low": 0.9810,
            "vwap": 1.0080,
            "change_pct": -2.94,
            "volume": 85_000_000,
        }
        ticks_up = [c["c"] for c in rising_1m]
        pf._compute_live_tv_ratings("XRPUSDT", xrp_row, ticks_up, candles_1m=rising_1m)
        self.assertGreater(xrp_row["tv_rec_1m"], 0.0)
        self.assertGreater(xrp_row["tv_recommend"], 0.0)
        self.assertIn(xrp_row["tv_signal"], ("BUY", "STRONG_BUY"))

        # Case 2: USUALUSDT is +2.70% on 24h (above 24h VWAP), but falling on 1m klines -> must be SELL/SHORT, NEVER LONG
        falling_1m = [
            {"t": 1794000000 + i * 60, "o": 0.01150 - i * 0.000006, "h": 0.01151 - i * 0.000006, "l": 0.01144 - i * 0.000006, "c": 0.01145 - i * 0.000006, "v": 50000}
            for i in range(35)
        ]
        usual_row = {
            "category": "CRYPTO",
            "live": True,
            "price": falling_1m[-1]["c"],
            "high": 0.01180,
            "low": 0.01080,
            "vwap": 0.01105,
            "change_pct": 2.70,
            "volume": 25_000_000,
        }
        ticks_down = [c["c"] for c in falling_1m]
        pf._compute_live_tv_ratings("USUALUSDT", usual_row, ticks_down, candles_1m=falling_1m)
        self.assertLess(usual_row["tv_rec_1m"], 0.0)
        self.assertLess(usual_row["tv_recommend"], 0.0)
        self.assertIn(usual_row["tv_signal"], ("SELL", "STRONG_SELL"))

    def test_non_blocking_candles_and_flat_tick_fallback_opens_entry(self):
        from price_feed import PriceFeed
        pf = PriceFeed()
        pf.prime([{"symbol": "XRPUSDT", "category": "CRYPTO", "ref_price": 0.99}])
        pf.prices["XRPUSDT"].update({
            "live": True,
            "price": 0.9920,
            "high": 1.0100,
            "low": 0.9750,
            "change_pct": -1.5,
            "volume": 95_000_000,
            "tv_rec_1m": 0.45,
            "tv_rec_5m": 0.32,
            "tv_recommend": 0.39,
            "tv_ma_1m": 0.50,
            "tv_ma_5m": 0.35,
            "tv_rsi_1m": 58.0,
            "tv_ema20_1m": 0.9890,
            "tv_ema50_1m": 0.9860,
        })
        # Even if history is a flat 20-tick seed [0.9920]*20, non-blocking candles() + 1m fallback must qualify LONG
        pf.history["XRPUSDT"].clear()
        for _ in range(20):
            pf.history["XRPUSDT"].append(0.9920)
        t0 = time.time()
        cs = pf.candles("XRPUSDT", "1m", 35)
        self.assertLess(time.time() - t0, 0.05)
        self.assertEqual(len(cs), 35)
        bot = Bot(pf)
        setup = bot.analyse("XRPUSDT", dict(pf.prices["XRPUSDT"]), mode="SCALP")
        self.assertIsNotNone(setup)
        self.assertEqual(setup["side"], "LONG")


if __name__ == "__main__":
    unittest.main()
