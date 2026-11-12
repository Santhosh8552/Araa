# Real Bot Mode — User Demat Account Onboarding & Compliance Architecture

This document describes the complete onboarding workflow, provider integrations, database schema, security safeguards, and user flow implemented for **Real Bot Mode** in TradePro.

---

## 1. Regulatory Context & Architectural Philosophy

TradePro operates as an algorithmic intelligence layer and execution routing interface. Under Indian financial regulations (SEBI mandates) and international exchange guidelines:
- A trading platform cannot independently create or maintain a Demat account without official Depository Participant (CDSL/NSDL) and SEBI broker registrations.
- Therefore, the platform integrates authorized Indian brokers (e.g. Zerodha, Angel One, Upstox) and global institutional exchanges (e.g. Bybit, Binance, Interactive Brokers) via their official onboarding, e-KYC, and OAuth/API endpoints.
- **Live Trading is strictly locked** until all provider confirmations, e-KYC verifications, risk acknowledgments, and explicit user confirmations are completed.

---

## 2. Multi-Step Onboarding Architecture

```mermaid
graph TD
    A[User clicks 'REAL BOT MODE' / 'MODE: PAPER'] --> B{Onboarding Check}
    B -->|Not Connected| C[Step 1: Account Choice Gateway]
    C -->|Option A| D[Apply for New Demat & Trading Account]
    C -->|Option B| E[Connect Existing Authorized Account]
    D --> F[Provider DigiLocker e-KYC & CDSL Verification]
    F -->|Callback: APPROVED| G[Retrieve Broker Account ID & Verified Funds]
    E -->|OAuth / API Verify| G
    G --> H[Step 3: Bot Strategy & Risk Limit Wizard]
    H --> I[Step 4: Legal & Risk Review & Explicit Activation]
    I --> J[Step 5: Live Bot Control Center (Starts in PAUSED state)]
    J -->|User explicitly clicks 'Start Bot'| K[Live Execution Engine Active]
```

### Step 1: Real Bot Mode Entry & Choice Gateway
- When the user clicks the top-bar `🟢 REAL BOT MODE (LOCKED)` button, trading **never** starts automatically.
- A dedicated onboarding gateway opens explaining that real-money trading requires an eligible, verified account with an authorized provider.
- Two distinct paths are presented:
  1. **Option 1: Open a New Demat Account** (Authorized Indian SEBI/CDSL Brokers).
  2. **Option 2: Connect Existing Account** (Authorized Brokers/Exchanges via OAuth/API).

### Step 2: Demat Application & Verification
- **New Account Flow:**
  - Collects only necessary identity credentials: PAN number (verified with standard 10-character alphanumeric check), last 4 digits of Aadhaar (for DigiLocker UIDAI verification), bank account details, and IFSC.
  - Generates a unique tracking reference: `DEMAT-<PROVIDER>-<UID>-<HEX>`.
  - Application states supported:
    - `NOT_STARTED`
    - `PENDING_VERIFICATION`
    - `ACTION_REQUIRED` (e.g., additional documentation request)
    - `APPROVED` (stamps verified broker Client ID and CDSL status)
    - `REJECTED` (with explicit rejection rationale)
- **Connect Existing Account Flow:**
  - Connects supported providers: Bybit, Binance, Zerodha, Angel One, Interactive Brokers, MetaTrader 5 Bridge, TradePro Direct.
  - Validates API key and API secret without logging secrets.
  - Enforces explicit algorithmic execution consent.

### Step 3: Market Segment Separation
The system maintains distinct eligibility checks per asset category:
- **Indian Equities & F&O:** Requires SEBI-compliant Demat & Trading account with CDSL depository verification.
- **Crypto (Spot & Futures):** Connects to supported crypto exchange gateway (no Demat required).
- **Forex & Metals (Gold/Silver):** Connects to authorized institutional bridge (Interactive Brokers / MT5).

### Step 4: Real Bot Configuration Wizard
After account verification, the user configures:
- **Strategy & AI Risk Profile:** Pure Crypto Scalper, Quantum Boost 500x, Continuous Active Trading, Target Scalping, or Safe & Conservative.
- **Max Order Size:** Hard ceiling per trade (₹500 to ₹5,00,000).
- **Max Daily Loss Limit:** Automated Kill Switch that immediately halts trading and cancels open orders if daily drawdown exceeds threshold.
- **Max Leverage Cap:** Up to 500x.
- **Take Profit & Stop Loss Limits:** Enforced on every live position.

### Step 5: Explicit Live Trading Activation
- Highlights prominent risk disclosures: Live real-money trading carries risk of capital loss; the platform never guarantees profits.
- Enforces 3 mandatory user checkboxes before enabling the activation button.
- **Pause-by-Default:** The bot initializes in `PAUSED` state. The user must explicitly press **▶ Start Bot** to begin live executions.

### Step 6: Live Control Center & Audit Trail
Once active, users have total consequential control:
- **▶ Start Bot:** Begins automated order routing.
- **⏸ Pause Bot:** Halts new entries while maintaining active positions.
- **⚡ Stop Bot & Cancel Orders:** Liquidates all open positions and cancels open pending orders.
- **Disconnect Account:** Safely severs provider connection and reverts back to Paper Mode.
- **Audit Event Log:** Tracks all application events, state transitions, and user consents in `real_bot_audit_logs`.

---

## 3. Database Schema Entities

1. `demat_applications`: Tracks user Demat applications, PAN, Aadhaar mask, provider, CDSL depository, and application status.
2. `broker_provider_consents`: Records regulatory user attestations, IP address, user-agent, and timestamps.
3. `real_bot_configs`: Stores user risk limits, max order sizes, stop-loss/take-profit, and bot status (`PAUSED`, `RUNNING`).
4. `real_bot_audit_logs`: Immutable audit trail for all real-money actions.
5. `broker_connections`: Tracks live provider balances, masked client identifiers, and live session status.

---

## 4. API Specification

| Endpoint | Method | Purpose |
| :--- | :--- | :--- |
| `/api/real-bot/providers` | `GET` | List authorized brokers and supported market segments |
| `/api/real-bot/onboarding-status` | `GET` | Returns unified onboarding state, applications, funds, and segment eligibility |
| `/api/real-bot/apply-demat` | `POST` | Submit new Demat application to authorized provider |
| `/api/real-bot/provider-verify-callback` | `POST` | Handles official provider verification callback (`APPROVED`, `ACTION_REQUIRED`, `REJECTED`) |
| `/api/real-bot/connect-existing` | `POST` | Connects existing provider account via authenticated credentials |
| `/api/real-bot/configure` | `POST` | Sets bot strategy, max order size, loss limits, leverage, and SL/TP |
| `/api/real-bot/toggle-state` | `POST` | Consequential actions: `START`, `PAUSE`, `STOP_AND_CANCEL_ORDERS`, `DISCONNECT` |
| `/api/real-bot/audit-logs` | `GET` | Retrieves tamper-evident compliance audit trail for user |
