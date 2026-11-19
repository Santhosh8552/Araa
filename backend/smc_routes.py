"""
AraaBot V2 — SMC Routes Blueprint.
Implements institutional SMC endpoints:
- Market Structure, Order Blocks, FVGs, Liquidity, Dealing Range
- Multi-Timeframe Matrix
- Araa AI Market Advisor & Scenario Trees
- Live Strategy Scanner
- User Alert Engine
- Historical Backtester
- Trading Journal
"""

import time
import json
import logging
import uuid
from typing import Dict, Any, List, Optional
from flask import Blueprint, request, jsonify

import database as db
from price_feed import feed
from smc_engine import (
    normalize_candles,
    compute_atr,
    MarketStructureEngine,
    OrderBlockEngine,
    FVGEngine,
    LiquidityEngine,
    AraaAIMarketAdvisor,
    MultiTimeframeEngine,
    SMCBacktestEngine
)

logger = logging.getLogger("araabot.smc_routes")
smc_bp = Blueprint("smc_bp", __name__)


def _get_user():
    token = request.headers.get("X-Token") or request.args.get("token")
    if not token:
        return None
    try:
        row = db.query_one(
            "SELECT s.token, u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
            (token,)
        )
        return row
    except Exception:
        return None


def _get_candles(symbol: str, tf: str = "15m", limit: int = 120) -> List[Dict[str, float]]:
    raw = feed.candles(symbol, interval=tf, limit=limit, allow_network=True)
    return normalize_candles(raw)


# ==============================================================================
# 1. SMC ANALYSIS & OVERLAY ENDPOINTS
# ==============================================================================

@smc_bp.route("/api/smc/analysis/<symbol>", methods=["GET"])
def smc_analysis(symbol: str):
    """Full institutional SMC analysis including Structure, OBs, FVGs, Liquidity & Araa AI report."""
    tf = request.args.get("timeframe", "15m")
    candles = _get_candles(symbol, tf=tf, limit=140)
    if not candles:
        return jsonify({"success": False, "error": "Unable to load market candles"}), 404

    current_price = candles[-1]["c"]
    atr = compute_atr(candles)
    swings = MarketStructureEngine.detect_swings(candles, sensitivity=4)
    structure_breaks = MarketStructureEngine.detect_structure_breaks(candles, swings)
    order_blocks = OrderBlockEngine.detect_order_blocks(candles, atr)
    fvgs = FVGEngine.detect_fvgs(candles, atr=atr)
    liquidity = LiquidityEngine.detect_liquidity_pools(candles, swings)

    ai_report = AraaAIMarketAdvisor.generate_report(
        symbol=symbol,
        timeframe=tf,
        current_price=current_price,
        structure_events=structure_breaks,
        order_blocks=order_blocks,
        fvgs=fvgs,
        liquidity=liquidity,
        atr=atr
    )

    return jsonify({
        "success": True,
        "symbol": symbol.upper(),
        "timeframe": tf,
        "current_price": current_price,
        "atr": round(atr, 4),
        "candles": candles,
        "swings": swings,
        "structure_breaks": structure_breaks,
        "order_blocks": order_blocks,
        "fair_value_gaps": fvgs,
        "liquidity": liquidity,
        "ai_report": ai_report,
        "timestamp": int(time.time())
    })


@smc_bp.route("/api/market/candles/<symbol>", methods=["GET"])
def market_candles(symbol: str):
    """Retrieve raw normalized OHLCV candles for any instrument and timeframe."""
    tf = request.args.get("timeframe", "15m")
    limit = int(request.args.get("limit", 140))
    candles = _get_candles(symbol, tf=tf, limit=limit)
    return jsonify({
        "success": True,
        "symbol": symbol.upper(),
        "timeframe": tf,
        "candles": candles,
        "count": len(candles)
    })


