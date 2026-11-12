# ARAA Crypto Pool — CoinDCX Company Spot-Only Setup (`COINDCX_SETUP.md`)

**Pool:** `POOL_CRYPTO_SPOT` (Strictly isolated from `POOL_INDIA_INR`; exact `Decimal` spot accounting)  
**Adapter:** `backend/coindcx_spot_adapter.py` (`CoinDCXSpotAdapter`)  
**Official Docs:** https://docs.coindcx.com/

---

## 1. Mandatory Spot-Only Safety Rules
ARAA enforces strict **Spot-Only** policy on CoinDCX:
- **Withdrawals MUST be disabled** on the company API key (verified at connect/verify time; keys with withdrawals enabled are rejected).
- **No Futures (`B-*`), No Perpetuals, No Margin, No Leverage > 1x** — blocked unconditionally inside `CoinDCXSpotAdapter.validate_instrument` and `place_order`.
- Only verified INR / USDT spot pairs matching CoinDCX market metadata precision (`min_quantity`, `step`, `min_notional`) are eligible.

## 2. Corporate Account & API Key Setup
1. Provision a **Company Entity CoinDCX Account** with completed corporate KYC and **FIU-IND VDA** compliance documentation.
2. Generate API Key + Secret with ONLY **Read** and **Spot Trade** permissions enabled (**Withdrawal = OFF**).
3. Whitelist the company server's static egress IP (`STATIC_EGRESS_IP`) in CoinDCX API settings.

## 3. Connecting Inside `/company/`
1. Sign in to `/company/` and open **Crypto Pool · CoinDCX Spot**.
2. Enter `Account Name`, **API Key**, **API Secret**, confirm **Withdrawals Disabled** (`Yes`), and click **Connect Spot Account**.
3. Click **Verify & Sync Spot Pool**:
   - Signs requests with `HMAC-SHA256` (`X-AUTH-APIKEY` / `X-AUTH-SIGNATURE`).
   - Synchronizes spot balances + active spot markets strictly into `POOL_CRYPTO_SPOT`.
   - Never displays balances or trades inside `POOL_INDIA_INR`.

