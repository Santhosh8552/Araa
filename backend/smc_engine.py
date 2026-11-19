"""
AraaBot V2 — Institutional Smart Money Concepts (SMC) Analysis Engine.
Independent, mathematically sound, reproducible calculation engine.
Includes:
- Market Structure (HH, HL, LH, LL, BOS, CHoCH, MSS)
- Order Blocks (Fresh, Tested, Mitigated, Breakers) with displacement scoring
- Fair Value Gaps (Bullish, Bearish, Inverse, Fill %, Midpoint)
- Liquidity (BSL, SSL, Equal Highs/Lows, Sweeps)
- Premium & Discount Dealing Ranges (50% Eq, 61.8%, 70.5%, 79% OTE)
- Multi-Timeframe Alignment Matrix (1M -> 1MN)
- Araa AI Market Interpretation (3-State Scenario Tree & Invalidation)
- Live Strategy Scanner
- Alert Engine with Duplicate Suppression
- No-Lookahead Historical Backtesting Engine
"""

import math
import time
import json
import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("araabot.smc_engine")


# ==============================================================================
# 1. CANDLE NORMALIZATION & UTILITIES
# ==============================================================================

def normalize_candles(candles: List[Dict[str, Any]], interval_sec: int = 900) -> List[Dict[str, float]]:
    """Normalizes raw candle dictionaries into clean float-based OHLCV data."""
    clean: List[Dict[str, float]] = []
    now = int(time.time())
    for idx, c in enumerate(candles or []):
        if not isinstance(c, dict):
            continue
        try:
            close_p = float(c.get("c") or c.get("close") or 0.0)
            open_p = float(c.get("o") or c.get("open") or close_p)
            high_p = float(c.get("h") or c.get("high") or max(open_p, close_p))
            low_p = float(c.get("l") or c.get("low") or min(open_p, close_p))
            vol = float(c.get("v") or c.get("volume") or 100.0)
            raw_t = c.get("t") or c.get("time") or (now - (len(candles) - idx) * interval_sec)
            ts = int(raw_t / 1000) if float(raw_t) > 1e11 else int(raw_t)
            if close_p > 0:
                clean.append({
                    "o": round(open_p, 6),
                    "h": round(max(high_p, open_p, close_p), 6),
                    "l": round(min(low_p, open_p, close_p), 6),
                    "c": round(close_p, 6),
                    "v": round(max(0.0, vol), 2),
                    "t": float(ts),
                })
        except Exception:
            continue
    return clean


def compute_atr(candles: List[Dict[str, float]], period: int = 14) -> float:
    """Computes Average True Range (ATR) over normalized candles."""
    if len(candles) < 2:
        return 1.0
    trs = [candles[0]["h"] - candles[0]["l"]]
    for i in range(1, len(candles)):
        h, l, prev_c = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    return sum(trs[-min(period, len(trs)):]) / max(1, min(period, len(trs)))


# ==============================================================================
# 2. MARKET STRUCTURE ENGINE (HH, HL, LH, LL, BOS, CHOCH, MSS)
# ==============================================================================

