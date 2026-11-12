"""Every country stock market TradingView lists, discovered from its public scanner.

https://in.tradingview.com/markets/ organises world equities by country, and each country page is
one scanner section (italy, japan, korea, ...). Posting the canonical scan body with
    filter: [{left: "country", operation: "equal", right: "Italy"}]
answers that country's listed companies with a real last price, day change, day range, volume,
name and market cap - no key, no scraping of HTML.

Two things the API does not give us and this module supplies:
  * we rank by market cap ourselves instead of trusting the order the scan answers in (big, liquid
    names are the ones worth trading, and the bot can only move on a quote it can actually fill);
  * the same company is listed on more than one exchange (RELIANCE on NSE: and BSE:, Toyota on
    TSE: and NAG:), so we keep one row per company, preferring the country's home exchange.

Verified against the live API: 36 sections answer, 404 for southafrica/saudi/unitedarab.
"""
import json, re, time, urllib.request

SCAN_URL = "https://scanner.tradingview.com/%s/scan"
DISCOVER_FIELDS = ["close", "change", "change_abs", "high", "low", "open", "volume",
                   "name", "description", "market_cap_basic", "country"]

# label, scanner section, issuer-country name as the scanner spells it, settlement currency,
# home exchanges we prefer when a company is dual-listed.
#
# The exchange codes are what the live scanner actually answers with, read off a full crawl of all
# 36 sections. Several differ from the prefix shown in a TradingView chart URL, which is why both
# spellings are listed: France and the Netherlands come back as EURONEXT:, Sweden as OMXSTO:,
# Denmark OMXCOP:, Poland GPW:, New Zealand NZX:, Malaysia MYX:, Bangladesh DSEBD:, Mexico BMV:,
# Argentina BCBA:, China SSE:/SZSE:, Canada TSX: (mirrored on NEO:), Germany XETR: (mirrored on
# HAN/MUN/BER/DTX and the Luxembourg LS/LSX lines), Switzerland SIX: (mirrored on BX).
COUNTRY_MARKETS = [
    ("United States", "america", "United States", "USD", ["NASDAQ", "NYSE"]),
    ("United Kingdom", "uk", "United Kingdom", "GBP", ["LSE", "LSIN"]),
    ("Germany", "germany", "Germany", "EUR", ["XETR", "FRA", "BER", "EBS"]),
    ("France", "france", "France", "EUR", ["EURONEXT", "PA"]),
    ("Italy", "italy", "Italy", "EUR", ["MIL"]),
    ("Spain", "spain", "Spain", "EUR", ["BME", "BMEX"]),
    ("Netherlands", "netherlands", "Netherlands", "EUR", ["EURONEXT", "AMS"]),
    ("Switzerland", "switzerland", "Switzerland", "CHF", ["SIX"]),
    ("Sweden", "sweden", "Sweden", "SEK", ["OMXSTO", "STO"]),
    ("Norway", "norway", "Norway", "NOK", ["OSL"]),
    ("Denmark", "denmark", "Denmark", "DKK", ["OMXCOP", "CSE"]),
    ("Poland", "poland", "Poland", "PLN", ["GPW", "WSE"]),
    ("Canada", "canada", "Canada", "CAD", ["TSX", "TOR"]),
    ("Australia", "australia", "Australia", "AUD", ["ASX"]),
    ("New Zealand", "newzealand", "New Zealand", "NZD", ["NZX"]),
    ("India", "india", "India", "INR", ["NSE", "BSE"]),
    ("Japan", "japan", "Japan", "JPY", ["TSE"]),
    ("China", "china", "China", "CNY", ["SSE", "SZSE"]),
    ("Hong Kong", "hongkong", "Hong Kong", "HKD", ["HKEX"]),
    ("South Korea", "korea", "South Korea", "KRW", ["KRX"]),
    ("Taiwan", "taiwan", "Taiwan", "TWD", ["TWSE"]),
    ("Singapore", "singapore", "Singapore", "SGD", ["SGX"]),
    ("Malaysia", "malaysia", "Malaysia", "MYR", ["MYX"]),
    ("Indonesia", "indonesia", "Indonesia", "IDR", ["IDX"]),
    ("Thailand", "thailand", "Thailand", "THB", ["SET"]),
    ("Vietnam", "vietnam", "Vietnam", "VND", ["HOSE"]),
    ("Philippines", "philippines", "Philippines", "PHP", ["PSE"]),
    ("Bangladesh", "bangladesh", "Bangladesh", "BDT", ["DSEBD"]),
    ("Pakistan", "pakistan", "Pakistan", "PKR", ["PSX", "KAR"]),
    ("Turkey", "turkey", "Turkey", "TRY", ["BIST"]),
    ("Brazil", "brazil", "Brazil", "BRL", ["BMFBOVESPA"]),
    ("Mexico", "mexico", "Mexico", "MXN", ["BMV"]),
    ("Argentina", "argentina", "Argentina", "ARS", ["BCBA"]),
    ("Chile", "chile", "Chile", "CLP", ["BCS"]),
    ("Israel", "israel", "Israel", "ILS", ["TASE"]),
    ("Egypt", "egypt", "Egypt", "EGP", ["EGX"]),
]

