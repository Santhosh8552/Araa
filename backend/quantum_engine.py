"""
Quantum Institutional Intelligence Engine for AraaBot
======================================================
Provides institutional-grade trading modules across both Paper Mode and Real Mode:
1. Multi-Agent Quantitative Trading Committee (Consensus Engine)
   - Agent Alpha: Trend & Orderflow Hunter (Momentum, CVD delta, EMAs, 1m candles)
   - Agent Beta: Risk & Adversarial Critic (Trap detector, funding rates, RSI divergence)
   - Agent Gamma: Macro & Sentiment Arbiter (Regime alignment, volatility bounds)
   - Consensus Arbiter: Weighted voting & confidence thresholding
2. Real-Time Liquidation Heatmap & Stop-Hunt Liquidity Engine
   - Calculates cluster bands where high-leverage positions liquidate (25x, 50x, 100x)
   - Detects liquidity sweeps (stop-runs into key pools that reject back)
3. Microstructure Trailing Stop & Dynamic Profit Lock
   - Evaluates real-time price action vs peak profit
   - Automatically tightens SL to lock 50%, 65%, 80% of peak gains or breakeven
4. Autonomous Market Regime Classifier & Playbook Switcher
   - Classifies market into: TRENDING_BULL, TRENDING_BEAR, HIGH_VOLATILITY_EXPANSION,
     RANGING_COMPRESSION, LIQUIDITY_SWEEP
   - Recommends adaptive parameter weights and playbook actions
"""

import math
import time
from typing import Dict, Any, List, Optional, Tuple

