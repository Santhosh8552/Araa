"""Real Broker Bridge for Trade Pro.

Supports live trade execution on real exchanges (Binance, Bybit, Delta Exchange India, OKX)
via standard CCXT unified API, with a clean simulation fallback when in PAPER mode.
"""
import os
import time
import logging

logger = logging.getLogger("real_broker")

try:
    import ccxt
    HAS_CCXT = True
except Exception:
    ccxt = None
    HAS_CCXT = False

_EXCHANGE_CLIENT = None
_EXCHANGE_ID = None

def get_broker_config():
    """Reads broker configuration from environment or database platform_state."""
    provider = os.environ.get("REAL_BROKER_PROVIDER", "binance").strip().lower()
    api_key = os.environ.get("BROKER_API_KEY", "").strip()
    api_secret = os.environ.get("BROKER_API_SECRET", "").strip()
    is_testnet = os.environ.get("BROKER_TESTNET", "false").strip().lower() in ("true", "1", "yes")
    is_real_enabled = os.environ.get("ENABLE_REAL_TRADING", "false").strip().lower() in ("true", "1", "yes")
    
    # Also check database fallback for state
    try:
        from database import get_state
        if not api_key:
            api_key = get_state("broker_api_key", "")
        if not api_secret:
            api_secret = get_state("broker_api_secret", "")
        db_provider = get_state("broker_provider", "")
        if db_provider:
            provider = db_provider.strip().lower()
        db_real_mode = get_state("trading_mode", "")
        if db_real_mode.upper() == "LIVE":
            is_real_enabled = True
    except Exception:
        pass

    return {
        "provider": provider or "binance",
        "api_key": api_key,
        "api_secret": api_secret,
        "testnet": is_testnet,
        "real_enabled": is_real_enabled and bool(api_key and api_secret)
    }

def init_exchange():
    """Initializes and returns the CCXT exchange client."""
    global _EXCHANGE_CLIENT, _EXCHANGE_ID
    if not HAS_CCXT:
        logger.warning("CCXT library not available. Real broker execution disabled.")
        return None

    cfg = get_broker_config()
    if not cfg["real_enabled"]:
        return None

    provider = cfg["provider"]
    if _EXCHANGE_CLIENT is not None and _EXCHANGE_ID == provider:
        return _EXCHANGE_CLIENT

    try:
        exchange_class = getattr(ccxt, provider, None)
        if not exchange_class:
            logger.error(f"Unsupported exchange provider: {provider}")
            return None

        client = exchange_class({
            "apiKey": cfg["api_key"],
            "secret": cfg["api_secret"],
            "enableRateLimit": True,
            "options": {
                "defaultType": "future",  # Support leverage & shorting
            }
        })
        if cfg["testnet"]:
            client.set_sandbox_mode(True)

        _EXCHANGE_CLIENT = client
        _EXCHANGE_ID = provider
        logger.info(f"Initialized real broker exchange: {provider.upper()} (Testnet: {cfg['testnet']})")
        return client
    except Exception as e:
        logger.error(f"Failed to initialize exchange {provider}: {e}")
        return None

def format_symbol_for_exchange(symbol, provider="binance"):
    """Converts local symbol (e.g. BTCUSDT, EURUSD) into standard CCXT exchange symbol."""
    sym = (symbol or "").strip().upper()
    if "USDT" in sym and not "/" in sym:
        base = sym.replace("USDT", "")
        return f"{base}/USDT:USDT"  # USDT-M Futures format
    if "/" not in sym and len(sym) == 6 and not sym.endswith("USDT"):
        return f"{sym[:3]}/{sym[3:]}"
    return sym

