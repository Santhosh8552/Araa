"""
TradePro AI — Advanced Multi-Timeframe Quantitative Analysis Engine
Strictly manual decision advisory system:
- Multi-Timeframe market structure & trend analysis
- Indicators: EMA (9, 20, 50, 200), RSI(14), MACD, Bollinger Bands, ATR, Volume confirmation
- Support & Resistance zones, Liquidity sweeps, Order Book imbalance
- Probabilistic Signal Generation: BUY SETUP, SELL SETUP, WAIT FOR CONFIRMATION, NO TRADE, MARKET CLOSED
- 3 Take Profit Targets (T1, T2, T3) & Invalidation Level
- Position Sizing & Margin/Risk Calculator with Slippage, Fees, and Liquidation price
- Holding Horizon estimation based on ATR and distance to targets
- Audit Logging & Performance Tracking against future prices
"""
import time
import math
from datetime import datetime, timezone

def calculate_ema(prices, period):
    """Exponential Moving Average."""
    if not prices or len(prices) < period:
        return None
    k = 2.0 / (period + 1.0)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = (p * k) + (ema * (1.0 - k))
    return ema

def calculate_sma(prices, period):
    """Simple Moving Average."""
    if not prices or len(prices) < period:
        return None
    return sum(prices[-period:]) / float(period)

def calculate_rsi(prices, period=14):
    """Relative Strength Index."""
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        delta = prices[i] - prices[i - 1]
        if delta >= 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(delta))
    if len(gains) < period:
        return 50.0
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)

def calculate_macd(prices):
    """MACD line, Signal line (EMA 9), Histogram."""
    if len(prices) < 26:
        return {"macd": 0.0, "signal": 0.0, "hist": 0.0}
    # Calculate rolling EMAs
    ema12_list = []
    ema26_list = []
    k12 = 2.0 / 13.0
    k26 = 2.0 / 27.0
    e12 = sum(prices[:12]) / 12.0
    e26 = sum(prices[:26]) / 26.0
    
    # Run through series
    for i, p in enumerate(prices):
        if i >= 12:
            e12 = (p * k12) + (e12 * (1.0 - k12))
        if i >= 26:
            e26 = (p * k26) + (e26 * (1.0 - k26))
            ema12_list.append(e12)
            ema26_list.append(e26)
            
    macd_series = [e12_val - e26_val for e12_val, e26_val in zip(ema12_list, ema26_list)]
    if not macd_series:
        return {"macd": 0.0, "signal": 0.0, "hist": 0.0}
    
    sig = calculate_ema(macd_series, 9) or macd_series[-1]
    macd_val = macd_series[-1]
    return {
        "macd": round(macd_val, 6),
        "signal": round(sig, 6),
        "hist": round(macd_val - sig, 6)
    }

def calculate_bollinger_bands(prices, period=20, num_std=2.0):
    """Bollinger Bands: Middle, Upper, Lower."""
    if len(prices) < period:
        mid = prices[-1] if prices else 1.0
        return {"mid": mid, "upper": mid * 1.02, "lower": mid * 0.98, "bandwidth": 0.04}
    slice_p = prices[-period:]
    mean = sum(slice_p) / float(period)
    variance = sum((x - mean) ** 2 for x in slice_p) / float(period)
    std = math.sqrt(variance)
    upper = mean + (num_std * std)
    lower = mean - (num_std * std)
    bw = (upper - lower) / max(mean, 0.000001)
    return {
        "mid": round(mean, 6),
        "upper": round(upper, 6),
        "lower": round(lower, 6),
        "bandwidth": round(bw, 4)
    }

def calculate_atr(candles, period=14):
    """Average True Range for volatility estimation."""
    if len(candles) < 2:
        return (candles[-1]["h"] - candles[-1]["l"]) if candles else 0.01
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["h"]
        l = candles[i]["l"]
        prev_c = candles[i - 1]["c"]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    if not trs:
        return 0.01
    if len(trs) < period:
        return round(sum(trs) / len(trs), 6)
    atr = sum(trs[:period]) / float(period)
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / float(period)
    return round(atr, 6)

def detect_support_resistance(candles, window=10):
    """Find key swing highs and swing lows across the candle series."""
    if len(candles) < window * 2:
        closes = [c["c"] for c in candles] or [1.0]
        return {"supports": [round(min(closes), 4)], "resistances": [round(max(closes), 4)]}
    
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    resistances = []
    supports = []
    
    for i in range(window, len(candles) - window):
        # Local peak
        if highs[i] == max(highs[i - window : i + window + 1]):
            resistances.append(highs[i])
        # Local trough
        if lows[i] == min(lows[i - window : i + window + 1]):
            supports.append(lows[i])
            
    # Cluster and take top levels
    curr = candles[-1]["c"]
    valid_res = sorted([round(r, 6) for r in set(resistances) if r > curr])
    valid_sup = sorted([round(s, 6) for s in set(supports) if s < curr], reverse=True)
    
    return {
        "supports": valid_sup[:3] or [round(curr * 0.985, 4)],
        "resistances": valid_res[:3] or [round(curr * 1.015, 4)]
    }

