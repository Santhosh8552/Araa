# TRADE.PRO — paper trading terminal + admin panel

A trading terminal that reads **real live market prices** and trades **fake money**.
Nothing here touches a broker, a bank, or a payment gateway.

## Run it

Needs `node` and `python3` on the machine (macOS: `brew install node python`).

```bash
npm run setup       # installs Flask + flask-cors (auto-creates .venv if pip is locked)
npm start           # Node is just the launcher; the app itself is Python + SQLite
```

If you got this as a zip: unzip it, `cd Trade-Pro-Admin-Direct-Open`, then run the two
commands above. The zip carries **no database file on purpose** — the first launch creates one and
seeds the demo accounts, deposits, withdrawals, brokerage ledger and closed trades into it, so the
panel is never empty and no login session or balance from someone else's machine travels with it.

Then open:

| What | Where |
| --- | --- |
| User app | http://localhost:7777 |
| Admin panel | http://localhost:7779 — opens straight away, no login |
| JSON API | http://127.0.0.1:5050 |

Demo login: `user@gmail.com` / `demo1234`
Goal-story login: `goal.demo@gmail.com` / `goal1234` (₹1,000 in, ₹1,500 target)

## What is real and what is not

| Real | Simulated |
| --- | --- |
| Every price, candle, RSI/MA, volume — scraped from Binance, TradingView and CNBC quote endpoints for 976 symbols (crypto, forex, indices, metals, US and Indian stocks, plus the 12 biggest listed companies of each of 36 countries) | Your ₹ balance, deposits, UPI/card payments, withdrawals, positions and P&L |
| The bot's decisions — it only acts on scraped live quotes and refuses to trade a symbol whose feed has gone dark | Order fills — no exchange is contacted, so there is no slippage, no rejection and no settlement |
| 30% brokerage maths on the admin panel | The admin panel itself is a demo with no authentication — never expose it to the internet |

## Charts

Every symbol has a **FULL LIVE CHART ON TRADINGVIEW ↗** pill above the chart. It is
view-only: it opens TradingView's own chart page for that symbol in a new tab and never
sends anything back into this app, so balances, positions and fills are untouched.
All 976 symbols resolve a link.

The embedded chart inside the app is a different story — the free TradingView embed widget
is not entitled for Indian exchange data, so `NSE:` and `BSE:` symbols (11 companies,
Nifty, Bank Nifty, Sensex) plus copper fall back to our own candle renderer. That is
TradingView's licensing limit, verified in the browser, not a bug in this app.

## World stocks — every country TradingView lists

`https://in.tradingview.com/markets/` organises equities by country, and each country page is one
public scanner section. `backend/country_markets.py` asks all 36 sections that answer (america, uk,
germany, france, italy, spain, netherlands, switzerland, sweden, norway, denmark, poland, canada,
australia, newzealand, india, japan, china, hongkong, korea, taiwan, singapore, malaysia, indonesia,
thailand, vietnam, philippines, bangladesh, pakistan, turkey, brazil, mexico, argentina, chile,
israel, egypt) for their **12 biggest listed companies by market cap** — 432 companies, one row per
company, dual listings merged (Reliance appears as `NSE:RELIANCE`, not also as `BSE:RELIANCE`) and
derivative lines dropped (depositary shares, ADRs, receipts, preferred series, Thai NVDR, Swiss
"TEMP" lines). South Africa, Saudi Arabia and the UAE sections answer 404, so they are not in the
list.

Those instruments live in the **WORLD STOCKS** market. Boot reads `backend/world_universe.json`
(a capture of the live scanner) so a fresh machine has all 36 countries immediately, then
re-crawls in the background once a week; an instrument an open position still rides is never
switched off.

Two things worth knowing:

* **Prices stay in the exchange's own currency.** Toyota is quoted in ¥, SAP in €, Petrobras in R$,
  and the currency code is printed next to every quote. P&L is still rupees, because quantity is
  `margin ÷ entry price`, so a 2% move earns 2% of the margin whatever the listing currency is —
  no FX conversion is involved and none is needed.
* **Filter by country, or show everything.** The watchlist has a country dropdown (each entry says
  how many companies and how many live quotes that country has) and a **SHOW ALL** button that
  lists every one of the 976 instruments instead of the busiest 60.

## Bot control

The **BOT ON / BOT OFF** pill in the top bar is the per-account switch — one click starts or
stops the bot trading your paper capital, and it keeps your max-positions, risk and mode
settings. The ⚡ AI Bot button next to it opens the drawer with the full controls, open
positions and the live log. Both stay in sync, and every change is written to the bot log.
The admin panel holds a separate global switch: with that off, your own ON does nothing.

## How the bot decides

The bot analyses all seven markets every cycle — FOREX, STOCKS, COMPANIES, WORLD (the country
stocks), METALS, INDICES, CRYPTO — and ranks each symbol **inside its own market** (crypto turnover is orders of
magnitude above an FX quote, so one global sort would starve everything else). A symbol is
only traded when every factor below is measured, never assumed:

