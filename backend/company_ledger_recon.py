"""
ARAA Company Trading Platform — Immutable Company Ledger, Automated Reconciliation & Compliance (Phase 9 & Sec 22).

Core guarantees:
- Immutable append-only `company_ledger_entries` in exact integer paise (no overwrites).
- Strictly separates LIVE broker-confirmed settlements from PAPER simulation.
- Reconciliation compares local balances/orders/fills/positions vs broker snapshots.
- Any mismatch records raw broker evidence in `reconciliation_differences` and freezes
  new entries (`reconciliation_status = 'MISMATCH_HALTED'`) until operator verification.
"""

import json
import time
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

try:
    from company_auth import log_company_audit
    from company_finance import MARKET_TO_POOL, paise_to_inr_str, to_paise
    from database import query, query_one, write, writes
    from universal_broker_manager import UniversalBrokerManager
except ImportError:
    from backend.company_auth import log_company_audit
    from backend.company_finance import MARKET_TO_POOL, paise_to_inr_str, to_paise
    from backend.database import query, query_one, write, writes
    from backend.universal_broker_manager import UniversalBrokerManager


class CompanyLedgerService:
    """Immutable financial trading ledger for live company executions and accounting records."""

    @staticmethod
    def record_execution_entry(
        company_id: int,
        pool_id: str,
        account_id: str,
        execution_id: str,
        symbol: str,
        side: str,
        value_paise: int,
        fee_paise: int = 0,
        tax_paise: int = 0,
        realized_pnl_paise: int = 0,
        execution_mode: str = "LIVE",
    ) -> Optional[str]:
        """Records ONLY LIVE broker-confirmed cashflows into `company_ledger_entries`."""
        if str(execution_mode or "").upper() != "LIVE":
            # Never contaminate real company ledger with paper simulation fills
            return None

        entry_id = f"led_{uuid.uuid4().hex[:14].upper()}"
        clean_side = side.upper()
        debit_acc = "2100_ASSET_HOLDINGS" if clean_side == "BUY" else f"1000_POOL_CASH_{pool_id}"
        credit_acc = f"1000_POOL_CASH_{pool_id}" if clean_side == "BUY" else "2100_ASSET_HOLDINGS"

        write(
            "INSERT INTO company_ledger_entries("
            "entry_id, company_id, pool_id, account_id, entry_type, source_type, source_id, "
            "source_classification, debit_account, credit_account, amount_paise, fee_paise, tax_paise, "
            "currency, execution_mode, narration, created_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'INR','LIVE',?,?)",
            (
                entry_id,
                company_id,
                pool_id,
                account_id,
                f"TRADE_{clean_side}",
                "EXECUTION",
                execution_id,
                "BROKER_CONFIRMED",
                debit_acc,
                credit_acc,
                int(value_paise),
                int(fee_paise),
                int(tax_paise),
                f"{clean_side} {symbol} (val=₹{paise_to_inr_str(value_paise)}, fee=₹{paise_to_inr_str(fee_paise)})",
                time.time(),
            ),
        )
        if fee_paise > 0 or tax_paise > 0 or realized_pnl_paise != 0:
            write(
                "UPDATE company_capital_pools SET fees_paise=fees_paise+?, taxes_expenses_paise=taxes_expenses_paise+?, "
                "realized_pnl_paise=realized_pnl_paise+?, updated_at=? WHERE company_id=? AND pool_id=?",
                (int(fee_paise), int(tax_paise), int(realized_pnl_paise), time.time(), company_id, pool_id),
            )
        return entry_id

    @staticmethod
    def record_adjustment(
        company_id: int,
        pool_id: str,
        amount_inr: Any,
        narration: str,
        actor: Dict[str, Any],
        source_id: str = "",
        ip_address: str = "",
    ) -> Dict[str, Any]:
        """Records a separate adjustment entry without overwriting historical ledger rows."""
        amt_p = to_paise(amount_inr)
        entry_id = f"adj_{uuid.uuid4().hex[:14].upper()}"
        write(
            "INSERT INTO company_ledger_entries("
            "entry_id, company_id, pool_id, account_id, entry_type, source_type, source_id, "
            "source_classification, debit_account, credit_account, amount_paise, currency, execution_mode, narration, created_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,'INR','LIVE',?,?)",
            (
                entry_id,
                company_id,
                pool_id,
                "",
                "ACCOUNTING_ADJUSTMENT",
                "MANUAL_ADJUSTMENT",
                source_id or entry_id,
                "ACCOUNTING_RECORD",
                f"1000_POOL_CASH_{pool_id}",
                "3900_RECON_ADJUSTMENTS",
                amt_p,
                narration,
                time.time(),
            ),
        )
        log_company_audit(
            company_id=company_id,
            action="LEDGER_ADJUSTMENT_RECORDED",
            actor=actor,
            resource_type="LEDGER_ENTRY",
            resource_id=entry_id,
            after={"pool_id": pool_id, "amount_inr": paise_to_inr_str(amt_p), "narration": narration},
            ip_address=ip_address,
        )
        return {"success": True, "entry_id": entry_id}

    @staticmethod
    def list_entries(company_id: int, pool_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        if pool_id:
            rows = query(
                "SELECT * FROM company_ledger_entries WHERE company_id=? AND pool_id=? ORDER BY created_at DESC LIMIT ?",
                (company_id, pool_id, int(limit)),
            )
        else:
            rows = query(
                "SELECT * FROM company_ledger_entries WHERE company_id=? ORDER BY created_at DESC LIMIT ?",
                (company_id, int(limit)),
            )
        return [{**r, "amount_inr": paise_to_inr_str(r["amount_paise"]), "fee_inr": paise_to_inr_str(r["fee_paise"])} for r in rows]


class CompanyReconciliationService:
    """Reconciles ARAA local orders/positions/balances against company broker snapshots."""

    @staticmethod
    def run_reconciliation(
        company_id: int,
        account_id: str,
        trigger_source: str = "MANUAL",
        actor: Optional[Dict[str, Any]] = None,
        ip_address: str = "",
    ) -> Dict[str, Any]:
        acc = query_one(
            "SELECT * FROM company_trading_accounts WHERE company_id=? AND account_id=?",
            (company_id, account_id),
        )
        if not acc:
            return {"success": False, "error": f"Company trading account {account_id} not found"}

        pool_id = MARKET_TO_POOL[acc["market_scope"]]
        started = time.time()
        run_id = f"rcn_{uuid.uuid4().hex[:14].upper()}"

        adapter = UniversalBrokerManager.get_adapter(company_id, account_id)
        bal = adapter.get_balances()
        if not bal.get("ok"):
            return {"success": False, "error": bal.get("error", "Broker balance unavailable for reconciliation")}

        broker_open_orders = adapter.get_open_orders()
        broker_positions = adapter.get_positions()
        broker_trades = adapter.get_trades()

        raw_snapshot = {
            "balances": bal,
            "open_orders": broker_open_orders,
            "positions": broker_positions,
            "trades_count": len(broker_trades),
        }

        discrepancies: List[Dict[str, Any]] = []
        pool = query_one("SELECT * FROM company_capital_pools WHERE company_id=? AND pool_id=?", (company_id, pool_id))

        # 1. Compare broker balance vs stored last synced equity if already synced previously
        broker_eq = int(bal.get("equity_paise", 0))
        local_eq = int(pool.get("broker_confirmed_equity_paise") or 0)
        if pool.get("last_broker_sync_at") and abs(broker_eq - local_eq) > 50000:
            discrepancies.append({
                "diff_type": "BALANCE_MISMATCH",
                "entity_ref": pool_id,
                "local": {"broker_confirmed_equity_paise": local_eq},
                "broker": {"equity_paise": broker_eq},
                "raw": bal,
            })

        # 2. Compare open live orders (provider_order_id check)
        local_open_orders = query(
            "SELECT * FROM broker_orders WHERE company_id=? AND account_id=? AND execution_mode='LIVE' "
            "AND status IN ('SUBMITTED','ACKNOWLEDGED','OPEN','PARTIALLY_FILLED','UNKNOWN','RECONCILIATION_REQUIRED')",
            (company_id, account_id),
        )
        broker_oid_set = {str(o.get("order_id") or o.get("id") or "") for o in broker_open_orders}
        local_oid_set = {str(o.get("provider_order_id") or "") for o in local_open_orders if o.get("provider_order_id")}

        for lo in local_open_orders:
            pid = str(lo.get("provider_order_id") or "")
            if lo["status"] in ("UNKNOWN", "RECONCILIATION_REQUIRED"):
                discrepancies.append({
                    "diff_type": "AMBIGUOUS_ORDER_STATUS",
                    "entity_ref": lo["order_id"],
                    "local": {"status": lo["status"], "symbol": lo["symbol"]},
                    "broker": {"in_open_orders": pid in broker_oid_set},
                    "raw": {"local_order": lo},
                })

        for pid in broker_oid_set:
            if pid and pid not in local_oid_set:
                discrepancies.append({
                    "diff_type": "UNTRACKED_BROKER_ORDER",
                    "entity_ref": pid,
                    "local": {"present": False},
                    "broker": {"order_id": pid},
                    "raw": next((o for o in broker_open_orders if str(o.get("order_id") or o.get("id")) == pid), {}),
                })

        # 3. Compare live positions symbol-by-symbol (only check unexpected broker positions or mismatched qty)
        local_positions = query(
            "SELECT * FROM company_positions WHERE company_id=? AND account_id=? AND execution_mode='LIVE' AND status='OPEN'",
            (company_id, account_id),
        )
        local_pos_qty: Dict[str, Decimal] = {}
        for lp in local_positions:
            sym = str(lp["symbol"]).upper()
            local_pos_qty[sym] = local_pos_qty.get(sym, Decimal("0")) + Decimal(str(lp["quantity_str"]))

        broker_pos_qty: Dict[str, Decimal] = {}
        for bp in broker_positions:
            sym = str(bp.get("tradingsymbol") or bp.get("symbol") or "").upper()
            qty_raw = bp.get("quantity") if bp.get("quantity") is not None else bp.get("net_quantity", 0)
            q_dec = Decimal(str(qty_raw or "0"))
            if sym and q_dec != 0:
                broker_pos_qty[sym] = broker_pos_qty.get(sym, Decimal("0")) + q_dec

        all_syms = set(local_pos_qty.keys()) | set(broker_pos_qty.keys())
        for sym in sorted(all_syms):
            lq = local_pos_qty.get(sym, Decimal("0"))
            bq = broker_pos_qty.get(sym, Decimal("0"))
            if lq != bq:
                discrepancies.append({
                    "diff_type": "POSITION_QUANTITY_MISMATCH" if (lq > 0 and bq > 0) else ("UNEXPECTED_BROKER_POSITION" if bq > 0 else "MISSING_BROKER_POSITION"),
                    "entity_ref": sym,
                    "local": {"quantity": str(lq)},
                    "broker": {"quantity": str(bq)},
                    "raw": [bp for bp in broker_positions if str(bp.get("tradingsymbol") or bp.get("symbol") or "").upper() == sym],
                })

        now = time.time()
        status = "MISMATCH_DETECTED" if discrepancies else "MATCHED"
        pool_recon_status = "MISMATCH_HALTED" if discrepancies else "MATCHED"

        write(
            "INSERT INTO reconciliation_runs("
            "run_id, company_id, pool_id, account_id, trigger_source, status, discrepancies_count, "
            "raw_broker_snapshot_json, summary_json, started_at, completed_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                company_id,
                pool_id,
                account_id,
                trigger_source.upper(),
                status,
                len(discrepancies),
                json.dumps(raw_snapshot, default=str),
                json.dumps({"matched": len(discrepancies) == 0, "discrepancies_count": len(discrepancies)}),
                started,
                now,
            ),
        )

        for d in discrepancies:
            diff_id = f"dif_{uuid.uuid4().hex[:14].upper()}"
            write(
                "INSERT INTO reconciliation_differences("
                "diff_id, run_id, company_id, pool_id, account_id, diff_type, entity_ref, "
                "local_value_json, broker_value_json, raw_broker_json, status, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,'OPEN',?)",
                (
                    diff_id,
                    run_id,
                    company_id,
                    pool_id,
                    account_id,
                    d["diff_type"],
                    d["entity_ref"],
                    json.dumps(d["local"], default=str),
                    json.dumps(d["broker"], default=str),
                    json.dumps(d["raw"], default=str),
                    now,
                ),
            )

        # Do NOT overwrite mismatches; halt pool entries if any discrepancy occurred
        if discrepancies:
            write(
                "UPDATE company_capital_pools SET reconciliation_status='MISMATCH_HALTED', updated_at=? "
                "WHERE company_id=? AND pool_id=?",
                (now, company_id, pool_id),
            )
        else:
            write(
                "UPDATE company_capital_pools SET reconciliation_status='MATCHED', "
                "broker_confirmed_equity_paise=?, free_funds_paise=?, locked_funds_paise=?, "
                "last_broker_sync_at=?, updated_at=? WHERE company_id=? AND pool_id=?",
                (broker_eq, int(bal.get("free_paise", 0)), int(bal.get("locked_paise", 0)), now, now, company_id, pool_id),
            )

        log_company_audit(
            company_id=company_id,
            action="RECONCILIATION_RUN",
            actor=actor,
            resource_type="RECONCILIATION_RUN",
            resource_id=run_id,
            after={"pool_id": pool_id, "status": status, "discrepancies": len(discrepancies)},
            ip_address=ip_address,
        )

        return {
            "success": True,
            "run_id": run_id,
            "pool_id": pool_id,
            "status": status,
            "pool_reconciliation_status": pool_recon_status,
            "discrepancies_count": len(discrepancies),
            "differences": query("SELECT * FROM reconciliation_differences WHERE run_id=?", (run_id,)),
        }

    @staticmethod
    def resolve_difference(
        company_id: int,
        diff_id: str,
        resolution_note: str,
        actor: Dict[str, Any],
        ip_address: str = "",
    ) -> Dict[str, Any]:
        diff = query_one(
            "SELECT * FROM reconciliation_differences WHERE company_id=? AND diff_id=?",
            (company_id, diff_id),
        )
        if not diff:
            return {"success": False, "error": "Reconciliation difference not found"}
        if diff["status"] != "OPEN":
            return {"success": False, "error": f"Difference already {diff['status']}"}
        if not (resolution_note or "").strip():
            return {"success": False, "error": "Explicit resolution_note is required"}

        now = time.time()
        write(
            "UPDATE reconciliation_differences SET status='RESOLVED', resolution_note=?, resolved_by=?, resolved_at=? "
            "WHERE diff_id=?",
            (resolution_note.strip(), actor["id"], now, diff_id),
        )
        remaining = query_one(
            "SELECT COUNT(*) as c FROM reconciliation_differences WHERE company_id=? AND pool_id=? AND status='OPEN'",
            (company_id, diff["pool_id"]),
        )["c"]
        if remaining == 0:
            write(
                "UPDATE company_capital_pools SET reconciliation_status='MATCHED', updated_at=? WHERE company_id=? AND pool_id=?",
                (now, company_id, diff["pool_id"]),
            )
        log_company_audit(
            company_id=company_id,
            action="RECONCILIATION_DIFF_RESOLVED",
            actor=actor,
            resource_type="RECONCILIATION_DIFFERENCE",
            resource_id=diff_id,
            after={"resolution_note": resolution_note.strip(), "remaining_open": remaining},
            ip_address=ip_address,
        )
        return {"success": True, "diff_id": diff_id, "remaining_open": remaining}

    @staticmethod
    def list_runs(company_id: int, limit: int = 30) -> Dict[str, Any]:
        runs = query(
            "SELECT * FROM reconciliation_runs WHERE company_id=? ORDER BY completed_at DESC LIMIT ?",
            (company_id, int(limit)),
        )
        diffs = query(
            "SELECT * FROM reconciliation_differences WHERE company_id=? ORDER BY created_at DESC LIMIT 100",
            (company_id,),
        )
        return {"runs": runs, "differences": diffs}


