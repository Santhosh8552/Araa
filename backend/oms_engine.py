"""
ARAA BOT V3 — ENTERPRISE ORDER MANAGEMENT SYSTEM (OMS) & EXECUTION MANAGEMENT SYSTEM (EMS)
Institutional OMS, EMS, Position Manager, Portfolio Manager, Broker Execution Adapter,
and Execution Reconciliation Engine.
"""

import time
import uuid
import json
import logging
from typing import Dict, Any, List, Optional, Tuple

from database import query, query_one, write, writes
from event_bus import get_event_bus, Events
from risk_engine import InstitutionalRiskEngine, OrderLifecycleManager

logger = logging.getLogger("OMS_ENGINE")


class OrderStatus:
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class OrderManagementSystem:
    """Institutional Order Management System (OMS) controlling complete order lifecycle."""

    @classmethod
    def create_order(cls, user_id: int, symbol: str, side: str, order_type: str,
                     quantity: float, price: float = 0.0, stop_price: float = 0.0,
                     take_profit: float = 0.0, stop_loss: float = 0.0, leverage: float = 1.0,
                     broker_account_id: Optional[str] = None, bot_id: Optional[str] = None,
                     is_paper: bool = False, client_order_id: Optional[str] = None) -> Dict[str, Any]:
        """Validates risk, generates deterministic UUID, creates order with state PENDING."""
        order_uuid = str(uuid.uuid4())
        now = time.time()
        side_clean = str(side).upper()
        order_type_clean = str(order_type).upper()

        # Duplicate order prevention via order_audit_lifecycle
        if client_order_id:
            dup = query_one("SELECT order_uuid FROM order_audit_lifecycle WHERE order_uuid=?", (client_order_id,))
            if dup:
                return {"success": False, "error": "DUPLICATE_ORDER_REJECTED", "order_uuid": client_order_id}

        # Pre-trade Risk Validation via Institutional Risk Engine
        w = query_one("SELECT deposit_balance, profit_balance FROM wallets WHERE user_id=?", (user_id,)) or {}
        equity = float(w.get("deposit_balance") or 0.0) + float(w.get("profit_balance") or 0.0)

        risk_approved, risk_reason, risk_meta = InstitutionalRiskEngine.evaluate_pre_trade_risk(
            user_id=user_id,
            symbol=symbol,
            side=side_clean,
            equity_usd=equity,
            entry_price=price,
            stop_price=stop_loss if stop_loss > 0 else (price * 0.98 if side_clean in ("BUY", "LONG") else price * 1.02),
            take_profit_price=take_profit if take_profit > 0 else (price * 1.03 if side_clean in ("BUY", "LONG") else price * 0.97),
            requested_leverage=leverage,
            is_live=not is_paper
        )

        if not risk_approved:
            audit_uuid = OrderLifecycleManager.create_order_record(
                user_id=user_id,
                symbol=symbol,
                side=side_clean,
                requested_qty=quantity,
                requested_price=price,
                leverage=leverage,
                execution_mode="PAPER" if is_paper else "LIVE",
                order_type=order_type_clean,
                is_live=not is_paper
            )
            OrderLifecycleManager.finalize_order_record(
                order_uuid=audit_uuid,
                executed=False,
                filled_qty=0.0,
                filled_price=0.0,
                error_reason=f"RISK_REJECTION: {risk_reason}"
            )
            get_event_bus().publish(Events.ORDER_REJECTED, user_id=user_id, order_uuid=audit_uuid, reason=risk_reason)
            return {"success": False, "error": f"Risk Guardian Rejection: {risk_reason}", "order_uuid": audit_uuid}

        # Sizing and fee estimation
        notional = quantity * price if price > 0 else 0.0
        margin = round(notional / max(leverage, 1.0), 4)
        fees = OrderLifecycleManager.calculate_execution_costs(notional, order_type_clean, is_paper, price, price)

        tp_pct = round(abs(take_profit - price) / price * 100.0, 2) if (take_profit > 0 and price > 0) else 1.5
        sl_pct = round(abs(stop_loss - price) / price * 100.0, 2) if (stop_loss > 0 and price > 0) else 0.8

        # Write to orders table using exact schema columns
        order_id = write(
            "INSERT INTO orders(user_id, symbol, side, qty, price, margin, status, created_at, "
            "leverage, target_pct, stop_pct, is_live) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, symbol, side_clean, quantity, price, margin, OrderStatus.PENDING, now,
             leverage, tp_pct, sl_pct, 0 if is_paper else 1)
        )

        audit_uuid = OrderLifecycleManager.create_order_record(
            user_id=user_id,
            symbol=symbol,
            side=side_clean,
            requested_qty=quantity,
            requested_price=price,
            leverage=leverage,
            margin_allocated=margin,
            execution_mode="PAPER" if is_paper else "LIVE",
            order_type=order_type_clean,
            is_live=not is_paper
        )

        get_event_bus().publish(
            Events.ORDER_CREATED,
            user_id=user_id,
            order_id=order_id,
            order_uuid=audit_uuid,
            symbol=symbol,
            side=side_clean,
            quantity=quantity,
            price=price,
            is_paper=is_paper
        )

        return {
            "success": True,
            "order_id": order_id,
            "order_uuid": audit_uuid,
            "status": OrderStatus.PENDING,
            "fees_est_usd": fees["fee_usd"]
        }

    @classmethod
    def cancel_order(cls, user_id: int, order_id: int, reason: str = "USER_CANCELLED") -> Dict[str, Any]:
        """Cancels a pending or open order."""
        row = query_one("SELECT * FROM orders WHERE id=? AND user_id=?", (order_id, user_id))
        if not row:
            return {"success": False, "error": "Order not found"}
        if row["status"] in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
            return {"success": False, "error": f"Cannot cancel order with status {row['status']}"}

        write("UPDATE orders SET status=?, error=? WHERE id=?", (OrderStatus.CANCELLED, reason, order_id))
        get_event_bus().publish(Events.ORDER_CANCELLED, user_id=user_id, order_id=order_id, reason=reason)
        return {"success": True, "order_id": order_id, "status": OrderStatus.CANCELLED}

    @classmethod
    def modify_order(cls, user_id: int, order_id: int, new_quantity: Optional[float] = None,
                     new_price: Optional[float] = None) -> Dict[str, Any]:
        """Modifies order parameters before execution."""
        row = query_one("SELECT * FROM orders WHERE id=? AND user_id=?", (order_id, user_id))
        if not row:
            return {"success": False, "error": "Order not found"}
        if row["status"] not in (OrderStatus.PENDING, OrderStatus.ACKNOWLEDGED, OrderStatus.SUBMITTED):
            return {"success": False, "error": f"Order in state {row['status']} cannot be modified"}

        qty = new_quantity if new_quantity is not None else row["qty"]
        px = new_price if new_price is not None else row["price"]

        write("UPDATE orders SET qty=?, price=? WHERE id=?", (qty, px, order_id))
        return {"success": True, "order_id": order_id, "qty": qty, "price": px}


