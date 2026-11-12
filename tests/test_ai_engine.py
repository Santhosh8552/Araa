import os
import sys
import unittest

# Ensure backend directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

# pyrefly: ignore [missing-import]
from gemini_advisor import analyze_trade_opportunity
# pyrefly: ignore [missing-import]
from bot_engine import MODES, MARKET, CATEGORIES

class TestGeminiTradingEngine(unittest.TestCase):
    
    def test_strategy_definitions(self):
        """Verify all 3 requested strategies exist with exact target specifications."""
        # 1. Safe & Conservative
        self.assertIn("CONSERVATIVE", MODES)
        c = MODES["CONSERVATIVE"]
        self.assertEqual(c["min_win_rate"], 78)
        self.assertGreaterEqual(c["max_trades"], 6)
        self.assertEqual(c["profit_target_pct"], "5% - 8%")
        self.assertIn("daily_profit_usd", c)

        # 2. Target Scalping (Gold + Forex)
        self.assertIn("SCALP", MODES)
        s = MODES["SCALP"]
        self.assertEqual(s["min_win_rate"], 75)
        self.assertGreaterEqual(s["max_trades"], 12)
        self.assertEqual(s["profit_target_pct"], "10% - 15%")
        self.assertIn("daily_profit_usd", s)

        # 3. Aggressive High-Momentum
        self.assertIn("AGGRESSIVE", MODES)
        a = MODES["AGGRESSIVE"]
        self.assertEqual(a["min_win_rate"], 70)
        self.assertGreaterEqual(a["max_trades"], 20)
        self.assertEqual(a["profit_target_pct"], "20% - 30%")
        self.assertIn("daily_profit_usd", a)

    def test_conservative_blocks_crypto(self):
        """Safe & Conservative mode must block high-volatility crypto setups."""
        verdict = analyze_trade_opportunity(
            symbol="BTCUSDT",
            category="CRYPTO",
            price=80000.0,
            change_pct=1.5,
            rsi_val=60.0,
            slope_z=1.2,
            direction="LONG",
            technical_conf=0.85,
            mode="CONSERVATIVE"
        )
        self.assertFalse(verdict["approved"], "Conservative mode should block crypto to maintain 78% win consistency.")

    def test_conservative_approves_clean_metals_trend(self):
        """Safe & Conservative mode must approve high-confidence clean metals setups."""
        verdict = analyze_trade_opportunity(
            symbol="XAUUSD",
            category="METALS",
            price=4150.0,
            change_pct=0.8,
            rsi_val=58.0,
            slope_z=2.1,
            direction="LONG",
            technical_conf=0.88,
            mode="CONSERVATIVE"
        )
        self.assertTrue(verdict["approved"])
        self.assertGreaterEqual(verdict["win_probability"], 78)

    def test_scalp_mode_scoring_and_targets(self):
        """Target Scalping mode evaluates gold and forex setups against 75% target."""
        verdict = analyze_trade_opportunity(
            symbol="EURUSD",
            category="FOREX",
            price=1.085,
            change_pct=0.3,
            rsi_val=55.0,
            slope_z=1.8,
            direction="LONG",
            technical_conf=0.82,
            mode="SCALP"
        )
        self.assertTrue(verdict["approved"])
        self.assertGreaterEqual(verdict["win_probability"], 75)

    def test_counter_trend_rejection(self):
        """Engine must reject dangerous counter-trend shorting into heavy pumps."""
        verdict = analyze_trade_opportunity(
            symbol="NVDA",
            category="STOCKS",
            price=120.0,
            change_pct=4.5,   # Heavy pump
            rsi_val=74.0,     # Overbought momentum
            slope_z=3.2,
            direction="SHORT", # Trying to knife-short
            technical_conf=0.65,
            mode="SCALP"
        )
        self.assertFalse(verdict["approved"], "Counter-trend shorts into strong momentum must be rejected.")

    def test_aggressive_momentum_breakout(self):
        """Aggressive mode admits valid high-momentum breakouts across all markets."""
        verdict = analyze_trade_opportunity(
            symbol="SOLUSDT",
            category="CRYPTO",
            price=180.0,
            change_pct=5.2,
            rsi_val=68.0,
            slope_z=2.8,
            direction="LONG",
            technical_conf=0.82,
            mode="AGGRESSIVE"
        )
        self.assertTrue(verdict["approved"])
        self.assertGreaterEqual(verdict["win_probability"], 70)

    def test_market_priorities(self):
        """Metals and Forex must have Priority 1 over general equities."""
        self.assertEqual(MARKET["METALS"]["priority"], 1)
        self.assertEqual(MARKET["FOREX"]["priority"], 1)
        self.assertGreater(MARKET["STOCKS"]["priority"], MARKET["METALS"]["priority"])

if __name__ == "__main__":
    unittest.main()