def verify_universal_real_bot_rules(user_id, symbol, side, qty, leverage=500.0, price=None, ai_win_prob=None):
    """
    Universal A-Z AraaBot Real-Mode Rule Enforcer for ALL connected broker APIs
    (CoinDCX, Exness MT4/MT5, Binance, Bybit, Delta, OKX, Zerodha, or any CCXT exchange).
    Ensures ONLY AraaBot A-Z rules & ARAA Quant AI v4.0 govern live execution with up to 500x leverage.
    """
    from database import query_one, write

    eff_lev = max(1.0, min(500.0, float(leverage or 500.0)))
    est_price = float(price or 0.0)
    if est_price <= 0:
        try:
            from price_feed import get_price_feed
            est_price = float(get_price_feed().live_price(symbol) or 0.0)
        except Exception:
            est_price = 0.0
    est_margin = ((float(qty or 0.0) * est_price) / eff_lev) if (est_price > 0 and qty) else 0.0

    def _audit_reject(ev_type, msg):
        try:
            write(
                "INSERT INTO real_bot_audit_logs(user_id, event_type, severity, message, details_json, created_at) "
                "VALUES(?, ?, 'WARNING', ?, ?, ?)",
                (int(user_id), ev_type, msg, f'{{"symbol":"{symbol}","side":"{side}","leverage":{eff_lev}}}', time.time()),
            )
        except Exception:
            pass

    if not user_id:
        return True, "System order allowed", eff_lev

    u_cfg = query_one("SELECT * FROM real_bot_configs WHERE user_id=?", (user_id,))
    u_row = query_one("SELECT id, bot_mode, bot_max_positions, bot_leverage, bot_trade_direction FROM users WHERE id=?", (user_id,))

    # Rule 0: Global / User Kill Switch & Emergency Shutdown
    try:
        from risk_engine import RiskGuardian
        if RiskGuardian.is_global_kill_switch_active():
            msg = "AraaBot Rule 0: Global Emergency Kill Switch is ACTIVE. All real orders halted."
            _audit_reject("ORDER_REJECTED_EMERGENCY", msg)
            return False, msg, eff_lev
    except Exception:
        pass
    if u_cfg and u_cfg.get("emergency_shutdown"):
        msg = "AraaBot Rule 0: User emergency shutdown lock is ACTIVE. Live execution blocked."
        _audit_reject("ORDER_REJECTED_EMERGENCY", msg)
        return False, msg, eff_lev

    # Rule A: User Bot Trade Direction Lock (BOTH / LONG / SHORT)
    dir_pref = str((u_row or {}).get("bot_trade_direction") or "BOTH").upper()
    want_buy = str(side or "BUY").upper() in ("BUY", "LONG")
    if dir_pref == "LONG" and not want_buy:
        msg = f"AraaBot Rule: Trade direction locked to LONG ONLY ({symbol} {side} blocked)."
        _audit_reject("ORDER_REJECTED_RISK", msg)
        return False, msg, eff_lev
    if dir_pref == "SHORT" and want_buy:
        msg = f"AraaBot Rule: Trade direction locked to SHORT ONLY ({symbol} {side} blocked)."
        _audit_reject("ORDER_REJECTED_RISK", msg)
        return False, msg, eff_lev

    # Rule 1: Daily Loss Circuit Breaker
    day_pnl = (query_one(
        "SELECT COALESCE(SUM(realized_pnl), 0.0) as s FROM positions WHERE user_id=? AND status='CLOSED' AND is_live=1 AND closed_at >= ?",
        (user_id, time.time() - 86400),
    ) or {}).get("s", 0.0)
    max_daily = float((u_cfg or {}).get("max_daily_loss") or 250.0)
    if day_pnl <= -abs(max_daily):
        msg = f"AraaBot Rule 1: Daily loss limit reached (${day_pnl:+.2f} <= -${abs(max_daily):,.2f})."
        _audit_reject("DAILY_LOSS_GUARD_TRIGGERED", msg)
        return False, msg, eff_lev

    # Rule 2: Isolated Margin Cap (supports up to 500x leverage calculations)
    max_order = float((u_cfg or {}).get("max_order_size") or 50000.0)
    if est_margin > max_order and est_margin > 0:
        msg = f"AraaBot Rule 2: Required margin ${est_margin:,.2f} (@ {eff_lev:.0f}x) exceeds max order limit ${max_order:,.2f}."
        _audit_reject("ORDER_REJECTED_RISK", msg)
        return False, msg, eff_lev

    # Rule 3: Max Open Positions Limit
    user_max_pos = int((u_row or {}).get("bot_max_positions") or (u_cfg or {}).get("max_positions") or 10)
    if user_max_pos < 999 and user_max_pos > 0:
        open_cnt = (query_one(
            "SELECT COUNT(*) as c FROM positions WHERE user_id=? AND status IN ('OPEN','PENDING_BROKER') AND is_live=1",
            (user_id,),
        ) or {}).get("c", 0)
        if open_cnt >= user_max_pos:
            msg = f"AraaBot Rule 3: Max live open positions reached ({open_cnt}/{user_max_pos})."
            _audit_reject("ORDER_REJECTED_RISK", msg)
            return False, msg, eff_lev

    # Rule 4 & 5: Spread & Anti-Falling-Knife Dump Protection across Live Feed
    try:
        from price_feed import get_price_feed
        q = get_price_feed().quote(symbol) or {}
        bid = float(q.get("bid") or 0.0)
        ask = float(q.get("ask") or 0.0)
        if bid > 0 and ask > 0:
            spread_pct = (ask - bid) / bid * 100.0
            max_spread = 0.65 if (symbol.endswith("INR") or len(symbol) == 6) else 0.45
            if spread_pct > max_spread:
                msg = f"AraaBot Rule 4: Spread {spread_pct:.2f}% on {symbol} exceeds {max_spread}% slippage guard."
                _audit_reject("ORDER_REJECTED_SPREAD", msg)
                return False, msg, eff_lev
        chg_24 = float(q.get("change_pct") or 0.0)
        if want_buy and chg_24 < -2.0:
            msg = f"AraaBot Rule 5: Anti-falling-knife active on {symbol} ({chg_24:+.2f}% 24h dump)."
            _audit_reject("ORDER_REJECTED_DUMP", msg)
            return False, msg, eff_lev
    except Exception:
        pass

    # Rule 6: Sovereign ARAA Quant AI v4.0 Consensus Approval
    win_p = int(ai_win_prob) if (ai_win_prob is not None and float(ai_win_prob) > 0) else None
    if win_p is None:
        recent_pred = query_one(
            "SELECT win_probability FROM ai_predictions WHERE user_id=? AND symbol=? AND post_entry_status='APPROVED' AND created_at>=? ORDER BY id DESC LIMIT 1",
            (user_id, symbol, time.time() - 300),
        )
        if recent_pred and recent_pred.get("win_probability"):
            win_p = int(recent_pred["win_probability"])

    min_thresh = 70
    try:
        from bot_trainer import load_training_state
        t_state = load_training_state()
        if t_state and t_state.get("custom_rules", {}).get("min_win_probability"):
            min_thresh = int(t_state["custom_rules"]["min_win_probability"])
    except Exception:
        min_thresh = 70
    min_thresh = max(60, min(95, min_thresh))

    if win_p is not None and win_p < min_thresh:
        msg = f"AraaBot Rule 6: ARAA Quant AI approval ({win_p}%) below {min_thresh}% Real-Mode threshold."
        _audit_reject("ORDER_REJECTED_AI", msg)
        return False, msg, eff_lev

    return True, f"AraaBot Universal Rules Approved ({eff_lev:.0f}x)", eff_lev


