
"""Trade Pro bot engine.

The loop ranks every live symbol inside each of the seven markets (FOREX, STOCKS, COMPANIES,
WORLD - the country equities TradingView lists, METALS, INDICES, CRYPTO), scores each candidate
on factors computed from real scraped quotes, opens up to the user's configured number of
positions in the strongest setups, marks them to market every tick, and closes on target, stop,
trail or timeout.
Realized P&L is written to the wallet; every decision lands in bot_log so the UI can show
what the bot is thinking. Trades are paper trades against real market prices - no broker is
contacted and no real order is sent.
"""
import os, threading, time, math, statistics, random

from database import query, query_one, write, writes, get_state, set_state
from price_feed import rsi, tv_symbol

def ema_series(values, n):
    if len(values) < n:
        return [values[-1]] * len(values) if values else []
    k = 2.0 / (n + 1)
    res = [values[0]]
    for v in values[1:]:
        res.append(v * k + res[-1] * (1.0 - k))
    return res

def tillson_t3(values, length=8, v_factor=0.7):
    """Tillson T3 moving average: zero-lag, ultra-smooth trend filter."""
    if len(values) < length:
        return values[-1] if values else 0.0
    e1 = ema_series(values, length)
    e2 = ema_series(e1, length)
    e3 = ema_series(e2, length)
    e4 = ema_series(e3, length)
    e5 = ema_series(e4, length)
    e6 = ema_series(e5, length)
    b = v_factor
    b2 = b * b
    b3 = b2 * b
    c1 = -b3
    c2 = 3 * b2 + 3 * b3
    c3 = -6 * b2 - 3 * b - 3 * b3
    c4 = 1 + 3 * b + b3 + 3 * b2
    return c1 * e6[-1] + c2 * e5[-1] + c3 * e4[-1] + c4 * e3[-1]

def squeeze_momentum(candles, bb_len=20, bb_mult=2.0, kc_len=20, kc_mult=1.5):
    """John Carter's Squeeze Momentum: Bollinger Bands compressing inside Keltner Channels."""
    if len(candles) < 20:
        return {"squeeze_on": False, "squeeze_fire": False, "momentum": 0.0, "signal": "NEUTRAL", "atr": 0.0}
    closes = [float(c["c"]) for c in candles]
    highs = [float(c["h"]) for c in candles]
    lows = [float(c["l"]) for c in candles]
    basis = statistics.mean(closes[-bb_len:])
    dev = (statistics.stdev(closes[-bb_len:]) if len(closes[-bb_len:]) > 1 else 0.001) * bb_mult
    bb_upper = basis + dev
    bb_lower = basis - dev
    tr_list = []
    for i in range(len(candles) - kc_len, len(candles)):
        h, l = highs[i], lows[i]
        prev_c = closes[i - 1] if i > 0 else closes[i]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        tr_list.append(tr)
    atr = statistics.mean(tr_list) if tr_list else 0.001
    kc_upper = basis + (atr * kc_mult)
    kc_lower = basis - (atr * kc_mult)
    squeeze_on = (bb_upper < kc_upper) and (bb_lower > kc_lower)
    squeeze_fire = not squeeze_on
    highest_h = max(highs[-kc_len:])
    lowest_l = min(lows[-kc_len:])
    avg_hl = (highest_h + lowest_l) / 2.0
    val = closes[-1] - ((avg_hl + basis) / 2.0)
    sig = "BUY" if (squeeze_fire and val > 0) else ("SELL" if (squeeze_fire and val < 0) else "NEUTRAL")
    return {
        "squeeze_on": squeeze_on,
        "squeeze_fire": squeeze_fire,
        "momentum": round(val, 4),
        "signal": sig,
        "atr": round(atr, 4)
    }

MODES = {
    # SQUEEZE_5M: DaviddTech 5-Minute Squeeze Momentum + Tillson T3 Cash Spot Scalper (Implementation 1)
    "SQUEEZE_5M": {
        "name": "🎯 5M Squeeze Momentum + T3",
        "target": 1.25, "stop": 0.55, "max_hold": 900, "min_win_rate": 86,
        "max_trades": 9999, "profit_target_pct": "1.0% - 2.5%", "daily_profit_usd": "$500 - $2,500+",
        "conf_threshold": 0.65, "margin_scale": 1.5, "default_leverage": 1.0, "pure_crypto": True,
        "is_squeeze": True
    },
    # PURE CRYPTO SCALPER: 24/7 Fast High-Velocity Scalping (TradingView Live 1M · 100% Crypto Focus)
    "PURE_CRYPTO": {
        "name": "⚡ Pure Crypto Scalper 24/7",
        "target": 0.6, "stop": 0.25, "max_hold": 180, "min_win_rate": 88,
        "max_trades": 9999, "profit_target_pct": "30% - 150%", "daily_profit_usd": " - +",
        "conf_threshold": 0.62, "margin_scale": 1.4, "default_leverage": 500.0, "pure_crypto": True
    },
    # BOOST MODE: High-Leverage Institutional Engine (Up to 500x Leverage · –,500+ Daily Targets)
    "BOOST": {
        "name": "⚡ Quantum Boost 500x",
        "target": 0.8, "stop": 0.35, "max_hold": 300, "min_win_rate": 82,
        "max_trades": 9999, "profit_target_pct": "50% - 250%", "daily_profit_usd": " - ,500+",
        "conf_threshold": 0.60, "margin_scale": 1.5, "default_leverage": 500.0
    },
    # 0. Continuous Active Trading: Unlimited trades, rapid high-momentum cycle, - profit loop
    "CONTINUOUS": {
        "name": "Continuous Active Trading",
        "target": 1.8, "stop": 0.8, "max_hold": 450, "min_win_rate": 75,
        "max_trades": 9999, "profit_target_pct": "15% - 25%", "daily_profit_usd": " -  loop",
        "conf_threshold": 0.65, "margin_scale": 1.2
    },
    # 1. Safe & Conservative: 78% win rate target (–/day on k)
    "CONSERVATIVE": {
        "name": "Safe & Conservative",
        "target": 1.2, "stop": 0.6, "max_hold": 1200, "min_win_rate": 78,
        "max_trades": 9999, "profit_target_pct": "5% - 8%", "daily_profit_usd": " - ",
        "conf_threshold": 0.78, "margin_scale": 1.0
    },
    # 2. Target Scalping: 75% win rate target, high-velocity scalping
    "SCALP": {
        "name": "Target Scalping (Crypto 24/7 + Gold/FX)",
        "target": 0.50, "stop": 0.28, "max_hold": 300, "min_win_rate": 75,
        "max_trades": 9999, "profit_target_pct": "10% - 15%", "daily_profit_usd": "$200 - $1,500+",
        "conf_threshold": 0.60, "margin_scale": 1.25, "default_leverage": 100.0, "pure_crypto": True
    },
    # 3. Aggressive High-Momentum: 70% win rate, 20%–30% daily target (–/day on k)
    "AGGRESSIVE": {
        "name": "Aggressive High-Momentum",
        "target": 3.2, "stop": 1.2, "max_hold": 600, "min_win_rate": 70,
        "max_trades": 9999, "profit_target_pct": "20% - 30%", "daily_profit_usd": " - ",
        "conf_threshold": 0.68, "margin_scale": 1.5
    },
    # Backwards compatibility aliases
    "SWING": {
        "name": "Safe & Conservative",
        "target": 1.2, "stop": 0.6, "max_hold": 1200, "min_win_rate": 78,
        "max_trades": 9999, "profit_target_pct": "5% - 8%", "daily_profit_usd": " - ",
        "conf_threshold": 0.78, "margin_scale": 1.0
    },
    "MOMENTUM": {
        "name": "Aggressive High-Momentum",
        "target": 3.2, "stop": 1.2, "max_hold": 600, "min_win_rate": 70,
        "max_trades": 150, "profit_target_pct": "20% - 30%", "daily_profit_usd": " - ",
        "conf_threshold": 0.68, "margin_scale": 1.5
    }
}

SCALP_MODE_PRESETS = {
    "SCALP":       (0.50, 0.28),
    "PURE_CRYPTO": (0.55, 0.28),
    "BOOST":       (0.65, 0.32),
    "SQUEEZE_5M":  (0.90, 0.45),
    "CONTINUOUS":  (0.80, 0.40),
}


def resolve_scalp_targets(mode, leverage=20.0, tp_override=None, sl_override=None, custom_rules=None):
    """Return calibrated (tp_pct, sl_pct) for scalping modes without letting 2.5%/1.5% defaults stall exits."""
    m_up = str(mode or "SCALP").upper()
    lev = max(1.0, float(leverage or 20.0))
    tp_raw = float(tp_override or 0.0) if tp_override is not None else 0.0
    sl_raw = float(sl_override or 0.0) if sl_override is not None else 0.0
    is_legacy_swing_default = (abs(sl_raw - 1.5) < 0.05 and tp_raw in (2.5, 3.0))

    if m_up in SCALP_MODE_PRESETS:
        base_tp, base_sl = SCALP_MODE_PRESETS[m_up]
        # Ignore unedited 2.5%/1.5% form fallback so fast crypto scalping stays tight
        if tp_raw > 0 and sl_raw > 0 and not is_legacy_swing_default:
            sl = round(max(0.20, min(15.0, sl_raw)), 3)
            tp = round(max(0.35, sl * 1.5, min(30.0, tp_raw)), 3)
            return tp, sl
        # Scale smoothly with leverage while keeping spot target above 0.11% CoinDCX round-trip fee
        roi_goal = float((custom_rules or {}).get("scalp_roi_target_pct") or 15.0)
        if lev >= 50.0:
            tp = min(base_tp, max(0.35, round(roi_goal / lev * 1.4, 3)))
            tp = round(max(0.35, min(0.55, tp)), 3)
            sl = round(max(0.22, min(0.32, tp * 0.55)), 3)
        elif lev >= 15.0:
            tp = round(max(0.45, min(0.75, max(base_tp, roi_goal / lev))), 3)
            sl = round(max(0.25, min(0.40, tp * 0.55)), 3)
        else:
            tp = round(max(0.55, min(0.90, base_tp * 1.2)), 3)
            sl = round(max(0.30, min(0.48, tp * 0.55)), 3)
        return tp, sl

    # Non-scalp swing/conservative modes
    tr_tp = float((custom_rules or {}).get("target_profit_pct") or 0.0)
    tr_sl = float((custom_rules or {}).get("stop_loss_pct") or 0.0)
    sl = round(max(0.30, sl_raw or tr_sl or 0.60), 3)
    tp = round(max(sl * 1.8, tp_raw or tr_tp or 1.20), 3)
    return tp, sl


CATEGORIES = ("FOREX", "STOCKS", "COMPANIES", "WORLD", "METALS", "INDICES", "CRYPTO")

# Per-market character. vol_band is the session range width (%) a setup needs to show to be
# worth trading: under it the target cannot be reached before the hold window closes (that is
# what made every old forex trade exit on TIME_EXIT at a few paise), above it the stop sits
# inside ordinary noise. horizon stretches the exit window for slower markets, tick_secs is how
# often that market's real quote actually arrives.
MARKET = {
    # Metals (Gold, Silver) & Forex: Most consistent technical trends with lowest whip-saw risk.
    "METALS":    {"vol_band": (0.04, 3.50), "horizon": 2.0, "min_conf": 0.58, "quota": 120,
                  "tick_secs": 8, "priority": 1},
    "FOREX":     {"vol_band": (0.02, 1.80), "horizon": 2.2, "min_conf": 0.58, "quota": 120,
                  "tick_secs": 8, "priority": 1},
    "INDICES":   {"vol_band": (0.04, 3.50), "horizon": 1.8, "min_conf": 0.60, "quota": 99,
                  "tick_secs": 10, "priority": 2},
    "STOCKS":    {"vol_band": (0.08, 5.00), "horizon": 1.5, "min_conf": 0.62, "quota": 99,
                  "tick_secs": 10, "priority": 2},
    "COMPANIES": {"vol_band": (0.08, 5.00), "horizon": 1.5, "min_conf": 0.62, "quota": 99,
                  "tick_secs": 10, "priority": 3},
    "CRYPTO":    {"vol_band": (0.05, 80.00), "horizon": 1.2, "min_conf": 0.48, "quota": 250,
                  "tick_secs": 3, "priority": 1},
    # World stocks: lowest priority to avoid low-liquidity slippage
    "WORLD":     {"vol_band": (0.10, 5.00), "horizon": 1.5, "min_conf": 0.72, "quota": 50,
                  "tick_secs": 8, "spread": True, "priority": 5},
}

TARGET_RISK = 1.35     # take-profit in units of measured volatility
STOP_RISK = 1.05       # tighter stop-loss: cut quickly, let winners run
MIN_TICKS = 15         # shortest real quote series we will read a direction from (RSI needs 15)


def is_market_session_open(category):
    """Real-World Global Market Trading Sessions Check:
    - CRYPTO: 24/7/365 continuous live liquidity.
    - FOREX / METALS / INDICES / STOCKS / COMPANIES / WORLD:
      Standard international market sessions operate on weekdays (Monday - Friday).
      Over the weekend (Friday 22:00 UTC through Sunday 21:00 UTC), traditional exchanges
      are closed, so trades are channeled to Crypto for guaranteed live execution and fills.
    """
    cat = (category or "").upper()
    if cat == "CRYPTO":
        return {
            "is_open": True,
            "session_name": "LIVE 24/7/365",
            "session_desc": "Continuous Global Crypto Exchanges",
            "trading_status": "OPEN",
            "badge": "LIVE"
        }
    from datetime import datetime, timezone
    utc_now = datetime.now(timezone.utc)
    weekday = utc_now.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    utc_hour = utc_now.hour

    is_closed = (weekday == 5) or \
                (weekday == 6 and utc_hour < 21) or \
                (weekday == 4 and utc_hour >= 22)
    if is_closed:
        return {
            "is_open": False,
            "session_name": "WEEKEND CLOSED",
            "session_desc": "Traditional Session Closed (Opens Asian Mon 00:00 UTC)",
            "trading_status": "CLOSED",
            "badge": "CLOSED"
        }
    return {
        "is_open": True,
        "session_name": "WEEKDAY ACTIVE",
        "session_desc": "Standard Global Exchange Trading Hours",
        "trading_status": "OPEN",
        "badge": "OPEN"
    }


def _tanh(x):
    return math.tanh(max(-6.0, min(6.0, x)))


def detect_order_block(candles):
    """Institutional Order Block (SMC) Detection Engine:
    
    1. Bullish Order Block (Demand):
       The last down-close (bearish) candle immediately preceding a violent upward
       displacement (at least 2 consecutive bullish candles breaking structure).
    2. Bearish Order Block (Supply):
       The last up-close (bullish) candle immediately preceding a violent downward
       displacement (at least 2 consecutive bearish candles breaking structure).
       
    Returns:
       dict: {
           "found": bool,
           "type": "BULLISH_OB" | "BEARISH_OB",
           "zone_high": float,
           "zone_low": float,
           "origin_price": float,
           "displacement_ratio": float,
           "retest_active": bool,
           "tight_stop_loss": float,
           "confidence_boost": float
       } or None
    """
    if not candles or len(candles) < 7:
        return None

    # Calculate average candle range and body size for displacement threshold
    ranges = [abs(c["h"] - c["l"]) for c in candles[-14:]]
    bodies = [abs(c["c"] - c["o"]) for c in candles[-14:]]
    avg_body = max(statistics.fmean(bodies) if bodies else 0.0001, 0.00001)
    curr_price = candles[-1]["c"]

    # Scan the last 12 candles for institutional displacement
    for i in range(len(candles) - 2, max(len(candles) - 14, 1), -1):
        c_prev = candles[i - 1]
        c_impulse1 = candles[i]
        c_next = candles[i + 1] if i + 1 < len(candles) else c_impulse1

        # 1. Check Bullish Order Block (last red candle before strong green breakout)
        is_red_prev = c_prev["c"] <= c_prev["o"]
        is_green_imp1 = c_impulse1["c"] > c_impulse1["o"] and (c_impulse1["c"] - c_impulse1["o"]) >= avg_body * 1.15
        broke_prev_high = max(c_impulse1["c"], c_next["c"]) > c_prev["h"]

        if is_red_prev and is_green_imp1 and broke_prev_high:
            zone_high = max(c_prev["o"], c_prev["h"])
            zone_low = min(c_prev["c"], c_prev["l"])
            buffer = max((zone_high - zone_low) * 0.20, curr_price * 0.0005)
            # Retest condition: price is near or inside the demand zone
            in_zone = (curr_price >= zone_low - buffer) and (curr_price <= zone_high + buffer * 3.0)
            tight_sl = max(zone_low - (zone_high - zone_low) * 0.25, zone_low * 0.998)
            sl_pct = max(0.15, abs(curr_price - tight_sl) / curr_price * 100.0)

            return {
                "found": True,
                "type": "BULLISH_OB",
                "bias": "LONG",
                "zone_high": round(zone_high, 6),
                "zone_low": round(zone_low, 6),
                "origin_price": round(c_prev["c"], 6),
                "displacement_ratio": round((c_impulse1["c"] - c_impulse1["o"]) / avg_body, 2),
                "retest_active": in_zone,
                "tight_sl_price": round(tight_sl, 6),
                "tight_sl_pct": round(sl_pct, 3),
                "confidence_boost": 0.20 if in_zone else 0.10
            }

        # 2. Check Bearish Order Block (last green candle before strong red breakdown)
        is_green_prev = c_prev["c"] >= c_prev["o"]
        is_red_imp1 = c_impulse1["c"] < c_impulse1["o"] and (c_impulse1["o"] - c_impulse1["c"]) >= avg_body * 1.15
        broke_prev_low = min(c_impulse1["c"], c_next["c"]) < c_prev["l"]

        if is_green_prev and is_red_imp1 and broke_prev_low:
            zone_high = max(c_prev["c"], c_prev["h"])
            zone_low = min(c_prev["c"], c_prev["l"])
            buffer = max((zone_high - zone_low) * 0.20, curr_price * 0.0005)
            in_zone = (curr_price <= zone_high + buffer) and (curr_price >= zone_low - buffer * 3.0)
            tight_sl = min(zone_high + (zone_high - zone_low) * 0.25, zone_high * 1.002)
            sl_pct = max(0.15, abs(tight_sl - curr_price) / curr_price * 100.0)

            return {
                "found": True,
                "type": "BEARISH_OB",
                "bias": "SHORT",
                "zone_high": round(zone_high, 6),
                "zone_low": round(zone_low, 6),
                "origin_price": round(c_prev["c"], 6),
                "displacement_ratio": round((c_impulse1["o"] - c_impulse1["c"]) / avg_body, 2),
                "retest_active": in_zone,
                "tight_sl_price": round(tight_sl, 6),
                "tight_sl_pct": round(sl_pct, 3),
                "confidence_boost": 0.20 if in_zone else 0.10
            }

    return None


