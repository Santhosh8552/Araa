#!/usr/bin/env python3
"""
Production Entrypoint for AraaBot.in & Trade Pro Platform.

Supports:
1. Direct CLI execution:
   - `python run.py`
   - `python run.py --port 5050 --no-open`
2. Cloud / WSGI execution (Render, Railway, Docker, Heroku, VPS):
   - `gunicorn --workers 1 --threads 8 --timeout 120 --keep-alive 5 --bind 0.0.0.0:$PORT run:app`
3. Autonomous anti-sleep keep-alive heartbeat daemon for cloud deployments.
"""
import argparse
import os
import sys
import threading
import time
import urllib.request
import webbrowser

# Prevent __pycache__ clutter in workspace
sys.dont_write_bytecode = True

# Validate & sanitize TLS CA bundle path so stale venv paths never crash HTTPS requests
for ca_var in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE"):
    val = os.environ.get(ca_var)
    if val and not os.path.exists(val):
        os.environ.pop(ca_var, None)

try:
    import certifi
    if os.path.exists(certifi.where()):
        os.environ["SSL_CERT_FILE"] = certifi.where()
        os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
except Exception:
    pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(CURRENT_DIR, "backend")
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from backend import app as backend_app

# Export Flask WSGI application for Gunicorn / uWSGI / Cloud servers (`run:app`)
app = backend_app.api

_initialized = False
_init_lock = threading.Lock()
_tracked_count = 0


def start_engine():
    """Initialize SQLite WAL database, market instruments, price feeds, and autonomous bot engine once."""
    global _initialized, _tracked_count
    with _init_lock:
        if not _initialized:
            try:
                _tracked_count = backend_app.boot_data()
                print(f"[BOOT] Market data primed: {_tracked_count} instruments active", flush=True)
                print("[BOOT] Autonomous trading bot & live TradingView feeds are ONLINE", flush=True)
            except Exception as exc:
                print(f"[BOOT] Warning during initial boot: {exc}", flush=True)
            _initialized = True
            _start_keepalive_if_configured()
            if os.environ.get("COMPANY_WORKER_ENABLED", "1") != "0":
                try:
                    from backend.company_worker import company_worker
                    company_worker.start()
                except Exception as wk_exc:
                    print(f"[WORKER] Warning starting company worker: {wk_exc}", flush=True)
    return _tracked_count


def _start_keepalive_if_configured():
    """Background keep-alive pinger to prevent free-tier cloud containers from sleeping."""
    external_url = (
        os.environ.get("RENDER_EXTERNAL_URL")
        or os.environ.get("KEEP_ALIVE_URL")
        or os.environ.get("APP_URL")
    )
    if not external_url:
        return

    target_url = external_url.rstrip("/") + "/healthz"
    print(f"[KEEPALIVE] Autonomous anti-sleep heartbeat daemon activated for {target_url}", flush=True)

    def _pinger():
        time.sleep(30)
        while True:
            try:
                req = urllib.request.Request(
                    target_url,
                    headers={"User-Agent": "AraaBot-KeepAlive/2.0"}
                )
                with urllib.request.urlopen(req, timeout=15) as res:
                    status_code = res.getcode()
                print(f"[KEEPALIVE] Periodic heartbeat OK (HTTP {status_code})", flush=True)
            except Exception as exc:
                print(f"[KEEPALIVE] Heartbeat notice: {exc}", flush=True)
            time.sleep(540)

    t = threading.Thread(target=_pinger, daemon=True, name="keepalive-daemon")
    t.start()


def parse_args():
    parser = argparse.ArgumentParser(description="AraaBot.in & Trade Pro Unified Server")
    parser.add_argument(
        "--host",
        default=os.environ.get("HOST", backend_app.HOST),
        help="Host interface to bind (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", backend_app.MAIN_PORT)),
        help="Port number to bind (default: 5050)"
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not automatically open the browser on startup"
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Automatically open the trading terminal in the default browser"
    )
    return parser.parse_args()


# Automatically initialize engine when imported by Gunicorn (`gunicorn run:app`)
if __name__ != "__main__":
    start_engine()


def main():
    args = parse_args()
    host = args.host
    port = args.port
    tracked = start_engine()

    banner = f"""
================================================================================
 ⚡ ARAABOT.IN — QUANTUM BOOST 500x & EXNESS MT4/MT5 TRADING PLATFORM
================================================================================
 [ONLINE] Live TradingView Market Feed ({tracked} instruments active · 100% Signals)

 🌐 UNIFIED APPLICATION LINKS (Port {port}):
 --------------------------------------------------------------------------------
 📈 Live Trading Web Terminal : http://localhost:{port}
 🏢 Company Control Center    : http://localhost:{port}/company
 🔴 Real MT4/MT5 Bridge Desk  : http://localhost:{port}/#real-terminal
 🛡️ Admin Management Portal   : http://localhost:{port}/admin
 📖 Swagger Interactive Docs  : http://localhost:{port}/docs
 ❤️ Health Check Endpoint     : http://localhost:{port}/healthz
================================================================================
"""
    print(banner, flush=True)

    if args.open and not args.no_open and not os.environ.get("DOCKER_CONTAINER"):
        threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{port}")).start()

    try:
        backend_app.api.run(
            host=host,
            port=port,
            debug=False,
            use_reloader=False,
            threaded=True
        )
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Stopping AraaBot engine and market feeds...", flush=True)
        try:
            backend_app.bot.stop_loop()
            backend_app.feed.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
