"""
ARAA Company Trading Platform — Company Capital Pools & Trading Account Isolation.

Core guarantees:
- Precision decimal / integer paise arithmetic (never binary float for INR or quantities).
- Two strictly isolated capital pools:
    1. POOL_INDIA_INR (Zerodha / India securities / INR)
    2. POOL_CRYPTO_SPOT (CoinDCX / Crypto spot pairs / INR reporting)
- Zero cross-pool transfers or shared risk budgets.
- Clear distinction between broker-confirmed balances and accounting capital entries.
- Company-owned broker accounts with encrypted secrets at rest (`broker_account_secrets`).
"""

import csv
import hashlib
import io
import json
import os
import time
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

try:
    from company_auth import log_company_audit
    from database import (
        decrypt_secret,
        encrypt_secret,
        is_secrets_encryption_enabled,
        query,
        query_one,
        write,
        writes,
    )
except ImportError:
    from backend.company_auth import log_company_audit
    from backend.database import (
        decrypt_secret,
        encrypt_secret,
        is_secrets_encryption_enabled,
        query,
        query_one,
        write,
        writes,
    )


POOL_INDIA_INR = "POOL_INDIA_INR"
POOL_CRYPTO_SPOT = "POOL_CRYPTO_SPOT"
POOL_CRYPTO_FUTURES = "POOL_CRYPTO_FUTURES"

MARKET_TO_POOL = {
    "INDIA": POOL_INDIA_INR,
    "CRYPTO": POOL_CRYPTO_SPOT,
    "CRYPTO_FUTURES": POOL_CRYPTO_FUTURES,
}

POOL_EXPECTED_PROVIDER = {
    POOL_INDIA_INR: ("INDIA", "ZERODHA"),
    POOL_CRYPTO_SPOT: ("CRYPTO", "COINDCX"),
    POOL_CRYPTO_FUTURES: ("CRYPTO", "COINDCX_FUTURES"),
}


