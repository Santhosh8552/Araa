/* ARAA Vision — live market wiring for the Vision Trading Terminal.
   Watchlist, chart and analysis panel are driven by /api/market/quotes and
   /api/smc/analysis (live candles + SMC trade plan). Market data by biquote. */
(function () {
  "use strict";
  var VT = window.VT;
  if (!VT) return;
  var $ = function (id) { return document.getElementById(id); };

  var WATCH = [
    ["XAUUSD", "Gold / US Dollar", "METALS", 2], ["EURUSD", "Euro / US Dollar", "FOREX", 5],
    ["GBPUSD", "Pound / US Dollar", "FOREX", 5], ["GBPJPY", "Pound / Yen", "FOREX", 3],
    ["USDJPY", "US Dollar / Yen", "FOREX", 3], ["NAS100", "Nasdaq 100", "INDICES", 1],
    ["US30", "Dow Jones 30", "INDICES", 1], ["US500", "S&P 500", "INDICES", 1],
    ["AUDUSD", "Aussie / US Dollar", "FOREX", 5], ["USDCAD", "US Dollar / CAD", "FOREX", 5],
    ["EURJPY", "Euro / Yen", "FOREX", 3], ["XAGUSD", "Silver / US Dollar", "METALS", 3],
    ["USOIL", "WTI Crude Oil", "ENERGY", 3], ["BTCUSD", "Bitcoin / US Dollar", "CRYPTO", 2],
    ["ETHUSD", "Ethereum / US Dollar", "CRYPTO", 2], ["SOLUSDT", "Solana / Tether", "CRYPTO", 2]
  ];
  var DIGITS = {};
  WATCH.forEach(function (w) { DIGITS[w[0]] = w[3]; });
  var quotes = {};
  var lastAnalysis = null;

  function digits(sym, p) {
    if (DIGITS[sym] != null) return DIGITS[sym];
    return p >= 1000 ? 2 : p >= 50 ? 3 : 5;
  }
  function fmt(sym, p) { return (p == null || isNaN(p)) ? "—" : Number(p).toFixed(digits(sym, p)); }
  function cap(s) { s = String(s || "").toLowerCase(); return s.charAt(0).toUpperCase() + s.slice(1); }
  function cls(dir) { return dir === "BULLISH" || dir === "BUY" ? "pos" : dir === "BEARISH" || dir === "SELL" ? "neg" : "mut"; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]; }); }
  function tfLabel(tf) { return String(tf || "").toUpperCase(); }

  VT.liveWatch = true;
  VT.liveAnalysis = true;
  VT.symbol = "XAUUSD";
  VT.timeframe = "1m";
  VT.indicators.quantumVision = false;
  VT.indicators.liquidityHeatmap = false;
  VT.indicators.marketDna = false;

  function closeOverlays() {
    [["qvPanel", "[data-qv='toggle']"], ["lqPanel", "[data-lq='toggle']"]].forEach(function (p) {
      var el = $(p[0]); if (el) el.style.display = "none";
      var b = document.querySelector(p[1]);
      if (b) { b.setAttribute("aria-pressed", "false"); b.classList.remove("active"); }
    });
    var lqBtn = document.querySelector("button.lq-btn[data-lq='toggle']");
    if (lqBtn) lqBtn.addEventListener("click", function () {
      var el = $("lqPanel"); if (el) el.style.display = VT.indicators.liquidityHeatmap ? "" : "none";
    });
  }

  /* ------------------------------- watchlist ------------------------------- */
  VT.renderWatchlist = function () {
    var wl = $("wl");
    if (!wl) return;
    wl.innerHTML = WATCH.map(function (w) {
      return '<button class="wl-row" data-sym="' + w[0] + '" data-cat="' + w[2] + '" aria-current="' + (VT.symbol === w[0]) + '">' +
        "<span><b>" + w[0] + "</b><small>" + esc(w[1]) + "</small></span>" +
        '<span class="wl-r"><span class="wl-p">—</span><span class="wl-c mut">—</span></span></button>';
    }).join("");
    wl.querySelectorAll(".wl-row").forEach(function (row) {
      row.addEventListener("click", function () { VT.setSymbol(row.getAttribute("data-sym")); });
    });
    paintWatch();
  };

  function paintWatch() {
    document.querySelectorAll("#wl .wl-row").forEach(function (row) {
      var s = row.getAttribute("data-sym"), q = quotes[s];
      row.setAttribute("aria-current", String(s === VT.symbol));
      if (!q) return;
      var pEl = row.querySelector(".wl-p"), cEl = row.querySelector(".wl-c");
      var prev = parseFloat(pEl.getAttribute("data-v"));
      pEl.textContent = fmt(s, q.price);
      pEl.setAttribute("data-v", q.price);
      if (!isNaN(prev) && prev !== q.price) {
        pEl.classList.remove("tick-up", "tick-dn"); void pEl.offsetWidth;
        pEl.classList.add(q.price > prev ? "tick-up" : "tick-dn");
      }
      var ch = Number(q.change_pct || 0);
      cEl.textContent = (ch >= 0 ? "+" : "") + ch.toFixed(2) + "%";
      cEl.className = "wl-c " + (ch >= 0 ? "pos" : "neg");
    });
  }

  function pollQuotes() {
    var syms = WATCH.map(function (w) { return w[0]; });
    if (syms.indexOf(VT.symbol) < 0) syms.push(VT.symbol);
    return fetch("/api/market/quotes?symbols=" + encodeURIComponent(syms.join(",")))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.quotes) return;
        quotes = d.quotes;
        paintWatch();
        applyTick();
      }).catch(function () {});
  }

  /* --------------------------- live forming candle --------------------------- */
  function applyTick() {
    var q = quotes[VT.symbol];
    if (!q || !VT.candles || !VT.candles.length || VT.replayActive) return;
    var k = VT.candles[VT.candles.length - 1];
    k.c = q.price; if (q.price > k.h) k.h = q.price; if (q.price < k.l) k.l = q.price;
    var s = VT.symbol;
    var set = function (id, v) { var el = $(id); if (el) el.textContent = v; };
    set("t_sub_o", fmt(s, k.o)); set("t_sub_h", fmt(s, k.h)); set("t_sub_l", fmt(s, k.l)); set("t_sub_c", fmt(s, k.c));
    set("t_sub_bid", fmt(s, q.bid)); set("t_sub_ask", fmt(s, q.ask)); set("t_sub_spread", fmt(s, q.spread));
    var chg = $("t_sub_chg");
    if (chg) {
      var c = Number(q.change_pct || 0);
      chg.textContent = (c >= 0 ? "+" : "") + c.toFixed(2) + "%";
      chg.style.color = c >= 0 ? "#22c55e" : "#f87171";
    }
    var lb = $("t_live_badge");
    if (lb) {
      var open = q.market_state === "open" && !q.stale;
      lb.innerHTML = '<span class="dot"></span><b>' + (open ? "LIVE" : "MARKET CLOSED") + "</b>";
      lb.classList.toggle("s-live", open);
    }
    if (typeof VT.renderSMCChart === "function") VT.renderSMCChart();
  }

  /* ----------------------------- analysis panel ----------------------------- */
  function ensurePanes() {
    var rp = $("rpane");
    if (!rp || $("rp_strength")) return;
    var wrap = document.createElement("div");
    wrap.id = "rp_strength";
    while (rp.firstChild) wrap.appendChild(rp.firstChild);
    rp.appendChild(wrap);
    ["rp_scenarios", "rp_analysis"].forEach(function (id) {
      var d = document.createElement("div"); d.id = id; d.hidden = true; rp.appendChild(d);
    });
    var plan = document.createElement("section");
    plan.className = "iva-sec"; plan.id = "iva_plan_sec";
    var dirSec = wrap.querySelector(".iva-sec");
    if (dirSec && dirSec.nextSibling) wrap.insertBefore(plan, dirSec.nextSibling); else wrap.appendChild(plan);
    document.querySelectorAll(".t-ai .tabs button[data-rt]").forEach(function (b) {
      b.addEventListener("click", function () { showPane(b.getAttribute("data-rt")); });
    });
  }
  function showPane(name) {
    ["strength", "scenarios", "analysis"].forEach(function (n) {
      var el = $("rp_" + n); if (el) el.hidden = n !== name;
    });
  }

  function planCard(p, active) {
    var s = VT.symbol, buy = p.side === "BUY";
    return '<div class="iva-t lv-plan ' + (buy ? "lv-buy" : "lv-sell") + (active ? " lv-on" : "") + '">' +
      "<small>" + (buy ? "Where to buy" : "Where to sell") + "</small>" +
      '<b class="' + (buy ? "pos" : "neg") + '">' + (buy ? "BUY" : "SELL") + " zone " + fmt(s, p.entry_low) + " – " + fmt(s, p.entry_high) + "</b>" +
      '<dl class="iva-dl"><dt>Stop loss</dt><dd>' + fmt(s, p.stop_loss) + "</dd><dt>Target 1</dt><dd>" + fmt(s, p.take_profit_1) +
      "</dd><dt>Target 2</dt><dd>" + fmt(s, p.take_profit_2) + "</dd><dt>Risk : reward</dt><dd>1 : " + p.risk_reward + "</dd></dl>" +
      "<span>" + esc(p.trigger) + "</span></div>";
  }

  function renderAnalysis(res) {
    ensurePanes();
    var ai = res.ai_report || {}, tp = res.trade_plan || {}, mtf = res.mtf || {}, s = res.symbol;
    var set = function (id, v) { var el = $(id); if (el) el.textContent = v; };
    var width = function (id, v) { var el = $(id); if (el) el.style.width = v + "%"; };
    var buy = Number(ai.buy_strength || 0), sell = Number(ai.sell_strength || 0);
    set("iva_buy_pct", buy + "%"); width("iva_buy_bar", buy);
    set("iva_sell_pct", sell + "%"); width("iva_sell_bar", sell);
    var bias = ai.overall_bias || "NEUTRAL";
    var bb = $("iva_bias_badge"); if (bb) { bb.textContent = bias; bb.className = cls(bias); }
    var net = (buy - sell) / 100;
    set("iva_net_score", "net " + (net >= 0 ? "+" : "") + net.toFixed(2));
    var conf = Number(ai.confidence_score || 0);
    set("iva_conf_txt", (conf >= 75 ? "High" : conf >= 55 ? "Medium" : "Low") + " · " + conf + "%"); width("iva_conf_bar", conf);
    set("iva_confluence_txt", (ai.confluence_score || 0) + "/100"); width("iva_confluence_bar", ai.confluence_score || 0);
    var al = mtf.alignment || "MIXED";
    var ha = $("iva_htf_align");
    if (ha) { ha.textContent = al === "MIXED" ? "Mixed" : cap(al) + " alignment"; ha.className = cls(al); if (ha.nextElementSibling) ha.nextElementSibling.textContent = (mtf.bull_votes || 0) + " bullish · " + (mtf.bear_votes || 0) + " bearish of 5 TFs"; }
    var head = document.querySelector("#rpane .iva-head p");
    if (head) head.textContent = "MARKET STRENGTH ANALYSIS · " + s + " · " + tfLabel(res.timeframe) + " · as of " +
      new Date((res.timestamp || Date.now() / 1000) * 1000).toLocaleString([], {day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"});

    var dec = tp.decision || "WAIT";
    var planSec = $("iva_plan_sec");
    if (planSec && tp.buy) {
      planSec.innerHTML = '<h4>Trade plan <small>where to buy · where to sell</small></h4>' +
        '<div class="iva-t lv-dec"><small>Current call</small><b class="' + cls(dec) + '">' + dec + "</b><span>" + esc(tp.reason) + "</span></div>" +
        planCard(dec === "SELL" ? tp.sell : tp.buy, dec !== "WAIT") + planCard(dec === "SELL" ? tp.buy : tp.sell, false) +
        '<p class="iva-disc">Levels come from live order blocks, liquidity and ATR. Educational analysis, not financial advice.</p>';
    }

    // multi-timeframe card
    document.querySelectorAll("#rp_strength .iva-card").forEach(function (card) {
      var h = card.querySelector("h3"); if (!h) return;
      var t = h.textContent || "";
      if (/Multi-timeframe/i.test(t) && mtf.rows) {
        card.innerHTML = "<h3>Multi-timeframe</h3>" + mtf.rows.map(function (r) {
          return '<div class="mtf-r"><span>' + tfLabel(r.tf) + '</span><span class="pill ' + cls(r.bias) + '">' + cap(r.bias) + "</span></div>";
        }).join("") + '<div class="mtf-r total"><span>Alignment</span><span>' + (al === "MIXED" ? "Mixed" : cap(al) + " alignment") + "</span></div>" +
          '<p class="note">Bias = direction of the latest confirmed BOS / CHoCH on each timeframe, from live candles.</p>';
      } else if (/Current bias/i.test(t)) {
        card.innerHTML = '<h3>Current bias: <span class="' + cls(bias) + '">' + bias + "</span></h3><p>" + esc(ai.explanation) + "</p>" +
          "<h4>Risk notes</h4><ul class=\"iva-ul no\">" + (ai.risk_considerations || []).map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul>";
      } else if (/How the scores|Candle Strength/i.test(t)) {
        card.hidden = true;
      }
    });
    // stale static market-condition / structure tiles
    var secs = document.querySelectorAll("#rp_strength .iva-sec");
    secs.forEach(function (sec) {
      var h = sec.querySelector("h4"); if (!h) return;
      if (/Market condition/i.test(h.textContent)) {
        sec.innerHTML = '<h4>Market condition</h4><div class="iva-tiles"><div class="iva-t"><small>Market Regime</small><b>' +
          cap(String(ai.market_regime || "").replace("_", " ")) + "</b><span>buy vs sell spread " + Math.abs(buy - sell) + " pts</span></div>" +
          '<div class="iva-t"><small>Volatility</small><b>' + cap(ai.volatility) + "</b><span>ATR " + fmt(s, res.atr) + "</span></div></div>";
      } else if (/Structure events/i.test(h.textContent)) {
        var evs = (res.structure_breaks || []).slice(-4).reverse();
        var last = evs[0];
        sec.innerHTML = '<h4>Structure events</h4>' + (last ? '<div class="iva-t"><small>Latest Structure Event</small><b><span class="' + cls(last.direction) + '">' +
          cap(last.direction) + " " + esc(String(last.type).replace(/_/g, " ")) + "</span></b><span>" + fmt(s, last.break_price || last.price) + " · confirmed</span></div>" : "<p class=\"iva-disc\">No confirmed break yet.</p>") +
          '<ul class="iva-ev-list">' + evs.map(function (e) {
            return "<li><time>" + new Date(e.time * 1000).toLocaleString([], {day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"}) + "</time>" +
              cap(e.direction) + " " + esc(String(e.type).replace(/_/g, " ")) + " at " + fmt(s, e.break_price || e.price) + " (" + tfLabel(res.timeframe) + ")</li>";
          }).join("") + "</ul>";
      }
    });

    // Scenarios & Zones tab
    var sc = (ai.scenarios || {}), zones = [];
    (res.order_blocks || []).filter(function (o) { return o.status !== "MITIGATED"; }).slice(-6).reverse().forEach(function (o) {
      zones.push('<div class="mtf-r"><span class="' + (/BULL/.test(o.type) ? "pos" : "neg") + '">' + (/BULL/.test(o.type) ? "Demand (bullish OB)" : "Supply (bearish OB)") +
        "</span><span>" + fmt(s, o.low != null ? o.low : o.bottom) + " – " + fmt(s, o.high != null ? o.high : o.top) + " · " + esc(o.status) + "</span></div>");
    });
    var liq = res.liquidity || {};
    var sp = $("rp_scenarios");
    if (sp) sp.innerHTML = '<section class="iva-sec">' + ($("iva_plan_sec") ? $("iva_plan_sec").innerHTML : "") + "</section>" +
      '<section class="iva-sec"><h4>Scenarios</h4>' +
      ["bullish", "bearish"].map(function (k) {
        var x = sc[k] || {};
        return '<div class="iva-t"><small>' + cap(k) + ' scenario</small><b class="' + (k === "bullish" ? "pos" : "neg") + '">Entry ' + esc(x.entry_zone) + "</b>" +
          "<span>" + esc(x.trigger) + " · T1 " + fmt(s, x.target_1) + " · T2 " + fmt(s, x.target_2) + " · invalid " + fmt(s, x.invalidation) + "</span></div>";
      }).join("") + (sc.neutral ? '<div class="iva-t"><small>Neutral</small><b>Stand aside</b><span>' + esc(sc.neutral.advice) + "</span></div>" : "") + "</section>" +
      '<section class="iva-sec"><h4>Key zones</h4>' + (zones.join("") || '<p class="iva-disc">No unmitigated order blocks in view.</p>') +
      (liq.bsl ? '<div class="mtf-r"><span class="neg">Buy-side liquidity</span><span>' + fmt(s, liq.bsl.level) + "</span></div>" : "") +
      (liq.ssl ? '<div class="mtf-r"><span class="pos">Sell-side liquidity</span><span>' + fmt(s, liq.ssl.level) + "</span></div>" : "") + "</section>";
    var ap = $("rp_analysis");
    if (ap) ap.innerHTML = '<section class="iva-sec"><h4>Structure <small>' + s + " · " + tfLabel(res.timeframe) + "</small></h4>" +
      '<ul class="iva-ev-list">' + (res.structure_breaks || []).slice(-12).reverse().map(function (e) {
        return "<li><time>" + new Date(e.time * 1000).toLocaleString([], {day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"}) + '</time><span class="' + cls(e.direction) + '">' +
          esc(String(e.type).replace(/_/g, " ")) + "</span> at " + fmt(s, e.break_price || e.price) + "</li>";
      }).join("") + "</ul></section>" +
      '<section class="iva-sec"><h4>Fair value gaps</h4>' + (res.fair_value_gaps || []).slice(-6).reverse().map(function (f) {
        return '<div class="mtf-r"><span class="' + (/BULL/.test(f.type) ? "pos" : "neg") + '">' + esc(String(f.type).replace(/_/g, " ")) + "</span><span>" +
          fmt(s, f.bottom != null ? f.bottom : f.low) + " – " + fmt(s, f.top != null ? f.top : f.high) + " · " + esc(f.status) + "</span></div>";
      }).join("") + "</section>";
  }

  /* --------------------------- analysis refresh --------------------------- */
  var origLoad = VT.loadMarketData;
  VT.loadMarketData = function (sym, tf) {
    var p = origLoad.call(VT, sym || VT.symbol, tf || VT.timeframe);
    return Promise.resolve(p).then(function () {
      if (VT.smcData && VT.smcData.success) { lastAnalysis = VT.smcData; renderAnalysis(VT.smcData); }
      paintWatch(); applyTick();
    });
  };

  function refreshAnalysis() {
    if (VT.replayActive || document.hidden || !$("rpane")) return;
    var s = VT.symbol, t = VT.timeframe;
    fetch("/api/smc/analysis/" + encodeURIComponent(s) + "?timeframe=" + encodeURIComponent(t))
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (!res || !res.success || s !== VT.symbol || t !== VT.timeframe || !res.candles || !res.candles.length) return;
        VT.candles = res.candles; VT.smcData = res; lastAnalysis = res;
        if (window.S) { window.S.candles = res.candles; window.S.smcDna = res; }
        renderAnalysis(res);
        applyTick();
      }).catch(function () {});
  }

  function boot() {
    closeOverlays();
    VT.renderWatchlist();
    ensurePanes();
    var symS = $("symBtnS"); if (symS) symS.textContent = VT.symbol;
    VT.loadMarketData(VT.symbol, VT.timeframe);
    pollQuotes();
    setInterval(pollQuotes, 2000);
    setInterval(refreshAnalysis, 15000);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { setTimeout(boot, 0); });
  else setTimeout(boot, 0);
})();
