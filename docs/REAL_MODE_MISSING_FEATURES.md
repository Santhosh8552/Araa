# ARAABOT REAL MODE 2.0 – MISSING & DEFECTIVE FEATURES AUDIT

## 1. Executive Summary
This document records all functional gaps, security loopholes, and bypass defects identified in the AraaBot codebase prior to the Real Mode 2.0 upgrade.

---

## 2. Identified Deficiencies & Critical Vulnerabilities

### Defect 1: Preflight Declared `READY` On Unsuccessful Reconciliation
- **File**: `backend/strategy_engine.py` (line 384)
- **Defect**: Preflight previously recorded exchange connectivity but allowed initialization to report `READY` even when active exchange positions did not match internal positions.
- **Risk**: Positions opened outside AraaBot or ghost orders on CoinDCX could cause collateral exhaustion or liquidations.
- **Resolution**: Implemented mandatory 20-point preflight validation with explicit state machine (`INITIALIZING`, `CHECKING`, `READY`, `BLOCKED`, `ERROR`, `EMERGENCY_STOP`). Preflight returns `READY` only if all 20 checks pass without error.

### Defect 2: Live Mode Stop-Loss Protection Bypasses
- **File**: `backend/bot_engine.py` (lines 1380 & 1678) and `backend/strategy_engine.py` (line 595)
- **Defect**:
  - `backend/bot_engine.py` line 1678 contained `if why == "STOP_LOSS" and not is_live:`, explicitly disabling stop loss exits for live positions!
  - `backend/bot_engine.py` line 1380 wrapped smart stop protect and technical stop-loss in `if not is_live:`.
  - `backend/strategy_engine.py` line 595 contained `if not bool(position.get("is_live")) and move_pct <= -sl_pct:`.
- **Risk**: Catastrophic loss / total liquidation of user CoinDCX Futures account.
- **Resolution**: Removed all `if not is_live` bypasses. Mandatory stop loss is enforced strictly on BOTH Paper and Live modes at all times.

### Defect 3: Assumed Fill Quantity on Exchange Submission
- **File**: `backend/coindcx_adapter.py` (line 376)
- **Defect**: When an order was submitted to CoinDCX, `filled_qty` fell back to `req_qty` without verifying `spot_equivalent_quantity`, `filled_quantity`, or `quantity_filled`.
- **Risk**: Over-allocating internal margin and attaching TP/SL orders sized larger than actual filled contract sizes.
- **Resolution**: Extracted confirmed fill quantity from exchange response; handles `PARTIALLY_FILLED` and updates internal positions with actual filled quantities.

### Defect 4: Cross-Contamination of Paper and Live Mode States
- **File**: `backend/strategy_engine.py` (line 495)
- **Defect**: Hard risk evaluation queried positions and daily realized PnL without filtering by `is_live`, causing paper trades to halt live bots or vice versa.
- **Resolution**: Enforced strict `AND is_live=?` isolation across all hard risk checks, daily loss limits, and positions queries.

### Defect 5: Missing Multi-Stage R-Multiple Partial Profit Booking
- **File**: `backend/strategy_engine.py`
- **Defect**: Exit logic only offered simple 50% partial exit without structured R-multiple targets (TP1=1R, TP2=2R, trailing remainder).
- **Resolution**: Implemented `evaluate_v2_smart_profit_and_exit` with configurable R-multiples, partial profit booking (TP1 30%, TP2 30%), break-even locks, and non-widening trailing stops.
