# ARAA Platform — Existing Features Inventory (`EXISTING_FEATURES.md`)

**Baseline Codebase:** `AraaBot-Online-Production-Ready`  
**Verification Basis:** Direct source inspection and `python -m unittest discover -s tests -p "test_*.py" -v` (`43/43` tests passing as of 2026-11-11).

---

## 1. Existing Modules to Preserve & Extend

| Module | File | Key Symbols & Capabilities | Verification Status |
| :--- | :--- | :--- | :--- |
| **Live Market Feeds** | `backend/price_feed.py` | Real-time price caching (`price`, `quote`, `get_price_feed`) across Binance crypto pairs, TradingView codes, and global equities/forex/metals (`crypto_universe.json`, `world_universe.json`). | Verified via live `/api/v1/markets/prices` & feed loop |
| **Technical Analysis** | `backend/analysis_engine.py` | Multi-indicator scanning (RSI, EMA/SMA, MACD, Bollinger Bands, ATR, VWAP). | Verified in bot analysis endpoints |
| **ML Prediction Engine** | `backend/prediction_engine.py` | Feature extraction, GRU sequence forecasting, multi-horizon trend prediction & accuracy audit. | Verified (`test_prediction_engine.py` — 5 tests pass) |
| **3-Agent AI Committee** | `backend/ai_committee.py` | `AgentAlphaMarketIntelligence`, `AgentBetaTechnicalIntelligence`, `AgentGammaRiskIntelligence`, weighted consensus, persisted rationales in `ai_committee_logs`. | Verified (`test_v3_platform.py`) |
| **Central ARAA AI Core** | `backend/araa_ai_core.py` | `AIModelRegistry`, `AIContextManager`, `AIToolRegistry`, `AIDecisionLogger`, `AIHealthMonitor`, `AraaAIOrchestrator` (`process_chat`). | Verified (`test_v3_enterprise_ecosystem.py` & live `/api/v1/ai/chat`) |
| **AI Fallback & Gemini** | `backend/gemini_advisor.py` | `predict_pre_entry` with automatic deterministic fallback when external Gemini quota/credits are unavailable. | Verified (`test_ai_engine.py` — 7 tests pass) |
| **Quantum Intelligence** | `backend/quantum_engine.py` | Smart-Money Concepts (SMC) / displacement & setup scoring. | Verified via `/api/quantum/intel` |
| **Historical Backtesting** | `backend/backtest_engine.py` | Fee (`0.05%`), slippage (`0.02%`), 8h funding rate simulation, equity curve, max drawdown, profit factor, Sharpe ratio, trade-by-trade log. | Verified (`test_v3_platform.py`) |
| **Event Bus & Outbox** | `backend/event_bus.py` | Thread-safe pub/sub backed by SQLite `event_outbox` (`get_event_bus`, `Events`). | Verified (`test_v3_enterprise_ecosystem.py`) |
| **Risk Engine** | `backend/risk_engine.py` | `InstitutionalRiskEngine` / `RiskGuardian`: pre-trade sizing, daily/weekly/monthly loss caps, max drawdown, max open positions ceiling, kill switches (`GLOBAL` and per-bot). | Verified (`test_v3_platform.py`, `test_v3_enterprise_ecosystem.py`) |
| **OMS / EMS Core** | `backend/oms_engine.py` | `OrderManagementSystem`, `ExecutionManagementSystem`, `PositionManager`, `PortfolioManager`, `OrderLifecycleManager`. | Verified (`test_v3_enterprise_ecosystem.py`) |
| **Double-Entry Ledger** | `backend/financial_ledger.py` | `DoubleEntryLedger` with Chart of Accounts (`1001`–`5001`), immutable debit/credit postings, `get_trial_balance()`. | Verified (`test_v3_enterprise_ecosystem.py`) |
| **Multi-Bot Supervisor** | `backend/bot_supervisor.py` | `BotSupervisor`, `BotLifecycleState` (create, start, pause, stop, clone, execution logs). | Verified (`test_v3_enterprise_ecosystem.py`) |
| **CoinDCX Gateway** | `backend/coindcx_gateway.py` | Official CoinDCX HMAC-SHA256 signing, public tickers/candles, futures/spot order calls, live-close verification (`close_real_order`), and leverage rules. | Unit-tested against mocks (`test_security_and_close.py`, `test_coindcx_futures_leverage.py`); live key validation requires active company API key |
| **Exchange Adapter Base** | `backend/exchange_adapter.py` | `BaseExchangeAdapter` interface + `CoinDCXExchangeAdapter` wrapper + `BrokerAdapter` structure. | Verified (`test_v3_platform.py`) |
| **Exness MT4/MT5 Bridge** | `backend/exness_gateway.py`, `mt4_mt5_bridges/` | EA pairing, token registration, terminal polling (`/api/mt4/poll`, `/api/mt4/sync`, `/api/mt4/order_callback`). | Verified (`test_exness_mt4_workflow.py` — 3 tests pass) |
| **Security & WAF** | `backend/security_firewall.py`, `backend/database.py` | Ingress SQLi/XSS/path-traversal filter, rate limits, `hash_password` (PBKDF2), `encrypt_secret`/`decrypt_secret` (Fernet), `X-Admin-Token` guard. | Verified (`test_security_and_close.py` — 12 tests pass) |
| **Frontend & Admin UI** | `frontend/`, `admin/` | Live charts (TradingView widget), bot terminal controls (leverage, position cap, direction), V3 suite modal, ARAA AI chat drawer, Admin Gatekeeper/Firewall/V3 Health dashboard. | Verified HTTP 200 serving on `/` and `/admin/` |

---

## 2. Existing Features Scheduled for Deprecation / Isolation Under Company-Only Prop Model

These modules exist and function in SaaS mode, **but conflict with Section 1 ("No customer deposits, custody, or brokerage services")**:
- Customer Wallets & Cashflows: `wallets`, `deposits`, `withdrawals`, `profit_links`, `brokerage_ledger`, `user_bank_accounts`.
- Customer Payment Rails: `backend/upi_gateway.py` (Google Pay / PhonePe QR), `backend/razorpay_gateway.py`, `backend/saas_manager.py` (SaaS subscription checkout).
- Customer Onboarding & Demat Applications: `demat_applications`, `broker_provider_consents`, user-submitted third-party `broker_connections`.
- Shared Multi-User Seed Data: `SEED_DEMO_USERS` bootstrapping `user@gmail.com` / synthetic balances.