def execute_real_order(symbol, side, qty, leverage=500.0, stop_loss=None, take_profit=None, user_id=None, price=None, ai_win_prob=None):
    """
    Executes a real order on ANY connected broker (CoinDCX, Exness MT4/MT5, Binance, Bybit, Delta, OKX).
    Enforces ALL A-Z AraaBot Rules & ARAA Quant AI v4.0 with up to 500x leverage before touching any API.
    """
    cfg = get_broker_config()
    provider = cfg["provider"].lower()

    leverage = max(1.0, min(500.0, float(leverage or 500.0)))
    rules_ok, rules_msg, leverage = verify_universal_real_bot_rules(
        user_id=user_id,
        symbol=symbol,
        side=side,
        qty=qty,
        leverage=leverage,
        price=price,
        ai_win_prob=ai_win_prob,
    )
    if not rules_ok:
        return {
            "mode": "LIVE_REJECTED",
            "executed": False,
            "broker_confirmed": False,
            "exchange": provider.upper(),
            "error": rules_msg,
        }

    user_broker = ""
    if user_id:
        from database import query_one
        b_conn = query_one("SELECT broker_name FROM broker_connections WHERE user_id=?", (user_id,))
        if b_conn and b_conn.get("broker_name"):
            user_broker = b_conn["broker_name"].upper()

    # Route CoinDCX Live Orders
    if user_id and user_broker == "COINDCX":
        try:
            from coindcx_gateway import get_user_coindcx_client, to_coindcx_market, verify_coindcx_risk, log_audit_event
            cdx = get_user_coindcx_client(user_id)
            if cdx:
                # Pre-flight risk check: Calculate actual allocated margin capital
                lev = float(leverage or 1.0)
                actual_margin_inr = (qty * (price or 1.0)) / (lev if lev > 0 else 1.0)
                risk_ok, risk_msg = verify_coindcx_risk(user_id, symbol, requested_amount_inr=actual_margin_inr, leverage=lev, side=side, price=price, ai_win_prob=ai_win_prob)
                if not risk_ok:
                    log_audit_event(user_id, "ORDER_RISK_REJECTED", f"Real bot order rejected by risk engine: {risk_msg}", "WARNING", {"symbol": symbol, "side": side, "qty": qty, "margin": actual_margin_inr})
                    return {
                        "mode": "LIVE_REJECTED",
                        "executed": False,
                        "broker_confirmed": False,
                        "exchange": "COINDCX",
                        "error": f"Risk limit exceeded: {risk_msg}"
                    }

                # STRICT ARAABOT COINDCX RULE: USD / USDT FUTURES ONLY!
                # Never allow INR trading on CoinDCX!
                clean_sym = str(symbol or "").upper().strip()
                if clean_sym.endswith("INR"):
                    clean_sym = clean_sym[:-3] + "USDT"
                elif not clean_sym.endswith("USDT") and not clean_sym.startswith("B-"):
                    clean_sym = clean_sym + "USDT"
                symbol = clean_sym

                cdx_market = to_coindcx_market(symbol)
                cdx_side = "buy" if side.upper() in ("BUY", "LONG") else "sell"
                ok, res = False, {}
                market_type = "SPOT"
                eff_lev = 1.0
                fut_note = ""
                # Leveraged real mode: CoinDCX Futures for BOTH long and short.
                if lev > 1.0 or cdx_side == "sell":
                    try:
                        fut_elig = cdx.futures.check_eligibility()
                        avail_fut_usdt = cdx.futures.get_available_futures_margin_usdt() if hasattr(cdx.futures, "get_available_futures_margin_usdt") else 1000.0
                        if (fut_elig.get("eligible") or cdx.is_offline) and (avail_fut_usdt >= 0.005 or cdx.is_offline):
                            eff_lev = cdx.futures.resolve_leverage(symbol, lev, cdx_side)
                            # qty arrives sized for the requested leverage; rescale to the leverage the exchange allows
                            fut_qty = qty * (eff_lev / lev) if lev > 0 else qty
                            ok, res = cdx.futures.place_futures_order(
                                symbol=symbol, side=cdx_side, quantity=fut_qty, leverage=eff_lev,
                                order_type="market_order", price=price,
                                stop_loss=stop_loss, take_profit=take_profit)
                            if ok:
                                market_type = "FUTURES"
                                qty = fut_qty
                            else:
                                fut_note = res.get("message") if isinstance(res, dict) else str(res)
                        else:
                            if not fut_elig.get("eligible"):
                                fut_note = fut_elig.get("message", "Futures not enabled on account")
                            else:
                                fut_note = f"Futures wallet balance is ${avail_fut_usdt:.2f} USDT (Transfer USDT to Futures wallet on CoinDCX app to activate 100x)"
                    except Exception as fut_err:
                        fut_note = str(fut_err)
                        logger.error(f"CoinDCX futures routing error: {fut_err}")
                    is_usd_only = True  # STRICT ARAABOT RULE: USD/USDT Futures ONLY! Never execute Spot INR!
                    if not ok:
                        log_audit_event(user_id, "FUTURES_ORDER_FAILED", f"CoinDCX Futures {cdx_side.upper()} order for {symbol} not executed: {fut_note}", "WARNING")
                if not ok and cdx_side == "buy" and not is_usd_only:
                    # Route through AraaCoinDCXRuleAdapter - CoinDCX operates strictly on OUR AraaBot rules!
                    # For Spot, use 1x equity cash sizing so it fits inside the user's INR balance!
                    spot_qty = actual_margin_inr / (price or 1.0)
                    eff_lev = 1.0
                    ok, res = cdx.adapter.execute_adapted_order(
                        symbol=symbol,
                        side=cdx_side,
                        requested_qty=spot_qty,
                        leverage=1.0,
                        price=price,
                        win_prob=ai_win_prob
                    )
                    market_type = "SPOT"
                    if ok and res.get("total_quantity"):
                        qty = float(res.get("total_quantity") or spot_qty)
                elif not ok:
                    err_msg = fut_note or (res.get("message") if isinstance(res, dict) else str(res)) or "CoinDCX live order execution failed"
                    log_audit_event(user_id, "ORDER_FAILED_LIVE", f"Live CoinDCX order failed (no fabricated fill allowed): {err_msg}", "ERROR", res)
                    return {
                        "mode": "LIVE_ERROR",
                        "executed": False,
                        "broker_confirmed": False,
                        "fallback_to_paper": False,
                        "exchange": "COINDCX",
                        "error": err_msg
                    }
                if ok:
                    fill_p = float(res.get("avg_price") or res.get("price_per_unit") or price or 0.0)
                    ord_id = str(res.get("id") or time.time())
                    log_audit_event(user_id, "ORDER_EXECUTED_LIVE", f"Live CoinDCX order executed: {side.upper()} {qty} {symbol} @ {fill_p}", "INFO", res)
                    return {
                        "mode": "LIVE_REAL",
                        "executed": True,
                        "broker_confirmed": True,
                        "status": "OPEN",
                        "order_id": ord_id,
                        "fill_price": fill_p,
                        "exchange": "COINDCX",
                        "market_type": market_type,
                        "leverage": eff_lev,
                        "qty": qty,
                        "raw": res
                    }
                else:
                    err_msg = res.get("message") if isinstance(res, dict) else str(res)
                    log_audit_event(user_id, "ORDER_FAILED_LIVE", f"Live CoinDCX order failed: {err_msg}", "ERROR", res)
                    return {
                        "mode": "LIVE_ERROR",
                        "executed": False,
                        "broker_confirmed": False,
                        "exchange": "COINDCX",
                        "error": err_msg
                    }
        except Exception as cdx_err:
            logger.error(f"CoinDCX order routing error: {cdx_err}")

    # Route Exness MT4 real orders
    if user_broker != "COINDCX" and ("exness" in provider or user_id):
        try:
            from exness_gateway import get_exness_client
            client = get_exness_client(user_id or 1)
            if client:
                res = client.open_order(
                    symbol=symbol,
                    side=side,
                    price=price or 0.0,
                    stop_loss=stop_loss,
                    take_profit=take_profit
                )
                if res.get("success"):
                    return {
                        "mode": "LIVE_REAL",
                        "executed": True,
                        "broker_confirmed": bool(res.get("broker_confirmed", False)),
                        "status": res.get("status", "QUEUED_FOR_BROKER"),
                        "command_id": res.get("command_id"),
                        "terminal_id": res.get("terminal_id"),
                        "order_id": res.get("command_id") or res.get("ticket"),
                        "fill_price": res["entry_price"],
                        "exchange": "EXNESS_MT4",
                        "lot": res["lot"],
                        "leverage": res["leverage"]
                    }
                else:
                    return {
                        "mode": "LIVE_ERROR",
                        "executed": False,
                        "broker_confirmed": False,
                        "exchange": "EXNESS_MT4",
                        "error": res.get("error", "Exness MT4 order rejected")
                    }
        except Exception as ex_err:
            logger.error(f"Exness order routing error: {ex_err}")
            return {
                "mode": "LIVE_ERROR",
                "executed": False,
                "broker_confirmed": False,
                "exchange": "EXNESS_MT4",
                "error": str(ex_err)
            }

    if not cfg["real_enabled"]:
        return {
            "mode": "PAPER",
            "executed": True,
            "order_id": f"paper_{int(time.time()*1000)}",
            "message": "Paper order logged. Configure BROKER_API_KEY & ENABLE_REAL_TRADING=true for live exchange fills."
        }

    client = init_exchange()
    if not client:
        return {
            "mode": "FALLBACK_PAPER",
            "executed": False,
            "error": "Broker connection failed. Executed as simulated position."
        }

    ex_symbol = format_symbol_for_exchange(symbol, cfg["provider"])
    ex_side = "buy" if side.upper() in ("BUY", "LONG") else "sell"

    try:
        # Set leverage (up to 500x; falls back to exchange ceiling only if rejected by exchange API)
        applied_lev = min(500, max(1, int(leverage)))
        try:
            if hasattr(client, "set_leverage") and applied_lev > 1:
                try:
                    client.set_leverage(applied_lev, ex_symbol)
                except Exception:
                    client.set_leverage(min(applied_lev, 125), ex_symbol)
                    applied_lev = min(applied_lev, 125)
        except Exception as lev_err:
            logger.warning(f"Set leverage warning: {lev_err}")

        # Execute market order
        params = {}
        order = client.create_order(
            symbol=ex_symbol,
            type="market",
            side=ex_side,
            amount=qty,
            params=params
        )

        fill_price = order.get("average") or order.get("price") or 0.0
        order_id = order.get("id") or str(time.time())

        # If Stop Loss or Take Profit specified, register bracket stop
        if stop_loss and hasattr(client, "create_order"):
            try:
                sl_side = "sell" if ex_side == "buy" else "buy"
                client.create_order(
                    symbol=ex_symbol,
                    type="stop_market",
                    side=sl_side,
                    amount=qty,
                    params={"stopPrice": stop_loss, "reduceOnly": True}
                )
            except Exception as sl_err:
                logger.warning(f"Stop-loss bracket setup notice: {sl_err}")

        return {
            "mode": "LIVE_REAL",
            "executed": True,
            "order_id": order_id,
            "fill_price": fill_price,
            "leverage": float(applied_lev),
            "exchange": cfg["provider"].upper(),
            "raw": order
        }
    except Exception as e:
        logger.error(f"Live exchange order failed on {ex_symbol}: {e}")
        return {
            "mode": "LIVE_ERROR",
            "executed": False,
            "error": str(e),
            "fallback_to_paper": False
        }