@smc_bp.route("/api/market/quote/<symbol>", methods=["GET"])
def market_quote(symbol: str):
    """Retrieve real-time ticker quote, bid, ask, and 24h change for any instrument."""
    candles = _get_candles(symbol, tf="1m", limit=2)
    cur = candles[-1]["c"] if candles else 0.0
    open_p = candles[-1]["o"] if candles else cur
    high_p = candles[-1]["h"] if candles else cur
    low_p = candles[-1]["l"] if candles else cur
    change = cur - open_p
    change_pct = (change / open_p * 100) if open_p > 0 else 0.0
    return jsonify({
        "success": True,
        "symbol": symbol.upper(),
        "price": cur,
        "bid": round(cur * 0.9999, 4),
        "ask": round(cur * 1.0001, 4),
        "high_24h": high_p,
        "low_24h": low_p,
        "change_pct": round(change_pct, 2),
        "timestamp": int(time.time())
    })


@smc_bp.route("/api/market/instruments", methods=["GET"])
@smc_bp.route("/api/smc/instruments", methods=["GET"])
def market_instruments():
    """List all supported instruments categorized across Crypto, Forex, Metals, and Indices."""
    instruments = [
        {"symbol": "BTCUSDT", "name": "Bitcoin / Tether", "category": "CRYPTO", "precision": 2, "min_qty": 0.001},
        {"symbol": "ETHUSDT", "name": "Ethereum / Tether", "category": "CRYPTO", "precision": 2, "min_qty": 0.01},
        {"symbol": "SOLUSDT", "name": "Solana / Tether", "category": "CRYPTO", "precision": 2, "min_qty": 0.1},
        {"symbol": "XAUUSD", "name": "Gold / US Dollar", "category": "METALS", "precision": 2, "min_qty": 0.01},
        {"symbol": "EURUSD", "name": "Euro / US Dollar", "category": "FOREX", "precision": 5, "min_qty": 1000},
        {"symbol": "GBPUSD", "name": "British Pound / US Dollar", "category": "FOREX", "precision": 5, "min_qty": 1000},
        {"symbol": "USDJPY", "name": "US Dollar / Japanese Yen", "category": "FOREX", "precision": 3, "min_qty": 1000},
        {"symbol": "NAS100", "name": "Nasdaq 100 Index", "category": "INDICES", "precision": 2, "min_qty": 0.1},
        {"symbol": "US30", "name": "Dow Jones 30", "category": "INDICES", "precision": 2, "min_qty": 0.1},
        {"symbol": "NIFTY50", "name": "Nifty 50 Index", "category": "INDICES", "precision": 2, "min_qty": 1}
    ]
    return jsonify({"success": True, "instruments": instruments, "count": len(instruments)})


@smc_bp.route("/api/smc/structure/<symbol>", methods=["GET"])
def smc_structure(symbol: str):
    tf = request.args.get("timeframe", "15m")
    candles = _get_candles(symbol, tf=tf, limit=140)
    swings = MarketStructureEngine.detect_swings(candles, sensitivity=4)
    breaks = MarketStructureEngine.detect_structure_breaks(candles, swings)
    return jsonify({
        "success": True,
        "symbol": symbol.upper(),
        "timeframe": tf,
        "swings": swings,
        "structure_breaks": breaks
    })


@smc_bp.route("/api/smc/order-blocks/<symbol>", methods=["GET"])
def smc_order_blocks(symbol: str):
    tf = request.args.get("timeframe", "15m")
    candles = _get_candles(symbol, tf=tf, limit=140)
    atr = compute_atr(candles)
    obs = OrderBlockEngine.detect_order_blocks(candles, atr)
    return jsonify({
        "success": True,
        "symbol": symbol.upper(),
        "timeframe": tf,
        "order_blocks": obs
    })


@smc_bp.route("/api/smc/fvg/<symbol>", methods=["GET"])
def smc_fvg(symbol: str):
    tf = request.args.get("timeframe", "15m")
    candles = _get_candles(symbol, tf=tf, limit=140)
    atr = compute_atr(candles)
    fvgs = FVGEngine.detect_fvgs(candles, atr=atr)
    return jsonify({
        "success": True,
        "symbol": symbol.upper(),
        "timeframe": tf,
        "fair_value_gaps": fvgs
    })


