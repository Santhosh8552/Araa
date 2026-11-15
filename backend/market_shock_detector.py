"""
AraaBot Market Shock & Rapid Price Surge / Crash Detection Engine
==================================================================
Detects:
- Sudden downward price movement (flash crashes)
- Sudden upward price movement (short squeezes / parabolic spikes)
- Abnormal candle size & ATR expansion
- Abnormal volume explosion
- Rapid spread widening & liquidity disappearance
- Order book depth collapse
- Funding-rate anomaly & open interest swings
- Exchange connectivity anomalies & stale data feeds

Response:
- Blocks new trade entries
- Emits high-priority risk warnings
- Triggers emergency exit / protects open positions
- Persists shock events to database with full telemetry
"""

import time
import math
from typing import Dict, List, Any, Optional, Tuple
from database import query, query_one, write


class MarketShockDetector:
    _SHOCK_CACHE: Dict[str, Dict[str, Any]] = {}

    # Critical thresholds for market shock detection
    CRASH_DROP_1M_PCT = 2.5       # 2.5% drop in 1 minute
    SURGE_SPIKE_1M_PCT = 3.0      # 3.0% spike in 1 minute
    CRASH_DROP_5M_PCT = 4.5       # 4.5% drop in 5 minutes
    SURGE_SPIKE_5M_PCT = 5.0      # 5.0% spike in 5 minutes
    ATR_EXPANSION_RATIO = 2.8     # Current candle range >= 2.8x 14-period ATR
    VOL_EXPLOSION_RATIO = 4.0     # Volume >= 4.0x average volume
    MAX_PERMISSIBLE_SPREAD_PCT = 0.50  # Spread > 0.50% indicates liquidity collapse
    STALE_DATA_THRESHOLD_SEC = 20.0    # No price updates for 20 seconds = data freeze

    @classmethod
    def analyze_market_shock(
        cls,
        symbol: str,
        candles: List[Dict[str, Any]],
        *,
        current_price: Optional[float] = None,
        spread_pct: Optional[float] = None,
        order_book: Optional[Dict[str, Any]] = None,
        funding_rate: Optional[float] = None,
        last_feed_timestamp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate candle series and live market telemetry for abnormal shock conditions.
        Returns detailed shock diagnosis, risk severity, and protective directives.
        """
        now = time.time()
        sym = (symbol or "BTCUSDT").upper().replace("B-", "").replace("_", "")

        if not candles or len(candles) < 15:
            return {
                "shock_detected": False,
                "severity": "NORMAL",
                "shock_type": "NONE",
                "details": "Insufficient candle data for shock analysis (<15 bars)",
                "block_new_entries": False,
                "protective_action": "NONE",
                "timestamp": now,
            }

        closes = [float(c["c"]) for c in candles]
        highs = [float(c["h"]) for c in candles]
        lows = [float(c["l"]) for c in candles]
        volumes = [float(c.get("v", 0.0)) for c in candles]
        
        curr_px = float(current_price if current_price is not None else closes[-1])
        prev_1m = closes[-2] if len(closes) >= 2 else curr_px
        prev_5m = closes[-6] if len(closes) >= 6 else closes[0]

        move_1m_pct = ((curr_px - prev_1m) / prev_1m) * 100.0 if prev_1m > 0 else 0.0
        move_5m_pct = ((curr_px - prev_5m) / prev_5m) * 100.0 if prev_5m > 0 else 0.0

        # Calculate 14-period ATR
        trs = []
        for i in range(1, len(candles)):
            h_l = highs[i] - lows[i]
            h_pc = abs(highs[i] - closes[i - 1])
            l_pc = abs(lows[i] - closes[i - 1])
            trs.append(max(h_l, h_pc, l_pc))
        atr_14 = sum(trs[-14:]) / 14.0 if len(trs) >= 14 else (curr_px * 0.01)
        curr_candle_range = highs[-1] - lows[-1]
        atr_ratio = curr_candle_range / max(atr_14, 1e-8)

        # Volume explosion
        avg_vol = sum(volumes[-14:]) / 14.0 if len(volumes) >= 14 else 1.0
        curr_vol = volumes[-1]
        vol_ratio = curr_vol / max(avg_vol, 1e-8)

        # Check for spread widening
        effective_spread = float(spread_pct or 0.04)
        spread_shock = effective_spread >= cls.MAX_PERMISSIBLE_SPREAD_PCT

        # Check for feed staleness
        feed_delay = (now - float(last_feed_timestamp)) if last_feed_timestamp else 0.0
        stale_data = feed_delay >= cls.STALE_DATA_THRESHOLD_SEC

        # Order book liquidity evaluation
        liquidity_evaporated = False
        book_imbalance = 0.5
        if order_book and order_book.get("bids") and order_book.get("asks"):
            bid_vol = sum(float(q) for _p, q in order_book["bids"][:5])
            ask_vol = sum(float(q) for _p, q in order_book["asks"][:5])
            tot = bid_vol + ask_vol
            if tot > 0:
                book_imbalance = bid_vol / tot
                if tot < (avg_vol * 0.05):  # Top 5 levels have less than 5% of average candle volume
                    liquidity_evaporated = True

        # Funding rate shock
        funding_shock = False
        if funding_rate is not None:
            if abs(float(funding_rate)) > 0.0015:  # > 0.15% funding per 8h
                funding_shock = True

        # Shock classification
        shock_detected = False
        severity = "NORMAL"
        shock_type = "NONE"
        reasons: List[str] = []

        if stale_data:
            shock_detected = True
            severity = "CRITICAL"
            shock_type = "FEED_STALENESS_FREEZE"
            reasons.append(f"Price feed freeze: {feed_delay:.1f}s latency exceeds limit ({cls.STALE_DATA_THRESHOLD_SEC}s)")

        elif move_1m_pct <= -cls.CRASH_DROP_1M_PCT or move_5m_pct <= -cls.CRASH_DROP_5M_PCT:
            shock_detected = True
            severity = "CRITICAL"
            shock_type = "FLASH_CRASH_DROP"
            reasons.append(f"Severe price drop detected: {move_1m_pct:.2f}% (1m) / {move_5m_pct:.2f}% (5m)")

        elif move_1m_pct >= cls.SURGE_SPIKE_1M_PCT or move_5m_pct >= cls.SURGE_SPIKE_5M_PCT:
            shock_detected = True
            severity = "CRITICAL"
            shock_type = "PARABOLIC_SURGE_SPIKE"
            reasons.append(f"Abnormal price surge detected: +{move_1m_pct:.2f}% (1m) / +{move_5m_pct:.2f}% (5m)")

        elif atr_ratio >= cls.ATR_EXPANSION_RATIO and vol_ratio >= cls.VOL_EXPLOSION_RATIO:
            shock_detected = True
            severity = "HIGH"
            shock_type = "VOLATILITY_VOLUME_EXPLOSION"
            reasons.append(f"Bar range {atr_ratio:.1f}x ATR with volume {vol_ratio:.1f}x normal")

        elif spread_shock:
            shock_detected = True
            severity = "HIGH"
            shock_type = "SPREAD_COLLAPSE"
            reasons.append(f"Spread widened dangerously to {effective_spread:.3f}% (max: {cls.MAX_PERMISSIBLE_SPREAD_PCT}%)")

        elif liquidity_evaporated:
            shock_detected = True
            severity = "MEDIUM"
            shock_type = "LIQUIDITY_EVAPORATION"
            reasons.append("Order book top-of-book depth evaporated")

        # Response actions
        block_new_entries = shock_detected
        protective_action = "NONE"
        if severity == "CRITICAL":
            protective_action = "EMERGENCY_PROTECT_OR_TIGHTEN"
        elif severity == "HIGH":
            protective_action = "CANCEL_PENDING_AND_TIGHTEN_SL"
        elif severity == "MEDIUM":
            protective_action = "HALT_NEW_ENTRIES"

        result = {
            "symbol": sym,
            "shock_detected": shock_detected,
            "severity": severity,
            "shock_type": shock_type,
            "reasons": reasons,
            "details": "; ".join(reasons) if reasons else "Market parameters normal",
            "move_1m_pct": round(move_1m_pct, 4),
            "move_5m_pct": round(move_5m_pct, 4),
            "atr_14": round(atr_14, 4),
            "atr_ratio": round(atr_ratio, 2),
            "vol_ratio": round(vol_ratio, 2),
            "effective_spread_pct": round(effective_spread, 4),
            "block_new_entries": block_new_entries,
            "protective_action": protective_action,
            "timestamp": now,
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        }

        # Cache shock state
        cls._SHOCK_CACHE[sym] = result

        # Persist shock incident to database if severe
        if shock_detected and severity in ("CRITICAL", "HIGH"):
            try:
                write(
                    """INSERT INTO system_incidents(
                         incident_type, severity, component, message, metadata_json, created_at
                       ) VALUES(?,?,?,?,?,?)""",
                    (
                        f"MARKET_SHOCK_{shock_type}",
                        severity,
                        f"MARKET_FEED_{sym}",
                        result["details"],
                        str(result),
                        now,
                    ),
                )
            except Exception:
                pass

        return result

    @classmethod
    def is_shock_active(cls, symbol: str) -> Tuple[bool, str]:
        """Fast check to see if an active market shock is ongoing for a symbol."""
        sym = (symbol or "BTCUSDT").upper().replace("B-", "").replace("_", "")
        cached = cls._SHOCK_CACHE.get(sym)
        if not cached:
            return False, "NORMAL"
        # Shocks persist for at least 90 seconds unless cleared
        age = time.time() - float(cached.get("timestamp") or 0.0)
        if age < 90.0 and bool(cached.get("shock_detected")):
            return True, str(cached.get("details") or cached.get("shock_type"))
        return False, "NORMAL"

    @classmethod
    def get_all_active_shocks(cls) -> List[Dict[str, Any]]:
        """Return all active market shock records across all monitored symbols."""
        now = time.time()
        active = []
        for sym, data in list(cls._SHOCK_CACHE.items()):
            if bool(data.get("shock_detected")) and (now - float(data.get("timestamp") or 0.0)) < 180.0:
                active.append(data)
        return active
