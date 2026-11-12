"""
ARAA BOT V3 — ENTERPRISE DOUBLE-ENTRY FINANCIAL LEDGER & REVENUE SYSTEM
Immutable double-entry bookkeeping, multi-currency accounting, SaaS billing,
brokerage commission allocation, and withdrawal maker-checker workflow.
"""

import time
import uuid
import logging
from typing import Dict, Any, List, Optional, Tuple

from database import query, query_one, write, writes
from event_bus import get_event_bus, Events

logger = logging.getLogger("FINANCIAL_LEDGER")

# Standard Institutional Chart of Accounts
DEFAULT_ACCOUNTS = [
    ("1001", "CASH_RESERVE_WALLET", "ASSET", "USD"),
    ("1002", "PAYMENT_GATEWAY_RECEIVABLE", "ASSET", "USD"),
    ("2001", "USER_DEPOSIT_LIABILITY", "LIABILITY", "USD"),
    ("2002", "USER_PROFIT_LIABILITY", "LIABILITY", "USD"),
    ("3001", "INSTITUTIONAL_TRADING_CAPITAL", "EQUITY", "USD"),
    ("4001", "SAAS_SUBSCRIPTION_REVENUE", "REVENUE", "USD"),
    ("4002", "BROKERAGE_COMMISSION_REVENUE", "REVENUE", "USD"),
    ("5001", "GATEWAY_PROCESSING_FEES", "EXPENSE", "USD"),
]


