# ARAA PRIVATE LIMITED — WALLET & PAYMENT INFRASTRUCTURE AUDIT (`WALLET_AUDIT.md`)

**Audit Date:** 2026-11-12  
**Inspected Modules:**
- `backend/company_finance.py` (`CompanyCapitalManager`, `POOL_INDIA_INR`, `POOL_CRYPTO_SPOT`)
- `backend/company_ledger_recon.py` (`CompanyLedgerService`, `CompanyReconciliationService`)
- `backend/financial_ledger.py` (Legacy V3 `DoubleEntryLedger`)
- `backend/upi_gateway.py` & `backend/razorpay_gateway.py` (Legacy retail payment rails)

---

## 1. Existing Wallet & Treasury State

1. **Company Prop Desk Capital Pools (`company_capital_pools` & `company_capital_movements`):**
   - **Status:** `IMPLEMENTED` & `AUTOMATED TESTED`.
   - Uses exact integer `paise` (INR) and `Decimal` strings.
   - Tracks `allocated_capital_paise`, `broker_confirmed_equity_paise`, `free_funds_paise`, `locked_funds_paise`, `realized_pnl_paise`, `unrealized_pnl_paise`, `fees_paise`, `taxes_expenses_paise`, and `reconciliation_status`.
   - Hard-blocks any cross-pool transfer between India (`POOL_INDIA_INR`) and Crypto (`POOL_CRYPTO_SPOT`).
2. **Legacy Retail Wallets (`wallets`, `deposits`, `withdrawals`, `upi_gateway.py`, `razorpay_gateway.py`):**
   - **Finding:** Legacy tables use SQLite `REAL` (floating point) and were built for retail SaaS deposits/withdrawals.
   - **Security & Compliance Action:** When `COMPANY_ONLY_MODE=1` (default for proprietary operations) or until `CUSTOMER_WALLET_B` is legally authorized in `service_authorization_register`, customer deposits, withdrawals, and custody remain **strictly disabled**.

---

## 2. ARAA Wallet Infrastructure Architecture (Parts 5 & 8)

To satisfy **Part 5 (Sections 10–13)**, ARAA Wallet is structured into two strictly isolated wallet products:

### Product 1: `WALLET_A_COMPANY_TREASURY` (Operational for ARAA Private Limited)
- Tracks and reconciles ARAA's own corporate treasury bank accounts (INR fiat) and corporate digital-asset treasury balances.
- Supports internal treasury deposits, withdrawals, capital pool funding vouchers, bank account verification records, and blockchain explorer reconciliation.

### Product 2: `WALLET_B_CUSTOMER_WALLET` (Built in Software, Locked Behind Authorization & Custody Gate)
- Complete schema and service architecture for future customer INR Fiat Wallets and Digital-Asset Wallets.
- **Hard Launch Gate:** Customer deposits, withdrawals, address generation, and custody remain blocked with `403 REGULATORY_AUTHORIZATION_REQUIRED` unless `service_authorization_register` has verified `APPROVED_FOR_PRODUCTION` status for RBI PPI/Escrow Partner (Fiat) or FIU-IND + Qualified Custody/HSM Partner (Crypto).

### 11-State Immutable Double-Entry Wallet Ledger
Every wallet transaction (`wallet_transactions` & `wallet_ledger_entries`) records:
- `transaction_id`, `wallet_id`, `wallet_product` (`TREASURY_A` vs `CUSTOMER_B`), `asset`, `network`, `debit_account`, `credit_account`, `amount_minor` (`paise` / `satoshi` / `wei` string), `fee_minor`, `state`, `reference_id`, `timestamp`, `source`, `approval_record_id`.
- **11 Enforced States:** `CREATED`, `PENDING`, `AUTHORIZED`, `PROCESSING`, `SUBMITTED`, `CONFIRMED`, `COMPLETED`, `FAILED`, `REJECTED`, `REVERSED`, `RECONCILIATION_REQUIRED`.
- Completed financial entries are immutable; corrections require a new auditable `REVERSED` or `ADJUSTMENT` entry.
- **Private Key Safety:** Private keys are never stored in frontend code, database columns, source files, or logs. Crypto signing is abstracted behind an `HSMKeySignerInterface` requiring external HSM/multisig custody hardware.

