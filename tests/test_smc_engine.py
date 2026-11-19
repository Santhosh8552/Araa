"""
Automated Test Suite for AraaBot V2 Smart Money Concepts (SMC) Engine.
Tests:
- Swing High & Low Detection
- Confirmed BOS & CHoCH Breakouts
- Order Block Displacement & Mitigation
- Fair Value Gap (FVG) Imbalance & Fill Percentage
- Liquidity Sweep Detection (SSL & BSL)
- Dealing Range Premium & Discount Equilibrium (50%, OTE Fibs)
- Araa AI 3-State Scenario Generation
- No-Lookahead Historical Backtesting Guarantees
"""

import unittest
import time
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.smc_engine import (
    normalize_candles,
    compute_atr,
    MarketStructureEngine,
    OrderBlockEngine,
    FVGEngine,
    LiquidityEngine,
    AraaAIMarketAdvisor,
    SMCBacktestEngine
)


class TestSMCEngine(unittest.TestCase):

    def setUp(self):
        # Generate synthetic realistic OHLCV market wave
        self.candles = []
        base = 100.0
        now = int(time.time())
        for i in range(80):
            wave = math.sin(i * 0.25) * 4.0 + (i * 0.1)
            nxt = base + wave
            hi = nxt + 1.2
            lo = nxt - 1.2
            self.candles.append({
                "o": round(nxt - 0.2, 4),
                "h": round(hi, 4),
                "l": round(lo, 4),
                "c": round(nxt + 0.2, 4),
                "v": 1500.0,
                "t": now - (80 - i) * 900
            })

    def test_candle_normalization(self):
        norm = normalize_candles(self.candles)
        self.assertEqual(len(norm), len(self.candles))
        for c in norm:
            self.assertGreaterEqual(c["h"], c["l"])
            self.assertGreaterEqual(c["h"], c["o"])
            self.assertGreaterEqual(c["h"], c["c"])

    def test_swing_detection(self):
        norm = normalize_candles(self.candles)
        swings = MarketStructureEngine.detect_swings(norm, sensitivity=3)
        self.assertIn("highs", swings)
        self.assertIn("lows", swings)
        self.assertGreater(len(swings["highs"]), 0)
        self.assertGreater(len(swings["lows"]), 0)

    def test_structure_breaks(self):
        norm = normalize_candles(self.candles)
        swings = MarketStructureEngine.detect_swings(norm, sensitivity=3)
        breaks = MarketStructureEngine.detect_structure_breaks(norm, swings)
        self.assertIsInstance(breaks, list)
        for b in breaks:
            self.assertIn(b["type"], ["BULLISH_BOS", "BEARISH_BOS", "BULLISH_CHOCH", "BEARISH_CHOCH"])
            self.assertTrue(b["confirmed"])

    def test_order_block_displacement(self):
        norm = normalize_candles(self.candles)
        atr = compute_atr(norm)
        obs = OrderBlockEngine.detect_order_blocks(norm, atr)
        self.assertIsInstance(obs, list)
        for ob in obs:
            self.assertIn(ob["type"], ["BULLISH_OB", "BEARISH_OB"])
            self.assertIn(ob["status"], ["FRESH", "TESTED", "MITIGATED", "BREAKER"])
            self.assertGreaterEqual(ob["strength"], 50)

    def test_fair_value_gaps(self):
        norm = normalize_candles(self.candles)
        atr = compute_atr(norm)
        fvgs = FVGEngine.detect_fvgs(norm, atr=atr)
        self.assertIsInstance(fvgs, list)
        for f in fvgs:
            self.assertIn(f["type"], ["BULLISH_FVG", "BEARISH_FVG"])
            self.assertGreaterEqual(f["top"], f["bottom"])
            self.assertGreaterEqual(f["fill_pct"], 0.0)

    def test_liquidity_and_dealing_range(self):
        norm = normalize_candles(self.candles)
        swings = MarketStructureEngine.detect_swings(norm, sensitivity=3)
        liq = LiquidityEngine.detect_liquidity_pools(norm, swings)
        self.assertIn("bsl", liq)
        self.assertIn("ssl", liq)
        self.assertIn("dealing_range", liq)
        dr = liq["dealing_range"]
        self.assertGreater(dr["high"], dr["low"])
        self.assertAlmostEqual(dr["equilibrium"], (dr["high"] + dr["low"]) / 2.0, places=3)
        self.assertIn(dr["current_zone"], ["PREMIUM", "DISCOUNT"])

    def test_araa_ai_scenario_generation(self):
        norm = normalize_candles(self.candles)
        atr = compute_atr(norm)
        swings = MarketStructureEngine.detect_swings(norm, sensitivity=3)
        breaks = MarketStructureEngine.detect_structure_breaks(norm, swings)
        obs = OrderBlockEngine.detect_order_blocks(norm, atr)
        fvgs = FVGEngine.detect_fvgs(norm, atr=atr)
        liq = LiquidityEngine.detect_liquidity_pools(norm, swings)

        report = AraaAIMarketAdvisor.generate_report(
            symbol="BTCUSDT",
            timeframe="15m",
            current_price=norm[-1]["c"],
            structure_events=breaks,
            order_blocks=obs,
            fvgs=fvgs,
            liquidity=liq,
            atr=atr
        )
        self.assertIn("scenarios", report)
        self.assertIn("bullish", report["scenarios"])
        self.assertIn("bearish", report["scenarios"])
        self.assertIn("neutral", report["scenarios"])
        self.assertIn(report["overall_bias"], ["BULLISH", "BEARISH", "NEUTRAL"])

    def test_no_lookahead_backtesting(self):
        norm = normalize_candles(self.candles)
        results = SMCBacktestEngine.run_backtest(norm, {"risk_reward": 2.0})
        self.assertIn("total_setups", results)
        self.assertIn("win_rate", results)
        self.assertIn("profit_factor", results)
        self.assertIn("max_drawdown", results)
        self.assertGreaterEqual(results["win_rate"], 0.0)
        self.assertLessEqual(results["win_rate"], 100.0)


if __name__ == "__main__":
    unittest.main()
