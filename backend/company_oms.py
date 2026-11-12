"""
ARAA Company Trading Platform — 16-State Order Management System & Position Engine (Phase 8).

Implements the exact workflow:
Signal/Intent -> Market Pool Selection -> Independent RiskGuardian -> Funds Check
-> UniversalBrokerManager (or Isolated Paper Simulator) -> 16-State OMS
-> Confirmed Partial/Full Executions (`broker_executions`) -> Position Update -> Company Ledger.

Strict Rules:
- Unique `idempotency_key` required on all order intents (prevents duplicates on retries/timeouts).
- Never create positions from unfilled/rejected/unknown intents.
- Never fall back to paper simulation if a live submission fails or times out.
- Network timeouts transition to `UNKNOWN` -> `RECONCILIATION_REQUIRED` and freeze pool until verified.
"""

import json
import time
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

try:
    from company_auth import log_company_audit
    from company_finance import MARKET_TO_POOL, CompanyCapitalManager, paise_to_inr_str, to_paise
    from company_ledger_recon import CompanyLedgerService, CompanyReconciliationService
    from company_risk_guardian import CompanyRiskGuardian
    from database import query, query_one, write
    from universal_broker_manager import UniversalBrokerManager
except ImportError:
    from backend.company_auth import log_company_audit
    from backend.company_finance import MARKET_TO_POOL, CompanyCapitalManager, paise_to_inr_str, to_paise
    from backend.company_ledger_recon import CompanyLedgerService, CompanyReconciliationService
    from backend.company_risk_guardian import CompanyRiskGuardian
    from backend.database import query, query_one, write
    from backend.universal_broker_manager import UniversalBrokerManager


OMS_STATES = (
    "CREATED",
    "RISK_PENDING",
    "RISK_REJECTED",
    "APPROVED",
    "SUBMISSION_PENDING",
    "SUBMITTED",
    "ACKNOWLEDGED",
    "OPEN",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCEL_PENDING",
    "CANCELLED",
    "REJECTED",
    "UNKNOWN",
    "RECONCILIATION_REQUIRED",
    "FAILED",
)


