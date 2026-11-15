# ARAABOT REAL MODE 2.0 – SOURCE-LEVEL CODE AUDIT REPORT

## Audit Scope
Inspection of all core trading, risk, broker, and execution files:
- `backend/strategy_engine.py`
- `backend/bot_engine.py`
- `backend/coindcx_gateway.py`
- `backend/coindcx_adapter.py`
- `backend/coindcx_spot_adapter.py`
- `backend/analysis_engine.py`
- `backend/risk_engine.py`
- `backend/oms_engine.py`
- `backend/price_feed.py`
- `backend/database.py`

---

## 1. Critical Preflight Defect Analysis
- **File**: `backend/strategy_engine.py` (`validate_real_bot_preflight`, lines 339-360)
- **Defects Identified**:
  1. Only checks 5 basic criteria (connection, balance, futures permission, strategy enabled, emergency shutdown).
  2. Does **not** verify: account identification, open position retrieval, open order retrieval, strict reconciliation match, market data availability, quantity and price precision, minimum order value, daily loss limit breach, existing stop-loss protection, database connectivity, or OMS readiness.
  3. Returns `{"ready": True, "state": "READY"}` even when reconciliation status is uncertain.

---

## 2. Mandatory Stop-Loss Defect Analysis
- **File**: `backend/bot_engine.py` (lines 1380-1386, 1678-1683, 2586-2600)
- **File**: `backend/strategy_engine.py` (line 531)
- **File**: `backend/coindcx_adapter.py` (lines 550-565)
- **Defects Identified**:
  1. `bot_engine.py` line 1678: `if why == "STOP_LOSS" and not is_live: self.close(p, price, why)` explicitly blocks closing on stop-loss if `is_live=True`.
  2. `bot_engine.py` lines 1380-1386: `if not is_live:` wraps `SMART_STOP_PROTECT`, `AUTO_STOP_LOSS_GUARD`, and `TECHNICAL_STOP_LOSS`, completely disabling stop-loss monitoring for live trades.
  3. `bot_engine.py` line 2587: `exch_stop_loss = sl_price if rbc_sl >= 1.0 else None` drops exchange-side stop loss on CoinDCX if `rbc_sl < 1.0`.
  4. `coindcx_adapter.py` line 550: `create_tpsl` only attaches `take_profit` and excludes `stop_loss`.
  5. `strategy_engine.py` line 531: `if not bool(position.get("is_live")) and move_pct <= -sl_pct:` stops stop loss exits in profit evaluation for live positions.

---

## 3. Exchange Fill Confirmation Defect Analysis
- **File**: `backend/coindcx_adapter.py` (lines 370-380)
- **File**: `backend/bot_engine.py` (lines 2610-2615)
- **Defects Identified**:
  1. `coindcx_adapter.py` line 372: `filled_qty = float((res_ord or {}).get("spot_equivalent_quantity") or ... or req_qty)`. If CoinDCX returns a pending order response without fill details, it assumes `req_qty` was 100% filled.
  2. `bot_engine.py` line 2613: `filled_qty = float(ad_res.get("filled_qty") or qty)`. Converts requested quantity into confirmed fill without polling or querying order status.

---

## 4. Paper vs Live Isolation Defect Analysis
- **File**: `backend/strategy_engine.py` (lines 427-432, 439-445)
- **File**: `backend/risk_engine.py` (lines 165, 181, 214)
- **Defects Identified**:
  1. `strategy_engine.py` line 428: `SELECT COUNT(*) AS c FROM positions WHERE user_id=? AND status IN ('OPEN','PENDING_BROKER')` fails to filter by `is_live` or `execution_mode`, counting Paper positions against Live position limits and vice-versa.
  2. `strategy_engine.py` line 439: `SELECT COALESCE(SUM(realized_pnl), 0.0) AS pnl ... FROM positions WHERE user_id=? AND status='CLOSED' AND closed_at>=?` lumps Paper and Live P&L together for daily loss limits.
  3. `risk_engine.py` lines 181, 214: Aggregates all closed positions without filtering by `is_live`.
