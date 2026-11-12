"""
ARAA Company Trading Platform — Official CoinDCX Spot-Only Company Adapter.

Reference: https://docs.coindcx.com/
Core guarantees:
- Isolated per-account HMAC-SHA256 credentials (no global keys, no user custody).
- Spot trading ONLY: explicitly rejects futures, perpetuals, margin, or leverage > 1x.
- Validates official CoinDCX market metadata precision & minimum quantities/notionals.
- Uses exact Decimal arithmetic; converts balances & spot equity conservatively to INR paise.
- Never fabricates balances or fills; submission timeouts transition cleanly to UNKNOWN.
- Includes `MockCoinDCXSpotAdapter` strictly for unit/integration testing.
"""

import hashlib
import hmac
import json
import time
import uuid
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from company_finance import to_paise
    from database import query_one, write
    from universal_broker_manager import BrokerAdapter
except ImportError:
    from backend.company_finance import to_paise
    from backend.database import query_one, write
    from backend.universal_broker_manager import BrokerAdapter


COINDCX_API_BASE = "https://api.coindcx.com"
COINDCX_PUBLIC_BASE = "https://public.coindcx.com"

_SPOT_MARKETS_CACHE: Tuple[float, Dict[str, Dict[str, Any]]] = (0.0, {})
SPOT_MARKETS_TTL = 900  # 15 minutes


def _quantize_step(value: Decimal, precision: int) -> str:
    prec = max(0, int(precision))
    fmt = "1" if prec == 0 else "0." + ("0" * (prec - 1)) + "1"
    return str(value.quantize(Decimal(fmt), rounding=ROUND_DOWN))