class CompanyOMS:
    """Institutional 16-state Order Management System with idempotency and Paper/Live isolation."""

    @staticmethod
    def submit_order_intent(
        company_id: int,
        account_id: str,
        symbol: str,
        side: str,
        quantity: Any,
        order_type: str = "MARKET",
        exchange: Optional[str] = None,
        limit_price: Optional[Any] = None,
        stop_price: Optional[Any] = None,
        stop_loss: Optional[Any] = None,
        target_price: Optional[Any] = None,
        product: Optional[str] = None,
        strategy_id: str = "",
        strategy_version_id: str = "",
        signal_id: str = "",
        execution_mode: str = "PAPER",
        idempotency_key: str = "",
        actor: Optional[Dict[str, Any]] = None,
        ip_address: str = "",
    ) -> Dict[str, Any]:
        clean_idem = (idempotency_key or "").strip()
        if not clean_idem:
            return {"success": False, "error": "idempotency_key is required on every order intent", "code": 400}

        # Idempotent duplicate check BEFORE creating new order
        existing = query_one("SELECT * FROM order_intents WHERE idempotency_key=?", (clean_idem,))
        if existing:
            ord_row = query_one("SELECT * FROM broker_orders WHERE intent_id=?", (existing["intent_id"],))
            return {
                "success": existing["status"] not in ("RISK_REJECTED", "REJECTED", "FAILED", "UNKNOWN", "RECONCILIATION_REQUIRED"),
                "duplicate_prevented": True,
                "intent": existing,
                "order": ord_row,
            }

        acc = query_one("SELECT * FROM company_trading_accounts WHERE company_id=? AND account_id=?", (company_id, account_id))
        if not acc:
            return {"success": False, "error": f"Company account {account_id} not found", "code": 404}

        mode = str(execution_mode or "PAPER").strip().upper()
        if mode not in ("PAPER", "LIVE"):
            return {"success": False, "error": "execution_mode must be PAPER or LIVE", "code": 400}

        market_scope = acc["market_scope"]
        provider = acc["provider"]
        pool_id = MARKET_TO_POOL[market_scope]
        clean_sym = (symbol or "").strip().upper()
        clean_side = (side or "").strip().upper()
        clean_otype = (order_type or "MARKET").strip().upper()
        ex = (exchange or ("NSE" if market_scope == "INDIA" else "COINDCX_SPOT")).strip().upper()
        prod = (product or ("CNC" if market_scope == "INDIA" else "SPOT")).strip().upper()

        qty_dec = Decimal(str(quantity))
        intent_id = f"int_{uuid.uuid4().hex[:14].upper()}"
        now = time.time()

        # State: CREATED -> RISK_PENDING
        write(
            "INSERT INTO order_intents("
            "intent_id, company_id, pool_id, account_id, strategy_id, strategy_version_id, signal_id, "
            "market_scope, provider, symbol, exchange, side, order_type, product, quantity_str, "
            "limit_price_str, stop_price_str, stop_loss_str, target_price_str, execution_mode, "
            "idempotency_key, status, created_by, created_at, updated_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'RISK_PENDING',?,?,?)",
            (
                intent_id,
                company_id,
                pool_id,
                account_id,
                strategy_id,
                strategy_version_id,
                signal_id,
                market_scope,
                provider,
                clean_sym,
                ex,
                clean_side,
                clean_otype,
                prod,
                str(qty_dec),
                str(limit_price or ""),
                str(stop_price or ""),
                str(stop_loss or ""),
                str(target_price or ""),
                mode,
                clean_idem,
                actor["id"] if actor else None,
                now,
                now,
            ),
        )
        intent_row = query_one("SELECT * FROM order_intents WHERE intent_id=?", (intent_id,))

        # Resolve quote for order value estimation & freshness check
        adapter = UniversalBrokerManager.get_adapter(company_id, account_id)
        quote = adapter.get_quote(clean_sym, ex)
        if limit_price and Decimal(str(limit_price)) > 0:
            est_px = Decimal(str(limit_price))
            q_ts = quote.get("timestamp") if quote.get("ok") else time.time()
        elif quote.get("ok") and quote.get("ltp"):
            est_px = Decimal(str(quote["ltp"]))
            q_ts = quote.get("timestamp")
        else:
            write(
                "UPDATE order_intents SET status='RISK_REJECTED', rejection_reason='Market quote unavailable', updated_at=? WHERE intent_id=?",
                (time.time(), intent_id),
            )
            return {"success": False, "status": "RISK_REJECTED", "error": f"Market quote unavailable for {clean_sym}", "intent_id": intent_id}

        order_val_paise = to_paise(qty_dec * est_px)

        # Independent Risk Guardian Gate
        risk_res = CompanyRiskGuardian.evaluate_order_intent(
            company_id=company_id,
            pool_id=pool_id,
            account_id=account_id,
            intent=intent_row,
            order_value_paise=order_val_paise,
            quote_timestamp=q_ts,
        )
        if not risk_res.get("approved"):
            write(
                "UPDATE order_intents SET status='RISK_REJECTED', rejection_reason=?, updated_at=? WHERE intent_id=?",
                (risk_res.get("reason", "Risk veto"), time.time(), intent_id),
            )
            return {
                "success": False,
                "status": "RISK_REJECTED",
                "rule_code": risk_res.get("rule_code"),
                "error": risk_res.get("reason"),
                "intent_id": intent_id,
            }

        # State: APPROVED -> SUBMISSION_PENDING
        order_id = f"ord_{uuid.uuid4().hex[:14].upper()}"
        write("UPDATE order_intents SET status='APPROVED', updated_at=? WHERE intent_id=?", (time.time(), intent_id))
        write(
            "INSERT INTO broker_orders("
            "order_id, intent_id, company_id, pool_id, account_id, strategy_id, strategy_version_id, "
            "market_scope, provider, symbol, exchange, side, order_type, quantity_str, limit_price_str, "
            "stop_price_str, idempotency_key, status, execution_mode, created_at, updated_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'SUBMISSION_PENDING',?,?,?)",
            (
                order_id,
                intent_id,
                company_id,
                pool_id,
                account_id,
                strategy_id,
                strategy_version_id,
                market_scope,
                provider,
                clean_sym,
                ex,
                clean_side,
                clean_otype,
                str(qty_dec),
                str(limit_price or ""),
                str(stop_price or ""),
                clean_idem,
                mode,
                time.time(),
                time.time(),
            ),
        )

        order_spec = {
            "symbol": clean_sym,
            "exchange": ex,
            "side": clean_side,
            "order_type": clean_otype,
            "product": prod,
            "quantity": int(qty_dec) if market_scope == "INDIA" else str(qty_dec),
            "price": float(limit_price) if limit_price else float(est_px),
            "trigger_price": float(stop_price) if stop_price else 0.0,
            "idempotency_key": clean_idem,
            "leverage": 1.0,
        }

        if mode == "PAPER":
            # Strictly isolated Paper execution (never touches real broker)
            return CompanyOMS._execute_paper_order(order_id, intent_id, company_id, pool_id, account_id, strategy_id, strategy_version_id, market_scope, provider, clean_sym, ex, clean_side, qty_dec, est_px, stop_loss, target_price)

        # LIVE Execution via UniversalBrokerManager (NO paper fallback allowed!)
        res = UniversalBrokerManager.route_order_for_account(company_id, account_id, pool_id, order_spec)
        now2 = time.time()

        if res.get("status") == "UNKNOWN":
            write(
                "UPDATE broker_orders SET status='UNKNOWN', provider_response_json=?, updated_at=? WHERE order_id=?",
                (json.dumps(res, default=str), now2, order_id),
            )
            write("UPDATE order_intents SET status='UNKNOWN', updated_at=? WHERE intent_id=?", (now2, intent_id))
            # Freeze pool for reconciliation safety upon ambiguous timeout
            write(
                "UPDATE company_capital_pools SET reconciliation_status='MISMATCH_HALTED', updated_at=? WHERE company_id=? AND pool_id=?",
                (now2, company_id, pool_id),
            )
            log_company_audit(
                company_id=company_id,
                action="LIVE_ORDER_UNKNOWN_TIMEOUT",
                actor=actor,
                resource_type="BROKER_ORDER",
                resource_id=order_id,
                after={"pool_id": pool_id, "symbol": clean_sym, "status": "UNKNOWN"},
                status="WARNING",
                ip_address=ip_address,
            )
            return {
                "success": False,
                "status": "UNKNOWN",
                "order_id": order_id,
                "intent_id": intent_id,
                "error": res.get("error", "Order submission timeout; marked UNKNOWN for reconciliation"),
            }

        if not res.get("ok"):
            write(
                "UPDATE broker_orders SET status='REJECTED', provider_response_json=?, updated_at=? WHERE order_id=?",
                (json.dumps(res, default=str), now2, order_id),
            )
            write(
                "UPDATE order_intents SET status='REJECTED', rejection_reason=?, updated_at=? WHERE intent_id=?",
                (res.get("error", "Broker rejected order"), now2, intent_id),
            )
            return {
                "success": False,
                "status": "REJECTED",
                "order_id": order_id,
                "intent_id": intent_id,
                "error": res.get("error", "Order rejected by broker"),
            }

        provider_oid = str(res.get("provider_order_id") or "")
        write(
            "UPDATE broker_orders SET status='SUBMITTED', provider_order_id=?, provider_response_json=?, updated_at=? WHERE order_id=?",
            (provider_oid, json.dumps(res, default=str), now2, order_id),
        )
        write("UPDATE order_intents SET status='SUBMITTED', updated_at=? WHERE intent_id=?", (now2, intent_id))

        # Immediately poll confirmed status/fills if synchronous adapter reports fills (never fabricate fills!)
        CompanyOMS.sync_order_fills(company_id, order_id, stop_loss=stop_loss, target_price=target_price)
        final_order = query_one("SELECT * FROM broker_orders WHERE order_id=?", (order_id,))
        log_company_audit(
            company_id=company_id,
            action="LIVE_ORDER_SUBMITTED",
            actor=actor,
            resource_type="BROKER_ORDER",
            resource_id=order_id,
            after={"provider_order_id": provider_oid, "status": final_order["status"], "symbol": clean_sym},
            ip_address=ip_address,
        )
        return {"success": True, "order": final_order, "intent_id": intent_id}

    @staticmethod
    def _execute_paper_order(
        order_id: str,
        intent_id: str,
        company_id: int,
        pool_id: str,
        account_id: str,
        strategy_id: str,
        strategy_version_id: str,
        market_scope: str,
        provider: str,
        symbol: str,
        exchange: str,
        side: str,
        qty_dec: Decimal,
        fill_px: Decimal,
        stop_loss: Optional[Any],
        target_price: Optional[Any],
    ) -> Dict[str, Any]:
        """Simulates fill strictly inside execution_mode='PAPER' without touching live ledger."""
        now = time.time()
        val_paise = to_paise(qty_dec * fill_px)
        fee_paise = max(1, int(val_paise * Decimal("0.0005")))
        sim_oid = f"PAPER-{uuid.uuid4().hex[:10].upper()}"
        exec_id = f"pex_{uuid.uuid4().hex[:12].upper()}"

        write(
            "UPDATE broker_orders SET status='FILLED', provider_order_id=?, filled_qty_str=?, "
            "avg_fill_price_str=?, fees_paise=?, updated_at=? WHERE order_id=?",
            (sim_oid, str(qty_dec), str(fill_px), fee_paise, now, order_id),
        )
        write("UPDATE order_intents SET status='FILLED', updated_at=? WHERE intent_id=?", (now, intent_id))
        write(
            "INSERT INTO broker_executions("
            "execution_id, order_id, company_id, pool_id, account_id, provider_trade_id, symbol, "
            "side, fill_qty_str, fill_price_str, fill_value_paise, fee_paise, tax_paise, execution_mode, executed_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,'PAPER',?)",
            (exec_id, order_id, company_id, pool_id, account_id, sim_oid, symbol, side, str(qty_dec), str(fill_px), val_paise, fee_paise, now),
        )
        CompanyOMS._apply_fill_to_position(
            company_id, pool_id, account_id, strategy_id, strategy_version_id,
            market_scope, provider, symbol, exchange, side, qty_dec, fill_px, fee_paise, "PAPER",
            stop_loss, target_price,
        )
        return {"success": True, "order": query_one("SELECT * FROM broker_orders WHERE order_id=?", (order_id,)), "intent_id": intent_id}

    @staticmethod
    def record_confirmed_fill(
        company_id: int,
        order_id: str,
        fill_qty: Any,
        fill_price: Any,
        provider_trade_id: str,
        fee_paise: int = 0,
        tax_paise: int = 0,
        stop_loss: Optional[Any] = None,
        target_price: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Records an actual broker fill (partial or complete) and updates position + LIVE ledger."""
        ord_row = query_one("SELECT * FROM broker_orders WHERE company_id=? AND order_id=?", (company_id, order_id))
        if not ord_row:
            return {"success": False, "error": "Order not found"}
        if query_one("SELECT execution_id FROM broker_executions WHERE order_id=? AND provider_trade_id=?", (order_id, provider_trade_id)):
            return {"success": True, "duplicate_fill_ignored": True, "order": ord_row}

        f_qty = Decimal(str(fill_qty))
        f_px = Decimal(str(fill_price))
        if f_qty <= 0 or f_px <= 0:
            return {"success": False, "error": "Confirmed fill qty and price must be > 0"}

        prev_filled = Decimal(str(ord_row["filled_qty_str"] or "0"))
        prev_avg = Decimal(str(ord_row["avg_fill_price_str"] or "0"))
        total_req = Decimal(str(ord_row["quantity_str"]))
        new_filled = min(total_req, prev_filled + f_qty)
        new_avg = ((prev_filled * prev_avg) + (f_qty * f_px)) / (prev_filled + f_qty)

        new_status = "FILLED" if new_filled >= total_req else "PARTIALLY_FILLED"
        now = time.time()
        val_paise = to_paise(f_qty * f_px)
        exec_id = f"exe_{uuid.uuid4().hex[:14].upper()}"

        write(
            "INSERT INTO broker_executions("
            "execution_id, order_id, company_id, pool_id, account_id, provider_trade_id, symbol, side, "
            "fill_qty_str, fill_price_str, fill_value_paise, fee_paise, tax_paise, execution_mode, executed_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                exec_id,
                order_id,
                company_id,
                ord_row["pool_id"],
                ord_row["account_id"],
                provider_trade_id,
                ord_row["symbol"],
                ord_row["side"],
                str(f_qty),
                str(f_px),
                val_paise,
                int(fee_paise),
                int(tax_paise),
                ord_row["execution_mode"],
                now,
            ),
        )
        write(
            "UPDATE broker_orders SET status=?, filled_qty_str=?, avg_fill_price_str=?, "
            "fees_paise=fees_paise+?, updated_at=? WHERE order_id=?",
            (new_status, str(new_filled), str(new_avg), int(fee_paise), now, order_id),
        )
        write("UPDATE order_intents SET status=?, updated_at=? WHERE intent_id=?", (new_status, now, ord_row["intent_id"]))

        realized_pnl_paise = CompanyOMS._apply_fill_to_position(
            company_id,
            ord_row["pool_id"],
            ord_row["account_id"],
            ord_row["strategy_id"],
            ord_row["strategy_version_id"],
            ord_row["market_scope"],
            ord_row["provider"],
            ord_row["symbol"],
            ord_row["exchange"],
            ord_row["side"],
            f_qty,
            f_px,
            int(fee_paise),
            ord_row["execution_mode"],
            stop_loss,
            target_price,
        )

        # Post immutable live ledger entry (skipped strictly for PAPER mode)
        CompanyLedgerService.record_execution_entry(
            company_id=company_id,
            pool_id=ord_row["pool_id"],
            account_id=ord_row["account_id"],
            execution_id=exec_id,
            symbol=ord_row["symbol"],
            side=ord_row["side"],
            value_paise=val_paise,
            fee_paise=int(fee_paise),
            tax_paise=int(tax_paise),
            realized_pnl_paise=realized_pnl_paise,
            execution_mode=ord_row["execution_mode"],
        )
        return {"success": True, "execution_id": exec_id, "order": query_one("SELECT * FROM broker_orders WHERE order_id=?", (order_id,))}

    @staticmethod
    def _apply_fill_to_position(
        company_id: int,
        pool_id: str,
        account_id: str,
        strategy_id: str,
        strategy_version_id: str,
        market_scope: str,
        provider: str,
        symbol: str,
        exchange: str,
        side: str,
        qty: Decimal,
        price: Decimal,
        fee_paise: int,
        execution_mode: str,
        stop_loss: Optional[Any],
        target_price: Optional[Any],
    ) -> int:
        now = time.time()
        open_pos = query_one(
            "SELECT * FROM company_positions WHERE company_id=? AND pool_id=? AND account_id=? "
            "AND symbol=? AND execution_mode=? AND status='OPEN' LIMIT 1",
            (company_id, pool_id, account_id, symbol, execution_mode),
        )
        if side.upper() == "BUY":
            if open_pos:
                old_q = Decimal(str(open_pos["quantity_str"]))
                old_p = Decimal(str(open_pos["avg_entry_price_str"]))
                new_q = old_q + qty
                new_avg = ((old_q * old_p) + (qty * price)) / new_q
                write(
                    "UPDATE company_positions SET quantity_str=?, avg_entry_price_str=?, current_price_str=?, "
                    "fees_paise=fees_paise+?, updated_at=? WHERE position_id=?",
                    (str(new_q), str(new_avg), str(price), int(fee_paise), now, open_pos["position_id"]),
                )
            else:
                pid = f"pos_{uuid.uuid4().hex[:14].upper()}"
                write(
                    "INSERT INTO company_positions("
                    "position_id, company_id, pool_id, account_id, strategy_id, strategy_version_id, "
                    "market_scope, provider, symbol, exchange, side, quantity_str, avg_entry_price_str, "
                    "current_price_str, stop_loss_str, take_profit_str, fees_paise, status, execution_mode, opened_at, updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, ?,?,'OPEN',?,?,?)",
                    (
                        pid,
                        company_id,
                        pool_id,
                        account_id,
                        strategy_id,
                        strategy_version_id,
                        market_scope,
                        provider,
                        symbol,
                        exchange,
                        "LONG",
                        str(qty),
                        str(price),
                        str(price),
                        str(stop_loss or ""),
                        str(target_price or ""),
                        int(fee_paise),
                        execution_mode,
                        now,
                        now,
                    ),
                )
            return 0
        else:
            # SELL reduces/closes existing LONG position
            if not open_pos:
                return 0
            old_q = Decimal(str(open_pos["quantity_str"]))
            entry_p = Decimal(str(open_pos["avg_entry_price_str"]))
            closed_q = min(old_q, qty)
            pnl_paise = to_paise((price - entry_p) * closed_q) - int(fee_paise)
            rem_q = old_q - closed_q
            if rem_q <= 0:
                write(
                    "UPDATE company_positions SET quantity_str='0', current_price_str=?, realized_pnl_paise=realized_pnl_paise+?, "
                    "fees_paise=fees_paise+?, exit_reason='CONFIRMED_BROKER_EXIT', status='CLOSED', closed_at=?, updated_at=? "
                    "WHERE position_id=?",
                    (str(price), pnl_paise, int(fee_paise), now, now, open_pos["position_id"]),
                )
            else:
                write(
                    "UPDATE company_positions SET quantity_str=?, current_price_str=?, realized_pnl_paise=realized_pnl_paise+?, "
                    "fees_paise=fees_paise+?, updated_at=? WHERE position_id=?",
                    (str(rem_q), str(price), pnl_paise, int(fee_paise), now, open_pos["position_id"]),
                )
            return pnl_paise

    @staticmethod
    def sync_order_fills(company_id: int, order_id: str, stop_loss: Optional[Any] = None, target_price: Optional[Any] = None) -> Dict[str, Any]:
        ord_row = query_one("SELECT * FROM broker_orders WHERE company_id=? AND order_id=?", (company_id, order_id))
        if not ord_row or not ord_row.get("provider_order_id") or ord_row["execution_mode"] != "LIVE":
            return {"ok": False}

        adapter = UniversalBrokerManager.get_adapter(company_id, ord_row["account_id"])
        st = adapter.get_order_status(ord_row["provider_order_id"])
        if not st.get("ok"):
            return st

        prov_status = str(st.get("status", "")).upper()
        filled_qty = Decimal(str(st.get("filled_quantity") or "0"))
        avg_px = Decimal(str(st.get("average_price") or "0"))

        if prov_status in ("COMPLETE", "FILLED") and filled_qty > 0 and avg_px > 0:
            CompanyOMS.record_confirmed_fill(
                company_id,
                order_id,
                filled_qty - Decimal(str(ord_row["filled_qty_str"] or "0")),
                avg_px,
                provider_trade_id=f"{ord_row['provider_order_id']}-FULL",
                fee_paise=to_paise(st.get("fee") or 0),
                stop_loss=stop_loss,
                target_price=target_price,
            )
        elif prov_status in ("OPEN", "TRIGGER PENDING", "ACKNOWLEDGED"):
            write("UPDATE broker_orders SET status='OPEN', updated_at=? WHERE order_id=?", (time.time(), order_id))
        elif prov_status in ("CANCELLED", "REJECTED") and Decimal(str(ord_row["filled_qty_str"] or "0")) == 0:
            mapped = "CANCELLED" if prov_status == "CANCELLED" else "REJECTED"
            write("UPDATE broker_orders SET status=?, updated_at=? WHERE order_id=?", (mapped, time.time(), order_id))
            write("UPDATE order_intents SET status=?, updated_at=? WHERE intent_id=?", (mapped, time.time(), ord_row["intent_id"]))
        return {"ok": True, "order": query_one("SELECT * FROM broker_orders WHERE order_id=?", (order_id,))}

    @staticmethod
    def cancel_order(company_id: int, order_id: str, actor: Dict[str, Any], ip_address: str = "") -> Dict[str, Any]:
        ord_row = query_one("SELECT * FROM broker_orders WHERE company_id=? AND order_id=?", (company_id, order_id))
        if not ord_row:
            return {"success": False, "error": "Order not found"}
        if ord_row["status"] in ("FILLED", "CANCELLED", "REJECTED", "RISK_REJECTED"):
            return {"success": False, "error": f"Order in terminal state {ord_row['status']}"}

        now = time.time()
        write("UPDATE broker_orders SET status='CANCEL_PENDING', updated_at=? WHERE order_id=?", (now, order_id))

        if ord_row["execution_mode"] == "PAPER" or not ord_row.get("provider_order_id"):
            write("UPDATE broker_orders SET status='CANCELLED', updated_at=? WHERE order_id=?", (now, order_id))
            write("UPDATE order_intents SET status='CANCELLED', updated_at=? WHERE intent_id=?", (now, ord_row["intent_id"]))
            return {"success": True, "order": query_one("SELECT * FROM broker_orders WHERE order_id=?", (order_id,))}

        adapter = UniversalBrokerManager.get_adapter(company_id, ord_row["account_id"])
        res = adapter.cancel_order(ord_row["provider_order_id"])
        if not res.get("ok"):
            return {"success": False, "error": res.get("error", "Broker cancel failed")}

        write("UPDATE broker_orders SET status='CANCELLED', updated_at=? WHERE order_id=?", (time.time(), order_id))
        write("UPDATE order_intents SET status='CANCELLED', updated_at=? WHERE intent_id=?", (time.time(), ord_row["intent_id"]))
        log_company_audit(
            company_id=company_id,
            action="ORDER_CANCELLED",
            actor=actor,
            resource_type="BROKER_ORDER",
            resource_id=order_id,
            ip_address=ip_address,
        )
        return {"success": True, "order": query_one("SELECT * FROM broker_orders WHERE order_id=?", (order_id,))}

    @staticmethod
    def flatten_preview(company_id: int, pool_id: str, execution_mode: str = "PAPER") -> Dict[str, Any]:
        positions = query(
            "SELECT * FROM company_positions WHERE company_id=? AND pool_id=? AND execution_mode=? AND status='OPEN'",
            (company_id, pool_id, execution_mode.upper()),
        )
        return {
            "pool_id": pool_id,
            "execution_mode": execution_mode.upper(),
            "open_positions_count": len(positions),
            "positions": positions,
            "requires_explicit_confirm": True,
        }

    @staticmethod
    def flatten_confirm(
        company_id: int,
        pool_id: str,
        execution_mode: str,
        confirm_token: str,
        actor: Dict[str, Any],
        ip_address: str = "",
    ) -> Dict[str, Any]:
        if str(confirm_token or "").strip().upper() != f"CONFIRM_FLATTEN_{pool_id}":
            return {
                "success": False,
                "error": f"Confirmation token must equal CONFIRM_FLATTEN_{pool_id}",
            }
        mode = execution_mode.upper()
        positions = query(
            "SELECT * FROM company_positions WHERE company_id=? AND pool_id=? AND execution_mode=? AND status='OPEN'",
            (company_id, pool_id, mode),
        )
        results = []
        for p in positions:
            r = CompanyOMS.submit_order_intent(
                company_id=company_id,
                account_id=p["account_id"],
                symbol=p["symbol"],
                side="SELL",
                quantity=p["quantity_str"],
                order_type="MARKET",
                exchange=p["exchange"],
                stop_loss=p["stop_loss_str"] or p["avg_entry_price_str"],
                execution_mode=mode,
                idempotency_key=f"flat_{p['position_id']}_{int(time.time())}",
                actor=actor,
                ip_address=ip_address,
            )
            results.append({"position_id": p["position_id"], "symbol": p["symbol"], "result": r})
        return {"success": True, "closed_attempts": len(results), "results": results}