# ---------------------------------------------------------------------------
# Exact Precision Financial Arithmetic Helpers
# ---------------------------------------------------------------------------
def to_paise(amount_inr: Any) -> int:
    """Converts INR decimal/string/int cleanly into integer paise without binary float drift."""
    if isinstance(amount_inr, bool):
        raise ValueError("Invalid boolean monetary amount")
    try:
        dec = Decimal(str(amount_inr).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid INR amount: {amount_inr}") from exc
    if not dec.is_finite():
        raise ValueError("Non-finite INR amount rejected")
    return int((dec * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def paise_to_inr_str(paise: int) -> str:
    """Formats integer paise cleanly as an exact 2-decimal INR string."""
    p = int(paise or 0)
    sign = "-" if p < 0 else ""
    abs_p = abs(p)
    rupees, rem = divmod(abs_p, 100)
    return f"{sign}{rupees}.{rem:02d}"


def quantize_decimal_str(value: Any, precision: int = 8) -> str:
    """Normalizes crypto quantities/prices using exact Decimal precision."""
    try:
        dec = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value}") from exc
    if not dec.is_finite():
        raise ValueError("Non-finite decimal rejected")
    fmt = "1" if precision <= 0 else "0." + ("0" * (precision - 1)) + "1"
    return str(dec.quantize(Decimal(fmt), rounding=ROUND_HALF_UP))


def _format_pool(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for k in (
        "allocated_capital_paise",
        "broker_confirmed_equity_paise",
        "free_funds_paise",
        "locked_funds_paise",
        "open_exposure_paise",
        "realized_pnl_paise",
        "unrealized_pnl_paise",
        "fees_paise",
        "taxes_expenses_paise",
        "daily_loss_paise",
        "available_risk_budget_paise",
    ):
        base_name = k.replace("_paise", "_inr")
        out[base_name] = paise_to_inr_str(out.get(k, 0))
    return out


# ---------------------------------------------------------------------------
# Independent Company Capital Pool Manager
# ---------------------------------------------------------------------------
class CompanyCapitalManager:
    """Enforces strict capital isolation between India (Zerodha) and Crypto (CoinDCX)."""

    @staticmethod
    def assert_pool_isolation(pool_id: str, market_scope: Optional[str] = None, provider: Optional[str] = None) -> None:
        if pool_id not in POOL_EXPECTED_PROVIDER:
            raise ValueError(f"Unknown capital pool: {pool_id}")
        exp_market, exp_provider = POOL_EXPECTED_PROVIDER[pool_id]
        if market_scope and market_scope.strip().upper() != exp_market:
            raise PermissionError(
                f"POOL_ISOLATION_VIOLATION: {market_scope} market cannot access {pool_id} ({exp_market} only)"
            )
        if provider and provider.strip().upper() != exp_provider:
            raise PermissionError(
                f"POOL_ISOLATION_VIOLATION: {provider} broker cannot use {pool_id} ({exp_provider} only)"
            )

    @staticmethod
    def get_pool_for_market(company_id: int, market_scope: str) -> Dict[str, Any]:
        scope = (market_scope or "").strip().upper()
        if scope not in MARKET_TO_POOL:
            raise ValueError(f"Unsupported market_scope: {market_scope}")
        pool_id = MARKET_TO_POOL[scope]
        row = query_one("SELECT * FROM company_capital_pools WHERE company_id=? AND pool_id=?", (company_id, pool_id))
        if not row:
            raise RuntimeError(f"Capital pool {pool_id} missing for company {company_id}")
        return _format_pool(row)

    @staticmethod
    def list_pools(company_id: int) -> List[Dict[str, Any]]:
        rows = query("SELECT * FROM company_capital_pools WHERE company_id=? ORDER BY pool_id ASC", (company_id,))
        formatted = []
        for r in rows:
            p = _format_pool(r)
            allocs = query(
                "SELECT allocation_id, strategy_code, allocated_paise, used_paise, status "
                "FROM capital_allocations WHERE company_id=? AND pool_id=? ORDER BY strategy_code ASC",
                (company_id, r["pool_id"]),
            )
            p["strategy_allocations"] = [
                {
                    **a,
                    "allocated_inr": paise_to_inr_str(a["allocated_paise"]),
                    "used_inr": paise_to_inr_str(a["used_paise"]),
                }
                for a in allocs
            ]
            formatted.append(p)
        return formatted

    @staticmethod
    def get_combined_portfolio(company_id: int) -> Dict[str, Any]:
        """Reporting-only valuation across both pools. Risk & order sizing always use individual pools."""
        pools = CompanyCapitalManager.list_pools(company_id)
        total_alloc = sum(int(p["allocated_capital_paise"]) for p in pools)
        total_broker_eq = sum(int(p["broker_confirmed_equity_paise"]) for p in pools)
        total_free = sum(int(p["free_funds_paise"]) for p in pools)
        total_locked = sum(int(p["locked_funds_paise"]) for p in pools)
        total_realized = sum(int(p["realized_pnl_paise"]) for p in pools)
        total_unrealized = sum(int(p["unrealized_pnl_paise"]) for p in pools)
        total_fees = sum(int(p["fees_paise"]) for p in pools)
        total_taxes = sum(int(p["taxes_expenses_paise"]) for p in pools)

        return {
            "company_id": company_id,
            "reporting_only": True,
            "cross_pool_transfers_allowed": False,
            "base_currency": "INR",
            "total_allocated_capital_paise": total_alloc,
            "total_allocated_capital_inr": paise_to_inr_str(total_alloc),
            "total_broker_confirmed_equity_paise": total_broker_eq,
            "total_broker_confirmed_equity_inr": paise_to_inr_str(total_broker_eq),
            "total_free_funds_paise": total_free,
            "total_free_funds_inr": paise_to_inr_str(total_free),
            "total_locked_funds_paise": total_locked,
            "total_locked_funds_inr": paise_to_inr_str(total_locked),
            "total_realized_pnl_paise": total_realized,
            "total_realized_pnl_inr": paise_to_inr_str(total_realized),
            "total_unrealized_pnl_paise": total_unrealized,
            "total_unrealized_pnl_inr": paise_to_inr_str(total_unrealized),
            "total_fees_paise": total_fees,
            "total_fees_inr": paise_to_inr_str(total_fees),
            "total_taxes_expenses_paise": total_taxes,
            "total_taxes_expenses_inr": paise_to_inr_str(total_taxes),
            "pools": {p["pool_id"]: p for p in pools},
        }

    @staticmethod
    def record_capital_movement(
        company_id: int,
        pool_id: str,
        movement_type: str,
        amount_inr: Any,
        actor: Optional[Dict[str, Any]] = None,
        reference_no: str = "",
        note: str = "",
        approval_id: str = "",
        target_pool_id: Optional[str] = None,
        ip_address: str = "",
    ) -> Dict[str, Any]:
        """Records an authorized accounting capital movement for ONE isolated pool (never cross-pool)."""
        if target_pool_id and target_pool_id != pool_id:
            return {
                "success": False,
                "error": "CROSS_POOL_TRANSFER_FORBIDDEN: Automatic or direct capital transfers between India and Crypto pools are disabled.",
            }
        mtype = (movement_type or "").strip().upper()
        if mtype in ("TRANSFER", "CROSS_POOL_TRANSFER"):
            return {
                "success": False,
                "error": "CROSS_POOL_TRANSFER_FORBIDDEN: Funds cannot transfer between India and Crypto capital pools.",
            }
        if mtype not in ("CAPITAL_ADDITION", "CAPITAL_WITHDRAWAL", "FEE_EXPENSE", "TAX_EXPENSE"):
            return {"success": False, "error": f"Invalid movement_type: {movement_type}"}

        if pool_id not in POOL_EXPECTED_PROVIDER:
            return {"success": False, "error": f"Unknown pool_id: {pool_id}"}

        amount_paise = to_paise(amount_inr)
        if amount_paise <= 0:
            return {"success": False, "error": "Amount must be greater than zero"}

        pool = query_one("SELECT * FROM company_capital_pools WHERE company_id=? AND pool_id=?", (company_id, pool_id))
        if not pool:
            return {"success": False, "error": "Pool not found"}

        cur_alloc = int(pool["allocated_capital_paise"])
        cur_budget = int(pool["available_risk_budget_paise"])
        cur_fees = int(pool["fees_paise"])
        cur_taxes = int(pool["taxes_expenses_paise"])

        new_alloc = cur_alloc
        new_budget = cur_budget
        new_fees = cur_fees
        new_taxes = cur_taxes

        if mtype == "CAPITAL_ADDITION":
            new_alloc += amount_paise
            new_budget += amount_paise
        elif mtype == "CAPITAL_WITHDRAWAL":
            if amount_paise > cur_alloc:
                return {
                    "success": False,
                    "error": f"Insufficient allocated capital in {pool_id} ({paise_to_inr_str(cur_alloc)} INR available)",
                }
            new_alloc -= amount_paise
            new_budget = max(0, new_budget - amount_paise)
        elif mtype == "FEE_EXPENSE":
            new_fees += amount_paise
            new_alloc = max(0, new_alloc - amount_paise)
            new_budget = max(0, new_budget - amount_paise)
        elif mtype == "TAX_EXPENSE":
            new_taxes += amount_paise
            new_alloc = max(0, new_alloc - amount_paise)
            new_budget = max(0, new_budget - amount_paise)

        mv_id = f"mv_{uuid.uuid4().hex[:14].upper()}"
        now = time.time()
        actor_id = actor["id"] if actor else None

        writes([
            (
                "INSERT INTO company_capital_movements("
                "movement_id, company_id, pool_id, movement_type, amount_paise, source_classification, "
                "reference_no, note, approval_id, created_by, created_at"
                ") VALUES(?,?,?,?,?,'ACCOUNTING_RECORD',?,?,?,?,?)",
                (mv_id, company_id, pool_id, mtype, amount_paise, reference_no, note, approval_id, actor_id, now),
            ),
            (
                "UPDATE company_capital_pools SET allocated_capital_paise=?, available_risk_budget_paise=?, "
                "fees_paise=?, taxes_expenses_paise=?, updated_at=? WHERE company_id=? AND pool_id=?",
                (new_alloc, new_budget, new_fees, new_taxes, now, company_id, pool_id),
            ),
        ])

        updated_pool = _format_pool(
            query_one("SELECT * FROM company_capital_pools WHERE company_id=? AND pool_id=?", (company_id, pool_id))
        )
        log_company_audit(
            company_id=company_id,
            action=f"CAPITAL_{mtype}",
            actor=actor,
            resource_type="CAPITAL_POOL",
            resource_id=pool_id,
            before={"allocated_capital_paise": cur_alloc},
            after={"allocated_capital_paise": new_alloc, "amount_paise": amount_paise, "movement_id": mv_id},
            ip_address=ip_address,
        )
        return {
            "success": True,
            "movement_id": mv_id,
            "source_classification": "ACCOUNTING_RECORD",
            "pool": updated_pool,
        }

    @staticmethod
    def allocate_to_strategy(
        company_id: int,
        pool_id: str,
        strategy_code: str,
        amount_inr: Any,
        actor: Optional[Dict[str, Any]] = None,
        ip_address: str = "",
    ) -> Dict[str, Any]:
        """Allocates capital within ONE pool to a specific strategy, ensuring total <= pool capital."""
        if pool_id not in POOL_EXPECTED_PROVIDER:
            return {"success": False, "error": f"Unknown pool_id: {pool_id}"}
        clean_strat = (strategy_code or "").strip().upper()
        if not clean_strat:
            return {"success": False, "error": "strategy_code required"}

        amt_paise = to_paise(amount_inr)
        if amt_paise < 0:
            return {"success": False, "error": "Allocated capital cannot be negative"}

        pool = query_one("SELECT * FROM company_capital_pools WHERE company_id=? AND pool_id=?", (company_id, pool_id))
        if not pool:
            return {"success": False, "error": "Pool not found"}

        other_sum_row = query_one(
            "SELECT COALESCE(SUM(allocated_paise), 0) as s FROM capital_allocations "
            "WHERE company_id=? AND pool_id=? AND strategy_code!=? AND status='ACTIVE'",
            (company_id, pool_id, clean_strat),
        )
        other_sum = int(other_sum_row["s"] or 0)
        pool_total = int(pool["allocated_capital_paise"] or 0)
        if other_sum + amt_paise > pool_total:
            return {
                "success": False,
                "error": (
                    f"Allocation exceeds {pool_id} available pool capital: "
                    f"requested={paise_to_inr_str(amt_paise)}, "
                    f"other_allocations={paise_to_inr_str(other_sum)}, "
                    f"pool_capital={paise_to_inr_str(pool_total)}"
                ),
            }

        now = time.time()
        alloc_id = f"alc_{uuid.uuid4().hex[:12].upper()}"
        actor_id = actor["id"] if actor else None
        write(
            "INSERT INTO capital_allocations(allocation_id, company_id, pool_id, strategy_code, allocated_paise, "
            "status, created_by, created_at, updated_at) VALUES(?,?,?,?,?,'ACTIVE',?,?,?) "
            "ON CONFLICT(pool_id, strategy_code) DO UPDATE SET allocated_paise=excluded.allocated_paise, "
            "status='ACTIVE', updated_at=excluded.updated_at",
            (alloc_id, company_id, pool_id, clean_strat, amt_paise, actor_id, now, now),
        )
        row = query_one("SELECT * FROM capital_allocations WHERE pool_id=? AND strategy_code=?", (pool_id, clean_strat))
        log_company_audit(
            company_id=company_id,
            action="STRATEGY_CAPITAL_ALLOCATED",
            actor=actor,
            resource_type="CAPITAL_ALLOCATION",
            resource_id=f"{pool_id}:{clean_strat}",
            after={"allocated_paise": amt_paise},
            ip_address=ip_address,
        )
        return {"success": True, "allocation": {**row, "allocated_inr": paise_to_inr_str(row["allocated_paise"])}}

    @staticmethod
    def get_financial_report(company_id: int, pool_id: Optional[str] = None, period: str = "ALL") -> Dict[str, Any]:
        window_map = {
            "DAILY": 86400,
            "WEEKLY": 7 * 86400,
            "MONTHLY": 30 * 86400,
            "YEARLY": 365 * 86400,
        }
        since = time.time() - window_map.get((period or "").upper(), 10 * 365 * 86400)
        if pool_id:
            movements = query(
                "SELECT * FROM company_capital_movements WHERE company_id=? AND pool_id=? AND created_at>=? "
                "ORDER BY created_at DESC LIMIT 200",
                (company_id, pool_id, since),
            )
        else:
            movements = query(
                "SELECT * FROM company_capital_movements WHERE company_id=? AND created_at>=? "
                "ORDER BY created_at DESC LIMIT 200",
                (company_id, since),
            )
        formatted_mv = [{**m, "amount_inr": paise_to_inr_str(m["amount_paise"])} for m in movements]
        return {
            "period": (period or "ALL").upper(),
            "portfolio": CompanyCapitalManager.get_combined_portfolio(company_id),
            "movements": formatted_mv,
        }

    @staticmethod
    def export_movements_csv(company_id: int) -> str:
        rows = query(
            "SELECT movement_id, pool_id, movement_type, amount_paise, source_classification, "
            "reference_no, note, created_at FROM company_capital_movements WHERE company_id=? ORDER BY created_at DESC",
            (company_id,),
        )
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["movement_id", "pool_id", "movement_type", "amount_inr", "amount_paise", "source_classification", "reference_no", "note", "created_at"])
        for r in rows:
            writer.writerow([
                r["movement_id"],
                r["pool_id"],
                r["movement_type"],
                paise_to_inr_str(r["amount_paise"]),
                r["amount_paise"],
                r["source_classification"],
                r["reference_no"],
                r["note"],
                r["created_at"],
            ])
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Company-Owned Broker Accounts & Isolated Secret Vault
# ---------------------------------------------------------------------------
class CompanyAccountManager:
    """Manages company-owned broker accounts with per-account encrypted credentials."""

    @staticmethod
    def register_account(
        company_id: int,
        provider: str,
        account_name: str,
        api_key: str,
        api_secret: str,
        actor: Optional[Dict[str, Any]] = None,
        static_egress_ip: str = "",
        withdrawal_disabled: bool = True,
        ip_address: str = "",
    ) -> Dict[str, Any]:
        clean_prov = (provider or "").strip().upper()
        if clean_prov not in ("ZERODHA", "COINDCX"):
            return {"success": False, "error": f"Unsupported provider: {provider}"}
        if not (api_key or "").strip() or not (api_secret or "").strip():
            return {"success": False, "error": "api_key and api_secret are required"}

        require_enc = (
            os.environ.get("REQUIRE_ENCRYPTION", "0") == "1"
            or os.environ.get("TRADING_MODE", "PAPER").strip().upper() == "LIVE"
        )
        if require_enc and not is_secrets_encryption_enabled():
            return {
                "success": False,
                "error": "SECRETS_KEY must be configured before storing company broker credentials in strict/live mode",
            }

        company = query_one("SELECT * FROM companies WHERE id=?", (company_id,))
        legal_holder = company["legal_name"] if company else "ARAA Proprietary Trading Pvt. Ltd."
        market_scope = "INDIA" if clean_prov == "ZERODHA" else "CRYPTO"
        pool_id = MARKET_TO_POOL[market_scope]

        # Enforce initial CoinDCX Spot-only & Zero Leverage policy
        supports_spot = 1
        supports_equity = 1 if clean_prov == "ZERODHA" else 0
        supports_futures = 0
        supports_options = 0
        leverage_allowed = 0

        account_id = f"ACC-{clean_prov}-{uuid.uuid4().hex[:8].upper()}"
        now = time.time()
        fingerprint = hashlib.sha256(api_key.strip().encode("utf-8")).hexdigest()[:12]

        writes([
            (
                "INSERT INTO company_trading_accounts("
                "account_id, company_id, provider, market_scope, account_name, legal_holder, "
                "ownership_verified, trading_approved, connection_status, execution_mode, "
                "api_permission_status, created_at, updated_at"
                ") VALUES(?,?,?,?,?,?,1,0,'CONFIGURED','PAPER','PENDING_VERIFICATION',?,?)",
                (account_id, company_id, clean_prov, market_scope, account_name.strip(), legal_holder, now, now),
            ),
            (
                "INSERT INTO broker_account_secrets("
                "account_id, api_key_enc, api_secret_enc, access_token_enc, key_fingerprint, "
                "static_egress_ip, withdrawal_disabled, updated_at"
                ") VALUES(?,?,?,'',?,?,?,?)",
                (
                    account_id,
                    encrypt_secret(api_key.strip()),
                    encrypt_secret(api_secret.strip()),
                    fingerprint,
                    static_egress_ip.strip(),
                    1 if withdrawal_disabled else 0,
                    now,
                ),
            ),
            (
                "INSERT INTO broker_capabilities("
                "account_id, supports_spot, supports_equity, supports_futures, supports_options, "
                "leverage_allowed, max_leverage, allowed_segments_json, updated_at"
                ") VALUES(?,?,?,?,?,?,'1',?,?)",
                (
                    account_id,
                    supports_spot,
                    supports_equity,
                    supports_futures,
                    supports_options,
                    leverage_allowed,
                    json.dumps(["NSE", "BSE"] if clean_prov == "ZERODHA" else ["COINDCX_SPOT"]),
                    now,
                ),
            ),
            (
                "UPDATE company_capital_pools SET account_id=?, updated_at=? WHERE company_id=? AND pool_id=?",
                (account_id, now, company_id, pool_id),
            ),
        ])

        log_company_audit(
            company_id=company_id,
            action="BROKER_ACCOUNT_REGISTERED",
            actor=actor,
            resource_type="COMPANY_TRADING_ACCOUNT",
            resource_id=account_id,
            after={"provider": clean_prov, "market_scope": market_scope, "pool_id": pool_id, "key_fingerprint": fingerprint},
            ip_address=ip_address,
        )
        return {"success": True, "account": CompanyAccountManager.get_account_safe(company_id, account_id)}

    @staticmethod
    def get_account_safe(company_id: int, account_id: str) -> Optional[Dict[str, Any]]:
        """Returns account & capabilities WITHOUT ever returning encrypted or plaintext secrets."""
        acc = query_one(
            "SELECT * FROM company_trading_accounts WHERE company_id=? AND account_id=?",
            (company_id, account_id),
        )
        if not acc:
            return None
        sec = query_one(
            "SELECT key_fingerprint, static_egress_ip, withdrawal_disabled, updated_at "
            "FROM broker_account_secrets WHERE account_id=?",
            (account_id,),
        ) or {}
        cap = query_one("SELECT * FROM broker_capabilities WHERE account_id=?", (account_id,)) or {}
        res = dict(acc)
        res["secret_meta"] = dict(sec)
        res["capabilities"] = dict(cap)
        return res

    @staticmethod
    def list_accounts(company_id: int) -> List[Dict[str, Any]]:
        rows = query(
            "SELECT account_id FROM company_trading_accounts WHERE company_id=? ORDER BY created_at DESC",
            (company_id,),
        )
        return [CompanyAccountManager.get_account_safe(company_id, r["account_id"]) for r in rows]

    @staticmethod
    def resolve_decrypted_credentials(company_id: int, account_id: str) -> Optional[Dict[str, Any]]:
        """Internal backend-only resolver for broker adapters. Never expose over HTTP."""
        acc = query_one(
            "SELECT * FROM company_trading_accounts WHERE company_id=? AND account_id=?",
            (company_id, account_id),
        )
        sec = query_one("SELECT * FROM broker_account_secrets WHERE account_id=?", (account_id,))
        if not acc or not sec:
            return None
        return {
            "account_id": account_id,
            "company_id": company_id,
            "provider": acc["provider"],
            "market_scope": acc["market_scope"],
            "api_key": decrypt_secret(sec["api_key_enc"]),
            "api_secret": decrypt_secret(sec["api_secret_enc"]),
            "access_token": decrypt_secret(sec.get("access_token_enc") or ""),
            "static_egress_ip": sec.get("static_egress_ip") or "",
            "withdrawal_disabled": bool(sec.get("withdrawal_disabled")),
        }
