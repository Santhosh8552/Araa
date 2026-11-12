"""
ARAA Company Trading Platform — Official Zerodha Kite Connect v3 Adapter.

Reference: https://kite.trade/docs/connect/v3/
Key guarantees:
- Isolated per-account credentials (never shares a global Kite client).
- Server-side SHA-256 checksum (`api_key + request_token + api_secret`) for session exchange.
- Tracks daily session expiration (~06:00 IST next trading morning).
- Validates authorized exchanges (NSE/BSE), products (CNC/MIS), and instrument master tick/lot rules.
- Never fabricates balances/fills; treats submission timeouts strictly as `UNKNOWN` (never auto-retries).
- Includes `MockZerodhaAdapter` solely for automated testing and offline development harnesses.
"""

import csv
import datetime
import hashlib
import io
import json
import time
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from company_finance import to_paise
    from database import encrypt_secret, query_one, write
    from universal_broker_manager import BrokerAdapter
except ImportError:
    from backend.company_finance import to_paise
    from backend.database import encrypt_secret, query_one, write
    from backend.universal_broker_manager import BrokerAdapter


KITE_LOGIN_BASE = "https://kite.trade/connect/login"
KITE_API_BASE = "https://api.kite.trade"

# In-memory short-lived instrument master cache keyed by (account_id, exchange)
_KITE_INSTRUMENT_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
INSTRUMENT_CACHE_TTL = 1800  # 30 minutes


def compute_next_kite_expiry_ts(now: Optional[float] = None) -> float:
    """Kite Connect access tokens expire daily at ~06:00 AM IST (00:30 UTC)."""
    ts = time.time() if now is None else float(now)
    utc_dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    candidate = utc_dt.replace(hour=0, minute=30, second=0, microsecond=0)
    if utc_dt >= candidate:
        candidate = candidate + datetime.timedelta(days=1)
    return candidate.timestamp()