| Factor | Measured from |
| --- | --- |
| Session range and 24h change | the scraped quote (Binance / TradingView / CNBC) |
| Trend, RSI, per-quote volatility | this process's own tick history of real quotes |
| Candle agreement | real Binance 1m klines (crypto only) |

Rules that follow from that: a symbol whose feed has gone dark is skipped, a market with too
little measured movement to reach a target inside its hold window is skipped, and take-profit
and stop are sized from the symbol's own volatility and quote cadence — capped at half of its
session range **and capped again at 1.5× the move the symbol demonstrably makes in that window**,
because a target it cannot reach in time is only ever paid by the stop-loss or the clock
(measured on this app's own ledger: setups asking 1.7-3% almost never hit, ones near 0.9% did).
Winning trades get a breakeven move at 75% of target and then a trail that gives back **half the
stop distance** (not a fraction of the target — on the slow markets the whole target is smaller
than one ordinary quote, so a target-sized trail closed every winner at flat). A trade that never
goes green is cut early: `STALL_EXIT` closes it once **half** of its own hold window has run, it is
still red and it has paid under a quarter of target. That rule came straight out of the ledger —
155 of 640 closes in one 90-minute window peaked below 0.02% against a 0.3% target, and every one
of them rode on to a full −0.28% stop; cut at the half-window mark the same setups cost −0.07%.
Crypto is held to a much higher bar than the rest (`min_conf` 0.75, day range band capped at 6%):
it is the only 3-second market, and in every window measured it carried the book's loss while the
other markets were flat or green. New positions are
filled round-robin across markets so one volatile altcoin cannot take every slot, and inside the
all-countries market the ticket pool is interleaved **country first** (`_rotate`) and started at a
new country every cycle, so a cycle's two world slots never go to the same exchange twice and the
36 countries come round in turn instead of the three biggest names trading all day.

Every position is marked and settled on a **confirmed quote only**. Until a market has answered
for a symbol, the app holds a placeholder level for it (the price the seed file captured, or the
anchor in `price_feed.py`), and those placeholders can be far from the exchange — the app once
stopped a Netflix trade out at ₹690 when the scanner said ₹70. Reading through
`feed.live_price()` instead of `feed.price()` means a restart warms the feed up before any trade
is entered, exited or limit-filled, and an open position keeps its last real mark in the meantime.

Tick history starts when the process starts, so after a restart each market needs about 15 of
its own real quotes before the bot will trade it: crypto in a couple of minutes, the swept
markets in roughly four (one posted scanner call quotes all of them at once, with CNBC filling
the handful the scanner does not carry). The **A-Z MARKET ANALYSIS** panel in the bot drawer
says exactly how many symbols per market have history, how many passed and how many were
skipped.

Sizing and protection: the margin per trade is your **risk per trade** percentage of the free
deposit balance, with a floor of 2% of capital (capped at ₹50) so a ₹1,000 account still gets
real positions instead of the bot sitting silent. A position can never lose more than the
margin it posted — a close that would cost more is booked at −margin and logged as
`LIQUIDATED`, which keeps a bad quote from draining the wallet.

Money in vs money earned: the **PROFIT GOAL** tracks the trading leg only. The first top-up sets the
baseline (₹1,000 in → ₹1,500 target) and every later manual deposit moves both figures by the
amount credited, so depositing ₹500 into a ₹1,000 → ₹1,500 goal re-bases it to ₹1,500 → ₹2,000
rather than showing the goal as "achieved" on money you put in yourself. **Set goal** overrides the
two numbers directly, and deposits, withdrawals and the balance are all yours to drive from the
wallet drawer — none of it touches a payment gateway.

The account poller redraws an open drawer every 3 seconds, so any field you touch (the goal's
Starting ₹ / Target ₹, the bot's MAX POSITIONS and RISK PER TRADE sliders, the enabled switch) is
frozen at your value until you press its Save button or close the drawer — before this the poller
overwrote the digits mid-typing and the sliders snapped back under the pointer.

## Layout

```
backend/app.py        Flask API (:5050), user app (:8988), admin (:8989) in three threads
backend/price_feed.py keyless live quote scraper + candle/indicator maths
backend/country_markets.py  all-country equity discovery from TradingView's scanner
backend/world_universe.json  the 432 discovered companies shipped as the first-boot seed
backend/bot_engine.py scan → signal → open → mark-to-market → close loop, resting limit fills
backend/database.py   SQLite schema, migrations, demo seed data (backend/tradepro.db)
frontend/             the terminal: index.html + styles.css + app.js (no build step)
admin/                the admin panel
.legacy/              the original minified frontend, kept for reference
```

## Honest warning

This turns ₹1,000 into ₹1,500 only if the market cooperates. Live testing on this build
showed the bot losing money on most cycles — which is what most short-horizon bots do.
Paper results do not predict real results, and real trading can lose money faster than
any dashboard can show it.
