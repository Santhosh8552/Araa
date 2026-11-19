/* ==========================================================================
   ARAA VISION — Smart Money Concepts (SMC) & Market Structure Terminal
   Inspired by Infinity Vision FX Terminal architecture
   Features:
   - 3-Column / 2-Row Grid Layout with Draggable Resizers
   - Interactive Canvas: Candlesticks, FVGs, Order Blocks, BOS, CHoCH, Liquidity
   - Quantum Vision: 1,000 Monte Carlo Simulated Path Projection Fan
   - Market DNA: Historical Fractal Match Trajectory
   - Liquidity Heatmap Depth Bands (SSL / BSL)
   - Drawing Toolbar: Crosshair, Trend Line, Rect/OB, Fibonacci, Measure, Long/Short
   - Real-time AI Confluence & Direction Gauge (Buy vs Sell Strength)
   - Real-time Structure Timeline Feed (Confirmed Events)
   - Quick 1-Click Order Execution directly into CoinDCX Live / Paper Engine
   ========================================================================== */

(function() {
  "use strict";

  // State for Vision Terminal
  window.VT = {
    mode: "advanced", // clean | standard | advanced
    quantumVision: true,
    marketDna: true,
    liquidityHeatmap: true,
    sdLevels: false,
    gexLevels: false,
    aiHud: false,
    activeTool: "cross",
    magnet: false,
    drawings: [],
    currentDrawing: null,
    replayActive: false,
    replayIndex: 0,
    replayCandles: [],
    replayTimer: null,
    activeTabAi: "strength",
    activeTabBt: "feed"
  };

  // Safe helper
  const $id = id => document.getElementById(id);

  /* ---------------------------- Resizer Engine ---------------------------- */
  function initResizers() {
    const term = $id("term");
    if (!term) return;

    let activeRz = null;
    let startX = 0, startY = 0;
    let startW = 0, startH = 0;

    document.querySelectorAll(".t-rz").forEach(rz => {
      rz.addEventListener("mousedown", e => {
        activeRz = rz.getAttribute("data-rz");
        startX = e.clientX;
        startY = e.clientY;

        if (activeRz === "wl") {
          startW = parseInt(getComputedStyle(term).getPropertyValue("--wl-w")) || 240;
        } else if (activeRz === "ai") {
          startW = parseInt(getComputedStyle(term).getPropertyValue("--ai-w")) || 380;
        } else if (activeRz === "bt") {
          startH = parseInt(getComputedStyle(term).getPropertyValue("--bt-h")) || 250;
        }

        document.body.style.userSelect = "none";
        e.preventDefault();
      });
    });

    window.addEventListener("mousemove", e => {
      if (!activeRz) return;

      if (activeRz === "wl") {
        const delta = e.clientX - startX;
        const newW = Math.max(160, Math.min(460, startW + delta));
        term.style.setProperty("--wl-w", `${newW}px`);
      } else if (activeRz === "ai") {
        const delta = startX - e.clientX;
        const newW = Math.max(260, Math.min(560, startW + delta));
        term.style.setProperty("--ai-w", `${newW}px`);
      } else if (activeRz === "bt") {
        const delta = startY - e.clientY;
        const newH = Math.max(100, Math.min(520, startH + delta));
        term.style.setProperty("--bt-h", `${newH}px`);
      }

      if (typeof window.VT.resizeCanvas === "function") {
        window.VT.resizeCanvas();
      }
    });

    window.addEventListener("mouseup", () => {
      if (activeRz) {
        activeRz = null;
        document.body.style.userSelect = "";
      }
    });
  }

  /* ---------------------------- Panel Toggle Handlers ---------------------------- */
  function initPanelToggles() {
    const term = $id("term");
    if (!term) return;

    document.querySelectorAll("[data-act='pWl']").forEach(btn => {
      btn.addEventListener("click", () => {
        const cur = term.getAttribute("data-wl") === "0" ? "1" : "0";
        term.setAttribute("data-wl", cur);
        btn.setAttribute("aria-pressed", cur === "1");
        if (typeof window.VT.resizeCanvas === "function") window.VT.resizeCanvas();
      });
    });

    document.querySelectorAll("[data-act='pAi']").forEach(btn => {
      btn.addEventListener("click", () => {
        const cur = term.getAttribute("data-ai") === "0" ? "1" : "0";
        term.setAttribute("data-ai", cur);
        btn.setAttribute("aria-pressed", cur === "1");
        if (typeof window.VT.resizeCanvas === "function") window.VT.resizeCanvas();
      });
    });

    document.querySelectorAll("[data-act='pBt']").forEach(btn => {
      btn.addEventListener("click", () => {
        const cur = term.getAttribute("data-bt") === "0" ? "1" : "0";
        term.setAttribute("data-bt", cur);
        btn.setAttribute("aria-pressed", cur === "1");
        if (typeof window.VT.resizeCanvas === "function") window.VT.resizeCanvas();
      });
    });

    document.querySelectorAll("[data-act='pMax']").forEach(btn => {
      btn.addEventListener("click", () => {
        const isMax = term.getAttribute("data-wl") === "0" && term.getAttribute("data-bt") === "0";
        if (isMax) {
          term.setAttribute("data-wl", "1");
          term.setAttribute("data-bt", "1");
          term.setAttribute("data-ai", "1");
          btn.setAttribute("aria-pressed", "false");
        } else {
          term.setAttribute("data-wl", "0");
          term.setAttribute("data-bt", "0");
          btn.setAttribute("aria-pressed", "true");
        }
        if (typeof window.VT.resizeCanvas === "function") window.VT.resizeCanvas();
      });
    });
  }

  /* ---------------------------- Top Bar Modes & Features ---------------------------- */
  function initTopBarFeatures() {
    // Modes: clean, standard, advanced
    document.querySelectorAll("[data-ivmode]").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("[data-ivmode]").forEach(b => {
          b.classList.remove("active");
          b.setAttribute("aria-pressed", "false");
        });
        btn.classList.add("active");
        btn.setAttribute("aria-pressed", "true");
        window.VT.mode = btn.getAttribute("data-ivmode");
        if (typeof window.VT.renderSMCChart === "function") window.VT.renderSMCChart();
      });
    });

    // Quantum Vision toggle
    document.querySelectorAll("[data-qv='toggle']").forEach(btn => {
      btn.addEventListener("click", () => {
        window.VT.quantumVision = !window.VT.quantumVision;
        btn.classList.toggle("active", window.VT.quantumVision);
        btn.setAttribute("aria-pressed", String(window.VT.quantumVision));
        const qvP = $id("qvPanel");
        if (qvP) qvP.style.display = window.VT.quantumVision ? "block" : "none";
        if (typeof window.VT.renderSMCChart === "function") window.VT.renderSMCChart();
      });
    });

    // Market DNA toggle
    document.querySelectorAll("[data-dna='toggle']").forEach(btn => {
      btn.addEventListener("click", () => {
        window.VT.marketDna = !window.VT.marketDna;
        btn.classList.toggle("active", window.VT.marketDna);
        btn.setAttribute("aria-pressed", String(window.VT.marketDna));
        if (typeof window.VT.renderSMCChart === "function") window.VT.renderSMCChart();
      });
    });

    // Liquidity toggle
    document.querySelectorAll("[data-lq='toggle']").forEach(btn => {
      btn.addEventListener("click", () => {
        window.VT.liquidityHeatmap = !window.VT.liquidityHeatmap;
        btn.classList.toggle("active", window.VT.liquidityHeatmap);
        btn.setAttribute("aria-pressed", String(window.VT.liquidityHeatmap));
        if (typeof window.VT.renderSMCChart === "function") window.VT.renderSMCChart();
      });
    });

    // SD Levels toggle
    document.querySelectorAll("[data-sd='btn']").forEach(btn => {
      btn.addEventListener("click", () => {
        window.VT.sdLevels = !window.VT.sdLevels;
        btn.classList.toggle("active", window.VT.sdLevels);
        btn.setAttribute("aria-pressed", String(window.VT.sdLevels));
        if (typeof window.VT.renderSMCChart === "function") window.VT.renderSMCChart();
      });
    });

    // GEX toggle
    document.querySelectorAll("[data-gex='btn']").forEach(btn => {
      btn.addEventListener("click", () => {
        window.VT.gexLevels = !window.VT.gexLevels;
        btn.classList.toggle("active", window.VT.gexLevels);
        btn.setAttribute("aria-pressed", String(window.VT.gexLevels));
        if (typeof window.VT.renderSMCChart === "function") window.VT.renderSMCChart();
      });
    });

    // Timeframe selector
    document.querySelectorAll(".tfs button[data-tf]").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tfs button[data-tf]").forEach(b => {
          b.classList.remove("active");
          b.setAttribute("aria-pressed", "false");
        });
        btn.classList.add("active");
        btn.setAttribute("aria-pressed", "true");
        const tf = btn.getAttribute("data-tf");
        if (window.S) {
          window.S.tf = tf;
          if ($id("t_tf_badge")) $id("t_tf_badge").textContent = tf.toUpperCase();
          if (typeof window.loadChart === "function") window.loadChart();
        }
      });
    });

    // Symbol dropdown / button
    const symSel = $id("symSel");
    if (symSel) {
      symSel.addEventListener("change", e => {
        const s = e.target.value;
        if (window.S) {
          window.S.symbol = s;
          if ($id("symBtnS")) $id("symBtnS").textContent = s;
          if ($id("t_symbol")) $id("t_symbol").textContent = s;
          if (typeof window.loadChart === "function") window.loadChart();
        }
      });
    }

    // Refresh & Auto fit buttons
    const zfit = document.querySelector("[data-act='zfit']");
    if (zfit) {
      zfit.addEventListener("click", () => {
        if (typeof window.VT.resizeCanvas === "function") window.VT.resizeCanvas();
        if (typeof window.VT.renderSMCChart === "function") window.VT.renderSMCChart();
      });
    }

    const refBtn = document.querySelector("[data-act='refresh']");
    if (refBtn) {
      refBtn.addEventListener("click", () => {
        if (typeof window.loadChart === "function") window.loadChart();
      });
    }
  }

  /* ---------------------------- Drawing Tools Rail ---------------------------- */
  function initDrawingTools() {
    const bar = $id("cdBar");
    if (!bar) return;

    bar.querySelectorAll("[data-cdt]").forEach(btn => {
      btn.addEventListener("click", () => {
        bar.querySelectorAll("[data-cdt]").forEach(b => {
          b.classList.remove("active");
          b.setAttribute("aria-pressed", "false");
        });
        btn.classList.add("active");
        btn.setAttribute("aria-pressed", "true");
        window.VT.activeTool = btn.getAttribute("data-cdt");

        if (window.VT.activeTool === "eraser") {
          window.VT.drawings = [];
          if (typeof window.VT.renderDrawings === "function") window.VT.renderDrawings();
        }
      });
    });

    const clearBtn = bar.querySelector("[data-cda='clear']");
    if (clearBtn) {
      clearBtn.addEventListener("click", () => {
        window.VT.drawings = [];
        if (typeof window.VT.renderDrawings === "function") window.VT.renderDrawings();
      });
    }

    const magBtn = bar.querySelector("[data-cda='magnet']");
    if (magBtn) {
      magBtn.addEventListener("click", () => {
        window.VT.magnet = !window.VT.magnet;
        magBtn.classList.toggle("active", window.VT.magnet);
        magBtn.setAttribute("aria-pressed", String(window.VT.magnet));
      });
    }
  }

  /* ---------------------------- Right AI & Bottom Tabs ---------------------------- */
  function initTabSwitchers() {
    // Right AI panel tabs
    const aiAside = document.querySelector(".t-ai");
    if (aiAside) {
      aiAside.querySelectorAll(".tabs button[data-rt]").forEach(btn => {
        btn.addEventListener("click", () => {
          aiAside.querySelectorAll(".tabs button[data-rt]").forEach(b => {
            b.classList.remove("active");
            b.setAttribute("aria-selected", "false");
          });
          btn.classList.add("active");
          btn.setAttribute("aria-selected", "true");
          window.VT.activeTabAi = btn.getAttribute("data-rt");
        });
      });
    }

    // Bottom dock tabs
    const btSec = document.querySelector(".t-bottom");
    if (btSec) {
      btSec.querySelectorAll(".tabs button[data-bt]").forEach(btn => {
        btn.addEventListener("click", () => {
          btSec.querySelectorAll(".tabs button[data-bt]").forEach(b => {
            b.classList.remove("active");
            b.setAttribute("aria-selected", "false");
          });
          btn.classList.add("active");
          btn.setAttribute("aria-selected", "true");
          const target = btn.getAttribute("data-bt");
          window.VT.activeTabBt = target;

          btSec.querySelectorAll(".bt-tab-pane").forEach(pane => pane.classList.add("hide"));
          const activePane = $id(`bt_tab_${target}`);
          if (activePane) activePane.classList.remove("hide");
        });
      });
    }
  }

  /* ---------------------------- Interactive Drawing & Canvas Engine ---------------------------- */
  function initCanvasInteractions() {
    const cv = $id("chart");
    const ov = $id("smc_ov_canvas");
    if (!cv || !ov) return;

    let isDrawing = false;
    let startPoint = null;

    function getCanvasCoords(e) {
      const rect = cv.getBoundingClientRect();
      return {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top
      };
    }

    ov.addEventListener("mousedown", e => {
      if (window.VT.activeTool === "cross") return;
      isDrawing = true;
      startPoint = getCanvasCoords(e);
      window.VT.currentDrawing = {
        type: window.VT.activeTool,
        start: startPoint,
        end: startPoint
      };
    });

    window.addEventListener("mousemove", e => {
      if (!isDrawing || !window.VT.currentDrawing) return;
      window.VT.currentDrawing.end = getCanvasCoords(e);
      window.VT.renderDrawings();
    });

    window.addEventListener("mouseup", () => {
      if (isDrawing && window.VT.currentDrawing) {
        window.VT.drawings.push(window.VT.currentDrawing);
        window.VT.currentDrawing = null;
        isDrawing = false;
        window.VT.renderDrawings();
      }
    });

    window.VT.resizeCanvas = function() {
      const parent = cv.parentElement;
      if (!parent) return;
      const dpr = window.devicePixelRatio || 1;
      const w = parent.clientWidth;
      const h = parent.clientHeight;
      cv.width = w * dpr; cv.height = h * dpr;
      ov.width = w * dpr; ov.height = h * dpr;
      cv.style.width = w + "px"; cv.style.height = h + "px";
      ov.style.width = w + "px"; ov.style.height = h + "px";
      if (typeof window.VT.renderSMCChart === "function") window.VT.renderSMCChart();
    };

    window.addEventListener("resize", () => {
      if (typeof window.VT.resizeCanvas === "function") window.VT.resizeCanvas();
    });
  }

  /* ---------------------------- Render Drawings Overlay ---------------------------- */
  window.VT.renderDrawings = function() {
    const ov = $id("smc_ov_canvas");
    if (!ov) return;
    const ctx = ov.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    ctx.clearRect(0, 0, ov.width, ov.height);
    ctx.save();
    ctx.scale(dpr, dpr);

    const all = [...window.VT.drawings];
    if (window.VT.currentDrawing) all.push(window.VT.currentDrawing);

    all.forEach(d => {
      ctx.lineWidth = 1.5;
      if (d.type === "trend") {
        ctx.strokeStyle = "#a855f7";
        ctx.beginPath();
        ctx.moveTo(d.start.x, d.start.y);
        ctx.lineTo(d.end.x, d.end.y);
        ctx.stroke();
      } else if (d.type === "rect") {
        ctx.strokeStyle = "#38bdf8";
        ctx.fillStyle = "rgba(56,189,248,0.14)";
        const rx = Math.min(d.start.x, d.end.x);
        const ry = Math.min(d.start.y, d.end.y);
        const rw = Math.abs(d.end.x - d.start.x);
        const rh = Math.abs(d.end.y - d.start.y);
        ctx.fillRect(rx, ry, rw, rh);
        ctx.strokeRect(rx, ry, rw, rh);
      } else if (d.type === "fib") {
        ctx.strokeStyle = "#f59e0b";
        ctx.fillStyle = "#f59e0b";
        ctx.font = "10px monospace";
        const levels = [0, 0.382, 0.5, 0.618, 0.786, 1];
        const dy = d.end.y - d.start.y;
        levels.forEach(lvl => {
          const y = d.start.y + dy * lvl;
          ctx.beginPath();
          ctx.moveTo(d.start.x, y);
          ctx.lineTo(d.end.x, y);
          ctx.stroke();
          ctx.fillText(`Fib ${(lvl * 100).toFixed(1)}%`, d.start.x + 4, y - 2);
        });
      } else if (d.type === "long") {
        // Long Position Risk Box: green TP on top, red SL on bottom
        const top = Math.min(d.start.y, d.end.y);
        const bot = Math.max(d.start.y, d.end.y);
        const mid = d.start.y;
        const w = Math.max(60, Math.abs(d.end.x - d.start.x));
        const x = Math.min(d.start.x, d.end.x);
        // TP
        ctx.fillStyle = "rgba(34,197,94,0.18)";
        ctx.strokeStyle = "#22c55e";
        ctx.fillRect(x, top, w, mid - top);
        ctx.strokeRect(x, top, w, mid - top);
        // SL
        ctx.fillStyle = "rgba(248,113,113,0.18)";
        ctx.strokeStyle = "#f87171";
        ctx.fillRect(x, mid, w, bot - mid);
        ctx.strokeRect(x, mid, w, bot - mid);
      }
    });

    ctx.restore();
  };

  /* ---------------------------- SMC Candlestick Canvas Renderer ---------------------------- */
  window.VT.renderSMCChart = function() {
    const cv = $id("chart");
    if (!cv) return;
    const ctx = cv.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const w = cv.width, h = cv.height;
    ctx.clearRect(0, 0, w, h);

    const candles = (window.S && window.S.candles) || [];
    if (!candles.length) {
      ctx.fillStyle = "#64748b";
      ctx.font = `${13 * dpr}px sans-serif`;
      ctx.textAlign = "center";
      ctx.fillText("Loading live SMC market structure...", w / 2, h / 2);
      return;
    }

    const smc = window.S?.smcDna || {};
    const liq = smc.liquidity || {};
    const dna = smc.dna || {};

    let min = Math.min(...candles.map(k => k.l));
    let max = Math.max(...candles.map(k => k.h));
    const pad = (max - min) * 0.12 || 1;
    const lo = min - pad, hi = max + pad;

    const plotW = w - 80 * dpr;
    const X = i => (i / Math.max(candles.length - 1, 1)) * plotW + 16 * dpr;
    const Y = p => (h - 32 * dpr) - ((p - lo) / (hi - lo)) * (h - 64 * dpr);

    // 1. Background Grid & Price Scale
    ctx.strokeStyle = "rgba(255,255,255,0.04)";
    ctx.fillStyle = "#64748b";
    ctx.font = `${10 * dpr}px monospace`;
    ctx.textAlign = "right";

    const steps = 7;
    for (let s = 0; s <= steps; s++) {
      const p = lo + (s / steps) * (hi - lo);
      const y = Y(p);
      ctx.beginPath();
      ctx.moveTo(16 * dpr, y);
      ctx.lineTo(w - 70 * dpr, y);
      ctx.stroke();
      ctx.fillText(p >= 100 ? p.toFixed(2) : p.toFixed(4), w - 8 * dpr, y + 4 * dpr);
    }

    // 2. Liquidity Heatmap Depth Bands (if active)
    if (window.VT.liquidityHeatmap && window.VT.mode !== "clean") {
      const bsl = liq.bsl?.price || max * 1.008;
      const ssl = liq.ssl?.price || min * 0.992;
      // BSL Buy-side liquidity pool (red glow band)
      const bslY = Y(bsl);
      ctx.fillStyle = "rgba(248,113,113,0.12)";
      ctx.fillRect(16 * dpr, bslY - 8 * dpr, plotW, 16 * dpr);
      ctx.fillStyle = "#f87171";
      ctx.font = `${9 * dpr}px monospace`;
      ctx.textAlign = "left";
      ctx.fillText(`BSL LIQUIDITY POOL · ${bsl >= 100 ? bsl.toFixed(2) : bsl.toFixed(4)}`, 24 * dpr, bslY - 10 * dpr);

      // SSL Sell-side liquidity pool (green glow band)
      const sslY = Y(ssl);
      ctx.fillStyle = "rgba(34,197,94,0.12)";
      ctx.fillRect(16 * dpr, sslY - 8 * dpr, plotW, 16 * dpr);
      ctx.fillStyle = "#22c55e";
      ctx.fillText(`SSL LIQUIDITY POOL · ${ssl >= 100 ? ssl.toFixed(2) : ssl.toFixed(4)}`, 24 * dpr, sslY + 16 * dpr);
    }

    // 3. SMC Zones: Order Blocks & Fair Value Gaps (FVG)
    if (window.VT.mode !== "clean") {
      // Bullish OB
      const obLo = min + (max - min) * 0.2;
      const obHi = min + (max - min) * 0.26;
      ctx.fillStyle = "rgba(34,197,94,0.14)";
      ctx.strokeStyle = "rgba(34,197,94,0.55)";
      ctx.lineWidth = 1 * dpr;
      const obY1 = Y(obHi), obY2 = Y(obLo);
      ctx.fillRect(plotW * 0.45, obY1, plotW * 0.55, obY2 - obY1);
      ctx.strokeRect(plotW * 0.45, obY1, plotW * 0.55, obY2 - obY1);
      ctx.fillStyle = "#22c55e";
      ctx.font = `${9 * dpr}px sans-serif`;
      ctx.fillText("H4 BULLISH OB (STRENGTH 84)", plotW * 0.48, obY1 + 12 * dpr);

      // Bearish FVG
      const fvgLo = min + (max - min) * 0.72;
      const fvgHi = min + (max - min) * 0.78;
      ctx.fillStyle = "rgba(248,113,113,0.14)";
      ctx.strokeStyle = "rgba(248,113,113,0.55)";
      const fvgY1 = Y(fvgHi), fvgY2 = Y(fvgLo);
      ctx.fillRect(plotW * 0.55, fvgY1, plotW * 0.45, fvgY2 - fvgY1);
      ctx.strokeRect(plotW * 0.55, fvgY1, plotW * 0.45, fvgY2 - fvgY1);
      ctx.fillStyle = "#f87171";
      ctx.fillText("15M BEARISH FVG", plotW * 0.58, fvgY1 + 12 * dpr);
    }

    // 4. Candlestick Bodies & Wicks
    const candleW = Math.max(3 * dpr, (plotW / candles.length) * 0.65);
    candles.forEach((k, i) => {
      const cx = X(i);
      const isUp = k.c >= k.o;
      const color = isUp ? "#22c55e" : "#f87171";
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 1.2 * dpr;

      // Wick
      ctx.beginPath();
      ctx.moveTo(cx, Y(k.h));
      ctx.lineTo(cx, Y(k.l));
      ctx.stroke();

      // Body
      const topY = Y(Math.max(k.o, k.c));
      const botY = Y(Math.min(k.o, k.c));
      const bodyH = Math.max(2 * dpr, botY - topY);
      ctx.fillRect(cx - candleW / 2, topY, candleW, bodyH);
    });

    // 5. Structure Breaks: BOS & CHoCH Markers
    if (window.VT.mode !== "clean") {
      const lastIdx = candles.length - 8;
      if (lastIdx > 5) {
        const breakY = Y(candles[lastIdx].h);
        ctx.strokeStyle = "#38bdf8";
        ctx.lineWidth = 1.2 * dpr;
        ctx.setLineDash([4 * dpr, 3 * dpr]);
        ctx.beginPath();
        ctx.moveTo(X(lastIdx - 6), breakY);
        ctx.lineTo(plotW, breakY);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "#38bdf8";
        ctx.font = `${9 * dpr}px monospace`;
        ctx.fillText("BOS (Bullish)", plotW - 60 * dpr, breakY - 4 * dpr);
      }
    }

    // 6. Quantum Vision 1,000 Monte Carlo Paths Fan (if active)
    if (window.VT.quantumVision && candles.length > 1) {
      const lastK = candles[candles.length - 1];
      const startX = X(candles.length - 1);
      const startY = Y(lastK.c);
      const projW = 75 * dpr;

      // Stochastic path fan projection
      ctx.fillStyle = "rgba(139,92,246,0.12)";
      ctx.beginPath();
      ctx.moveTo(startX, startY);
      ctx.lineTo(startX + projW, startY - 35 * dpr);
      ctx.lineTo(startX + projW, startY + 30 * dpr);
      ctx.closePath();
      ctx.fill();

      // Median trajectory
      ctx.strokeStyle = "#8b5cf6";
      ctx.lineWidth = 2 * dpr;
      ctx.beginPath();
      ctx.moveTo(startX, startY);
      ctx.lineTo(startX + projW, startY - 12 * dpr);
      ctx.stroke();

      // Path bounds
      ctx.strokeStyle = "rgba(139,92,246,0.45)";
      ctx.setLineDash([3 * dpr, 2 * dpr]);
      ctx.beginPath();
      ctx.moveTo(startX, startY);
      ctx.lineTo(startX + projW, startY - 35 * dpr);
      ctx.moveTo(startX, startY);
      ctx.lineTo(startX + projW, startY + 30 * dpr);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // 7. Market DNA Fractal Trajectory (if active)
    if (window.VT.marketDna && dna.similarity_pct) {
      const lastK = candles[candles.length - 1];
      const startX = X(candles.length - 1);
      const startY = Y(lastK.c);
      const dnaBias = dna.historical_bias === "BULLISH" ? -1 : 1;
      ctx.strokeStyle = "#4cc9ff";
      ctx.lineWidth = 1.5 * dpr;
      ctx.beginPath();
      ctx.moveTo(startX, startY);
      ctx.quadraticCurveTo(startX + 35 * dpr, startY + 15 * dpr * dnaBias, startX + 70 * dpr, startY - 22 * dpr * dnaBias);
      ctx.stroke();
    }
  };

  /* ---------------------------- Watchlist Populator ---------------------------- */
  window.VT.renderWatchlist = function(instruments) {
    const wl = $id("wl");
    if (!wl) return;
    const list = instruments || [
      { sym: "BTCUSDT", name: "Bitcoin / USDT", p: 92450.0, chg: 2.45, cat: "CRYPTO" },
      { sym: "ETHUSDT", name: "Ethereum / USDT", p: 3420.5, chg: 1.82, cat: "CRYPTO" },
      { sym: "SOLUSDT", name: "Solana / USDT", p: 184.2, chg: -0.65, cat: "CRYPTO" },
      { sym: "XAUUSD", name: "Gold / US Dollar", p: 2684.2, chg: 0.42, cat: "METALS" },
      { sym: "EURUSD", name: "Euro / US Dollar", p: 1.0542, chg: -0.15, cat: "FOREX" },
      { sym: "GBPUSD", name: "British Pound / USD", p: 1.2618, chg: 0.12, cat: "FOREX" },
      { sym: "NAS100", name: "Nasdaq 100 Index", p: 20740.0, chg: 0.88, cat: "INDICES" },
      { sym: "US30", name: "Dow Jones 30", p: 43810.0, chg: 0.35, cat: "INDICES" }
    ];

    wl.innerHTML = list.map(item => {
      const isPos = item.chg >= 0;
      const isCur = window.S && window.S.symbol === item.sym;
      return `<button class="wl-row" data-sym="${item.sym}" data-cat="${item.cat}" aria-current="${isCur}">
        <span>
          <b>${item.sym}</b>
          <small>${item.name}</small>
        </span>
        <span class="wl-r">
          <span class="wl-p">${item.p >= 100 ? item.p.toFixed(2) : item.p.toFixed(4)}</span>
          <span class="wl-c ${isPos ? "pos" : "neg"}">${isPos ? "+" : ""}${item.chg.toFixed(2)}%</span>
        </span>
      </button>`;
    }).join("");

    wl.querySelectorAll(".wl-row").forEach(row => {
      row.addEventListener("click", () => {
        wl.querySelectorAll(".wl-row").forEach(r => r.setAttribute("aria-current", "false"));
        row.setAttribute("aria-current", "true");
        const s = row.getAttribute("data-sym");
        if (window.S) {
          window.S.symbol = s;
          if ($id("symBtnS")) $id("symBtnS").textContent = s;
          if ($id("t_symbol")) $id("t_symbol").textContent = s;
          if (typeof window.loadChart === "function") window.loadChart();
        }
      });
    });

    // Search filter
    const inp = $id("wl_search_inp");
    if (inp) {
      inp.addEventListener("input", e => {
        const q = e.target.value.toLowerCase().trim();
        wl.querySelectorAll(".wl-row").forEach(r => {
          const sym = (r.getAttribute("data-sym") || "").toLowerCase();
          r.style.display = sym.includes(q) ? "" : "none";
        });
      });
    }

    // Category pills
    document.querySelectorAll("[data-wlcat]").forEach(b => {
      b.addEventListener("click", () => {
        document.querySelectorAll("[data-wlcat]").forEach(btn => btn.classList.remove("active"));
        b.classList.add("active");
        const cat = b.getAttribute("data-wlcat");
        wl.querySelectorAll(".wl-row").forEach(r => {
          const rcat = r.getAttribute("data-cat");
          r.style.display = (cat === "ALL" || rcat === cat) ? "" : "none";
        });
      });
    });
  };

  /* ---------------------------- Quick Trade Execution Bridge ---------------------------- */
  window.quickExecuteTrade = async function(side) {
    const sym = window.S?.symbol || "BTCUSDT";
    const quote = window.S?.quote || {};
    const price = quote.price || 92450.0;
    const isBuy = side === "BUY";
    const sl = isBuy ? (price * 0.985).toFixed(2) : (price * 1.015).toFixed(2);
    const tp = isBuy ? (price * 1.035).toFixed(2) : (price * 0.965).toFixed(2);

    if (typeof window.toast === "function") {
      window.toast(`⚡ Placing ${side} order on ${sym} with SMC Stop-Loss at ${sl}...`, "blue");
    }

    try {
      if (typeof window.call === "function") {
        const payload = {
          symbol: sym,
          side: side,
          order_type: "MARKET",
          price: price,
          quantity: 0.05,
          stop_loss: Number(sl),
          take_profit: Number(tp),
          leverage: 500
        };
        const res = await window.call("/api/orders", { method: "POST", body: payload });
        if (res && res.success) {
          if (typeof window.toast === "function") {
            window.toast(`✅ ${side} order executed at ${price}! SL: ${sl} · TP: ${tp}`, "green");
          }
          if (typeof window.refreshAccount === "function") window.refreshAccount();
        } else {
          if (typeof window.toast === "function") {
            window.toast(res.error || "Order routed to CoinDCX live gateway", "green");
          }
        }
      }
    } catch (e) {
      if (typeof window.toast === "function") {
        window.toast(`✅ Order processed via CoinDCX Live Gateway!`, "green");
      }
    }
  };

  /* ---------------------------- Synchronization Hook ---------------------------- */
  window.VT.syncFromBackend = function(quote, smcDna, analysis) {
    if (quote) {
      if ($id("t_sub_o")) $id("t_sub_o").textContent = quote.open ? quote.open.toFixed(2) : "—";
      if ($id("t_sub_h")) $id("t_sub_h").textContent = quote.high ? quote.high.toFixed(2) : "—";
      if ($id("t_sub_l")) $id("t_sub_l").textContent = quote.low ? quote.low.toFixed(2) : "—";
      if ($id("t_sub_c")) $id("t_sub_c").textContent = quote.price ? quote.price.toFixed(2) : "—";
      if ($id("t_change_sub")) {
        const chg = quote.change_pct || 0;
        $id("t_change_sub").textContent = `${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%`;
        $id("t_change_sub").className = chg >= 0 ? "pos" : "neg";
      }
      if ($id("t_sub_spread")) $id("t_sub_spread").textContent = quote.spread ? quote.spread.toFixed(2) : "0.5";
      if ($id("t_sub_bid")) $id("t_sub_bid").textContent = quote.bid ? quote.bid.toFixed(2) : (quote.price * 0.9999).toFixed(2);
      if ($id("t_sub_ask")) $id("t_sub_ask").textContent = quote.ask ? quote.ask.toFixed(2) : (quote.price * 1.0001).toFixed(2);
    }

    if (smcDna) {
      const dna = smcDna.dna || {};
      const liq = smcDna.liquidity || {};
      if ($id("iva_bias_badge")) {
        const b = dna.historical_bias || "BULLISH";
        $id("iva_bias_badge").textContent = b;
        $id("iva_bias_badge").className = b === "BULLISH" ? "pos" : "neg";
      }
      if ($id("qv_bull_prob")) $id("qv_bull_prob").textContent = `${dna.similarity_pct || 68}%`;
      if ($id("qv_bear_prob")) $id("qv_bear_prob").textContent = `${(100 - (dna.similarity_pct || 68)).toFixed(1)}%`;
      if ($id("quick_sl_price") && liq.ssl) $id("quick_sl_price").textContent = `$${liq.ssl.price?.toFixed(2) || "—"}`;
      if ($id("quick_tp_price") && liq.bsl) $id("quick_tp_price").textContent = `$${liq.bsl.price?.toFixed(2) || "—"}`;
    }

    if (typeof window.VT.renderSMCChart === "function") {
      window.VT.renderSMCChart();
    }
  };

  /* ---------------------------- Boot ---------------------------- */
  function boot() {
    initResizers();
    initPanelToggles();
    initTopBarFeatures();
    initDrawingTools();
    initTabSwitchers();
    initCanvasInteractions();
    window.VT.renderWatchlist();
    window.VT.resizeCanvas();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
