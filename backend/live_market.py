"""Live quotes and OHLC candles for FX, metals, indices, energies and crypto.

Market data by biquote (https://biquote.io) — free, keyless, indicative prices.
Results are cached briefly so many terminal users share one upstream request.
"""

import json
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime

BASE = "https://biquote.io/api"
UA = {"User-Agent": "Mozilla/5.0 (AraaVision terminal)", "Accept": "application/json"}

ALIASES = {
    "NAS100": "USTEC", "NDX": "USTEC", "US100": "USTEC",
    "SPX500": "US500", "SPX": "US500",
    "DJI": "US30", "DOW": "US30",
    "GOLD": "XAUUSD", "SILVER": "XAGUSD",
    "WTI": "USOIL", "OIL": "USOIL", "BRENT": "UKOIL",
    "BTCUSD": "BTCUSD", "ETHUSD": "ETHUSD",
}

NATIVE_TF = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d"}
# timeframes the provider lacks are built from a smaller native one
DERIVED_TF = {"3m": ("1m", 3), "2h": ("1h", 2), "1w": ("1d", 7)}
TF_SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
              "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400, "1w": 604800}
MAX_BARS = 300

_lock = threading.Lock()
_candle_cache = {}
_quote_cache = {}


def norm_tf(tf):
    t = str(tf or "15m").strip()
    low = t.lower()
    if t in ("1MN", "1mn", "1mo"):
        return "1w"  # monthly bars are not available; weekly is the closest
    if low in ("1d", "d", "1day"):
        return "1d"
    if low in ("1w", "w", "1wk"):
        return "1w"
    return low if low in TF_SECONDS else "15m"


def provider_symbol(symbol):
    s = str(symbol or "").upper().replace("/", "").replace("-", "").replace("_", "")
    return ALIASES.get(s, s)


def _get(url, timeout=6.0):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _ts(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _fetch_native(psym, tf, limit):
    url = f"{BASE}/{urllib.parse.quote(psym)}/ohlc?interval={tf}&limit={min(int(limit), MAX_BARS)}"
    d = _get(url)
    bars = d.get("bars") if isinstance(d, dict) else None
    if not bars:
        return []
    out = []
    for b in bars:
        try:
            o, h, l, c = float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if c <= 0:
            continue
        out.append({"t": _ts(b["openTime"]), "o": o, "h": h, "l": l, "c": c,
                    "v": float(b.get("volume") or 0) or float(b.get("tickVolume") or 0)})
    out.sort(key=lambda k: k["t"])
    return out


WEEK_ANCHOR = 4 * 86400  # 1970-01-05, a Monday


def _aggregate(bars, seconds):
    anchor = WEEK_ANCHOR if seconds == TF_SECONDS["1w"] else 0
    out = []
    for b in bars:
        bucket = b["t"] - ((b["t"] - anchor) % seconds)
        if out and out[-1]["t"] == bucket:
            k = out[-1]
            k["h"] = max(k["h"], b["h"]); k["l"] = min(k["l"], b["l"])
            k["c"] = b["c"]; k["v"] += b["v"]
        else:
            out.append({"t": bucket, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]})
    return out


def candles(symbol, tf="15m", limit=140):
    """Oldest-first OHLCV list ([] when the provider has no data for the symbol)."""
    tf = norm_tf(tf)
    psym = provider_symbol(symbol)
    limit = max(10, min(int(limit or 140), MAX_BARS))
    key = (psym, tf)
    ttl = 3.0 if TF_SECONDS[tf] <= 300 else 10.0
    now = time.time()
    with _lock:
        hit = _candle_cache.get(key)
    if hit and now - hit[0] < ttl and hit[2] >= limit:
        return [dict(k) for k in hit[1][-limit:]]
    try:
        if tf in NATIVE_TF:
            bars = _fetch_native(psym, NATIVE_TF[tf], limit)
        else:
            base, mult = DERIVED_TF[tf]
            bars = _aggregate(_fetch_native(psym, base, min(MAX_BARS, limit * mult)), TF_SECONDS[tf])
    except Exception:
        bars = hit[1] if hit else []
    if bars:
        with _lock:
            _candle_cache[key] = (now, bars, limit)
            if len(_candle_cache) > 800:
                _candle_cache.clear()
    return [dict(k) for k in bars[-limit:]]


def quotes(symbols):
    """{requested_symbol: quote} for every symbol the provider knows."""
    req = [str(s).upper() for s in symbols if s][:60]
    if not req:
        return {}
    psyms = {s: provider_symbol(s) for s in req}
    now = time.time()
    out, missing = {}, []
    with _lock:
        for s, p in psyms.items():
            hit = _quote_cache.get(p)
            if hit and now - hit[0] < 1.5:
                out[s] = dict(hit[1], symbol=s)
            else:
                missing.append(p)
    if missing:
        qs = "&".join("symbols=" + urllib.parse.quote(p) for p in sorted(set(missing)))
        try:
            raw = _get(f"{BASE}/latest?{qs}", timeout=5.0) or {}
        except Exception:
            raw = {}
        fresh = {}
        for p, q in raw.items():
            try:
                bid, ask = float(q.get("bid") or 0), float(q.get("ask") or 0)
                mid = float(q.get("mid") or 0) or (bid + ask) / 2 or float(q.get("last") or 0)
            except (TypeError, ValueError):
                continue
            if mid <= 0:
                continue
            fresh[p] = {
                "price": mid, "bid": bid or mid, "ask": ask or mid,
                "spread": float(q.get("spread") or max(ask - bid, 0)),
                "change_pct": round(float(q.get("dayDiffPercent") or 0), 3),
                "high": float(q.get("high") or 0) or mid, "low": float(q.get("low") or 0) or mid,
                "name": q.get("description") or p, "market_state": q.get("marketState") or "open",
                "stale": bool(q.get("stale")), "updated": q.get("timestamp"),
                "source": "biquote",
            }
        with _lock:
            for p, q in fresh.items():
                _quote_cache[p] = (now, q)
        for s, p in psyms.items():
            if s not in out and p in fresh:
                out[s] = dict(fresh[p], symbol=s)
    return out


def quote(symbol):
    return quotes([symbol]).get(str(symbol).upper())