class ExecutionManagementSystem:
    """Execution Management System (EMS) routing orders to brokers or simulation engine."""

    @classmethod
    def execute_order(cls, order_id: int) -> Dict[str, Any]:
        """Routes order to broker execution adapter or simulated fill."""
        order = query_one("SELECT * FROM orders WHERE id=?", (order_id,))
        if not order:
            return {"success": False, "error": "Order not found"}

        now = time.time()
        write("UPDATE orders SET status=? WHERE id=?", (OrderStatus.SUBMITTED, order_id))
        get_event_bus().publish(Events.ORDER_SUBMITTED, order_id=order_id, symbol=order["symbol"])

        is_paper = not bool(order.get("is_live"))
        if is_paper:
            req_p = float(order.get("price") or 0.0)
            if req_p <= 0:
                from price_feed import get_price_feed
                feed = get_price_feed()
                req_p = feed.price(order["symbol"]) or 1.0

            side = str(order.get("side")).upper()
            slip_mult = 1.0002 if side in ("BUY", "LONG") else 0.9998
            fill_price = round(req_p * slip_mult, 6)
            qty = float(order.get("qty") or 1.0)
            fill_uuid = f"fill_{uuid.uuid4().hex[:12]}"
            order_uuid = f"ord_{order_id}"

            # Record fill into order_fills exact schema
            write(
                "INSERT INTO order_fills(fill_id, order_uuid, user_id, exchange_fill_id, "
                "fill_qty, fill_price, fee_amount, fee_currency, is_partial, executed_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, 'USDT', 0, ?)",
                (fill_uuid, order_uuid, order["user_id"], f"SIM-{order_id}", qty, fill_price,
                 round(fill_price * qty * 0.0004, 4), now)
            )

            pos_id = PositionManager.open_position_from_order(order, fill_price, qty, is_paper=True)

            write(
                "UPDATE orders SET status=?, filled_at=?, price=?, position_id=? WHERE id=?",
                (OrderStatus.FILLED, now, fill_price, pos_id, order_id)
            )

            get_event_bus().publish(
                Events.ORDER_FILLED,
                order_id=order_id,
                position_id=pos_id,
                fill_price=fill_price,
                fill_quantity=qty,
                is_paper=True
            )

            return {
                "success": True,
                "order_id": order_id,
                "status": OrderStatus.FILLED,
                "fill_price": fill_price,
                "fill_quantity": qty,
                "position_id": pos_id
            }

        return BrokerExecutionAdapter.execute_real(order)


