"""Tests for unified SMC + DNA + All CoinDCX Indicators, Alpha/Beta/Gamma Committee, and sec-off profit auto-close."""
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test_smc_dna_sec_off.db"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from database import init_schema, write
from quantum_engine import SMCDNAEngine
from ai_committee import AICommitteeOrchestrator
from prediction_engine import predict_and_advise
from bot_engine import Bot
from price_feed import PriceFeed
from strategy_engine import StrategyEngine


def _bsl_sweep_candles():
    now = int(time.time()) - 40 * 60
    cs = []
    px = 44.30
    for i in range(36):
        op = px
        cl = px + 0.012
        cs.append({"t": now + i * 60, "o": op, "h": cl + 0.01, "l": op - 0.01, "c": cl, "v": 1000.0 + i * 25})
        px = cl
    # Sweep above prior swing high then reject cleanly back down
    prior_hi = max(k["h"] for k in cs)
    cs.append({"t": now + 36 * 60, "o": px, "h": prior_hi + 0.05, "l": px - 0.02, "c": px - 0.04, "v": 4200.0})
    px = cs[-1]["c"]
    for i in range(3):
        op = px
        cl = op - 0.05
        cs.append({"t": now + (37 + i) * 60, "o": op, "h": op + 0.005, "l": cl - 0.01, "c": cl, "v": 2500.0})
        px = cl
    return cs


def _bull_trend_candles():
    now = int(time.time()) - 40 * 60
    cs = []
    px = 100.0
    for i in range(40):
        op = px
        cl = op + 0.35
        cs.append({"t": now + i * 60, "o": op, "h": cl + 0.12, "l": op - 0.08, "c": cl, "v": 1500.0 + i * 30})
        px = cl
    return cs


class SMCDNACommitteeSecOffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_schema()

    def setUp(self):
        now = time.time()
        self.uid = write(
            "INSERT INTO users(email, name, pw_salt, pw_hash, bot_enabled, bot_leverage, created_at) VALUES(?,?,?,?,?,?,?)",
            (f"smcdna_{now}@araabot.in", "SmcUser", "s", "h", 1, 100.0, now),
        )
        write(
            "INSERT INTO wallets(user_id, deposit_balance, starting_balance, target_amount, profit_balance, locked_balance) VALUES(?,?,?,?,?,?)",
            (self.uid, 100.0, 100.0, 150.0, 0.0, 0.0),
        )
        write(
            """INSERT INTO broker_connections(
                 user_id, broker_name, api_key_masked, status, is_live_active,
                 live_balance, live_equity, free_margin, currency, connected_at, last_synced_at
               ) VALUES(?, 'COINDCX', '0505...72db', 'CONNECTED', 1, 100.0, 100.0, 100.0, 'USDT', ?, ?)""",
            (self.uid, now, now),
        )

    def test_1_smcdna_computes_all_indicators_entry_and_bsl_sweep_exit(self):
        cs = _bsl_sweep_candles()
        res = SMCDNAEngine.analyze_candles("LTCUSDT", cs, "1m", cs[-1]["c"])
        self.assertIn("all_indicators", res)
        self.assertIn("entry_signal", res)
        self.assertIn("exit_signal", res)

        ind = res["all_indicators"]
        for key in ("ema9", "ema21", "ema50", "ema200", "rsi14", "macd_hist", "bb_pct", "supertrend", "vwap", "atr14", "obv_slope"):
            self.assertIn(key, ind)

        self.assertTrue(res["liquidity"]["bsl"]["swept"])
        self.assertTrue(res["exit_signal"]["close_long"])
        self.assertTrue(len(res["exit_signal"]["reason_long"]) > 0)

    def test_2_alpha_beta_gamma_committee_uses_smc_dna_and_all_indicators(self):
        bull_cs = _bull_trend_candles()
        res_ok = AICommitteeOrchestrator.evaluate_candidate(
            "SOLUSDT",
            user_id=self.uid,
            candles=bull_cs,
            quote_data={"price": bull_cs[-1]["c"], "change_pct": 2.4, "volume": 5000000.0},
            equity_usd=100.0,
            requested_leverage=50.0,
            is_live=True,
            persist=False,
            intended_side="LONG",
        )
        self.assertIn("smc_dna", res_ok)
        self.assertIn("all_indicators", res_ok)
        self.assertIn("supertrend", res_ok["beta"]["indicators"])
        self.assertIn("dna_similarity_pct", res_ok["alpha"]["metrics"])
        self.assertTrue(res_ok["approved"], res_ok)

        # BSL sweep trap blocks LONG entry cleanly
        trap_cs = _bsl_sweep_candles()
        res_trap = AICommitteeOrchestrator.evaluate_candidate(
            "LTCUSDT",
            user_id=self.uid,
            candles=trap_cs,
            quote_data={"price": trap_cs[-1]["c"], "change_pct": -0.5, "volume": 3000000.0},
            equity_usd=100.0,
            requested_leverage=50.0,
            is_live=True,
            persist=False,
            intended_side="LONG",
        )
        self.assertFalse(res_trap["approved"])

    def test_3_prediction_engine_integrates_smc_dna_and_auto_close_plan(self):
        cs = _bull_trend_candles()
        pred = predict_and_advise("BTCUSDT", "CRYPTO", cs, timeframe="15m")
        self.assertIn("smc_dna", pred)
        self.assertIn("auto_close_plan", pred)
        self.assertIn("supertrend", pred["indicators"])
        self.assertIn("bsl", pred["indicators"])
        self.assertIn("ssl", pred["indicators"])
        self.assertEqual(pred["prediction"], "UP")

    def test_4_bot_sec_off_immediate_profit_and_smc_dna_auto_close(self):
        bot = Bot(PriceFeed())
        pos = {
            "id": 901,
            "symbol": "LTCUSDT",
            "side": "LONG",
            "margin": 6.00,
            "leverage": 30.0,
            "target_pct": 0.60,
            "stop_pct": 0.30,
            "is_live": 1,
        }
        # Even at time_held = 0.1s (sec off!), hitting $1+ profit closes immediately
        r_tp = bot._evaluate_bot_exit_signal(pos, price=44.80, raw_pnl=1.08, move_pct=0.60, peak_cash=1.08, peak_pct=0.60, time_held=0.1)
        self.assertIsNotNone(r_tp)

        # Even at time_held = 0.2s, SMC+DNA BSL sweep with fee-safe net profit ($0.45 > est_fee $0.252) closes immediately
        fake_smc = {"exit_signal": {"close_long": True, "reason_long": "BSL_LIQUIDITY_SWEPT", "close_short": False, "reason_short": ""}}
        with patch.object(bot, "_smc_dna_snapshot", return_value=fake_smc):
            r_smc = bot._evaluate_bot_exit_signal(pos, price=44.74, raw_pnl=0.45, move_pct=0.25, peak_cash=0.45, peak_pct=0.25, time_held=0.2)
            self.assertIsNotNone(r_smc)
            self.assertIn("SMC_DNA_AUTO_CLOSE", r_smc)

            # Still blocks premature exit when gross profit is below CoinDCX taker fees ($0.10 < $0.252)
            r_sub = bot._evaluate_bot_exit_signal(pos, price=44.66, raw_pnl=0.10, move_pct=0.055, peak_cash=0.10, peak_pct=0.055, time_held=0.2)
            self.assertIsNone(r_sub)

    def test_5_strategy_engine_v2_smart_exit_honors_smc_dna_and_fee_floor(self):
        pos = {
            "id": 902,
            "user_id": self.uid,
            "symbol": "LTCUSDT",
            "side": "LONG",
            "entry_price": 44.50,
            "current_sl_price": 44.36,
            "stop_pct": 0.30,
            "target_pct": 0.80,
            "qty": 4.0,
            "margin": 6.0,
            "leverage": 30.0,
            "partial_tp_booked": 0,
            "is_live": 1,
        }
        fake_smc = {"exit_signal": {"close_long": True, "reason_long": "BEAR_OB_SUPPLY_HIT", "close_short": False, "reason_short": ""}}
        # Fee-covered move (+$0.80 > $0.252 est_fee) exits immediately via SMC_DNA_AUTO_CLOSE
        dec = StrategyEngine.evaluate_v2_smart_profit_and_exit(
            self.uid, pos, current_price=44.70, smc_dna=fake_smc
        )
        self.assertEqual(dec["action"], "FULL_EXIT")
        self.assertIn("SMC_DNA_AUTO_CLOSE", dec["exit_reason"])


if __name__ == "__main__":
    unittest.main()
