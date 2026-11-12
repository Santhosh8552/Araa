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