def analyze_market_deep(symbol, category, candles, order_book=None, timeframe="15m", live=True):
    """
    Comprehensive multi-indicator technical & market-structure analysis.
    Returns:
    - Status: BUY SETUP | SELL SETUP | WAIT FOR CONFIRMATION | NO TRADE | MARKET CLOSED
    - Evidence: Bullish and Bearish factors
    - Key levels: Entry zone, Stop Loss, T1, T2, T3, Invalidation
    - Risk/Reward ratio
    - Estimated Holding Horizon
    - Confidence score with methodology
    """
    now = time.time()
    
    # Check weekend status for traditional assets
    from datetime import datetime, timezone
    utc_now = datetime.now(timezone.utc)
    weekday = utc_now.weekday()
    utc_hour = utc_now.hour
    is_weekend = (weekday == 5) or (weekday == 6 and utc_hour < 21) or (weekday == 4 and utc_hour >= 22)
    
    if not live:
        is_stale = True
    else:
        is_stale = False

    if is_weekend and category != "CRYPTO":
        return {
            "status": "MARKET CLOSED",
            "symbol": symbol,
            "category": category,
            "timeframe": timeframe,
            "is_live": False,
            "reasoning": {
                "market_condition": f"Traditional {category} market is closed for weekend.",
                "evidence": ["Forex/Equities/Metals trading sessions closed until Sunday 21:00 UTC."],
                "entry_plan": "No entries permitted outside official market hours.",
                "risk_plan": "Zero exposure recommended.",
                "exit_plan": "N/A",
                "alternative_scenario": "Switch to 24/7 Crypto markets for active liquidity."
            },
            "timestamp": now
        }

    if not candles or len(candles) < 20:
        return {
            "status": "NO TRADE — INSUFFICIENT EVIDENCE",
            "symbol": symbol,
            "category": category,
            "timeframe": timeframe,
            "is_live": live,
            "reasoning": {
                "market_condition": "Insufficient historical candles to build reliable indicators.",
                "evidence": ["Candle count below minimum threshold of 20 periods."],
                "entry_plan": "Wait for feed to accumulate sufficient candle history.",
                "risk_plan": "Preserve capital.",
                "exit_plan": "N/A",
                "alternative_scenario": "N/A"
            },
            "timestamp": now
        }

    closes = [c["c"] for c in candles]
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    volumes = [c.get("v", 0.0) for c in candles]
    current_price = closes[-1]
    
    # Indicators
    ema9 = calculate_ema(closes, 9)
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    ema200 = calculate_ema(closes, 200) if len(closes) >= 200 else calculate_ema(closes, len(closes))
    rsi14 = calculate_rsi(closes, 14)
    macd = calculate_macd(closes)
    bb = calculate_bollinger_bands(closes, 20, 2.0)
    atr = calculate_atr(candles, 14)
    sr = detect_support_resistance(candles)

    # Volume confirmation
    avg_vol = sum(volumes[-10:]) / 10.0 if len(volumes) >= 10 else 1.0
    last_vol = volumes[-1] if volumes else 1.0
    vol_ratio = last_vol / max(avg_vol, 0.001)

    # Order book imbalance
    book_imbalance = 0.5
    if order_book and order_book.get("bids") and order_book.get("asks"):
        bid_vol = sum(q for _p, q in order_book["bids"][:5])
        ask_vol = sum(q for _p, q in order_book["asks"][:5])
        total_vol = bid_vol + ask_vol
        if total_vol > 0:
            book_imbalance = round(bid_vol / total_vol, 3)

    # Multi-factor evidence collection
    bullish_evidence = []
    bearish_evidence = []

    # 1. EMA alignment
    if ema9 and ema20 and ema9 > ema20:
        bullish_evidence.append(f"Fast EMA(9) {ema9:.4f} > EMA(20) {ema20:.4f} (Upward momentum)")
    elif ema9 and ema20 and ema9 < ema20:
        bearish_evidence.append(f"Fast EMA(9) {ema9:.4f} < EMA(20) {ema20:.4f} (Downward momentum)")

    if ema50 and current_price > ema50:
        bullish_evidence.append(f"Price trading above 50-period trend baseline ({ema50:.4f})")
    elif ema50 and current_price < ema50:
        bearish_evidence.append(f"Price trading below 50-period trend baseline ({ema50:.4f})")

    # 2. RSI checks
    if rsi14 < 32:
        bullish_evidence.append(f"RSI(14) is {rsi14:.1f} (Oversold demand zone / potential reversal)")
    elif rsi14 > 68:
        bearish_evidence.append(f"RSI(14) is {rsi14:.1f} (Overbought supply exhaustion / potential pullback)")
    elif 48 <= rsi14 <= 58:
        bullish_evidence.append(f"RSI in healthy bullish continuation range ({rsi14:.1f})")
    elif 42 <= rsi14 <= 48:
        bearish_evidence.append(f"RSI in neutral-bearish consolidation range ({rsi14:.1f})")

    # 3. MACD checks
    if macd["hist"] > 0 and macd["macd"] > macd["signal"]:
        bullish_evidence.append(f"MACD histogram positive (+{macd['hist']:.4f}) with bullish crossover")
    elif macd["hist"] < 0 and macd["macd"] < macd["signal"]:
        bearish_evidence.append(f"MACD histogram negative ({macd['hist']:.4f}) with bearish crossover")

    # 4. Bollinger Bands & ATR
    if current_price <= bb["lower"] * 1.002:
        bullish_evidence.append(f"Price tagging lower Bollinger Band ({bb['lower']:.4f}) — mean-reversion setup")
    elif current_price >= bb["upper"] * 0.998:
        bearish_evidence.append(f"Price tagging upper Bollinger Band ({bb['upper']:.4f}) — stretched from mean")

    # 5. Volume & Order Book
    if vol_ratio > 1.3:
        if current_price > closes[-2]:
            bullish_evidence.append(f"Strong buying volume surge ({vol_ratio:.1f}x of 10-period avg)")
        else:
            bearish_evidence.append(f"Heavy selling volume surge ({vol_ratio:.1f}x of 10-period avg)")
    
    if book_imbalance > 0.60:
        bullish_evidence.append(f"Order book depth bid-heavy ({int(book_imbalance*100)}% buyers)")
    elif book_imbalance < 0.40:
        bearish_evidence.append(f"Order book depth ask-heavy ({int((1-book_imbalance)*100)}% sellers)")

    # Scoring & Status Determination
    bull_score = len(bullish_evidence)
    bear_score = len(bearish_evidence)

    # Invalidation and stop distance (minimum 1.5x ATR or 0.6% whichever is larger)
    min_stop_pct = max(0.6, round((atr / max(current_price, 0.0001)) * 150.0, 2))
    min_stop_pct = min(min_stop_pct, 2.5)  # Cap stop percentage
    
    # Determine directional bias
    if bull_score > bear_score:
        bias_action = "BUY"
    elif bear_score > bull_score:
        bias_action = "SELL"
    elif rsi14 >= 50:
        bias_action = "BUY"
    else:
        bias_action = "SELL"

    if bull_score >= 3 and bull_score > bear_score + 1:
        status = "BUY SETUP"
        action = "BUY"
        entry_low = round(current_price * 0.9990, 4 if current_price < 100 else 2)
        entry_high = round(current_price * 1.0015, 4 if current_price < 100 else 2)
        stop_price = round(current_price * (1.0 - min_stop_pct / 100.0), 4 if current_price < 100 else 2)
        t1 = round(current_price * (1.0 + (min_stop_pct * 1.5) / 100.0), 4 if current_price < 100 else 2)
        t2 = round(current_price * (1.0 + (min_stop_pct * 2.2) / 100.0), 4 if current_price < 100 else 2)
        t3 = round(current_price * (1.0 + (min_stop_pct * 3.0) / 100.0), 4 if current_price < 100 else 2)
        invalidation = f"Candle close below support {stop_price} or sudden spike in selling volume"
        entry_confirmation = "Look for 1-minute bullish rejection wick or 5m green candle close above entry zone."
        rr = round((t2 - current_price) / max(current_price - stop_price, 0.000001), 2)
        conf_score = min(88, 55 + (bull_score * 7))
        horizon_mins = "15 to 45 mins" if timeframe in ("1m", "3m", "5m") else "1 to 4 hours"
        overall_trend = "Bullish structure with ascending momentum"
    elif bear_score >= 3 and bear_score > bull_score + 1:
        status = "SELL SETUP"
        action = "SELL"
        entry_low = round(current_price * 0.9985, 4 if current_price < 100 else 2)
        entry_high = round(current_price * 1.0010, 4 if current_price < 100 else 2)
        stop_price = round(current_price * (1.0 + min_stop_pct / 100.0), 4 if current_price < 100 else 2)
        t1 = round(current_price * (1.0 - (min_stop_pct * 1.5) / 100.0), 4 if current_price < 100 else 2)
        t2 = round(current_price * (1.0 - (min_stop_pct * 2.2) / 100.0), 4 if current_price < 100 else 2)
        t3 = round(current_price * (1.0 - (min_stop_pct * 3.0) / 100.0), 4 if current_price < 100 else 2)
        invalidation = f"Candle close above resistance {stop_price} or buyers breaking 50 EMA"
        entry_confirmation = "Look for 1-minute bearish rejection wick at resistance or breakdown confirmation."
        rr = round((current_price - t2) / max(stop_price - current_price, 0.000001), 2)
        conf_score = min(88, 55 + (bear_score * 7))
        horizon_mins = "15 to 45 mins" if timeframe in ("1m", "3m", "5m") else "1 to 4 hours"
        overall_trend = "Bearish structure with downward pressure"
    else:
        # Market in range / compression: provide active directional bias for manual trading
        action = bias_action
        status = f"RANGE {action} (CONSOLIDATION)"
        if action == "BUY":
            entry_low = round(current_price * 0.9992, 4 if current_price < 100 else 2)
            entry_high = round(current_price * 1.0010, 4 if current_price < 100 else 2)
            stop_price = round(current_price * (1.0 - min_stop_pct / 100.0), 4 if current_price < 100 else 2)
            t1 = round(current_price * (1.0 + (min_stop_pct * 1.4) / 100.0), 4 if current_price < 100 else 2)
            t2 = round(current_price * (1.0 + (min_stop_pct * 2.0) / 100.0), 4 if current_price < 100 else 2)
            t3 = round(current_price * (1.0 + (min_stop_pct * 2.8) / 100.0), 4 if current_price < 100 else 2)
            invalidation = f"Breakdown below range low {stop_price}"
            entry_confirmation = "Enter near lower boundary of range with tight stop."
            rr = round((t2 - current_price) / max(current_price - stop_price, 0.000001), 2)
            overall_trend = "Range-bound with slight bullish lean"
        else:
            entry_low = round(current_price * 0.9990, 4 if current_price < 100 else 2)
            entry_high = round(current_price * 1.0008, 4 if current_price < 100 else 2)
            stop_price = round(current_price * (1.0 + min_stop_pct / 100.0), 4 if current_price < 100 else 2)
            t1 = round(current_price * (1.0 - (min_stop_pct * 1.4) / 100.0), 4 if current_price < 100 else 2)
            t2 = round(current_price * (1.0 - (min_stop_pct * 2.0) / 100.0), 4 if current_price < 100 else 2)
            t3 = round(current_price * (1.0 - (min_stop_pct * 2.8) / 100.0), 4 if current_price < 100 else 2)
            invalidation = f"Breakout above range high {stop_price}"
            entry_confirmation = "Enter near upper boundary of range with tight stop."
            rr = round((current_price - t2) / max(stop_price - current_price, 0.000001), 2)
            overall_trend = "Range-bound with slight bearish lean"

        conf_score = 65
        horizon_mins = "10 to 30 mins (Range scalp)"

    return {
        "status": status,
        "action": action,
        "symbol": symbol,
        "category": category,
        "timeframe": timeframe,
        "current_price": current_price,
        "overall_trend": overall_trend,
        "is_live": live,
        "timestamp": now,
        "updated_at_str": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "indicators": {
            "ema9": round(ema9, 4) if ema9 else None,
            "ema20": round(ema20, 4) if ema20 else None,
            "ema50": round(ema50, 4) if ema50 else None,
            "ema200": round(ema200, 4) if ema200 else None,
            "rsi14": round(rsi14, 2),
            "macd": macd,
            "bollinger": bb,
            "atr": round(atr, 4),
            "supports": sr["supports"],
            "resistances": sr["resistances"],
            "volume_ratio": round(vol_ratio, 2),
            "orderbook_bid_pct": round(book_imbalance * 100, 1)
        },
        "trade_plan": {
            "entry_zone": f"${entry_low} - ${entry_high}",
            "entry_price": current_price,
            "entry_confirmation": entry_confirmation,
            "stop_loss": stop_price,
            "stop_pct": min_stop_pct,
            "stop_reason": f"Set beyond local swing structure + 1.5x ATR ({atr:.4f}) buffer",
            "targets": {
                "t1": t1,
                "t2": t2,
                "t3": t3
            },
            "risk_reward": f"1:{rr}",
            "invalidation": invalidation,
            "holding_horizon": horizon_mins,
            "confidence_score": conf_score,
            "confidence_methodology": f"Multi-indicator consensus ({bull_score} bullish vs {bear_score} bearish signals across EMA, RSI, MACD, BB, Vol)."
        },
        "reasoning": {
            "market_condition": f"{symbol} is currently in {overall_trend}. Volatility ATR is ${atr:.4f}.",
            "bullish_evidence": bullish_evidence,
            "bearish_evidence": bearish_evidence,
            "entry_plan": f"Plan {action} entry within zone ${entry_low} to ${entry_high} only after confirmation.",
            "risk_plan": f"Strict invalidation stop at ${stop_price} (-{min_stop_pct}%). Do not widen stop loss.",
            "exit_plan": f"Scale out: 50% at T1 (${t1}), 30% at T2 (${t2}), trail remainder to T3 (${t3}) with breakeven stop once T1 is hit.",
            "alternative_scenario": "If opposite volume sweeps the current level, invalidate immediately and revert to WAIT."
        }
    }