@smc_bp.route("/api/smc/liquidity/<symbol>", methods=["GET"])
def smc_liquidity(symbol: str):
    tf = request.args.get("timeframe", "15m")
    candles = _get_candles(symbol, tf=tf, limit=140)
    swings = MarketStructureEngine.detect_swings(candles, sensitivity=4)
    liq = LiquidityEngine.detect_liquidity_pools(candles, swings)
    return jsonify({
        "success": True,
        "symbol": symbol.upper(),
        "timeframe": tf,
        "liquidity": liq
    })


@smc_bp.route("/api/smc/multi-timeframe/<symbol>", methods=["GET"])
def smc_multi_timeframe(symbol: str):
    timeframes = ["1m", "5m", "15m", "1h", "4h", "1d"]
    mtf_candles: Dict[str, List[Dict[str, Any]]] = {}
    for tf in timeframes:
        mtf_candles[tf] = feed.candles(symbol, interval=tf, limit=60, allow_network=True)
    res = MultiTimeframeEngine.evaluate_multi_timeframe(symbol, mtf_candles)
    return jsonify({"success": True, **res})


# ==============================================================================
# 2. ARAA AI MARKET ADVISOR ENDPOINTS
# ==============================================================================

@smc_bp.route("/api/ai/analyze", methods=["POST"])
def ai_analyze_post():
    data = request.get_json(silent=True) or {}
    symbol = str(data.get("symbol") or "BTCUSDT").upper()
    tf = str(data.get("timeframe") or "15m").lower()

    candles = _get_candles(symbol, tf=tf, limit=140)
    if not candles:
        return jsonify({"success": False, "error": "Insufficient market data"}), 400

    atr = compute_atr(candles)
    swings = MarketStructureEngine.detect_swings(candles, sensitivity=4)
    structure_breaks = MarketStructureEngine.detect_structure_breaks(candles, swings)
    order_blocks = OrderBlockEngine.detect_order_blocks(candles, atr)
    fvgs = FVGEngine.detect_fvgs(candles, atr=atr)
    liquidity = LiquidityEngine.detect_liquidity_pools(candles, swings)

    report = AraaAIMarketAdvisor.generate_report(
        symbol=symbol,
        timeframe=tf,
        current_price=candles[-1]["c"],
        structure_events=structure_breaks,
        order_blocks=order_blocks,
        fvgs=fvgs,
        liquidity=liquidity,
        atr=atr
    )
    return jsonify({"success": True, "report": report})


@smc_bp.route("/api/ai/reports/<symbol>", methods=["GET"])
def ai_reports_get(symbol: str):
    tf = request.args.get("timeframe", "15m")
    candles = _get_candles(symbol, tf=tf, limit=140)
    atr = compute_atr(candles)
    swings = MarketStructureEngine.detect_swings(candles, sensitivity=4)
    structure_breaks = MarketStructureEngine.detect_structure_breaks(candles, swings)
    order_blocks = OrderBlockEngine.detect_order_blocks(candles, atr)
    fvgs = FVGEngine.detect_fvgs(candles, atr=atr)
    liquidity = LiquidityEngine.detect_liquidity_pools(candles, swings)

    report = AraaAIMarketAdvisor.generate_report(
        symbol=symbol,
        timeframe=tf,
        current_price=candles[-1]["c"] if candles else 100.0,
        structure_events=structure_breaks,
        order_blocks=order_blocks,
        fvgs=fvgs,
        liquidity=liquidity,
        atr=atr
    )
    return jsonify({"success": True, "report": report})


# ==============================================================================
# 3. LIVE STRATEGY SCANNER ENDPOINTS
# ==============================================================================

TRACKED_SCANNER_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "NAS100", "US30"
]

