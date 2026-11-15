# ARAABOT REAL MODE 2.0 – UI & PANEL ACCESS MAPPING

This document specifies the exact separation of UI components between the **User Panel**, **Company Panel**, and **Admin Panel**.

---

## 1. Strict Panel Access Enforcement

```
┌────────────────────────────────────────────────────────┐
│                   AraaBot Ecosystem                    │
├─────────────────────────┬──────────────────────────────┤
│  ADMIN / COMPANY PANELS │          USER PANEL          │
│  (Internal Operations)  │       (Client Facing)        │
├─────────────────────────┼──────────────────────────────┤
│ • System Monitoring     │ • Real-time USD Dashboard    │
│ • Update History        │ • Live Bot Controls          │
│ • Automated Validation  │ • Scalping Strategy Selector │
│ • Database Health       │ • Active Open Positions      │
│ • Security Audit        │ • Trade History & Fills      │
│ • Integration Health    │ • Protection Order Status    │
│ • Production Readiness  │ • Bot Activity Log           │
│ • Capital Pools / ERP   │ • Manual Emergency Stop      │
│ • Broker Conn Center    │                              │
│ • Ledger Reconciliation │ [STRICTLY ISOLATED FROM      │
│ • Risk Guardian         │  INTERNAL SYSTEM HEALTH &    │
│ • Compliance Center     │  AUTOMATED TEST DIAGNOSTICS] │
└─────────────────────────┴──────────────────────────────┘
```

---

## 2. User Panel Real Mode Dashboard
Located in `templates/` and `static/js/`:
- **Real-Time USD Profit Dashboard**:
  - Net Realized Profit (Daily / Weekly / Monthly / All-Time).
  - Mark-to-Market Unrealized Profit & Active Positions Margin.
  - Transparent Fee Deduction Breakdown (Trading Fees + Funding Fees).
- **Execution Controller**:
  - Live 20-Point Preflight Status Indicator (`READY` in green, `BLOCKED` in yellow, `ERROR` in red).
  - Mode Switch (Paper vs Real Mode) with strict visual distinction.
  - Action Controls: `Start Auto Bot`, `Pause Bot`, `Stop Bot`, and prominent Red `EMERGENCY STOP` button.
- **Auto Scalping Configuration**:
  - Timeframe selector: 1m (entry trigger), 5m (setup confirmation), 15m (trend filter).
  - Strategy selector: EMA Momentum, RSI Momentum, MACD Scalp, Breakout Scalp, Araa AI Scalp.
- **Protection & Order Transparency Table**:
  - Displays each open trade with entry price, confirmed filled size, exchange stop-loss status, and take-profit targets (TP1, TP2).
  - Real-time Bot Activity Log showing evaluated rules, spread checks, and execution results.

---

## 3. Admin & Company Panel Monitoring
Access is gated on server-side RBAC (`ADMIN`, `SUPER_ADMIN`, `COMPANY_ADMIN`, `COMPANY_OPERATOR`):
- **Admin Panel**:
  - System Monitoring & Health: CPU, memory, socket connections, worker threads.
  - Update History & Program Change History.
  - Automated Validation (Playwright, API, Integration tests).
  - Database Health & Connection Pool Metrics.
  - Production Deployment Readiness Checklist.
- **Company Panel**:
  - Institutional Trading & Company Capital Pool Management.
  - Broker Connection Center (Multi-Broker status, CoinDCX Futures, Zerodha, Exness).
  - Order Management System (OMS) & Execution Audit.
  - Financial Ledger & Ledger Reconciliation Center.
  - Corporate Risk Guardian & Compliance Center.
