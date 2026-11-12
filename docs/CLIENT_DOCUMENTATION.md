# TRADE PRO — CLIENT DOCUMENTATION & PLATFORM SPECIFICATION

**Project Version:** 3.8 (Quantum Boost Multi-Market Edition)  
**Classification:** Enterprise Institutional Paper Trading & AI Automation Terminal  
**Primary Engine:** ARAA AI 3.8 Neural Execution Engine (Gemini, Claude, GPT Multi-Model Advisor)  
**Environments:** User Web Terminal (`:7777`), Admin Command Center (`:7779`), Flask Core API (`:5050`)

---

## 1. Executive Summary

**Trade Pro** is a high-performance institutional simulation and paper trading platform engineered for multi-market asset classes. The terminal ingests **real-time tick data and multi-timeframe candle feeds** across 976 global instruments (Forex, Global Stocks, Crypto, Indices, Metals, Commodities, and Bonds) with zero delay.

All financial execution operates in a strictly isolated, risk-free simulation environment using virtual capital (INR / ₹) with real mark-to-market calculations, authentic order books, and dynamic leverage up to **500x**.

### Core Value Pillars
- **Real-Time Market Ingestion:** 976 live feeds aggregated from Binance WebSocket feeds, TradingView scanner clusters, and CNBC quotes.
- **ARAA AI 3.8 Neural Engine:** Multi-agent decision pipeline integrating Gemini 3.8, Claude 3.5, and OpenAI GPT-4o for Bayesian pre-entry predictions, dynamic stop-loss invalidation, and automated execution.
- **Full-Featured Admin Governance:** Real-time brokerage accounting (30% revenue share model), user balance controls, global bot master switches, KYC/account approvals, and live telemetry feeds.
- **Cybernetic 3D Trading Terminal:** Immersive user cockpit with 3D stage pipelines, customizable viewports, TradingView charts, and responsive mobile-ready interfaces.

---

## 2. System Architecture

```mermaid
graph TD
    subgraph Market Feeds
        BF[Binance 24/7 WebSockets]
        TV[TradingView Multi-Country Scanners]
        CNBC[CNBC & Index Quotes]
    end

    subgraph Backend Core (:5050)
        PF[Price Feed Ingester - 976 Assets]
        AE[Technical Analysis Engine - RSI/EMA/VWAP]
        AA[ARAA AI Neural Engine - Gemini 3.8 / LLMs]
        BE[Automated Bot Executor - Loop & Exit Rail]
        DB[(SQLite / Database tradepro.db)]
    end

    subgraph Client Applications
        UT[User Terminal :7777 - Trading Cockpit]
        AD[Admin Dashboard :7779 - Direct Management]
    end

    BF --> PF
    TV --> PF
    CNBC --> PF
    PF --> AE
    AE --> AA
    AA --> BE
    BE --> DB
    DB --> UT
    DB --> AD
```

---

## 3. Key Modules & Functional Overview

### 3.1. User Trading Terminal (`frontend/` · Port 7777)
The user interface is designed for professional traders, prop firm challenges, and paper-money experimentation:
1. **Interactive Charts:**
   - Real-time candlestick charts with built-in indicators (MA 50, Volume profiles, RSI, Crosshair, and OHLC telemetry).
   - Instant TradingView Deep Link (`FULL LIVE CHART ON TRADINGVIEW ↗`) for verified price comparison.
2. **Multi-Market Watchlist:**
   - 976 symbols divided across 9 asset classes: `CRYPTO`, `FOREX`, `FUTURES`, `INDICES`, `METALS`, `BONDS`, `ECONOMY`, `OPTIONS`, and `WORLD STOCKS` (top 12 companies from 36 countries).
   - Real-time country filters, search, and A-Z sorting.
3. **Execution & Leverage:**
   - Single-click manual order placement for Long (Buy) and Short (Sell).
   - Dynamic leverage configuration ranging from **1x up to 500x Boost**.
   - Real-time margin calculator, liquidation price estimator, and target risk-to-reward ratio checker.
4. **ARAA AI 3.8 Neural Terminal View:**
   - Interactive 3D pipeline showing real-time scanning stages (Radar → Quantum Screen → Regime Router → Neural Brain → 500x Execution).
   - User-controlled **`🧠 AI FORECAST`** button to view AI trade setups, confidence probabilities, and entry zones on demand without obstructing the chart.

---

### 3.2. ARAA AI 3.8 Neural Engine (`backend/gemini_advisor.py` & `backend/bot_engine.py`)
The platform includes an autonomous institutional AI trading assistant:
- **Prediction-First Protocol:** Every prospective trade is evaluated before capital commitment. It establishes:
  - Bayesian Win Probability ($P(UP)$ vs $P(DN)$)
  - Directional Bias (`BUY`, `SELL`, `HOLD`, `NO_TRADE`)
  - Target Take-Profit and Stop-Loss invalidation price
  - Risk-to-Reward Ratio ($R:R \ge 1:2.0$)