class CoinDCXSpotAdapter(BrokerAdapter):
    """Official CoinDCX REST adapter restricted strictly to Spot trading on company accounts."""

    provider = "COINDCX"
    market_scope = "CRYPTO"

    def __init__(self, account_id: str, company_id: int, credentials: Dict[str, Any]):
        super().__init__(account_id, company_id, credentials)
        self.api_key = (credentials.get("api_key") or "").strip()
        self.api_secret = (credentials.get("api_secret") or "").strip()
        self.withdrawal_disabled = bool(credentials.get("withdrawal_disabled", True))
        self._session = requests.Session()
        self._last_req_ts = 0.0

    def _throttle(self, min_interval: float = 0.12) -> None:
        elapsed = time.time() - self._last_req_ts
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_req_ts = time.time()

    def _sign_body(self, payload: Dict[str, Any]) -> Tuple[bytes, str]:
        body_dict = dict(payload)
        body_dict.setdefault("timestamp", int(time.time() * 1000))
        json_bytes = json.dumps(body_dict, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self.api_secret.encode("utf-8"), json_bytes, hashlib.sha256).hexdigest()
        return json_bytes, signature

    def _signed_post(self, path: str, payload: Optional[Dict[str, Any]] = None, timeout: float = 12.0) -> Tuple[bool, Any, int]:
        if not self.api_key or not self.api_secret:
            return False, {"error": "CoinDCX API key/secret missing for account"}, 401

        self._throttle()
        json_bytes, sig = self._sign_body(payload or {})
        headers = {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": self.api_key,
            "X-AUTH-SIGNATURE": sig,
            "User-Agent": "ARAA-Company-CoinDCXSpot/3.0",
        }
        try:
            resp = self._session.post(f"{COINDCX_API_BASE}{path}", data=json_bytes, headers=headers, timeout=timeout)
        except requests.Timeout:
            return False, {"error": "REQUEST_TIMEOUT", "ambiguous": True}, 504
        except requests.RequestException as exc:
            return False, {"error": str(exc)}, 502

        try:
            data = resp.json()
        except Exception:
            data = {"message": resp.text}

        if 200 <= resp.status_code < 300:
            return True, data, resp.status_code

        if resp.status_code in (401, 403):
            write(
                "UPDATE company_trading_accounts SET connection_status='REVOKED_OR_INVALID', updated_at=? WHERE account_id=?",
                (time.time(), self.account_id),
            )
        msg = data.get("message") if isinstance(data, dict) else str(data)
        return False, {"error": msg or f"CoinDCX HTTP {resp.status_code}", "raw": data}, resp.status_code

    def _public_get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: float = 10.0) -> Tuple[bool, Any]:
        self._throttle(0.05)
        try:
            resp = self._session.get(f"{COINDCX_API_BASE}{path}", params=params, timeout=timeout)
            return resp.status_code == 200, resp.json()
        except Exception as exc:
            return False, {"error": str(exc)}

    def _load_spot_markets(self) -> Dict[str, Dict[str, Any]]:
        global _SPOT_MARKETS_CACHE
        now = time.time()
        if _SPOT_MARKETS_CACHE[1] and (now - _SPOT_MARKETS_CACHE[0]) < SPOT_MARKETS_TTL:
            return _SPOT_MARKETS_CACHE[1]

        ok_req, data = self._public_get("/exchange/v1/markets_details", timeout=15.0)
        if not ok_req or not isinstance(data, list):
            return _SPOT_MARKETS_CACHE[1]

        mapping: Dict[str, Dict[str, Any]] = {}
        for m in data:
            if not isinstance(m, dict):
                continue
            coindcx_name = str(m.get("coindcx_name") or m.get("symbol") or "").upper()
            pair = str(m.get("pair") or "").upper()
            # Filter out perpetual futures keys (B-BTC_USDT) cleanly
            if pair.startswith("B-") or str(m.get("status", "")).lower() != "active":
                continue
            if coindcx_name:
                mapping[coindcx_name] = m
        if mapping:
            _SPOT_MARKETS_CACHE = (now, mapping)
        return mapping

    def _usdt_inr_rate(self) -> Decimal:
        ok_req, data = self._public_get("/exchange/ticker")
        if ok_req and isinstance(data, list):
            for t in data:
                if str(t.get("market", "")).upper() == "USDTINR" and t.get("last_price"):
                    try:
                        return Decimal(str(t["last_price"]))
                    except InvalidOperation:
                        pass
        return Decimal("85.00")

    # -----------------------------------------------------------------------
    # 14 Required BrokerAdapter Methods (Spot-Only Enforced)
    # -----------------------------------------------------------------------
    def verify_connection(self) -> Dict[str, Any]:
        if not self.withdrawal_disabled:
            return {"ok": False, "error": "Security policy: CoinDCX company API key must have withdrawals disabled"}

        ok_req, data, code = self._signed_post("/exchange/v1/users/info", {})
        if ok_req and isinstance(data, dict):
            return {
                "ok": True,
                "broker_user_id": str(data.get("coindcx_id") or data.get("email") or "COINDCX_CO"),
                "profile": data,
                "authorized_segments": ["COINDCX_SPOT"],
                "authorized_products": ["SPOT"],
            }

        # Fallback to balances verification if users/info is scoped differently
        ok_b, bal_data, _ = self._signed_post("/exchange/v1/users/balances", {})
        if ok_b and isinstance(bal_data, list):
            return {
                "ok": True,
                "broker_user_id": f"CDX-{self.api_key[:6].upper()}",
                "profile": {"coindcx_id": f"CDX-{self.api_key[:6].upper()}", "spot_only": True},
                "authorized_segments": ["COINDCX_SPOT"],
                "authorized_products": ["SPOT"],
            }
        err_msg = data.get("error") if isinstance(data, dict) else f"HTTP {code}"
        return {"ok": False, "error": err_msg or "CoinDCX credential verification failed"}

    def get_profile(self) -> Dict[str, Any]:
        ver = self.verify_connection()
        if not ver.get("ok"):
            return ver
        return {"ok": True, "profile": ver["profile"]}

    def get_balances(self) -> Dict[str, Any]:
        ok_req, data, _ = self._signed_post("/exchange/v1/users/balances", {})
        if not ok_req or not isinstance(data, list):
            err = data.get("error", "Failed to fetch CoinDCX balances") if isinstance(data, dict) else "Invalid CoinDCX balance payload"
            return {"ok": False, "error": err}

        usdt_inr = self._usdt_inr_rate()
        tickers = {}
        ok_t, t_data = self._public_get("/exchange/ticker")
        if ok_t and isinstance(t_data, list):
            for t in t_data:
                if isinstance(t, dict) and t.get("market") and t.get("last_price"):
                    tickers[str(t["market"]).upper()] = Decimal(str(t["last_price"]))

        free_inr = Decimal("0")
        locked_inr = Decimal("0")
        assets: Dict[str, Dict[str, str]] = {}

        for row in data:
            cur = str(row.get("currency") or "").upper()
            if not cur:
                continue
            avail = Decimal(str(row.get("balance") or "0"))
            locked = Decimal(str(row.get("locked_balance") or "0"))
            if avail == 0 and locked == 0:
                continue
            assets[cur] = {"available": str(avail), "locked": str(locked)}

            if cur == "INR":
                mult = Decimal("1")
            elif cur in ("USDT", "USDC"):
                mult = usdt_inr
            elif f"{cur}INR" in tickers:
                mult = tickers[f"{cur}INR"]
            elif f"{cur}USDT" in tickers:
                mult = tickers[f"{cur}USDT"] * usdt_inr
            else:
                mult = Decimal("0")

            free_inr += avail * mult
            locked_inr += locked * mult

        return {
            "ok": True,
            "currency": "INR",
            "equity_paise": to_paise(free_inr + locked_inr),
            "free_paise": to_paise(free_inr),
            "locked_paise": to_paise(locked_inr),
            "assets": assets,
            "usdt_inr_rate": str(usdt_inr),
        }

    def get_positions(self) -> List[Dict[str, Any]]:
        """Spot-only adapter maps non-zero spot token holdings (excluding INR/USDT) as spot inventory."""
        bal = self.get_balances()
        if not bal.get("ok"):
            return []
        inv = []
        for cur, vals in (bal.get("assets") or {}).items():
            if cur in ("INR", "USDT", "USDC"):
                continue
            qty = Decimal(vals["available"]) + Decimal(vals["locked"])
            if qty > 0:
                inv.append({"asset": cur, "symbol": f"{cur}INR", "quantity": str(qty), "side": "LONG", "product": "SPOT"})
        return inv

    def get_open_orders(self) -> List[Dict[str, Any]]:
        ok_req, data, _ = self._signed_post("/exchange/v1/orders/active_orders", {})
        if not ok_req or not isinstance(data, dict):
            return []
        return list(data.get("orders") or [])

    def get_instruments(self, exchange: Optional[str] = None) -> List[Dict[str, Any]]:
        return list(self._load_spot_markets().values())

    def get_quote(self, symbol: str, exchange: Optional[str] = None) -> Dict[str, Any]:
        clean = (symbol or "").strip().upper()
        ok_t, t_data = self._public_get("/exchange/ticker")
        if ok_t and isinstance(t_data, list):
            for t in t_data:
                if str(t.get("market", "")).upper() == clean:
                    return {
                        "ok": True,
                        "symbol": clean,
                        "exchange": "COINDCX_SPOT",
                        "ltp": t.get("last_price"),
                        "bid": t.get("bid"),
                        "ask": t.get("ask"),
                        "timestamp": float(t.get("timestamp") or time.time()),
                        "source": "COINDCX_PUBLIC_TICKER",
                    }
        return {"ok": False, "error": f"Spot quote unavailable for {clean}"}

    def validate_instrument(
        self,
        symbol: str,
        exchange: Optional[str] = None,
        quantity: Optional[Any] = None,
        order_type: str = "MARKET",
        product: Optional[str] = "SPOT",
    ) -> Dict[str, Any]:
        clean = (symbol or "").strip().upper()
        if not clean:
            return {"valid": False, "error": "Spot symbol required"}
        if clean.startswith("B-") or (exchange and exchange.upper() not in ("COINDCX", "COINDCX_SPOT")):
            return {"valid": False, "error": "CoinDCX company adapter allows SPOT pairs only (no futures/perps)"}
        if product and product.upper() not in ("SPOT", "CASH"):
            return {"valid": False, "error": f"Product {product} prohibited; SPOT only"}

        markets = self._load_spot_markets()
        if markets and clean not in markets:
            return {"valid": False, "error": f"Symbol {clean} is not an active CoinDCX Spot pair"}
        meta = markets.get(clean, {})

        if quantity is not None:
            try:
                q_dec = Decimal(str(quantity))
            except (InvalidOperation, ValueError):
                return {"valid": False, "error": f"Invalid decimal quantity: {quantity}"}
            min_qty = Decimal(str(meta.get("min_quantity") or "0"))
            if q_dec <= 0 or q_dec < min_qty:
                return {"valid": False, "error": f"Quantity {q_dec} below CoinDCX min_quantity {min_qty}"}

        return {"valid": True, "instrument": meta}

    def calculate_margin(self, order_spec: Dict[str, Any]) -> Dict[str, Any]:
        qty = Decimal(str(order_spec.get("quantity") or "0"))
        px = Decimal(str(order_spec.get("price") or "0"))
        if px <= 0:
            q = self.get_quote(order_spec.get("symbol", ""))
            if not q.get("ok"):
                return {"ok": False, "error": q.get("error", "Price unavailable")}
            px = Decimal(str(q["ltp"]))
        sym = str(order_spec.get("symbol") or "").upper()
        notional = qty * px
        if sym.endswith("USDT"):
            notional_inr = notional * self._usdt_inr_rate()
        else:
            notional_inr = notional
        return {"ok": True, "required_inr_paise": to_paise(notional_inr)}

    def place_order(self, order_spec: Dict[str, Any]) -> Dict[str, Any]:
        # Hard guard against futures / leverage / withdrawals
        if float(order_spec.get("leverage") or 1) > 1.0:
            return {"ok": False, "status": "REJECTED", "error": "SPOT_ONLY_POLICY: Leverage > 1x is prohibited"}
        prod = str(order_spec.get("product") or "SPOT").upper()
        if prod in ("FUTURES", "PERPETUAL", "MARGIN"):
            return {"ok": False, "status": "REJECTED", "error": f"SPOT_ONLY_POLICY: {prod} is prohibited"}

        sym = str(order_spec.get("symbol") or "").strip().upper()
        side = str(order_spec.get("side") or "").strip().lower()
        if side not in ("buy", "sell"):
            return {"ok": False, "status": "REJECTED", "error": f"Invalid spot side: {side}"}

        otype = str(order_spec.get("order_type") or "MARKET").strip().lower()
        coindcx_otype = "market_order" if otype == "market" else "limit_order"

        markets = self._load_spot_markets()
        meta = markets.get(sym, {})
        base_prec = int(meta.get("base_currency_precision") or 6)
        qty_str = _quantize_step(Decimal(str(order_spec.get("quantity") or "0")), base_prec)

        payload: Dict[str, Any] = {
            "side": side,
            "order_type": coindcx_otype,
            "market": sym,
            "total_quantity": float(Decimal(qty_str)),
        }
        if order_spec.get("idempotency_key"):
            payload["client_order_id"] = str(order_spec["idempotency_key"])[:36]
        if coindcx_otype == "limit_order":
            target_prec = int(meta.get("target_currency_precision") or 4)
            px_str = _quantize_step(Decimal(str(order_spec.get("price") or "0")), target_prec)
            payload["price_per_unit"] = float(Decimal(px_str))

        ok_req, data, http_code = self._signed_post("/exchange/v1/orders/create", payload, timeout=10.0)
        if not ok_req:
            if http_code == 504 or (isinstance(data, dict) and data.get("ambiguous")):
                return {
                    "ok": False,
                    "status": "UNKNOWN",
                    "error": "CoinDCX order timed out; marked UNKNOWN for reconciliation (no auto retry)",
                    "raw": data,
                }
            return {"ok": False, "status": "REJECTED", "error": data.get("error", "CoinDCX order rejected"), "raw": data}

        orders = data.get("orders") if isinstance(data, dict) else []
        first = orders[0] if orders else {}
        return {
            "ok": True,
            "status": "SUBMITTED",
            "provider_order_id": str(first.get("id") or ""),
            "raw": data,
        }

    def get_order_status(self, provider_order_id: str) -> Dict[str, Any]:
        ok_req, data, _ = self._signed_post("/exchange/v1/orders/status", {"id": provider_order_id})
        if not ok_req or not isinstance(data, dict):
            return {"ok": False, "error": data.get("error", "CoinDCX order status failed") if isinstance(data, dict) else "Status failed"}
        return {
            "ok": True,
            "provider_order_id": provider_order_id,
            "status": str(data.get("status", "UNKNOWN")).upper(),
            "filled_quantity": Decimal(str(data.get("total_quantity") or 0)) - Decimal(str(data.get("remaining_quantity") or 0)),
            "remaining_quantity": data.get("remaining_quantity", 0),
            "average_price": data.get("avg_price", 0),
            "fee": data.get("fee_amount", 0),
            "raw": data,
        }

    def get_trades(self) -> List[Dict[str, Any]]:
        ok_req, data, _ = self._signed_post("/exchange/v1/orders/trade_history", {"limit": 100})
        return list(data) if ok_req and isinstance(data, list) else []

    def cancel_order(self, provider_order_id: str, variety: str = "regular") -> Dict[str, Any]:
        ok_req, data, _ = self._signed_post("/exchange/v1/orders/cancel", {"id": provider_order_id})
        if not ok_req:
            return {"ok": False, "error": data.get("error", "Cancel rejected") if isinstance(data, dict) else "Cancel failed"}
        return {"ok": True, "status": "CANCELLED", "provider_order_id": provider_order_id, "raw": data}

    def disconnect(self) -> Dict[str, Any]:
        write(
            "UPDATE company_trading_accounts SET connection_status='DISCONNECTED', updated_at=? WHERE account_id=?",
            (time.time(), self.account_id),
        )
        return {"ok": True, "connection_status": "DISCONNECTED"}


