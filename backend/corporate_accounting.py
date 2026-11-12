"""
ARAA PRIVATE LIMITED — Corporate Finance, Double-Entry General Ledger & Accounting Service.

Features:
- Standard Chart of Accounts (Assets, Liabilities, Equity, Revenues, Expenses).
- Strict Double-Entry Journal Postings (Sum of Debits MUST equal Sum of Credits).
- Trial Balance computation.
- Profit & Loss (P&L) Statement generation.
- Balance Sheet computation (Assets = Liabilities + Equity).
- Cash Flow Statement generation.
- Tax & Statutory Compliance Workflows (GST, TDS, Advance Tax, Annual Filing).
"""

import hashlib
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

try:
    from database import query, query_one, write, writes
except ImportError:
    from backend.database import query, query_one, write, writes


DEFAULT_COA = [
    # 1000 - ASSETS
    ("1010", "Cash & Bank Balances (HDFC Current Account)", "ASSET", "INR", "1000", "Operating corporate current accounts"),
    ("1020", "India Equities Proprietary Trading Pool (Zerodha Kite)", "ASSET", "INR", "1000", "Company trading capital deployed on NSE/BSE"),
    ("1030", "Digital Asset Spot Proprietary Pool (CoinDCX)", "ASSET", "INR", "1000", "Company crypto spot holdings (1x leverage)"),
    ("1040", "Corporate IT & High-Performance Compute Infrastructure", "ASSET", "INR", "1000", "Physical servers and high-speed network hardware"),

    # 2000 - LIABILITIES
    ("2010", "Trade Payables & Vendor Obligations", "LIABILITY", "INR", "2000", "Cloud, market data, and telecom vendor obligations"),
    ("2020", "Statutory TDS Withholding Payable (Section 194C/J)", "LIABILITY", "INR", "2000", "Withholding tax deducted on vendor payouts"),
    ("2030", "Goods and Services Tax (GST) Payable", "LIABILITY", "INR", "2000", "Output GST liabilities due to government"),

    # 3000 - EQUITY
    ("3010", "Paid-Up Share Capital", "EQUITY", "INR", "3000", "Initial equity shareholding subscribed by founders"),
    ("3020", "Retained Earnings / Accumulated Reserves", "EQUITY", "INR", "3000", "Undistributed proprietary trading profits and operational net earnings"),

    # 4000 - REVENUES
    ("4010", "Proprietary Trading Gains (Indian Equities / Zerodha)", "REVENUE", "INR", "4000", "Realized quantitative alpha trading gains"),
    ("4020", "Proprietary Trading Gains (Crypto Spot / CoinDCX)", "REVENUE", "INR", "4000", "Realized crypto spot arbitrage and directional gains"),
    ("4030", "FinTech Software Licensing & Advisory Fees", "REVENUE", "INR", "4000", "Enterprise white-label software distribution royalties"),

    # 5000 - EXPENSES
    ("5010", "Brokerage, Exchange & SEBI Turnover Fees", "EXPENSE", "INR", "5000", "Direct broker commissions, STT, and clearing fees"),
    ("5020", "Cloud Compute & Low-Latency Data Hosting", "EXPENSE", "INR", "5000", "AWS, GCP, Render, and colocated data center infrastructure"),
    ("5030", "Employee Compensation, Payroll & Contractor Fees", "EXPENSE", "INR", "5000", "Quant researchers, developers, and management CTC"),
    ("5040", "Legal, Audit & MCA Regulatory Filing Expenses", "EXPENSE", "INR", "5000", "Statutory audit fees, ROC filings, and legal retainers"),
]


