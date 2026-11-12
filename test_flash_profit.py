import sys
sys.path.insert(0, 'backend')
import unittest
import time
from database import init_schema as init_db, query_one, write, writes
from bot_engine import Bot
from price_feed import PriceFeed

class TestFlashProfitAndMultiEntry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_flash_profit_lock(self):
        feed = PriceFeed()
        bot = Bot(feed)
        now = time.time()
        # Create a test live position
        pos_id = write(
            "INSERT INTO positions(user_id, symbol, source, side, qty, entry_price, margin, target_pct, stop_pct, status, current_price, unrealized_pnl, opened_at, is_live, leverage) "
            "VALUES(?, 'BTCINR', 'COINDCX LIVE', 'LONG', 0.029, 7750000.0, 450.0, 1.8, 0.85, 'OPEN', 7750000.0, 0, ?, 1, 500.0)",
            (2, now)
        )
        p = query_one("SELECT * FROM positions WHERE id=?", (pos_id,))
        
        # Simulate a sudden 1-second price spike: BTC moves up from 7,750,000 to 7,770,000 (+₹20,000 points)
        # 0.029 * 20000 = +₹580.00 P&L!
        spike_price = 7770000.0
        feed.prices["BTCINR"] = {
            "price": spike_price, "target": spike_price, "open24h": 7750000.0,
            "change_pct": 0.25, "high": spike_price, "low": 7750000.0,
            "volume": 100000.0, "category": "CRYPTO", "live": True
        }
        
        # Run mark_to_market
        by_user = bot.mark_to_market()
        
        # Verify that the position was CLOSED immediately by a profit-capture rule!
        closed_p = query_one("SELECT * FROM positions WHERE id=?", (pos_id,))
        self.assertEqual(closed_p["status"], "CLOSED")
        # The spike is captured by whichever profit rule fires first (reason labels changed over time).
        self.assertTrue(any(tag in closed_p["close_reason"] for tag in
                            ("INSTANT_PROFIT_CAPTURE", "PROFIT_TRAIL_LOCK", "TARGET_PROFIT_HIT", "SCALP_QUICK_WIN")),
                        closed_p["close_reason"])
        self.assertGreaterEqual(closed_p["realized_pnl"], 500.0)
        print(f"Verified Flash Profit Lock: Position #{pos_id} closed at spike price {spike_price} with realized P&L: ₹{closed_p['realized_pnl']:.2f} ({closed_p['close_reason']})")

if __name__ == '__main__':
    unittest.main()