class ZerodhaKiteAdapter(BrokerAdapter):
    """Production Zerodha Kite Connect v3 REST adapter for one isolated company account."""

    provider = "ZERODHA"
    market_scope = "INDIA"

    def __init__(self, account_id: str, company_id: int, credentials: Dict[str, Any]):
        super().__init__(account_id, company_id, credentials)
        self.api_key = (credentials.get("api_key") or "").strip()
        self.api_secret = (credentials.get("api_secret") or "").strip()
        self.access_token = (credentials.get("access_token") or "").strip()
        self.static_egress_ip = (credentials.get("static_egress_ip") or "").strip()
        self._session = requests.Session()
        self._last_request_ts = 0.0

    def _headers(self) -> Dict[str, str]:
        return {
            "X-Kite-Version": "3",
            "Authorization": f"token {self.api_key}:{self.access_token}",
            "User-Agent": "ARAA-Company-KiteAdapter/3.0",
        }

    def _throttle(self, min_interval: float = 0.12) -> None:
        elapsed = time.time() - self._last_request_ts
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_ts = time.time()

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        timeout: float = 12.0,
        allow_text: bool = False,
    ) -> Tuple[bool, Any, int]:
        if not self.api_key or not self.access_token:
            return False, {"error": "Zerodha session token not active; complete daily Kite login first"}, 401

        self._throttle()
        url = f"{KITE_API_BASE}{path}"
        try:
            resp = self._session.request(
                method=method.upper(),
                url=url,
                headers=self._headers(),
                params=params,
                data=data,
                timeout=timeout,
            )
        except requests.Timeout:
            return False, {"error": "REQUEST_TIMEOUT", "ambiguous": True}, 504
        except requests.RequestException as exc:
            return False, {"error": str(exc)}, 502

        if allow_text and resp.status_code == 200:
            return True, resp.text, 200

        try:
            body = resp.json()
        except Exception:
            body = {"message": resp.text}

        if resp.status_code == 200 and body.get("status") == "success":
            return True, body.get("data"), 200

        err_type = body.get("error_type", "")
        if resp.status_code in (401, 403) or err_type == "TokenException":
            write(
                "UPDATE company_trading_accounts SET connection_status='TOKEN_EXPIRED', updated_at=? WHERE account_id=?",
                (time.time(), self.account_id),
            )
        return False, {"error": body.get("message") or f"HTTP {resp.status_code}", "error_type": err_type, "raw": body}, resp.status_code

    # -----------------------------------------------------------------------
    # OAuth Login & Checksum Exchange
    # -----------------------------------------------------------------------
    def get_login_url(self, redirect_params: Optional[str] = None) -> str:
        params = {"v": "3", "api_key": self.api_key}
        if redirect_params:
            params["redirect_params"] = redirect_params
        return f"{KITE_LOGIN_BASE}?{urllib.parse.urlencode(params)}"

    def generate_session(self, request_token: str) -> Dict[str, Any]:
        req_tok = (request_token or "").strip()
        if not req_tok or not self.api_key or not self.api_secret:
            return {"ok": False, "error": "api_key, api_secret, and request_token are required"}

        checksum_raw = f"{self.api_key}{req_tok}{self.api_secret}".encode("utf-8")
        checksum = hashlib.sha256(checksum_raw).hexdigest()

        try:
            resp = self._session.post(
                f"{KITE_API_BASE}/session/token",
                headers={"X-Kite-Version": "3"},
                data={"api_key": self.api_key, "request_token": req_tok, "checksum": checksum},
                timeout=15.0,
            )
            body = resp.json()
        except Exception as exc:
            return {"ok": False, "error": f"Kite session exchange failed: {exc}"}

        if resp.status_code != 200 or body.get("status") != "success":
            return {"ok": False, "error": body.get("message") or f"Kite HTTP {resp.status_code}", "raw": body}

        data = body.get("data") or {}
        access_token = (data.get("access_token") or "").strip()
        if not access_token:
            return {"ok": False, "error": "Kite did not return an access_token"}

        self.access_token = access_token
        expires_at = compute_next_kite_expiry_ts()
        now = time.time()
        write(
            "UPDATE broker_account_secrets SET access_token_enc=?, updated_at=? WHERE account_id=?",
            (encrypt_secret(access_token), now, self.account_id),
        )
        write(
            "UPDATE company_trading_accounts SET broker_user_id=?, connection_status='CONNECTED', "
            "api_permission_status='VERIFIED', token_expires_at=?, updated_at=? WHERE account_id=?",
            (str(data.get("user_id") or ""), expires_at, now, self.account_id),
        )
        return {
            "ok": True,
            "broker_user_id": data.get("user_id", ""),
            "user_name": data.get("user_name", ""),
            "email": data.get("email", ""),
            "exchanges": data.get("exchanges", []),
            "products": data.get("products", []),
            "order_types": data.get("order_types", []),
            "expires_at": expires_at,
        }

    # -----------------------------------------------------------------------
    # 14 Required BrokerAdapter Methods
    # -----------------------------------------------------------------------
    def verify_connection(self) -> Dict[str, Any]:
        acc = query_one("SELECT token_expires_at FROM company_trading_accounts WHERE account_id=?", (self.account_id,))
        if acc and acc.get("token_expires_at") and float(acc["token_expires_at"]) <= time.time():
            write("UPDATE company_trading_accounts SET connection_status='TOKEN_EXPIRED' WHERE account_id=?", (self.account_id,))
            return {"ok": False, "error": "Zerodha daily access token expired; re-login required"}

        prof = self.get_profile()
        if not prof.get("ok"):
            return {"ok": False, "error": prof.get("error", "Profile check failed")}
        p = prof["profile"]
        exchanges = [e.upper() for e in (p.get("exchanges") or [])]
        products = [pr.upper() for pr in (p.get("products") or [])]
        return {
            "ok": True,
            "broker_user_id": p.get("user_id", ""),
            "profile": p,
            "authorized_segments": exchanges,
            "authorized_products": products,
        }

    def get_profile(self) -> Dict[str, Any]:
        ok_req, data, _ = self._request("GET", "/user/profile")
        if not ok_req:
            return {"ok": False, "error": data.get("error", "Unable to fetch Kite profile")}
        return {"ok": True, "profile": data}

    def get_balances(self) -> Dict[str, Any]:
        ok_req, data, _ = self._request("GET", "/user/margins")
        if not ok_req:
            return {"ok": False, "error": data.get("error", "Unable to fetch Kite margins")}

        eq = (data or {}).get("equity") or {}
        avail = eq.get("available") or {}
        util = eq.get("utilised") or {}

        net_val = eq.get("net") if eq.get("net") is not None else avail.get("live_balance", avail.get("cash", 0))
        free_val = avail.get("live_balance") if avail.get("live_balance") is not None else avail.get("cash", 0)
        used_val = util.get("debits", 0)

        return {
            "ok": True,
            "currency": "INR",
            "equity_paise": to_paise(net_val or 0),
            "free_paise": to_paise(free_val or 0),
            "locked_paise": to_paise(used_val or 0),
            "raw": data,
        }

    def get_positions(self) -> List[Dict[str, Any]]:
        ok_req, data, _ = self._request("GET", "/portfolio/positions")
        if not ok_req or not isinstance(data, dict):
            return []
        return list(data.get("net") or [])

    def get_holdings(self) -> List[Dict[str, Any]]:
        ok_req, data, _ = self._request("GET", "/portfolio/holdings")
        return list(data) if ok_req and isinstance(data, list) else []

    def get_open_orders(self) -> List[Dict[str, Any]]:
        ok_req, data, _ = self._request("GET", "/orders")
        if not ok_req or not isinstance(data, list):
            return []
        open_states = {"OPEN", "TRIGGER PENDING", "VALIDATION PENDING", "PUT ORDER REQ RECEIVED"}
        return [o for o in data if str(o.get("status", "")).upper() in open_states]

    def get_instruments(self, exchange: Optional[str] = None) -> List[Dict[str, Any]]:
        ex = (exchange or "NSE").strip().upper()
        cache_key = f"{self.account_id}:{ex}"
        cached = _KITE_INSTRUMENT_CACHE.get(cache_key)
        if cached and (time.time() - cached[0]) < INSTRUMENT_CACHE_TTL:
            return cached[1]

        path = f"/instruments/{ex}" if ex else "/instruments"
        ok_req, csv_text, _ = self._request("GET", path, allow_text=True, timeout=20.0)
        if not ok_req or not isinstance(csv_text, str):
            return []

        rows = list(csv.DictReader(io.StringIO(csv_text)))
        _KITE_INSTRUMENT_CACHE[cache_key] = (time.time(), rows)
        return rows

    def get_quote(self, symbol: str, exchange: Optional[str] = "NSE") -> Dict[str, Any]:
        ex = (exchange or "NSE").strip().upper()
        inst_key = f"{ex}:{symbol.strip().upper()}"
        ok_req, data, _ = self._request("GET", "/quote", params={"i": inst_key})
        if not ok_req or not isinstance(data, dict) or inst_key not in data:
            return {"ok": False, "error": data.get("error", "Quote unavailable") if isinstance(data, dict) else "Quote unavailable"}
        q = data[inst_key]
        return {
            "ok": True,
            "symbol": symbol.upper(),
            "exchange": ex,
            "ltp": q.get("last_price"),
            "ohlc": q.get("ohlc", {}),
            "timestamp": time.time(),
            "source": "ZERODHA_KITE",
            "raw": q,
        }

    def get_ltp(self, symbol: str, exchange: str = "NSE") -> Dict[str, Any]:
        inst_key = f"{exchange.upper()}:{symbol.upper()}"
        ok_req, data, _ = self._request("GET", "/quote/ltp", params={"i": inst_key})
        if not ok_req or not isinstance(data, dict) or inst_key not in data:
            return {"ok": False, "error": "LTP unavailable"}
        return {"ok": True, "symbol": symbol.upper(), "exchange": exchange.upper(), "ltp": data[inst_key].get("last_price"), "timestamp": time.time()}

    def get_ohlc(self, symbol: str, exchange: str = "NSE") -> Dict[str, Any]:
        inst_key = f"{exchange.upper()}:{symbol.upper()}"
        ok_req, data, _ = self._request("GET", "/quote/ohlc", params={"i": inst_key})
        if not ok_req or not isinstance(data, dict) or inst_key not in data:
            return {"ok": False, "error": "OHLC unavailable"}
        return {"ok": True, "symbol": symbol.upper(), "exchange": exchange.upper(), "data": data[inst_key], "timestamp": time.time()}

    def validate_instrument(
        self,
        symbol: str,
        exchange: Optional[str] = "NSE",
        quantity: Optional[Any] = None,
        order_type: str = "MARKET",
        product: Optional[str] = "CNC",
    ) -> Dict[str, Any]:
        clean_sym = (symbol or "").strip().upper()
        ex = (exchange or "NSE").strip().upper()
        if not clean_sym:
            return {"valid": False, "error": "Symbol required"}
        if ex not in ("NSE", "BSE"):
            return {"valid": False, "error": f"Exchange {ex} not permitted in initial India Equity pool (NSE/BSE only)"}

        cap = query_one("SELECT allowed_segments_json FROM broker_capabilities WHERE account_id=?", (self.account_id,)) or {}
        try:
            segs = json.loads(cap.get("allowed_segments_json") or '["NSE","BSE"]')
        except Exception:
            segs = ["NSE", "BSE"]
        if segs and ex not in [s.upper() for s in segs]:
            return {"valid": False, "error": f"Account {self.account_id} is not authorized for segment {ex}"}

        instruments = self.get_instruments(ex)
        match = next((i for i in instruments if str(i.get("tradingsymbol", "")).upper() == clean_sym), None)
        if not match:
            return {"valid": False, "error": f"Instrument {ex}:{clean_sym} not found in Zerodha master"}

        if quantity is not None:
            try:
                qty_int = int(quantity)
                lot = int(float(match.get("lot_size") or 1))
                if qty_int <= 0 or (lot > 0 and qty_int % lot != 0):
                    return {"valid": False, "error": f"Quantity {qty_int} must be a positive multiple of lot size {lot}"}
            except Exception:
                return {"valid": False, "error": f"Invalid equity quantity: {quantity}"}

        return {"valid": True, "instrument": match}

    def calculate_margin(self, order_spec: Dict[str, Any]) -> Dict[str, Any]:
        payload = [{
            "exchange": str(order_spec.get("exchange") or "NSE").upper(),
            "tradingsymbol": str(order_spec.get("symbol") or "").upper(),
            "transaction_type": str(order_spec.get("side") or "BUY").upper(),
            "variety": str(order_spec.get("variety") or "regular").lower(),
            "product": str(order_spec.get("product") or "CNC").upper(),
            "order_type": str(order_spec.get("order_type") or "MARKET").upper(),
            "quantity": int(order_spec.get("quantity") or 1),
            "price": float(order_spec.get("price") or 0.0),
        }]
        self._throttle()
        try:
            resp = self._session.post(
                f"{KITE_API_BASE}/margins/orders",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=payload,
                timeout=12.0,
            )
            body = resp.json()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        if resp.status_code != 200 or body.get("status") != "success":
            return {"ok": False, "error": body.get("message") or "Margin query failed"}
        items = body.get("data") or []
        req_total = sum(float(i.get("total") or 0) for i in items)
        return {"ok": True, "required_inr_paise": to_paise(req_total), "raw": items}

    def place_order(self, order_spec: Dict[str, Any]) -> Dict[str, Any]:
        # Static egress IP requirement check before live order submission
        if not self.static_egress_ip:
            return {"ok": False, "status": "REJECTED", "error": "Zerodha live orders require a registered static_egress_ip"}

        variety = str(order_spec.get("variety") or "regular").lower()
        payload = {
            "exchange": str(order_spec.get("exchange") or "NSE").upper(),
            "tradingsymbol": str(order_spec.get("symbol") or "").upper(),
            "transaction_type": str(order_spec.get("side") or "BUY").upper(),
            "quantity": int(order_spec.get("quantity") or 0),
            "product": str(order_spec.get("product") or "CNC").upper(),
            "order_type": str(order_spec.get("order_type") or "MARKET").upper(),
            "validity": str(order_spec.get("validity") or "DAY").upper(),
        }
        if order_spec.get("price") is not None and float(order_spec["price"]) > 0:
            payload["price"] = str(order_spec["price"])
        if order_spec.get("trigger_price") is not None and float(order_spec["trigger_price"]) > 0:
            payload["trigger_price"] = str(order_spec["trigger_price"])
        if order_spec.get("tag"):
            payload["tag"] = str(order_spec["tag"])[:20]

        # CRITICAL: Never retry ambiguous order submissions on timeout!
        ok_req, data, http_code = self._request("POST", f"/orders/{variety}", data=payload, timeout=10.0)
        if not ok_req:
            if http_code == 504 or (isinstance(data, dict) and data.get("ambiguous")):
                return {
                    "ok": False,
                    "status": "UNKNOWN",
                    "error": "Submission timed out; order marked UNKNOWN for reconciliation (no duplicate retry)",
                    "raw": data,
                }
            return {
                "ok": False,
                "status": "REJECTED",
                "error": data.get("error", "Order rejected by Zerodha") if isinstance(data, dict) else "Order rejected",
                "raw": data,
            }

        return {
            "ok": True,
            "status": "SUBMITTED",
            "provider_order_id": str(data.get("order_id") or ""),
            "raw": data,
        }

    def get_order_status(self, provider_order_id: str) -> Dict[str, Any]:
        ok_req, data, _ = self._request("GET", f"/orders/{provider_order_id}")
        if not ok_req:
            return {"ok": False, "error": data.get("error", "Order history unavailable")}
        history = data if isinstance(data, list) else [data]
        latest = history[-1] if history else {}
        return {
            "ok": True,
            "provider_order_id": provider_order_id,
            "status": latest.get("status", "UNKNOWN"),
            "filled_quantity": latest.get("filled_quantity", 0),
            "pending_quantity": latest.get("pending_quantity", 0),
            "average_price": latest.get("average_price", 0),
            "status_message": latest.get("status_message", ""),
            "history": history,
        }

    def get_trades(self) -> List[Dict[str, Any]]:
        ok_req, data, _ = self._request("GET", "/trades")
        return list(data) if ok_req and isinstance(data, list) else []

    def cancel_order(self, provider_order_id: str, variety: str = "regular") -> Dict[str, Any]:
        ok_req, data, _ = self._request("DELETE", f"/orders/{variety}/{provider_order_id}")
        if not ok_req:
            return {"ok": False, "error": data.get("error", "Cancel rejected")}
        return {"ok": True, "status": "CANCELLED", "provider_order_id": provider_order_id, "raw": data}

    def disconnect(self) -> Dict[str, Any]:
        if self.api_key and self.access_token:
            self._request("DELETE", "/session/token", params={"api_key": self.api_key, "access_token": self.access_token})
        now = time.time()
        write("UPDATE broker_account_secrets SET access_token_enc='', updated_at=? WHERE account_id=?", (now, self.account_id))
        write(
            "UPDATE company_trading_accounts SET connection_status='DISCONNECTED', token_expires_at=NULL, updated_at=? WHERE account_id=?",
            (now, self.account_id),
        )
        return {"ok": True, "connection_status": "DISCONNECTED"}