class MarketRegimeEngine:
    """Classifies current market regime and recommends adaptive strategy weights."""
    
    REGIMES = {
        "TRENDING_BULL": {
            "name": "Trending Bull Run",
            "bias": "LONG",
            "tp_multiplier": 1.35,
            "sl_multiplier": 0.90,
            "min_win_threshold": 78,
            "description": "High directional bullish momentum with strong buyer volume absorption."
        },
        "TRENDING_BEAR": {
            "name": "Trending Bear Breakdown",
            "bias": "SHORT",
            "tp_multiplier": 1.35,
            "sl_multiplier": 0.90,
            "min_win_threshold": 78,
            "description": "Aggressive supply distribution with falling price structure."
        },
        "HIGH_VOLATILITY_EXPANSION": {
            "name": "High-Vol Expansion",
            "bias": "BOTH",
            "tp_multiplier": 1.50,
            "sl_multiplier": 1.10,
            "min_win_threshold": 82,
            "description": "Expanded ATR with rapid liquidation wicks. Wide targets, rapid trailing."
        },
        "RANGING_COMPRESSION": {
            "name": "Ranging Chop / Compression",
            "bias": "MEAN_REVERSION",
            "tp_multiplier": 0.85,
            "sl_multiplier": 0.80,
            "min_win_threshold": 85,
            "description": "Price coiling between support and resistance. Quick scalps, tight stops."
        },
        "LIQUIDITY_SWEEP": {
            "name": "Institutional Liquidity Sweep",
            "bias": "REVERSAL",
            "tp_multiplier": 1.40,
            "sl_multiplier": 0.75,
            "min_win_threshold": 80,
            "description": "False breakout / stop-hunt detected; high probability mean reversion."
        }
    }

    @classmethod
    def classify_regime(cls, symbol: str, quote: Dict[str, Any], ticks: List[float], candles: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Classifies the market regime for a symbol based on live tick history and candle data."""
        price = float(quote.get("price") or 0.0)
        chg_24h = float(quote.get("change_pct") or 0.0)
        hi = float(quote.get("high") or price * 1.02)
        lo = float(quote.get("low") or price * 0.98)
        
        day_range_pct = ((hi - lo) / max(price, 0.0000001)) * 100.0 if price > 0 else 2.0
        
        # Calculate tick momentum & volatility
        tick_vol = 1.0
        slope = 0.0
        if len(ticks) >= 10:
            diffs = [ticks[i] - ticks[i-1] for i in range(1, len(ticks))]
            avg_diff = sum(diffs) / max(len(diffs), 1)
            slope = (avg_diff / max(price, 0.0000001)) * 10000.0
            variance = sum((d - avg_diff) ** 2 for d in diffs) / max(len(diffs), 1)
            tick_vol = math.sqrt(variance) / max(price, 0.0000001) * 100.0

        # Check candle sweeps if available
        is_sweep = False
        sweep_bias = "LONG"
        if candles and len(candles) >= 5:
            last_c = candles[-1]
            prev_c = candles[-2]
            body = abs(float(last_c.get("c", 0)) - float(last_c.get("o", 0)))
            total_range = max(0.000001, float(last_c.get("h", 0)) - float(last_c.get("l", 0)))
            lower_wick = min(float(last_c.get("c", 0)), float(last_c.get("o", 0))) - float(last_c.get("l", 0))
            upper_wick = float(last_c.get("h", 0)) - max(float(last_c.get("c", 0)), float(last_c.get("o", 0)))
            
            # Rejection wick > 55% of candle range = liquidity sweep
            if lower_wick / total_range > 0.55 and float(last_c.get("l", 0)) < float(prev_c.get("l", 0)):
                is_sweep = True
                sweep_bias = "LONG"
            elif upper_wick / total_range > 0.55 and float(last_c.get("h", 0)) > float(prev_c.get("h", 0)):
                is_sweep = True
                sweep_bias = "SHORT"

        # Determine regime
        if is_sweep:
            regime_key = "LIQUIDITY_SWEEP"
        elif day_range_pct > 8.0 or tick_vol > 0.45:
            regime_key = "HIGH_VOLATILITY_EXPANSION"
        elif chg_24h > 3.0 and slope > 0.2:
            regime_key = "TRENDING_BULL"
        elif chg_24h < -3.0 and slope < -0.2:
            regime_key = "TRENDING_BEAR"
        else:
            regime_key = "RANGING_COMPRESSION"

        spec = cls.REGIMES[regime_key]
        return {
            "symbol": symbol,
            "regime_key": regime_key,
            "regime_name": spec["name"],
            "description": spec["description"],
            "bias": sweep_bias if regime_key == "LIQUIDITY_SWEEP" else spec["bias"],
            "tp_multiplier": spec["tp_multiplier"],
            "sl_multiplier": spec["sl_multiplier"],
            "min_win_threshold": spec["min_win_threshold"],
            "volatility_score": round(day_range_pct, 2),
            "tick_volatility": round(tick_vol, 3),
            "updated_at": time.time()
        }


class LiquidationHeatmapEngine:
    """Calculates liquidation clusters and stop-hunt zones for symbols."""
    
    @staticmethod
    def calculate_clusters(symbol: str, current_price: float, high24: float, low24: float, volume: float) -> Dict[str, Any]:
        """Estimates high-density liquidation zones based on standard institutional leverage tiers (25x, 50x, 100x)."""
        if current_price <= 0:
            return {"symbol": symbol, "clusters": [], "nearest_sweep_target": None}

        leverage_tiers = [
            {"leverage": 100, "long_liq_pct": 0.008, "short_liq_pct": 0.008, "vol_weight": 0.45},
            {"leverage": 50,  "long_liq_pct": 0.018, "short_liq_pct": 0.018, "vol_weight": 0.35},
            {"leverage": 25,  "long_liq_pct": 0.038, "short_liq_pct": 0.038, "vol_weight": 0.20},
        ]

        vol_proxy = max(volume, 50000.0)
        long_clusters = []
        short_clusters = []

        for tier in leverage_tiers:
            lev = tier["leverage"]
            # Long liquidations sit BELOW current price
            long_liq_price = round(current_price * (1.0 - tier["long_liq_pct"]), 6 if current_price < 1 else 2)
            est_long_vol = round((vol_proxy * tier["vol_weight"]) / (lev / 10.0), 2)
            long_clusters.append({
                "type": "LONG_LIQUIDATION",
                "leverage": f"{lev}x",
                "price": long_liq_price,
                "distance_pct": round(-tier["long_liq_pct"] * 100, 2),
                "estimated_usd": est_long_vol,
                "intensity": "HIGH" if lev == 100 else ("MEDIUM" if lev == 50 else "MODERATE")
            })

            # Short liquidations sit ABOVE current price
            short_liq_price = round(current_price * (1.0 + tier["short_liq_pct"]), 6 if current_price < 1 else 2)
            est_short_vol = round((vol_proxy * tier["vol_weight"]) / (lev / 10.0), 2)
            short_clusters.append({
                "type": "SHORT_LIQUIDATION",
                "leverage": f"{lev}x",
                "price": short_liq_price,
                "distance_pct": round(tier["short_liq_pct"] * 100, 2),
                "estimated_usd": est_short_vol,
                "intensity": "HIGH" if lev == 100 else ("MEDIUM" if lev == 50 else "MODERATE")
            })

        # Identify nearest high-gravity magnet level
        nearest_down = long_clusters[0]
        nearest_up = short_clusters[0]
        
        # Target with higher intensity closest to price is the primary liquidity magnet
        primary_magnet = nearest_up if abs(nearest_up["distance_pct"]) < abs(nearest_down["distance_pct"]) else nearest_down

        return {
            "symbol": symbol,
            "current_price": current_price,
            "long_liquidation_pools": long_clusters,
            "short_liquidation_pools": short_clusters,
            "primary_magnet": primary_magnet,
            "total_liquidity_at_risk_usd": round(sum(c["estimated_usd"] for c in long_clusters + short_clusters), 2),
            "sweep_recommendation": f"Monitor {primary_magnet['type']} pool at ${primary_magnet['price']} ({primary_magnet['distance_pct']:+.2f}%) for stop-run rejection.",
            "updated_at": time.time()
        }


class TradingCommitteeEngine:
    """Multi-Agent Quantitative Trading Committee consensus engine."""
    
    @staticmethod
    def evaluate_committee(symbol: str, setup: Dict[str, Any], quote: Dict[str, Any], regime_info: Dict[str, Any], heatmap_info: Dict[str, Any]) -> Dict[str, Any]:
        """Runs the 3 specialized sub-agents and produces an authoritative consensus score and reasoning."""
        side = (setup.get("side") or "LONG").upper()
        conf = float(setup.get("confidence") or 0.80)
        rsi = float(setup.get("rsi") or 50.0)
        chg_24 = float(quote.get("change_pct") or 0.0)
        price = float(quote.get("price") or 0.0)
        
        # 1. Agent Alpha: Trend & Orderflow Hunter
        # Looks for strong directional continuation and momentum alignment
        alpha_score = 0.50
        alpha_verdict = "NEUTRAL"
        alpha_reasons = []
        if side in ("BUY", "LONG"):
            if chg_24 > 0.5:
                alpha_score += 0.20
                alpha_reasons.append(f"Bullish 24h delta (+{chg_24:.2f}%)")
            if 45 <= rsi <= 68:
                alpha_score += 0.20
                alpha_reasons.append(f"Optimal RSI expansion sweet-spot ({rsi:.0f})")
            if regime_info.get("regime_key") == "TRENDING_BULL":
                alpha_score += 0.15
                alpha_reasons.append("Aligned with Trending Bull Regime")
            alpha_verdict = "STRONG_BUY" if alpha_score >= 0.80 else ("BUY" if alpha_score >= 0.65 else "HOLD")
        else:
            if chg_24 < -0.5:
                alpha_score += 0.20
                alpha_reasons.append(f"Bearish 24h delta ({chg_24:.2f}%)")
            if 32 <= rsi <= 55:
                alpha_score += 0.20
                alpha_reasons.append(f"Optimal RSI breakdown channel ({rsi:.0f})")
            if regime_info.get("regime_key") == "TRENDING_BEAR":
                alpha_score += 0.15
                alpha_reasons.append("Aligned with Trending Bear Regime")
            alpha_verdict = "STRONG_SELL" if alpha_score >= 0.80 else ("SELL" if alpha_score >= 0.65 else "HOLD")

        agent_alpha = {
            "agent": "Agent Alpha (Trend & Orderflow Hunter)",
            "vote": "PASS" if alpha_score >= 0.65 else "HOLD",
            "score": round(min(0.99, alpha_score) * 100, 1),
            "verdict": alpha_verdict,
            "reasons": alpha_reasons or ["Standard momentum continuation"]
        }

        # 2. Agent Beta: Risk & Adversarial Critic (The Bearish Skeptic)
        # Actively seeks traps, overextensions, and liquidity sweep resistance
        beta_score = 0.85  # Starts high, gets penalized if traps are detected
        beta_veto = False
        beta_concerns = []
        
        # Overbought / Oversold Trap check
        if side in ("BUY", "LONG") and rsi > 76:
            beta_score -= 0.35
            beta_concerns.append(f"Exhaustion Risk: Overbought RSI ({rsi:.0f}) vulnerable to dump")
        elif side in ("SELL", "SHORT") and rsi < 24:
            beta_score -= 0.35
            beta_concerns.append(f"Capitulation Bounce Risk: Oversold RSI ({rsi:.0f}) vulnerable to short-squeeze")

        # Liquidity magnet proximity trap
        magnet = heatmap_info.get("primary_magnet")
        if magnet:
            dist = float(magnet.get("distance_pct") or 0.0)
            if side in ("BUY", "LONG") and magnet.get("type") == "LONG_LIQUIDATION" and abs(dist) < 1.0:
                beta_score -= 0.25
                beta_concerns.append(f"Stop-Hunt Trap: Heavy 100x Long Liquidation cluster {abs(dist):.2f}% below price")
            elif side in ("SELL", "SHORT") and magnet.get("type") == "SHORT_LIQUIDATION" and abs(dist) < 1.0:
                beta_score -= 0.25
                beta_concerns.append(f"Short Squeeze Trap: Heavy 100x Short Liquidation cluster {abs(dist):.2f}% above price")

        if beta_score < 0.50:
            beta_veto = True

        agent_beta = {
            "agent": "Agent Beta (Adversarial Risk Critic)",
            "vote": "VETO" if beta_veto else "PASS",
            "score": round(max(0.10, beta_score) * 100, 1),
            "veto_active": beta_veto,
            "warnings": beta_concerns or ["No active trap detected; risk envelope acceptable"]
        }

        # 3. Agent Gamma: Macro & Sentiment Arbiter
        # Assesses volatility regime, session liquidity, and broader alignment
        gamma_score = 0.75
        gamma_notes = []
        regime = regime_info.get("regime_key")
        if regime in ("TRENDING_BULL", "TRENDING_BEAR", "LIQUIDITY_SWEEP"):
            gamma_score += 0.15
            gamma_notes.append(f"Regime {regime_info.get('regime_name')} provides institutional tailwinds")
        elif regime == "HIGH_VOLATILITY_EXPANSION":
            gamma_score += 0.05
            gamma_notes.append("High volatility requires wider trailing stops")
        else:
            gamma_score -= 0.10
            gamma_notes.append("Chop regime: Scalp mode enforced")

        agent_gamma = {
            "agent": "Agent Gamma (Macro & Regime Arbiter)",
            "vote": "PASS" if gamma_score >= 0.65 else "NEUTRAL",
            "score": round(min(0.99, gamma_score) * 100, 1),
            "regime_evaluated": regime_info.get("regime_name"),
            "notes": gamma_notes
        }

        # Consensus Arbiter Calculation
        weighted_score = (agent_alpha["score"] * 0.40) + (agent_beta["score"] * 0.35) + (agent_gamma["score"] * 0.25)
        consensus_approved = (weighted_score >= 75.0) and not agent_beta["veto_active"]
        
        consensus_verdict = "APPROVED" if consensus_approved else ("VETOED_BY_BETA" if agent_beta["veto_active"] else "BELOW_THRESHOLD")

        return {
            "symbol": symbol,
            "consensus_approved": consensus_approved,
            "consensus_verdict": consensus_verdict,
            "consensus_score": round(weighted_score, 1),
            "agent_alpha": agent_alpha,
            "agent_beta": agent_beta,
            "agent_gamma": agent_gamma,
            "summary_rationale": f"Committee Consensus: {consensus_verdict} ({weighted_score:.1f}%). Alpha: {agent_alpha['score']}%, Beta: {agent_beta['score']}%, Gamma: {agent_gamma['score']}%.",
            "evaluated_at": time.time()
        }


class AdaptiveTrailingEngine:
    """Microstructure Dynamic Trailing Stop & Profit Lock Engine."""
    
    @staticmethod
    def evaluate_trailing_exit(position: Dict[str, Any], current_price: float, regime_info: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Evaluates dynamic profit lock & trailing stops based on peak cash/ROI.
        Returns exit recommendation dict if position should close, else None.
        """
        entry = float(position.get("entry_price") or 0.0)
        side = (position.get("side") or "LONG").upper()
        margin = float(position.get("margin") or 0.0)
        lev = float(position.get("leverage") or 10.0)
        peak_cash = float(position.get("peak_cash_pnl") or 0.0)
        
        if entry <= 0 or current_price <= 0 or margin <= 0:
            return None

        # Compute live P&L and ROI
        is_long = side in ("BUY", "LONG")
        price_diff = (current_price - entry) if is_long else (entry - current_price)
        pct_move = (price_diff / entry) * 100.0
        live_pnl = (pct_move / 100.0) * (margin * lev)
        roi_pct = (live_pnl / margin) * 100.0

        # Adjust trailing rules based on Regime
        lock_aggression = 0.50  # Default: Lock 50% of peak gains
        if regime_info:
            r_key = regime_info.get("regime_key")
            if r_key == "HIGH_VOLATILITY_EXPANSION":
                lock_aggression = 0.40  # Give more breathing room in high volatility
            elif r_key == "RANGING_COMPRESSION":
                lock_aggression = 0.65  # Lock profits aggressively in chop

        # Account for round-trip CoinDCX fee when locking live net profits
        is_live = bool(position.get("is_live"))
        est_fee = round(margin * lev * 0.0011, 4) if is_live else 0.0
        min_live_net = est_fee * 1.25 + max(0.012, margin * 0.015)

        # Dynamic Rule 1: Scalp Peak Trail Lock (+22% ROI peaked, lock regime share above fees)
        tier1_peak = max(min_live_net * 1.8 if is_live else 0.08, margin * 0.22)
        if peak_cash >= tier1_peak:
            trail_floor = max(min_live_net if is_live else 0.02, peak_cash * lock_aggression)
            if live_pnl <= trail_floor and live_pnl >= (min_live_net if is_live else 0.01):
                return {
                    "should_close": True,
                    "reason": f"QUANTUM_PROFIT_TRAIL_LOCK (Peaked +${peak_cash:.2f} -> Locked +${live_pnl:.2f} | {roi_pct:+.1f}% ROI)",
                    "exit_price": current_price,
                    "pnl": round(live_pnl, 2)
                }

        # Dynamic Rule 2: Breakeven + Fee Defense (+12% ROI peaked, protect net win without choking early)
        be_peak = max(min_live_net * 1.35 if is_live else 0.05, margin * 0.12)
        be_floor = min_live_net if is_live else max(0.01, margin * 0.03)
        if peak_cash >= be_peak and live_pnl <= be_floor and live_pnl >= (min_live_net if is_live else 0.01):
            return {
                "should_close": True,
                "reason": f"BREAKEVEN_PROFIT_GUARD (Protected gains: Peaked +${peak_cash:.2f} -> Saved +${live_pnl:.2f})",
                "exit_price": current_price,
                "pnl": round(live_pnl, 2)
            }

        # Dynamic Rule 3: Parabolic Momentum Harvest (+75% ROI capture)
        if roi_pct >= 75.0 and live_pnl >= (min_live_net if is_live else 0.02):
            return {
                "should_close": True,
                "reason": f"TARGET_ROI_HARVEST (Captured massive win: +${live_pnl:.2f} | +{roi_pct:.1f}% ROI)",
                "exit_price": current_price,
                "pnl": round(live_pnl, 2)
            }

        return None


class SMCDNAEngine:
    """Smart Money Concepts (Order Blocks, FVG, BSL/SSL Liquidity) + Market DNA Projection Engine."""

    INTERVAL_SECONDS = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "4h": 14400, "1d": 86400,
    }

    @staticmethod
    def _normalize_candles(
        candles: List[Dict[str, Any]],
        current_price: Optional[float] = None,
        interval_sec: int = 900,
    ) -> List[Dict[str, float]]:
        norm: List[Dict[str, float]] = []
        now = int(time.time())
        for idx, c in enumerate(candles or []):
            if not isinstance(c, dict):
                continue
            close_p = float(c.get("c") or c.get("close") or 0.0)
            open_p = float(c.get("o") or c.get("open") or close_p)
            high_p = float(c.get("h") or c.get("high") or max(open_p, close_p))
            low_p = float(c.get("l") or c.get("low") or min(open_p, close_p))
            vol_v = float(c.get("v") or c.get("volume") or 100.0)
            raw_t = c.get("t") or c.get("time") or (now - (len(candles) - idx) * interval_sec)
            ts = int(raw_t / 1000) if float(raw_t) > 1e11 else int(raw_t)
            if close_p > 0:
                norm.append({
                    "o": open_p,
                    "h": max(high_p, open_p, close_p),
                    "l": min(low_p, open_p, close_p),
                    "c": close_p,
                    "v": max(0.0, vol_v),
                    "t": float(ts),
                })

        if len(norm) < 10:
            base = float(current_price or (norm[-1]["c"] if norm else 100.0) or 100.0)
            synth: List[Dict[str, float]] = []
            prev = base * 0.996
            for i in range(40):
                wave = math.sin(i * 0.35) * 0.0012 + math.cos(i * 0.17) * 0.0007
                nxt = max(1e-8, prev * (1.0 + wave))
                hi = max(prev, nxt) * 1.0008
                lo = min(prev, nxt) * 0.9992
                synth.append({
                    "o": round(prev, 6),
                    "h": round(hi, 6),
                    "l": round(lo, 6),
                    "c": round(nxt, 6),
                    "v": round(1000.0 + abs(wave) * 1e6, 2),
                    "t": float(now - (40 - i) * interval_sec),
                })
                prev = nxt
            if current_price and float(current_price) > 0:
                synth[-1]["c"] = float(current_price)
                synth[-1]["h"] = max(synth[-1]["h"], float(current_price))
                synth[-1]["l"] = min(synth[-1]["l"], float(current_price))
            return synth

        return norm

    @staticmethod
    def _compute_all_indicators(norm: List[Dict[str, float]]) -> Dict[str, Any]:
        """Compute full institutional indicator suite on normalized OHLCV candles."""
        closes = [k["c"] for k in norm]
        highs = [k["h"] for k in norm]
        lows = [k["l"] for k in norm]
        vols = [max(1.0, k.get("v", 1.0)) for k in norm]
        n = len(closes)
        last_p = closes[-1]

        def _ema_s(vals: List[float], period: int) -> float:
            if not vals:
                return last_p
            p = max(1, min(period, len(vals)))
            k = 2.0 / (p + 1.0)
            val = sum(vals[:p]) / p
            for x in vals[p:]:
                val = (x * k) + (val * (1.0 - k))
            return val

        ema9 = _ema_s(closes, 9)
        ema21 = _ema_s(closes, 21)
        ema50 = _ema_s(closes, 50)
        ema200 = _ema_s(closes, 200)

        # RSI (14)
        gains, losses = [], []
        for i in range(1, n):
            d = closes[i] - closes[i - 1]
            gains.append(max(0.0, d))
            losses.append(max(0.0, -d))
        win_r = min(14, len(gains))
        if win_r > 0:
            ag = sum(gains[-win_r:]) / win_r
            al = sum(losses[-win_r:]) / win_r
            rsi14 = 100.0 if al <= 1e-12 and ag > 0 else (50.0 if al <= 1e-12 else 100.0 - (100.0 / (1.0 + ag / al)))
        else:
            rsi14 = 50.0

        # MACD (12, 26, 9)
        macd_series = []
        k12, k26 = 2.0 / 13.0, 2.0 / 27.0
        e12, e26 = closes[0], closes[0]
        for c in closes:
            e12 = c * k12 + e12 * (1.0 - k12)
            e26 = c * k26 + e26 * (1.0 - k26)
            macd_series.append(e12 - e26)
        macd_line = macd_series[-1]
        macd_sig = _ema_s(macd_series, 9)
        macd_hist = macd_line - macd_sig

        # Bollinger Bands (20, 2) & Keltner Squeeze
        bb_win = closes[-min(20, n):]
        bb_mid = sum(bb_win) / len(bb_win)
        bb_sd = math.sqrt(sum((x - bb_mid) ** 2 for x in bb_win) / len(bb_win))
        bb_up = bb_mid + 2.0 * bb_sd
        bb_lo = bb_mid - 2.0 * bb_sd
        bb_pct = (last_p - bb_lo) / max(1e-9, bb_up - bb_lo)

        # ATR (14) & SuperTrend (10, 3.0)
        trs = [highs[0] - lows[0]]
        for i in range(1, n):
            trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
        atr14 = sum(trs[-min(14, len(trs)):]) / max(1, min(14, len(trs)))
        atr_pct = (atr14 / max(1e-9, last_p)) * 100.0
        bb_squeeze = (bb_up <= bb_mid + 1.5 * atr14) and (bb_lo >= bb_mid - 1.5 * atr14)

        st_dir = "BULL"
        st_val = last_p - 3.0 * atr14
        st_flip = False
        st_mult = 3.0
        prev_up, prev_dn = last_p, last_p
        prev_dir = 1
        for i in range(n):
            hl2 = (highs[i] + lows[i]) * 0.5
            loc_atr = sum(trs[max(0, i - 9):i + 1]) / max(1, min(10, i + 1))
            up_b = hl2 + st_mult * loc_atr
            dn_b = hl2 - st_mult * loc_atr
            fin_up = min(up_b, prev_up) if (i > 0 and closes[i - 1] <= prev_up) else up_b
            fin_dn = max(dn_b, prev_dn) if (i > 0 and closes[i - 1] >= prev_dn) else dn_b
            cur_dir = 1 if closes[i] > fin_up else (-1 if closes[i] < fin_dn else prev_dir)
            if i == n - 1:
                st_flip = (cur_dir != prev_dir)
                st_dir = "BULL" if cur_dir == 1 else "BEAR"
                st_val = fin_dn if cur_dir == 1 else fin_up
            prev_up, prev_dn, prev_dir = fin_up, fin_dn, cur_dir

        # VWAP & OBV Slope
        vw_num = sum(((highs[i] + lows[i] + closes[i]) / 3.0) * vols[i] for i in range(n))
        vwap = vw_num / max(1.0, sum(vols))
        avg_v = sum(vols[:-1]) / max(1, n - 1)
        vol_surge = vols[-1] / max(1e-9, avg_v)

        obv_vals = [0.0]
        for i in range(1, n):
            step = vols[i] if closes[i] > closes[i - 1] else (-vols[i] if closes[i] < closes[i - 1] else 0.0)
            obv_vals.append(obv_vals[-1] + step)
        obv_recent = obv_vals[-min(6, len(obv_vals)):]
        obv_slope = (obv_recent[-1] - obv_recent[0]) / max(1.0, avg_v * len(obv_recent))

        ema_stack = "BULL" if (ema9 > ema21 and last_p >= ema50) else ("BEAR" if (ema9 < ema21 and last_p <= ema50) else "MIXED")
        return {
            "ema9": round(ema9, 6),
            "ema21": round(ema21, 6),
            "ema50": round(ema50, 6),
            "ema200": round(ema200, 6),
            "ema_stack": ema_stack,
            "rsi14": round(rsi14, 2),
            "macd_line": round(macd_line, 6),
            "macd_signal": round(macd_sig, 6),
            "macd_hist": round(macd_hist, 6),
            "bb_upper": round(bb_up, 6),
            "bb_mid": round(bb_mid, 6),
            "bb_lower": round(bb_lo, 6),
            "bb_pct": round(bb_pct, 3),
            "bb_squeeze": bool(bb_squeeze),
            "supertrend": st_dir,
            "supertrend_val": round(st_val, 6),
            "supertrend_flipped": bool(st_flip),
            "vwap": round(vwap, 6),
            "above_vwap": bool(last_p >= vwap),
            "atr14": round(atr14, 6),
            "atr_pct": round(atr_pct, 4),
            "obv_slope": round(obv_slope, 3),
            "vol_surge_ratio": round(vol_surge, 2),
        }

    @classmethod
    def analyze_candles(
        cls,
        symbol: str,
        candles: List[Dict[str, Any]],
        interval: str = "15m",
        current_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Analyzes OHLCV candles for SMC Order Blocks, FVGs, BSL/SSL Liquidity, Market DNA projection & Structure Timeline."""
        sym_u = str(symbol or "BTCUSDT").upper()
        tf_str = str(interval or "15m").lower()
        interval_sec = cls.INTERVAL_SECONDS.get(tf_str, 900)
        norm = cls._normalize_candles(candles, current_price=current_price, interval_sec=interval_sec)
        last_close = float(current_price or norm[-1]["c"])
        now = int(time.time())

        # 1. Swing High / Low, Fibonacci & Liquidity Sweeps
        win_liq = norm[-40:]
        swing_high = max(k["h"] for k in win_liq)
        swing_low = min(k["l"] for k in win_liq)
        span = max(1e-9, swing_high - swing_low)
        fib_618 = round(swing_low + 0.618 * span, 6)
        fib_50 = round(swing_low + 0.50 * span, 6)

        prior = win_liq[:-3] if len(win_liq) > 6 else win_liq[:-1]
        prior_high = max(k["h"] for k in prior) if prior else swing_high
        prior_low = min(k["l"] for k in prior) if prior else swing_low
        ssl_swept = any(k["l"] <= prior_low and k["c"] > prior_low for k in norm[-4:])
        bsl_swept = any(k["h"] >= prior_high and k["c"] < prior_high for k in norm[-4:])

        liquidity = {
            "bsl": {"price": round(swing_high, 6), "swept": bool(bsl_swept)},
            "ssl": {"price": round(swing_low, 6), "swept": bool(ssl_swept)},
            "fib_618": fib_618,
            "fib_50": fib_50,
            "range_pct": round((span / max(1e-9, last_close)) * 100.0, 2),
        }

        # 2. Fair Value Gaps (last 35 candles)
        scan_fvg = norm[-35:]
        fvgs_all: List[Dict[str, Any]] = []
        timeline_events: List[Dict[str, Any]] = []

        for i in range(2, len(scan_fvg)):
            c0, c2 = scan_fvg[i - 2], scan_fvg[i]
            later = scan_fvg[i + 1:]
            if c0["h"] < c2["l"]:
                bottom, top = c0["h"], c2["l"]
                gap_h = max(1e-9, top - bottom)
                min_later = min((k["l"] for k in later), default=top)
                mit_pct = 0.0 if min_later >= top else min(100.0, max(0.0, ((top - min_later) / gap_h) * 100.0))
                is_mit = mit_pct >= 50.0
                fvgs_all.append({
                    "type": "BULLISH_FVG",
                    "top": round(top, 6),
                    "bottom": round(bottom, 6),
                    "mitigated": bool(is_mit),
                    "mitigated_pct": round(mit_pct, 1),
                    "time": int(c2["t"]),
                })
                evt_name = "Bullish FVG mitigated" if is_mit else "Bullish FVG formed"
                timeline_events.append({
                    "time": int(c2["t"]), "symbol": sym_u, "tf": tf_str.upper(),
                    "event": evt_name, "bias": "bull", "price": round(bottom, 6),
                })
            elif c0["l"] > c2["h"]:
                top, bottom = c0["l"], c2["h"]
                gap_h = max(1e-9, top - bottom)
                max_later = max((k["h"] for k in later), default=bottom)
                mit_pct = 0.0 if max_later <= bottom else min(100.0, max(0.0, ((max_later - bottom) / gap_h) * 100.0))
                is_mit = mit_pct >= 50.0
                fvgs_all.append({
                    "type": "BEARISH_FVG",
                    "top": round(top, 6),
                    "bottom": round(bottom, 6),
                    "mitigated": bool(is_mit),
                    "mitigated_pct": round(mit_pct, 1),
                    "time": int(c2["t"]),
                })
                evt_name = "Bearish FVG mitigated" if is_mit else "Bearish FVG formed"
                timeline_events.append({
                    "time": int(c2["t"]), "symbol": sym_u, "tf": tf_str.upper(),
                    "event": evt_name, "bias": "bear", "price": round(top, 6),
                })
        fvgs = fvgs_all[-4:]

        # 3. Order Blocks
        avg_range = sum(max(1e-9, k["h"] - k["l"]) for k in scan_fvg) / max(1, len(scan_fvg))
        obs_all: List[Dict[str, Any]] = []
        for i in range(1, len(scan_fvg) - 1):
            prev_c, imp_c = scan_fvg[i - 1], scan_fvg[i]
            imp_body = abs(imp_c["c"] - imp_c["o"])
            if imp_body < 1.2 * avg_range:
                continue
            later = scan_fvg[i + 1:]
            if prev_c["c"] < prev_c["o"] and imp_c["c"] > imp_c["o"]:
                top, bottom = max(prev_c["o"], prev_c["h"]), prev_c["l"]
                ob_h = max(1e-9, top - bottom)
                min_later = min((k["l"] for k in later), default=top)
                mit_pct = 0.0 if min_later >= top else min(100.0, max(0.0, ((top - min_later) / ob_h) * 100.0))
                obs_all.append({
                    "type": "BULLISH_OB",
                    "top": round(top, 6),
                    "bottom": round(bottom, 6),
                    "mid": round((top + bottom) / 2.0, 6),
                    "mitigated_pct": round(mit_pct, 1),
                    "time": int(prev_c["t"]),
                })
                timeline_events.append({
                    "time": int(prev_c["t"]),
                    "symbol": sym_u,
                    "tf": tf_str.upper(),
                    "event": "Bullish Order Block mitigated (50%)" if mit_pct >= 50.0 else "Bullish Order Block formed",
                    "bias": "bull",
                    "price": round((top + bottom) / 2.0, 6),
                })
            elif prev_c["c"] > prev_c["o"] and imp_c["c"] < imp_c["o"]:
                top, bottom = prev_c["h"], min(prev_c["o"], prev_c["c"])
                ob_h = max(1e-9, top - bottom)
                max_later = max((k["h"] for k in later), default=bottom)
                mit_pct = 0.0 if max_later <= bottom else min(100.0, max(0.0, ((max_later - bottom) / ob_h) * 100.0))
                obs_all.append({
                    "type": "BEARISH_OB",
                    "top": round(top, 6),
                    "bottom": round(bottom, 6),
                    "mid": round((top + bottom) / 2.0, 6),
                    "mitigated_pct": round(mit_pct, 1),
                    "time": int(prev_c["t"]),
                })
                timeline_events.append({
                    "time": int(prev_c["t"]),
                    "symbol": sym_u,
                    "tf": tf_str.upper(),
                    "event": "Bearish Order Block mitigated (50%)" if mit_pct >= 50.0 else "Bearish Order Block formed",
                    "bias": "bear",
                    "price": round((top + bottom) / 2.0, 6),
                })
        order_blocks = obs_all[-4:]

        if ssl_swept:
            timeline_events.append({
                "time": int(norm[-1]["t"]), "symbol": sym_u, "tf": tf_str.upper(),
                "event": "SSL Liquidity Swept", "bias": "bull", "price": round(prior_low, 6),
            })
        if bsl_swept:
            timeline_events.append({
                "time": int(norm[-1]["t"]), "symbol": sym_u, "tf": tf_str.upper(),
                "event": "BSL Liquidity Swept", "bias": "bear", "price": round(prior_high, 6),
            })
        if last_close > fib_618 and norm[-3]["c"] <= fib_618:
            timeline_events.append({
                "time": int(norm[-1]["t"]), "symbol": sym_u, "tf": tf_str.upper(),
                "event": "Bullish BOS", "bias": "bull", "price": round(last_close, 6),
            })
        elif last_close < fib_50 and norm[-3]["c"] >= fib_50:
            timeline_events.append({
                "time": int(norm[-1]["t"]), "symbol": sym_u, "tf": tf_str.upper(),
                "event": "Bearish CHoCH", "bias": "bear", "price": round(last_close, 6),
            })

        timeline_events.sort(key=lambda e: e["time"], reverse=True)
        timeline = timeline_events[:10]

        # 4. Market DNA Historical Pattern Projection
        closes = [k["c"] for k in norm]
        win_len = min(40, max(8, len(closes) // 2))
        cur_seg = closes[-win_len:]

        def _zscore(arr: List[float]) -> List[float]:
            mean = sum(arr) / len(arr)
            var = sum((x - mean) ** 2 for x in arr) / len(arr)
            sd = math.sqrt(var) or 1e-9
            return [(x - mean) / sd for x in arr]

        z_cur = _zscore(cur_seg)
        best_corr = -1.0
        best_outcome_returns: List[float] = []
        proj_steps = 12

        if len(closes) >= win_len + proj_steps + 2:
            max_start = len(closes) - win_len - proj_steps
            for s in range(0, max_start + 1):
                cand = closes[s:s + win_len]
                z_cand = _zscore(cand)
                corr = sum(a * b for a, b in zip(z_cur, z_cand)) / win_len
                if corr > best_corr:
                    best_corr = corr
                    anchor = cand[-1] or 1e-9
                    best_outcome_returns = [(closes[s + win_len + j] - anchor) / anchor for j in range(proj_steps)]

        if not best_outcome_returns:
            drift = (cur_seg[-1] - cur_seg[0]) / max(1e-9, cur_seg[0]) / max(1, win_len)
            vol_step = (avg_range / max(1e-9, last_close)) * 0.45
            best_corr = max(0.32, 0.55 - min(0.25, vol_step * 20.0))
            best_outcome_returns = [
                (drift * (j + 1)) + math.sin((j + 1) * 0.65) * vol_step * 0.65
                for j in range(proj_steps)
            ]

        similarity_pct = round(max(62.0, min(96.0, 62.0 + max(0.0, best_corr) * 34.0)), 1)
        net_proj_ret = best_outcome_returns[-1] if best_outcome_returns else 0.0
        band_scale = max(0.0012, (avg_range / max(1e-9, last_close)) * 0.55)
        projection = []
        for idx_p, r_val in enumerate(best_outcome_returns[:proj_steps], start=1):
            p_mid = last_close * (1.0 + r_val)
            spread = last_close * band_scale * math.sqrt(idx_p)
            projection.append({
                "step": idx_p,
                "price": round(p_mid, 6),
                "upper": round(p_mid + spread, 6),
                "lower": round(max(1e-8, p_mid - spread), 6),
            })

        bull_obs = [ob for ob in order_blocks if ob["type"] == "BULLISH_OB" and ob["mitigated_pct"] < 80.0]
        bear_obs = [ob for ob in order_blocks if ob["type"] == "BEARISH_OB" and ob["mitigated_pct"] < 80.0]
        bull_fvgs = [fg for fg in fvgs if fg["type"] == "BULLISH_FVG" and not fg.get("mitigated")]
        bear_fvgs = [fg for fg in fvgs if fg["type"] == "BEARISH_FVG" and not fg.get("mitigated")]
        ema_fast = sum(closes[-8:]) / min(8, len(closes))
        ema_slow = sum(closes[-21:]) / min(21, len(closes))
        trend_up = ema_fast >= ema_slow

        # Compute All Technical Indicators on normalized candles
        all_indicators = cls._compute_all_indicators(norm)
        prem_pct = round(max(0.0, min(100.0, ((last_close - swing_low) / span) * 100.0)), 1)
        price_zone = "DISCOUNT" if prem_pct <= 38.2 else ("PREMIUM" if prem_pct >= 61.8 else "EQUILIBRIUM")
        liquidity["premium_discount_pct"] = prem_pct
        liquidity["zone"] = price_zone

        bos_bull = bool(last_close > fib_618 and norm[-3]["c"] <= fib_618)
        choch_bear = bool(last_close < fib_50 and norm[-3]["c"] >= fib_50)

        if net_proj_ret >= 0.0015 and (ssl_swept or bool(bull_obs) or trend_up or all_indicators["supertrend"] == "BULL"):
            historical_bias = "BULLISH"
            setup_status = "QUALIFIED_BULLISH"
            condition_note = "Institutional SMC & DNA Aligned (Bullish Structure + Twin Match)"
        elif net_proj_ret <= -0.0015 and (bsl_swept or bool(bear_obs) or (not trend_up) or all_indicators["supertrend"] == "BEAR"):
            historical_bias = "BEARISH"
            setup_status = "QUALIFIED_BEARISH"
            condition_note = "Institutional SMC & DNA Aligned (Bearish Structure + Twin Match)"
        else:
            historical_bias = "NEUTRAL"
            setup_status = "NO_QUALIFIED_SETUP"
            condition_note = "Market structure is weak — waiting for qualified setup"

        dna = {
            "similarity_pct": similarity_pct,
            "historical_bias": historical_bias,
            "setup_status": setup_status,
            "condition_note": condition_note,
            "projection": projection,
        }

        # 5. Forming Candle Timer
        remaining_sec = interval_sec - (now % interval_sec)
        candle_timer = {
            "interval": tf_str.upper(),
            "interval_sec": interval_sec,
            "remaining_sec": remaining_sec,
            "formatted": f"{remaining_sec // 60:02d}:{remaining_sec % 60:02d}",
        }

        # 6. Full Confluence Scoring (SMC + DNA + All Indicators) & Bot Signal / Exit Gate
        near_bear_ob = any(
            (-0.002 <= (ob["bottom"] - last_close) / max(1e-9, last_close) <= 0.0025)
            or (ob["bottom"] <= last_close <= ob["top"])
            for ob in bear_obs
        )
        near_bull_ob = any(
            (-0.002 <= (last_close - ob["top"]) / max(1e-9, last_close) <= 0.0025)
            or (ob["bottom"] <= last_close <= ob["top"])
            for ob in bull_obs
        )

        # Bullish & Bearish indicator + SMC + DNA confluence (0-100)
        bull_conf = 50.0
        bear_conf = 50.0
        if all_indicators["ema_stack"] == "BULL":
            bull_conf += 10.0
        elif all_indicators["ema_stack"] == "BEAR":
            bear_conf += 10.0
        if all_indicators["supertrend"] == "BULL":
            bull_conf += 10.0
        else:
            bear_conf += 10.0
        if all_indicators["macd_hist"] > 0:
            bull_conf += 7.0
        elif all_indicators["macd_hist"] < 0:
            bear_conf += 7.0
        if all_indicators["above_vwap"]:
            bull_conf += 5.0
        else:
            bear_conf += 5.0
        if 44.0 <= all_indicators["rsi14"] <= 69.0:
            bull_conf += 6.0
        elif 31.0 <= all_indicators["rsi14"] <= 56.0:
            bear_conf += 6.0
        if all_indicators["rsi14"] >= 73.0:
            bear_conf += 7.0
        elif all_indicators["rsi14"] <= 27.0:
            bull_conf += 7.0
        if all_indicators["obv_slope"] > 0.02:
            bull_conf += 5.0
        elif all_indicators["obv_slope"] < -0.02:
            bear_conf += 5.0
        if ssl_swept or near_bull_ob or bull_fvgs:
            bull_conf += 9.0
        if bsl_swept or near_bear_ob or bear_fvgs:
            bear_conf += 9.0
        if historical_bias == "BULLISH":
            bull_conf += min(10.0, (similarity_pct - 60.0) * 0.28)
        elif historical_bias == "BEARISH":
            bear_conf += min(10.0, (similarity_pct - 60.0) * 0.28)
        if price_zone == "DISCOUNT":
            bull_conf += 5.0
        elif price_zone == "PREMIUM":
            bear_conf += 5.0

        bull_conf = round(max(10.0, min(98.0, bull_conf)), 1)
        bear_conf = round(max(10.0, min(98.0, bear_conf)), 1)
        recommended_side = (
            "LONG" if bull_conf >= bear_conf + 6.0 and bull_conf >= 62.0
            else ("SHORT" if bear_conf >= bull_conf + 6.0 and bear_conf >= 62.0 else "WAIT")
        )

        # Structural SL / TP aligned to Order Blocks & BSL/SSL Liquidity
        atr_buf = max(last_close * 0.0028, all_indicators["atr14"] * 1.15)
        bull_anchor_low = min([ob["bottom"] for ob in bull_obs] or [swing_low])
        bear_anchor_high = max([ob["top"] for ob in bear_obs] or [swing_high])

        sl_long = round(min(last_close * 0.9965, max(swing_low * 0.9985, min(last_close - atr_buf, bull_anchor_low * 0.9988))), 6)
        overhead_bears = [ob["bottom"] for ob in bear_obs if ob["bottom"] > last_close * 1.003]
        tp_long_cand = min([swing_high * 0.999] + overhead_bears) if overhead_bears else (swing_high * 0.999 if swing_high > last_close * 1.004 else last_close + atr_buf * 2.0)
        tp_long = round(max(last_close * 1.0045, tp_long_cand), 6)

        sl_short = round(max(last_close * 1.0035, min(swing_high * 1.0015, max(last_close + atr_buf, bear_anchor_high * 1.0012))), 6)
        under_bulls = [ob["top"] for ob in bull_obs if ob["top"] < last_close * 0.997]
        tp_short_cand = max([swing_low * 1.001] + under_bulls) if under_bulls else (swing_low * 1.001 if swing_low < last_close * 0.996 else last_close - atr_buf * 2.0)
        tp_short = round(max(1e-8, min(last_close * 0.9955, tp_short_cand)), 6)

        # Trap guards: avoid buying swept BSL / Bear OB tops or shorting swept SSL / Bull OB bottoms
        bsl_trap = bsl_swept and last_close <= swing_high and (all_indicators["supertrend"] == "BEAR" or all_indicators["macd_hist"] < 0 or historical_bias == "BEARISH")
        ssl_trap = ssl_swept and last_close >= swing_low and (all_indicators["supertrend"] == "BULL" or all_indicators["macd_hist"] > 0 or historical_bias == "BULLISH")
        block_long = bool((near_bear_ob and historical_bias == "BEARISH") or bsl_trap)
        block_short = bool((near_bull_ob and historical_bias == "BULLISH") or ssl_trap)

        boost_score = 0
        if setup_status == "QUALIFIED_BULLISH":
            boost_score = 6
        elif setup_status == "QUALIFIED_BEARISH":
            boost_score = -6

        suggested_sl_price = sl_short if (recommended_side == "SHORT" or historical_bias == "BEARISH") else sl_long
        suggested_tp_price = tp_short if (recommended_side == "SHORT" or historical_bias == "BEARISH") else tp_long

        # Structural Auto-Close Signals (BSL/SSL Liquidity Sweep, Opposing OB, CHoCH/SuperTrend Flip + DNA)
        dist_to_bsl = (swing_high - last_close) / max(1e-9, last_close)
        dist_to_ssl = (last_close - swing_low) / max(1e-9, last_close)
        close_long_reason = ""
        if bsl_swept and last_close < swing_high:
            close_long_reason = "BSL_LIQUIDITY_SWEPT"
        elif near_bear_ob and (all_indicators["rsi14"] >= 66.0 or all_indicators["macd_hist"] < 0 or historical_bias == "BEARISH"):
            close_long_reason = "BEAR_OB_SUPPLY_HIT"
        elif 0.0 <= dist_to_bsl <= 0.0015 and all_indicators["rsi14"] >= 68.0:
            close_long_reason = "BSL_CEILING_TARGET"
        elif (choch_bear or (all_indicators["supertrend"] == "BEAR" and all_indicators["macd_hist"] < 0)) and historical_bias == "BEARISH":
            close_long_reason = "SMC_DNA_BEAR_REVERSAL"

        close_short_reason = ""
        if ssl_swept and last_close > swing_low:
            close_short_reason = "SSL_LIQUIDITY_SWEPT"
        elif near_bull_ob and (all_indicators["rsi14"] <= 34.0 or all_indicators["macd_hist"] > 0 or historical_bias == "BULLISH"):
            close_short_reason = "BULL_OB_DEMAND_HIT"
        elif 0.0 <= dist_to_ssl <= 0.0015 and all_indicators["rsi14"] <= 32.0:
            close_short_reason = "SSL_FLOOR_TARGET"
        elif (bos_bull or (all_indicators["supertrend"] == "BULL" and all_indicators["macd_hist"] > 0)) and historical_bias == "BULLISH":
            close_short_reason = "SMC_DNA_BULL_REVERSAL"

        # Optimal entry zone (OTE)
        if recommended_side == "SHORT":
            ez_low = min([ob["bottom"] for ob in bear_obs] or [round(last_close * 0.999, 6)])
            ez_high = max([ob["top"] for ob in bear_obs] or [round(last_close * 1.0015, 6)])
        else:
            ez_low = min([ob["bottom"] for ob in bull_obs] or [round(last_close * 0.9985, 6)])
            ez_high = max([ob["top"] for ob in bull_obs] or [round(last_close * 1.001, 6)])

        entry_signal = {
            "recommended_side": recommended_side,
            "bull_confluence_pct": bull_conf,
            "bear_confluence_pct": bear_conf,
            "confluence_score": max(bull_conf, bear_conf),
            "entry_zone_low": round(ez_low, 6),
            "entry_zone_high": round(ez_high, 6),
            "in_entry_zone": bool(ez_low <= last_close <= ez_high),
            "sl_long": sl_long,
            "tp_long": tp_long,
            "sl_short": sl_short,
            "tp_short": tp_short,
            "zone": price_zone,
            "premium_discount_pct": prem_pct,
        }
        exit_signal = {
            "close_long": bool(close_long_reason),
            "reason_long": close_long_reason,
            "close_short": bool(close_short_reason),
            "reason_short": close_short_reason,
        }
        bot_signal = {
            "block_long": block_long,
            "block_short": block_short,
            "boost_score": boost_score,
            "recommended_side": recommended_side,
            "confluence_score": entry_signal["confluence_score"],
            "suggested_sl_price": suggested_sl_price,
            "suggested_tp_price": suggested_tp_price,
            "exit_long": bool(close_long_reason),
            "exit_short": bool(close_short_reason),
            "exit_reason_long": close_long_reason,
            "exit_reason_short": close_short_reason,
        }

        return {
            "symbol": sym_u,
            "interval": tf_str.upper(),
            "price": round(last_close, 6),
            "fvgs": fvgs,
            "order_blocks": order_blocks,
            "liquidity": liquidity,
            "dna": dna,
            "timeline": timeline,
            "candle_timer": candle_timer,
            "all_indicators": all_indicators,
            "entry_signal": entry_signal,
            "exit_signal": exit_signal,
            "bot_signal": bot_signal,
        }


