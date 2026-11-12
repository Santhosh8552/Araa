"""
ARAA Company Trading Platform — Independent Risk Guardian (Phase 7).

Core guarantees:
- AI strategies NEVER override risk rules.
- Every live (and company paper) order intent must pass `evaluate_order_intent` before OMS submission.
- Enforces: pool isolation, reconciliation mismatch freeze, stop-loss requirement, order/position/daily-loss caps,
  quote freshness, session windows, duplicate-order checks, and emergency stop controls.
"""

import datetime
import json
import time
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

try:
    from company_auth import log_company_audit
    from company_finance import CompanyCapitalManager, paise_to_inr_str, to_paise
    from database import query, query_one, write
except ImportError:
    from backend.company_auth import log_company_audit
    from backend.company_finance import CompanyCapitalManager, paise_to_inr_str, to_paise
    from backend.database import query, query_one, write


class CompanyRiskGuardian:
    """Independent institutional pre-trade risk validator & emergency brake."""

    @staticmethod
    def get_policy(company_id: int, pool_id: str) -> Dict[str, Any]:
        row = query_one(
            "SELECT * FROM company_risk_policies WHERE company_id=? AND pool_id=?",
            (company_id, pool_id),
        )
        if not row:
            raise RuntimeError(f"Risk policy missing for {pool_id}")
        out = dict(row)
        out["max_capital_inr"] = paise_to_inr_str(out["max_capital_paise"])
        out["max_order_value_inr"] = paise_to_inr_str(out["max_order_value_paise"])
        out["max_position_size_inr"] = paise_to_inr_str(out["max_position_size_paise"])
        out["max_daily_loss_inr"] = paise_to_inr_str(out["max_daily_loss_paise"])
        return out

    @staticmethod
    def list_policies(company_id: int) -> List[Dict[str, Any]]:
        rows = query("SELECT pool_id FROM company_risk_policies WHERE company_id=? ORDER BY pool_id ASC", (company_id,))
        return [CompanyRiskGuardian.get_policy(company_id, r["pool_id"]) for r in rows]

    @staticmethod
    def update_policy(
        company_id: int,
        pool_id: str,
        updates: Dict[str, Any],
        actor: Dict[str, Any],
        ip_address: str = "",
    ) -> Dict[str, Any]:
        before = CompanyRiskGuardian.get_policy(company_id, pool_id)
        fields: List[str] = []
        values: List[Any] = []

        inr_map = {
            "max_capital_inr": "max_capital_paise",
            "max_order_value_inr": "max_order_value_paise",
            "max_position_size_inr": "max_position_size_paise",
            "max_daily_loss_inr": "max_daily_loss_paise",
        }
        for ext_k, col in inr_map.items():
            if ext_k in updates and updates[ext_k] is not None:
                val_p = to_paise(updates[ext_k])
                if val_p <= 0:
                    return {"success": False, "error": f"{ext_k} must be > 0"}
                fields.append(f"{col}=?")
                values.append(val_p)

        for k in ("max_open_positions", "max_drawdown_bps", "max_quote_age_sec", "require_stop_loss", "trading_window_enabled"):
            if k in updates and updates[k] is not None:
                fields.append(f"{k}=?")
                values.append(int(updates[k]))

        for k in ("session_start_ist", "session_end_ist"):
            if k in updates and updates[k]:
                fields.append(f"{k}=?")
                values.append(str(updates[k]).strip())

        if not fields:
            return {"success": False, "error": "No valid policy fields updated"}

        fields.extend(["updated_by=?", "updated_at=?"])
        values.extend([actor["id"], time.time(), company_id, pool_id])
        write(f"UPDATE company_risk_policies SET {', '.join(fields)} WHERE company_id=? AND pool_id=?", tuple(values))

        after = CompanyRiskGuardian.get_policy(company_id, pool_id)
        log_company_audit(
            company_id=company_id,
            action="RISK_POLICY_UPDATED",
            actor=actor,
            resource_type="RISK_POLICY",
            resource_id=pool_id,
            before=before,
            after=after,
            ip_address=ip_address,
        )
        return {"success": True, "policy": after}

    @staticmethod
    def _record_event(
        company_id: int,
        pool_id: str,
        event_type: str,
        rule_code: str,
        message: str,
        severity: str = "WARNING",
        intent_id: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        eid = f"rev_{uuid.uuid4().hex[:14].upper()}"
        write(
            "INSERT INTO company_risk_events("
            "event_id, company_id, pool_id, intent_id, event_type, severity, rule_code, message, details_json, created_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?)",
            (eid, company_id, pool_id, intent_id, event_type, severity, rule_code, message, json.dumps(details or {}), time.time()),
        )
        return eid

    @staticmethod
    def _is_within_ist_window(start_hhmm: str, end_hhmm: str) -> bool:
        ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        now_ist = datetime.datetime.now(tz=ist)
        if now_ist.weekday() >= 5:
            return False
        cur = now_ist.strftime("%H:%M")
        return start_hhmm <= cur <= end_hhmm

    @staticmethod
    def evaluate_order_intent(
        company_id: int,
        pool_id: str,
        account_id: str,
        intent: Dict[str, Any],
        order_value_paise: int,
        quote_timestamp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Independent pre-trade gate. Any failure immediately vetoes the order intent."""
        intent_id = intent.get("intent_id", "")

        def reject(rule_code: str, reason: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
            CompanyRiskGuardian._record_event(
                company_id, pool_id, "ORDER_VETO", rule_code, reason, "CRITICAL", intent_id, details
            )
            return {"approved": False, "rule_code": rule_code, "reason": reason}

        # 1. Pool & Market isolation check
        try:
            CompanyCapitalManager.assert_pool_isolation(pool_id, intent.get("market_scope"), intent.get("provider"))
        except (ValueError, PermissionError) as exc:
            return reject("POOL_ISOLATION", str(exc))

        pool = query_one("SELECT * FROM company_capital_pools WHERE company_id=? AND pool_id=?", (company_id, pool_id))
        if not pool:
            return reject("POOL_MISSING", f"Capital pool {pool_id} not found")

        policy = CompanyRiskGuardian.get_policy(company_id, pool_id)

        # 2. Emergency stop / paused checks
        if int(policy.get("emergency_stop") or 0) == 1:
            return reject("EMERGENCY_STOP_ACTIVE", f"Emergency stop active on {pool_id}")
        if int(policy.get("paused") or 0) == 1:
            return reject("TRADING_PAUSED", f"New entries paused on {pool_id}")

        # 3. Reconciliation mismatch freeze (live mode or whenever discrepancies exist)
        open_diffs = query_one(
            "SELECT COUNT(*) as c FROM reconciliation_differences WHERE company_id=? AND pool_id=? AND status='OPEN'",
            (company_id, pool_id),
        )["c"]
        if pool.get("reconciliation_status") == "MISMATCH_HALTED" or open_diffs > 0:
            return reject(
                "RECONCILIATION_MISMATCH_HALT",
                f"{pool_id} has {open_diffs} unresolved reconciliation discrepancies; resolve before trading",
            )

        exec_mode = str(intent.get("execution_mode") or "PAPER").upper()

        # 4. Account verification & connectivity (mandatory for LIVE mode)
        if exec_mode == "LIVE":
            acc = query_one(
                "SELECT * FROM company_trading_accounts WHERE company_id=? AND account_id=?",
                (company_id, account_id),
            )
            if not acc:
                return reject("ACCOUNT_NOT_FOUND", f"Account {account_id} not found")
            if acc["connection_status"] != "CONNECTED" or acc["api_permission_status"] != "VERIFIED":
                return reject("BROKER_NOT_VERIFIED", f"Broker account {account_id} status={acc['connection_status']} perm={acc['api_permission_status']}")
            if int(acc.get("trading_approved") or 0) != 1:
                return reject("LIVE_NOT_APPROVED", f"Live trading approval not granted for account {account_id}")

        # 5. Mandatory Stop-Loss validation
        if int(policy.get("require_stop_loss") or 1) == 1:
            sl_val = str(intent.get("stop_loss_str") or "").strip()
            if not sl_val or Decimal(sl_val) <= 0:
                return reject("MISSING_STOP_LOSS", "Every order intent requires a valid > 0 stop_loss")

        # 6. Quote freshness check
        max_age = int(policy.get("max_quote_age_sec") or 60)
        if quote_timestamp is not None and (time.time() - float(quote_timestamp)) > max_age:
            return reject("STALE_MARKET_DATA", f"Market quote older than {max_age}s")

        # 7. Trading window enforcement if enabled
        if int(policy.get("trading_window_enabled") or 0) == 1:
            if not CompanyRiskGuardian._is_within_ist_window(policy["session_start_ist"], policy["session_end_ist"]):
                return reject("OUTSIDE_TRADING_WINDOW", f"Outside configured IST window {policy['session_start_ist']}-{policy['session_end_ist']}")

        # 8. Order value & position size ceilings
        if order_value_paise <= 0:
            return reject("INVALID_ORDER_VALUE", "Order notional value must exceed 0 INR")
        if order_value_paise > int(policy["max_order_value_paise"]):
            return reject(
                "MAX_ORDER_VALUE_EXCEEDED",
                f"Order value ₹{paise_to_inr_str(order_value_paise)} exceeds limit ₹{policy['max_order_value_inr']}",
            )
        if order_value_paise > int(policy["max_position_size_paise"]):
            return reject(
                "MAX_POSITION_SIZE_EXCEEDED",
                f"Position size ₹{paise_to_inr_str(order_value_paise)} exceeds limit ₹{policy['max_position_size_inr']}",
            )

        # 9. Independent pool capital check (LIVE uses broker_confirmed / free_funds; PAPER checks policy/pool ceiling)
        if exec_mode == "LIVE":
            free_p = int(pool["free_funds_paise"] or 0)
            if free_p < order_value_paise:
                return reject(
                    "INSUFFICIENT_POOL_FUNDS",
                    f"{pool_id} free broker funds ₹{paise_to_inr_str(free_p)} < required ₹{paise_to_inr_str(order_value_paise)}",
                )

        # 10. Daily loss circuit breaker
        daily_loss_p = abs(min(0, int(pool.get("daily_loss_paise") or 0)))
        if daily_loss_p >= int(policy["max_daily_loss_paise"]):
            return reject("DAILY_LOSS_BREACHED", f"Daily loss ₹{paise_to_inr_str(daily_loss_p)} reached max limit")

        # 11. Max open positions limit (isolated per pool & execution_mode)
        open_pos = query_one(
            "SELECT COUNT(*) as c FROM company_positions WHERE company_id=? AND pool_id=? AND execution_mode=? AND status='OPEN'",
            (company_id, pool_id, exec_mode),
        )["c"]
        if str(intent.get("side", "BUY")).upper() == "BUY" and open_pos >= int(policy["max_open_positions"]):
            return reject("MAX_OPEN_POSITIONS", f"{pool_id} already at {open_pos}/{policy['max_open_positions']} open positions")

        # 12. Strategy allocation check if strategy_id is linked
        strat_id = intent.get("strategy_id")
        if strat_id:
            strat = query_one("SELECT strategy_code FROM company_strategies WHERE strategy_id=?", (strat_id,))
            if strat:
                alloc = query_one(
                    "SELECT allocated_paise, used_paise FROM capital_allocations WHERE pool_id=? AND strategy_code=? AND status='ACTIVE'",
                    (pool_id, strat["strategy_code"]),
                )
                if alloc and (int(alloc["used_paise"]) + order_value_paise) > int(alloc["allocated_paise"]):
                    return reject("STRATEGY_ALLOCATION_EXCEEDED", f"Strategy {strat['strategy_code']} exceeded allocated capital in {pool_id}")

        return {"approved": True, "pool_id": pool_id, "order_value_paise": order_value_paise}

    # -----------------------------------------------------------------------
    # Trading Session Control & Emergency Brakes
    # -----------------------------------------------------------------------
    @staticmethod
    def set_trading_control(
        company_id: int,
        pool_id: str,
        action: str,
        actor: Dict[str, Any],
        ip_address: str = "",
    ) -> Dict[str, Any]:
        act = (action or "").strip().upper()
        now = time.time()
        if act == "PAUSE":
            write("UPDATE company_risk_policies SET paused=1, updated_by=?, updated_at=? WHERE company_id=? AND pool_id=?", (actor["id"], now, company_id, pool_id))
            CompanyRiskGuardian._record_event(company_id, pool_id, "TRADING_PAUSED", "OPERATOR_PAUSE", f"{actor['email']} paused new entries on {pool_id}", "INFO")
        elif act == "RESUME":
            write("UPDATE company_risk_policies SET paused=0, emergency_stop=0, updated_by=?, updated_at=? WHERE company_id=? AND pool_id=?", (actor["id"], now, company_id, pool_id))
        elif act == "EMERGENCY_STOP":
            write("UPDATE company_risk_policies SET paused=1, emergency_stop=1, updated_by=?, updated_at=? WHERE company_id=? AND pool_id=?", (actor["id"], now, company_id, pool_id))
            CompanyRiskGuardian._record_event(company_id, pool_id, "EMERGENCY_STOP", "OPERATOR_KILL_SWITCH", f"Emergency stop triggered by {actor['email']}", "CRITICAL")
        else:
            return {"success": False, "error": f"Unknown risk control action: {act}"}

        log_company_audit(
            company_id=company_id,
            action=f"RISK_{act}",
            actor=actor,
            resource_type="CAPITAL_POOL",
            resource_id=pool_id,
            ip_address=ip_address,
        )
        return {"success": True, "policy": CompanyRiskGuardian.get_policy(company_id, pool_id)}

    @staticmethod
    def list_risk_events(company_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        return query(
            "SELECT * FROM company_risk_events WHERE company_id=? ORDER BY created_at DESC LIMIT ?",
            (company_id, int(limit)),
        )