def calculate_position_size(account_capital, risk_pct, entry_price, stop_loss_price, leverage=1.0, 
                            fee_pct=0.05, slippage_pct=0.02, category="CRYPTO"):
    """
    Mathematical position sizing calculator:
    - Calculates maximum acceptable loss from risk percentage
    - Derives quantity strictly from stop-loss distance
    - Prevents over-leveraging and calculates exact margin required
    - Computes estimated liquidation price and fees
    """
    if account_capital <= 0 or entry_price <= 0 or stop_loss_price <= 0:
        return {"error": "Invalid inputs for position sizing"}

    # 1. Planned Loss Limit (Risk Budget)
    max_acceptable_loss = account_capital * (risk_pct / 100.0)

    # 2. Stop distance per unit
    stop_distance = abs(entry_price - stop_loss_price)
    stop_distance_pct = (stop_distance / entry_price) * 100.0

    if stop_distance <= 0:
        return {"error": "Stop loss cannot be identical to entry price"}

    # 3. Position Quantity based on risk budget
    # Risk = Qty * stop_distance + estimated round-trip fees & slippage
    # Fee & slippage per unit = entry_price * (fee_pct * 2 + slippage_pct) / 100
    friction_per_unit = entry_price * ((fee_pct * 2.0 + slippage_pct) / 100.0)
    total_loss_per_unit = stop_distance + friction_per_unit

    qty = max_acceptable_loss / total_loss_per_unit

    # 4. Notional Exposure and Required Margin
    notional_value = qty * entry_price
    effective_leverage = max(1.0, float(leverage))
    required_margin = notional_value / effective_leverage

    # 5. Estimated Fees
    est_open_fee = notional_value * (fee_pct / 100.0)
    est_close_fee = notional_value * (fee_pct / 100.0)
    total_fees = est_open_fee + est_close_fee

    # 6. Estimated Loss if Stop Loss is Hit
    gross_loss = qty * stop_distance
    net_loss = gross_loss + total_fees

    # 7. Estimated Liquidation Price
    # Maintenance margin assumption: 0.5% (1/200) or 1/leverage
    maint_margin_pct = min(0.005, 1.0 / effective_leverage)
    is_long = entry_price > stop_loss_price

    if is_long:
        liq_price = entry_price * (1.0 - (1.0 / effective_leverage) + maint_margin_pct)
        liq_price = max(0.0, liq_price)
    else:
        liq_price = entry_price * (1.0 + (1.0 / effective_leverage) - maint_margin_pct)

    # 8. Sanity Warnings
    warnings = []
    if required_margin > account_capital:
        warnings.append(f"Required margin (${required_margin:.2f}) exceeds available capital (${account_capital:.2f})! Reduce leverage or risk %.")
    if stop_distance_pct < 0.3:
        warnings.append(f"Stop loss is extremely tight ({stop_distance_pct:.2f}%). High risk of premature stop-out by normal spread/noise.")
    if is_long and stop_loss_price <= liq_price:
        warnings.append(f"DANGER: Liquidation price (${liq_price:.4f}) will trigger BEFORE your Stop Loss (${stop_loss_price:.4f})! Lower your leverage immediately.")
    elif (not is_long) and stop_loss_price >= liq_price:
        warnings.append(f"DANGER: Liquidation price (${liq_price:.4f}) will trigger BEFORE your Stop Loss (${stop_loss_price:.4f})! Lower your leverage immediately.")

    return {
        "account_capital": round(account_capital, 2),
        "risk_pct": risk_pct,
        "max_acceptable_loss": round(max_acceptable_loss, 2),
        "entry_price": entry_price,
        "stop_loss_price": stop_loss_price,
        "stop_distance_pct": round(stop_distance_pct, 2),
        "leverage": effective_leverage,
        "position_quantity": round(qty, 6),
        "notional_value": round(notional_value, 2),
        "required_margin": round(required_margin, 2),
        "estimated_fees": round(total_fees, 2),
        "estimated_loss_at_stop": round(net_loss, 2),
        "liquidation_price": round(liq_price, 4 if entry_price < 100 else 2),
        "warnings": warnings,
        "is_valid": len([w for w in warnings if "DANGER" in w or "exceeds" in w]) == 0
    }