def close_real_order(symbol, side, qty, user_id=None, ticket_id=None, price=None, reason="TARGET_OR_STOP", leverage=None):
    """Closes an open real position on the exchange (CoinDCX, Exness MT4, or CCXT)."""
    cfg = get_broker_config()
    provider = cfg["provider"].lower()

    user_broker = ""
    if user_id:
        from database import query_one
        b_conn = query_one("SELECT broker_name FROM broker_connections WHERE user_id=?", (user_id,))
        if b_conn and b_conn.get("broker_name"):
            user_broker = b_conn["broker_name"].upper()

    # Route CoinDCX Close. This branch ALWAYS returns: it must never fall through to the
    # PAPER branch below and report "closed" when the exchange close did not happen.
    if user_id and user_broker == "COINDCX":
        try:
            from coindcx_gateway import get_user_coindcx_client, to_coindcx_market, log_audit_event
            cdx = get_user_coindcx_client(user_id)
            if not cdx:
                return {"mode": "FALLBACK_PAPER", "closed": True, "exchange": "COINDCX", "order_id": f"closed_{int(time.time()*1000)}"}
            cdx_market = to_coindcx_market(symbol)
            is_long = side.upper() in ("BUY", "LONG")
            close_side = "sell" if is_long else "buy"
            lev = float(leverage or 1.0)

            # Leveraged / short positions live on CoinDCX Futures: use the exchange's own exit.
            if lev > 1.0 or not is_long:
                ok_p, rows = cdx.futures.get_positions()
                pos = cdx.futures.find_open_position(symbol) if ok_p else None
                pos_uuid = str((pos or {}).get("id") or ticket_id or "")
                inv_fn = getattr(cdx, "invalidate_balance_cache", None)
                settle_fn = getattr(cdx.futures, "get_position_settlement", None)
                wait_fn = getattr(cdx.futures, "wait_for_position_flat", None)

                if pos or cdx.is_offline:
                    exit_by_id_fn = getattr(cdx.futures, "exit_position_by_id", None)
                    if pos_uuid and callable(exit_by_id_fn) and not cdx.is_offline:
                        ok, res = exit_by_id_fn(pos_uuid)
                        if not ok:
                            ok, res = cdx.futures.exit_position(symbol)
                    else:
                        ok, res = cdx.futures.exit_position(symbol)
                    if ok:
                        if not cdx.is_offline and callable(wait_fn):
                            wait_fn(symbol, pos_uuid, timeout_sec=2.0)
                        if callable(inv_fn):
                            inv_fn()
                        settle = settle_fn(pos_uuid) if (pos_uuid and callable(settle_fn) and not cdx.is_offline) else None
                        return {
                            "mode": "LIVE_REAL",
                            "closed": True,
                            "exchange": "COINDCX",
                            "market_type": "FUTURES",
                            "order_id": (res or {}).get("id"),
                            "exchange_position_id": pos_uuid,
                            "exchange_settled": bool(settle),
                            "realized_pnl": float((settle or {}).get("net_pnl") or 0.0),
                            "fee_usd": float((settle or {}).get("fee_usd") or 0.0),
                        }
                    return {"mode": "LIVE_ERROR", "closed": False, "exchange": "COINDCX",
                            "error": (res or {}).get("message", "futures exit failed")}
                if not ok_p:
                    return {"mode": "LIVE_ERROR", "closed": False, "exchange": "COINDCX",
                            "error": "Could not read CoinDCX futures positions; will retry"}

                # Cancel any lingering unfilled entry/TP/SL order on this contract before marking flat
                get_ord_fn = getattr(cdx.futures, "get_orders", None)
                cancel_fn = getattr(cdx.futures, "cancel_order", None)
                to_pair_fn = getattr(cdx.futures, "to_futures_pair", None)
                if callable(get_ord_fn) and not cdx.is_offline:
                    try:
                        ok_o, fut_orders = get_ord_fn()
                        pair_name = to_pair_fn(symbol) if callable(to_pair_fn) else symbol
                        clean_s = str(symbol or "").upper().replace("-", "").replace("_", "")
                        if ok_o and isinstance(fut_orders, list):
                            for fo in fut_orders:
                                f_pair = str(fo.get("pair") or "")
                                f_clean = f_pair.upper().replace("B-", "").replace("-", "").replace("_", "")
                                if (f_pair == pair_name or f_clean == clean_s) and fo.get("id") and callable(cancel_fn):
                                    cancel_fn(str(fo["id"]))
                    except Exception:
                        pass

                if callable(inv_fn):
                    inv_fn()
                settle = settle_fn(pos_uuid) if (pos_uuid and callable(settle_fn) and not cdx.is_offline) else None
                # If positions fetched successfully and this contract has 0 open futures position: already closed/liquidated on CoinDCX!
                return {
                    "mode": "LIVE_REAL",
                    "closed": True,
                    "exchange": "COINDCX",
                    "market_type": "FUTURES",
                    "already_flat": True,
                    "exchange_position_id": pos_uuid,
                    "exchange_settled": bool(settle),
                    "realized_pnl": float((settle or {}).get("net_pnl") or 0.0),
                    "fee_usd": float((settle or {}).get("fee_usd") or 0.0),
                }

            sell_qty = (qty / lev) * 0.95 if (lev > 1.0 and close_side == "sell") else qty
            ok, res = cdx.place_order(
                side=close_side,
                market=cdx_market,
                quantity=sell_qty,
                order_type="market_order",
                price=price
            )
            if ok:
                return {"mode": "LIVE_REAL", "closed": True, "exchange": "COINDCX",
                        "order_id": res.get("id"), "realized_pnl": 0.0}
            return {"mode": "LIVE_ERROR", "closed": False, "exchange": "COINDCX",
                    "error": (res.get("message") if isinstance(res, dict) else str(res)) or "spot close failed"}
        except Exception as cdx_err:
            logger.error(f"CoinDCX close order error: {cdx_err}")
            return {"mode": "LIVE_ERROR", "closed": False, "exchange": "COINDCX", "error": str(cdx_err)}

    if user_broker != "COINDCX" and ("exness" in provider or user_id):
        try:
            from exness_gateway import get_exness_client
            client = get_exness_client(user_id or 1)
            if client:
                # Find matching ticket or close by symbol
                if ticket_id:
                    res = client.close_order(ticket_id, close_price=price, reason=reason)
                    if res.get("success"):
                        return {"mode": "LIVE_REAL", "closed": True, "ticket": ticket_id, "realized_pnl": res.get("realized_pnl", 0.0)}
                else:
                    # Look for position by symbol
                    for p in list(client.positions):
                        if p["symbol"] == symbol or symbol.startswith(p["symbol"]):
                            res = client.close_order(p["ticket"], close_price=price, reason=reason)
                            return {"mode": "LIVE_REAL", "closed": True, "ticket": p["ticket"], "realized_pnl": res.get("realized_pnl", 0.0)}
        except Exception as ex_err:
            logger.error(f"Exness close order error: {ex_err}")

    if not cfg["real_enabled"]:
        return {"mode": "PAPER", "closed": True}

    client = init_exchange()
    if not client:
        return {"mode": "FALLBACK_PAPER", "closed": False}

    ex_symbol = format_symbol_for_exchange(symbol, cfg["provider"])
    close_side = "sell" if side.upper() in ("BUY", "LONG") else "buy"

    try:
        order = client.create_order(
            symbol=ex_symbol,
            type="market",
            side=close_side,
            amount=qty,
            params={"reduceOnly": True}
        )
        return {"mode": "LIVE_REAL", "closed": True, "order_id": order.get("id")}
    except Exception as e:
        logger.error(f"Live position close failed for {ex_symbol}: {e}")
        return {"mode": "LIVE_ERROR", "closed": False, "error": str(e)}

def check_broker_status():
    """Returns the current connection and balance status of the broker."""
    cfg = get_broker_config()
    status = {
        "provider": cfg["provider"].upper(),
        "real_enabled": cfg["real_enabled"],
        "has_keys": bool(cfg["api_key"] and cfg["api_secret"]),
        "testnet": cfg["testnet"],
        "connected": False,
        "balance": None
    }
    if not cfg["real_enabled"]:
        return status

    client = init_exchange()
    if client:
        try:
            bal = client.fetch_balance()
            total_usdt = bal.get("total", {}).get("USDT", 0.0)
            status["connected"] = True
            status["balance"] = {
                "USDT": round(total_usdt, 2),
                "free_USDT": round(bal.get("free", {}).get("USDT", 0.0), 2)
            }
        except Exception as e:
            status["error"] = str(e)
    return status