- **Automated Trading Modes:**
  | Strategy Mode | Minimum Win Rate Target | Min Confidence | Default Leverage | Target Assets |
  | :--- | :--- | :--- | :--- | :--- |
  | **⚡ Quantum Boost** | **92%** | 0.75 | **500x** | High-liquidity Crypto/FX |
  | **Continuous Active** | **88%** | 0.72 | **20x** | Continuous multi-market loops |
  | **Safe & Conservative** | **95%** | 0.82 | **10x** | Low-volatility Equities/FX |
  | **Target Scalping** | **90%** | 0.78 | **50x** | Gold, Silver, BTC, ETH |
  | **Aggressive Momentum** | **85%** | 0.74 | **100x** | High-beta breakout movers |
- **Weekend Liquidity Protection:** Traditional markets (Forex, Equities, Indices) automatically switch to Weekend Pause on Friday evening UTC, dynamically routing 100% of trading activity to 24/7 Crypto liquidity pools.

---

### 3.3. Admin Command Dashboard (`admin/` · Port 7779)
Direct administrative control center requiring zero complex setup:
1. **Master Switch & Kill Switches:**
   - Global AI Bot Master Switch (disables or enables automated trading across all accounts in 1 click).
   - Emergency close-all-positions rail.
2. **User & Capital Management:**
   - View, credit, or debit user balances, deposit approvals, and withdrawal clearances.
   - Adjust individual user starting balances and profit target tracking.
3. **Brokerage & Financial Ledger:**
   - Real-time 30% brokerage fee computation generated from trade margin and volume.
   - Breakdown of realized platform profits, net turnover, and platform fees.
4. **Live 3D Execution Pipeline Visualizer:**
   - Real-time visual representation of all 5 operational stages of the bot backend.
   - Active throughput counters, latency metrics, and candidate qualification statistics.

---

## 4. API Endpoints Reference

The backend provides a RESTful JSON API running on port `5050`:

### Authentication & Account
- `POST /api/auth/login`: User authentication (`email`, `password`).
- `POST /api/auth/register`: Create new trader account.
- `GET /api/account/summary`: Fetch balance, equity, margin, closed trades, and goal progress.
- `GET /api/user/mode`: Current trade mode (`PAPER` vs `LIVE`).

### Market Data & Quotes
- `GET /api/market/quotes`: Complete list of live price feeds for all 976 instruments.
- `GET /api/market/candle-history?symbol=BTCUSDT&timeframe=15m`: Fetch OHLC candle history for charting.
- `GET /api/market/categories`: List supported categories and asset counts.

### Trading & Orders
- `POST /api/trade/open`: Place market or limit order (`symbol`, `side`, `margin`, `leverage`, `stop_loss`, `take_profit`).
- `POST /api/trade/close`: Liquidate an open position (`position_id`).
- `GET /api/trade/positions`: List all active open positions with live unrealized P&L.
- `GET /api/trade/history`: Fetch historical closed trades with execution timestamps.

### ARAA AI & Bot Engine
- `GET /api/ai/predict?symbol=BTCUSDT&tf=15m`: Pre-entry forecast with Bayesian win probability and regime check.
- `POST /api/bot/toggle`: Start/stop AI bot for the logged-in user.
- `GET /api/bot/status`: Bot telemetry, active strategy mode, scan cycle, and logs.
- `GET /api/ai/calculate-size`: Formula-driven capital exposure, stop-loss distance, and liquidation price calculator.

### Admin Controls
- `GET /api/admin/overview`: System-wide metrics, active users, total platform equity, and brokerage.
- `POST /api/admin/bot/global-toggle`: Global kill-switch for automated bot execution.
- `POST /api/admin/user/adjust-balance`: Manual credit/debit adjustments for user wallets.

---

## 5. Quick-Start & Installation Guide

### Prerequisites
- **Python 3.10+**
- **Node.js 18+**
- **Git**

### Installation Steps

1. **Clone or Extract Project:**
   ```bash
   cd Trade-Pro-Admin-Direct-Open
   ```

2. **One-Command Setup:**
   ```bash
   npm run setup
   ```
   *This automatically sets up Python virtual environments and installs all required dependencies (`Flask`, `Flask-CORS`, `google-genai`, etc.).*

3. **Launch the Platform:**
   ```bash
   npm start
   ```

4. **Access the Portals:**
   - **User Terminal:** [http://localhost:7777](http://localhost:7777)  
     *(Default Demo Login: `user@gmail.com` / `demo1234` or `goal.demo@gmail.com` / `goal1234`)*
   - **Admin Panel:** [http://localhost:7779](http://localhost:7779) *(Direct instant access)*
   - **REST Backend:** [http://127.0.0.1:5050](http://127.0.0.1:5050)

---

## 6. Security, Compliance & Deployment Notice

1. **Simulation Scope:** This platform is engineered for educational, analytical, and prop trading evaluation purposes. No real bank accounts or fiat payment processors are connected.
2. **Production Hardening:** When deploying to public servers or cloud VMs:
   - Ensure the Admin Panel (`:7779`) is placed behind a secure reverse proxy (e.g., NGINX with HTTP Basic Auth or VPN tunnel).
   - Maintain API keys (`GEMINI_API_KEY`, `OPENAI_API_KEY`) within secure `.env` files and never commit secrets to public repositories.
3. **Database Integrity:** SQLite database `tradepro.db` auto-initializes on startup with full demo records and seeds, ensuring a zero-configuration out-of-the-box experience.

---
*Trade Pro Institutional Solutions · ARAA AI 3.8 Neural Execution Platform*