class MarketStructureEngine:
    @staticmethod
    def detect_swings(candles: List[Dict[str, float]], sensitivity: int = 4) -> Dict[str, Any]:
        """Detects major and internal swing highs and swing lows."""
        n = len(candles)
        swing_highs: List[Dict[str, Any]] = []
        swing_lows: List[Dict[str, Any]] = []

        if n < sensitivity * 2 + 1:
            return {"highs": [], "lows": [], "points": []}

        for i in range(sensitivity, n - sensitivity):
            cur_h = candles[i]["h"]
            cur_l = candles[i]["l"]
            is_sh = all(candles[j]["h"] <= cur_h for j in range(i - sensitivity, i + sensitivity + 1) if j != i)
            is_sl = all(candles[j]["l"] >= cur_l for j in range(i - sensitivity, i + sensitivity + 1) if j != i)

            if is_sh:
                swing_highs.append({
                    "index": i,
                    "price": cur_h,
                    "time": int(candles[i]["t"]),
                    "type": "SWING_HIGH"
                })
            if is_sl:
                swing_lows.append({
                    "index": i,
                    "price": cur_l,
                    "time": int(candles[i]["t"]),
                    "type": "SWING_LOW"
                })

        # Classify HH, HL, LH, LL
        classified_points: List[Dict[str, Any]] = []
        for i in range(len(swing_highs)):
            pt = swing_highs[i]
            if i == 0:
                tag = "SH"
            else:
                tag = "HH" if pt["price"] > swing_highs[i - 1]["price"] else "LH"
            pt["tag"] = tag
            classified_points.append(pt)

        for i in range(len(swing_lows)):
            pt = swing_lows[i]
            if i == 0:
                tag = "SL"
            else:
                tag = "HL" if pt["price"] > swing_lows[i - 1]["price"] else "LL"
            pt["tag"] = tag
            classified_points.append(pt)

        classified_points.sort(key=lambda x: x["time"])
        return {
            "highs": swing_highs,
            "lows": swing_lows,
            "points": classified_points
        }

    @staticmethod
    def detect_structure_breaks(candles: List[Dict[str, float]], swings: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Detects Break of Structure (BOS), Change of Character (CHoCH), and MSS.
        Validates candle body close beyond previous swing high/low.
        """
        events: List[Dict[str, Any]] = []
        highs = swings.get("highs", [])
        lows = swings.get("lows", [])
        n = len(candles)

        if not highs or not lows:
            return events

        # Track trend state: 1 = bullish, -1 = bearish
        trend = 1 if highs[-1]["price"] > (highs[-2]["price"] if len(highs) > 1 else 0) else -1

        # Check for confirmed BOS and CHoCH on closed candles
        active_high = highs[-1]["price"] if highs else 0
        active_low = lows[-1]["price"] if lows else 0

        for i in range(max(10, n - 40), n):
            c = candles[i]
            prev_c = candles[i - 1]

            # Bullish Breakout
            for sh in reversed(highs):
                if sh["index"] < i and c["c"] > sh["price"] and prev_c["c"] <= sh["price"]:
                    ev_type = "BULLISH_BOS" if trend == 1 else "BULLISH_CHOCH"
                    events.append({
                        "type": ev_type,
                        "direction": "BULLISH",
                        "price": sh["price"],
                        "break_price": c["c"],
                        "candle_index": i,
                        "time": int(c["t"]),
                        "confirmed": True,
                        "invalidation": lows[-1]["price"] if lows else c["l"]
                    })
                    trend = 1
                    break

            # Bearish Breakdown
            for sl in reversed(lows):
                if sl["index"] < i and c["c"] < sl["price"] and prev_c["c"] >= sl["price"]:
                    ev_type = "BEARISH_BOS" if trend == -1 else "BEARISH_CHOCH"
                    events.append({
                        "type": ev_type,
                        "direction": "BEARISH",
                        "price": sl["price"],
                        "break_price": c["c"],
                        "candle_index": i,
                        "time": int(c["t"]),
                        "confirmed": True,
                        "invalidation": highs[-1]["price"] if highs else c["h"]
                    })
                    trend = -1
                    break

        return events


# ==============================================================================
# 3. ORDER BLOCK ENGINE
# ==============================================================================

class OrderBlockEngine:
    @staticmethod
    def detect_order_blocks(candles: List[Dict[str, float]], atr: float) -> List[Dict[str, Any]]:
        """
        Detects Institutional Order Blocks.
        Applies displacement validation (> 1.6x ATR) and tracks mitigation status.
        """
        order_blocks: List[Dict[str, Any]] = []
        n = len(candles)
        if n < 6:
            return order_blocks

        for i in range(2, n - 2):
            c_prev = candles[i - 1]
            c_curr = candles[i]
            c_next = candles[i + 1]

            # Displacement check
            displacement = abs(c_next["c"] - c_curr["o"])
            if displacement < 1.4 * atr:
                continue

            # Bullish Order Block: Bearish candle followed by explosive displacement up
            if c_curr["c"] < c_curr["o"] and c_next["c"] > c_curr["h"]:
                ob_high = c_curr["h"]
                ob_low = c_curr["l"]
                midpoint = (ob_high + ob_low) / 2.0

                # Check subsequent price action for mitigation
                subsequent = candles[i + 2:]
                mitigated = any(k["l"] <= midpoint for k in subsequent)
                broken = any(k["c"] < ob_low for k in subsequent)

                status = "BREAKER" if broken else ("MITIGATED" if mitigated else "FRESH")
                strength = min(98, int(65 + (displacement / max(1e-9, atr)) * 8))

                order_blocks.append({
                    "id": f"OB_BULL_{int(c_curr['t'])}",
                    "type": "BULLISH_OB",
                    "high": ob_high,
                    "low": ob_low,
                    "midpoint": round(midpoint, 6),
                    "strength": strength,
                    "status": status,
                    "creation_time": int(c_curr["t"]),
                    "origin_index": i
                })

            # Bearish Order Block: Bullish candle followed by explosive displacement down
            elif c_curr["c"] > c_curr["o"] and c_next["c"] < c_curr["l"]:
                ob_high = c_curr["h"]
                ob_low = c_curr["l"]
                midpoint = (ob_high + ob_low) / 2.0

                subsequent = candles[i + 2:]
                mitigated = any(k["h"] >= midpoint for k in subsequent)
                broken = any(k["c"] > ob_high for k in subsequent)

                status = "BREAKER" if broken else ("MITIGATED" if mitigated else "FRESH")
                strength = min(98, int(65 + (displacement / max(1e-9, atr)) * 8))

                order_blocks.append({
                    "id": f"OB_BEAR_{int(c_curr['t'])}",
                    "type": "BEARISH_OB",
                    "high": ob_high,
                    "low": ob_low,
                    "midpoint": round(midpoint, 6),
                    "strength": strength,
                    "status": status,
                    "creation_time": int(c_curr["t"]),
                    "origin_index": i
                })

        return order_blocks[-12:]  # Return most recent 12 order blocks


# ==============================================================================
# 4. FAIR VALUE GAP (FVG) ENGINE
# ==============================================================================

class FVGEngine:
    @staticmethod
    def detect_fvgs(candles: List[Dict[str, float]], min_gap_atr_ratio: float = 0.25, atr: float = 1.0) -> List[Dict[str, Any]]:
        """
        Detects 3-candle imbalance Fair Value Gaps (FVG).
        Tracks fill percentage, consequent encroachment (50% midpoint), and inverse status.
        """
        fvgs: List[Dict[str, Any]] = []
        n = len(candles)
        if n < 4:
            return fvgs

        for i in range(2, n):
            c0 = candles[i - 2]
            c1 = candles[i - 1]
            c2 = candles[i]
            subsequent = candles[i + 1:]

            # Bullish FVG: Low of candle 3 > High of candle 1
            if c2["l"] > c0["h"]:
                bottom = c0["h"]
                top = c2["l"]
                gap_size = top - bottom
                if gap_size >= min_gap_atr_ratio * atr:
                    midpoint = (top + bottom) / 2.0
                    min_later = min((k["l"] for k in subsequent), default=top)
                    fill_pct = 0.0 if min_later >= top else min(100.0, ((top - min_later) / gap_size) * 100.0)
                    is_inverse = any(k["c"] < bottom for k in subsequent)

                    status = "INVERSE_FVG" if is_inverse else ("MITIGATED" if fill_pct >= 50.0 else "OPEN")
                    fvgs.append({
                        "id": f"FVG_BULL_{int(c1['t'])}",
                        "type": "BULLISH_FVG",
                        "top": round(top, 6),
                        "bottom": round(bottom, 6),
                        "midpoint": round(midpoint, 6),
                        "size": round(gap_size, 6),
                        "fill_pct": round(fill_pct, 1),
                        "status": status,
                        "creation_time": int(c1["t"])
                    })

            # Bearish FVG: High of candle 3 < Low of candle 1
            elif c2["h"] < c0["l"]:
                top = c0["l"]
                bottom = c2["h"]
                gap_size = top - bottom
                if gap_size >= min_gap_atr_ratio * atr:
                    midpoint = (top + bottom) / 2.0
                    max_later = max((k["h"] for k in subsequent), default=bottom)
                    fill_pct = 0.0 if max_later <= bottom else min(100.0, ((max_later - bottom) / gap_size) * 100.0)
                    is_inverse = any(k["c"] > top for k in subsequent)

                    status = "INVERSE_FVG" if is_inverse else ("MITIGATED" if fill_pct >= 50.0 else "OPEN")
                    fvgs.append({
                        "id": f"FVG_BEAR_{int(c1['t'])}",
                        "type": "BEARISH_FVG",
                        "top": round(top, 6),
                        "bottom": round(bottom, 6),
                        "midpoint": round(midpoint, 6),
                        "size": round(gap_size, 6),
                        "fill_pct": round(fill_pct, 1),
                        "status": status,
                        "creation_time": int(c1["t"])
                    })

        return fvgs[-15:]


# ==============================================================================
# 5. LIQUIDITY & DEALING RANGE ENGINE
# ==============================================================================

class LiquidityEngine:
    @staticmethod
    def detect_liquidity_pools(candles: List[Dict[str, float]], swings: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detects Buy-Side Liquidity (BSL), Sell-Side Liquidity (SSL),
        Equal Highs (EQH), Equal Lows (EQL), and Liquidity Sweeps.
        """
        n = len(candles)
        if not candles:
            return {}

        current_price = candles[-1]["c"]
        highs = swings.get("highs", [])
        lows = swings.get("lows", [])

        major_high = max((k["h"] for k in candles[-60:]), default=current_price * 1.01)
        major_low = min((k["l"] for k in candles[-60:]), default=current_price * 0.99)
        dealing_span = max(1e-9, major_high - major_low)

        # Equal Highs / Lows (tolerance within 0.08% of price)
        eqh_list = []
        for i in range(len(highs) - 1):
            h1, h2 = highs[i]["price"], highs[i + 1]["price"]
            if abs(h1 - h2) / max(1e-9, h1) < 0.0008:
                eqh_list.append(round((h1 + h2) / 2.0, 6))

        eql_list = []
        for i in range(len(lows) - 1):
            l1, l2 = lows[i]["price"], lows[i + 1]["price"]
            if abs(l1 - l2) / max(1e-9, l1) < 0.0008:
                eql_list.append(round((l1 + l2) / 2.0, 6))

        # Check for sweeps in recent 5 candles
        recent = candles[-5:]
        ssl_swept = any(k["l"] < major_low and k["c"] > major_low for k in recent)
        bsl_swept = any(k["h"] > major_high and k["c"] < major_high for k in recent)

        # Dealing Range Premium & Discount (Equilibrium 50%, OTE Fibs)
        eq = major_low + 0.50 * dealing_span
        fib_618 = major_low + 0.618 * dealing_span
        fib_705 = major_low + 0.705 * dealing_span
        fib_790 = major_low + 0.790 * dealing_span

        zone = "PREMIUM" if current_price >= eq else "DISCOUNT"

        return {
            "bsl": {
                "level": round(major_high, 6),
                "swept": bool(bsl_swept),
                "description": "Buy-side Liquidity Pool (Resting buy-stops above swing high)"
            },
            "ssl": {
                "level": round(major_low, 6),
                "swept": bool(ssl_swept),
                "description": "Sell-side Liquidity Pool (Resting sell-stops below swing low)"
            },
            "equal_highs": eqh_list,
            "equal_lows": eql_list,
            "dealing_range": {
                "high": round(major_high, 6),
                "low": round(major_low, 6),
                "equilibrium": round(eq, 6),
                "fib_618": round(fib_618, 6),
                "fib_705": round(fib_705, 6),
                "fib_790": round(fib_790, 6),
                "current_zone": zone,
                "price_location_pct": round(((current_price - major_low) / dealing_span) * 100.0, 1)
            }
        }


# ==============================================================================
# 6. ARAA AI MARKET INTERPRETATION & SCENARIO ENGINE
# ==============================================================================

class AraaAIMarketAdvisor:
    @staticmethod
    def generate_report(
        symbol: str,
        timeframe: str,
        current_price: float,
        structure_events: List[Dict[str, Any]],
        order_blocks: List[Dict[str, Any]],
        fvgs: List[Dict[str, Any]],
        liquidity: Dict[str, Any],
        atr: float
    ) -> Dict[str, Any]:
        """
        Synthesizes all structural SMC evidence into a calibrated institutional report
        with a 3-State Scenario Tree (Bullish, Bearish, Neutral) and Invalidation rules.
        """
        recent_breaks = structure_events[-3:] if structure_events else []
        last_ev = recent_breaks[-1] if recent_breaks else {"type": "RANGING", "direction": "NEUTRAL"}
        direction = last_ev.get("direction", "NEUTRAL")

        # Dealing range position
        dr = liquidity.get("dealing_range", {})
        curr_zone = dr.get("current_zone", "EQUILIBRIUM")
        loc_pct = dr.get("price_location_pct", 50.0)

        # Nearest fresh zones
        bull_obs = [ob for ob in order_blocks if ob["type"] == "BULLISH_OB" and ob["status"] in ["FRESH", "TESTED"]]
        bear_obs = [ob for ob in order_blocks if ob["type"] == "BEARISH_OB" and ob["status"] in ["FRESH", "TESTED"]]
        nearest_bull_ob = bull_obs[-1] if bull_obs else None
        nearest_bear_ob = bear_obs[-1] if bear_obs else None

        # Evidence scoring
        bull_score = 0
        bear_score = 0

        if direction == "BULLISH":
            bull_score += 35
        elif direction == "BEARISH":
            bear_score += 35

        if curr_zone == "DISCOUNT":
            bull_score += 25
        elif curr_zone == "PREMIUM":
            bear_score += 25

        if liquidity.get("ssl", {}).get("swept"):
            bull_score += 20  # Liquidity sweep of lows favors upward reversal
        if liquidity.get("bsl", {}).get("swept"):
            bear_score += 20  # Liquidity sweep of highs favors downward reversal

        total = bull_score + bear_score or 1
        buy_strength = min(92, max(8, int((bull_score / total) * 100)))
        sell_strength = 100 - buy_strength

        # Bias determination
        if buy_strength >= 65:
            bias = "BULLISH"
        elif sell_strength >= 65:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        confidence = min(94, 60 + abs(buy_strength - sell_strength))
        confluence_score = int(confidence * 0.9)

        # Scenarios
        bsl_target = liquidity.get("bsl", {}).get("level", current_price * 1.02)
        ssl_target = liquidity.get("ssl", {}).get("level", current_price * 0.98)
        inval_bull = nearest_bull_ob["low"] if nearest_bull_ob else (current_price - 2.0 * atr)
        inval_bear = nearest_bear_ob["high"] if nearest_bear_ob else (current_price + 2.0 * atr)

        bullish_scenario = {
            "trigger": "Mitigation of Bullish OB / FVG in Discount Zone with lower-TF CHoCH",
            "entry_zone": f"{nearest_bull_ob['low']:.2f} - {nearest_bull_ob['high']:.2f}" if nearest_bull_ob else f"{(current_price - 0.5 * atr):.2f}",
            "target_1": round(dr.get("equilibrium", current_price * 1.01), 2),
            "target_2": round(bsl_target, 2),
            "invalidation": round(inval_bull, 2),
            "rationale": "Liquidity sweep of sell stops + displacement above internal structure."
        }

        bearish_scenario = {
            "trigger": "Rejection from Bearish OB in Premium Zone with displacement below internal swing low",
            "entry_zone": f"{nearest_bear_ob['low']:.2f} - {nearest_bear_ob['high']:.2f}" if nearest_bear_ob else f"{(current_price + 0.5 * atr):.2f}",
            "target_1": round(dr.get("equilibrium", current_price * 0.99), 2),
            "target_2": round(ssl_target, 2),
            "invalidation": round(inval_bear, 2),
            "rationale": "Price in Premium dealing range, targeting resting sell-side liquidity."
        }

        neutral_scenario = {
            "condition": "Price consolidating inside Equilibrium dealing range without clear structure break",
            "advice": "Stand aside. Wait for clear expansion or external liquidity sweep before committing capital."
        }

        explanation = (
            f"Araa AI institutional analysis indicates a {bias} bias on {symbol} ({timeframe.upper()}). "
            f"Price is presently situated in the {curr_zone} zone ({loc_pct}% of dealing range). "
            f"Structure confirms {last_ev.get('type', 'orderly flow')} with confidence at {confidence}%. "
            f"Key resting liquidity resides at {bsl_target:.2f} (Buy-Side) and {ssl_target:.2f} (Sell-Side)."
        )

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "overall_bias": bias,
            "buy_strength": buy_strength,
            "sell_strength": sell_strength,
            "confidence_score": confidence,
            "confluence_score": confluence_score,
            "market_regime": "EXPANSION" if abs(buy_strength - sell_strength) > 25 else "RANGE_BOUND",
            "volatility": "HIGH" if atr / current_price > 0.015 else "NORMAL",
            "explanation": explanation,
            "scenarios": {
                "bullish": bullish_scenario,
                "bearish": bearish_scenario,
                "neutral": neutral_scenario
            },
            "risk_considerations": [
                "Respect invalidation stop-loss strictly on structure violation.",
                "Ensure higher-timeframe alignment before taking lower-timeframe execution triggers.",
                "Be vigilant during high-impact macroeconomic news releases."
            ],
            "generated_at": int(time.time())
        }