class DoubleEntryLedger:
    """Manages balanced immutable double-entry records and financial integrity."""

    @classmethod
    def init_ledger_accounts(cls):
        """Ensures standard institutional accounts exist in ledger_accounts."""
        now = time.time()
        for code, name, acct_type, curr in DEFAULT_ACCOUNTS:
            row = query_one("SELECT account_code FROM ledger_accounts WHERE account_code=?", (code,))
            if not row:
                write(
                    "INSERT INTO ledger_accounts(account_code, account_name, account_type, currency, "
                    "balance, description, created_at) VALUES(?, ?, ?, ?, 0.0, ?, ?)",
                    (code, name, acct_type, curr, f"Institutional {name}", now)
                )

    @classmethod
    def record_entry(cls, debit_code: str, credit_code: str, amount: float,
                     currency: str = "USD", description: str = "", user_id: Optional[int] = None,
                     transaction_ref: Optional[str] = None) -> Dict[str, Any]:
        """
        Records a strict double-entry transaction:
        Debit account balance increases (for Assets/Expenses) or decreases (for Liabilities/Revenue/Equity).
        Credit account balance decreases (for Assets/Expenses) or increases (for Liabilities/Revenue/Equity).
        """
        cls.init_ledger_accounts()
        amt = round(float(amount or 0.0), 4)
        if amt <= 0:
            return {"success": False, "error": "Amount must be strictly positive"}

        deb_acct = query_one("SELECT * FROM ledger_accounts WHERE account_code=?", (debit_code,))
        cred_acct = query_one("SELECT * FROM ledger_accounts WHERE account_code=?", (credit_code,))

        if not deb_acct or not cred_acct:
            return {"success": False, "error": f"Invalid accounts: {debit_code} or {credit_code}"}

        entry_uuid = str(uuid.uuid4())
        tx_ref = transaction_ref or f"TX-{int(time.time()*1000)}-{entry_uuid[:8]}"
        now = time.time()

        # Update debit account: Assets and Expenses increase with Debit (+); Liabilities, Equity, Revenue decrease with Debit (-)
        deb_type = deb_acct["account_type"]
        deb_delta = amt if deb_type in ("ASSET", "EXPENSE") else -amt

        # Update credit account: Liabilities, Equity, Revenue increase with Credit (+); Assets and Expenses decrease with Credit (-)
        cred_type = cred_acct["account_type"]
        cred_delta = -amt if cred_type in ("ASSET", "EXPENSE") else amt

        writes([
            ("UPDATE ledger_accounts SET balance = balance + ? WHERE account_code=?", (deb_delta, debit_code)),
            ("UPDATE ledger_accounts SET balance = balance + ? WHERE account_code=?", (cred_delta, credit_code)),
            ("INSERT INTO ledger_entries(entry_uuid, transaction_ref, debit_account, credit_account, "
             "amount, currency, user_id, correlation_id, narration, status, created_at) "
             "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'POSTED', ?)",
             (entry_uuid, tx_ref, debit_code, credit_code, amt, currency, user_id, tx_ref, description, now))
        ])

        return {
            "success": True,
            "entry_uuid": entry_uuid,
            "transaction_ref": tx_ref,
            "amount": amt,
            "debit_account": debit_code,
            "credit_account": credit_code,
            "created_at": now
        }

    @classmethod
    def deposit_capital(cls, user_id: int, amount: float, currency: str = "USD",
                        gateway: str = "COINDCX", tx_hash: Optional[str] = None) -> Dict[str, Any]:
        """Processes and journals customer capital deposit."""
        now = time.time()
        amt = round(float(amount), 2)
        desc = f"Customer deposit via {gateway} ({tx_hash or 'Direct'})"

        # Double entry: Debit Cash Reserve (1001), Credit User Deposit Liability (2001)
        ledger_res = cls.record_entry(
            debit_code="1001",
            credit_code="2001",
            amount=amt,
            currency=currency,
            description=desc,
            user_id=user_id,
            transaction_ref=tx_hash
        )

        # Update user wallet
        write("UPDATE wallets SET deposit_balance = deposit_balance + ? WHERE user_id=?", (amt, user_id))
        write(
            "INSERT INTO deposits(user_id, method, asset, amount, credited, ref, status, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, 'CONFIRMED', ?)",
            (user_id, gateway, currency, amt, amt, tx_hash or ledger_res["entry_uuid"], now)
        )

        get_event_bus().publish(
            Events.PAYMENT_COMPLETED,
            user_id=user_id,
            amount=amt,
            currency=currency,
            gateway=gateway,
            tx_hash=tx_hash
        )

        return {"success": True, "amount": amt, "currency": currency, "entry": ledger_res}

    @classmethod
    def process_profit_brokerage(cls, user_id: int, realized_pnl: float,
                                 brokerage_rate: float = 0.30) -> Dict[str, Any]:
        """Calculates 30% platform brokerage and credits 70% net profit to user liability."""
        pnl = round(float(realized_pnl), 4)
        if pnl <= 0:
            return {"brokerage_usd": 0.0, "net_pnl_usd": pnl}

        brokerage = round(pnl * brokerage_rate, 4)
        net_profit = round(pnl - brokerage, 4)

        # Double entry for brokerage revenue: Debit User Profit Liability (2002) / Credit Brokerage Revenue (4002)
        cls.record_entry(
            debit_code="2002",
            credit_code="4002",
            amount=brokerage,
            currency="USD",
            description=f"30% Performance Brokerage on Trade P&L ${pnl:.2f}",
            user_id=user_id
        )

        return {
            "gross_profit_usd": pnl,
            "brokerage_usd": brokerage,
            "net_profit_usd": net_profit,
            "brokerage_rate": brokerage_rate
        }

    @classmethod
    def request_withdrawal(cls, user_id: int, amount: float, method: str = "BANK_WIRE",
                           details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Creates withdrawal request requiring maker-checker approval."""
        amt = round(float(amount), 2)
        w = query_one("SELECT deposit_balance, profit_balance FROM wallets WHERE user_id=?", (user_id,))
        if not w:
            return {"success": False, "error": "Wallet not found"}

        total_avail = float(w.get("deposit_balance") or 0.0) + float(w.get("profit_balance") or 0.0)
        if amt > total_avail:
            return {"success": False, "error": f"Insufficient funds: available ${total_avail:.2f}"}

        now = time.time()
        # Deduct from user wallet to prevent double spend while pending
        if amt <= float(w.get("profit_balance") or 0.0):
            write("UPDATE wallets SET profit_balance = profit_balance - ? WHERE user_id=?", (amt, user_id))
        else:
            write("UPDATE wallets SET deposit_balance = deposit_balance - ? WHERE user_id=?", (amt, user_id))

        wid = write(
            "INSERT INTO withdrawals(user_id, amount, brokerage, net_payable, method, status, "
            "bank_name, account_number, ifsc_code, account_holder, created_at) "
            "VALUES(?, ?, 0.0, ?, ?, 'PENDING_APPROVAL', ?, ?, ?, ?, ?)",
            (user_id, amt, amt, method,
             (details or {}).get("bank_name", "Crypto / Bank"),
             (details or {}).get("account_number", "USDT_ADDRESS"),
             (details or {}).get("ifsc_code", "N/A"),
             (details or {}).get("account_holder", "User"), now)
        )

        return {"success": True, "withdrawal_id": wid, "amount": amt, "status": "PENDING_APPROVAL"}

    @classmethod
    def approve_withdrawal(cls, withdrawal_id: int, admin_user_id: int,
                           note: str = "Approved by Finance") -> Dict[str, Any]:
        """Checker approval: releases funds and updates double-entry ledger."""
        w_req = query_one("SELECT * FROM withdrawals WHERE id=?", (withdrawal_id,))
        if not w_req or w_req["status"] != "PENDING_APPROVAL":
            return {"success": False, "error": "Withdrawal not found or already processed"}

        amt = float(w_req["amount"])
        uid = w_req["user_id"]
        now = time.time()

        # Double entry: Debit User Liability (2001) / Credit Cash Reserve Wallet (1001)
        ledger_res = cls.record_entry(
            debit_code="2001",
            credit_code="1001",
            amount=amt,
            currency="USD",
            description=f"Withdrawal WID-{withdrawal_id} payout approved by Admin-{admin_user_id}: {note}",
            user_id=uid
        )

        write("UPDATE withdrawals SET status='COMPLETED' WHERE id=?", (withdrawal_id,))
        return {"success": True, "withdrawal_id": withdrawal_id, "status": "COMPLETED", "ledger": ledger_res}

    @classmethod
    def get_trial_balance(cls) -> Dict[str, Any]:
        """Calculates Trial Balance across all ledger accounts to prove mathematical balance."""
        cls.init_ledger_accounts()
        accounts = query("SELECT * FROM ledger_accounts ORDER BY account_code ASC")
        total_assets = 0.0
        total_liabilities = 0.0
        total_equity = 0.0
        total_revenue = 0.0
        total_expenses = 0.0

        for a in accounts:
            bal = float(a["balance"])
            t = a["account_type"]
            if t == "ASSET":
                total_assets += bal
            elif t == "LIABILITY":
                total_liabilities += bal
            elif t == "EQUITY":
                total_equity += bal
            elif t == "REVENUE":
                total_revenue += bal
            elif t == "EXPENSE":
                total_expenses += bal

        # Accounting Equation: Assets + Expenses = Liabilities + Equity + Revenue
        total_debits = round(total_assets + total_expenses, 4)
        total_credits = round(total_liabilities + total_equity + total_revenue, 4)
        is_balanced = abs(total_debits - total_credits) < 0.01

        return {
            "is_balanced": is_balanced,
            "total_debits": total_debits,
            "total_credits": total_credits,
            "discrepancy": round(abs(total_debits - total_credits), 4),
            "accounts": accounts,
            "checked_at": time.time()
        }