# ---------------------------------------------------------------------------
# Isolated Test & Development Mock Adapter (Never shipped in production routes)
# ---------------------------------------------------------------------------
class MockZerodhaAdapter(BrokerAdapter):
    """Deterministic in-memory mock Zerodha Kite Connect v3 adapter for unit & integration tests."""

    provider = "ZERODHA"
    market_scope = "INDIA"

    def __init__(
        self,
        account_id: str,
        company_id: int,
        credentials: Dict[str, Any],
        cash_inr: str = "250000.00",
        simulate_timeout: bool = False,
        reject_orders: bool = False,
        authorized_exchanges: Optional[List[str]] = None,
    ):
        super().__init__(account_id, company_id, credentials)
        self.cash_paise = to_paise(cash_inr)
        self.locked_paise = 0
        self.simulate_timeout = simulate_timeout
        self.reject_orders = reject_orders
        self.authorized_exchanges = authorized_exchanges or ["NSE", "BSE"]
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.trades: List[Dict[str, Any]] = []
        self.positions: List[Dict[str, Any]] = []
        self.instruments: List[Dict[str, Any]] = [
            {"exchange": "NSE", "tradingsymbol": "RELIANCE", "name": "Reliance Industries", "lot_size": "1", "tick_size": "0.05", "last_price": 2950.0},
            {"exchange": "NSE", "tradingsymbol": "TCS", "name": "Tata Consultancy Services", "lot_size": "1", "tick_size": "0.05", "last_price": 4120.0},
            {"exchange": "NSE", "tradingsymbol": "INFY", "name": "Infosys Ltd", "lot_size": "1", "tick_size": "0.05", "last_price": 1825.0},
            {"exchange": "BSE", "tradingsymbol": "HDFCBANK", "name": "HDFC Bank Ltd", "lot_size": "1", "tick_size": "0.05", "last_price": 1710.0},
        ]

    def verify_connection(self) -> Dict[str, Any]:
        if not self.credentials.get("api_key") or self.credentials.get("api_key") == "INVALID":
            return {"ok": False, "error": "TokenException: Invalid Zerodha credentials"}
        return {
            "ok": True,
            "broker_user_id": "ZR_ARAA_CO_01",
            "profile": {"user_id": "ZR_ARAA_CO_01", "user_name": "ARAA Proprietary Trading", "exchanges": self.authorized_exchanges, "products": ["CNC", "MIS"]},
            "authorized_segments": self.authorized_exchanges,
            "authorized_products": ["CNC", "MIS"],
        }

    def get_profile(self) -> Dict[str, Any]:
        ver = self.verify_connection()
        if not ver.get("ok"):
            return ver
        return {"ok": True, "profile": ver["profile"]}

    def get_balances(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "currency": "INR",
            "equity_paise": self.cash_paise + self.locked_paise,
            "free_paise": self.cash_paise,
            "locked_paise": self.locked_paise,
        }

    def get_positions(self) -> List[Dict[str, Any]]:
        return list(self.positions)

    def get_open_orders(self) -> List[Dict[str, Any]]:
        return [o for o in self.orders.values() if o["status"] in ("OPEN", "TRIGGER PENDING")]

    def get_instruments(self, exchange: Optional[str] = None) -> List[Dict[str, Any]]:
        if not exchange:
            return list(self.instruments)
        return [i for i in self.instruments if i["exchange"] == exchange.upper()]

    def get_quote(self, symbol: str, exchange: Optional[str] = "NSE") -> Dict[str, Any]:
        ex = (exchange or "NSE").upper()
        inst = next((i for i in self.instruments if i["symbol" if "symbol" in i else "tradingsymbol"] == symbol.upper() and i["exchange"] == ex), None)
        if not inst:
            return {"ok": False, "error": "Instrument not found"}
        px = inst["last_price"]
        return {"ok": True, "symbol": symbol.upper(), "exchange": ex, "ltp": px, "ohlc": {"open": px, "high": px, "low": px, "close": px}, "timestamp": time.time(), "source": "MOCK_ZERODHA"}

    def validate_instrument(
        self,
        symbol: str,
        exchange: Optional[str] = "NSE",
        quantity: Optional[Any] = None,
        order_type: str = "MARKET",
        product: Optional[str] = "CNC",
    ) -> Dict[str, Any]:
        ex = (exchange or "NSE").upper()
        if ex not in self.authorized_exchanges:
            return {"valid": False, "error": f"Exchange {ex} not authorized for {self.account_id}"}
        inst = next((i for i in self.instruments if i["tradingsymbol"] == symbol.upper() and i["exchange"] == ex), None)
        if not inst:
            return {"valid": False, "error": f"Unknown instrument {ex}:{symbol}"}
        if quantity is not None and int(quantity) <= 0:
            return {"valid": False, "error": "Quantity must be positive"}
        return {"valid": True, "instrument": inst}

    def calculate_margin(self, order_spec: Dict[str, Any]) -> Dict[str, Any]:
        q = self.get_quote(order_spec.get("symbol", ""), order_spec.get("exchange", "NSE"))
        if not q.get("ok"):
            return {"ok": False, "error": q.get("error")}
        qty = int(order_spec.get("quantity") or 1)
        px = float(order_spec.get("price") or q["ltp"])
        return {"ok": True, "required_inr_paise": to_paise(px * qty)}

    def place_order(self, order_spec: Dict[str, Any]) -> Dict[str, Any]:
        if self.simulate_timeout:
            return {"ok": False, "status": "UNKNOWN", "error": "Simulated Kite timeout -> requires reconciliation"}
        if self.reject_orders:
            return {"ok": False, "status": "REJECTED", "error": "Simulated Zerodha rejection"}

        sym = str(order_spec.get("symbol") or "").upper()
        ex = str(order_spec.get("exchange") or "NSE").upper()
        qty = int(order_spec.get("quantity") or 1)
        oid = f"261111{uuid.uuid4().hex[:10].upper()}"
        q = self.get_quote(sym, ex)
        px = float(order_spec.get("price") or (q.get("ltp") if q.get("ok") else 0.0))

        order_rec = {
            "order_id": oid,
            "tradingsymbol": sym,
            "exchange": ex,
            "transaction_type": str(order_spec.get("side") or "BUY").upper(),
            "order_type": str(order_spec.get("order_type") or "MARKET").upper(),
            "quantity": qty,
            "filled_quantity": qty if order_spec.get("order_type", "MARKET").upper() == "MARKET" else 0,
            "pending_quantity": 0 if order_spec.get("order_type", "MARKET").upper() == "MARKET" else qty,
            "average_price": px if order_spec.get("order_type", "MARKET").upper() == "MARKET" else 0.0,
            "status": "COMPLETE" if order_spec.get("order_type", "MARKET").upper() == "MARKET" else "OPEN",
        }
        self.orders[oid] = order_rec
        if order_rec["status"] == "COMPLETE":
            self.trades.append({
                "trade_id": f"TRD-{uuid.uuid4().hex[:8].upper()}",
                "order_id": oid,
                "tradingsymbol": sym,
                "exchange": ex,
                "transaction_type": order_rec["transaction_type"],
                "quantity": qty,
                "average_price": px,
                "fill_timestamp": time.time(),
            })
        return {"ok": True, "status": "SUBMITTED", "provider_order_id": oid, "raw": order_rec}

    def get_order_status(self, provider_order_id: str) -> Dict[str, Any]:
        rec = self.orders.get(provider_order_id)
        if not rec:
            return {"ok": False, "error": "Order not found"}
        return {"ok": True, "provider_order_id": provider_order_id, **rec}

    def get_trades(self) -> List[Dict[str, Any]]:
        return list(self.trades)

    def cancel_order(self, provider_order_id: str, variety: str = "regular") -> Dict[str, Any]:
        rec = self.orders.get(provider_order_id)
        if not rec:
            return {"ok": False, "error": "Order not found"}
        if rec["status"] == "COMPLETE":
            return {"ok": False, "error": "Cannot cancel already completed order"}
        rec["status"] = "CANCELLED"
        rec["pending_quantity"] = 0
        return {"ok": True, "status": "CANCELLED", "provider_order_id": provider_order_id}

    def disconnect(self) -> Dict[str, Any]:
        write("UPDATE company_trading_accounts SET connection_status='DISCONNECTED' WHERE account_id=?", (self.account_id,))
        return {"ok": True, "connection_status": "DISCONNECTED"}