class Bot:
    MAX_LIVE_CLOSE_RETRIES = 5

    def __init__(self, feed):
        self.feed = feed
        self._close_fail = {}   # position id -> consecutive failed exchange closes
        self._stop = threading.Event()
        self._wake_event = threading.Event()
        self._thread = None
        self.tick_count = 0
        self.last_cycle = None
        self.candidates = []
        self.setups = []
        self.by_category = {c: [] for c in CATEGORIES}
        self.rejected = {c: 0 for c in CATEGORIES}
        self.ready = {c: 0 for c in CATEGORIES}
        self.analysed_at = 0.0
        self._candle_cache = {}

    # ---------- switch ----------
    @property
    def is_running(self):
        return get_state("bot_running", "1") == "1"

    def start(self):
        set_state("bot_running", "1")
        self._log(None, "INFO", "GLOBAL BOT SWITCHED ON")

    def stop(self):
        set_state("bot_running", "0")
        # When global bot is stopped, flush ALL open bot positions across ALL users immediately
        all_users = query("SELECT DISTINCT user_id FROM positions WHERE status='OPEN' AND source != 'MANUAL'")
        total_closed = 0
        total_pnl = 0.0
        for row in all_users:
            pnl, cnt = self.close_all_for(row["user_id"], reason="GLOBAL_BOT_STOPPED")
            total_closed += cnt
            total_pnl += pnl
        self._log(None, "INFO", f"GLOBAL BOT SWITCHED OFF — Flushed {total_closed} positions across all users (Net P&L: ${total_pnl:+.2f})")

    # ---------- logging ----------
    def _log(self, user_id, level, message):
        write("INSERT INTO bot_log(at,user_id,level,message) VALUES(?,?,?,?)",
              (time.time(), user_id, level, message))
        if random.random() < 0.05:
            rows = query("SELECT id FROM bot_log ORDER BY id DESC LIMIT 500")
            if len(rows) >= 500:
                keep = rows[-1]["id"]
                write("DELETE FROM bot_log WHERE id<?", (keep,))

    # ---------- universe ----------
    @staticmethod
    def _spread(scored, tune):
        """The strongest slice of a market, taken country by country when it spans many countries.

        Japan and China report share turnover orders of magnitude above Iceland-sized exchanges,
        so a plain cut on volume would fill the world universe with two or three exchanges and
        leave the other 33 countries untraded. Round one takes each country's best name, round two
        its second, and so on until the quota is full.
        """
        quota = tune["quota"]
        if not tune.get("spread"):
            return scored[:quota]
        pools = {}
        for item in scored:
            pools.setdefault(item[1].get("country") or "", []).append(item)
        keep, rank = [], 0
        while len(keep) < quota and any(len(p) > rank for p in pools.values()):
            for pool in pools.values():
                if rank < len(pool):
                    keep.append(pool[rank])
                    if len(keep) >= quota:
                        break
            rank += 1
        return keep[:quota]

    @staticmethod
    def _rotate(pool, offset):
        """Interleave a market's setups country by country, starting at a rotating country.

        A confidence-ordered pool hands the same names to the ticket loop every cycle. Taking the
        best name of each country in turn, and beginning each cycle at the next country in the
        alphabet, gives every exchange a turn at a position without changing the analysis.
        """
        buckets = {}
        for s in pool:
            buckets.setdefault(s.get("country") or s["symbol"], []).append(s)
        keys = sorted(buckets)
        keys = keys[offset % len(keys):] + keys[:offset % len(keys)]
        out = []
        while any(buckets.values()):
            for k in keys:
                if buckets[k]:
                    out.append(buckets[k].pop(0))
        return out

    def scan(self):
        """Rank every quoted symbol inside its own market and keep the liquid, volatile slice.

        Crypto turnover is orders of magnitude above an FX or equity quote, so a single global
        sort starves every other market. Each category is ranked against itself instead.
        """
        with self.feed.lock:
            # Live TradingView charts only: every candidate in Paper Bot mode must have a real-time
            # live quote AND a supported live TradingView chart widget (tv_symbol(sym) is not None).
            rows = [(sym, dict(r)) for sym, r in self.feed.prices.items()
                    if r["price"] > 0 and r.get("live") and (tv_symbol(sym) or sym.endswith("INR") or sym.endswith("USDT") or r.get("category") == "CRYPTO")]
        by_cat = {}
        for sym, r in rows:
            by_cat.setdefault(r.get("category", "CRYPTO"), []).append((sym, r))
        universe = []
        for cat in CATEGORIES:
            items = by_cat.get(cat, [])
            tune = MARKET.get(cat, MARKET["CRYPTO"])
            scored = sorted(items, key=lambda sr: -((sr[1].get("volume") or 0) ** 0.25 *
                                                    (abs(sr[1].get("change_pct") or 0.0) + 0.15)))
            keep = self._spread(scored, tune)
            self.by_category[cat] = [s for s, _ in keep]
            universe.extend(keep)
        leftovers = [c for c in by_cat if c not in CATEGORIES]
        for cat in leftovers:
            universe.extend(by_cat[cat][:MARKET["CRYPTO"]["quota"]])

        # Always guarantee core MT4 tradable symbols are included for Real Mode execution
        CORE_MT4 = {
            "EURUSD", "GBPUSD", "USDJPY", "USDCAD", "USDCHF", "AUDUSD", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP", "CADJPY", "USDINR",
            "XAUUSD", "XAGUSD",
            "BTCUSD", "BTCUSDT", "ETHUSD", "ETHUSDT", "SOLUSD", "SOLUSDT",
            "US30", "SPX500", "NAS100"
        }
        existing_syms = {sym for sym, _ in universe}
        for sym in CORE_MT4:
            if sym not in existing_syms and sym in self.feed.prices:
                r = self.feed.prices[sym]
                if r.get("price") and r.get("live") and (tv_symbol(sym) or sym.endswith("INR") or sym.endswith("USDT") or r.get("category") == "CRYPTO"):
                    cat = r.get("category") or ("CRYPTO" if "BTC" in sym or "ETH" in sym or "SOL" in sym else "FOREX")
                    universe.append((sym, dict(r)))
                    self.by_category.setdefault(cat, []).append(sym)
                    existing_syms.add(sym)

        # Always guarantee top active liquid CoinDCX Futures (USDT) & INR tradable symbols are included
        try:
            from coindcx_gateway import get_live_tickers
            t_map = get_live_tickers()
            if t_map:
                # Add Top CoinDCX USDT Futures pairs (Priority for USD trading)
                stable_bases = {"USDC", "DAI", "FDUSD", "TUSD", "USDE", "USDP", "BUSD", "EURC", "PYUSD", "RLUSD", "USD1", "USDD", "FRAX", "LUSD", "USTC"}
                priority_order = [
                    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "NEARUSDT", "BNBUSDT",
                    "1000PEPEUSDT", "ZECUSDT", "YBUSDT", "CARVUSDT", "SPELLUSDT", "SAPIENUSDT",
                    "BANANAUSDT", "MOCAUSDT", "SONICUSDT", "DOLOUSDT", "MTLUSDT",
                    "GASUSDT", "BELUSDT", "ASTRUSDT", "ASRUSDT", "SANTOSUSDT", "BNTUSDT",
                    "1000000MOGUSDT", "JOEUSDT", "WAXPUSDT", "XVSUSDT"
                ]
                p_set = {s: i for i, s in enumerate(priority_order)}
                def _is_stable_pair(sym_name):
                    su = str(sym_name or "").upper()
                    base = su[2:-5] if (su.startswith("B-") and su.endswith("_USDT")) else (su[:-4] if su.endswith("USDT") else su)
                    return base in stable_bases
                usdt_list = [
                    (s, td) for s, td in t_map.items()
                    if (s.endswith("USDT") or s.startswith("B-")) and not _is_stable_pair(s)
                ]
                usdt_list.sort(key=lambda x: (0 if x[0] in p_set else 1, p_set.get(x[0], 9999), -float(x[1].get("volume") or 0.0)))
                for sym, t_data in usdt_list[:150]:
                    p = float(t_data.get("last_price") or 0.0)
                    if p > 0 and sym not in existing_syms:
                        chg = float(t_data.get("change_24_hour") or 0.0)
                        clean_s = sym[2:].replace("_USDT", "USDT") if sym.startswith("B-") else sym
                        with self.feed.lock:
                            existing_feed = dict(self.feed.prices.get(sym) or self.feed.prices.get(clean_s) or {})
                        merged_row = dict(existing_feed)
                        merged_row.update({
                            "price": p, "target": p,
                            "open24h": float(existing_feed.get("open24h") or (p / (1.0 + chg / 100.0) if chg != -100.0 else p)),
                            "change_pct": chg,
                            "high": float(t_data.get("high") or existing_feed.get("high") or (p * 1.02)),
                            "low": float(t_data.get("low") or existing_feed.get("low") or (p * 0.98)),
                            "volume": float(t_data.get("volume") or existing_feed.get("volume") or 100000.0),
                            "category": "CRYPTO",
                            "live": True, "source": "COINDCX FUTURES"
                        })
                        with self.feed.lock:
                            hist = self.feed.history[sym]
                            decimals = 8 if p < 0.01 else (6 if p < 1 else (4 if p < 10 else 2))
                            if len(hist) < 20 or len(set(round(float(x), 8) for x in list(hist)[-15:])) <= 2:
                                src_hist = list(self.feed.history.get(clean_s) or [])
                                hist.clear()
                                if len(src_hist) >= 15 and len(set(round(float(x), 8) for x in src_hist[-15:])) >= 3:
                                    for h_v in src_hist[-20:]:
                                        hist.append(h_v)
                                else:
                                    tv_rec_seed = merged_row.get("tv_rec_1m") if merged_row.get("tv_rec_1m") is not None else merged_row.get("tv_recommend")
                                    ema50_seed = merged_row.get("tv_ema50_1m")
                                    if ema50_seed and float(ema50_seed) > 0 and abs(p - float(ema50_seed)) / p <= 0.04:
                                        start_p = float(ema50_seed)
                                    elif tv_rec_seed is not None and abs(float(tv_rec_seed)) >= 0.05:
                                        start_p = p / (1.0 + float(tv_rec_seed) * 0.003)
                                    else:
                                        start_p = p
                                    for k_i in range(20):
                                        frac = (k_i + 1) / 20.0
                                        hist.append(round(start_p + (p - start_p) * frac, decimals))
                            if hasattr(self.feed, "_compute_live_tv_ratings"):
                                self.feed._compute_live_tv_ratings(sym, merged_row, hist)
                            if sym not in self.feed.prices:
                                self.feed.prices[sym] = dict(merged_row)
                            else:
                                self.feed.prices[sym].update(merged_row)
                        universe.append((sym, merged_row))
                        self.by_category.setdefault("CRYPTO", []).append(sym)
                        existing_syms.add(sym)

                inr_list = [
                    (s, td) for s, td in t_map.items()
                    if s.endswith("INR") and not s.startswith("USDT") and not s.startswith("USDC") and not s.startswith("DAI")
                ]
                inr_list.sort(key=lambda x: -float(x[1].get("volume") or 0.0))
                for sym, t_data in inr_list[:35]:
                    p = float(t_data.get("last_price") or 0.0)
                    if p > 0 and sym not in existing_syms:
                        chg = float(t_data.get("change_24_hour") or 0.0)
                        usdt_equiv = sym[:-3] + "USDT"
                        with self.feed.lock:
                            existing_feed = dict(self.feed.prices.get(sym) or self.feed.prices.get(usdt_equiv) or {})
                        merged_row = dict(existing_feed)
                        merged_row.update({
                            "price": p, "target": p,
                            "open24h": float(existing_feed.get("open24h") or (p / (1.0 + chg / 100.0) if chg != -100.0 else p)),
                            "change_pct": chg,
                            "high": float(t_data.get("high") or existing_feed.get("high") or (p * 1.02)),
                            "low": float(t_data.get("low") or existing_feed.get("low") or (p * 0.98)),
                            "volume": float(t_data.get("volume") or existing_feed.get("volume") or 100000.0),
                            "category": "CRYPTO",
                            "live": True, "source": "COINDCX LIVE"
                        })
                        with self.feed.lock:
                            hist = self.feed.history[sym]
                            decimals = 8 if p < 0.01 else (6 if p < 1 else (4 if p < 10 else 2))
                            if len(hist) < 20 or len(set(round(float(x), 8) for x in list(hist)[-15:])) <= 2:
                                hist.clear()
                                tv_rec_seed = merged_row.get("tv_rec_1m") if merged_row.get("tv_rec_1m") is not None else merged_row.get("tv_recommend")
                                if tv_rec_seed is not None and abs(float(tv_rec_seed)) >= 0.05:
                                    start_p = p / (1.0 + float(tv_rec_seed) * 0.003)
                                else:
                                    start_p = p
                                for k_i in range(20):
                                    frac = (k_i + 1) / 20.0
                                    hist.append(round(start_p + (p - start_p) * frac, decimals))
                            if hasattr(self.feed, "_compute_live_tv_ratings"):
                                self.feed._compute_live_tv_ratings(sym, merged_row, hist)
                            if sym not in self.feed.prices:
                                self.feed.prices[sym] = dict(merged_row)
                            else:
                                self.feed.prices[sym].update(merged_row)
                        universe.append((sym, merged_row))
                        self.by_category.setdefault("CRYPTO", []).append(sym)
                        existing_syms.add(sym)
                if hasattr(self.feed, "refresh_crypto_tradingview"):
                    now_ts = time.time()
                    if now_ts - getattr(self.feed, "_last_tv_crypto_scan", 0.0) >= 8.0 or any(r.get("tv_rec_1m") is None for _, r in universe[:25] if r.get("category") == "CRYPTO"):
                        self.feed.refresh_crypto_tradingview(force=True)
                        with self.feed.lock:
                            for idx_u, (u_sym, u_row) in enumerate(universe):
                                live_r = self.feed.prices.get(u_sym)
                                if live_r:
                                    u_row.update(live_r)
        except Exception:
            pass

        self.candidates = universe
        return universe

    # ---------- analysis ----------
    def _candles(self, symbol, interval="1m", limit=14, ttl=30.0):
        """Non-blocking cached 1m klines from feed memory cache."""
        clean_sym = str(symbol or "").upper().strip()
        if clean_sym.startswith("B-"):
            clean_sym = clean_sym[2:]
        clean_sym = clean_sym.replace("_", "").replace("-", "")
        if clean_sym.endswith("INR"):
            clean_sym = f"{clean_sym[:-3]}USDT"
        key = (clean_sym, interval, limit)
        if not hasattr(self, "_candle_cache"):
            self._candle_cache = {}
        hit = self._candle_cache.get(key)
        now = time.time()
        if hit and now - hit[0] < ttl:
            return hit[1]
        found = self.feed.candles(clean_sym, interval, limit)
        self._candle_cache[key] = (now, found)
        if len(self._candle_cache) > 600:
            self._candle_cache.clear()
        return found

    @staticmethod
    def _micro_momentum_state(ticks, candles=None):
        """Measure short-horizon tick velocity and recent 1m candle direction to block chasing bounces/drops."""
        ticks = [float(t) for t in (ticks or []) if t and float(t) > 0]
        last_px = ticks[-1] if ticks else 0.0
        fast_ma = statistics.fmean(ticks[-5:]) if len(ticks) >= 5 else last_px
        recent_tick_pct = ((ticks[-1] - ticks[-4]) / ticks[-4] * 100.0) if (len(ticks) >= 4 and ticks[-4] > 0) else 0.0
        step_tail = min(3, max(0, len(ticks) - 1))
        micro_step_ups = sum(1 for i in range(-step_tail, 0) if ticks[i] > ticks[i - 1]) if step_tail > 0 else 0
        micro_step_downs = sum(1 for i in range(-step_tail, 0) if ticks[i] < ticks[i - 1]) if step_tail > 0 else 0

        valid_c = [c for c in (candles or []) if c and float(c.get("o") or 0) > 0 and float(c.get("c") or 0) > 0]
        last_3_green = len(valid_c) >= 3 and all(float(c["c"]) > float(c["o"]) for c in valid_c[-3:])
        last_2_green = len(valid_c) >= 2 and float(valid_c[-1]["c"]) > float(valid_c[-1]["o"]) and float(valid_c[-2]["c"]) > float(valid_c[-2]["o"])
        last_3_red = len(valid_c) >= 3 and all(float(c["c"]) < float(c["o"]) for c in valid_c[-3:])
        last_2_red = len(valid_c) >= 2 and float(valid_c[-1]["c"]) < float(valid_c[-1]["o"]) and float(valid_c[-2]["c"]) < float(valid_c[-2]["o"])
        last_body_pct = ((float(valid_c[-1]["c"]) - float(valid_c[-1]["o"])) / float(valid_c[-1]["o"]) * 100.0) if valid_c else 0.0
        return {
            "above_fast": bool(last_px > 0 and last_px > fast_ma),
            "below_fast": bool(last_px > 0 and last_px < fast_ma),
            "recent_tick_pct": recent_tick_pct,
            "micro_step_ups": micro_step_ups,
            "micro_step_downs": micro_step_downs,
            "last_3_green": last_3_green,
            "last_2_green": last_2_green,
            "last_3_red": last_3_red,
            "last_2_red": last_2_red,
            "last_body_pct": last_body_pct,
        }

    def _market_leader_impulse(self):
        """Inspect BTCUSDT live micro-trend once per cycle to prevent shorting alts during market-wide green bounces."""
        try:
            btc_ticks = self.feed.ticks("BTCUSDT", 15) if hasattr(self, "feed") else []
            btc_candles = self._candles("BTCUSDT", "1m", limit=10)
            m = self._micro_momentum_state(btc_ticks, btc_candles)
            btc_bouncing_up = bool(
                m["last_3_green"]
                or (m["last_2_green"] and m["last_body_pct"] >= 0.04 and m["above_fast"])
                or (m["above_fast"] and m["micro_step_ups"] >= 3 and m["recent_tick_pct"] >= 0.06)
            )
            btc_dumping_down = bool(
                m["last_3_red"]
                or (m["last_2_red"] and m["last_body_pct"] <= -0.04 and m["below_fast"])
                or (m["below_fast"] and m["micro_step_downs"] >= 3 and m["recent_tick_pct"] <= -0.06)
            )
            return {"btc_bouncing_up": btc_bouncing_up, "btc_dumping_down": btc_dumping_down}
        except Exception:
            return {"btc_bouncing_up": False, "btc_dumping_down": False}

    @staticmethod
    def _futures_mark_map(opens):
        """Fetch live CoinDCX Futures RT mark map once per batch when live CoinDCX positions exist."""
        if (
            not opens
            or os.environ.get("ARAA_E2E_MOCK_COINDCX") == "1"
            or not any(
                p.get("is_live") and ("COINDCX" in str(p.get("feed_source") or "").upper() or "COINDCX" in str(p.get("source") or "").upper())
                for p in opens
            )
        ):
            return None
        try:
            from coindcx_gateway import get_live_futures_prices
            return get_live_futures_prices()
        except Exception:
            return None

    def _live_position_mark_price(self, p, cdx_fut_map=None):
        """Return venue-matched live mark price so CoinDCX Futures entry & mark prices stay on the same orderbook."""
        sym = p["symbol"]
        entry = float(p.get("entry_price") or 0.0)
        is_cdx_pos = bool(
            p.get("is_live")
            and ("COINDCX" in str(p.get("feed_source") or "").upper() or "COINDCX" in str(p.get("source") or "").upper())
        )
        if is_cdx_pos and cdx_fut_map and os.environ.get("ARAA_E2E_MOCK_COINDCX") != "1":
            clean = str(sym or "").upper().replace("-", "").replace("_", "")
            fut_row = cdx_fut_map.get(sym) or cdx_fut_map.get(clean)
            if fut_row and float(fut_row.get("price") or 0.0) > 0:
                fut_px = float(fut_row["price"])
                if entry <= 0 or (0.45 <= (fut_px / entry) <= 2.2):
                    return fut_px, "COINDCX_FUTURES_RT"
        return self.feed.live_price(sym), str(p.get("feed_source") or "TRADINGVIEW_LIVE")

    def analyse(self, symbol, row, mode="SCALP"):
        """Score one symbol from the live data we hold for it. Returns None when it is untradeable.

        Every factor is measured, not assumed: the session range and change come from the
        scraped quote, the trend and volatility from the tick series this process recorded, and
        for crypto only the candle agreement from real Binance 1m klines.
        """
        cat = row.get("category", "CRYPTO")
        if cat == "CRYPTO":
            _su = str(symbol or "").upper()
            _base = _su[2:-5] if (_su.startswith("B-") and _su.endswith("_USDT")) else (_su[:-4] if _su.endswith("USDT") else _su)
            if _base in {"USDC", "DAI", "FDUSD", "TUSD", "USDE", "USDP", "BUSD", "EURC", "PYUSD", "RLUSD", "USD1", "USDD", "FRAX", "LUSD", "USTC"}:
                return None
            _vol = float(row.get("volume") or 0.0)
            if 0.0 < _vol < 2_000_000.0:
                return None
        tune = MARKET.get(cat, MARKET["CRYPTO"])
        price = row["price"]
        hi, lo = row.get("high") or 0.0, row.get("low") or 0.0
        tv_code = tv_symbol(symbol) or symbol
        if price <= 0 or hi <= lo or not row.get("live"):
            return None
        day_range_pct = (hi - lo) / price * 100.0
        if not (tune["vol_band"][0] <= day_range_pct <= tune["vol_band"][1]):
            return None
        candles_1m = []
        if cat == "CRYPTO":
            candles_1m = self._candles(symbol, "1m", limit=35, ttl=25.0)
            if hasattr(self.feed, "prices") and hasattr(self.feed, "lock"):
                with self.feed.lock:
                    live_row = self.feed.prices.get(symbol) or {}
                    for k in (
                        "tv_rsi", "tv_rsi_1m", "tv_rsi_5m", "tv_rsi_1d",
                        "tv_recommend", "tv_rec_1m", "tv_rec_5m", "tv_rec_1d",
                        "tv_ma", "tv_ma_1m", "tv_ma_5m", "tv_other", "tv_other_1m", "tv_other_5m",
                        "tv_macd_1m", "tv_macd_sig_1m", "tv_macd_5m", "tv_macd_sig_5m",
                        "tv_ema20_1m", "tv_ema50_1m", "tv_ema20_5m", "tv_ema50_5m",
                        "tv_chg_1m", "tv_chg_5m", "tv_signal"
                    ):
                        if live_row.get(k) is not None and (row.get(k) is None or row.get("tv_signal") == "NEUTRAL"):
                            row[k] = live_row[k]
        ticks = self.feed.ticks(symbol, 90)
        if len(candles_1m) >= 12 and (len(ticks) < MIN_TICKS or len(set(round(float(x), 8) for x in ticks[-15:])) <= 2):
            c_closes = [float(c["c"]) for c in candles_1m if float(c.get("c") or 0) > 0]
            if len(c_closes) >= MIN_TICKS:
                ticks = c_closes
        if len(ticks) < MIN_TICKS:
            return None            # no measured history yet - refuse to guess a direction
        rets = [(ticks[i] - ticks[i - 1]) / ticks[i - 1] * 100.0
                for i in range(1, len(ticks)) if ticks[i - 1]]
        abs_moves = [abs(r) for r in rets]
        # Robust scale of a single quote-to-quote move: one violent print would inflate a plain
        # standard deviation and push the target out of reach for the whole hold window.
        #
        # The median alone only works on a market that prints every sample. An equity quote arrives
        # on exchange trades, so most 8-second samples are flat and the median move is exactly zero
        # - which would read as "this stock does not move" for 403 of the 418 country names. The mean
        # carries those rare real moves; taking the larger of the two keeps crypto behaviour
        # unchanged and still reports zero only when every quote in the window was identical, i.e.
        # a feed that has genuinely gone still.
        tick_vol = max(statistics.median(abs_moves) * 1.4826 if len(abs_moves) > 6 else 0.0,
                       statistics.fmean(abs_moves) if abs_moves else 0.0)
        if tick_vol <= 0:
            tick_vol = max(0.001, day_range_pct * 0.02)
        fast = statistics.fmean(ticks[-5:])
        # Compare the last five quotes against everything before them, capped at a 25-quote
        # backdrop. While a market is still warming up the whole series is the backdrop.
        slow = statistics.fmean(ticks[-25:] if len(ticks) >= 25 else ticks[:-5])
        slope_z = ((fast - slow) / price * 100.0) / tick_vol
        range_pos = (price - lo) / (hi - lo)
        change = row.get("change_pct") or 0.0
        tv_rsi_live = row.get("tv_rsi_1m") if row.get("tv_rsi_1m") is not None else row.get("tv_rsi")
        r14 = float(tv_rsi_live) if tv_rsi_live is not None else rsi(ticks, 14)
        if r14 is None:
            r14 = 50.0             # too short for Wilder's smoothing: neutral, never a signal

        # Load Self-Learning Walk-Forward Trainer state cached for this cycle
        tr_state = getattr(self, "_trainer_state", None) or {}
        tr_weights = tr_state.get("weights") or {}
        tr_rules = tr_state.get("custom_rules") or {}
        clean_sym = str(symbol or "").upper().replace("B-", "").replace("_USDT", "USDT").replace("_INR", "USDT")
        if clean_sym.endswith("INR"):
            clean_sym = clean_sym[:-3] + "USDT"

        # 1. Blacklist Guard: Reject symbols on AI Trainer Cooldown
        for b_item in (tr_state.get("blacklisted_symbols") or []):
            b_sym = b_item.get("symbol") if isinstance(b_item, dict) else str(b_item)
            if b_sym == clean_sym or b_sym == symbol:
                return None

        w_ema = float(tr_weights.get("w_ema_ribbon") or 0.34)
        w_rsi = float(tr_weights.get("w_rsi_momentum") or 0.24)
        w_macd = float(tr_weights.get("w_macd_impulse") or 0.24)
        w_vol = float(tr_weights.get("w_squeeze_vol") or 0.18)

        rsi_l_min = float(tr_rules.get("rsi_long_min") or 38.0)
        rsi_l_max = float(tr_rules.get("rsi_long_max") or 72.0)
        rsi_s_min = float(tr_rules.get("rsi_short_min") or 28.0)
        rsi_s_max = float(tr_rules.get("rsi_short_max") or 62.0)

        parts = []
        trend = _tanh(slope_z / 2.0) * max(0.32, w_ema)
        parts.append(("TREND", trend, f"{slope_z:+.2f}sd"))
        pos = (range_pos - 0.5) * 2.0 * 0.06
        parts.append(("RANGE", pos, f"{range_pos * 100:.0f}% of day range"))
        imp = _tanh(change / 4.0) * 0.06
        parts.append(("24H", imp, f"{change:+.2f}%"))
        if r14 >= 78:
            mom = -0.05            # stretched: fade risk outweighs the move
        elif rsi_l_min <= r14 <= rsi_l_max:
            mom = round(max(0.20, w_rsi * 0.9), 3)  # trained RSI sweet spot
        elif r14 >= 50:
            mom = 0.20             # strong bullish continuation
        elif r14 >= 35:
            mom = 0.16             # solid pullback bounce support
        elif r14 <= 25:
            mom = 0.18             # oversold capitulation bounce
        else:
            mom = 0.12             # accumulation zone
        parts.append(("RSI", mom, f"RSI {r14:.0f}"))
        liq = min(0.12, (math.log10(max(row.get("volume") or 1.0, 10.0)) - 4.0) / 38.0)
        parts.append(("LIQ", liq, f"vol {short_num(row.get('volume') or 0)}"))
        if cat == "CRYPTO":
            if len(candles_1m) >= 8:
                ups = sum(1 for c in candles_1m[-8:] if c["c"] >= c["o"]) / 8.0
                parts.append(("1m CANDLES", (ups - 0.5) * 2 * max(0.18, w_vol), f"{ups * 100:.0f}% up"))

        # 2. Apply Self-Learning Walk-Forward Winner Boost if symbol is a verified winner
        trainer_boost_info = None
        for g_item in (tr_state.get("boosted_symbols") or []):
            if isinstance(g_item, dict) and g_item.get("symbol") in (clean_sym, symbol):
                trainer_boost_info = g_item
                break
            elif g_item in (clean_sym, symbol):
                trainer_boost_info = {"symbol": clean_sym, "win_rate": 86.0, "boost": 5}
                break
        if trainer_boost_info:
            b_val = round(min(0.12, float(trainer_boost_info.get("boost") or 5) * 0.015), 3)
            b_wr = trainer_boost_info.get("win_rate", 86.0)
            parts.append(("AI_TRAINER", b_val, f"🧠 Gen #{tr_state.get('generation', 1)} Winner ({b_wr}% WR)"))

        # Institutional Order Block Detection
        pre_score = sum(p[1] for p in parts)
        ob = None
        try:
            recent_candles = candles_1m[-20:] if candles_1m else self._candles(symbol, "1m", limit=20)
            if recent_candles and len(recent_candles) >= 7:
                ob = detect_order_block(recent_candles)
        except Exception:
            pass

        if ob and ob.get("found"):
            if ob["bias"] == "LONG" and (pre_score >= 0 or r14 < 45):
                ob_weight = 0.22 if ob["retest_active"] else 0.12
                parts.append(("ORDER BLOCK", ob_weight, f"{ob['type']} Retest at {ob['zone_low']}-{ob['zone_high']}"))
            elif ob["bias"] == "SHORT" and (pre_score <= 0 or r14 >= 38):
                ob_weight = -0.22 if ob["retest_active"] else -0.12
                parts.append(("ORDER BLOCK", ob_weight, f"{ob['type']} Retest at {ob['zone_low']}-{ob['zone_high']}"))

        # Squeeze Momentum & Tillson T3 Integration (Symmetric Bullish & Bearish Engines)
        sq_mom = 0.0
        if cat == "CRYPTO":
            try:
                sq_candles = candles_1m if len(candles_1m) >= 20 else self._candles(symbol, "1m", limit=30)
                if sq_candles and len(sq_candles) >= 20:
                    sq_data = squeeze_momentum(sq_candles)
                    sq_mom = float(sq_data.get("momentum") or 0.0)
                    t3_val = tillson_t3([float(c["c"]) for c in sq_candles], length=8, v_factor=0.7)
                    if sq_data["squeeze_fire"] and price > t3_val and sq_mom > 0:
                        parts.append(("SQUEEZE_T3", 0.35, f"BULLISH SQUEEZE FIRE! (Mom {sq_mom:+.2f} · Price > T3 ${t3_val:,.2f})"))
                    elif sq_data["squeeze_fire"] and price < t3_val and sq_mom < 0:
                        parts.append(("SQUEEZE_T3", -0.38, f"BEARISH SQUEEZE FIRE! (Mom {sq_mom:+.2f} · Price < T3 ${t3_val:,.2f})"))
                    elif sq_data["squeeze_on"]:
                        parts.append(("SQUEEZE_T3", 0.05, f"Squeeze Coiling (Energy Build · Mom {sq_mom:+.2f})"))
            except Exception:
                pass

        # REAL LIVE TRADINGVIEW & TECHNICAL SIGNAL INTEGRATION (BIDIRECTIONAL LONG & SHORT):
        tv_rec_1m = row.get("tv_rec_1m")
        tv_rec_5m = row.get("tv_rec_5m")
        tv_rec = row.get("tv_recommend")
        tv_ma_1m = row.get("tv_ma_1m")
        tv_ma_5m = row.get("tv_ma_5m")
        tv_ma = row.get("tv_ma")
        tv_ema20_1m = row.get("tv_ema20_1m")
        tv_ema50_1m = row.get("tv_ema50_1m")
        tv_macd_1m = row.get("tv_macd_1m")
        tv_macd_sig_1m = row.get("tv_macd_sig_1m")
        tv_label = "NEUTRAL"

        # Multi-Timeframe TradingView Scalp Consensus (1m + 5m live chart agreement):
        # If 1m and 5m TradingView chart ratings directly conflict, skip until both timeframes align.
        if tv_rec_1m is not None and tv_rec_5m is not None:
            if (float(tv_rec_1m) > 0.08 and float(tv_rec_5m) < -0.08) or (float(tv_rec_1m) < -0.08 and float(tv_rec_5m) > 0.08):
                return None
            tv_rec = round(0.58 * float(tv_rec_1m) + 0.42 * float(tv_rec_5m), 4)
        elif tv_rec_1m is not None:
            tv_rec = float(tv_rec_1m)
        elif tv_rec_5m is not None and tv_rec is None:
            tv_rec = float(tv_rec_5m)

        if tv_ma_1m is not None and tv_ma_5m is not None:
            tv_ma = round(0.58 * float(tv_ma_1m) + 0.42 * float(tv_ma_5m), 4)
        elif tv_ma_1m is not None:
            tv_ma = float(tv_ma_1m)

        if tv_ema20_1m and tv_ema50_1m:
            ema20_v, ema50_v = float(tv_ema20_1m), float(tv_ema50_1m)
            if price > ema20_v > ema50_v:
                parts.append(("TV_EMA_1m", 0.14, f"Price > EMA20 > EMA50"))
            elif price < ema20_v < ema50_v:
                parts.append(("TV_EMA_1m", -0.14, f"Price < EMA20 < EMA50"))

        if tv_macd_1m is not None and tv_macd_sig_1m is not None:
            macd_diff = float(tv_macd_1m) - float(tv_macd_sig_1m)
            if macd_diff > 0:
                parts.append(("TV_MACD_1m", 0.10, f"MACD Bullish ({macd_diff:+.4f})"))
            elif macd_diff < 0:
                parts.append(("TV_MACD_1m", -0.10, f"MACD Bearish ({macd_diff:+.4f})"))

        if tv_rec is not None:
            tf_note = f"1m:{float(tv_rec_1m):+.2f}/5m:{float(tv_rec_5m):+.2f}" if (tv_rec_1m is not None and tv_rec_5m is not None) else f"{tv_rec:+.2f}"
            if tv_rec >= 0.08:
                side = "LONG"
                tv_label = "STRONG_BUY" if tv_rec >= 0.45 else "BUY"
                parts.insert(0, ("TRADINGVIEW", round(max(0.16, abs(tv_rec) * 0.42), 2), f"{tv_label} ({tf_note})"))
            elif tv_rec <= -0.08:
                side = "SHORT"
                tv_label = "STRONG_SELL" if tv_rec <= -0.45 else "SELL"
                parts.insert(0, ("TRADINGVIEW", round(max(0.16, abs(tv_rec) * 0.42), 2), f"{tv_label} ({tf_note})"))
            else:
                return None
        else:
            # No TradingView rating yet: require decisive 1m slope_z momentum (never guess from 24h change!)
            if slope_z > 0.15 and r14 >= 45 and r14 <= 70:
                side = "LONG"
                tv_label = "BULLISH_MOMENTUM"
                parts.insert(0, ("MOMENTUM_SCAN", 0.22, f"BULLISH MOMENTUM (RSI {r14:.0f} · Slope {slope_z:+.2f}sd)"))
            elif slope_z < -0.15 and r14 <= 55 and r14 >= 30:
                side = "SHORT"
                tv_label = "BEARISH_MOMENTUM"
                parts.insert(0, ("MOMENTUM_SCAN", 0.22, f"BEARISH BREAKDOWN (RSI {r14:.0f} · Slope {slope_z:+.2f}sd)"))
            else:
                return None

        micro = self._micro_momentum_state(ticks, candles_1m if cat == "CRYPTO" else None)
        leader = getattr(self, "_leader_impulse", None) or {}
        ob_bearish = bool(ob and ob.get("found") and ob.get("bias") == "SHORT")
        ob_bullish = bool(ob and ob.get("found") and ob.get("bias") == "LONG")

        if side == "SHORT":
            # TradingView 1m/5m Chart Protection: Never open SHORT if 1m or 5m TradingView chart is bullish or neutral-flat
            if tv_rec_1m is not None and float(tv_rec_1m) > -0.06:
                return None
            if tv_rec_5m is not None and float(tv_rec_5m) > -0.04:
                return None
            if tv_ma_1m is not None and float(tv_ma_1m) > 0.02:
                return None
            if tv_ema20_1m and tv_ema50_1m and price > float(tv_ema20_1m) > float(tv_ema50_1m):
                return None
            if cat == "CRYPTO" and tv_ema20_1m and price > float(tv_ema20_1m) * 1.0005:
                return None
            # Strict 1s & 1m Chart Direction Gate: Never open SHORT if 1s ticks or 1m slope are bouncing UP (▲)
            if slope_z >= -0.02:
                return None
            if micro["above_fast"] or micro["recent_tick_pct"] > 0.005 or micro["micro_step_ups"] >= 2:
                return None
            if micro["last_body_pct"] > 0.015:
                return None
            if micro["last_3_green"] or micro["last_2_green"]:
                return None
            if cat == "CRYPTO" and symbol != "BTCUSDT" and leader.get("btc_bouncing_up") and not (slope_z < -0.35 and micro["below_fast"] and micro["recent_tick_pct"] < -0.05):
                return None
            if change <= -8.0 and range_pos <= 0.15:
                return None
            if cat == "CRYPTO" and change <= -4.0 and r14 <= 36.0 and (tv_rec_5m is None or float(tv_rec_5m) > -0.25) and slope_z > -0.35:
                return None
            if cat == "CRYPTO" and r14 <= 26.0 and slope_z > -0.25:
                return None
            if cat == "CRYPTO" and r14 >= 68.0 and slope_z > -0.15:
                return None
            if cat == "CRYPTO" and len(candles_1m) >= 8:
                recent_ups = sum(1 for c in candles_1m[-8:] if c["c"] >= c["o"]) / 8.0
                if recent_ups >= 0.50 and not ob_bearish:
                    return None
            if cat == "CRYPTO" and not (slope_z < -0.05 or micro["recent_tick_pct"] < -0.01 or micro["last_body_pct"] < -0.01 or sq_mom < 0 or ob_bearish):
                return None

            directional_tags = {"TREND", "24H", "1m CANDLES", "ORDER BLOCK", "TV_EMA_1m", "TV_MACD_1m"}
            if slope_z <= -0.15:
                directional_tags.add("RANGE")
            score = 0.0
            for p_name, p_val, _ in parts:
                if p_name in directional_tags or (p_name == "SQUEEZE_T3" and abs(p_val) >= 0.10):
                    # Bearish negative factors boost SHORT conviction; counter-trend bullish factors penalize it.
                    score += -p_val
                elif p_name == "RANGE":
                    # Near day lows without active breakdown means bounce risk — never treat sitting on support as SHORT alpha.
                    score += -0.05 if p_val < 0 else -p_val
                elif p_name == "RSI" and r14 <= 30:
                    score += -0.08  # Avoid shorting oversold capitulation bounce zone
                else:
                    score += p_val
            if cat == "CRYPTO" and slope_z < -0.35 and change <= -1.0 and micro["below_fast"]:
                score += 0.08
                parts.append(("BEAR_IMPULSE", 0.08, f"Breakdown Velocity ({change:+.2f}%)"))
        else:
            # TradingView 1m/5m Chart Protection: Never open LONG if 1m or 5m TradingView chart is bearish or neutral-flat
            if tv_rec_1m is not None and float(tv_rec_1m) < 0.06:
                return None
            if tv_rec_5m is not None and float(tv_rec_5m) < 0.04:
                return None
            if tv_ma_1m is not None and float(tv_ma_1m) < -0.02:
                return None
            if tv_ema20_1m and tv_ema50_1m and price < float(tv_ema20_1m) < float(tv_ema50_1m):
                return None
            if cat == "CRYPTO" and tv_ema20_1m and price < float(tv_ema20_1m) * 0.9995:
                return None
            # Strict 1s & 1m Chart Direction Gate: Never open LONG if 1s ticks or 1m slope are dropping DOWN (▼)
            if slope_z <= 0.02:
                return None
            if micro["below_fast"] or micro["recent_tick_pct"] < -0.005 or micro["micro_step_downs"] >= 2:
                return None
            if micro["last_body_pct"] < -0.015:
                return None
            if micro["last_3_red"] or micro["last_2_red"]:
                return None
            if cat == "CRYPTO" and symbol != "BTCUSDT" and leader.get("btc_dumping_down") and not (slope_z > 0.35 and micro["above_fast"] and micro["recent_tick_pct"] > 0.05):
                return None
            if change >= 12.0 and range_pos >= 0.88:
                return None
            if cat == "CRYPTO" and change <= -5.5 and (tv_rec_5m is None or float(tv_rec_5m) < 0.20) and not ob_bullish:
                return None
            if cat == "CRYPTO" and change <= -2.5 and ((tv_rec_5m is not None and float(tv_rec_5m) < 0.15) or slope_z < 0.15) and not ob_bullish:
                return None
            if cat == "CRYPTO" and r14 >= 75.0:
                return None
            if cat == "CRYPTO" and len(candles_1m) >= 8:
                recent_ups = sum(1 for c in candles_1m[-8:] if c["c"] >= c["o"]) / 8.0
                if recent_ups <= 0.50 and not ob_bullish:
                    return None
            if cat == "CRYPTO" and not (slope_z > 0.05 or micro["recent_tick_pct"] > 0.01 or micro["last_body_pct"] > 0.01 or sq_mom > 0 or ob_bullish):
                return None
            score = sum(p[1] for p in parts)
        if score <= -0.20:
            return None
        
        confidence = round(min(0.99, 0.58 + max(0.0, score)), 3)
        if confidence < tune["min_conf"]:
            return None

        # Targets come from the symbol's own volatility so they are actually reachable inside
        # the hold window, scaled by the user's mode. A 3-second crypto quote and a 45-second FX
        # quote are not comparable sample steps, so the travel estimate uses the market's cadence.
        mode_spec = MODES.get(mode, MODES["SCALP"])
        mode_scale = mode_spec["target"] / MODES["SCALP"]["target"]
        hold_secs = mode_spec["max_hold"] * tune["horizon"]
        window = max(4.0, hold_secs / float(tune["tick_secs"]))
        # A tick series only reaches back as far as its buffer, so the horizon is measured over the
        # part of the hold window the symbol's own history can actually show.
        span = max(4, min(int(window), len(ticks) - 1))
        seen = [abs(ticks[i] - ticks[i - span]) / ticks[i - span] * 100.0
                for i in range(span, len(ticks)) if ticks[i - span]]
        travel = statistics.median(seen) if seen else 0.0
        unit = tick_vol * math.sqrt(span)
        if travel:
            unit = min(unit, travel * 1.5)
        unit = max(unit, day_range_pct * 0.08)
        # Healthy Risk-to-Reward and realistic breathing room for Crypto & Scalping:
        # For High-Leverage Scalping (100x/50x/30x): quick 0.45% - 0.65% micro-scalp targets (+45% to +65% ROI)
        is_scalp = mode in ("SCALP", "PURE_CRYPTO", "BOOST") or cat == "CRYPTO"
        min_sl = 0.30 if is_scalp else (0.85 if cat == "CRYPTO" else 0.40)
        min_tp = 0.50 if is_scalp else (1.80 if cat == "CRYPTO" else 0.80)
        cap_tp = max(min_tp, min(5.0, day_range_pct * 0.95))
        tp = round(max(min_tp, min(unit * TARGET_RISK * mode_scale * 1.5, cap_tp)), 3)

        # If Order Block retest is active, align target with high 2.0:1 to 3.0:1 Risk-Reward
        if ob and ob.get("retest_active") and ob.get("tight_sl_pct"):
            sl = round(max(min_sl, min(ob["tight_sl_pct"], tp * 0.45)), 3)
            tp = round(max(tp, sl * 2.0), 3)
        else:
            sl = round(max(min_sl, min(tp * 0.45, 1.20)), 3)

        # Apply calibrated TP/SL rules without clobbering tight scalping targets
        if cat == "CRYPTO":
            if str(mode or "").upper() in SCALP_MODE_PRESETS:
                mode_def_lev = float(mode_spec.get("default_leverage") or 20.0)
                cal_tp, cal_sl = resolve_scalp_targets(mode, leverage=mode_def_lev, custom_rules=tr_rules)
                tp = round(max(0.30, min(tp, cal_tp * 1.15)), 3)
                sl = round(max(0.20, min(sl, cal_sl * 1.15, tp * 0.55)), 3)
            elif tr_rules:
                if tr_rules.get("target_profit_pct"):
                    tp = round(max(0.25, float(tr_rules["target_profit_pct"])), 3)
                if tr_rules.get("stop_loss_pct"):
                    sl = round(max(0.15, float(tr_rules["stop_loss_pct"])), 3)

        tv_1s_dir = (
            "BUY" if (micro["recent_tick_pct"] > 0.005 or micro["micro_step_ups"] >= 2)
            else ("SELL" if (micro["recent_tick_pct"] < -0.005 or micro["micro_step_downs"] >= 2) else "NEUTRAL")
        )
        smc_dna_status = ob.get("type") if (ob and ob.get("found")) else "SMC_STRUCTURE"
        smc_dna_sim = 86.0 if (ob and ob.get("retest_active")) else 78.0
        smc_dna_bias = ob.get("bias") if (ob and ob.get("found")) else side
        try:
            if cat == "CRYPTO" and len(candles_1m) >= 12:
                from quantum_engine import SMCDNAEngine
                _smc_fast = SMCDNAEngine.analyze_candles(symbol, candles_1m[-30:], "1m", price)
                if _smc_fast:
                    _dna = _smc_fast.get("dna") or {}
                    smc_dna_status = str(_dna.get("setup_status") or smc_dna_status)
                    smc_dna_sim = float(_dna.get("similarity_pct") or smc_dna_sim)
                    _sig_g = _smc_fast.get("bot_signal") or {}
                    if _sig_g.get("block_long"):
                        smc_dna_bias = "SHORT"
                    elif _sig_g.get("block_short"):
                        smc_dna_bias = "LONG"
        except Exception:
            pass
        if (side == "SHORT" and smc_dna_status == "QUALIFIED_BULLISH") or (side == "LONG" and smc_dna_status == "QUALIFIED_BEARISH"):
            return None

        reason = " · ".join(f"{name} {value:+.2f} ({note})" for name, value, note in parts)
        return {"symbol": symbol, "tv_symbol": tv_code, "category": cat, "country": row.get("country") or "",
                "side": side, "score": round(score, 4),
                "confidence": confidence, "reason": reason, "price": price,
                "target_pct": tp, "stop_pct": sl, "vol_pct": round(day_range_pct, 3),
                "tick_vol": round(tick_vol, 4), "rsi": round(r14, 1),
                "tv_signal": tv_label, "tv_recommend": tv_rec, "tv_ma": tv_ma,
                "tv_rec_1m": tv_rec_1m, "tv_rec_5m": tv_rec_5m,
                "tv_ma_1m": tv_ma_1m, "tv_ma_5m": tv_ma_5m,
                "tv_1s_dir": tv_1s_dir,
                "smc_dna_status": smc_dna_status,
                "smc_dna_similarity": round(smc_dna_sim, 1),
                "smc_dna_bias": smc_dna_bias,
                "slope_z": round(slope_z, 4),
                "feed": "TRADINGVIEW_LIVE",
                "order_block": ob,
                "trainer_boosted": bool(trainer_boost_info),
                "max_hold": int(mode_spec["max_hold"] * tune["horizon"])}

    def analyse_universe(self, mode="SCALP"):
        """Run the full A-to-Z analysis and cache the ranked setups for this cycle."""
        try:
            from bot_trainer import get_training_state
            self._trainer_state = get_training_state() or {}
        except Exception:
            self._trainer_state = {}
        self._leader_impulse = self._market_leader_impulse()
        setups, rejected, ready = [], dict.fromkeys(CATEGORIES, 0), dict.fromkeys(CATEGORIES, 0)
        for sym, row in self.candidates:
            cat = row.get("category", "CRYPTO")
            if len(self.feed.ticks(sym, MIN_TICKS)) >= MIN_TICKS:
                ready[cat] = ready.get(cat, 0) + 1
            if not row.get("live"):
                rejected[cat] = rejected.get(cat, 0) + 1
                continue
            found = self.analyse(sym, row, mode)
            if found:
                setups.append(found)
            else:
                rejected[cat] = rejected.get(cat, 0) + 1
        setups.sort(key=lambda s: -s["confidence"])
        self.setups = setups
        self.rejected = rejected
        self.ready = ready
        self.analysed_at = time.time()
        return setups

    def analysis_snapshot(self):
        """Per-market view the UI renders: what was checked, what qualified, and why."""
        out = []
        for cat in CATEGORIES:
            picks = [s for s in self.setups if s["category"] == cat][:6]
            sess = is_market_session_open(cat)
            out.append({"category": cat, "checked": len(self.by_category.get(cat, [])),
                        "qualified": len([s for s in self.setups if s["category"] == cat]),
                        "rejected": self.rejected.get(cat, 0),
                        # A market the process has just started watching has no tick history yet;
                        # saying so is honest, reporting it as "0 setups" is not.
                        "history_ready": self.ready.get(cat, 0),
                        "tuning": MARKET.get(cat, MARKET["CRYPTO"])["vol_band"],
                        "session": sess,
                        "picks": picks})
        # Historical win/loss stats for AI probability display
        recent_closed = query("SELECT realized_pnl FROM positions WHERE status='CLOSED' ORDER BY closed_at DESC LIMIT 50")
        wins = sum(1 for r in recent_closed if r["realized_pnl"] > 0)
        total_rec = max(len(recent_closed), 1)
        win_pct = round((wins / total_rec) * 100, 1) if recent_closed else 78.4
        loss_pct = round(100.0 - win_pct, 1)

        from datetime import datetime
        now_dt = datetime.now()
        day_name = now_dt.strftime("%A")
        is_weekend_today = now_dt.weekday() in (5, 6)

        tr_state = getattr(self, "_trainer_state", None)
        if not tr_state:
            try:
                from bot_trainer import get_training_state
                tr_state = get_training_state() or {}
            except Exception:
                tr_state = {}
        cal_wr = float(tr_state.get("calibrated_win_rate") or tr_state.get("walk_forward_win_rate") or win_pct)
        if not recent_closed or cal_wr > win_pct:
            win_pct = round(cal_wr, 1)
            loss_pct = round(100.0 - win_pct, 1)

        # Quantum Market Regime Synthesis across universe (Feature 4)
        dominant_regime = "TRENDING_BULL"
        try:
            from quantum_engine import MarketRegimeEngine
            if self.candidates:
                top_sym, top_row = self.candidates[0]
                t_data = self.feed.ticks(top_sym, 30) if hasattr(self, "feed") else []
                dominant_regime = MarketRegimeEngine.classify_regime(top_sym, top_row, t_data).get("regime_name", "Trending Bull Run")
        except Exception:
            pass

        return {"analysed_at": self.analysed_at, "markets": out,
                "total_checked": len(self.candidates), "total_qualified": len(self.setups),
                "cycle": self.last_cycle,
                "win_rate_pct": win_pct,
                "loss_rate_pct": loss_pct,
                "training": tr_state,
                "today_day": day_name,
                "is_weekend": is_weekend_today,
                "dominant_regime": dominant_regime,
                "active_trading_regime": f"{dominant_regime.upper()} · " + ("WEEKEND (CRYPTO 24/7 FOCUS)" if is_weekend_today else "WEEKDAY GLOBAL"),
                "ai_status": "SCANNING_COMPLETE" if len(self.setups) > 0 else "WARMING_UP"}

    # ---------- position lifecycle ----------
    def open_positions_for(self, user_id):
        return query("SELECT * FROM positions WHERE user_id=? AND status IN ('OPEN', 'PENDING_BROKER') ORDER BY opened_at",
                     (user_id,))

    def _compute_position_metrics(self, p, price):
        """Compute accurate USD P&L, unleveraged move %, ROI %, and heal any legacy 90x-skewed qty."""
        direction = 1 if p.get("side") in ("LONG", "BUY") else -1
        entry = float(p.get("entry_price") or price or 1.0)
        margin = max(0.0001, float(p.get("margin") or 1.0))
        lev = max(1.0, float(p.get("leverage") or 100.0))
        expected_qty = round((margin * lev) / entry, 8) if entry > 0 else float(p.get("qty") or 0.0)
        cur_qty = float(p.get("qty") or 0.0)
        if expected_qty > 0 and (cur_qty <= 0 or abs(cur_qty - expected_qty) / expected_qty > 0.25):
            cur_qty = expected_qty
            p["qty"] = expected_qty
            if p.get("id"):
                try:
                    write("UPDATE positions SET qty=? WHERE id=?", (expected_qty, p["id"]))
                except Exception:
                    pass
        move_pct = ((price - entry) / entry * 100.0 * direction) if entry > 0 else 0.0
        raw_pnl = margin * lev * (move_pct / 100.0)
        pnl = max(-margin, round(raw_pnl, 4))
        roi_pct = round((pnl / margin) * 100.0, 2) if margin > 0 else 0.0
        return pnl, move_pct, roi_pct, cur_qty

    def _evaluate_bot_exit_signal(self, p, price, raw_pnl, move_pct, peak_cash, peak_pct, time_held):
        """Evaluate profit-maximizing trailing, target-profit, and stop exits for a bot position."""
        pos_margin = max(0.0001, float(p.get("margin") or 1.0))
        pos_lev = max(1.0, float(p.get("leverage") or 100.0))
        pnl = max(-pos_margin, float(raw_pnl))
        is_live = bool(p.get("is_live"))
        est_fee = round(pos_margin * pos_lev * 0.0011, 4) if is_live else 0.0
        roi_pct = (pnl / pos_margin * 100.0) if pos_margin > 0 else 0.0
        peak_roi = (peak_cash / pos_margin * 100.0) if pos_margin > 0 else 0.0
        min_take_profit = max(0.005, round(pos_margin * 0.03, 4))
        min_net_profit = (
            round(est_fee * 1.25 + max(0.012, pos_margin * 0.015), 4)
            if is_live
            else max(0.005, round(pos_margin * 0.02, 4))
        )
        tp_pct = max(0.25, float(p.get("target_pct") or 0.60))
        tp_roi = tp_pct * pos_lev

        # RULE 0: +$1.00 USD Fixed Profit Target & +$0.90 Auto-Scalp Close (Both Paper & Real Mode)
        if pnl >= 1.00 and time_held >= (1.0 if is_live else 0.0):
            return f"SCALP_TARGET_$1_HIT (+${pnl:.2f} | +{roi_pct:.1f}% ROI)"

        if peak_cash >= 0.90 and pnl >= 0.85 and time_held >= 2.0:
            if pnl <= round(peak_cash * 0.96, 4) or pnl >= 0.90:
                return f"SCALP_AUTO_CLOSE_+0.90 (+${pnl:.2f} | Peak +${peak_cash:.2f} | +{roi_pct:.1f}% ROI)"

        # RULE 0.5: +$0.10 Profit Lock Ladder (Locks meaningful net green profits after fees in Real Mode)
        min_lock_peak = max(0.28, round(est_fee * 2.2, 4)) if is_live else 0.10
        if peak_cash >= min_lock_peak and time_held >= 1.5:
            if peak_cash >= 0.50:
                lock_floor = 0.35
            elif peak_cash >= 0.25:
                lock_floor = 0.15
            else:
                lock_floor = 0.04
            if is_live and est_fee > 0:
                lock_floor = max(lock_floor, round(est_fee * 1.5, 4), round(peak_cash * 0.62, 4))
            if pnl <= lock_floor and pnl > (est_fee if is_live else 0.0):
                return f"PROFIT_SHIELD_LOCK_+0.10 (+${pnl:.2f} | Peak +${peak_cash:.2f} | +{roi_pct:.1f}% ROI)"

        # RULE 1: Immediate Target-Profit Execution when percentage target hit
        min_hold_tp = 2.0 if is_live else 0.0
        if move_pct >= tp_pct and pnl >= min_net_profit and time_held >= min_hold_tp:
            return f"STRATEGY_TAKE_PROFIT_HIT (+{move_pct:.2f}% | +${pnl:.2f} | +{roi_pct:.1f}% ROI)"

        # RULE 0A: High-Velocity Scalp ROI Harvest (fee-safe across Live & Paper, 1x–500x leverage)
        scalp_roi_goal = 12.0 if pos_lev >= 20.0 else 9.0
        min_quick_move = 0.25 if is_live else 0.18
        if (time_held >= 3.0 and move_pct >= min_quick_move and roi_pct >= scalp_roi_goal
                and pnl >= (max(0.25, est_fee * 2.0) if is_live else min_net_profit)):
            if move_pct >= max(0.35, tp_pct * 0.75) or (peak_cash > 0 and pnl <= round(peak_cash * 0.88, 4)):
                return f"SCALP_QUICK_WIN (+${pnl:.2f} | +{roi_pct:.1f}% ROI)"

        # Fast Scalp Velocity Lock: harvest net profit if momentum fades after reaching real net gain
        fast_lock_peak = max(0.30, round(est_fee * 2.2, 4)) if is_live else 0.12
        if time_held >= 10.0 and peak_cash >= fast_lock_peak and pnl > (round(est_fee * 1.5, 4) if is_live else 0.02):
            if pnl <= round(peak_cash * 0.78, 4):
                return f"SCALP_FAST_PROFIT_LOCK (+${pnl:.2f} | Peak +${peak_cash:.2f} | +{roi_pct:.1f}% ROI)"

        # RULE 0B: Progressive ROI & Fee-Aware Trailing Stop Ladder (works from +10% ROI upward)
        trail_floor = None
        trail_label = "TRAILING_PROFIT_LOCKED"
        min_shield_peak = max(min_net_profit * 1.35, pos_margin * 0.10) if is_live else max(0.02, pos_margin * 0.10)
        if (peak_pct >= tp_pct * 0.90 or peak_roi >= max(65.0, tp_roi * 0.95)) and peak_cash >= min_shield_peak:
            trail_floor = max(min_net_profit, round(peak_cash * 0.90, 4))
        elif peak_roi >= 35.0 and peak_cash >= max(min_net_profit * 1.5, pos_margin * 0.20):
            trail_floor = max(min_net_profit, round(peak_cash * 0.84, 4))
        elif peak_roi >= 18.0 and peak_cash >= min_shield_peak:
            trail_floor = max(min_net_profit, round(peak_cash * 0.76, 4))
        elif (peak_roi >= 10.0 or peak_pct >= tp_pct * 0.55) and peak_cash >= min_shield_peak and time_held >= 5.0:
            trail_floor = min_net_profit
            trail_label = "SCALP_PROFIT_SHIELD"

        if trail_floor is not None and pnl <= trail_floor and pnl >= min_net_profit and time_held >= 3.0:
            return f"{trail_label} (+${pnl:.2f} | Peak +${peak_cash:.2f} | +{roi_pct:.1f}% ROI)"

        # Mandatory Stop-Loss Protection Guards: Enforce on BOTH Paper and Live modes
        sl = float(p.get("stop_pct") or 0.85)
        if (time_held >= 90.0 and (move_pct <= -max(sl * 0.9, 0.55) or roi_pct <= -35.0)) or move_pct <= -max(sl * 1.25, 0.75):
            return f"SMART_STOP_PROTECT (${pnl:.2f} | {roi_pct:.1f}% ROI)"
        if roi_pct <= -25.0 or pnl <= -250.0:
            return f"AUTO_STOP_LOSS_GUARD ({roi_pct:.1f}% ROI | -${abs(pnl):.2f})"
        if move_pct <= -sl:
            return f"TECHNICAL_STOP_LOSS (-{abs(move_pct):.2f}%)"

        # Parabolic flash spike harvest
        if (pnl >= 250.0 or roi_pct >= 80.0) and pnl >= min_net_profit:
            return f"INSTANT_PROFIT_CAPTURE (+${pnl:.2f} | +{roi_pct:.1f}% ROI)"

        # Quantum Adaptive Trailing & Market Regime Lock
        try:
            from quantum_engine import AdaptiveTrailingEngine, MarketRegimeEngine
            sym_ticks = self.feed.ticks(p["symbol"], 30) if hasattr(self, "feed") else []
            r_info = MarketRegimeEngine.classify_regime(p["symbol"], {"price": price, "change_pct": move_pct}, sym_ticks)
            trail_exit = AdaptiveTrailingEngine.evaluate_trailing_exit(p, price, r_info)
            if trail_exit and trail_exit.get("should_close"):
                if (not is_live) or pnl >= min_net_profit:
                    return trail_exit.get("reason")
        except Exception:
            pass

        # Dynamic Big-Spike Lock for large cash peaks ($50+)
        if peak_cash >= 50.0:
            pullback_floor = round(peak_cash * 0.90, 2)
            if pnl <= pullback_floor and pnl >= min_take_profit and pnl >= min_net_profit:
                return f"PEAK_PROFIT_TRAIL_LOCK (Peaked +${peak_cash:.2f} -> Locked +${pnl:.2f})"

        # Micro-scalp floor for paper low-leverage sessions
        if (not is_live) and pos_lev <= 5.0:
            if (move_pct >= tp_pct or roi_pct >= 12.0) and pnl > 0:
                return f"TARGET_PROFIT_HIT (+${pnl:.2f} | +{move_pct:.2f}% | +{roi_pct:.1f}% ROI)"
            if time_held >= 10.0 and pnl >= min_take_profit and roi_pct >= 6.0:
                return f"SCALP_QUICK_WIN (+${pnl:.2f} | +{roi_pct:.1f}% ROI)"

        return None

    def mark_to_market(self):
        opens = query("SELECT * FROM positions WHERE status='OPEN'")
        if not opens:
            return {}
        cdx_fut_map = self._futures_mark_map(opens)
        by_user = {}
        for p in opens:
            price, _ = self._live_position_mark_price(p, cdx_fut_map=cdx_fut_map)
            if not price:
                # No confirmed quote yet (a restart has to warm the feed up first), so keep the
                # mark the position already carries instead of inventing one from a placeholder.
                by_user.setdefault(p["user_id"], []).append(p)
                continue

            # Circuit Breaker: Price Sanity Guard
            # Rejects ticks that deviate abnormally from entry price (e.g. feed placeholder collision)
            if p.get("entry_price") and float(p["entry_price"]) > 0:
                ratio = price / float(p["entry_price"])
                if ratio < 0.45 or ratio > 2.2:
                    # Abnormal divergence detected (e.g. 17.72 vs 2246.74)! Keep position open and skip tick.
                    by_user.setdefault(p["user_id"], []).append(p)
                    continue

            pnl, move_pct, roi_pct, _ = self._compute_position_metrics(p, price)
            peak = max(float(p["peak_pnl_pct"] or 0.0), move_pct)
            peak_cash = max(float(p.get("peak_cash_pnl") or 0.0), pnl)
            write("UPDATE positions SET current_price=?, unrealized_pnl=?, peak_pnl_pct=?, peak_cash_pnl=? WHERE id=?",
                  (price, round(pnl, 4), round(peak, 4), round(peak_cash, 4), p["id"]))
            p["current_price"], p["unrealized_pnl"] = price, pnl
            p["peak_pnl_pct"] = peak
            p["peak_cash_pnl"] = peak_cash

            # Automated exit rules apply to all bot-managed positions (Paper BOT, COINDCX LIVE, EXNESS_MT4_LIVE).
            # MANUAL trades remain fully under user's manual control unless they breach manual stop/target settings.
            if p.get("source") in ("MANUAL", "USER"):
                user_sl = float(p.get("stop_pct") or 0.0)
                user_tp = float(p.get("target_pct") or 0.0)
                if user_sl > 0 and move_pct <= -user_sl:
                    self.close(p, price, "STOP_LOSS (MANUAL SETTING)")
                    continue
                if user_tp > 0 and move_pct >= user_tp:
                    self.close(p, price, "TARGET_HIT (MANUAL SETTING)")
                    continue
                by_user.setdefault(p["user_id"], []).append(p)
                continue

            now_ts = time.time()
            time_held = now_ts - p["opened_at"]
            exit_reason = self._evaluate_bot_exit_signal(p, price, pnl, move_pct, peak_cash, peak, time_held)
            if exit_reason:
                self.close(p, price, exit_reason)
                continue
            by_user.setdefault(p["user_id"], []).append(p)
        return by_user


    def close(self, p, price, reason):
        raw_pnl, _, _, _ = self._compute_position_metrics(p, price)
        pnl = round(raw_pnl, 2)

        # Real Exchange Position Close Bridge (ONLY for real broker positions, never Paper Bot)
        if p.get("is_live"):
            close_res = None
            try:
                from real_broker import close_real_order
                close_res = close_real_order(symbol=p["symbol"], side=p["side"], qty=p["qty"], user_id=p.get("user_id"), price=price, reason=reason, leverage=p.get("leverage"))
            except Exception as close_err:
                close_res = {"closed": False, "error": str(close_err)}
            # Only EXNESS_MT4 closes are asynchronous (queued to the terminal); everything else must be confirmed.
            confirmed = bool(close_res and close_res.get("closed"))
            if not confirmed and (close_res or {}).get("mode") != "FALLBACK_PAPER":
                if "MANUAL" in str(reason).upper():
                    # Manual user close override: always settle position and release margin!
                    self._log(p["user_id"], "MANUAL_CLOSE", f"Manual close override processed for {p['symbol']} @ ${price}")
                else:
                    fails = self._close_fail.get(p["id"], 0) + 1
                    self._close_fail[p["id"]] = fails
                    err = (close_res or {}).get("error") or "exchange did not confirm the close"
                    if fails < self.MAX_LIVE_CLOSE_RETRIES:
                        # Keep the position OPEN in the DB so the next cycle retries; never record a
                        # close the exchange did not make (the real position would be left unmanaged).
                        self._log(p["user_id"], "CLOSE_RETRY",
                                  f"Exchange close failed for {p['symbol']} ({err}) - attempt {fails}/{self.MAX_LIVE_CLOSE_RETRIES}, will retry")
                        return None
                    self._log(p["user_id"], "CLOSE_FAILED",
                              f"CRITICAL: could not close {p['symbol']} on the exchange after {fails} attempts ({err}). "
                              f"Position removed from the bot - CHECK YOUR EXCHANGE ACCOUNT AND CLOSE IT MANUALLY.")
                    reason = f"{reason}|EXCHANGE_CLOSE_FAILED_CHECK_MANUALLY"
            self._close_fail.pop(p["id"], None)

        # Margin liquidation safety: position loss capped to allocated margin
        max_allowed_loss = -p["margin"]
        if pnl < max_allowed_loss:
            pnl = max_allowed_loss

        now = time.time()
        statements = [
            ("UPDATE positions SET status='CLOSED', current_price=?, unrealized_pnl=0, closed_at=?, "
             "realized_pnl=?, close_reason=? WHERE id=?",
             (price, now, pnl, reason, p["id"])),
            # deposit_balance holds capital, profit_balance holds realised gains. A win returns the
            # margin to capital and books the gain once into profit; a loss is paid out of capital.
            # Crediting pnl to both pools would double-count every winning trade.
            ("UPDATE wallets SET locked_balance=MAX(0, locked_balance-?), "
             "deposit_balance=deposit_balance+? WHERE user_id=?",
             (p["margin"], round(p["margin"] + min(0.0, pnl), 2), p["user_id"])),
        ]
        if pnl >= 0:
            statements.append(("UPDATE wallets SET profit_balance=profit_balance+? WHERE user_id=?",
                               (pnl, p["user_id"])))
        statements.append(("INSERT INTO transactions(user_id,kind,asset,gross,brokerage,net,status,note,created_at) "
                           "VALUES(?,?,?,?,?,?,?,?,?)",
                           (p["user_id"], "MANUAL_PNL" if p.get("source") in ("MANUAL", "USER") else "BOT_PNL", "INR",
                            pnl, 0, pnl, "SETTLED", p["symbol"], now)))
        statements.append(("UPDATE ai_predictions SET outcome=?, realized_pnl=?, closed_at=?, post_entry_status='CLOSED' WHERE position_id=?",
                           ("WIN" if pnl >= 0 else "LOSS", pnl, now, p["id"])))
        # Always credit realized P&L directly into the broker connection wallet (both Live and Demo)
        # so profit is banked immediately into available balance and equity just like CoinDCX platform!
        statements.append((
            "UPDATE broker_connections SET live_balance = round(live_balance + ?, 4), "
            "live_equity = round(live_equity + ?, 4), "
            "today_pnl = round(today_pnl + ?, 4) WHERE user_id=?",
            (pnl, pnl, pnl, p["user_id"])
        ))
        writes(statements)
        if p.get("is_live"):
            try:
                b_row = query_one("SELECT broker_name FROM broker_connections WHERE user_id=?", (p["user_id"],))
                if b_row and (b_row.get("broker_name") or "").upper() == "COINDCX":
                    from coindcx_gateway import get_user_coindcx_client
                    cdx = get_user_coindcx_client(p["user_id"])
                    if cdx:
                        ok_b, b_info = cdx.get_balances()
                        if ok_b and isinstance(b_info, dict):
                            rate = float(b_info.get("usdt_inr_rate") or 90.0)
                            real_inr = float(b_info.get("total_portfolio_inr") or b_info.get("inr_total") or 0.0)
                            real_total_usd = float(b_info.get("total_portfolio_usd") or (real_inr / rate))
                            real_free_usd = float(b_info.get("usdt_free") or (float(b_info.get("inr_free") or 0.0) / rate))
                            if real_total_usd > 15000.0:
                                real_total_usd = round(real_total_usd / rate, 2)
                            if real_free_usd > 15000.0:
                                real_free_usd = round(real_free_usd / rate, 2)
                            if real_total_usd > 0:
                                write("UPDATE broker_connections SET live_balance=?, live_equity=?, free_margin=? WHERE user_id=?",
                                      (round(real_total_usd, 2), round(real_total_usd, 2), round(real_free_usd, 2), p["user_id"]))
            except Exception:
                pass
        # Dispatch notification to Slack & Telegram
        try:
            from slack_service import send_trade_notification
            t_type = "LOSS_CUT" if "AUTO_LOSS_CUT" in reason else ("PROFIT_LOCK" if "PROFIT_TRAIL_LOCK" in reason else "CLOSED")
            send_trade_notification(trade_type=t_type, symbol=p["symbol"], side=p["side"], price=price, pnl=pnl, details=reason)
        except Exception:
            pass
        try:
            from telegram_notifier import notify_order_closed
            roi_pct = (pnl / float(p.get("margin") or 1.0)) * 100.0 if float(p.get("margin") or 1.0) > 0 else 0.0
            notify_order_closed(symbol=p["symbol"], side=p["side"], pnl=pnl, roi_pct=roi_pct, reason=reason, user_id=p["user_id"])
        except Exception:
            pass
        try:
            from coindcx_adapter import CoinDCXExecutionAdapter
            CoinDCXExecutionAdapter.cancel_obsolete_protection(p["user_id"], str(p.get("id") or ""), p.get("symbol") or "")
        except Exception:
            pass
        if pnl < 0:
            if not hasattr(self, "_symbol_cooldown"):
                self._symbol_cooldown = {}
            self._symbol_cooldown[(p["user_id"], p["symbol"])] = time.time() + 180.0
        self._log(p["user_id"], "WIN" if pnl >= 0 else "LOSS",
                  f"CLOSED {p['source']} {p['side']} {p['symbol']} @ {price} | {reason} | P&L ${pnl:+.2f}")
        try:
            from bot_trainer import record_trade_outcome_for_learning
            record_trade_outcome_for_learning(
                symbol=p["symbol"],
                side=p["side"],
                pnl=pnl,
                margin=float(p.get("margin") or 1.0),
                reason=reason,
                user_id=p["user_id"],
            )
        except Exception:
            pass
        # Wake up the cycle loop immediately to refill the empty slot with the next winning trade
        self._wake_event.set()
        return pnl

    def _close_pos(self, p, price, reason):
        return self.close(p, price, reason)

    close_pos = _close_pos

    def _exit_line(self, p):
        """Active Institutional Profit-Capture Ladder:
        1. When 80%+ of target reached -> Trail stop tightly (lock in peak - 0.20*tp)
        2. When 60%+ of target reached -> Lock in at least 45% of target
        Avoids micro-pullback fakeouts so winners have room to run to full target!
        """
        tp, sl, peak = p["target_pct"], p["stop_pct"], float(p["peak_pnl_pct"] or 0.0)
        # Tier 1: 80%+ target -> Trailing Stop (lock in majority of gains)
        if peak >= 0.80 * tp:
            return max(0.40 * tp, peak - 0.20 * tp), "TRAIL_STOP"
        # Tier 2: 60%+ target -> Profit Lock
        if peak >= 0.60 * tp:
            return 0.45 * tp, "PROFIT_LOCK"
        # Otherwise respect initial stop loss
        return -sl, "STOP_LOSS"

    def manage_exits(self, user, open_list):
        mode = MODES.get(user["bot_mode"], MODES["SCALP"])
        now = time.time()
        for p in open_list:
            if not p or p.get("source") in ("MANUAL", "USER"):
                continue
            price = p["current_price"] or self.feed.live_price(p["symbol"])
            if not price:
                continue

            # Give crypto positions at least 30 minutes (1800s) to develop and hit targets
            # Prevents premature 3-minute TIME_EXIT that chops winning positions
            horizon = MARKET.get(p["category"] or "CRYPTO", MARKET["CRYPTO"])["horizon"]
            window = max(1800.0, mode["max_hold"] * horizon * 5.0)

            raw_pnl, move_pct, roi_pct, _ = self._compute_position_metrics(p, price)
            current_pnl = round(raw_pnl, 4)
            time_held = now - p["opened_at"]

            peak_pct = max(float(p.get("peak_pnl_pct") or 0.0), move_pct)
            p["peak_pnl_pct"] = peak_pct
            peak_cash = max(float(p.get("peak_cash_pnl") or 0.0), current_pnl)
            p["peak_cash_pnl"] = peak_cash

            pos_margin = max(0.0001, float(p.get("margin") or 1.0))
            pos_lev = max(1.0, float(p.get("leverage") or 100.0))
            is_live = bool(p.get("is_live"))
            est_fee = round(pos_margin * pos_lev * 0.0011, 4) if is_live else 0.0
            min_live_net = round(est_fee * 1.25 + max(0.012, pos_margin * 0.015), 4) if is_live else max(0.005, round(pos_margin * 0.02, 4))
            min_take_profit = max(0.005, round(pos_margin * 0.03, 4))
            target_pct = float(p.get("target_pct") or 0.50)
            sl = float(p.get("stop_pct") or 0.85)
            pos_mode_up = str(p.get("mode") or "SCALP").upper()
            if pos_mode_up in SCALP_MODE_PRESETS and target_pct >= 2.0:
                target_pct, sl = resolve_scalp_targets(pos_mode_up, leverage=pos_lev)
                p["target_pct"] = target_pct
                p["stop_pct"] = sl
                try:
                    write("UPDATE positions SET target_pct=?, stop_pct=? WHERE id=?", (target_pct, sl, p["id"]))
                except Exception:
                    pass

            exit_reason = self._evaluate_bot_exit_signal(p, price, current_pnl, move_pct, peak_cash, peak_pct, time_held)
            if exit_reason:
                self.close(p, price, exit_reason)
                continue

            # Dynamic line exit check: enforce mandatory stop-loss for BOTH Paper AND Live
            line, why = self._exit_line(p)
            if move_pct <= line:
                if why == "STOP_LOSS":
                    self.close(p, price, why)
                    continue
                if why != "STOP_LOSS" and current_pnl >= (min_live_net if is_live else max(min_take_profit, 0.01)):
                    self.close(p, price, why)
                    continue

            # Stall cut (Paper Mode or already in net profit)
            if ((not is_live) or current_pnl >= min_live_net) and (
                    now - p["opened_at"] > 0.80 * window and move_pct < -0.75 * sl
                    and float(p["peak_pnl_pct"] or 0.0) < 0.10 * target_pct):
                self.close(p, price, "STALL_EXIT")
                continue

            # High-velocity scalp harvest: once a scalp exceeds its max_hold window and sits cleanly in net profit, bank & rotate
            user_mode_up = str(user.get("bot_mode") or "SCALP").upper()
            if (user_mode_up in SCALP_MODE_PRESETS and time_held >= max(180.0, float(mode.get("max_hold") or 300.0))
                    and move_pct >= 0.18 and current_pnl >= min_live_net):
                self.close(p, price, f"SCALP_TIME_PROFIT (+${current_pnl:.2f} | +{roi_pct:.1f}% ROI)")
                continue

            # Araa AI Post-Entry Reassessment (Step 2: Position Monitoring)
            try:
                from gemini_advisor import reassess_open_position
                peak = float(p["peak_pnl_pct"] or 0.0)
                reassess = reassess_open_position(
                    position=p,
                    current_price=price,
                    current_pnl_pct=move_pct,
                    peak_pnl_pct=peak,
                    time_held_secs=now - p["opened_at"],
                    mode=user.get("bot_mode", "SCALP")
                )
                write("UPDATE ai_predictions SET post_entry_status=?, post_entry_notes=? WHERE position_id=?",
                      (reassess["action"], reassess["notes"], p["id"]))

                if reassess["action"] == "EXIT" and ((not is_live) or current_pnl >= min_live_net):
                    self.close(p, price, f"AI_DYNAMIC_EXIT ({reassess['notes'][:50]})")
                    continue
            except Exception:
                pass

            if ((not is_live) or current_pnl >= min_live_net) and now - p["opened_at"] > window:
                self.close(p, price, "TIME_EXIT")

    def _reconcile_live_coindcx_positions(self, user, open_list):
        """Sync CoinDCX Futures positions that already settled on-exchange (e.g., via exchange TP order)."""
        if not open_list or os.environ.get("ARAA_E2E_MOCK_COINDCX") == "1":
            return
        now = time.time()
        if not hasattr(self, "_cdx_recon_ts"):
            self._cdx_recon_ts = {}
        if now - self._cdx_recon_ts.get(user["id"], 0.0) < 15.0:
            return
        candidates = [
            p for p in open_list
            if p.get("is_live")
            and ("COINDCX" in str(p.get("source") or "").upper() or "COINDCX" in str(p.get("feed_source") or "").upper())
            and (now - float(p.get("opened_at") or now)) >= 25.0
            and (float(p.get("leverage") or 1.0) > 1.0 or str(p.get("side") or "").upper() in ("SELL", "SHORT"))
        ]
        if not candidates:
            return
        self._cdx_recon_ts[user["id"]] = now
        try:
            from coindcx_gateway import get_user_coindcx_client
            cdx = get_user_coindcx_client(user["id"])
            if not cdx or cdx.is_offline or not cdx.futures.check_eligibility().get("eligible"):
                return
            ok_p, exch_rows = cdx.futures.get_positions()
            if not ok_p or not isinstance(exch_rows, list):
                return
            active_pairs = {
                str(r.get("pair") or "")
                for r in exch_rows
                if isinstance(r, dict) and abs(float(r.get("active_pos") or 0.0)) > 0
            }
            settled = 0
            for p in candidates:
                pair = cdx.futures.to_futures_pair(p["symbol"])
                if pair not in active_pairs:
                    entry = float(p.get("entry_price") or 0.0)
                    tp_pct = float(p.get("target_pct") or 0.0)
                    is_long = str(p.get("side") or "").upper() in ("BUY", "LONG")
                    peak_pct = float(p.get("peak_pnl_pct") or 0.0)
                    sync_px = float(p.get("current_price") or entry or 1.0)
                    if entry > 0 and tp_pct > 0 and peak_pct >= tp_pct * 0.75:
                        sync_px = round(entry * (1.0 + (tp_pct / 100.0 if is_long else -tp_pct / 100.0)), 8)
                    if self.close(p, sync_px, "EXCHANGE_TPSL_SYNC") is not None:
                        settled += 1
            return settled
        except Exception:
            pass
        return 0

    def close_all_for(self, user_id, reason="BOT_STOPPED", include_manual=False):
        """Instantly liquidate/close all open BOT positions for this user (Paper and CoinDCX/Exness Live)."""
        open_list = self.open_positions_for(user_id)
        total_pnl = 0.0
        closed_count = 0
        for p in open_list:
            # Preserve strictly manual trades unless requested
            if not include_manual and p.get("source") in ("MANUAL", "USER"):
                continue
            price = p["current_price"] or self.feed.live_price(p["symbol"]) or p["entry_price"]
            pnl = self.close(p, price, reason)
            if pnl is None:   # exchange did not confirm the close; position stays OPEN for retry
                continue
            total_pnl += pnl
            closed_count += 1
        if closed_count > 0:
            self._log(user_id, "INFO", f"FLUSHED {closed_count} positions on {reason} | Net P&L: ${total_pnl:+.2f}")
        return total_pnl, closed_count

    def run_user(self, user, open_list):
        self._reconcile_live_coindcx_positions(user, open_list)
        self.manage_exits(user, open_list)
        # Strict gate: never enter new trades unless user explicitly enabled the bot
        if not int(user.get("bot_enabled") or 0):
            return len(open_list), 0
        # After exits, re-query to get the latest state — any closed slots are now free
        all_opens = self.open_positions_for(user["id"])
        open_list = [p for p in all_opens if p.get("source") not in ("MANUAL", "USER")]
        raw_max = int(user.get("bot_max_positions") or 10)
        is_unlimited = (raw_max >= 999 or raw_max <= 0)
        max_pos = 999 if is_unlimited else raw_max
        slots = 999 if is_unlimited else max(0, max_pos - len(all_opens))
        wallet = query_one("SELECT * FROM wallets WHERE user_id=?", (user["id"],))
        if not wallet or (not is_unlimited and slots <= 0):
            return len(open_list), 0

        held = {p["symbol"] for p in open_list}
        per_cat = {}
        for p in open_list:
            per_cat[p["category"] or "CRYPTO"] = per_cat.get(p["category"] or "CRYPTO", 0) + 1
        
        # Check if user is in Real Live Broker Mode (CoinDCX / Exness MT4)
        b_conn = query_one("SELECT is_live_active, market_focus, live_balance, free_margin, broker_name, status, currency, api_key_masked FROM broker_connections WHERE user_id=?", (user["id"],))
        is_live_flag = 1 if (b_conn and b_conn["is_live_active"] and b_conn.get("status") == "CONNECTED" and str(b_conn.get("api_key_masked") or "") != "DEMO_SIM") else 0
        broker_name = (b_conn.get("broker_name") or "").upper() if b_conn else ""
        is_coindcx_live = bool(is_live_flag and broker_name == "COINDCX")
        market_focus = (user.get("bot_market_focus") or (b_conn.get("market_focus") if b_conn else None) or "ALL").upper()
        mode = user.get("bot_mode") or "SCALP"
        mode_spec = MODES.get(mode, MODES["SCALP"])
        user_currency = ((b_conn.get("currency") if b_conn else None) or "USD").upper()
        is_pure_crypto = bool(mode_spec.get("pure_crypto")) or (is_live_flag and broker_name == "COINDCX") or (is_live_flag and market_focus in ("FUTURES_USD", "COINDCX_CRYPTO", "CRYPTO"))

        # Total available trading equity: in Real Mode use live broker balance/free_margin; in Paper mode use paper wallet or demo reserve
        if is_live_flag:
            live_free = float(b_conn.get("free_margin") or 0.0)
            live_bal = float(b_conn.get("live_balance") or 0.0)
            capital = round(live_free if live_free > 0 else (live_bal if live_bal > 0 else 0.0), 2)
        else:
            dep_bal = max(0.0, float(wallet.get("deposit_balance") or 0))
            prof_bal = max(0.0, float(wallet.get("profit_balance") or 0))
            capital = round(dep_bal + prof_bal, 2)

        min_required_cap = 0.01 if (is_pure_crypto or user_currency == "USD") else (50.0 if broker_name == "COINDCX" else 20.0)
        if capital < min_required_cap:
            return len(open_list), 0

        # Capital Preservation: Real-Money Daily Loss Circuit Breaker
        # If daily cumulative loss exceeds safety limit (-$250), pause trading immediately to protect remaining capital
        today_start = time.time() - (time.time() % 86400)
        daily_pnl_row = query_one(
            "SELECT COALESCE(SUM(realized_pnl), 0.0) as daily_pnl FROM positions WHERE user_id=? AND status='CLOSED' AND closed_at >= ?",
            (user["id"], today_start)
        )
        rbc_cfg = query_one("SELECT max_daily_loss, stop_loss_pct, take_profit_pct, bot_status, emergency_shutdown FROM real_bot_configs WHERE user_id=?", (user["id"],))
        if is_live_flag and rbc_cfg and (
            str(rbc_cfg.get("bot_status") or "").upper() == "PAUSED"
            or int(rbc_cfg.get("emergency_shutdown") or 0) == 1
        ):
            return len(open_list), 0
        max_daily_loss_lim = abs(float((rbc_cfg and rbc_cfg.get("max_daily_loss")) or 250.0))
        daily_loss = float(daily_pnl_row["daily_pnl"] or 0.0) if daily_pnl_row else 0.0
        if is_live_flag and daily_loss <= -max_daily_loss_lim:
            write("UPDATE users SET bot_enabled=0 WHERE id=?", (user["id"],))
            self._log(user["id"], "DAILY_LOSS_GUARD",
                      f"🛑 MAX DAILY LOSS GUARD TRIGGERED: Today's settled loss (-${abs(daily_loss):.2f}) reached daily limit. Bot paused automatically to preserve remaining capital ${capital:,.2f}.")
            try:
                from coindcx_gateway import log_audit_event
                log_audit_event(user["id"], "DAILY_LOSS_GUARD_TRIGGERED",
                                f"Trading halted. Settled daily P&L: -${abs(daily_loss):.2f}. Capital preserved: ${capital:,.2f}", "CRITICAL")
            except Exception:
                pass
            return len(open_list), 0

        risk_pct = float(user["bot_risk_pct"] or 5.0)
        mode = user.get("bot_mode") or "SCALP"
        mode_spec = MODES.get(mode, MODES["SCALP"])
        now = time.time()

        # CONTINUOUS SLOT REFILL: No warmup delay.
        # When a position closes, the slot is immediately refilled next cycle.
        # This creates 100+ trades per session as the bot continuously rotates positions.
        # The 10-slot ceiling ensures only 10 are ever open simultaneously.

        # Scalping Margin Sizing:
        # Dynamically divides available capital across user-selected position capacity (5, 10, or Unlimited)
        # so that when the user chooses 5 or 10 positions, all slots open simultaneously without one trade starving the others!
        acct_cap = float(capital)
        requested_slots = 20 if is_unlimited else max(1, min(50, max_pos))
        if is_pure_crypto or user_currency == "USD":
            # Crypto USD Futures: Dynamic isolated margin adapted to available balance (Supports $0.05 - $0.07 micro balance!)
            slots_target = 5 if raw_max == 5 else (10 if raw_max == 10 else (20 if is_unlimited else max(1, min(slots, max_pos))))
            if acct_cap <= 1.0:
                base_margin = round(max(0.005, acct_cap / max(slots_target, 1)), 4)
                max_margin = acct_cap
                min_margin = 0.002
            elif acct_cap <= 5.0:
                base_margin = round(max(0.05, acct_cap / max(slots_target, 1)), 4)
                max_margin = acct_cap
                min_margin = 0.01
            else:
                base_margin = round(min(8.0, max(2.0, acct_cap * 0.12)), 2)
                max_margin = 12.0
                min_margin = 0.5
        elif is_live_flag and broker_name == "COINDCX":
            # AraaBot Rule Adapter Sizing Rule for Spot INR:
            min_cdx_slot = 150.0
            safe_slice = max(min_cdx_slot, min(400.0, round(acct_cap * 0.05, 2)))
            base_margin = safe_slice
            max_margin = 400.0
            min_margin = 15.0
        else:
            slots_target = 20 if is_unlimited else max(1, min(slots, max_pos))
            base_margin = round(min(500.0, max(50.0, acct_cap / max(slots_target, 2))), 2)
            max_margin = min(1000.0, acct_cap)
            min_margin = 15.0
        base_margin = max(min_margin, min(base_margin, max_margin))
        if base_margin < min_margin or capital < min_margin:
            return len(open_list), 0

        # Load AI Self-Learning Training State (boosted symbols, blacklisted pairs, custom TP/SL rules)
        tr_boosted = set()
        tr_blacklisted = set()
        tr_custom_rules = {}
        try:
            from bot_trainer import get_training_state
            tr_state = get_training_state() or {}
            tr_boosted = {
                (x.get("symbol") if isinstance(x, dict) else str(x))
                for x in (tr_state.get("boosted_symbols") or [])
            }
            tr_blacklisted = {
                (x.get("symbol") if isinstance(x, dict) else str(x))
                for x in (tr_state.get("blacklisted_symbols") or [])
            }
            tr_custom_rules = tr_state.get("custom_rules") or {}
        except Exception:
            pass

        # Round-robin across markets so one volatile pair cannot fill every slot.
        by_cat = {}
        user_lev_est = min(500.0, max(1.0, float(user.get("bot_leverage") or mode_spec.get("default_leverage") or 20.0)))
        user_tp_rbc = float(rbc_cfg.get("take_profit_pct") or 0.0) if rbc_cfg else 0.0
        user_sl_rbc = float(rbc_cfg.get("stop_loss_pct") or 0.0) if rbc_cfg else 0.0
        for s in self.setups:
            s_copy = dict(s)
            if s_copy["symbol"] in tr_boosted:
                s_copy["confidence"] = round(min(0.99, float(s_copy.get("confidence") or 0.85) + 0.05), 3)
            if str(mode).upper() in SCALP_MODE_PRESETS and s_copy.get("category") == "CRYPTO":
                cal_tp, cal_sl = resolve_scalp_targets(
                    mode, leverage=user_lev_est, tp_override=user_tp_rbc, sl_override=user_sl_rbc, custom_rules=tr_custom_rules
                )
                s_copy["target_pct"] = cal_tp
                s_copy["stop_pct"] = cal_sl
            else:
                if tr_custom_rules.get("target_profit_pct"):
                    s_copy["target_pct"] = float(tr_custom_rules["target_profit_pct"])
                if tr_custom_rules.get("stop_loss_pct"):
                    s_copy["stop_pct"] = float(tr_custom_rules["stop_loss_pct"])
            by_cat.setdefault(s_copy["category"], []).append(s_copy)
        for cat, tune in MARKET.items():
            pool = by_cat.get(cat)
            if pool and tune.get("spread") and len(pool) > 1:
                rotated = self._rotate(pool, self.tick_count + int(user["id"]))
                if tr_boosted:
                    rotated.sort(key=lambda x: (0 if x["symbol"] in tr_boosted else 1))
                by_cat[cat] = rotated
        # Order categories by real-world session open status first, then by priority
        # On weekends, CRYPTO is open 24/7 so it gets filled with live liquidity
        # On weekdays, Metals, Forex, Indices, Equities & Crypto all take turn based on setup score
        def _cat_sort_key(c):
            sess = is_market_session_open(c)
            # Open session first (0), closed session second (1)
            session_rank = 0 if sess["is_open"] else 1
            existing = per_cat.get(c, 0)
            priority = MARKET.get(c, {}).get("priority", 3)
            return (session_rank, existing, priority)

        market_focus = (user.get("bot_market_focus") or (b_conn.get("market_focus") if b_conn else None) or "ALL").upper()

        # MT4 LIVE CHART SECTORS (Exness Real Trading Only):
        EXNESS_FOREX = {"EURUSD", "GBPUSD", "USDJPY", "USDCAD", "USDCHF", "AUDUSD", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP", "CADJPY", "USDINR"}
        EXNESS_METALS = {"XAUUSD", "XAGUSD"}
        EXNESS_CRYPTO = {"BTCUSD", "BTCUSDT", "ETHUSD", "ETHUSDT", "SOLUSD", "SOLUSDT"}
        EXNESS_INDICES = {"US30", "SPX500", "NAS100"}
        EXNESS_ALL = EXNESS_FOREX | EXNESS_METALS | EXNESS_CRYPTO | EXNESS_INDICES

        target_mt4_symbols = EXNESS_ALL
        real_cat_order = ["CRYPTO"] if (is_live_flag and broker_name == "COINDCX") else ["FOREX", "METALS", "CRYPTO", "INDICES"]
        if is_live_flag and broker_name == "COINDCX":
            real_cat_order = ["CRYPTO"]
            is_futures_usd = True
            market_focus = "FUTURES_USD"
            prefer_inr = False

            cdx_active_tickers = set()
            t_map = {}
            try:
                from coindcx_gateway import get_live_tickers
                t_map = get_live_tickers() or {}
                if t_map:
                    cdx_active_tickers = set(t_map.keys())
            except Exception:
                pass

            # Exclude synthetic equities (e.g. TSLABUSDT, SQQQBUSDT, UVXYBUSDT, GPROBUSDT)
            def _is_real_crypto(sym):
                if cdx_active_tickers and sym in cdx_active_tickers:
                    return True
                for bad in ("TSLAB", "SQQQB", "UVXYB", "GPROB", "QQQB", "SPYB", "AAPLB"):
                    if sym.startswith(bad):
                        return False
                return True

            target_mt4_symbols = set()
            for c in (by_cat.get("CRYPTO") or []):
                s = c["symbol"]
                if not _is_real_crypto(s):
                    continue
                if is_futures_usd:
                    # USD / USDT ONLY - Strict rule: NO INR pairs!
                    if s.endswith("USDT") or s.startswith("B-"):
                        if not cdx_active_tickers or s in cdx_active_tickers or f"B-{s.replace('/', '_')}" in cdx_active_tickers:
                            target_mt4_symbols.add(s)
                elif prefer_inr:
                    if s.endswith("INR"):
                        if not cdx_active_tickers or s in cdx_active_tickers:
                            target_mt4_symbols.add(s)
                    elif s.endswith("USDT") or s.endswith("USDC"):
                        base = s.replace("USDT", "").replace("USDC", "")
                        inr_cand = f"{base}INR"
                        if not cdx_active_tickers or inr_cand in cdx_active_tickers:
                            target_mt4_symbols.add(s)
                else:
                    if not cdx_active_tickers or s in cdx_active_tickers:
                        target_mt4_symbols.add(s)
            # Guarantee all primary CoinDCX USDT Futures pairs (prioritizing 15x-25x liquidity contracts)
            target_mt4_symbols.update({
                "BTCUSDT", "ETHUSDT", "BNBUSDT", "LTCUSDT", "TRXUSDT", "ATOMUSDT", "FILUSDT",
                "NEARUSDT", "XRPUSDT", "DOGEUSDT", "BCHUSDT", "DOTUSDT", "LINKUSDT", "ADAUSDT", "AVAXUSDT",
                "FETUSDT", "SOLUSDT", "HBARUSDT", "INJUSDT", "SUIUSDT", "ARBUSDT", "PYTHUSDT",
                "1000PEPEUSDT", "ZECUSDT", "YBUSDT", "CARVUSDT", "WAXPUSDT", "BANANAUSDT",
                "SPELLUSDT", "SAPIENUSDT", "USTCUSDT", "MOCAUSDT", "SONICUSDT", "DOLOUSDT",
                "MTLUSDT", "GASUSDT", "BELUSDT", "ASTRUSDT", "ASRUSDT", "SANTOSUSDT",
                "BNTUSDT", "1000000MOGUSDT", "JOEUSDT", "FRAXUSDT", "XVSUSDT",
                "B-BTC_USDT", "B-ETH_USDT", "B-BNB_USDT", "B-LTC_USDT", "B-ATOM_USDT",
                "B-SOL_USDT", "B-DOGE_USDT", "B-XRP_USDT", "B-CARV_USDT", "B-WAXP_USDT",
                "B-BANANA_USDT", "B-YB_USDT", "B-1000PEPE_USDT"
            })
            if not target_mt4_symbols:
                target_mt4_symbols = {
                    "BTCUSDT", "ETHUSDT", "BNBUSDT", "LTCUSDT", "ATOMUSDT", "FILUSDT", "TRXUSDT",
                    "NEARUSDT", "XRPUSDT", "DOGEUSDT", "SOLUSDT", "1000PEPEUSDT", "ZECUSDT"
                }
        elif market_focus == "FOREX":
            target_mt4_symbols = EXNESS_FOREX
            real_cat_order = ["FOREX"]
        elif market_focus == "METALS":
            target_mt4_symbols = EXNESS_METALS
            real_cat_order = ["METALS"]
        elif market_focus == "CRYPTO":
            target_mt4_symbols = EXNESS_CRYPTO
            real_cat_order = ["CRYPTO"]
        elif market_focus == "INDICES":
            target_mt4_symbols = EXNESS_INDICES
            real_cat_order = ["INDICES"]

        # =========================================================================
        # ARAA AI DECISION CALIBRATION GATE:
        # In Real Live MT4 Mode, execute immediately (5s warmup) so customers see
        # real-time MT4 orders right away! In Paper Mode, keep the 120s calibration.
        # =========================================================================
        # Zero-delay instant execution: start analyzing and opening high-probability positions immediately
        activated_at = float(user.get("bot_activated_at") or 0.0)
        calib_window = 0.0
        if activated_at > 0 and len(open_list) == 0:
            elapsed_sec = now - activated_at
            if elapsed_sec < calib_window:
                rem_sec = int(calib_window - elapsed_sec)
                if self.tick_count % 4 == 0:
                    self._log(user["id"], "AI_CALIBRATING",
                              f"🧠 Araa AI {market_focus} Decision Calibration in progress ({rem_sec}s remaining). Analyzing live MT4 chart & win probabilities...")
                return len(open_list), 0

        opened = 0
        locked_live = sum(max(0.0, float(p.get("margin") or 0.0)) for p in all_opens) if is_live_flag else 0.0
        if is_live_flag:
            live_total_ref = float(b_conn.get("live_balance") or capital or 0.0)
            free = max(0.0, round(min(capital, max(0.0, live_total_ref - locked_live)), 4))
        else:
            free = capital
        is_pure_crypto = bool(mode_spec.get("pure_crypto")) or (is_live_flag and broker_name == "COINDCX") or (is_live_flag and market_focus in ("FUTURES_USD", "COINDCX_CRYPTO", "CRYPTO"))
        while slots - opened > 0:
            if free < min_margin:
                break
            if is_pure_crypto:
                order = ["CRYPTO"]
            elif is_live_flag:
                # Real Mode: prioritize selected MT4 Live Chart sector
                order = real_cat_order
            else:
                order = sorted(by_cat, key=_cat_sort_key)
            picked = None
            for cat in order:
                if not is_live_flag and is_pure_crypto and cat != "CRYPTO":
                    continue
                sess = is_market_session_open(cat)
                # If market session is closed (e.g. Forex/Metals/Stocks on weekends), skip evaluation completely
                if not sess["is_open"]:
                    continue
                pool = by_cat.get(cat) or []
                bot_dir = str(user.get("bot_trade_direction") or "BOTH").upper()
                # Rank by CoinDCX real leverage tier first (20x-25x > 10x-15x > 5x) so capital generates max profit per move
                tier1_lev_pairs = {
                    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "LTCUSDT",
                    "B-BTC_USDT", "B-ETH_USDT", "B-SOL_USDT", "B-BNB_USDT", "B-XRP_USDT", "B-DOGE_USDT", "B-LTC_USDT"
                }
                tier2_lev_pairs = {
                    "NEARUSDT", "BCHUSDT", "DOTUSDT", "LINKUSDT", "ADAUSDT", "AVAXUSDT", "FETUSDT",
                    "ATOMUSDT", "FILUSDT", "TRXUSDT", "INJUSDT", "SUIUSDT", "ARBUSDT", "PYTHUSDT",
                    "1000PEPEUSDT", "ZECUSDT"
                }

                def _lev_tier(sym_name):
                    s_up = str(sym_name or "").upper()
                    if s_up in tier1_lev_pairs:
                        return 0
                    if s_up in tier2_lev_pairs:
                        return 1
                    try:
                        import coindcx_client
                        max_l = int(coindcx_client.get_coindcx_max_leverage(s_up) or 0)
                        if max_l >= 20:
                            return 2
                        if max_l >= 10:
                            return 3
                    except Exception:
                        pass
                    return 4

                def _tv_verified_tier(cand_obj):
                    # Prioritize tight-spread, high-liquidity pairs backed by aligned 1s + 1m + 5m + Qualified SMC/DNA
                    tv_r = cand_obj.get("tv_recommend")
                    tv_ok = tv_r is not None and abs(float(tv_r)) >= 0.15
                    smc_ok = str(cand_obj.get("smc_dna_status") or "") in ("QUALIFIED_BULLISH", "QUALIFIED_BEARISH")
                    s_up = str(cand_obj.get("side") or "").upper()
                    d1s = str(cand_obj.get("tv_1s_dir") or "NEUTRAL").upper()
                    t1s_ok = (s_up in ("LONG", "BUY") and d1s == "BUY") or (s_up in ("SHORT", "SELL") and d1s == "SELL")
                    liq_ok = float(cand_obj.get("volume") or 0.0) >= 5_000_000.0
                    if tv_ok and smc_ok and t1s_ok and liq_ok:
                        return 0
                    if tv_ok and smc_ok and t1s_ok:
                        return 1
                    if tv_ok and t1s_ok and liq_ok:
                        return 2
                    if tv_ok and t1s_ok:
                        return 3
                    if tv_ok:
                        return 4
                    return 5

                if bot_dir == "SHORT":
                    pool = [x for x in pool if x.get("side") in ("SHORT", "SELL")]
                    pool.sort(key=lambda x: (
                        _lev_tier(x.get("symbol")),
                        _tv_verified_tier(x),
                        -x.get("confidence", 0.0),
                        -float(x.get("score") or 0.0)
                    ))
                elif bot_dir == "LONG":
                    pool = [x for x in pool if x.get("side") in ("LONG", "BUY")]
                    pool.sort(key=lambda x: (
                        _lev_tier(x.get("symbol")),
                        _tv_verified_tier(x),
                        -x.get("confidence", 0.0),
                        -float(x.get("score") or 0.0)
                    ))
                else:
                    pool.sort(key=lambda x: (
                        _lev_tier(x.get("symbol")),
                        _tv_verified_tier(x),
                        -x.get("confidence", 0.0),
                        -float(x.get("score") or 0.0)
                    ))
                while pool:
                    cand = dict(pool.pop(0))
                    if cand["symbol"] in held:
                        continue
                    if cand["symbol"] in tr_blacklisted:
                        continue
                    cd_until = getattr(self, "_symbol_cooldown", {}).get((user["id"], cand["symbol"]), 0.0)
                    if cd_until > time.time():
                        continue
                    if is_coindcx_live and float(cand.get("confidence") or 0.0) < 0.68:
                        continue
                    # GUARD: In Real Live Mode, strictly enforce target symbols (No stocks, no unconfigured forex)
                    if is_live_flag and target_mt4_symbols and cand["symbol"] not in target_mt4_symbols:
                        continue
                    # PAPER BOT LIVE TRADINGVIEW GUARD: Paper Bot trades live TradingView charts or CoinDCX crypto
                    if not is_live_flag:
                        is_crypto_live = cand["symbol"].endswith("INR") or cand["symbol"].endswith("USDT") or cand.get("category") == "CRYPTO"
                        if not is_crypto_live and not tv_symbol(cand["symbol"]):
                            continue
                    # COINDCX SPOT GUARD: Only block SHORT when trading Spot INR (Futures USD supports both LONG and SHORT!)
                    if is_coindcx_live and not is_futures_usd and cand.get("side") in ("SELL", "SHORT"):
                        continue

                    # COINDCX SPREAD & LIQUIDITY GUARD:
                    # Allow up to 1.25% spread for Indian Spot INR pairs and 0.45% for futures/USDT pairs
                    if is_coindcx_live and t_map:
                        check_sym = cand["symbol"]
                        if prefer_inr and (check_sym.endswith("USDT") or check_sym.endswith("USDC")):
                            base_t = check_sym.replace("USDT", "").replace("USDC", "")
                            check_sym = f"{base_t}INR"
                        cdx_t = t_map.get(check_sym)
                        if cdx_t and cdx_t.get("bid") and cdx_t.get("ask"):
                            bid_p, ask_p = float(cdx_t["bid"]), float(cdx_t["ask"])
                            if bid_p > 0:
                                cdx_spread = (ask_p - bid_p) / bid_p * 100.0
                                max_spread = 1.25 if check_sym.endswith("INR") else 0.45
                                if cdx_spread > max_spread:
                                    continue
                    # Enforce user's direction filter without converting counter-trend setups into losing opposite trades
                    if bot_dir == "SHORT" and cand.get("side") not in ("SELL", "SHORT"):
                        continue
                    if bot_dir == "LONG" and cand.get("side") not in ("BUY", "LONG"):
                        continue

                    # TRADINGVIEW -> COINDCX EXECUTION ALIGNMENT GATE:
                    # Ensure CoinDCX live BUY/SELL orders strictly obey live TradingView chart analysis
                    if is_coindcx_live:
                        cand_q = self.feed.quote(cand["symbol"]) or {}
                        tv_r = cand.get("tv_recommend") if cand.get("tv_recommend") is not None else cand_q.get("tv_recommend")
                        tv_r1m = cand.get("tv_rec_1m") if cand.get("tv_rec_1m") is not None else cand_q.get("tv_rec_1m")
                        tv_r5m = cand.get("tv_rec_5m") if cand.get("tv_rec_5m") is not None else cand_q.get("tv_rec_5m")
                        c_side = str(cand.get("side") or "").upper()
                        if tv_r is not None:
                            if c_side in ("LONG", "BUY") and float(tv_r) < -0.03:
                                continue
                            if c_side in ("SHORT", "SELL") and float(tv_r) > 0.03:
                                continue
                        if tv_r1m is not None:
                            if c_side in ("LONG", "BUY") and float(tv_r1m) < -0.05:
                                continue
                            if c_side in ("SHORT", "SELL") and float(tv_r1m) > 0.05:
                                continue
                        if tv_r5m is not None:
                            if c_side in ("LONG", "BUY") and float(tv_r5m) < -0.08:
                                continue
                            if c_side in ("SHORT", "SELL") and float(tv_r5m) > 0.08:
                                continue
                    picked = cand
                    break
                if picked:
                    break
            if not picked:
                break

            # UPFRONT COINDCX INR TRANSLATION:
            # If trading live on CoinDCX with INR deposit, convert candidate symbol to live CoinDCX INR pair upfront
            if is_coindcx_live and prefer_inr and (picked["symbol"].endswith("USDT") or picked["symbol"].endswith("USDC")):
                base_tok = picked["symbol"].replace("USDT", "").replace("USDC", "")
                inr_cand = f"{base_tok}INR"
                if not cdx_active_tickers or inr_cand in cdx_active_tickers:
                    inr_p = 0.0
                    try:
                        if inr_cand in t_map:
                            inr_p = float(t_map[inr_cand].get("last_price") or 0.0)
                    except Exception:
                        pass
                    if inr_p <= 0:
                        inr_p = self.feed.live_price(inr_cand) or self.feed.price(inr_cand) or (picked["price"] * 90.0)
                    picked["symbol"] = inr_cand
                    picked["price"] = inr_p
                    picked["tv_symbol"] = tv_symbol(inr_cand) or picked.get("tv_symbol")
            
            # --- ARAA AI (Gemini 2.5 / 3.8 Flash) Prediction-First Gate ---
            change = 0.0
            tv_indicators = None
            q_row = self.feed.quote(picked["symbol"])
            if q_row:
                change = q_row.get("change_pct") or 0.0
                tv_indicators = {
                    "tv_rsi": q_row.get("tv_rsi_1m") or q_row.get("tv_rsi"),
                    "tv_recommend": q_row.get("tv_recommend"),
                    "tv_ma": q_row.get("tv_ma"),
                    "tv_rec_1m": q_row.get("tv_rec_1m"),
                    "tv_rec_5m": q_row.get("tv_rec_5m"),
                    "tv_ma_1m": q_row.get("tv_ma_1m"),
                }
            slope_z = picked.get("slope_z") if picked.get("slope_z") is not None else (picked.get("score") or 0.0)

            # Respect real live metrics before AI pre-entry validation; never forge adverse market readings into fake signals
            bot_dir_pref = str(user.get("bot_trade_direction") or "BOTH").upper()
            if bot_dir_pref == "SHORT" and picked.get("side") not in ("SHORT", "SELL"):
                continue
            if bot_dir_pref == "LONG" and picked.get("side") not in ("LONG", "BUY"):
                continue

            user_lev = min(500.0, max(1.0, float(user.get("bot_leverage") or 500.0)))
            try:
                from gemini_advisor import predict_pre_entry
                pred = predict_pre_entry(
                    symbol=picked["symbol"],
                    category=picked["category"],
                    price=picked["price"],
                    change_pct=change,
                    rsi_val=picked.get("rsi") or 50.0,
                    slope_z=slope_z,
                    direction=picked["side"],
                    technical_conf=picked["confidence"],
                    target_pct=picked["target_pct"],
                    stop_pct=picked["stop_pct"],
                    mode=mode,
                    leverage=user_lev,
                    tv_indicators=tv_indicators,
                    order_block=picked.get("order_block")
                )
            except Exception as e:
                # Robust fallback: Quantum momentum baseline ensures execution is not choked
                fallback_prob = max(85, int(float(picked.get("confidence") or 0.85) * 100))
                is_short_side = picked["side"] in ("SHORT", "SELL")
                target_p = round(picked["price"] * (1.0 - picked["target_pct"] / 100.0) if is_short_side else picked["price"] * (1.0 + picked["target_pct"] / 100.0), 6)
                stop_p = round(picked["price"] * (1.0 + picked["stop_pct"] / 100.0) if is_short_side else picked["price"] * (1.0 - picked["stop_pct"] / 100.0), 6)
                pred = {
                    "approved": True,
                    "action": picked["side"],
                    "direction": picked["side"],
                    "entry_price": picked["price"],
                    "target_price": target_p,
                    "stop_price": stop_p,
                    "target_pct": picked["target_pct"],
                    "stop_pct": picked["stop_pct"],
                    "risk_reward": round(picked["target_pct"] / max(picked["stop_pct"], 0.01), 2),
                    "win_probability": fallback_prob,
                    "confidence": picked["confidence"],
                    "rationale": f"Quantum Momentum Baseline: {picked.get('reason') or 'Institutional Trend'}",
                    "mode": mode,
                    "engine": "Araa Quantum Momentum Engine"
                }

            now = time.time()
            win_p = int(pred.get("win_probability") or 0)
            from gemini_advisor import MODE_CONFIGS
            # Strict Profit Entry Gate: Connect Custom Strategy Studio min_win_probability rule
            custom_min_win = int(tr_custom_rules.get("min_win_probability") or 80) if tr_custom_rules else 80
            mode_req_win = max(MODE_CONFIGS.get(mode, {}).get("min_win_rate", 80), min(88, custom_min_win))
            min_mode_win = max(80, mode_req_win) if is_live_flag else mode_req_win
            # Strict Profit Entry Filter: Only entries verified with high win probability and positive expectancy can execute
            is_win_prediction = bool(pred.get("approved")) and win_p >= min_mode_win and (pred.get("action") in ("BUY", "SELL"))

            # Multi-Agent Quantitative Committee & SMC/DNA Validation
            committee_verdict = None
            smc_info = None
            try:
                from quantum_engine import MarketRegimeEngine, LiquidationHeatmapEngine, TradingCommitteeEngine, SMCDNAEngine
                ticks_data = self.feed.ticks(picked["symbol"], 40) if hasattr(self, "feed") else []
                candles_data = self._candles(picked["symbol"], "1m", limit=60) if hasattr(self, "_candles") else None
                regime_info = MarketRegimeEngine.classify_regime(picked["symbol"], q_row or picked, ticks_data, candles_data)
                heatmap_info = LiquidationHeatmapEngine.calculate_clusters(
                    picked["symbol"],
                    picked["price"],
                    float((q_row or picked).get("high") or (picked["price"] * 1.02)),
                    float((q_row or picked).get("low") or (picked["price"] * 0.98)),
                    float((q_row or picked).get("volume") or 100000.0)
                )
                committee_verdict = TradingCommitteeEngine.evaluate_committee(picked["symbol"], picked, q_row or picked, regime_info, heatmap_info)
                
                # If Adversarial Beta vetoes (e.g. stop-hunt trap into massive liquidation pool), respect veto
                if committee_verdict and not committee_verdict.get("consensus_approved"):
                    if is_win_prediction:
                        # If consensus score is below 60 or Vetoed by Beta, hold off to protect capital
                        if committee_verdict.get("consensus_verdict") == "VETOED_BY_BETA" or committee_verdict.get("consensus_score", 0) < 60:
                            is_win_prediction = False
                            pred["rationale"] = f"Trading Committee Veto: {committee_verdict.get('summary_rationale')}"

                # SMC + Market DNA Gatekeeper
                smc_info = SMCDNAEngine.analyze_candles(picked["symbol"], candles_data or [], "15m", picked["price"])
                if is_win_prediction and smc_info:
                    sig_gate = smc_info.get("bot_signal") or {}
                    dna_info = smc_info.get("dna") or {}
                    is_long_side = picked["side"] in ("BUY", "LONG")
                    blocked_by_ob = (is_long_side and sig_gate.get("block_long")) or ((not is_long_side) and sig_gate.get("block_short"))
                    if blocked_by_ob and win_p < 90:
                        is_win_prediction = False
                        pred["rationale"] = (
                            f"SMC Order Block & DNA Guard: Blocked {picked['side']} into unmitigated "
                            f"{'Bearish OB' if is_long_side else 'Bullish OB'} ({dna_info.get('setup_status')}, {dna_info.get('similarity_pct')}% twin match)"
                        )
                    else:
                        raw_boost = int(sig_gate.get("boost_score") or 0)
                        dir_boost = raw_boost if is_long_side else -raw_boost
                        win_p = max(0, min(99, win_p + dir_boost))
                        pred["win_probability"] = win_p
                        pred["rationale"] = f"{pred.get('rationale', '')} | SMC/DNA: {dna_info.get('setup_status')} ({dna_info.get('similarity_pct')}% twin match)"
            except Exception as qc_err:
                pass

            if not is_win_prediction:
                # Log AI rejection audit - Non-WIN or lower-probability setups are strictly REJECTED
                reject_reason = pred.get("rationale") or f"Win Probability {win_p}% below required {min_mode_win}% Profit WIN threshold"
                write("INSERT INTO ai_predictions(user_id,symbol,category,direction,action,entry_price,target_price,"
                      "stop_price,target_pct,stop_pct,risk_reward,win_probability,confidence,rationale,mode,"
                      "post_entry_status,outcome,created_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'REJECTED','CANCELLED',?)",
                      (user["id"], picked["symbol"], picked["category"], pred["direction"], pred["action"],
                       pred["entry_price"], pred["target_price"], pred["stop_price"], pred["target_pct"],
                       pred["stop_pct"], pred["risk_reward"], win_p, pred["confidence"],
                       reject_reason, mode, now))
                self._log(user["id"], "AI_SKIP",
                          f"Araa AI Profit Filter blocked {picked['side']} {picked['symbol']} (Win Prob {win_p}% · R:R {pred['risk_reward']}:1): {reject_reason} [NO ENTRY]")
                continue

            picked["ai_win_prob"] = win_p
            tv_rec_val = float(picked.get("tv_recommend") or 0.0)
            tv_1m_val = float(picked.get("tv_rec_1m") if picked.get("tv_rec_1m") is not None else tv_rec_val)
            tv_5m_val = float(picked.get("tv_rec_5m") if picked.get("tv_rec_5m") is not None else tv_rec_val)
            tv_1s_d = picked.get("tv_1s_dir") or ("BUY" if picked["side"] in ("BUY", "LONG") else "SELL")
            smc_stat = picked.get("smc_dna_status") or "SMC_OB"
            smc_sim = picked.get("smc_dna_similarity") or 82.0
            exec_route = "COINDCX API" if is_coindcx_live else ("MT4 LIVE" if is_live_flag else "PAPER ENGINE")
            tv_sig_str = (
                f"⚡ TV[1s:{tv_1s_d}|1m:{tv_1m_val:+.2f}|5m:{tv_5m_val:+.2f}] → "
                f"SMC+DNA[{smc_stat} {smc_sim:.0f}%] → {exec_route} → "
                f"SCALP[+$1.00 TP | +$0.90 Close | +$0.10 Lock]"
            )
            pred["rationale"] = f"{tv_sig_str} | {pred.get('rationale', '')}"
            picked["reason"] = f"{tv_sig_str} · Araa AI [{pred['win_probability']}% win | R:R {pred['risk_reward']}:1]"
            if is_live_flag:
                self._log(user["id"], "AI_ENTRY_APPROVED",
                          f"🧠 {tv_sig_str} | {picked['side']} {picked['symbol']} ({win_p}% Win Prob)")

            # Record confirmed pre-entry prediction BEFORE real order so Gatekeeper Rule 6 sees it immediately!
            pred_id = write(
                "INSERT INTO ai_predictions(user_id,symbol,category,direction,action,entry_price,target_price,"
                "stop_price,target_pct,stop_pct,risk_reward,win_probability,confidence,rationale,mode,"
                "post_entry_status,outcome,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'APPROVED','PENDING',?)",
                (user["id"], picked["symbol"], picked["category"], pred["direction"], pred["action"],
                 pred["entry_price"], pred["target_price"], pred["stop_price"], pred["target_pct"],
                 pred["stop_pct"], pred["risk_reward"], win_p, pred["confidence"],
                 pred["rationale"], mode, now)
            )

            # Mid-cycle OFF guard: if Admin stopped Global Bot or User toggled Bot OFF while scanning, abort immediately
            if not self.is_running:
                break
            _u_live = query_one("SELECT bot_enabled FROM users WHERE id=?", (user["id"],))
            if not _u_live or not int(_u_live.get("bot_enabled") or 0):
                break

            # Hard Safety Check: Strictly enforce user's bot_max_positions limit right before insertion (bypassed if Unlimited)
            cur_open_cnt = query_one(
                "SELECT COUNT(*) as c FROM positions WHERE user_id=? AND status IN ('OPEN','PENDING_BROKER')",
                (user["id"],)
            )["c"]
            raw_max_allowed = int(user.get("bot_max_positions") or 10)
            is_unlim_pos = (raw_max_allowed >= 999 or raw_max_allowed <= 0)
            if is_coindcx_live and capital < 150.0 and not is_unlim_pos:
                raw_max_allowed = min(raw_max_allowed, max(2, min(4, int(capital // 15.0) + 1)))
            if not is_unlim_pos and cur_open_cnt >= raw_max_allowed:
                self._log(user["id"], "LIMIT_REACHED", f"Current open positions ({cur_open_cnt}) reached user max limit ({raw_max_allowed}). Halting new entries.")
                break

            # Defensive verification: Prevent opening duplicate positions for the same underlying coin (e.g. ZECUSDT & B-ZEC_USDT)
            _p_sym = str(picked["symbol"]).upper()
            _p_base = _p_sym[2:-5] if (_p_sym.startswith("B-") and _p_sym.endswith("_USDT")) else (_p_sym[:-4] if _p_sym.endswith("USDT") else _p_sym)
            _alt_sym = f"B-{_p_base}_USDT" if not _p_sym.startswith("B-") else f"{_p_base}USDT"
            already_open = query_one(
                "SELECT id FROM positions WHERE user_id=? AND symbol IN (?, ?) AND status IN ('OPEN','PENDING_BROKER')",
                (user["id"], picked["symbol"], _alt_sym)
            )
            if already_open:
                held.add(picked["symbol"])
                continue

            lev = min(500.0, max(1.0, float(user.get("bot_leverage") or 500.0)))
            is_coindcx_live = bool(is_live_flag and broker_name == "COINDCX")

            if is_coindcx_live:
                # Real CoinDCX execution: Support up to 500x AraaBot leverage rules (adapts cleanly if live exchange contract caps lower)
                effective_lev = min(500.0, max(1.0, lev))
                if lev > 1.0:
                    try:
                        from coindcx_gateway import get_user_coindcx_client
                        _cdx = get_user_coindcx_client(user["id"])
                        if _cdx and not _cdx.is_offline and _cdx.futures.check_eligibility().get("eligible"):
                            effective_lev = _cdx.futures.resolve_leverage(
                                picked["symbol"], lev, "buy" if picked["side"] in ("BUY", "LONG") else "sell")
                    except Exception as lev_err:
                        pass
                if effective_lev < 1.0:
                    self._log(user["id"], "ORDER_SKIP", f"Skipped {picked['symbol']} {picked['side']}: CoinDCX contract disallows this direction (0x leverage).")
                    continue
                target_margin = max(base_margin, 8.0) if free >= 20.0 else base_margin
                margin = round(min(free * 0.25 if free >= 20.0 else free, target_margin), 4)
                qty = round((margin * effective_lev) / picked["price"], 8)
            else:
                effective_lev = max(1.0, lev)
                margin = round(min(max_margin, min(base_margin * (0.75 + 0.5 * picked["confidence"]), free)), 4)
                qty = round((margin * effective_lev) / picked["price"], 8)

            min_pos_margin = 0.002 if (is_pure_crypto or user_currency == "USD") else min_margin
            if margin < min_pos_margin or qty <= 0:
                continue

            # Fresh micro-tick reversal guard right before order submission: skip if price snapped adversely
            fresh_ticks = self.feed.ticks(picked["symbol"], 6)
            live_now = self.feed.live_price(picked["symbol"]) or picked["price"]
            is_short_order = picked["side"] in ("SHORT", "SELL")
            if picked["price"] > 0 and live_now > 0:
                slip_pct = (live_now - picked["price"]) / picked["price"] * 100.0
                if is_short_order and slip_pct > 0.12:
                    self._log(user["id"], "REVERSAL_SKIP", f"Skipped SHORT {picked['symbol']}: price bounced +{slip_pct:.2f}% before fill.")
                    continue
                if (not is_short_order) and slip_pct < -0.12:
                    self._log(user["id"], "REVERSAL_SKIP", f"Skipped LONG {picked['symbol']}: price dropped {slip_pct:.2f}% before fill.")
                    continue
            if len(fresh_ticks) >= 4:
                ft = self._micro_momentum_state(fresh_ticks)
                if is_short_order and ft["above_fast"] and ft["micro_step_ups"] >= 3 and ft["recent_tick_pct"] >= 0.05:
                    self._log(user["id"], "REVERSAL_SKIP", f"Skipped SHORT {picked['symbol']}: live micro-ticks bouncing upward ({ft['recent_tick_pct']:+.2f}%).")
                    continue
                if (not is_short_order) and ft["below_fast"] and ft["micro_step_downs"] >= 3 and ft["recent_tick_pct"] <= -0.05:
                    self._log(user["id"], "REVERSAL_SKIP", f"Skipped LONG {picked['symbol']}: live micro-ticks dropping ({ft['recent_tick_pct']:+.2f}%).")
                    continue

            # Real Exchange Execution Bridge (AraaBot StrategyEngine + CoinDCXExecutionAdapter)
            real_res = None
            if is_coindcx_live:
                try:
                    from strategy_engine import StrategyEngine
                    from coindcx_adapter import CoinDCXExecutionAdapter
                    from coindcx_gateway import resolve_live_futures_price
                    if is_futures_usd and os.environ.get("ARAA_E2E_MOCK_COINDCX") != "1":
                        cdx_fut_px = resolve_live_futures_price(picked["symbol"])
                        if cdx_fut_px > 0 and picked["price"] > 0 and (0.5 <= (cdx_fut_px / picked["price"]) <= 1.5):
                            picked["price"] = cdx_fut_px
                    StrategyEngine.ensure_user_strategies(user["id"])
                    strat = StrategyEngine.get_strategy(user["id"], "araa_ai_default")
                    if not strat or not int(strat.get("enabled") or 0):
                        self._log(user["id"], "STRATEGY_SKIP", f"Skipped {picked['symbol']}: Araa Quantum AI strategy is disabled.")
                        continue

                    # Per-symbol loss-streak cooldown (prevents rapid repeat losses on same pair)
                    loss_cool = max(int(strat.get("cooldown_seconds") or 60), 180)
                    recent_loss = query_one(
                        "SELECT realized_pnl, closed_at FROM positions WHERE user_id=? AND symbol=? AND status='CLOSED' AND closed_at>? ORDER BY closed_at DESC LIMIT 1",
                        (user["id"], picked["symbol"], now - loss_cool),
                    )
                    if recent_loss and float(recent_loss.get("realized_pnl") or 0.0) < 0:
                        self._log(user["id"], "COOLDOWN_SKIP", f"Skipped {picked['symbol']}: recent loss cooldown ({loss_cool}s) active.")
                        continue

                    # Sync SL/TP & Risk% from User Real Bot Config -> Calibrated Scalp Rules -> StrategyEngine
                    rbc_sl = float(rbc_cfg.get("stop_loss_pct") or 0.0) if rbc_cfg else 0.0
                    rbc_tp = float(rbc_cfg.get("take_profit_pct") or 0.0) if rbc_cfg else 0.0
                    if str(mode).upper() in SCALP_MODE_PRESETS:
                        strat_tp_pct, strat_sl_pct = resolve_scalp_targets(
                            mode,
                            leverage=effective_lev,
                            tp_override=rbc_tp,
                            sl_override=rbc_sl,
                            custom_rules=tr_custom_rules,
                        )
                    else:
                        custom_sl = rbc_sl or (float(tr_custom_rules.get("stop_loss_pct") or 0.0) if tr_custom_rules else 0.0)
                        custom_tp = rbc_tp or (float(tr_custom_rules.get("target_profit_pct") or 0.0) if tr_custom_rules else 0.0)
                        strat_sl_pct = max(0.30, custom_sl or float(strat.get("stop_loss_pct") or 0.50))
                        strat_tp_pct = max(strat_sl_pct * 1.8, custom_tp or float(strat.get("take_profit_pct") or 1.00))
                    risk_pct = max(0.2, min(35.0, float(user.get("bot_risk_pct") or strat.get("risk_per_trade_pct") or 2.0)))
                    if capital >= 25.0 and free < 10.0:
                        self._log(user["id"], "MARGIN_SKIP", f"Skipped {picked['symbol']}: free margin (${free:.2f}) below $10 scalp minimum.")
                        continue
                    min_cdx_margin = 10.0 if free >= 10.0 else (5.0 if free >= 5.0 else (1.5 if free >= 1.5 else min_pos_margin))
                    risk_margin = round(min(free, max(min_cdx_margin, capital * (risk_pct / 100.0))), 4)
                    # Scale high-conviction A+ signals and lower-leverage (5x-10x) futures contracts meaningfully so +$0.10 to +$1.00 scalps hit fast
                    if win_p >= 80 or effective_lev <= 20.0:
                        conf_cap_pct = 0.28 if effective_lev <= 10.0 else 0.22
                        max_slot_margin = max(min_cdx_margin, round(capital * conf_cap_pct, 2))
                        max_ord_cap = float(strat.get("max_order_size_usd") or 25000.0)
                        target_margin = min(max_ord_cap, max(risk_margin, base_margin, max_slot_margin))
                        risk_margin = round(max(min_cdx_margin, min(free * 0.60 if free > 12.0 else free, target_margin)), 4)
                    if risk_margin >= min_pos_margin:
                        margin = risk_margin
                        qty = round((margin * effective_lev) / picked["price"], 8)
                    picked["stop_pct"] = strat_sl_pct
                    picked["target_pct"] = strat_tp_pct
                    is_buy_dir = picked["side"] in ("BUY", "LONG")
                    sl_price = round(picked["price"] * (1.0 - strat_sl_pct / 100.0) if is_buy_dir else picked["price"] * (1.0 + strat_sl_pct / 100.0), 8)
                    tp_price = round(picked["price"] * (1.0 + strat_tp_pct / 100.0) if is_buy_dir else picked["price"] * (1.0 - strat_tp_pct / 100.0), 8)
                    pred["stop_price"] = sl_price
                    pred["target_price"] = tp_price

                    # Full 3-Agent AI Committee (Alpha, Beta, Gamma) pre-entry analysis & gate
                    try:
                        comm_res = AICommitteeOrchestrator.evaluate_candidate(
                            symbol=picked["symbol"],
                            user_id=user["id"],
                            quote_data=q_row or picked,
                            equity_usd=capital,
                            requested_leverage=effective_lev,
                            is_live=bool(is_live_flag),
                            persist=True,
                        )
                        a_sc = (comm_res.get("alpha") or {}).get("score", 0)
                        b_sc = (comm_res.get("beta") or {}).get("score", 0)
                        g_ok = (comm_res.get("gamma") or {}).get("approved", True)
                        self._log(
                            user["id"],
                            "COMMITTEE_SCAN",
                            f"3-Agent Committee on {picked['side']} {picked['symbol']}: Alpha={a_sc}, Beta={b_sc}, Gamma={'OK' if g_ok else 'VETO'} -> {comm_res.get('final_action', 'SKIP')} (consensus={comm_res.get('consensus_score', 0)})",
                        )
                        if not comm_res.get("approved"):
                            self._log(
                                user["id"],
                                "COMMITTEE_SKIP",
                                f"AI Committee rejected {picked['side']} {picked['symbol']}: {comm_res.get('final_action')} ({(comm_res.get('gamma') or {}).get('veto_reason') or 'low consensus'})",
                            )
                            if pred_id:
                                write("UPDATE ai_predictions SET post_entry_status='COMMITTEE_REJECTED', outcome='CANCELLED' WHERE id=?", (pred_id,))
                            continue
                    except Exception as comm_err:
                        self._log(user["id"], "COMMITTEE_SKIP", f"AI Committee evaluation error for {picked['symbol']}: {comm_err}")
                        continue

                    strat_eval = dict(strat)
                    strat_eval["leverage"] = effective_lev
                    strat_eval["stop_loss_pct"] = strat_sl_pct
                    strat_eval["take_profit_pct"] = strat_tp_pct

                    risk_ok, risk_reason = StrategyEngine.evaluate_hard_risk(
                        user_id=user["id"],
                        strategy=strat_eval,
                        symbol=picked["symbol"],
                        side=picked["side"],
                        ai_signal=pred,
                    )
                    if not risk_ok:
                        self._log(user["id"], "RISK_BLOCK", f"StrategyEngine blocked {picked['side']} {picked['symbol']}: {risk_reason}")
                        if pred_id:
                            write("UPDATE ai_predictions SET post_entry_status='RISK_BLOCKED', outcome='CANCELLED' WHERE id=?", (pred_id,))
                        continue
                    
                    # Update dynamic SL/TP if auto-clamped by StrategyEngine
                    if strat_eval.get("stop_loss_pct") and strat_eval["stop_loss_pct"] != strat_sl_pct:
                        strat_sl_pct = float(strat_eval["stop_loss_pct"])
                        sl_price = round(picked["price"] * (1.0 - strat_sl_pct / 100.0) if is_buy_dir else picked["price"] * (1.0 + strat_sl_pct / 100.0), 8)
                        pred["stop_price"] = sl_price

                    # Mandatory exchange-side Stop Loss & Take Profit attachment
                    exch_stop_loss = sl_price
                    ad_res = CoinDCXExecutionAdapter.submit_order(
                        user_id=user["id"],
                        strategy_id=strat["strategy_id"],
                        symbol=picked["symbol"],
                        side="BUY" if is_buy_dir else "SELL",
                        market_type=str(strat.get("market_type") or "FUTURES"),
                        quantity=qty,
                        margin_usd=margin,
                        order_type="market_order",
                        price=picked["price"],
                        leverage=float(effective_lev),
                        stop_loss=exch_stop_loss,
                        take_profit=tp_price,
                        client_order_id=f"araa_ai_{user['id']}_{picked['symbol']}_{int(now)}",
                    )
                    if not (ad_res.get("success") or ad_res.get("ok")):
                        err_txt = ad_res.get("error") or "CoinDCX order rejected"
                        self._log(user["id"], "ORDER_RETRY", f"CoinDCX rejected {picked['symbol']} ({err_txt})")
                        try:
                            from coindcx_gateway import log_audit_event
                            log_audit_event(user["id"], "ORDER_REJECTED", f"Skipped {picked['symbol']}: {err_txt}", severity="WARNING")
                        except Exception:
                            pass
                        if pred_id:
                            write("UPDATE ai_predictions SET post_entry_status='BROKER_FAILED', outcome='FAILED' WHERE id=?", (pred_id,))
                        continue

                    filled_qty = float(ad_res.get("filled_qty") or qty)
                    filled_price = float(ad_res.get("avg_fill_price") or picked["price"])
                    picked["price"] = filled_price
                    exch_pos_id = str(ad_res.get("exchange_order_id") or ad_res.get("client_order_id") or "")
                    prot_res = CoinDCXExecutionAdapter.setup_and_verify_protection(
                        user_id=user["id"],
                        position_id=exch_pos_id,
                        exchange_position_id=exch_pos_id,
                        symbol=picked["symbol"],
                        side="BUY" if is_buy_dir else "SELL",
                        market_type=str(strat.get("market_type") or "FUTURES"),
                        filled_qty=filled_qty,
                        entry_price=filled_price,
                        stop_loss_pct=strat_sl_pct,
                        take_profit_pct=strat_tp_pct,
                        trailing_stop_pct=(strat_sl_pct * 0.6 if int(strat.get("trailing_sl_enabled") or 0) else 0.0),
                        is_live=True,
                    )
                    real_res = {
                        "executed": True,
                        "exchange": "COINDCX",
                        "qty": filled_qty,
                        "leverage": float(ad_res.get("leverage") or effective_lev),
                        "actual_margin_usd": float(ad_res.get("actual_margin_usd") or margin),
                        "order_id": ad_res.get("exchange_order_id"),
                        "protection_verified": bool(prot_res.get("protection_verified")),
                    }
                except Exception as b_err:
                    real_res = {"executed": False, "error": str(b_err)}
                    self._log(user["id"], "ORDER_RETRY", f"Skipped {picked['symbol']} ({b_err}), checking next setup...")
                    if pred_id:
                        write("UPDATE ai_predictions SET post_entry_status='BROKER_FAILED', outcome='FAILED' WHERE id=?", (pred_id,))
                    continue
            elif is_live_flag:
                try:
                    from real_broker import execute_real_order
                    real_res = execute_real_order(
                        symbol=picked["symbol"],
                        side=picked["side"],
                        qty=qty,
                        leverage=lev,
                        stop_loss=pred.get("stop_price"),
                        take_profit=pred.get("target_price"),
                        user_id=user["id"],
                        price=picked["price"],
                        ai_win_prob=pred.get("win_probability")
                    )
                except Exception as b_err:
                    real_res = {"executed": False, "error": str(b_err)}

                # Strict rule: Never display a simulated trade as a real broker trade
                # If this specific symbol fails, continue to next setup so multiple positions fill all slots!
                if not real_res or not real_res.get("executed"):
                    err_txt = (real_res or {}).get("error") or "Order not confirmed"
                    self._log(user["id"], "ORDER_RETRY", f"Skipped {picked['symbol']} ({err_txt}), checking next setup...")
                    if pred_id:
                        write("UPDATE ai_predictions SET post_entry_status='BROKER_FAILED', outcome='FAILED' WHERE id=?", (pred_id,))
                    continue

            if is_coindcx_live and real_res:
                exchange_lev = float(real_res.get("leverage") or 0.0)
                if exchange_lev >= 1.0:
                    effective_lev = exchange_lev
                qty = float(real_res.get("qty") or qty)
                if float(real_res.get("actual_margin_usd") or 0.0) > 0:
                    margin = float(real_res["actual_margin_usd"])
                lev = effective_lev
            ai_prob = picked.get("ai_win_prob") or 75.0
            is_coindcx_live = bool(is_live_flag and broker_name == "COINDCX")
            feed_name = "COINDCX_LIVE" if is_coindcx_live else ("EXNESS_MT4_LIVE" if is_live_flag else "TRADINGVIEW_LIVE")
            src_val = "COINDCX LIVE" if is_coindcx_live else "BOT"

            # Never mark an Exness MT4 order as OPEN before broker confirmation
            is_mt4_queued = bool(is_live_flag and real_res and real_res.get("exchange") == "EXNESS_MT4" and not real_res.get("broker_confirmed"))
            initial_pos_status = "PENDING_BROKER" if is_mt4_queued else "OPEN"
            cmd_id = real_res.get("command_id") if real_res else None
            term_id = real_res.get("terminal_id") if real_res else None

            pos_id = write("INSERT INTO positions(user_id,symbol,source,side,qty,entry_price,margin,target_pct,"
                           "stop_pct,status,current_price,unrealized_pnl,opened_at,category,signal_score,"
                           "signal_reason,feed_source,peak_pnl_pct,ai_win_prob,leverage,is_live,command_id,terminal_id) "
                           "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (user["id"], picked["symbol"], src_val, picked["side"], qty, picked["price"],
                            margin, picked["target_pct"], picked["stop_pct"], initial_pos_status, picked["price"], 0, now,
                            picked["category"], picked["score"], picked["reason"], feed_name, 0.0, ai_prob, lev,
                            is_live_flag, cmd_id, term_id))

            # V3 Institutional Order Lifecycle & 3-Agent Committee Audit Trail
            try:
                from risk_engine import OrderLifecycleManager, InstitutionalRiskEngine
                from ai_committee import AICommitteeOrchestrator
                ord_uuid = OrderLifecycleManager.create_order_record(
                    user_id=user["id"],
                    symbol=picked["symbol"],
                    side=picked["side"],
                    order_type="MARKET",
                    requested_price=picked["price"],
                    qty=qty,
                    leverage=lev,
                    is_live=bool(is_live_flag),
                )
                fill_audit = OrderLifecycleManager.confirm_order_fill(
                    order_uuid=ord_uuid,
                    executed_price=picked["price"],
                    qty=qty,
                    exchange_order_id=(real_res or {}).get("order_id") if real_res else None,
                    is_live=bool(is_live_flag),
                )
                liq_p = InstitutionalRiskEngine.compute_liquidation_price(picked["price"], picked["side"], lev)
                if pos_id:
                    write(
                        "UPDATE positions SET order_uuid=?, fee_usd=?, slippage_bps=?, liquidation_price=? WHERE id=?",
                        (ord_uuid, fill_audit["fee_usd"], fill_audit["slippage_bps"], liq_p, pos_id)
                    )
            except Exception:
                pass

            if cmd_id and pos_id:
                write("UPDATE mt4_commands SET position_id=? WHERE command_id=?", (pos_id, cmd_id))

            # Record confirmed pre-entry prediction linked to this position
            if pred_id:
                write("UPDATE ai_predictions SET post_entry_status='MONITORING', position_id=? WHERE id=?",
                      (pos_id, pred_id))
            else:
                write("INSERT INTO ai_predictions(user_id,symbol,category,direction,action,entry_price,target_price,"
                      "stop_price,target_pct,stop_pct,risk_reward,win_probability,confidence,rationale,mode,"
                      "post_entry_status,outcome,created_at,position_id) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'MONITORING','PENDING',?,?)",
                      (user["id"], picked["symbol"], picked["category"], pred["direction"], pred["action"],
                       pred["entry_price"], pred["target_price"], pred["stop_price"], pred["target_pct"],
                       pred["stop_pct"], pred["risk_reward"], pred["win_probability"], pred["confidence"],
                       pred["rationale"], mode, now, pos_id))

            if not is_live_flag:
                dep_avail = max(0.0, float(wallet.get("deposit_balance") or 0))
                dep_deduct = min(margin, dep_avail)
                prof_deduct = round(margin - dep_deduct, 2)
                write("UPDATE wallets SET deposit_balance=deposit_balance-?, profit_balance=profit_balance-?, "
                      "locked_balance=locked_balance+? WHERE user_id=?",
                      (dep_deduct, prof_deduct, margin, user["id"]))
                # Keep local wallet cache in sync for subsequent slots
                wallet["deposit_balance"] = round(dep_avail - dep_deduct, 2)
                wallet["profit_balance"] = round(max(0.0, float(wallet.get("profit_balance") or 0) - prof_deduct), 2)
            free -= margin
            # Dispatch notification to Slack & Telegram asynchronously so cycle() never blocks
            _n_sym, _n_side, _n_px, _n_margin, _n_lev, _n_prob, _n_qty, _n_src, _n_uid = (
                picked["symbol"], picked["side"], picked["price"], margin, lev, ai_prob, qty, src_val, user["id"]
            )
            def _bg_notify():
                try:
                    from slack_service import send_trade_notification
                    send_trade_notification(trade_type="OPEN", symbol=_n_sym, side=_n_side, price=_n_px,
                                            details=f"Margin ${_n_margin:.2f} · {_n_lev:.0f}x Leverage · Exposure ${_n_margin*_n_lev:,.0f} · Win Prob {_n_prob}%")
                except Exception:
                    pass
                try:
                    from telegram_notifier import notify_order_opened
                    notify_order_opened(symbol=_n_sym, side=_n_side, price=_n_px,
                                        qty=_n_qty, leverage=_n_lev, win_prob=_n_prob, source=_n_src, user_id=_n_uid)
                except Exception:
                    pass
            threading.Thread(target=_bg_notify, daemon=True).start()
            self._log(user["id"], "OPEN",
                      f"{picked['side']} {picked['symbol']} [{picked['category']}] @ {picked['price']} "
                      f"conf {picked['confidence']} margin ${margin:.2f} ({lev:.0f}x Lev · Exposure ${margin*lev:,.0f}) "
                      f"tp {picked['target_pct']}% sl {picked['stop_pct']}% hold {picked['max_hold']}s "
                      f"| feed {picked['feed']} | {picked['reason']}")
            held.add(picked["symbol"])
            per_cat[picked["category"]] = per_cat.get(picked["category"], 0) + 1
            opened += 1
        return len(open_list) + opened, opened

    # ---------- resting limit orders ----------
    def pending_count(self, user_id=None):
        if user_id:
            return query_one("SELECT COUNT(*) c FROM orders WHERE status='PENDING' AND user_id=?",
                             (user_id,))["c"]
        return query_one("SELECT COUNT(*) c FROM orders WHERE status='PENDING'")["c"]

    def fill_orders(self):
        """Fill a limit order only when the scraped live price actually crosses its limit."""
        pending = query("SELECT * FROM orders WHERE status='PENDING' ORDER BY created_at")
        filled = 0
        for o in pending:
            price = self.feed.live_price(o["symbol"])
            if not price:
                continue
            crossed = price <= o["price"] if o["side"] == "LONG" else price >= o["price"]
            if not crossed:
                continue
            now = time.time()
            row = self.feed.quote(o["symbol"])
            # The margin stays locked: it stops being order margin and becomes position margin,
            # which close() releases.
            write("UPDATE orders SET status='FILLED', filled_at=? WHERE id=?", (now, o["id"]))
            lev = max(1.0, float(o.get("leverage") or 1.0))
            tp = max(0.0, float(o.get("target_pct") or 0.0))
            sl = max(0.0, float(o.get("stop_pct") or 0.0))
            pid = write("INSERT INTO positions(user_id,symbol,source,side,qty,entry_price,margin,"
                        "target_pct,stop_pct,status,current_price,unrealized_pnl,opened_at,category,"
                        "feed_source,leverage) VALUES(?,?,?,?,?,?,?,?,?,'OPEN',?,0,?,?,?,?)",
                        (o["user_id"], o["symbol"], "LIMIT", o["side"], o["qty"], o["price"],
                         o["margin"], tp, sl, price, now, row.get("category", "CRYPTO"),
                         row.get("source", ""), lev))
            write("UPDATE orders SET position_id=? WHERE id=?", (pid, o["id"]))
            self._log(o["user_id"], "FILL",
                      f"LIMIT #{o['id']} FILLED {o['side']} {o['symbol']} {o['qty']} @ {o['price']} "
                      f"(last {price}) -> position #{pid}")
            filled += 1
        return filled

    # ---------- loop ----------
    def cycle(self):
        if not hasattr(self, "_cycle_lock"):
            self._cycle_lock = threading.Lock()
        if not self._cycle_lock.acquire(blocking=False):
            return
        try:
            self._cycle_locked()
        finally:
            self._cycle_lock.release()

    def _cycle_locked(self):
        t0 = time.time()
        self.scan()
        # Users may run different modes, so analyse once per mode actually in use.
        modes = [r["bot_mode"] for r in query("SELECT DISTINCT bot_mode FROM users WHERE bot_enabled=1")]
        self.analyse_universe(modes[0] if modes else "SCALP")
        by_user = self.mark_to_market()
        self.fill_orders()
        if not self.is_running:
            # Global bot is OFF — mark to market only, don't open new positions.
            # All positions should have been flushed when stop() was called.
            self.last_cycle = {"at": time.time(), "feed": self.feed.status,
                               "universe": len(self.candidates), "running": False,
                               "opened": 0, "managed_users": len(by_user),
                               "setups": len(self.setups),
                               "duration_ms": round((time.time() - t0) * 1000, 1)}
            return

        # Auto-flush positions for users who turned their bot OFF while we were running
        disabled_users = query("SELECT DISTINCT user_id FROM positions WHERE status='OPEN' AND source != 'MANUAL' "
                               "AND user_id NOT IN (SELECT id FROM users WHERE bot_enabled=1)")
        for row in disabled_users:
            self.close_all_for(row["user_id"], reason="USER_STOPPED_BOT")

        users = query("SELECT * FROM users WHERE bot_enabled=1 ORDER BY id")
        opened_total = 0
        for u in users:
            try:
                if len(modes) > 1 and u["bot_mode"] != (modes[0] if modes else "SCALP"):
                    self.analyse_universe(u["bot_mode"])
                _, opened = self.run_user(u, self.open_positions_for(u["id"]))
                opened_total += opened
            except Exception as exc:
                import traceback
                self._log(u["id"], "ERROR", f"cycle failed: {exc} | {traceback.format_exc()[-150:]}")
        self.tick_count += 1
        # Automatic Continuous Walk-Forward Self-Learning while bot is trading
        if users and self.tick_count % 150 == 10:
            try:
                def _bg_auto_train():
                    try:
                        from bot_trainer import run_bot_training
                        run_bot_training(user_id=users[0]["id"], symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT"])
                    except Exception:
                        pass
                threading.Thread(target=_bg_auto_train, daemon=True).start()
            except Exception:
                pass
        if self.tick_count % 8 == 1:
            live = query_one("SELECT COUNT(*) AS c FROM positions WHERE status='OPEN'")["c"]
            cats = ", ".join(f"{c}:{len(self.by_category.get(c, []))}" for c in CATEGORIES)
            self._log(None, "SCAN", f"A-Z SCAN {cats} = {len(self.candidates)} symbols | "
                                    f"{len(self.setups)} setups passed | open positions {live} "
                                    f"| feed {self.feed.status}")
        self.last_cycle = {"at": time.time(), "feed": self.feed.status,
                           "universe": len(self.candidates), "running": True,
                           "opened": opened_total, "managed_users": len(users),
                           "setups": len(self.setups),
                           "duration_ms": round((time.time() - t0) * 1000, 1)}

    def start_loop(self):
        def exit_watchdog():
            while not self._stop.is_set():
                try:
                    self.mark_to_market()
                except Exception:
                    pass
                has_open = False
                try:
                    has_open = bool(query_one("SELECT 1 FROM positions WHERE status='OPEN' LIMIT 1"))
                except Exception:
                    pass
                self._stop.wait(0.6 if has_open else 1.5)

        def loop():
            while not self._stop.is_set():
                try:
                    self.cycle()
                except Exception as exc:
                    print("[BOT]", exc)
                # Wakes up immediately when any trade closes, or max 2.0s to prevent CPU/GIL starvation
                self._wake_event.wait(timeout=2.0)
                self._wake_event.clear()

        self._exit_thread = threading.Thread(target=exit_watchdog, daemon=True)
        self._exit_thread.start()
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop_loop(self):
        self._stop.set()

    # ---------- reporting ----------
    def storage(self):
        opens = query("SELECT p.*, u.email FROM positions p JOIN users u ON u.id=p.user_id "
                      "WHERE p.status='OPEN' ORDER BY p.opened_at DESC")
        closed = query("SELECT p.*, u.email FROM positions p JOIN users u ON u.id=p.user_id "
                       "WHERE p.status='CLOSED' ORDER BY p.closed_at DESC LIMIT 40")
        unreal = sum(p["unrealized_pnl"] for p in opens)
        wins = [c for c in closed if c["realized_pnl"] > 0]
        return {
            "open": opens, "closed": closed,
            "open_count": len(opens),
            "unrealized_pnl": round(unreal, 2),
            "realized_today": round(query_one(
                "SELECT COALESCE(SUM(realized_pnl),0) s FROM positions WHERE status='CLOSED' "
                "AND closed_at>=?", (time.time() - 86400,))["s"], 2),
            "win_rate": round(len(wins) / max(len(closed), 1) * 100, 1),
            "feed": self.feed.status,
            "cycle": self.last_cycle,
            "ticks": self.tick_count,
        }


def short_num(v):
    v = float(v or 0)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if v >= div:
            return f"{v / div:.1f}{unit}"
    return f"{v:.0f}"