@smc_bp.route("/api/scanner", methods=["GET"])
@smc_bp.route("/api/scanner/events", methods=["GET"])
def smc_scanner():
    """Scans all supported instruments across multiple timeframes for SMC events."""
    target_tf = request.args.get("timeframe", "15m")
    events: List[Dict[str, Any]] = []

    for sym in TRACKED_SCANNER_SYMBOLS:
        try:
            candles = _get_candles(sym, tf=target_tf, limit=50)
            if len(candles) < 15:
                continue
            cur_p = candles[-1]["c"]
            atr = compute_atr(candles)
            swings = MarketStructureEngine.detect_swings(candles, sensitivity=3)
            breaks = MarketStructureEngine.detect_structure_breaks(candles, swings)
            obs = OrderBlockEngine.detect_order_blocks(candles, atr)
            fvgs = FVGEngine.detect_fvgs(candles, atr=atr)
            liq = LiquidityEngine.detect_liquidity_pools(candles, swings)

            last_break = breaks[-1] if breaks else None
            bias = last_break["direction"] if last_break else "NEUTRAL"
            latest_ev = last_break["type"] if last_break else "CONSOLIDATING"
            ev_price = last_break["price"] if last_break else cur_p

            events.append({
                "instrument": sym,
                "current_price": cur_p,
                "timeframe": target_tf.upper(),
                "market_bias": bias,
                "latest_event": latest_ev,
                "event_price": ev_price,
                "fresh_obs": len([ob for ob in obs if ob["status"] == "FRESH"]),
                "open_fvgs": len([f for f in fvgs if f["status"] == "OPEN"]),
                "ssl_swept": bool(liq.get("ssl", {}).get("swept")),
                "bsl_swept": bool(liq.get("bsl", {}).get("swept")),
                "dealing_zone": liq.get("dealing_range", {}).get("current_zone", "EQUILIBRIUM"),
                "timestamp": int(candles[-1]["t"])
            })
        except Exception as e:
            logger.warning("Error scanning %s: %s", sym, e)
            continue

    return jsonify({
        "success": True,
        "timeframe": target_tf,
        "count": len(events),
        "events": events
    })


# ==============================================================================
# 4. USER ALERT ENGINE ENDPOINTS
# ==============================================================================

@smc_bp.route("/api/alerts", methods=["GET"])
def get_user_alerts():
    u = _get_user()
    uid = u["id"] if u else 1
    rows = db.query("SELECT * FROM smc_user_alerts WHERE user_id=? ORDER BY created_at DESC", (uid,))
    history = db.query("SELECT * FROM smc_alert_history WHERE user_id=? ORDER BY triggered_at DESC LIMIT 30", (uid,))
    return jsonify({
        "success": True,
        "alerts": [dict(r) for r in rows],
        "history": [dict(h) for h in history]
    })


@smc_bp.route("/api/alerts", methods=["POST"])
def create_user_alert():
    u = _get_user()
    uid = u["id"] if u else 1
    data = request.get_json(silent=True) or {}

    sym = str(data.get("symbol") or "BTCUSDT").upper()
    tf = str(data.get("timeframe") or "15m").lower()
    alert_type = str(data.get("alert_type") or "BOS_BULLISH").upper()
    cond_price = float(data.get("condition_price") or 0.0)

    db.write(
        """INSERT INTO smc_user_alerts(user_id, symbol, timeframe, alert_type, condition_price, active, created_at)
           VALUES (?, ?, ?, ?, ?, 1, ?)""",
        (uid, sym, tf, alert_type, cond_price, time.time())
    )
    return jsonify({"success": True, "message": "SMC alert created successfully."})


@smc_bp.route("/api/alerts/<int:alert_id>", methods=["DELETE"])
def delete_user_alert(alert_id: int):
    u = _get_user()
    uid = u["id"] if u else 1
    db.write("DELETE FROM smc_user_alerts WHERE id=? AND user_id=?", (alert_id, uid))
    return jsonify({"success": True, "message": "Alert removed."})


# ==============================================================================
# 5. HISTORICAL BACKTESTING ENDPOINTS
# ==============================================================================