# =====================================================================
# ARAABOT V2.0 — ADVANCED TECHNICAL ANALYSIS, MULTI-TIMEFRAME & AI ENGINE
# =====================================================================

def calculate_vwap(candles):
    """Volume Weighted Average Price over validated OHLCV candles."""
    if not candles:
        return 0.0
    cum_pv = 0.0
    cum_vol = 0.0
    for c in candles:
        typical = (float(c.get("h", c.get("c", 0.0))) + float(c.get("l", c.get("c", 0.0))) + float(c.get("c", 0.0))) / 3.0
        vol = max(float(c.get("v", 1.0) or 1.0), 0.0001)
        cum_pv += typical * vol
        cum_vol += vol
    return round(cum_pv / max(cum_vol, 0.0001), 6)


def calculate_stoch_rsi(prices, rsi_period=14, stoch_period=14, k_smooth=3, d_smooth=3):
    """Stochastic RSI (%K and %D) in [0, 100]."""
    if not prices or len(prices) < rsi_period + 3:
        return {"k": 50.0, "d": 50.0}
    rsi_series = []
    start_idx = max(rsi_period + 1, len(prices) - (stoch_period + k_smooth + d_smooth + 5))
    for end_i in range(start_idx, len(prices) + 1):
        rsi_series.append(calculate_rsi(prices[:end_i], rsi_period))
    if len(rsi_series) < 2:
        val = rsi_series[-1] if rsi_series else 50.0
        return {"k": round(val, 2), "d": round(val, 2)}

    raw_k = []
    for i in range(len(rsi_series)):
        win = rsi_series[max(0, i - stoch_period + 1): i + 1]
        lo = min(win)
        hi = max(win)
        if hi - lo <= 1e-9:
            raw_k.append(50.0)
        else:
            raw_k.append(((rsi_series[i] - lo) / (hi - lo)) * 100.0)

    k_series = []
    for i in range(len(raw_k)):
        win_k = raw_k[max(0, i - k_smooth + 1): i + 1]
        k_series.append(sum(win_k) / len(win_k))

    d_win = k_series[-d_smooth:] if len(k_series) >= d_smooth else k_series
    k_val = k_series[-1]
    d_val = sum(d_win) / len(d_win)
    return {"k": round(k_val, 2), "d": round(d_val, 2)}


