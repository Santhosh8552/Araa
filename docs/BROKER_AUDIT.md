# ARAA PRIVATE LIMITED — BROKER & EXCHANGE INTEGRATION AUDIT (`BROKER_AUDIT.md`)

**Audit Date:** 2026-11-12  
**Inspected Adapters:**
- `backend/universal_broker_manager.py` (`UniversalBrokerManager`, `BrokerAdapter` 14-method contract)
- `backend/zerodha_adapter.py` (`ZerodhaKiteAdapter`, `MockZerodhaAdapter`)
- `backend/coindcx_spot_adapter.py` (`CoinDCXSpotAdapter`, `MockCoinDCXSpotAdapter`)
- `backend/coindcx_gateway.py` (Legacy/Retail CoinDCX REST gateway)
- `backend/exness_gateway.py` & `mt4_mt5_bridges/` (Exness MT4/MT5 Expert Advisor bridge)
- `backend/real_broker.py` (Legacy CCXT wrapper)

---

## 1. Broker Integration Status Matrix

| Provider / Adapter | Market Scope | Capital Pool | Auth & Signing | Capabilities Implemented | Status Tier |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Zerodha Kite Connect v3** (`backend/zerodha_adapter.py`) | India Equities (`NSE`, `BSE`) | `POOL_INDIA_INR` | OAuth Login URL + SHA-256 Checksum (`api_key + request_token + api_secret`) + `X-Kite-Version: 3` | Profile, Margins/Funds, Holdings, Positions, Open Orders, Instrument Master CSV Sync, Quote/LTP/OHLC, Margin Calculation, Order Place, Order Modify, Order Cancel, Order Status, Tradebook, Historical Candles, Statutory Charges Estimator, Static IP Enforcement, Daily 06:00 IST Token Expiry Alert. | `AUTOMATED TESTED`<br>*(Requires company Kite API key + registered static IP for `PROVIDER VERIFIED`)* |
| **CoinDCX Spot Company Adapter** (`backend/coindcx_spot_adapter.py`) | Crypto Spot (`COINDCX_SPOT`) | `POOL_CRYPTO_SPOT` | HMAC-SHA256 (`X-AUTH-APIKEY`, `X-AUTH-SIGNATURE`) | User Info, Balances (Available + Locked converted to INR paise), Spot Inventory Positions, Active Orders, Spot Market Metadata (`markets_details`), Live Ticker Quotes, Precision/Step-Size Quantizer, Spot Order Place, Order Cancel, Order Status, Trade History, Fee Calculation, **Spot-Only Policy** (blocks `B-*` futures, margin, leverage > 1x), **Withdrawal-Disabled Key Check**. | `AUTOMATED TESTED`<br>*(Requires company CoinDCX Spot API key for `PROVIDER VERIFIED`)* |
| **Universal Broker Manager** (`backend/universal_broker_manager.py`) | Multi-Market (`INDIA`, `CRYPTO`) | Strictly Isolated per Pool | Per-Account Fernet Decryption (`SECRETS_KEY`) | Eliminates global shared exchange clients; enforces `CompanyCapitalManager.assert_pool_isolation` before every sync or order route; supports deterministic per-account mock injection for test suites. | `AUTOMATED TESTED` |
| **Exness MT4/MT5 Bridge** (`backend/exness_gateway.py`) | Forex / Metals (`MT4`/`MT5`) | Legacy Terminal | Pairing Token + EA Polling | `/api/mt4/register`, `/api/mt4/sync`, `/api/mt4/poll`, `/api/mt4/order_callback`. | `AUTOMATED TESTED` |

---

## 2. Critical Safety Rules Verified

1. **Zero Fabricated Executions:** If Zerodha or CoinDCX rejects an order or returns an HTTP error, the order transitions to `REJECTED` with zero positions and zero ledger entries.
2. **Ambiguous Timeout Safety (`UNKNOWN` State):** If an HTTP order submission times out (`504` / `requests.Timeout`), the adapter never blindly retries. It returns `status="UNKNOWN"`, transitions the OMS order to `UNKNOWN`, and freezes the capital pool (`reconciliation_status="MISMATCH_HALTED"`) until broker order status is reconciled.
3. **No Live-to-Paper Fallback:** In `LIVE` mode, orders never fall back to paper simulation upon broker error.
4. **No Fake Exchange / Matching Engine:** ARAA Brokerage routes orders solely through authorized external broker/exchange adapters (`ZerodhaKiteAdapter`, `CoinDCXSpotAdapter`) or isolated `PAPER` simulation tagged explicitly as `execution_mode="PAPER"`.