class CorporateAccountingService:
    """Manages double-entry bookkeeping, chart of accounts, and financial statements."""

    @classmethod
    def seed_chart_of_accounts(cls):
        """Seeds standard Indian corporate chart of accounts idempotently."""
        now = time.time()
        for code, name, acct_type, ccy, parent, desc in DEFAULT_COA:
            write(
                """
                INSERT INTO chart_of_accounts(account_code, account_name, account_type, currency, parent_code, description, is_active, created_at)
                VALUES(?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(account_code) DO UPDATE SET account_name=excluded.account_name, description=excluded.description
                """,
                (code, name, acct_type, ccy, parent, desc, now),
            )

    @classmethod
    def list_accounts(cls) -> List[Dict[str, Any]]:
        return query("SELECT * FROM chart_of_accounts WHERE is_active=1 ORDER BY account_code ASC")

    @classmethod
    def post_journal_entry(
        cls,
        company_id: int,
        posting_date: str,
        narrative: str,
        lines: List[Dict[str, Any]],
        posted_by: str = "SYSTEM_ACCOUNTANT",
        doc_ref: str = "",
    ) -> Dict[str, Any]:
        """
        Posts a double-entry journal.
        Enforces: Sum(Debits) MUST EQUAL Sum(Credits) exactly in Paise.
        """
        if len(lines) < 2:
            return {"success": False, "error": "Journal entry must have at least two balanced lines"}

        total_debit = sum(int(l.get("debit_paise", 0)) for l in lines)
        total_credit = sum(int(l.get("credit_paise", 0)) for l in lines)

        if total_debit != total_credit:
            return {
                "success": False,
                "error": f"Double-entry violation: Total debits (₹{total_debit/100:,.2f}) != Total credits (₹{total_credit/100:,.2f})",
            }

        if total_debit <= 0:
            return {"success": False, "error": "Journal total must be greater than zero"}

        now = time.time()
        journal_id = f"jnl_{uuid.uuid4().hex[:10]}"
        jnl_num = f"JV-{int(now)}-{uuid.uuid4().hex[:4].upper()}"
        period_key = posting_date[:7]  # YYYY-MM

        write(
            """
            INSERT INTO general_ledger_journals(journal_id, company_id, journal_number, posting_date, period_key, narrative, source_document_ref, posted_by, is_posted, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (journal_id, company_id, jnl_num, posting_date, period_key, narrative.strip(), doc_ref.strip(), posted_by.strip(), now),
        )

        for l in lines:
            entry_id = f"gle_{uuid.uuid4().hex[:10]}"
            write(
                """
                INSERT INTO general_ledger_entries(entry_id, journal_id, company_id, account_code, debit_paise, credit_paise, currency, created_at)
                VALUES(?, ?, ?, ?, ?, ?, 'INR', ?)
                """,
                (entry_id, journal_id, company_id, l["account_code"], int(l.get("debit_paise", 0)), int(l.get("credit_paise", 0)), now),
            )

        return {
            "success": True,
            "journal_id": journal_id,
            "journal_number": jnl_num,
            "total_paise": total_debit,
            "total_inr": f"{total_debit / 100:,.2f}",
        }

    @classmethod
    def get_trial_balance(cls, company_id: int) -> Dict[str, Any]:
        """Calculates Trial Balance across all chart of accounts."""
        accounts = cls.list_accounts()
        totals = query(
            """
            SELECT account_code, SUM(debit_paise) as total_debit, SUM(credit_paise) as total_credit
            FROM general_ledger_entries
            WHERE company_id=?
            GROUP BY account_code
            """,
            (company_id,),
        )
        totals_map = {r["account_code"]: r for r in totals}

        tb_rows = []
        grand_debit = 0
        grand_credit = 0

        for a in accounts:
            code = a["account_code"]
            t = totals_map.get(code, {"total_debit": 0, "total_credit": 0})
            deb = int(t["total_debit"] or 0)
            cred = int(t["total_credit"] or 0)
            grand_debit += deb
            grand_credit += cred
            tb_rows.append({
                "account_code": code,
                "account_name": a["account_name"],
                "account_type": a["account_type"],
                "debit_paise": deb,
                "credit_paise": cred,
                "debit_inr": f"{deb / 100:,.2f}",
                "credit_inr": f"{cred / 100:,.2f}",
            })

        is_balanced = (grand_debit == grand_credit)
        return {
            "rows": tb_rows,
            "grand_total_debit_paise": grand_debit,
            "grand_total_credit_paise": grand_credit,
            "grand_total_debit_inr": f"{grand_debit / 100:,.2f}",
            "grand_total_credit_inr": f"{grand_credit / 100:,.2f}",
            "is_balanced": is_balanced,
        }

    @classmethod
    def get_profit_and_loss(cls, company_id: int) -> Dict[str, Any]:
        """Calculates Profit & Loss Statement (Revenues - Expenses)."""
        entries = query(
            """
            SELECT e.account_code, a.account_name, a.account_type, SUM(e.debit_paise) as deb, SUM(e.credit_paise) as cred
            FROM general_ledger_entries e
            JOIN chart_of_accounts a ON a.account_code=e.account_code
            WHERE e.company_id=? AND a.account_type IN ('REVENUE', 'EXPENSE')
            GROUP BY e.account_code, a.account_name, a.account_type
            """,
            (company_id,),
        )

        revenues = []
        expenses = []
        total_rev_paise = 0
        total_exp_paise = 0

        for r in entries:
            deb = int(r["deb"] or 0)
            cred = int(r["cred"] or 0)
            if r["account_type"] == "REVENUE":
                net = cred - deb
                total_rev_paise += net
                revenues.append({"code": r["account_code"], "name": r["account_name"], "amount_inr": f"{net/100:,.2f}"})
            else:
                net = deb - cred
                total_exp_paise += net
                expenses.append({"code": r["account_code"], "name": r["account_name"], "amount_inr": f"{net/100:,.2f}"})

        net_profit_paise = total_rev_paise - total_exp_paise
        return {
            "revenues": revenues,
            "total_revenue_inr": f"{total_rev_paise/100:,.2f}",
            "expenses": expenses,
            "total_expense_inr": f"{total_exp_paise/100:,.2f}",
            "net_profit_paise": net_profit_paise,
            "net_profit_inr": f"{net_profit_paise/100:,.2f}",
            "is_profitable": (net_profit_paise > 0),
        }