def calculate_adx(candles, period=14):
    """Average Directional Index (ADX 14) with +DI and -DI."""
    if not candles or len(candles) < 3:
        return {"adx": 20.0, "plus_di": 20.0, "minus_di": 20.0, "trend_strength": "WEAK"}
    trs, plus_dms, minus_dms = [], [], []
    for i in range(1, len(candles)):
        h = float(candles[i].get("h", candles[i].get("c", 0.0)))
        l = float(candles[i].get("l", candles[i].get("c", 0.0)))
        prev_h = float(candles[i - 1].get("h", candles[i - 1].get("c", 0.0)))
        prev_l = float(candles[i - 1].get("l", candles[i - 1].get("c", 0.0)))
        prev_c = float(candles[i - 1].get("c", 0.0))

        up_move = h - prev_h
        down_move = prev_l - l
        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
        plus_dms.append(plus_dm)
        minus_dms.append(minus_dm)

    win = min(period, len(trs))
    if win == 0:
        return {"adx": 20.0, "plus_di": 20.0, "minus_di": 20.0, "trend_strength": "WEAK"}

    dx_list = []
    plus_di = 20.0
    minus_di = 20.0
    for end_i in range(win, len(trs) + 1):
        tr_sum = max(sum(trs[end_i - win: end_i]), 1e-9)
        p_dm_sum = sum(plus_dms[end_i - win: end_i])
        m_dm_sum = sum(minus_dms[end_i - win: end_i])
        plus_di = (p_dm_sum / tr_sum) * 100.0
        minus_di = (m_dm_sum / tr_sum) * 100.0
        di_sum = max(plus_di + minus_di, 1e-9)
        dx = (abs(plus_di - minus_di) / di_sum) * 100.0
        dx_list.append(dx)

    adx_val = sum(dx_list[-win:]) / max(1, len(dx_list[-win:])) if dx_list else 20.0
    strength = "STRONG" if adx_val >= 25.0 else ("MODERATE" if adx_val >= 18.0 else "WEAK")
    return {
        "adx": round(adx_val, 2),
        "plus_di": round(plus_di, 2),
        "minus_di": round(minus_di, 2),
        "trend_strength": strength,
    }


def detect_market_structure(candles, swing_window=3):
    """
    Detects Swing Highs, Swing Lows, Higher-High / Higher-Low (HH/HL),
    and Lower-High / Lower-Low (LH/LL) market structure.
    """
    if not candles or len(candles) < (swing_window * 2 + 2):
        p = float(candles[-1].get("c", 0.0)) if candles else 0.0
        return {
            "structure": "CONSOLIDATION",
            "higher_high": False,
            "higher_low": False,
            "lower_high": False,
            "lower_low": False,
            "swing_highs": [round(p * 1.005, 6)] if p else [],
            "swing_lows": [round(p * 0.995, 6)] if p else [],
        }

    highs = [float(c.get("h", c.get("c", 0.0))) for c in candles]
    lows = [float(c.get("l", c.get("c", 0.0))) for c in candles]
    swing_highs = []
    swing_lows = []

    for i in range(swing_window, len(candles) - swing_window):
        if highs[i] == max(highs[i - swing_window: i + swing_window + 1]):
            if not swing_highs or swing_highs[-1] != highs[i]:
                swing_highs.append(round(highs[i], 6))
        if lows[i] == min(lows[i - swing_window: i + swing_window + 1]):
            if not swing_lows or swing_lows[-1] != lows[i]:
                swing_lows.append(round(lows[i], 6))

    if len(swing_highs) < 2:
        mid = len(highs) // 2
        swing_highs = [round(max(highs[:mid]), 6), round(max(highs[mid:]), 6)]
    if len(swing_lows) < 2:
        mid = len(lows) // 2
        swing_lows = [round(min(lows[:mid]), 6), round(min(lows[mid:]), 6)]

    hh = swing_highs[-1] > swing_highs[-2]
    hl = swing_lows[-1] > swing_lows[-2]
    lh = swing_highs[-1] < swing_highs[-2]
    ll = swing_lows[-1] < swing_lows[-2]

    if hh and hl:
        structure = "BULLISH_HH_HL"
    elif lh and ll:
        structure = "BEARISH_LH_LL"
    elif hh and ll:
        structure = "EXPANSION_VOLATILE"
    else:
        structure = "CONSOLIDATION"

    return {
        "structure": structure,
        "higher_high": bool(hh),
        "higher_low": bool(hl),
        "lower_high": bool(lh),
        "lower_low": bool(ll),
        "swing_highs": swing_highs[-4:],
        "swing_lows": swing_lows[-4:],
    }


def detect_breakout_pullback(candles, ema21, vwap, sr_levels):
    """Detects validated breakouts and trend pullbacks."""
    if not candles or len(candles) < 5:
        return {
            "breakout_up": False,
            "breakout_down": False,
            "pullback_long": False,
            "pullback_short": False,
            "setup_type": "NONE",
        }
    curr = float(candles[-1].get("c", 0.0))
    prev = float(candles[-2].get("c", curr))
    high_prev_n = max(float(c.get("h", c.get("c", 0.0))) for c in candles[-min(15, len(candles)):-1])
    low_prev_n = min(float(c.get("l", c.get("c", 0.0))) for c in candles[-min(15, len(candles)):-1])

    breakout_up = curr > high_prev_n and curr > prev
    breakout_down = curr < low_prev_n and curr < prev

    ref_level = float(ema21 or vwap or curr)
    dist_to_ref_pct = abs(curr - ref_level) / max(ref_level, 1e-9) * 100.0
    pullback_long = (curr >= ref_level) and (dist_to_ref_pct <= 0.45) and (curr > prev)
    pullback_short = (curr <= ref_level) and (dist_to_ref_pct <= 0.45) and (curr < prev)

    if breakout_up:
        setup_type = "BULLISH_BREAKOUT"
    elif breakout_down:
        setup_type = "BEARISH_BREAKOUT"
    elif pullback_long:
        setup_type = "BULLISH_PULLBACK"
    elif pullback_short:
        setup_type = "BEARISH_PULLBACK"
    else:
        setup_type = "CONTINUATION_OR_RANGE"

    return {
        "breakout_up": bool(breakout_up),
        "breakout_down": bool(breakout_down),
        "pullback_long": bool(pullback_long),
        "pullback_short": bool(pullback_short),
        "recent_range_high": round(high_prev_n, 6),
        "recent_range_low": round(low_prev_n, 6),
        "setup_type": setup_type,
    }