class CompanyComplianceService:
    """Tracks corporate, Zerodha/SEBI, CoinDCX/FIU-IND, and security readiness evidence."""

    @staticmethod
    def list_records(company_id: int) -> List[Dict[str, Any]]:
        return query("SELECT * FROM compliance_records WHERE company_id=? ORDER BY category ASC, record_id ASC", (company_id,))

    @staticmethod
    def update_record(
        company_id: int,
        record_id: str,
        status: str,
        evidence_ref: str,
        notes: str,
        actor: Dict[str, Any],
        ip_address: str = "",
    ) -> Dict[str, Any]:
        clean_st = (status or "").strip().upper()
        if clean_st not in ("REQUIRES_REVIEW", "IN_PROGRESS", "EVIDENCE_UPLOADED", "VERIFIED_BY_COUNSEL"):
            return {"success": False, "error": "Invalid compliance status"}
        row = query_one("SELECT * FROM compliance_records WHERE company_id=? AND record_id=?", (company_id, record_id))
        if not row:
            return {"success": False, "error": "Compliance record not found"}
        write(
            "UPDATE compliance_records SET status=?, evidence_ref=?, notes=?, updated_by=?, updated_at=? WHERE record_id=?",
            (clean_st, evidence_ref.strip(), notes.strip(), actor["id"], time.time(), record_id),
        )
        log_company_audit(
            company_id=company_id,
            action="COMPLIANCE_RECORD_UPDATED",
            actor=actor,
            resource_type="COMPLIANCE_RECORD",
            resource_id=record_id,
            before=row,
            after={"status": clean_st, "evidence_ref": evidence_ref.strip()},
            ip_address=ip_address,
        )
        return {"success": True, "record": query_one("SELECT * FROM compliance_records WHERE record_id=?", (record_id,))}