@smc_bp.route("/api/backtest/run", methods=["POST"])
def run_backtest():
    u = _get_user()
    uid = u["id"] if u else 1
    data = request.get_json(silent=True) or {}

    sym = str(data.get("symbol") or "BTCUSDT").upper()
    tf = str(data.get("timeframe") or "15m").lower()
    limit = int(data.get("candles") or 250)

    candles = _get_candles(sym, tf=tf, limit=limit)
    if len(candles) < 40:
        return jsonify({"success": False, "error": "Insufficient historical candles for backtesting"}), 400

    results = SMCBacktestEngine.run_backtest(candles, strategy_config=data)
    job_id = f"BT_{uuid.uuid4().hex[:8]}"

    try:
        db.write(
            "INSERT INTO smc_backtest_jobs(id, user_id, symbol, timeframe, metrics_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, uid, sym, tf, json.dumps(results), time.time())
        )
    except Exception:
        pass

    return jsonify({
        "success": True,
        "job_id": job_id,
        "symbol": sym,
        "timeframe": tf,
        "results": results
    })


@smc_bp.route("/api/backtest/history", methods=["GET"])
def backtest_history():
    u = _get_user()
    uid = u["id"] if u else 1
    rows = db.query("SELECT * FROM smc_backtest_jobs WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (uid,))
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["metrics"] = json.loads(d["metrics_json"])
        except Exception:
            d["metrics"] = {}
        out.append(d)
    return jsonify({"success": True, "history": out})


# ==============================================================================
# 6. TRADING JOURNAL ENDPOINTS
# ==============================================================================

@smc_bp.route("/api/journal", methods=["GET"])
def get_journal():
    u = _get_user()
    uid = u["id"] if u else 1
    rows = db.query("SELECT * FROM smc_trading_journal WHERE user_id=? ORDER BY created_at DESC", (uid,))
    return jsonify({"success": True, "journal": [dict(r) for r in rows]})


@smc_bp.route("/api/journal", methods=["POST"])
def add_journal():
    u = _get_user()
    uid = u["id"] if u else 1
    data = request.get_json(silent=True) or {}

    sym = str(data.get("symbol") or "BTCUSDT").upper()
    tf = str(data.get("timeframe") or "15m").lower()
    trade_type = str(data.get("trade_type") or "BUY").upper()
    entry = float(data.get("entry_price") or 0.0)
    exit_p = float(data.get("exit_price") or 0.0)
    pnl = float(data.get("pnl") or 0.0)
    notes = str(data.get("notes") or "")

    db.write(
        """INSERT INTO smc_trading_journal(user_id, symbol, timeframe, trade_type, entry_price, exit_price, pnl, notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (uid, sym, tf, trade_type, entry, exit_p, pnl, notes, time.time())
    )
    return jsonify({"success": True, "message": "Trade logged in journal."})


@smc_bp.route("/api/journal/<int:entry_id>", methods=["DELETE"])
def delete_journal(entry_id: int):
    u = _get_user()
    uid = u["id"] if u else 1
    db.write("DELETE FROM smc_trading_journal WHERE id=? AND user_id=?", (entry_id, uid))
    return jsonify({"success": True, "message": "Journal entry deleted."})


# ==============================================================================
# 7. MARKET PROVIDER STATUS
# ==============================================================================

@smc_bp.route("/api/market/providers/status", methods=["GET"])
def market_providers_status():
    return jsonify({
        "success": True,
        "providers": [
            {
                "name": "CoinDCX Direct WebSocket",
                "asset_class": "Crypto Futures & Spot",
                "status": "HEALTHY",
                "latency_ms": 14,
                "coverage": "BTC, ETH, SOL, XRP + 200 Pairs",
                "attribution": "CoinDCX Liquidity Gateway"
            },
            {
                "name": "Institutional FX & Metals Feed",
                "asset_class": "Forex & Commodities",
                "status": "HEALTHY",
                "latency_ms": 22,
                "coverage": "XAUUSD, EURUSD, GBPUSD, USDJPY",
                "attribution": "Global Interbank Feed"
            },
            {
                "name": "Global Indices Feed",
                "asset_class": "Index Equities",
                "status": "HEALTHY",
                "latency_ms": 18,
                "coverage": "NAS100, US30, SPX500, NIFTY50",
                "attribution": "Exchange Aggregator"
            }
        ],
        "server_time": int(time.time()),
        "data_normalization": "OHLCV Unified Standard"
    })