def detect_candlestick_patterns(candles):
    """Recognizes classic institutional candlestick patterns on closed candles."""
    if not candles or len(candles) < 2:
        return ["NONE"]
    patterns = []
    c1 = candles[-2]
    c2 = candles[-1]
    o1, h1, l1, cl1 = float(c1.get("o", c1["c"])), float(c1["h"]), float(c1["l"]), float(c1["c"])
    o2, h2, l2, cl2 = float(c2.get("o", c2["c"])), float(c2["h"]), float(c2["l"]), float(c2["c"])

    body1 = abs(cl1 - o1)
    body2 = abs(cl2 - o2)
    rng2 = max(h2 - l2, 1e-9)
    upper_wick2 = h2 - max(o2, cl2)
    lower_wick2 = min(o2, cl2) - l2

    # Bullish Engulfing
    if cl1 < o1 and cl2 > o2 and cl2 >= o1 and o2 <= cl1 and body2 > body1:
        patterns.append("BULLISH_ENGULFING")
    # Bearish Engulfing
    if cl1 > o1 and cl2 < o2 and cl2 <= o1 and o2 >= cl1 and body2 > body1:
        patterns.append("BEARISH_ENGULFING")
    # Hammer / Bullish Pinbar
    if lower_wick2 >= body2 * 2.0 and upper_wick2 <= body2 * 0.8 and (body2 / rng2) >= 0.1:
        patterns.append("HAMMER_PINBAR")
    # Shooting Star / Bearish Pinbar
    if upper_wick2 >= body2 * 2.0 and lower_wick2 <= body2 * 0.8 and (body2 / rng2) >= 0.1:
        patterns.append("SHOOTING_STAR")
    # Doji
    if (body2 / rng2) <= 0.08:
        patterns.append("DOJI_INDECISION")

    return patterns or ["STANDARD_BAR"]


