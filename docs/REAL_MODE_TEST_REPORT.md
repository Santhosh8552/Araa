# ARAABOT REAL MODE 2.0 – TEST EXECUTION REPORT

## 1. Test Summary
- **Total Test Cases Executed**: 151
- **Passed**: 151
- **Failed**: 0
- **Errors**: 0
- **Duration**: ~8.0 seconds

---

## 2. Dedicated Real Mode 2.0 Test Suite (`tests/test_real_mode_v2.py`)

| Test Name | Focus | Result |
|---|---|---|
| `test_01_preflight_20_point_validation_ready` | 20-Point Preflight check completeness & `READY` state assertion | **PASS** |
| `test_02_preflight_blocked_when_offline` | Connection failure causes preflight to transition to `BLOCKED` | **PASS** |
| `test_03_preflight_emergency_stop_state` | Active emergency stop causes preflight state to report `EMERGENCY_STOP` | **PASS** |
| `test_04_live_stop_loss_not_bypassed` | Live positions trigger `STOP_LOSS_EXIT` on adverse move (no bypass) | **PASS** |
| `test_05_confirmed_exchange_fill_derivation` | Partial order execution derives confirmed filled quantity from exchange | **PASS** |
| `test_06_paper_vs_live_mode_isolation` | Paper mode losses and positions do not block or affect Live risk limits | **PASS** |
| `test_07_smart_profit_booking_and_trailing_exit`| Multi-stage R-multiple booking: TP1 (30%), TP2 (30%), Trailing Stop exit | **PASS** |
| `test_08_emergency_stop_closes_all_positions` | Emergency Stop triggers immediate market closure of all live positions | **PASS** |

---

## 3. Integration & Multi-Broker Test Suites
- `tests/test_coindcx_integration_a_to_f.py`: 9 Tests (**PASS**)
- `tests/test_company_enterprise_phase1.py` - `phase5.py`: All Phase tests (**PASS**)
- `tests/test_strategy_engine_integration.py`: (**PASS**)
- Core Webhook, OMS, Risk Guardian, and Corporate Accounting tests: (**PASS**)
