import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

# pyrefly: ignore [missing-import]
from bot_engine import Bot
# pyrefly: ignore [missing-import]
from gemini_advisor import predict_pre_entry


class _FakeFeed:
    def __init__(self, ticks_by_sym, candles_by_sym, live_px=None):
        self._ticks = ticks_by_sym
        self._candles = candles_by_sym
        self._live = live_px or {}

    def ticks(self, sym, n=90):
        return list(self._ticks.get(sym, []))[-n:]

    def candles(self, sym, interval="1m", limit=30):
        return list(self._candles.get(sym, []))[-limit:]

    def live_price(self, sym):
        if sym in self._live:
            return self._live[sym]
        t = self._ticks.get(sym) or []
        return t[-1] if t else None


def _make_candles(prices_oc):
    return [
        {"t": 1700000000 + i * 60, "o": o, "h": max(o, c) * 1.001, "l": min(o, c) * 0.999, "c": c, "v": 1000.0}
        for i, (o, c) in enumerate(prices_oc)
    ]


class TestShortAntiBounce(unittest.TestCase):
    def test_short_rejected_on_green_bounce_candles(self):
        """Lagging 24h -6% & negative tv_recommend must not open SHORT during a 3-candle 1m green bounce."""
        ticks = [1.335 - i * 0.0005 for i in range(20)] + [1.325, 1.326, 1.327, 1.328, 1.3306]
        candles = _make_candles(
            [(1.336, 1.333), (1.333, 1.330), (1.330, 1.327), (1.327, 1.325), (1.325, 1.324)]
            + [(1.324, 1.326), (1.326, 1.3285), (1.3285, 1.3306)]
        )
        bot = Bot(_FakeFeed({"ATOMUSDT": ticks}, {"ATOMUSDT": candles}))
        bot._trainer_state = {}
        bot._leader_impulse = {"btc_bouncing_up": False, "btc_dumping_down": False}
        row = {
            "symbol": "ATOMUSDT",
            "category": "CRYPTO",
            "price": 1.3306,
            "high": 1.434,
            "low": 1.315,
            "change_pct": -4.8,
            "volume": 14_000_000.0,
            "live": True,
            "tv_recommend": -0.35,
        }
        self.assertIsNone(bot.analyse("ATOMUSDT", row, mode="SCALP"))

    def test_altcoin_short_blocked_when_btc_bouncing_green(self):
        """Altcoin SHORT must wait when BTCUSDT leader is actively printing green bounce candles."""
        btc_ticks = [67300 + i * 15 for i in range(15)]
        btc_candles = _make_candles([(67310, 67330), (67330, 67360), (67360, 67415)])
        alt_ticks = [0.0625 - i * 0.00001 for i in range(20)] + [0.06230, 0.06229, 0.06228, 0.06228, 0.06227]
        alt_candles = _make_candles([(0.0625, 0.0624), (0.0624, 0.0623), (0.0623, 0.06227)])
        feed = _FakeFeed(
            {"BTCUSDT": btc_ticks, "PYTHUSDT": alt_ticks},
            {"BTCUSDT": btc_candles, "PYTHUSDT": alt_candles},
        )
        bot = Bot(feed)
        bot._trainer_state = {}
        bot._leader_impulse = bot._market_leader_impulse()
        self.assertTrue(bot._leader_impulse["btc_bouncing_up"])
        row = {
            "symbol": "PYTHUSDT",
            "category": "CRYPTO",
            "price": 0.06227,
            "high": 0.0672,
            "low": 0.0611,
            "change_pct": -7.3,
            "volume": 12_000_000.0,
            "live": True,
            "tv_recommend": -0.30,
        }
        self.assertIsNone(bot.analyse("PYTHUSDT", row, mode="SCALP"))

    def test_valid_breakdown_short_approved(self):
        """Genuine downward breakdown (red 1m candles + falling ticks) produces approved SHORT setup."""
        ticks = [100.0 - i * 0.08 for i in range(25)]
        candles = _make_candles([(100.0 - i * 0.15, 100.0 - (i + 1) * 0.15) for i in range(20)])
        bot = Bot(_FakeFeed({"SOLUSDT": ticks, "BTCUSDT": ticks}, {"SOLUSDT": candles, "BTCUSDT": candles}))
        bot._trainer_state = {}
        bot._leader_impulse = {"btc_bouncing_up": False, "btc_dumping_down": True}
        row = {
            "symbol": "SOLUSDT",
            "category": "CRYPTO",
            "price": ticks[-1],
            "high": 103.5,
            "low": 96.0,
            "change_pct": -2.1,
            "volume": 1_500_000_000.0,
            "live": True,
            "tv_recommend": -0.42,
        }
        setup = bot.analyse("SOLUSDT", row, mode="SCALP")
        self.assertIsNotNone(setup)
        self.assertEqual(setup["side"], "SHORT")
        pred = predict_pre_entry(
            symbol="SOLUSDT",
            category="CRYPTO",
            price=setup["price"],
            change_pct=-2.1,
            rsi_val=42.0,
            slope_z=setup["slope_z"],
            direction="SHORT",
            technical_conf=setup["confidence"],
            target_pct=setup["target_pct"],
            stop_pct=setup["stop_pct"],
            mode="SCALP",
            leverage=20.0,
            tv_indicators={"tv_recommend": -0.42},
        )
        self.assertTrue(pred["approved"])

    def test_predict_pre_entry_rejects_short_against_positive_slope(self):
        """Pre-entry gate must reject SHORT when live slope is actively bouncing upward."""
        pred = predict_pre_entry(
            symbol="ATOMUSDT",
            category="CRYPTO",
            price=1.33,
            change_pct=-4.8,
            rsi_val=57.0,
            slope_z=0.55,
            direction="SHORT",
            technical_conf=0.85,
            target_pct=1.0,
            stop_pct=0.5,
            mode="SCALP",
            leverage=20.0,
            tv_indicators={"tv_recommend": -0.25},
        )
        self.assertFalse(pred["approved"])

    def test_live_position_mark_price_uses_coindcx_futures_rt(self):
        """Live CoinDCX positions must mark against CoinDCX Futures RT price to prevent cross-venue gaps."""
        feed = _FakeFeed({"PYTHUSDT": [0.06288]}, {}, live_px={"PYTHUSDT": 0.06288})
        bot = Bot(feed)
        live_pos = {"symbol": "PYTHUSDT", "is_live": 1, "feed_source": "COINDCX_LIVE", "source": "COINDCX LIVE", "entry_price": 0.06245}
        paper_pos = {"symbol": "PYTHUSDT", "is_live": 0, "feed_source": "TRADINGVIEW_LIVE", "source": "BOT", "entry_price": 0.06288}
        with patch.dict(os.environ, {"ARAA_E2E_MOCK_COINDCX": "0"}, clear=False):
            px_live, src_live = bot._live_position_mark_price(live_pos, cdx_fut_map={"PYTHUSDT": {"price": 0.06243}})
            px_paper, src_paper = bot._live_position_mark_price(paper_pos, cdx_fut_map={"PYTHUSDT": {"price": 0.06243}})
        self.assertAlmostEqual(px_live, 0.06243)
        self.assertEqual(src_live, "COINDCX_FUTURES_RT")
        self.assertAlmostEqual(px_paper, 0.06288)
        self.assertEqual(src_paper, "TRADINGVIEW_LIVE")

    def test_meme_1000x_futures_contract_unit_consistency(self):
        """1000x Futures contracts (BONKUSDT -> B-1000BONK_USDT) must keep spot-unit price & uninflated margin."""
        import coindcx_gateway as cg
        with patch.dict(os.environ, {"ARAA_E2E_MOCK_COINDCX": "1"}, clear=False):
            client = cg.CoinDCXClient(api_key="e2e_key_meme_test", api_secret="e2e_secret_valid_999", user_id=1)
            client.futures.get_instrument = lambda pair: {"max_leverage_short": 5.0, "max_leverage_long": 5.0, "quantity_increment": 0.1, "min_quantity": 0.1, "min_notional": 5.0}
            with patch.object(cg, "_request", side_effect=lambda ep, method="GET", body=None, **kw: (True, [{"id": "e2e_bonk", "pair": (body or {}).get("order", {}).get("pair"), "avg_price": 0.0, "status": "filled", "leverage": 5}]) if ep.endswith("orders/create") else (True, [{"currency_short_name": "USDT", "balance": 50.0, "locked_balance": 0.0}]) if ep.endswith("wallets") else (True, [])):
                req_qty = (4.50 * 5.0) / 0.00000257
                ok_ord, res = client.futures.place_futures_order(
                    symbol="BONKUSDT", side="sell", quantity=req_qty, leverage=5.0, price=0.00000257
                )
        self.assertTrue(ok_ord)
        self.assertLess(abs(float(res["spot_equivalent_price"]) - 0.00000257), 1e-8)
        self.assertLess(float(res["actual_margin_usd"]), 6.0)


if __name__ == "__main__":
    unittest.main()
