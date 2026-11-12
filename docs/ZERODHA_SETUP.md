# ARAA India Pool — Zerodha Kite Connect v3 Setup (`ZERODHA_SETUP.md`)

**Pool:** `POOL_INDIA_INR` (Strictly isolated from `POOL_CRYPTO_SPOT`; accounted in integer INR paise)  
**Adapter:** `backend/zerodha_adapter.py` (`ZerodhaKiteAdapter`)  
**Official Docs:** https://kite.trade/docs/connect/v3/

---

## 1. Corporate & Exchange Prerequisites
1. Open/authorize a **Company/Corporate Demat & Trading Account** with Zerodha (no retail customer custody).
2. Create a Kite Connect v3 app in the Zerodha Developer Console under company credentials.
3. Configure the **Redirect URL** to your HTTPS domain callback (e.g. `https://<domain>/company/?broker=zerodha`).
4. Register a **Static Production Egress IP** with Zerodha / exchange algo permissions where applicable (`STATIC_EGRESS_IP`).
5. Ensure SEBI & exchange corporate algo registration / dealer approvals are documented in the `Company & Compliance` tab before enabling `LIVE` execution.

## 2. Connecting Inside `/company/`
1. Sign in to `http://localhost:5050/company/` (or HTTPS production URL) as `COMPANY_DIRECTOR` or `TECHNICAL_ADMIN`.
2. Navigate to **India Pool · Zerodha**:
   - Enter `Account Name`, **API Key**, **API Secret**, and **Static Egress IP**.
   - Click **Connect Zerodha Account** (credentials are encrypted with `enc1:` Fernet at rest via `SECRETS_KEY`).
3. Click **1. Open Kite OAuth Login**, sign in with Zerodha corporate credentials + TOTP, copy the `request_token` from the callback URL, and click **2. Complete Request Token**.
4. Click **3. Verify & Sync India Pool** — populates broker-confirmed `free_funds_inr` and `broker_confirmed_equity_inr` strictly inside `POOL_INDIA_INR`.

## 3. Daily Token Lifecycle
- Zerodha Kite access tokens expire daily around **06:00 IST**.
- The background supervisor (`backend/company_worker.py`) monitors `token_expires_at` and raises operational warnings inside `system_incidents` (and optional Slack/Telegram alerts) when `< 60` minutes remain.
- Operators must complete the daily OAuth login before NSE/BSE market open (`09:15 IST`).

