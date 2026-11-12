# 🚀 AraaBot — Production Cloud Deployment & CoinDCX Operations Guide

This guide details how to deploy **AraaBot** to production cloud platforms (**Render**, **Railway**, **Docker / VPS**) with **zero errors**, full resilience against network hiccups, persistent database storage, and complete **CoinDCX Login / Logout** management.

---

## 📋 Table of Contents
1. [Deployment Architecture](#1-deployment-architecture)
2. [Option A: Deploy to Render.com (Recommended)](#2-option-a-deploy-to-rendercom-recommended)
3. [Option B: Deploy to Railway.app](#3-option-b-deploy-to-railwayapp)
4. [Option C: Self-Hosted Docker VPS (Ubuntu / Debian / AWS EC2)](#4-option-c-self-hosted-docker-vps)
5. [Required Environment Variables](#5-required-environment-variables)
6. [CoinDCX Account Authentication & Login/Logout Management](#6-coindcx-account-authentication--loginlogout-management)
7. [Zero-Error Resilience Safeguards](#7-zero-error-resilience-safeguards)

---

## 1. Deployment Architecture

```
                    ┌────────────────────────────┐
                    │      Cloud Web Client      │
                    │   (Desktop / Mobile PWA)   │
                    └─────────────┬──────────────┘
                                  │ HTTPS / WSS
                                  ▼
               ┌──────────────────────────────────────┐
               │         Gunicorn WSGI Engine         │
               │   (Flask App + 8 Async Worker Threads│
               │     + Background Keepalive Pinger)   │
               └──────────────────┬───────────────────┘
                                  │
         ┌────────────────────────┼────────────────────────┐
         ▼                        ▼                        ▼
┌──────────────────┐    ┌──────────────────┐     ┌──────────────────┐
│  Araa AI Engine  │    │  CoinDCX Gateway │     │  SQLite Database │
│ • 85%+ Win Prob  │    │ • HMAC-SHA256    │     │ • Users & Config │
│ • Multi-Position │    │ • Online (IP)    │     │ • Audit Trail    │
│ • Order Blocks   │    │ • Offline Sim    │     │ • Persistent Disk│
└──────────────────┘    └──────────────────┘     └──────────────────┘
```

- **Runtime:** Python 3.11+
- **WSGI Server:** Gunicorn with 8 concurrent worker threads
- **Database:** SQLite with WAL mode & automated column migrations
- **Market Feeds:** Live TradingView quotes (1014 instruments) + Direct CoinDCX Spot & Futures

---

## 2. Option A: Deploy to Render.com (Recommended)

AraaBot comes pre-configured with a native `render.yaml` blueprint.

### Steps:
1. Push your AraaBot repository to **GitHub** or **GitLab**.
2. Sign in to [Render.com](https://render.com).
3. Click **New +** ➡️ **Blueprint**.
4. Select your AraaBot repository. Render will automatically detect `render.yaml`.
5. Review the settings:
   - **Environment:** `Python`
   - **Build Command:** `pip install --upgrade pip && pip install -r requirements.txt`
   - **Start Command:** `gunicorn --workers 1 --threads 8 --timeout 120 --keep-alive 5 --bind 0.0.0.0:${PORT:-5050} run:app`
   - **Health Check Path:** `/healthz`
6. (Optional) Under **Disks**, add a persistent disk mounted at `/app/data` with environment variable `DB_PATH=/app/data/tradepro.db` so all trades and credentials persist across restarts.
7. Click **Apply**. Render will build and deploy your app in ~2 minutes with a free SSL URL (e.g. `https://araabot-trade-pro.onrender.com`).

---

## 3. Option B: Deploy to Railway.app

AraaBot has a production `Dockerfile` and `Procfile` ready for Railway.

### Steps:
1. Go to [Railway.app](https://railway.app) and click **New Project** ➡️ **Deploy from GitHub repo**.
2. Select your AraaBot repository.
3. In the project **Settings**:
   - Railway will automatically detect the `Dockerfile` or `Procfile`.
   - Set the **Healthcheck Path** to `/healthz`.
4. In **Variables**, add:
   - `PORT` = `5050`
   - `PYTHONUNBUFFERED` = `1`
   - `DB_PATH` = `/app/data/tradepro.db`
5. Under **Volumes**, add a Volume mounted to `/app/data`.
6. Click **Deploy**. Your custom domain or `*.up.railway.app` URL will be live.

---

## 4. Option C: Self-Hosted Docker VPS

For dedicated servers, AWS EC2, DigitalOcean Droplets, or Linode:

### 1-Line Deployment:
```bash
# Clone and enter repo
git clone <your-repo-url> araabot
cd araabot

# Start in background with persistent volume
docker compose up -d --build
```

### Check Logs & Status:
```bash
docker compose logs -f araabot
curl http://localhost:5050/healthz
```

Your terminal will be running at `http://YOUR_SERVER_IP:5050`. To attach an SSL domain, put Nginx or Caddy in front with HTTPS reverse proxying to `http://127.0.0.1:5050`.

---

## 5. Required Environment Variables

All variables have safe fallbacks, meaning AraaBot boots immediately without configuration:

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `PORT` | `5050` | Port listened to by Flask & Gunicorn |
| `HOST` | `0.0.0.0` | Bind host (all interfaces for cloud containers) |
| `DB_PATH` | `backend/tradepro.db` | Path to persistent SQLite database |
| `PYTHONUNBUFFERED` | `1` | Forces real-time log output |
| `RENDER_EXTERNAL_URL` | *(Auto)* | Render public URL for keepalive pinging |

---

## 6. CoinDCX Account Authentication & Login/Logout Management

### How Login Works:
1. Open the **AraaBot Institutional Crypto Terminal** (`/terminal` or Topbar CoinDCX Badge).
2. If not logged in, the **CoinDCX Login Form** appears:
   - **CoinDCX API Key**
   - **CoinDCX API Secret** (toggleable visibility)
   - **Whitelisted IP Address** (matches what you entered in CoinDCX)
   - **Real CoinDCX Wallet Balance (₹ INR)**
3. Choose your connection mode:
   - **⚡ CONNECT ONLINE (STRICT COINDCX IP):** Connects directly to CoinDCX servers with HMAC-SHA256 verification (requires matching IP whitelist on CoinDCX).
   - **🟢 CONNECT OFFLINE MODE (ZERO-IP SETUP):** Uses real CoinDCX prices with zero IP setup required.
4. The interface updates instantly to the **Live Terminal Desk** with live balances and Spot/Futures adapter status.

### How Logout & Switch Account Works:
1. In the terminal header, two buttons are available:
   - **🚪 Logout CoinDCX:** Cancels all active exchange limit orders, liquidates open bot positions, clears stored API credentials, resets the session to `DISCONNECTED`, and transitions the view back to the clean login form.
   - **🔄 Switch / Login Account:** Prompts for confirmation to disconnect the current account and enter new credentials without requiring a browser refresh.
2. The REST API endpoints:
   - `POST /api/real-bot/coindcx/logout`
   - `POST /api/real-bot/coindcx/disconnect`

---

## 7. Zero-Error Resilience Safeguards

AraaBot includes multiple production shields to ensure zero error popups:

1. **Global Frontend Error Shields:**
   - Unhandled JavaScript promises and cross-origin iframe events (such as TradingView chart script noise) are trapped silently without throwing red popups.
2. **Backend 404 & 500 Catchers:**
   - Custom Flask error handlers return structured JSON with safe fallback messages for API requests, and serve `index.html` for single-page application route transitions.
3. **Database Schema Auto-Migration:**
   - On every server start, `init_schema()` checks all required columns (`max_positions`, `is_live_active`, `broker_connections`, etc.) and automatically alters tables if missing, preventing SQLite schema mismatches.
4. **Leverage & Risk Shield:**
   - Position sizing evaluates the user's allocated margin (`₹622.50`) against risk rules rather than raw 500x nominal notional, preventing spurious order rejections.
5. **Instant Liquidate on Bot OFF:**
   - Turning the bot OFF via Topbar button, Bot drawer, or Emergency Kill Switch immediately closes all open bot positions and cancels active exchange orders.



## Security configuration (required after the latest update)

Set these environment variables on your server (Render: Environment tab; Docker: `.env`):

| Variable | Purpose |
|---|---|
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Admin panel login. There is **no default admin** any more; without these the admin login returns 503. |
| `SECRETS_KEY` | Long random string. Encrypts stored CoinDCX API keys/secrets in the database. Keep it safe. |
| `ADMIN_SESSION_TTL` | Optional admin session lifetime in seconds (default 43200). |
| `COINDCX_FALLBACK_MAX_LEVERAGE` | Optional. Futures leverage used only if CoinDCX does not report a contract max (default 10). |

All `/api/admin/*` endpoints now require the `X-Admin-Token` header returned by `/api/admin/login`.

If an API key (for example `GEMINI_API_KEY`) was ever inside a shared `.env` file or zip, **rotate it**.
