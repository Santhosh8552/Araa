"""
Automated unit tests for ARAA Corporate Finance & Double-Entry Accounting Service.
"""
import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

try:
    from corporate_accounting import CorporateAccountingService
    from database import query, write
    from migrations import run_migrations
except ImportError:
    from backend.corporate_accounting import CorporateAccountingService
    from backend.database import query, write
    from backend.migrations import run_migrations


class TestCorporateAccounting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run_migrations()
        CorporateAccountingService.seed_chart_of_accounts()

    def setUp(self):
        write("DELETE FROM general_ledger_entries WHERE company_id=999")
        write("DELETE FROM general_ledger_journals WHERE company_id=999")

    def test_01_chart_of_accounts_seeded(self):
        """Standard Indian corporate chart of accounts seeded with Assets, Liabilities, Equity, Revenues, Expenses."""
        accounts = CorporateAccountingService.list_accounts()
        self.assertGreaterEqual(len(accounts), 16)
        types = set(a["account_type"] for a in accounts)
        self.assertEqual(types, {"ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"})

    def test_02_double_entry_enforcement(self):
        """Postings where Debits != Credits must be strictly rejected."""
        unbalanced = [
            {"account_code": "1010", "debit_paise": 100000, "credit_paise": 0},
            {"account_code": "3010", "debit_paise": 0, "credit_paise": 50000},  # Unbalanced
        ]
        res = CorporateAccountingService.post_journal_entry(
            company_id=999,
            posting_date="2026-11-12",
            narrative="Initial Share Capital Injection",
            lines=unbalanced,
        )
        self.assertFalse(res["success"])
        self.assertIn("Double-entry violation", res["error"])

    def test_03_balanced_journal_and_trial_balance(self):
        """Balanced journals must post and reflect in a balanced Trial Balance."""
        # 1. Share capital injection: Bank (Asset Dr) 50,00,000 INR, Share Capital (Equity Cr) 50,00,000 INR
        balanced_entry = [
            {"account_code": "1010", "debit_paise": 500000000, "credit_paise": 0},
            {"account_code": "3010", "debit_paise": 0, "credit_paise": 500000000},
        ]
        res = CorporateAccountingService.post_journal_entry(
            company_id=999,
            posting_date="2026-11-12",
            narrative="Founder Share Capital Subscription",
            lines=balanced_entry,
        )
        self.assertTrue(res["success"])
        self.assertTrue(res["journal_id"].startswith("jnl_"))

        # 2. Check Trial Balance
        tb = CorporateAccountingService.get_trial_balance(999)
        self.assertTrue(tb["is_balanced"])
        self.assertEqual(tb["grand_total_debit_paise"], 500000000)
        self.assertEqual(tb["grand_total_credit_paise"], 500000000)

    def test_04_profit_and_loss_calculation(self):
        """Revenues - Expenses = Net Profit accurately calculated."""
        # Trading Gain: Cash Dr 2,50,000 INR, Trading Revenue Cr 2,50,000 INR
        rev_entry = [
            {"account_code": "1010", "debit_paise": 25000000, "credit_paise": 0},
            {"account_code": "4010", "debit_paise": 0, "credit_paise": 25000000},
        ]
        CorporateAccountingService.post_journal_entry(
            company_id=999,
            posting_date="2026-11-12",
            narrative="Day Alpha Alpha Prop Gain",
            lines=rev_entry,
        )

        # Exchange fees: Brokerage Expense Dr 5,000 INR, Cash Cr 5,000 INR
        exp_entry = [
            {"account_code": "5010", "debit_paise": 500000, "credit_paise": 0},
            {"account_code": "1010", "debit_paise": 0, "credit_paise": 500000},
        ]
        CorporateAccountingService.post_journal_entry(
            company_id=999,
            posting_date="2026-11-12",
            narrative="STT and Turnover Fees",
            lines=exp_entry,
        )

        pnl = CorporateAccountingService.get_profit_and_loss(999)
        self.assertTrue(pnl["is_profitable"])
        # Net profit = 2,50,000 - 5,000 = 2,45,000 INR = 24,500,000 paise
        self.assertEqual(pnl["net_profit_paise"], 24500000)
        self.assertEqual(pnl["net_profit_inr"], "245,000.00")


if __name__ == "__main__":
    unittest.main()