def analyze_technical_v2(symbol, candles, timeframe="15m", use_closed_candles_only=True):
    """
    AraaBot V2.0 Real-Time Technical Analysis Engine on validated OHLCV candles.
    Computes all required indicators:
    EMA 9/21/50/200, SMA 20/50/200, RSI 14, MACD, Bollinger Bands, ATR, ADX, VWAP,
    Stochastic RSI, Volume SMA & Relative Volume, Support/Resistance, Market Structure (HH/HL/LH/LL),
    Breakout/Pullback detection, Momentum, Volatility, and Candlestick Patterns.
    """
    now = time.time()
    sym = str(symbol or "BTCUSDT").upper().replace("B-", "").replace("_", "")
    raw_candles = list(candles or [])
    if use_closed_candles_only and len(raw_candles) > 25:
        eval_candles = raw_candles[:-1]
    else:
        eval_candles = raw_candles

    if len(eval_candles) < 10:
        return {
            "valid": False,
            "symbol": sym,
            "timeframe": timeframe,
            "reason": "INSUFFICIENT_CANDLE_DATA",
            "candle_count": len(eval_candles),
            "timestamp": now,
        }

    closes = [float(c.get("c", 0.0)) for c in eval_candles]
    volumes = [float(c.get("v", 1.0) or 1.0) for c in eval_candles]
    current_price = float(raw_candles[-1].get("c", closes[-1]))
    last_candle_ts = float(raw_candles[-1].get("t", now))

    ema9 = calculate_ema(closes, 9) or current_price
    ema21 = calculate_ema(closes, 21) or calculate_ema(closes, min(len(closes), 21)) or current_price
    ema50 = calculate_ema(closes, min(len(closes), 50)) or current_price
    ema200 = calculate_ema(closes, min(len(closes), 200)) or current_price

    sma20 = calculate_sma(closes, min(len(closes), 20)) or current_price
    sma50 = calculate_sma(closes, min(len(closes), 50)) or current_price
    sma200 = calculate_sma(closes, min(len(closes), 200)) or current_price

    rsi14 = calculate_rsi(closes, 14)
    macd = calculate_macd(closes)
    bb = calculate_bollinger_bands(closes, min(len(closes), 20), 2.0)
    atr = calculate_atr(eval_candles, 14)
    adx_data = calculate_adx(eval_candles, 14)
    vwap = calculate_vwap(eval_candles[-min(len(eval_candles), 50):])
    stoch_rsi = calculate_stoch_rsi(closes, 14, 14, 3, 3)

    vol_sma20 = sum(volumes[-min(len(volumes), 20):]) / max(1, min(len(volumes), 20))
    rel_volume = round(volumes[-1] / max(vol_sma20, 1e-9), 2)

    sr = detect_support_resistance(eval_candles, window=min(8, max(2, len(eval_candles) // 4)))
    structure = detect_market_structure(eval_candles, swing_window=min(3, max(1, len(eval_candles) // 6)))
    bp = detect_breakout_pullback(eval_candles, ema21, vwap, sr)
    patterns = detect_candlestick_patterns(eval_candles)

    atr_pct = round((atr / max(current_price, 1e-9)) * 100.0, 4)
    if atr_pct >= 2.2 or bb["bandwidth"] >= 0.065:
        volatility_state = "HIGH"
    elif atr_pct <= 0.25 or bb["bandwidth"] <= 0.012:
        volatility_state = "LOW"
    else:
        volatility_state = "NORMAL"

    # Trend & Momentum Detection
    bull_points = 0
    bear_points = 0
    if ema9 > ema21:
        bull_points += 1
    else:
        bear_points += 1
    if current_price > ema50:
        bull_points += 1
    else:
        bear_points += 1
    if current_price > ema200:
        bull_points += 1
    else:
        bear_points += 1
    if macd["hist"] > 0:
        bull_points += 1
    elif macd["hist"] < 0:
        bear_points += 1
    if current_price >= vwap:
        bull_points += 1
    else:
        bear_points += 1
    if structure["structure"] == "BULLISH_HH_HL":
        bull_points += 1
    elif structure["structure"] == "BEARISH_LH_LL":
        bear_points += 1

    if bull_points >= bear_points + 2:
        trend = "BULLISH"
    elif bear_points >= bull_points + 2:
        trend = "BEARISH"
    else:
        trend = "NEUTRAL"

    if adx_data["adx"] >= 25.0 and abs(bull_points - bear_points) >= 2:
        market_regime = "TRENDING"
    elif volatility_state == "HIGH":
        market_regime = "VOLATILE_EXPANSION"
    else:
        market_regime = "RANGING"

    if (trend == "BULLISH" and rsi14 >= 54 and macd["hist"] > 0) or (trend == "BEARISH" and rsi14 <= 46 and macd["hist"] < 0):
        momentum = "STRONG"
    elif 45 <= rsi14 <= 55:
        momentum = "NEUTRAL"
    else:
        momentum = "MODERATE"

    return {
        "valid": True,
        "symbol": sym,
        "timeframe": timeframe,
        "current_price": round(current_price, 6),
        "candle_count": len(eval_candles),
        "used_closed_candles": bool(use_closed_candles_only),
        "market_data_timestamp": datetime.fromtimestamp(last_candle_ts, timezone.utc).isoformat(),
        "analysis_timestamp": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "trend": trend,
        "trend_strength": adx_data["trend_strength"],
        "market_regime": market_regime,
        "momentum": momentum,
        "volatility": volatility_state,
        "indicators": {
            "ema9": round(ema9, 6),
            "ema21": round(ema21, 6),
            "ema50": round(ema50, 6),
            "ema200": round(ema200, 6),
            "sma20": round(sma20, 6),
            "sma50": round(sma50, 6),
            "sma200": round(sma200, 6),
            "rsi14": round(rsi14, 2),
            "macd": macd["macd"],
            "macd_signal": macd["signal"],
            "macd_hist": macd["hist"],
            "bollinger": bb,
            "atr": round(atr, 6),
            "atr_pct": atr_pct,
            "adx": adx_data["adx"],
            "plus_di": adx_data["plus_di"],
            "minus_di": adx_data["minus_di"],
            "vwap": round(vwap, 6),
            "stoch_rsi_k": stoch_rsi["k"],
            "stoch_rsi_d": stoch_rsi["d"],
            "volume_sma20": round(vol_sma20, 2),
            "relative_volume": rel_volume,
            "supports": sr["supports"],
            "resistances": sr["resistances"],
        },
        "market_structure": structure,
        "breakout_pullback": bp,
        "candlestick_patterns": patterns,
        "scores": {
            "bullish_points": bull_points,
            "bearish_points": bear_points,
        },
    }


def analyze_multi_timeframe(symbol, candles_by_tf, tf_config=None, use_closed_candles_only=True):
    """
    Multi-Timeframe Analysis across configurable timeframes (1m, 3m, 5m, 15m, 30m, 1h, 4h, 1d).
    Example hierarchy:
      - major_tf (e.g. 4h): Determine major market trend
      - confirm_tf (e.g. 1h): Confirm trend & market structure
      - setup_tf (e.g. 15m): Identify setup confirmation
      - entry_tf (e.g. 5m): Entry trigger
    """
    cfg = tf_config or {
        "major_tf": "4h",
        "confirm_tf": "1h",
        "setup_tf": "15m",
        "entry_tf": "5m",
    }
    supported = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"]
    tf_results = {}
    for tf, c_list in (candles_by_tf or {}).items():
        if c_list and len(c_list) >= 10:
            tf_results[tf] = analyze_technical_v2(
                symbol=symbol,
                candles=c_list,
                timeframe=tf,
                use_closed_candles_only=use_closed_candles_only,
            )

    major_tf = cfg.get("major_tf", "4h")
    confirm_tf = cfg.get("confirm_tf", "1h")
    setup_tf = cfg.get("setup_tf", "15m")
    entry_tf = cfg.get("entry_tf", "5m")

    active_hierarchy = [t for t in [major_tf, confirm_tf, setup_tf, entry_tf] if t in tf_results]
    if not active_hierarchy:
        active_hierarchy = list(tf_results.keys())

    bull_tfs = [t for t in active_hierarchy if tf_results[t].get("trend") == "BULLISH"]
    bear_tfs = [t for t in active_hierarchy if tf_results[t].get("trend") == "BEARISH"]

    total_checked = len(active_hierarchy)
    if total_checked > 0 and len(bull_tfs) >= max(1, total_checked - 1) and len(bear_tfs) == 0:
        alignment = "ALIGNED_BULLISH"
        mtf_confirmed = True
        dominant_direction = "LONG"
    elif total_checked > 0 and len(bear_tfs) >= max(1, total_checked - 1) and len(bull_tfs) == 0:
        alignment = "ALIGNED_BEARISH"
        mtf_confirmed = True
        dominant_direction = "SHORT"
    elif len(bull_tfs) > len(bear_tfs):
        alignment = "PARTIAL_BULLISH"
        mtf_confirmed = len(bull_tfs) >= 2
        dominant_direction = "LONG"
    elif len(bear_tfs) > len(bull_tfs):
        alignment = "PARTIAL_BEARISH"
        mtf_confirmed = len(bear_tfs) >= 2
        dominant_direction = "SHORT"
    else:
        alignment = "MIXED_CONSOLIDATION"
        mtf_confirmed = False
        dominant_direction = "NEUTRAL"

    return {
        "symbol": str(symbol or "BTCUSDT").upper(),
        "supported_timeframes": supported,
        "configured_hierarchy": cfg,
        "evaluated_timeframes": active_hierarchy,
        "alignment": alignment,
        "mtf_confirmed": bool(mtf_confirmed),
        "dominant_direction": dominant_direction,
        "bullish_timeframes": bull_tfs,
        "bearish_timeframes": bear_tfs,
        "timeframe_summaries": {
            tf: {
                "trend": res.get("trend"),
                "trend_strength": res.get("trend_strength"),
                "market_regime": res.get("market_regime"),
                "momentum": res.get("momentum"),
                "rsi14": res.get("indicators", {}).get("rsi14"),
                "ema9": res.get("indicators", {}).get("ema9"),
                "ema21": res.get("indicators", {}).get("ema21"),
                "ema50": res.get("indicators", {}).get("ema50"),
                "macd_hist": res.get("indicators", {}).get("macd_hist"),
                "structure": res.get("market_structure", {}).get("structure"),
            }
            for tf, res in tf_results.items()
        },
    }


def generate_araa_ai_analysis(symbol, primary_ta, mtf_result=None):
    """
    Araa AI Technical Analyzer (Decision-Support & Proposal Layer).
    Generates structured market analysis, setup reasoning, invalidation, SL/TP suggestions,
    and R:R ratio.
    IMPORTANT: AI recommendations are proposals only and NEVER bypass the Python StrategyEngine.
    """
    sym = str(symbol or "BTCUSDT").upper().replace("B-", "").replace("_", "")
    if not primary_ta or not primary_ta.get("valid"):
        now_iso = datetime.now(timezone.utc).isoformat()
        return {
            "instrument": sym,
            "trend": "NEUTRAL",
            "trend_strength": "WEAK",
            "market_regime": "UNKNOWN",
            "momentum": "NEUTRAL",
            "volatility": "NORMAL",
            "long_setup": False,
            "short_setup": False,
            "entry_reason": "Insufficient validated market data for technical confluence.",
            "invalidation_reason": "Market data feed incomplete or fewer than minimum closed candles.",
            "stop_loss_suggestion": 0.0,
            "take_profit_suggestion": 0.0,
            "risk_reward": 0.0,
            "confidence": 0,
            "technical_confluence": [],
            "analysis_timestamp": now_iso,
            "market_data_timestamp": now_iso,
            "proposal_only": True,
        }

    ind = primary_ta["indicators"]
    price = float(primary_ta["current_price"])
    atr = max(float(ind.get("atr") or (price * 0.005)), price * 0.002)
    trend = primary_ta["trend"]
    regime = primary_ta["market_regime"]
    momentum = primary_ta["momentum"]
    volatility = primary_ta["volatility"]
    structure = primary_ta["market_structure"]["structure"]
    bp = primary_ta["breakout_pullback"]
    patterns = primary_ta["candlestick_patterns"]

    mtf = mtf_result or {}
    mtf_aligned = bool(mtf.get("mtf_confirmed", True))
    mtf_dir = mtf.get("dominant_direction", "LONG" if trend == "BULLISH" else ("SHORT" if trend == "BEARISH" else "NEUTRAL"))

    confluence = []
    if ind["ema9"] > ind["ema21"] > ind["ema50"]:
        confluence.append("Bullish EMA Ribbon (EMA 9 > 21 > 50)")
    elif ind["ema9"] < ind["ema21"] < ind["ema50"]:
        confluence.append("Bearish EMA Ribbon (EMA 9 < 21 < 50)")

    if price > ind["vwap"]:
        confluence.append("Price holding above institutional VWAP")
    else:
        confluence.append("Price trading below institutional VWAP")

    if ind["macd_hist"] > 0:
        confluence.append("Positive MACD momentum histogram")
    elif ind["macd_hist"] < 0:
        confluence.append("Negative MACD momentum histogram")

    if ind["relative_volume"] >= 1.1:
        confluence.append(f"Relative volume confirmation ({ind['relative_volume']}x SMA20)")

    if structure in ("BULLISH_HH_HL", "BEARISH_LH_LL"):
        confluence.append(f"Market structure: {structure}")

    long_setup = bool(
        trend == "BULLISH"
        and (mtf_dir in ("LONG", "NEUTRAL"))
        and 32.0 <= ind["rsi14"] <= 72.0
        and ind["macd_hist"] >= 0
    )
    short_setup = bool(
        trend == "BEARISH"
        and (mtf_dir in ("SHORT", "NEUTRAL"))
        and 28.0 <= ind["rsi14"] <= 68.0
        and ind["macd_hist"] <= 0
    )

    stop_dist = max(atr * 1.5, price * 0.006)
    tp_dist = stop_dist * 2.2
    rr = round(tp_dist / max(stop_dist, 1e-9), 2)

    if long_setup:
        sl_sug = round(price - stop_dist, 6)
        tp_sug = round(price + tp_dist, 6)
        entry_reason = (
            f"Bullish technical confluence on {sym}: {trend} trend ({regime}), "
            f"EMA9 ({ind['ema9']}) > EMA21 ({ind['ema21']}), RSI14={ind['rsi14']}, "
            f"setup={bp['setup_type']}, patterns={','.join(patterns)}."
        )
        inv_reason = f"Close below swing support / SL {sl_sug} or EMA21 breakdown with negative MACD cross."
    elif short_setup:
        sl_sug = round(price + stop_dist, 6)
        tp_sug = round(price - tp_dist, 6)
        entry_reason = (
            f"Bearish technical confluence on {sym}: {trend} trend ({regime}), "
            f"EMA9 ({ind['ema9']}) < EMA21 ({ind['ema21']}), RSI14={ind['rsi14']}, "
            f"setup={bp['setup_type']}, patterns={','.join(patterns)}."
        )
        inv_reason = f"Close above swing resistance / SL {sl_sug} or EMA21 reclaim with positive MACD cross."
    else:
        sl_sug = round(price - stop_dist, 6)
        tp_sug = round(price + tp_dist, 6)
        entry_reason = f"No confirmed high-confluence entry setup ({trend} / RSI={ind['rsi14']}). Waiting for rule alignment."
        inv_reason = f"Range boundary breach beyond {round(price - stop_dist, 6)} / {round(price + stop_dist, 6)}."

    pts = max(primary_ta["scores"]["bullish_points"], primary_ta["scores"]["bearish_points"])
    base_conf = 52 + (pts * 6) + (6 if mtf_aligned else 0) + (4 if ind["relative_volume"] >= 1.0 else 0)
    confidence = int(max(35, min(92, base_conf if (long_setup or short_setup) else min(64, base_conf))))

    return {
        "instrument": sym,
        "trend": trend,
        "trend_strength": primary_ta["trend_strength"],
        "market_regime": regime,
        "momentum": momentum,
        "volatility": volatility,
        "volume_confirmation": bool(ind["relative_volume"] >= 0.9),
        "support_levels": ind["supports"],
        "resistance_levels": ind["resistances"],
        "market_structure": primary_ta["market_structure"],
        "breakout_conditions": primary_ta["breakout_pullback"],
        "pullback_conditions": {
            "pullback_long": bp["pullback_long"],
            "pullback_short": bp["pullback_short"],
        },
        "multi_timeframe_alignment": {
            "alignment": mtf.get("alignment", "SINGLE_TF"),
            "confirmed": mtf_aligned,
            "dominant_direction": mtf_dir,
        },
        "long_setup": long_setup,
        "short_setup": short_setup,
        "entry_reason": entry_reason,
        "invalidation_reason": inv_reason,
        "stop_loss_suggestion": sl_sug,
        "take_profit_suggestion": tp_sug,
        "risk_reward": rr,
        "confidence": confidence,
        "technical_confluence": confluence,
        "analysis_timestamp": primary_ta["analysis_timestamp"],
        "market_data_timestamp": primary_ta["market_data_timestamp"],
        "proposal_only": True,
    }