COUNTRIES = [c[0] for c in COUNTRY_MARKETS]
BY_COUNTRY = {c[0]: c for c in COUNTRY_MARKETS}

# Ranking the biggest tickers by market cap also returns the paper a company lists alongside its
# shares: Alphabet's depositary shares, ARM's London ADR, ABN AMRO's depositary receipts. Thailand
# answers with an NVDR line for every stock (the non-voting depository note foreigners trade), and
# Switzerland stamps a TEMP line on a name whose dividend has just gone ex. Those are the same
# company at the same price, so the equity itself is what we trade.
DERIVATIVE = re.compile(r"depositary|receipt|\badr\b|sponsored|\bpfd\b|\bpref|preferred|warrant|"
                        r"unsp|\bnvdr\b|\btemp\b", re.I)


BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/"
}

def _post(section, body, timeout=25):
    req = urllib.request.Request(SCAN_URL % section, data=json.dumps(body).encode(),
                                 headers=BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _discover_body(country, rows):
    # range has to be an array and the query options have to say "stock" - any other shape the
    # scanner rejects with 400 rather than a helpful message. The window is wider than the number
    # we keep because a country's biggest names each occupy several lines: SAP SE appears on XETR,
    # HAN, MUN, LS, HAM and LSX inside the same 96 rows, and every Thai stock comes with an NVDR.
    return {"columns": DISCOVER_FIELDS,
            "filter": [{"left": "country", "operation": "equal", "right": country}],
            "ignore_unknown_fields": False,
            "options": {"lang": "en", "sizes": ["1", "3", "5"]},
            "range": [0, rows],
            "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
            "symbols": {"query": {"options": [{"type": "stock", "include": True}],
                                   "limit": [0, rows]}, "tickers": []}}


def _exchange_of(code):
    return code.split(":")[0] if ":" in code else ""


def _normalise(company):
    """Company identity for dedupe: SAP SE on Xetra and on Luxembourg Line are one company."""
    return re.sub(r"[^a-z0-9]", "", (company or "").lower())


def _scan_country(label, section, issuer, currency, prefs, rows, limit, timeout):
    data = _post(section, _discover_body(issuer, rows), timeout=timeout)
    found = []
    for r in data.get("data") or []:
        d = dict(zip(DISCOVER_FIELDS, r.get("d") or []))
        price = float(d.get("close") or 0)
        company = d.get("description") or d.get("name") or ""
        if price <= 0 or not d.get("name") or DERIVATIVE.search(company):
            continue
        found.append({"symbol": r.get("s"), "company": company,
                      "ticker": d["name"], "price": price,
                      "market_cap": float(d.get("market_cap_basic") or 0),
                      "country": label, "currency": currency,
                      "exchange": _exchange_of(r.get("s") or "")})
    found.sort(key=lambda x: (-x["market_cap"], 0 if x["exchange"] in prefs else 1))
    picked, seen_ticker, seen_company = [], set(), set()
    for row in found:
        tk, ck = row["ticker"].upper(), _normalise(row["company"])
        if tk in seen_ticker or ck in seen_company:
            continue
        seen_ticker.add(tk)
        seen_company.add(ck)
        row["section"] = section
        picked.append(row)
        if len(picked) >= limit:
            break
    return picked


def discover_country(label, section, issuer, currency, prefs, limit=12, timeout=25):
    """One country's biggest listed companies, one row per company.

    The scanner lists the same company on several venues (Reliance on NSE: and BSE:, SAP SE also
    as a Luxembourg line, Shopify also on the NEO exchange), so dedupe runs on both the ticker and
    the company name. Sorting puts a country's home exchange first on an equal market cap, so the
    row that survives is the listing people actually trade.

    A country whose window dedupes down to fewer than `limit` names is asked again with a wider
    slice: 96 rows are enough for 34 of the 36 markets, but Germany answers with six lines per
    company and Canada mirrors every TSX listing on NEO, so both need 240 to reach twelve.
    """
    picked = []
    for factor in (8, 20, 50):
        picked = _scan_country(label, section, issuer, currency, prefs,
                               limit * factor, limit, timeout)
        if len(picked) >= limit:
            break
    return picked


def discover(limit_per_country=12, sleep=0.25):
    """The whole world universe: [{symbol, company, country, currency, price, ...}].

    If rate-limited, safely pauses without noisy console error spam.
    """
    out = []
    for label, section, issuer, currency, prefs in COUNTRY_MARKETS:
        try:
            out.extend(discover_country(label, section, issuer, currency, prefs,
                                        limit=limit_per_country))
        except Exception as exc:
            err = str(exc)
            if "429" in err:
                print("[WORLD] Scanner rate-limited on cloud IP (429) — relying on pre-seeded world universe.", flush=True)
                break
        if sleep:
            time.sleep(sleep)
    return out


def sections_of(rows):
    """{section: [tv codes]} - what each country's quote sweep asks for."""
    by = {}
    for r in rows:
        by.setdefault(r["section"], []).append(r["symbol"])
    return by


if __name__ == "__main__":
    t0 = time.time()
    found = discover()
    print("%d instruments across %d countries in %.1fs"
          % (len(found), len({f['country'] for f in found}), time.time() - t0))
    print(json.dumps(found[:2], indent=1))
