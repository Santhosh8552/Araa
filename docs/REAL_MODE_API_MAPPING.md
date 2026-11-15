# ARAABOT REAL MODE 2.0 – API ENDPOINT MAPPING

The following endpoints are implemented in `backend/app.py` under the `/api/bot/real-mode/` prefix:

| Endpoint | Method | Role | Description |
|---|---|---|---|
| `/api/bot/real-mode/status` | `GET` | USER / ADMIN | Retrieves current Real Mode engine state, active strategy, and emergency stop status. |
| `/api/bot/real-mode/preflight` | `GET` / `POST` | USER / ADMIN | Runs the 20-point preflight validation suite and returns detailed check results. |
| `/api/bot/real-mode/activate` | `POST` | USER / ADMIN | Activates live auto scalping/trading after passing preflight checks. |
| `/api/bot/real-mode/pause` | `POST` | USER / ADMIN | Pauses new order submissions while keeping existing positions monitored. |
| `/api/bot/real-mode/stop` | `POST` | USER / ADMIN | Stops the trading bot without closing existing open positions. |
| `/api/bot/real-mode/account` | `GET` | USER / ADMIN | Returns real CoinDCX wallet balance, available futures margin, and account eligibility. |
| `/api/bot/real-mode/positions` | `GET` | USER / ADMIN | Returns active live open positions on CoinDCX with real-time unrealized PnL. |
| `/api/bot/real-mode/orders` | `GET` | USER / ADMIN | Lists recent order mappings and execution records submitted to CoinDCX. |
| `/api/bot/real-mode/fills` | `GET` | USER / ADMIN | Retrieves confirmed fill records with actual executed quantities, prices, and fees. |
| `/api/bot/real-mode/protection` | `GET` | USER / ADMIN | Returns active position protections (Stop-Loss and Take-Profit orders/status). |
| `/api/bot/real-mode/pnl` | `GET` | USER / ADMIN | Computes live USD profit dashboard (realized, unrealized, today, weekly, monthly, fees). |
| `/api/bot/real-mode/reconciliation`| `GET` / `POST` | USER / ADMIN | Executes live state reconciliation between CoinDCX exchange and internal database. |
| `/api/bot/real-mode/events` | `GET` | USER / ADMIN | Streams real-time bot activity log events for entries, exits, adjustments, and errors. |
