# ARAABOT REAL MODE 2.0 – DATABASE MAPPING

This document details database tables and column additions utilized by the Real Mode 2.0 trading engine.

---

## 1. `real_bot_configs`
Stores user-level live bot execution settings, risk limits, and emergency controls.

- `user_id` (INTEGER PRIMARY KEY): Reference to `users.id`.
- `provider_id` (TEXT): Broker name (`COINDCX`, `ZERODHA`, `EXNESS`).
- `broker_account_id` (TEXT): Associated exchange account ID.
- `market_segments` (TEXT): Allowed markets (e.g., `FUTURES`, `SPOT`).
- `strategy_mode` (TEXT): Mode (`SCALP`, `INTRADAY`, `SWING`).
- `max_order_size` (REAL): Max USD notional allowed per trade.
- `max_daily_loss` (REAL): Max allowable realized loss in USD per day.
- `max_exposure_limit` (REAL): Aggregate portfolio exposure ceiling in USD.
- `max_leverage` (REAL): Maximum allowed leverage on derivatives.
- `stop_loss_pct` (REAL): Mandatory stop-loss percentage.
- `take_profit_pct` (REAL): Default take-profit percentage.
- `trailing_stop_enabled` (INTEGER): `1` if trailing stop active, `0` otherwise.
- `execution_speed` (TEXT): Order speed setting (`FAST`, `NORMAL`).
- `bot_status` (TEXT): Engine status (`IDLE`, `RUNNING`, `PAUSED`, `STOPPED`, `EMERGENCY_STOP`).
- `emergency_shutdown` (INTEGER): `1` if emergency stop triggered; locks all execution until reset.
- `verified_funds` (REAL): Confirmed balance on last audit.
- `verified_margin` (REAL): Confirmed available margin on last audit.
- `last_risk_audit_at` (REAL): Timestamp of most recent risk engine audit.
- `created_at` / `updated_at` (REAL): Unix timestamps.

---

## 2. `positions`
Stores open and closed positions for both Paper and Live modes.

- `id` (INTEGER PRIMARY KEY AUTOINCREMENT)
- `user_id` (INTEGER): Foreign key to `users.id`.
- `symbol` (TEXT): Trading pair (e.g. `BTCUSDT`).
- `source` (TEXT): Signal source (`ARAA_AI`, `TRADINGVIEW`, `MANUAL`).
- `side` (TEXT): `BUY` / `LONG` or `SELL` / `SHORT`.
- `qty` (REAL): Active remaining contract quantity.
- `margin` (REAL): Margin allocated in USD.
- `entry_price` (REAL): Weighted average entry price.
- `current_price` (REAL): Mark/live price.
- `target_pct` (REAL): Take profit target percentage.
- `stop_pct` (REAL): Stop loss trigger percentage.
- `status` (TEXT): `OPEN` or `CLOSED`.
- `realized_pnl` (REAL): Realized PnL accumulated on close/partial closes in USD.
- `unrealized_pnl` (REAL): Mark-to-market unrealized PnL in USD.
- `is_live` (INTEGER): `1` for Real Mode (CoinDCX live), `0` for Paper Trading.
- `partial_tp_booked` (INTEGER): Number of partial take-profit stages executed (0, 1, 2).
- `peak_pnl_pct` (REAL): High-water mark profit percentage for trailing stops.
- `close_reason` (TEXT): Trigger for closure (`STOP_LOSS`, `TAKE_PROFIT`, `TRAILING_STOP`, `EMERGENCY_STOP_TRIGGERED`).
- `opened_at` / `closed_at` (REAL): Unix timestamps.

---

## 3. `position_protections`
Manages exchange-side and local secondary stop-loss / take-profit tracking.

- `user_id` (INTEGER)
- `position_id` (TEXT): Internal position ID.
- `exchange_position_id` (TEXT): CoinDCX position UUID.
- `symbol` (TEXT): Instrument symbol.
- `market_type` (TEXT): `FUTURES`, `SPOT`, or `MARGIN`.
- `entry_price` (REAL): Executed entry price.
- `filled_qty` (REAL): Confirmed fill quantity.
- `stop_loss_price` (REAL): Calculated stop-loss trigger price.
- `take_profit_price` (REAL): Calculated take-profit trigger price.
- `trailing_stop_pct` (REAL): Trailing stop percentage offset.
- `sl_order_id` (TEXT): CoinDCX exchange stop loss order ID.
- `tp_order_id` (TEXT): CoinDCX exchange take profit order ID.
- `protection_verified` (INTEGER): `1` if confirmed on exchange, `0` otherwise.
- `protection_status` (TEXT): `VERIFIED`, `MONITORED_BACKEND`, `FAILED`, `CANCELLED`.
- `failure_reason` (TEXT): Error message if exchange attachment failed.
- `updated_at` (REAL): Unix timestamp.

---

## 4. `order_mappings`
Audit trail of every client order submitted to the exchange.

- `client_order_id` (TEXT PRIMARY KEY): Unique UUID preventing duplicate orders.
- `exchange_order_id` (TEXT): Exchange assigned ID.
- `user_id` (INTEGER)
- `symbol` (TEXT)
- `side` (TEXT)
- `mode` (TEXT): `REAL` or `PAPER`.
- `requested_qty` (REAL)
- `filled_qty` (REAL): Confirmed filled quantity from exchange callback/response.
- `avg_fill_price` (REAL): Executed average price.
- `fee_usd` (REAL): Trading fees charged by exchange.
- `status` (TEXT): `NEW`, `PARTIALLY_FILLED`, `FILLED`, `REJECTED`, `CANCELLED`.
- `rejection_reason` (TEXT)
- `created_at` (REAL)