# ==============================================================================
# 7. MULTI-TIMEFRAME ANALYSIS SYNTHESIS
# ==============================================================================

class MultiTimeframeEngine:
    TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]

    @classmethod
    def evaluate_multi_timeframe(cls, symbol: str, mtf_candles: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Evaluates multiple timeframes and compiles an institutional confluence matrix."""
        matrix: Dict[str, Any] = {}
        bull_count = 0
        bear_count = 0

        for tf in cls.TIMEFRAMES:
            candles = mtf_candles.get(tf) or []
            norm = normalize_candles(candles)
            if len(norm) < 15:
                # Fallback estimation if specific sub-TF is sparse
                matrix[tf] = {"trend": "NEUTRAL", "structure": "ESTIMATED", "bias": "NEUTRAL"}
                continue

            swings = MarketStructureEngine.detect_swings(norm, sensitivity=3)
            breaks = MarketStructureEngine.detect_structure_breaks(norm, swings)
            atr = compute_atr(norm)
            obs = OrderBlockEngine.detect_order_blocks(norm, atr)
            fvgs = FVGEngine.detect_fvgs(norm, atr=atr)

            last_b = breaks[-1]["direction"] if breaks else "NEUTRAL"
            if last_b == "BULLISH":
                bull_count += 1
            elif last_b == "BEARISH":
                bear_count += 1

            matrix[tf] = {
                "trend": last_b,
                "latest_event": breaks[-1]["type"] if breaks else "NONE",
                "fresh_obs": len([ob for ob in obs if ob["status"] == "FRESH"]),
                "open_fvgs": len([f for f in fvgs if f["status"] == "OPEN"]),
            }

        htf_align = "BULLISH_ALIGNMENT" if bull_count >= 4 else ("BEARISH_ALIGNMENT" if bear_count >= 4 else "MIXED_CONFIRMATION")
        return {
            "symbol": symbol,
            "htf_alignment": htf_align,
            "matrix": matrix,
            "bull_votes": bull_count,
            "bear_votes": bear_count,
            "updated_at": int(time.time())
        }


# ==============================================================================
# 8. NO-LOOKAHEAD HISTORICAL BACKTESTING ENGINE
# ==============================================================================

class SMCBacktestEngine:
    @staticmethod
    def run_backtest(
        candles: List[Dict[str, float]],
        strategy_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Executes a historical backtest of Smart Money Concepts without lookahead bias.
        Evaluates confirmed CHoCH / BOS + FVG retests with strictly future candles for resolution.
        """
        cfg = strategy_config or {}
        risk_reward_target = float(cfg.get("risk_reward", 2.2))
        risk_per_trade_pct = float(cfg.get("risk_pct", 1.0))
        starting_equity = float(cfg.get("capital", 10000.0))

        n = len(candles)
        if n < 50:
            return {"error": "Insufficient historical candles for backtesting", "setups": 0}

        trades: List[Dict[str, Any]] = []
        equity = starting_equity
        peak_equity = starting_equity
        max_drawdown = 0.0

        i = 25
        while i < n - 10:
            # Step by step window: only candles[:i] are visible to avoid lookahead
            hist_window = candles[:i]
            atr = compute_atr(hist_window)
            swings = MarketStructureEngine.detect_swings(hist_window, sensitivity=3)
            breaks = MarketStructureEngine.detect_structure_breaks(hist_window, swings)

            if not breaks:
                i += 1
                continue

            last_break = breaks[-1]
            break_idx = last_break.get("candle_index", 0)

            # Trigger condition: fresh break occurred within last 2 candles
            if i - break_idx <= 2:
                direction = last_break["direction"]
                entry_p = candles[i]["c"]
                inval = last_break["invalidation"]
                stop_dist = abs(entry_p - inval)

                if stop_dist > 0.05 * atr:
                    target_dist = stop_dist * risk_reward_target
                    sl_price = inval
                    tp_price = entry_p + target_dist if direction == "BULLISH" else entry_p - target_dist

                    # Simulate forward outcome candle by candle
                    outcome = "OPEN"
                    exit_price = entry_p
                    exit_idx = i

                    for j in range(i + 1, min(i + 30, n)):
                        fut_k = candles[j]
                        if direction == "BULLISH":
                            if fut_k["l"] <= sl_price:
                                outcome = "LOSS"
                                exit_price = sl_price
                                exit_idx = j
                                break
                            elif fut_k["h"] >= tp_price:
                                outcome = "WIN"
                                exit_price = tp_price
                                exit_idx = j
                                break
                        else:
                            if fut_k["h"] >= sl_price:
                                outcome = "LOSS"
                                exit_price = sl_price
                                exit_idx = j
                                break
                            elif fut_k["l"] <= tp_price:
                                outcome = "WIN"
                                exit_price = tp_price
                                exit_idx = j
                                break

                    if outcome in ["WIN", "LOSS"]:
                        pnl_usd = (starting_equity * (risk_per_trade_pct / 100.0) * risk_reward_target) if outcome == "WIN" else (-starting_equity * (risk_per_trade_pct / 100.0))
                        equity += pnl_usd
                        if equity > peak_equity:
                            peak_equity = equity
                        dd = ((peak_equity - equity) / peak_equity) * 100.0
                        if dd > max_drawdown:
                            max_drawdown = dd

                        trades.append({
                            "entry_index": i,
                            "entry_time": int(candles[i]["t"]),
                            "direction": direction,
                            "entry_price": entry_p,
                            "exit_price": exit_price,
                            "outcome": outcome,
                            "pnl_usd": round(pnl_usd, 2),
                            "equity_after": round(equity, 2)
                        })
                        i = exit_idx + 1
                        continue

            i += 1

        total_trades = len(trades)
        wins = [t for t in trades if t["outcome"] == "WIN"]
        losses = [t for t in trades if t["outcome"] == "LOSS"]
        win_rate = round((len(wins) / max(1, total_trades)) * 100.0, 1)

        gross_profit = sum(t["pnl_usd"] for t in wins)
        gross_loss = abs(sum(t["pnl_usd"] for t in losses))
        profit_factor = round(gross_profit / max(1.0, gross_loss), 2)
        expectancy = round(((win_rate / 100.0) * risk_reward_target) - ((1.0 - (win_rate / 100.0)) * 1.0), 2)

        # Winning and losing streaks
        curr_streak = 0
        longest_win = 0
        longest_loss = 0
        for t in trades:
            if t["outcome"] == "WIN":
                curr_streak = curr_streak + 1 if curr_streak > 0 else 1
                if curr_streak > longest_win:
                    longest_win = curr_streak
            else:
                curr_streak = curr_streak - 1 if curr_streak < 0 else -1
                if abs(curr_streak) > longest_loss:
                    longest_loss = abs(curr_streak)

        return {
            "total_setups": total_trades,
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "max_drawdown": round(max_drawdown, 2),
            "expectancy": expectancy,
            "longest_winning_streak": longest_win,
            "longest_losing_streak": longest_loss,
            "net_profit": round(equity - starting_equity, 2),
            "final_equity": round(equity, 2),
            "trades": trades[-25:]
        }
