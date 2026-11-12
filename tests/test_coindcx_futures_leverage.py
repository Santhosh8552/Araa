"""Offline tests for CoinDCX futures leverage path (no network: _request is mocked)."""
import os, sys, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import coindcx_gateway as g

CALLS = []

def fake_request(endpoint, method="GET", body=None, api_key=None, api_secret=None, **kw):
    CALLS.append((endpoint, method, body))
    if "data/instrument?" in endpoint:
        return True, {"instrument": {"max_leverage_long": 50, "max_leverage_short": 25,
                                      "quantity_increment": 0.001, "min_quantity": 0.001}}
    if endpoint.endswith("/positions"):
        return True, []
    if endpoint.endswith("update_leverage"):
        return True, {"ok": 1}
    if endpoint.endswith("orders/create"):
        return True, [{"id": "abc", "avg_price": "100"}]
    return False, {"code": 404, "message": "x"}

g._request = fake_request
g.log_audit_event = lambda *a, **k: None
g.time.sleep = lambda *_: None

def adapter():
    g._FUT_INSTRUMENT_CACHE.clear(); CALLS.clear()
    return g.CoinDCXFuturesAdapter("k", "s", user_id=1)

def test_pair_mapping():
    a = adapter()
    assert a.to_futures_pair("BTCINR") == "B-BTC_USDT"
    assert a.to_futures_pair("eth/usdt") == "B-ETH_USDT"
    assert a.to_futures_pair("B-SOL_USDT") == "B-SOL_USDT"

def test_500x_clamped_to_exchange_max():
    a = adapter()
    assert a.resolve_leverage("BTCUSDT", 500, "buy") == 50
    assert a.resolve_leverage("BTCUSDT", 500, "sell") == 25
    assert a.resolve_leverage("BTCUSDT", 10, "buy") == 10

def test_order_payload_and_qty_step():
    a = adapter()
    ok, res = a.place_futures_order("BTCINR", "buy", 0.12345, leverage=500)
    assert ok and res["leverage"] == 50
    order = [c for c in CALLS if c[0].endswith("orders/create")][0][2]["order"]
    assert order["pair"] == "B-BTC_USDT" and order["leverage"] == 50
    assert order["total_quantity"] == 0.123 and order["side"] == "buy"
    assert any(c[0].endswith("update_leverage") for c in CALLS)

def test_transient_error_is_retried():
    a = adapter(); n = {"i": 0}
    def flaky(endpoint, **kw):
        n["i"] += 1
        return (True, []) if n["i"] == 3 else (False, {"code": 503, "message": "down"})
    g._request = flaky
    ok, _ = a._call("/exchange/v1/derivatives/futures/positions", attempts=4)
    g._request = fake_request
    assert ok and n["i"] == 3

def test_client_error_not_retried():
    a = adapter(); n = {"i": 0}
    def bad(endpoint, **kw):
        n["i"] += 1
        return False, {"code": 401, "message": "bad key"}
    g._request = bad
    ok, _ = a._call("/x", attempts=4)
    g._request = fake_request
    assert not ok and n["i"] == 1

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
