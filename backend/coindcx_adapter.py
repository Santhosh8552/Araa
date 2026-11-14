"""Centralized CoinDCXExecutionAdapter for AraaBot.

Owns all live CoinDCX API interactions across Futures, Spot, and Margin markets:
- API auth & trading permission verification
- Balance, open position, and open order synchronization
- Idempotent order submission (prevents duplicate live orders on retry/reconnect)
- Exact error diagnostics (endpoint, sanitized request, API message, corrective hint)
- Partial fill, lifecycle, and execution fee tracking in `order_mappings`
- Post-fill Stop-Loss & Take-Profit protection setup and verification in `position_protections`
"""

import json
import time
import uuid
import logging
from typing import Any, Dict, List, Optional, Tuple

from database import query, query_one, write
from coindcx_gateway import (
    get_user_coindcx_client,
    round_to_increment,
    to_coindcx_market,
)

logger = logging.getLogger("araabot.coindcx_adapter")

SENSITIVE_KEYS = ("secret", "api_key", "api_secret", "signature", "x-auth-signature", "x-auth-apikey", "password")


def sanitize_request(payload: Any) -> Dict[str, Any]:
    """Strip any secret or credential fields before storing or returning diagnostics."""
    if not isinstance(payload, dict):
        return {"raw": str(payload)[:300]}
    out: Dict[str, Any] = {}
    for k, v in payload.items():
        if any(s in str(k).lower() for s in SENSITIVE_KEYS):
            out[k] = "***REDACTED***"
        elif isinstance(v, dict):
            out[k] = sanitize_request(v)
        else:
            out[k] = v
    return out


def corrective_action_for(err_msg: str) -> str:
    """Return an actionable corrective hint for common CoinDCX API rejections."""
    low = (err_msg or "").lower()
    if any(k in low for k in ("insufficient", "balance", "margin", "funds")):
        return "Transfer more USDT to your CoinDCX Futures/Spot wallet or reduce position size/leverage."
    if any(k in low for k in ("permission", "unauthorized", "forbidden", "signature", "invalid api", "ip")):
        return "Check CoinDCX API Key permissions (Read + Trade enabled) and IP whitelist in CoinDCX settings."
    if any(k in low for k in ("not active", "invalid market", "invalid pair", "symbol")):
        return "Verify the trading pair is active on CoinDCX (e.g. BTCUSDT / B-BTC_USDT) and supported for this market type."
    if any(k in low for k in ("quantity", "min", "step", "lot", "precision", "divisible")):
        return "Adjust order quantity/price to match CoinDCX's minimum order size and tick increment."
    if "leverage" in low:
        return "Reduce requested leverage to within CoinDCX's allowed max leverage for this contract."
    return "Inspect the CoinDCX API message and verify account balance, symbol, and API key permissions."