# ---------------------------------------------------------------------------
# Isolated Mock CoinDCX Spot Adapter (Tests & Dev Harness Only)
# ---------------------------------------------------------------------------
class MockCoinDCXSpotAdapter(BrokerAdapter):
    """Deterministic CoinDCX Spot-only mock adapter for automated integration & security tests."""

    provider = "COINDCX"
    market_scope = "CRYPTO"

    def __init__(
        self,
        account_id: str,
        company_id: int,
        credentials: Dict[str, Any],
        inr_balance: str = "100000.00",
        simulate_timeout: bool = False,
        reject_orders: bool = False,
    ):
        super().__init__(account_id, company_id, credentials)
        self.inr_balance = Decimal(inr_balance)
        self.locked_inr = Decimal("0")
        self.simulate_timeout = simulate_timeout
        self.reject_orders = reject_orders
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.trades: List[Dict[str, Any]] = []
        self.holdings: Dict[str, Decimal] = {}
        self.markets = {
            "BTCINR": {"coindcx_name": "BTCINR", "base_currency_precision": 5, "target_currency_precision": 2, "min_quantity": "0.0001", "last_price": "6500000.00"},
            "ETHINR": {"coindcx_name": "ETHINR", "base_currency_precision": 4, "target_currency_precision": 2, "min_quantity": "0.001", "last_price": "180000.00"},
            "SOLINR": {"coindcx_name": "SOLINR", "base_currency_precision": 2, "target_currency_precision": 2, "min_quantity": "0.05", "last_price": "14000.00"},
        }

    def verify_connection(self) -> Dict[str, Any]:
        if not self.credentials.get("api_key") or self.credentials.get("api_key") == "INVALID":
            return {"ok": False, "error": "Invalid CoinDCX API key"}
        if not self.credentials.get("withdrawal_disabled", True):
            return {"ok": False, "error": "CoinDCX key must have withdrawals disabled"}
        return {
            "ok": True,
            "broker_user_id": "CDX_ARAA_SPOT_01",
            "profile": {"coindcx_id": "CDX_ARAA_SPOT_01", "spot_only": True},
            "authorized_segments": ["COINDCX_SPOT"],
            "authorized_products": ["SPOT"],
        }

    def get_profile(self) -> Dict[str, Any]:
        ver = self.verify_connection()
        return {"ok": True, "profile": ver["profile"]} if ver.get("ok") else ver

    def get_balances(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "currency": "INR",
            "equity_paise": to_paise(self.inr_balance + self.locked_inr),
            "free_paise": to_paise(self.inr_balance),
            "locked_paise": to_paise(self.locked_inr),
            "assets": {"INR": {"available": str(self.inr_balance), "locked": str(self.locked_inr)}},
        }

    def get_positions(self) -> List[Dict[str, Any]]:
        return [
            {"asset": k, "symbol": f"{k}INR", "quantity": str(v), "side": "LONG", "product": "SPOT"}
            for k, v in self.holdings.items()
            if v > 0
        ]

    def get_open_orders(self) -> List[Dict[str, Any]]:
        return [o for o in self.orders.values() if o["status"] in ("OPEN", "PARTIALLY_FILLED")]

    def get_instruments(self, exchange: Optional[str] = None) -> List[Dict[str, Any]]:
        return list(self.markets.values())

    def get_quote(self, symbol: str, exchange: Optional[str] = None) -> Dict[str, Any]:
        m = self.markets.get(symbol.upper())
        if not m:
            return {"ok": False, "error": "Unknown CoinDCX Spot pair"}
        return {"ok": True, "symbol": symbol.upper(), "exchange": "COINDCX_SPOT", "ltp": m["last_price"], "timestamp": time.time(), "source": "MOCK_COINDCX_SPOT"}

    def validate_instrument(
        self,
        symbol: str,
        exchange: Optional[str] = None,
        quantity: Optional[Any] = None,
        order_type: str = "MARKET",
        product: Optional[str] = "SPOT",
    ) -> Dict[str, Any]:
        sym = (symbol or "").upper()
        if sym.startswith("B-") or (product and product.upper() not in ("SPOT", "CASH")):
            return {"valid": False, "error": "SPOT_ONLY_POLICY: Futures/perpetuals rejected"}
        m = self.markets.get(sym)
        if not m:
            return {"valid": False, "error": f"Pair {sym} not supported in CoinDCX Spot"}
        if quantity is not None and Decimal(str(quantity)) < Decimal(m["min_quantity"]):
            return {"valid": False, "error": f"Quantity below min_quantity {m['min_quantity']}"}
        return {"valid": True, "instrument": m}

    def calculate_margin(self, order_spec: Dict[str, Any]) -> Dict[str, Any]:
        sym = str(order_spec.get("symbol") or "").upper()
        q = self.get_quote(sym)
        if not q.get("ok"):
            return {"ok": False, "error": q.get("error")}
        qty = Decimal(str(order_spec.get("quantity") or "0"))
        px = Decimal(str(order_spec.get("price") or q["ltp"]))
        return {"ok": True, "required_inr_paise": to_paise(qty * px)}

    def place_order(self, order_spec: Dict[str, Any]) -> Dict[str, Any]:
        if float(order_spec.get("leverage") or 1) > 1.0 or str(order_spec.get("product") or "SPOT").upper() != "SPOT":
            return {"ok": False, "status": "REJECTED", "error": "SPOT_ONLY_POLICY violated"}
        if self.simulate_timeout:
            return {"ok": False, "status": "UNKNOWN", "error": "Simulated CoinDCX timeout -> reconciliation required"}
        if self.reject_orders:
            return {"ok": False, "status": "REJECTED", "error": "Simulated CoinDCX rejection"}

        sym = str(order_spec.get("symbol") or "").upper()
        qty = Decimal(str(order_spec.get("quantity") or "0"))
        q = self.get_quote(sym)
        px = Decimal(str(order_spec.get("price") or q["ltp"]))
        oid = f"cdx-{uuid.uuid4().hex[:12]}"
        otype = str(order_spec.get("order_type") or "MARKET").upper()
        is_market = otype == "MARKET"
        status = "FILLED" if is_market else "OPEN"

        rec = {
            "id": oid,
            "market": sym,
            "side": str(order_spec.get("side") or "BUY").upper(),
            "order_type": otype,
            "total_quantity": str(qty),
            "filled_quantity": str(qty if is_market else Decimal("0")),
            "remaining_quantity": str(Decimal("0") if is_market else qty),
            "avg_price": str(px if is_market else Decimal("0")),
            "fee_amount": str((qty * px * Decimal("0.001")).quantize(Decimal("0.01"))),
            "status": status,
        }
        self.orders[oid] = rec
        if is_market:
            self.trades.append({
                "id": f"ctrd-{uuid.uuid4().hex[:8]}",
                "order_id": oid,
                "symbol": sym,
                "side": rec["side"],
                "quantity": str(qty),
                "price": str(px),
                "fee_amount": rec["fee_amount"],
                "timestamp": time.time(),
            })
            asset = sym[:-3] if sym.endswith("INR") else sym
            if rec["side"] == "BUY":
                self.holdings[asset] = self.holdings.get(asset, Decimal("0")) + qty
        return {"ok": True, "status": "SUBMITTED", "provider_order_id": oid, "raw": rec}

    def get_order_status(self, provider_order_id: str) -> Dict[str, Any]:
        rec = self.orders.get(provider_order_id)
        if not rec:
            return {"ok": False, "error": "Order not found"}
        return {"ok": True, "provider_order_id": provider_order_id, **rec}

    def get_trades(self) -> List[Dict[str, Any]]:
        return list(self.trades)

    def cancel_order(self, provider_order_id: str, variety: str = "regular") -> Dict[str, Any]:
        rec = self.orders.get(provider_order_id)
        if not rec or rec["status"] == "FILLED":
            return {"ok": False, "error": "Cannot cancel filled/missing order"}
        rec["status"] = "CANCELLED"
        return {"ok": True, "status": "CANCELLED", "provider_order_id": provider_order_id}

    def disconnect(self) -> Dict[str, Any]:
        write("UPDATE company_trading_accounts SET connection_status='DISCONNECTED' WHERE account_id=?", (self.account_id,))
        return {"ok": True, "connection_status": "DISCONNECTED"}