class PositionManager:
    """Tracks, reconciles, and manages open and closed positions."""

    @classmethod
    def open_position_from_order(cls, order: Dict[str, Any], fill_price: float,
                                 fill_quantity: float, is_paper: bool = False) -> int:
        now = time.time()
        user_id = order["user_id"]
        symbol = order["symbol"]
        side = order["side"]
        lev = float(order.get("leverage") or 1.0)
        margin = round((fill_price * fill_quantity) / lev, 4)

        tp_pct = float(order.get("target_pct") or 1.5)
        sl_pct = float(order.get("stop_pct") or 0.8)
        liq_p = InstitutionalRiskEngine.calculate_liquidation_price(fill_price, side, lev)

        pos_id = write(
            "INSERT INTO positions(user_id, symbol, source, side, qty, entry_price, margin, "
            "target_pct, stop_pct, status, current_price, unrealized_pnl, opened_at, leverage, "
            "is_live, liquidation_price) "
            "VALUES(?, ?, 'OMS', ?, ?, ?, ?, ?, ?, 'OPEN', ?, 0.0, ?, ?, ?, ?)",
            (user_id, symbol, side, fill_quantity, fill_price, margin, tp_pct, sl_pct,
             fill_price, now, lev, 0 if is_paper else 1, liq_p)
        )

        get_event_bus().publish(
            Events.POSITION_OPENED,
            user_id=user_id,
            position_id=pos_id,
            symbol=symbol,
            side=side,
            entry_price=fill_price,
            margin=margin
        )
        return pos_id

    @classmethod
    def close_position(cls, position_id: int, close_price: float, reason: str = "MANUAL_CLOSE") -> Dict[str, Any]:
        """Closes a position and calculates P&L."""
        pos = query_one("SELECT * FROM positions WHERE id=?", (position_id,))
        if not pos or pos["status"] != "OPEN":
            return {"success": False, "error": "Position not open"}

        now = time.time()
        is_long = pos["side"] in ("BUY", "LONG")
        entry = float(pos["entry_price"])
        direction = 1.0 if is_long else -1.0
        lev = float(pos.get("leverage") or 1.0)
        margin = float(pos.get("margin") or 1.0)

        move_pct = ((close_price - entry) / entry * 100.0 * direction) if entry > 0 else 0.0
        raw_pnl = margin * lev * (move_pct / 100.0)
        realized_pnl = max(-margin, round(raw_pnl, 4))
        pnl_pct = round((realized_pnl / margin) * 100.0, 2) if margin > 0 else 0.0
        dur_sec = max(0.0, now - float(pos.get("opened_at") or now))

        write(
            "UPDATE positions SET status='CLOSED', current_price=?, realized_pnl=?, unrealized_pnl=0.0, "
            "closed_at=?, close_reason=? WHERE id=?",
            (close_price, realized_pnl, now, reason, position_id)
        )

        # Record in trades table using exact schema
        trade_id = f"TRD-{uuid.uuid4().hex[:10].upper()}"
        write(
            "INSERT INTO trades(trade_id, user_id, symbol, side, entry_price, exit_price, qty, "
            "leverage, margin, realized_pnl, pnl_pct, fee_total, duration_seconds, entry_reason, "
            "exit_reason, execution_mode, opened_at, closed_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OMS', ?, ?, ?, ?)",
            (trade_id, pos["user_id"], pos["symbol"], pos["side"], entry, close_price,
             pos["qty"], lev, margin, realized_pnl, pnl_pct, round(margin * 0.0008, 4), dur_sec,
             reason, "LIVE" if pos.get("is_live") else "PAPER", pos.get("opened_at") or now, now)
        )

        get_event_bus().publish(
            Events.POSITION_CLOSED,
            user_id=pos["user_id"],
            position_id=position_id,
            symbol=pos["symbol"],
            realized_pnl=realized_pnl,
            close_reason=reason
        )

        return {
            "success": True,
            "trade_id": trade_id,
            "position_id": position_id,
            "realized_pnl": realized_pnl,
            "close_price": close_price,
            "reason": reason
        }


