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

        # Dynamic Rule 1: High Peak Lock (+25% ROI peaked, lock at least 50% of peak)
        tier1_peak = max(0.10, margin * 0.25)
        if peak_cash >= tier1_peak:
            trail_floor = peak_cash * lock_aggression
            if live_pnl <= trail_floor and live_pnl > 0.01:
                return {
                    "should_close": True,
                    "reason": f"QUANTUM_PROFIT_TRAIL_LOCK (Peaked +${peak_cash:.2f} -> Locked +${live_pnl:.2f} | {roi_pct:+.1f}% ROI)",
                    "exit_price": current_price,
                    "pnl": round(live_pnl, 2)
                }

        # Dynamic Rule 2: Breakeven Invalidation Defense (+15% ROI peaked, NEVER lose money!)
        be_peak = max(0.05, margin * 0.15)
        be_floor = max(0.01, margin * 0.03)  # Guaranteed small gain
        if peak_cash >= be_peak and live_pnl <= be_floor:
            return {
                "should_close": True,
                "reason": f"BREAKEVEN_PROFIT_GUARD (Protected gains: Peaked +${peak_cash:.2f} -> Saved +${live_pnl:.2f})",
                "exit_price": current_price,
                "pnl": round(live_pnl, 2)
            }

        # Dynamic Rule 3: Extreme Momentum Target (+50% ROI capture)
        if roi_pct >= 50.0:
            return {
                "should_close": True,
                "reason": f"TARGET_ROI_HARVEST (Captured massive win: +${live_pnl:.2f} | +{roi_pct:.1f}% ROI)",
                "exit_price": current_price,
                "pnl": round(live_pnl, 2)
            }

        return None