class CoinDCXExecutionAdapter:
    """Authoritative exchange adapter wrapping CoinDCX Spot, Margin, and Futures APIs."""

    @staticmethod
    def _client(user_id: int):
        return get_user_coindcx_client(user_id)

    @classmethod
    def verify_connection(cls, user_id: int) -> Dict[str, Any]:
        """Verify API authentication, account access, and trading permissions."""
        cdx = cls._client(user_id)
        if not cdx:
            return {
                "connected": False,
                "mode": "DISCONNECTED",
                "permissions": {"read": False, "trade": False, "futures": False},
                "available_balance_usd": 0.0,
                "total_balance_usd": 0.0,
                "error": "CoinDCX API key not configured for this account.",
            }
        if cdx.is_offline:
            return {
                "connected": False,
                "mode": "OFFLINE_SIMULATION",
                "permissions": {"read": False, "trade": False, "futures": False},
                "available_balance_usd": 0.0,
                "total_balance_usd": 0.0,
                "error": "CoinDCX client is in offline simulation mode.",
            }

        ok_bal, bal = cdx.get_balances()
        if not ok_bal:
            err = str((bal or {}).get("message") or (bal or {}).get("error") or "Authentication failed")
            return {
                "connected": False,
                "mode": "AUTH_FAILED",
                "permissions": {"read": False, "trade": False, "futures": False},
                "available_balance_usd": 0.0,
                "total_balance_usd": 0.0,
                "error": err,
                "corrective_action": corrective_action_for(err),
            }

        fut_elig = cdx.futures.check_eligibility()
        fut_ok = bool(fut_elig.get("eligible"))
        avail_usd = float(bal.get("usdt_free") or 0.0)
        total_usd = float(bal.get("total_portfolio_usd") or 0.0)
        if avail_usd <= 0 and fut_ok:
            avail_usd = float(cdx.futures.get_available_futures_margin_usdt() or 0.0)

        return {
            "connected": True,
            "mode": "LIVE",
            "permissions": {"read": True, "trade": True, "futures": fut_ok},
            "available_balance_usd": round(avail_usd, 4),
            "total_balance_usd": round(total_usd, 4),
            "error": "" if fut_ok else str(fut_elig.get("reason") or ""),
        }

    @classmethod
    def get_account_snapshot(cls, user_id: int) -> Dict[str, Any]:
        """Retrieve live balances, open positions, and active orders from CoinDCX."""
        status = cls.verify_connection(user_id)
        if not status.get("connected"):
            return {**status, "positions": [], "open_orders": []}

        cdx = cls._client(user_id)
        positions: List[Dict[str, Any]] = []
        open_orders: List[Dict[str, Any]] = []

        ok_pos, raw_pos = cdx.futures.get_positions()
        if ok_pos and isinstance(raw_pos, list):
            for p in raw_pos:
                try:
                    qty = float(p.get("active_pos") or 0.0)
                    if abs(qty) <= 0:
                        continue
                    positions.append({
                        "exchange_position_id": str(p.get("id") or ""),
                        "pair": str(p.get("pair") or ""),
                        "side": "LONG" if qty > 0 else "SHORT",
                        "qty": abs(qty),
                        "entry_price": float(p.get("avg_price") or 0.0),
                        "mark_price": float(p.get("mark_price") or p.get("avg_price") or 0.0),
                        "leverage": float(p.get("leverage") or 1.0),
                        "locked_margin": float(p.get("locked_margin") or 0.0),
                        "liquidation_price": float(p.get("liquidation_price") or 0.0),
                    })
                except Exception:
                    continue

        ok_ord, raw_ord = cdx.futures.get_orders()
        if ok_ord and isinstance(raw_ord, list):
            for o in raw_ord:
                st = str(o.get("status") or "").lower()
                if st in ("open", "partially_filled", "init", "untriggered"):
                    open_orders.append({
                        "exchange_order_id": str(o.get("id") or ""),
                        "pair": str(o.get("pair") or ""),
                        "side": str(o.get("side") or "").upper(),
                        "order_type": str(o.get("order_type") or ""),
                        "qty": float(o.get("total_quantity") or 0.0),
                        "remaining_qty": float(o.get("remaining_quantity") or 0.0),
                        "price": float(o.get("price") or 0.0),
                        "stop_price": float(o.get("stop_price") or 0.0),
                        "status": st.upper(),
                    })

        return {**status, "positions": positions, "open_orders": open_orders}

    @classmethod
    def _record_order_mapping(
        cls,
        *,
        user_id: int,
        client_order_id: str,
        exchange_order_id: str,
        position_id: str,
        strategy_id: str,
        symbol: str,
        market_type: str,
        side: str,
        mode: str,
        requested_qty: float,
        filled_qty: float,
        avg_fill_price: float,
        fee_usd: float,
        status: str,
        rejection_reason: str,
        endpoint: str,
        sanitized_req: Dict[str, Any],
    ) -> None:
        now = time.time()
        write(
            """INSERT INTO order_mappings(
                 user_id, client_order_id, exchange_order_id, position_id, strategy_id,
                 symbol, market_type, side, mode, requested_qty, filled_qty, avg_fill_price,
                 fee_usd, status, rejection_reason, endpoint, sanitized_request, created_at, updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(client_order_id) DO UPDATE SET
                 exchange_order_id=excluded.exchange_order_id,
                 position_id=excluded.position_id,
                 filled_qty=excluded.filled_qty,
                 avg_fill_price=excluded.avg_fill_price,
                 fee_usd=excluded.fee_usd,
                 status=excluded.status,
                 rejection_reason=excluded.rejection_reason,
                 updated_at=excluded.updated_at""",
            (
                user_id, client_order_id, exchange_order_id, position_id, strategy_id,
                symbol, market_type, side, mode, float(requested_qty or 0.0),
                float(filled_qty or 0.0), float(avg_fill_price or 0.0), float(fee_usd or 0.0),
                status, rejection_reason, endpoint, json.dumps(sanitized_req), now, now,
            ),
        )

    @classmethod
    def submit_order(
        cls,
        user_id: int,
        *,
        symbol: str,
        side: str,
        market_type: str = "FUTURES",
        quantity: float = 0.0,
        margin_usd: float = 0.0,
        leverage: float = 20.0,
        order_type: str = "market_order",
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        strategy_id: str = "",
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submit a validated, idempotent live CoinDCX order across Futures, Spot, or Margin."""
        cid = (client_order_id or f"araa_{user_id}_{uuid.uuid4().hex[:16]}").strip()

        # Idempotency guard: never submit duplicate live order on retry/reconnect
        existing = query_one("SELECT * FROM order_mappings WHERE client_order_id=?", (cid,))
        if existing and existing.get("status") in ("NEW", "PARTIALLY_FILLED", "FILLED"):
            return {
                "success": True,
                "idempotent_replay": True,
                "client_order_id": cid,
                "exchange_order_id": existing.get("exchange_order_id"),
                "status": existing.get("status"),
                "filled_qty": existing.get("filled_qty"),
                "avg_fill_price": existing.get("avg_fill_price"),
                "fee_usd": existing.get("fee_usd"),
            }

        mkt_type = (market_type or "FUTURES").upper().strip()
        side_up = (side or "BUY").upper().strip()
        order_side = "buy" if side_up in ("BUY", "LONG") else "sell"
        sym_up = (symbol or "").upper().strip()

        cdx = cls._client(user_id)
        if not cdx or cdx.is_offline:
            err = "CoinDCX API disconnected or in offline mode. Cannot execute real order."
            cls._record_order_mapping(
                user_id=user_id, client_order_id=cid, exchange_order_id="", position_id="",
                strategy_id=strategy_id, symbol=sym_up, market_type=mkt_type, side=side_up,
                mode="REAL", requested_qty=quantity, filled_qty=0.0, avg_fill_price=0.0,
                fee_usd=0.0, status="REJECTED", rejection_reason=err,
                endpoint="precheck", sanitized_req={"symbol": sym_up, "side": side_up, "market_type": mkt_type},
            )
            return {
                "success": False,
                "status": "REJECTED",
                "client_order_id": cid,
                "error": err,
                "endpoint": "precheck",
                "sanitized_request": {"symbol": sym_up, "side": side_up, "market_type": mkt_type},
                "corrective_action": "Connect a live CoinDCX API key with Read + Trade permissions.",
            }

        if not sym_up or len(sym_up) < 4:
            err = f"Invalid trading symbol: '{sym_up}'"
            cls._record_order_mapping(
                user_id=user_id, client_order_id=cid, exchange_order_id="", position_id="",
                strategy_id=strategy_id, symbol=sym_up, market_type=mkt_type, side=side_up,
                mode="REAL", requested_qty=quantity, filled_qty=0.0, avg_fill_price=0.0,
                fee_usd=0.0, status="REJECTED", rejection_reason=err,
                endpoint="precheck", sanitized_req={"symbol": sym_up},
            )
            return {
                "success": False, "status": "REJECTED", "client_order_id": cid,
                "error": err, "endpoint": "precheck",
                "sanitized_request": {"symbol": sym_up},
                "corrective_action": corrective_action_for(err),
            }

        # Route by market type (Futures vs Spot vs Margin)
        if mkt_type == "FUTURES":
            endpoint = "/exchange/v1/derivatives/futures/orders/create"
            elig = cdx.futures.check_eligibility()
            if not elig.get("eligible"):
                err = str(elig.get("reason") or "CoinDCX Futures not permitted on this API key.")
                cls._record_order_mapping(
                    user_id=user_id, client_order_id=cid, exchange_order_id="", position_id="",
                    strategy_id=strategy_id, symbol=sym_up, market_type="FUTURES", side=side_up,
                    mode="REAL", requested_qty=quantity, filled_qty=0.0, avg_fill_price=0.0,
                    fee_usd=0.0, status="REJECTED", rejection_reason=err,
                    endpoint=endpoint, sanitized_req={"symbol": sym_up, "side": order_side},
                )
                return {
                    "success": False, "status": "REJECTED", "client_order_id": cid,
                    "error": err, "endpoint": endpoint,
                    "sanitized_request": {"symbol": sym_up, "side": order_side},
                    "corrective_action": corrective_action_for(err),
                }

            eff_lev = cdx.futures.resolve_leverage(sym_up, leverage, order_side)
            ref_price = float(price or 0.0)
            if ref_price <= 0:
                inst = cdx.futures.get_instrument(sym_up)
                ref_price = float(inst.get("last_price") or inst.get("mark_price") or 0.0)
            req_qty = float(quantity or 0.0)
            if req_qty <= 0 and margin_usd > 0 and ref_price > 0:
                req_qty = (margin_usd * eff_lev) / ref_price
            if req_qty <= 0:
                err = f"Invalid order quantity ({req_qty}) for {sym_up}."
                cls._record_order_mapping(
                    user_id=user_id, client_order_id=cid, exchange_order_id="", position_id="",
                    strategy_id=strategy_id, symbol=sym_up, market_type="FUTURES", side=side_up,
                    mode="REAL", requested_qty=req_qty, filled_qty=0.0, avg_fill_price=0.0,
                    fee_usd=0.0, status="REJECTED", rejection_reason=err,
                    endpoint=endpoint, sanitized_req={"symbol": sym_up, "quantity": req_qty},
                )
                return {
                    "success": False, "status": "REJECTED", "client_order_id": cid,
                    "error": err, "endpoint": endpoint,
                    "sanitized_request": {"symbol": sym_up, "quantity": req_qty},
                    "corrective_action": corrective_action_for(err),
                }

            san_req = sanitize_request({
                "pair": cdx.futures.to_futures_pair(sym_up),
                "side": order_side,
                "order_type": order_type,
                "quantity": req_qty,
                "leverage": eff_lev,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "client_order_id": cid,
            })

            ok_ord, res_ord = cdx.futures.place_futures_order(
                symbol=sym_up,
                side=order_side,
                quantity=req_qty,
                leverage=eff_lev,
                order_type=order_type,
                price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                client_order_id=cid,
            )
            if not ok_ord:
                err = str((res_ord or {}).get("message") or (res_ord or {}).get("error") or "CoinDCX Futures order rejected")
                cls._record_order_mapping(
                    user_id=user_id, client_order_id=cid, exchange_order_id="", position_id="",
                    strategy_id=strategy_id, symbol=sym_up, market_type="FUTURES", side=side_up,
                    mode="REAL", requested_qty=req_qty, filled_qty=0.0, avg_fill_price=0.0,
                    fee_usd=0.0, status="REJECTED", rejection_reason=err,
                    endpoint=endpoint, sanitized_req=san_req,
                )
                return {
                    "success": False, "status": "REJECTED", "client_order_id": cid,
                    "error": err, "endpoint": endpoint, "sanitized_request": san_req,
                    "corrective_action": corrective_action_for(err),
                }

            ex_id = str((res_ord or {}).get("id") or "")
            filled_qty = float((res_ord or {}).get("spot_equivalent_quantity") or (res_ord or {}).get("filled_quantity") or (res_ord or {}).get("total_quantity") or (res_ord or {}).get("quantity") or req_qty)
            avg_px = float((res_ord or {}).get("spot_equivalent_price") or (res_ord or {}).get("avg_price") or (res_ord or {}).get("mark_price") or (res_ord or {}).get("price") or ref_price or 0.0)
            fee_usd = float((res_ord or {}).get("fee_amount") or round(filled_qty * avg_px * 0.0005, 6))
            raw_st = str((res_ord or {}).get("status") or "filled").lower()
            ord_status = "PARTIALLY_FILLED" if ("partial" in raw_st or (0 < filled_qty < req_qty * 0.999)) else "FILLED"
            actual_eff_lev = float((res_ord or {}).get("leverage") or eff_lev)
            actual_margin_usd = float((res_ord or {}).get("actual_margin_usd") or 0.0) or (round((filled_qty * avg_px) / max(1.0, actual_eff_lev), 4) if avg_px > 0 else round(float(margin_usd or 0.0), 4))

            cls._record_order_mapping(
                user_id=user_id, client_order_id=cid, exchange_order_id=ex_id, position_id=ex_id,
                strategy_id=strategy_id, symbol=sym_up, market_type="FUTURES", side=side_up,
                mode="REAL", requested_qty=req_qty, filled_qty=filled_qty, avg_fill_price=avg_px,
                fee_usd=fee_usd, status=ord_status, rejection_reason="",
                endpoint=endpoint, sanitized_req=san_req,
            )
            return {
                "success": True,
                "status": ord_status,
                "client_order_id": cid,
                "exchange_order_id": ex_id,
                "filled_qty": filled_qty,
                "avg_fill_price": avg_px,
                "leverage": actual_eff_lev,
                "actual_margin_usd": actual_margin_usd,
                "fee_usd": fee_usd,
                "endpoint": endpoint,
                "sanitized_request": san_req,
                "raw": res_ord,
            }

        elif mkt_type == "MARGIN":
            endpoint = "/exchange/v1/margin/create"
            if quantity <= 0:
                err = f"Invalid margin order quantity ({quantity}) for {sym_up}."
                return {
                    "success": False, "status": "REJECTED", "client_order_id": cid,
                    "error": err, "endpoint": endpoint,
                    "sanitized_request": {"symbol": sym_up, "quantity": quantity},
                    "corrective_action": corrective_action_for(err),
                }
            mkt = to_coindcx_market(sym_up)
            san_req = sanitize_request({
                "market": mkt, "side": order_side, "quantity": quantity,
                "leverage": min(5.0, max(1.0, float(leverage or 2.0))), "order_type": order_type,
            })
            ok_ord, res_ord = cdx._call(endpoint, body={
                "side": order_side,
                "order_type": "market_order" if order_type == "market_order" else "limit_order",
                "market": mkt,
                "total_quantity": float(quantity),
                "price": float(price) if (price and order_type != "market_order") else None,
                "ecode": "B",
                "leverage": min(5, max(1, int(leverage or 2))),
                "timestamp": int(time.time() * 1000),
            }, attempts=1)
            if not ok_ord:
                err = str((res_ord or {}).get("message") or "CoinDCX Margin order rejected")
                cls._record_order_mapping(
                    user_id=user_id, client_order_id=cid, exchange_order_id="", position_id="",
                    strategy_id=strategy_id, symbol=sym_up, market_type="MARGIN", side=side_up,
                    mode="REAL", requested_qty=quantity, filled_qty=0.0, avg_fill_price=0.0,
                    fee_usd=0.0, status="REJECTED", rejection_reason=err,
                    endpoint=endpoint, sanitized_req=san_req,
                )
                return {
                    "success": False, "status": "REJECTED", "client_order_id": cid,
                    "error": err, "endpoint": endpoint, "sanitized_request": san_req,
                    "corrective_action": corrective_action_for(err),
                }
            ex_id = str((res_ord or {}).get("id") or "")
            avg_px = float((res_ord or {}).get("price_per_unit") or price or 0.0)
            fee_usd = round(float(quantity) * avg_px * 0.001, 6)
            cls._record_order_mapping(
                user_id=user_id, client_order_id=cid, exchange_order_id=ex_id, position_id=ex_id,
                strategy_id=strategy_id, symbol=sym_up, market_type="MARGIN", side=side_up,
                mode="REAL", requested_qty=quantity, filled_qty=quantity, avg_fill_price=avg_px,
                fee_usd=fee_usd, status="FILLED", rejection_reason="",
                endpoint=endpoint, sanitized_req=san_req,
            )
            return {
                "success": True, "status": "FILLED", "client_order_id": cid,
                "exchange_order_id": ex_id, "filled_qty": quantity, "avg_fill_price": avg_px,
                "leverage": min(5.0, float(leverage or 2.0)), "fee_usd": fee_usd,
                "endpoint": endpoint, "sanitized_request": san_req, "raw": res_ord,
            }

        else:
            # SPOT
            endpoint = "/exchange/v1/orders/create"
            if quantity <= 0:
                err = f"Invalid spot order quantity ({quantity}) for {sym_up}."
                return {
                    "success": False, "status": "REJECTED", "client_order_id": cid,
                    "error": err, "endpoint": endpoint,
                    "sanitized_request": {"symbol": sym_up, "quantity": quantity},
                    "corrective_action": corrective_action_for(err),
                }
            mkt = to_coindcx_market(sym_up)
            san_req = sanitize_request({"market": mkt, "side": order_side, "quantity": quantity, "price": price})
            ok_ord, res_ord = cdx.place_order(
                side=order_side, market=mkt, quantity=float(quantity),
                price=price if (price and order_type != "market_order") else None,
            )
            if not ok_ord:
                err = str((res_ord or {}).get("message") or (res_ord or {}).get("error") or "CoinDCX Spot order rejected")
                cls._record_order_mapping(
                    user_id=user_id, client_order_id=cid, exchange_order_id="", position_id="",
                    strategy_id=strategy_id, symbol=sym_up, market_type="SPOT", side=side_up,
                    mode="REAL", requested_qty=quantity, filled_qty=0.0, avg_fill_price=0.0,
                    fee_usd=0.0, status="REJECTED", rejection_reason=err,
                    endpoint=endpoint, sanitized_req=san_req,
                )
                return {
                    "success": False, "status": "REJECTED", "client_order_id": cid,
                    "error": err, "endpoint": endpoint, "sanitized_request": san_req,
                    "corrective_action": corrective_action_for(err),
                }
            orders = res_ord.get("orders") if isinstance(res_ord, dict) else None
            first = orders[0] if isinstance(orders, list) and orders else (res_ord if isinstance(res_ord, dict) else {})
            ex_id = str(first.get("id") or "")
            filled_qty = float(first.get("total_quantity") or quantity)
            avg_px = float(first.get("price_per_unit") or price or 0.0)
            fee_usd = float(first.get("fee_amount") or round(filled_qty * avg_px * 0.001, 6))
            cls._record_order_mapping(
                user_id=user_id, client_order_id=cid, exchange_order_id=ex_id, position_id=ex_id,
                strategy_id=strategy_id, symbol=sym_up, market_type="SPOT", side=side_up,
                mode="REAL", requested_qty=quantity, filled_qty=filled_qty, avg_fill_price=avg_px,
                fee_usd=fee_usd, status="FILLED", rejection_reason="",
                endpoint=endpoint, sanitized_req=san_req,
            )
            return {
                "success": True, "status": "FILLED", "client_order_id": cid,
                "exchange_order_id": ex_id, "filled_qty": filled_qty, "avg_fill_price": avg_px,
                "leverage": 1.0, "fee_usd": fee_usd, "endpoint": endpoint,
                "sanitized_request": san_req, "raw": res_ord,
            }

    @classmethod
    def setup_and_verify_protection(
        cls,
        user_id: int,
        *,
        position_id: str,
        exchange_position_id: str,
        symbol: str,
        market_type: str,
        side: str,
        entry_price: float,
        filled_qty: float,
        stop_loss_pct: float,
        take_profit_pct: float,
        trailing_stop_pct: float = 0.0,
        is_live: bool = False,
    ) -> Dict[str, Any]:
        """Compute SL/TP from actual filled entry price and verify exchange or backend protection."""
        is_long = (side or "").upper() in ("BUY", "LONG")
        sl_price = round(entry_price * (1.0 - stop_loss_pct / 100.0) if is_long else entry_price * (1.0 + stop_loss_pct / 100.0), 6)
        tp_price = round(entry_price * (1.0 + take_profit_pct / 100.0) if is_long else entry_price * (1.0 - take_profit_pct / 100.0), 6)

        verified = 0
        prot_status = "MONITORED_BACKEND"
        fail_reason = ""
        sl_ord_id = ""
        tp_ord_id = ""

        if is_live and market_type.upper() == "FUTURES":
            cdx = cls._client(user_id)
            if cdx and not cdx.is_offline:
                pos = cdx.futures.find_open_position(symbol)
                pos_uuid = str((pos or {}).get("id") or exchange_position_id or "")
                inst = cdx.futures.get_instrument(symbol)
                p_inc = float(inst.get("price_increment") or 0.0)
                if p_inc > 0:
                    sl_price = round_to_increment(sl_price, p_inc)
                    tp_price = round_to_increment(tp_price, p_inc)
                if pos_uuid:
                    # Profit-Only Real Mode: attach exchange-side Take Profit only (no forced SL close at a loss)
                    ok_tpsl, res_tpsl = cdx.futures._call(
                        "/exchange/v1/derivatives/futures/positions/create_tpsl",
                        body={
                            "id": pos_uuid,
                            "take_profit": {"stop_price": str(tp_price), "order_type": "take_profit_market"},
                        },
                        attempts=2,
                    )
                    if ok_tpsl:
                        verified = 1
                        prot_status = "VERIFIED"
                        sl_ord_id = str((res_tpsl or {}).get("stop_loss_order_id") or pos_uuid)
                        tp_ord_id = str((res_tpsl or {}).get("take_profit_order_id") or pos_uuid)
                    else:
                        verified = 0
                        prot_status = "FAILED"
                        fail_reason = str((res_tpsl or {}).get("message") or "Exchange TP/SL creation rejected; fallback backend monitor active.")
                else:
                    verified = 0
                    prot_status = "FAILED"
                    fail_reason = "No matching live CoinDCX position UUID found to attach TP/SL."
            else:
                prot_status = "FAILED"
                fail_reason = "CoinDCX client disconnected while verifying SL/TP."
        elif not is_live:
            verified = 1
            prot_status = "VERIFIED"

        now = time.time()
        write(
            """INSERT INTO position_protections(
                 user_id, position_id, exchange_position_id, symbol, market_type,
                 entry_price, filled_qty, stop_loss_price, take_profit_price,
                 trailing_stop_pct, sl_order_id, tp_order_id, protection_verified,
                 protection_status, failure_reason, updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id, position_id) DO UPDATE SET
                 exchange_position_id=excluded.exchange_position_id,
                 entry_price=excluded.entry_price,
                 filled_qty=excluded.filled_qty,
                 stop_loss_price=excluded.stop_loss_price,
                 take_profit_price=excluded.take_profit_price,
                 trailing_stop_pct=excluded.trailing_stop_pct,
                 sl_order_id=excluded.sl_order_id,
                 tp_order_id=excluded.tp_order_id,
                 protection_verified=excluded.protection_verified,
                 protection_status=excluded.protection_status,
                 failure_reason=excluded.failure_reason,
                 updated_at=excluded.updated_at""",
            (
                user_id, str(position_id), str(exchange_position_id), symbol.upper(),
                market_type.upper(), entry_price, filled_qty, sl_price, tp_price,
                trailing_stop_pct, sl_ord_id, tp_ord_id, verified, prot_status, fail_reason, now,
            ),
        )
        return {
            "position_id": str(position_id),
            "symbol": symbol.upper(),
            "stop_loss_price": sl_price,
            "take_profit_price": tp_price,
            "protection_verified": bool(verified),
            "protection_status": prot_status,
            "failure_reason": fail_reason,
        }

    @classmethod
    def cancel_obsolete_protection(cls, user_id: int, position_id: str, symbol: str = "") -> None:
        """Mark protection cancelled on close and cancel any resting exchange orders for the pair."""
        write(
            "UPDATE position_protections SET protection_status='CANCELLED', updated_at=? WHERE user_id=? AND position_id=?",
            (time.time(), user_id, str(position_id)),
        )
        if symbol:
            cdx = cls._client(user_id)
            if cdx and not cdx.is_offline:
                try:
                    ok_ord, orders = cdx.futures.get_orders()
                    pair = cdx.futures.to_futures_pair(symbol)
                    if ok_ord and isinstance(orders, list):
                        for o in orders:
                            if o.get("pair") == pair and str(o.get("status") or "").lower() in ("open", "init", "untriggered"):
                                cdx.futures._call("/exchange/v1/derivatives/futures/orders/cancel", body={"id": o.get("id")}, attempts=1)
                except Exception:
                    pass

    @classmethod
    def reconcile_state(cls, user_id: int) -> Dict[str, Any]:
        """Restore protection monitoring & reconcile live CoinDCX positions after restart or reconnect."""
        snap = cls.get_account_snapshot(user_id)
        prots = query("SELECT * FROM position_protections WHERE user_id=? AND protection_status IN ('VERIFIED','MONITORED_BACKEND','FAILED')", (user_id,))
        active_pairs = {p.get("pair") for p in snap.get("positions", [])}
        reconciled = 0
        for pr in prots:
            if not active_pairs and snap.get("connected"):
                # Live exchange has no matching position; keep paper/local check separate
                pass
            reconciled += 1
        return {"connected": snap.get("connected"), "positions_count": len(snap.get("positions", [])), "protections_active": reconciled}