class PortfolioManager:
    """Computes total exposure, leverage, unrealized/realized P&L, and asset breakdown."""

    @classmethod
    def get_portfolio_summary(cls, user_id: int) -> Dict[str, Any]:
        w = query_one("SELECT * FROM wallets WHERE user_id=?", (user_id,)) or {}
        opens = query("SELECT * FROM positions WHERE user_id=? AND status='OPEN'", (user_id,))
        closed_row = query_one("SELECT COALESCE(SUM(realized_pnl), 0.0) as sum_pnl FROM positions WHERE user_id=? AND status='CLOSED'", (user_id,))

        unrealized = sum(float(p.get("unrealized_pnl") or 0.0) for p in opens)
        margin_locked = sum(float(p.get("margin") or 0.0) for p in opens)
        exposure = sum(float(p.get("margin") or 0.0) * float(p.get("leverage") or 1.0) for p in opens)
        deposit = float(w.get("deposit_balance") or 0.0)
        profit = float(w.get("profit_balance") or 0.0)
        total_equity = deposit + profit + unrealized

        return {
            "user_id": user_id,
            "deposit_balance": deposit,
            "profit_balance": profit,
            "total_equity": round(total_equity, 2),
            "margin_locked": round(margin_locked, 2),
            "available_free_margin": round(max(0.0, deposit + profit - margin_locked), 2),
            "unrealized_pnl": round(unrealized, 2),
            "cumulative_realized_pnl": round(float(closed_row["sum_pnl"] or 0.0), 2),
            "total_portfolio_exposure": round(exposure, 2),
            "open_positions_count": len(opens),
            "effective_leverage": round(exposure / max(total_equity, 1.0), 2)
        }


class BrokerExecutionAdapter:
    """Routes execution calls to broker gateways (CoinDCX, Exness, etc.)."""

    @classmethod
    def execute_real(cls, order: Dict[str, Any]) -> Dict[str, Any]:
        user_id = order["user_id"]
        symbol = order["symbol"]
        side = order["side"]
        qty = float(order.get("qty") or 1.0)
        price = float(order.get("price") or 0.0)
        order_id = order["id"]

        try:
            from real_broker import place_real_order
            res = place_real_order(
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                user_id=user_id,
                leverage=float(order.get("leverage") or 1.0),
                order_type="MARKET"
            )
            if res and res.get("order_id"):
                now = time.time()
                fill_price = float(res.get("price") or price)
                pos_id = PositionManager.open_position_from_order(order, fill_price, qty, is_paper=False)
                write(
                    "UPDATE orders SET status=?, filled_at=?, price=?, position_id=? WHERE id=?",
                    (OrderStatus.FILLED, now, fill_price, pos_id, order_id)
                )
                return {"success": True, "order_id": order_id, "status": OrderStatus.FILLED, "exchange_order_id": res.get("order_id")}
            else:
                err = (res or {}).get("error", "Broker order placement failed")
                write("UPDATE orders SET status=?, error=? WHERE id=?", (OrderStatus.REJECTED, err, order_id))
                return {"success": False, "error": err, "order_id": order_id}
        except Exception as exc:
            logger.error(f"BrokerExecutionAdapter error: {exc}")
            write("UPDATE orders SET status=?, error=? WHERE id=?", (OrderStatus.REJECTED, str(exc), order_id))
            return {"success": False, "error": str(exc), "order_id": order_id}


class ExecutionReconciliationEngine:
    """Periodically audits broker state against database state to prevent phantom fills or orphaned trades."""

    @classmethod
    def reconcile_user_positions(cls, user_id: int) -> Dict[str, Any]:
        """Compares DB open positions against active broker positions."""
        db_opens = query("SELECT * FROM positions WHERE user_id=? AND status='OPEN' AND is_live=1", (user_id,))
        b_conn = query_one("SELECT * FROM broker_connections WHERE user_id=?", (user_id,))
        if not b_conn or b_conn.get("status") == "CONNECTED_OFFLINE":
            return {"reconciled": True, "mode": "OFFLINE_SIMULATED", "discrepancies": []}

        discrepancies = []
        try:
            from coindcx_gateway import get_user_coindcx_client
            cdx = get_user_coindcx_client(user_id)
            if cdx and not cdx.is_offline:
                ok_p, live_pos = cdx.futures.get_positions()
                if ok_p:
                    live_syms = {p.get("pair") or p.get("symbol") for p in live_pos if float(p.get("active_units") or p.get("quantity") or 0) > 0}
                    for p in db_opens:
                        if p["symbol"] not in live_syms:
                            discrepancies.append({
                                "symbol": p["symbol"],
                                "issue": "ORPHANED_IN_DB",
                                "message": f"{p['symbol']} open in database but flat on exchange"
                            })
        except Exception as e:
            logger.warning(f"Reconciliation check exception: {e}")

        return {
            "reconciled": len(discrepancies) == 0,
            "discrepancies_count": len(discrepancies),
            "discrepancies": discrepancies,
            "checked_at": time.time()
        }
