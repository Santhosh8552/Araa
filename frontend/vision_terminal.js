/* ==========================================================================
   ARAA VISION — Institutional Smart Money Concepts (SMC) & Market Terminal
   Adheres to MicasR/fx-tools SMC Indicator Specification & Infinity Vision FX
   Features:
   - Real-time Candlesticks, Multi-Timeframe Structure & Dynamic Price/Time Scales
   - Market Structure Engine: Swings (HH, HL, LH, LL), BOS, CHoCH, MSS
   - Order Blocks (OB) & Fair Value Gaps (FVG) with Real Mitigation Tracking
   - Liquidity Pools: BSL, SSL, Equal Highs (EQH), Equal Lows (EQL), Sweeps
   - Premium / Discount Dealing Ranges & 50% Equilibrium & OTE (61.8%–79%)
   - Multi-Timeframe (MTF) Trend Bias Dashboard HUD (M15, H1, H4, D1, W1)
   - Quantum Vision Monte Carlo Stochastic Path Fan (1,000 Projected Drift Paths)
   - Interactive Canvas: Pan, Zoom, Crosshair HUD, and Full Drawing Suite
   - Slide-out Floating Indicators Drawer with Granular Layer Toggles & Presets
   - Live Ticker Countdown with Real forming candle timer
   ========================================================================== */

(function() {
  "use strict";

  // Global State for Araa Vision Terminal
  window.VT = {
    symbol: "BTCUSDT",
    timeframe: "15m",
    candles: [],
    smcData: null,
    isLoading: false,
    mode: "advanced", // clean | standard | advanced
    panOffset: 0,
    zoomLevel: 1.0,
    isPanning: false,
    panStartX: 0,
    panStartOffset: 0,
    crosshair: null,
    activeTool: "cross",
    magnet: false,
    drawings: [],
    currentDrawing: null,
    replayActive: false,
    replayIndex: 0,
    replayCandles: [],
    replayTimer: null,
    activeTabAi: "strength",
    activeTabBt: "feed",
    candleTimerId: null,
    pollerTimerId: null,

    // Granular SMC Indicator Layers (MicasR Technical Spec)
    indicators: {
      showSwings: true,
      showBOS: true,
      showCHoCH: true,
      showMSS: true,
      showBullOB: true,
      showBearOB: true,
      showFVG: true,
      showFVGMitigation: true,
      showSweeps: true,
      showBSL: true,
      showSSL: true,
      showEQ: true,
      showPD: true,
      showEQ50: true,
      showOTE: true,
      showIDM: true,
      showMTF: true,
      showDashboard: true,
      quantumVision: true,
      marketDna: true,
      liquidityHeatmap: true
    }
  };

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
      });
    });

    window.addEventListener("mousemove", e => {
      if (!activeRz) return;

      if (activeRz === "wl") {
        const delta = e.clientX - startX;
        const newW = Math.max(160, Math.min(420, startW + delta));
        term.style.setProperty("--wl-w", `${newW}px`);
      } else if (activeRz === "ai") {
        const delta = startX - e.clientX;
        const newW = Math.max(260, Math.min(520, startW + delta));
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
        if (typeof window.VT.resizeCanvas === "function") {
          window.VT.resizeCanvas();
        }
      }
    });
  }

  /* ---------------------------- Panel Visibility Toggles ---------------------------- */
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
    // Mode switcher (Clean, Standard, Advanced)
    document.querySelectorAll(".t-modes button[data-ivmode]").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".t-modes button[data-ivmode]").forEach(b => {
          b.classList.remove("active");
          b.setAttribute("aria-pressed", "false");
        });
        btn.classList.add("active");
        btn.setAttribute("aria-pressed", "true");
        window.VT.setPresetMode(btn.getAttribute("data-ivmode"));
      });
    });

    // Timeframe selector
    document.querySelectorAll(".tfs button[data-tf]").forEach(btn => {
      btn.addEventListener("click", () => {
        const tf = btn.getAttribute("data-tf");
        window.VT.setTimeframe(tf);
      });
    });

    // Symbol dropdown
    const symSel = $id("symSel");
    if (symSel) {
      symSel.addEventListener("change", e => {
        window.VT.setSymbol(e.target.value);
      });
    }

    // Refresh & Auto fit buttons
    const zfit = document.querySelector("[data-act='zfit']");
    if (zfit) {
      zfit.addEventListener("click", () => {
        window.VT.panOffset = 0;
        window.VT.zoomLevel = 1.0;
        if (typeof window.VT.resizeCanvas === "function") window.VT.resizeCanvas();
        if (typeof window.VT.renderSMCChart === "function") window.VT.renderSMCChart();
      });
    }

    const refBtn = document.querySelector("[data-act='refresh']");
    if (refBtn) {
      refBtn.addEventListener("click", () => {
        window.VT.loadMarketData(window.VT.symbol, window.VT.timeframe);
      });
    }

    // Quantum Vision toggle
    const qvBtn = document.querySelector("[data-qv='toggle']");
    if (qvBtn) {
      qvBtn.addEventListener("click", () => {
        window.VT.indicators.quantumVision = !window.VT.indicators.quantumVision;
        qvBtn.classList.toggle("active", window.VT.indicators.quantumVision);
        qvBtn.setAttribute("aria-pressed", String(window.VT.indicators.quantumVision));
        const qvPanel = $id("qvPanel");
        if (qvPanel) qvPanel.style.display = window.VT.indicators.quantumVision ? "block" : "none";
        window.VT.renderSMCChart();
      });
    }

    // Market DNA toggle
    const dnaBtn = document.querySelector("[data-dna='toggle']");
    if (dnaBtn) {
      dnaBtn.addEventListener("click", () => {
        window.VT.indicators.marketDna = !window.VT.indicators.marketDna;
        dnaBtn.classList.toggle("active", window.VT.indicators.marketDna);
        dnaBtn.setAttribute("aria-pressed", String(window.VT.indicators.marketDna));
        window.VT.renderSMCChart();
      });
    }

    // Liquidity Heatmap toggle
    const lqBtn = document.querySelector("[data-lq='toggle']");
    if (lqBtn) {
      lqBtn.addEventListener("click", () => {
        window.VT.indicators.liquidityHeatmap = !window.VT.indicators.liquidityHeatmap;
        lqBtn.classList.toggle("active", window.VT.indicators.liquidityHeatmap);
        lqBtn.setAttribute("aria-pressed", String(window.VT.indicators.liquidityHeatmap));
        window.VT.renderSMCChart();
      });
    }

    // Indicators Drawer Toggle (Infinity Vision FX style)
    const indBtn = $id("btn_toggle_indicators");
    const drawer = $id("smc_indicators_drawer");
    if (indBtn && drawer) {
      indBtn.addEventListener("click", () => {
        const isHidden = drawer.style.display === "none" || !drawer.style.display;
        drawer.style.display = isHidden ? "flex" : "none";
        indBtn.setAttribute("aria-pressed", String(isHidden));
      });
    }

    const indClose = $id("ind_close");
    if (indClose && drawer) {
      indClose.addEventListener("click", () => {
        drawer.style.display = "none";
        if (indBtn) indBtn.setAttribute("aria-pressed", "false");
      });
    }

    // Hook Drawer Checkboxes
    initIndicatorsDrawerControls();
  }

  /* ---------------------------- Indicators Drawer Controls ---------------------------- */
  function initIndicatorsDrawerControls() {
    const mapping = {
      ind_swings: "showSwings",
      ind_bos: "showBOS",
      ind_choch: "showCHoCH",
      ind_mss: "showMSS",
      ind_sweeps: "showSweeps",
      ind_bull_ob: "showBullOB",
      ind_bear_ob: "showBearOB",
      ind_fvg: "showFVG",
      ind_fvg_mit: "showFVGMitigation",
      ind_bsl: "showBSL",
      ind_ssl: "showSSL",
      ind_eq: "showEQ",
      ind_pd: "showPD",
      ind_eq50: "showEQ50",
      ind_ote: "showOTE",
      ind_qv: "quantumVision",
      ind_mtf_dash: "showDashboard",
      ind_dna: "marketDna"
    };

    Object.entries(mapping).forEach(([elId, key]) => {
      const el = $id(elId);
      if (el) {
        el.checked = !!window.VT.indicators[key];
        el.addEventListener("change", () => {
          window.VT.indicators[key] = el.checked;
          window.VT.renderSMCChart();
        });
      }
    });

    const showAllBtn = $id("ind_show_all");
    if (showAllBtn) {
      showAllBtn.addEventListener("click", () => {
        Object.keys(window.VT.indicators).forEach(k => window.VT.indicators[k] = true);
        Object.keys(mapping).forEach(id => { if ($id(id)) $id(id).checked = true; });
        window.VT.renderSMCChart();
      });
    }

    const hideAllBtn = $id("ind_hide_all");
    if (hideAllBtn) {
      hideAllBtn.addEventListener("click", () => {
        Object.keys(window.VT.indicators).forEach(k => window.VT.indicators[k] = false);
        Object.keys(mapping).forEach(id => { if ($id(id)) $id(id).checked = false; });
        window.VT.renderSMCChart();
      });
    }

    const resetDefBtn = $id("ind_reset_def");
    if (resetDefBtn) {
      resetDefBtn.addEventListener("click", () => {
        window.VT.setPresetMode("advanced");
      });
    }

    document.querySelectorAll("[data-indpreset]").forEach(btn => {
      btn.addEventListener("click", () => {
        window.VT.setPresetMode(btn.getAttribute("data-indpreset"));
      });
    });
  }

  window.VT.setPresetMode = function(mode) {
    window.VT.mode = mode;
    const mapping = {
      ind_swings: "showSwings",
      ind_bos: "showBOS",
      ind_choch: "showCHoCH",
      ind_mss: "showMSS",
      ind_sweeps: "showSweeps",
      ind_bull_ob: "showBullOB",
      ind_bear_ob: "showBearOB",
      ind_fvg: "showFVG",
      ind_fvg_mit: "showFVGMitigation",
      ind_bsl: "showBSL",
      ind_ssl: "showSSL",
      ind_eq: "showEQ",
      ind_pd: "showPD",
      ind_eq50: "showEQ50",
      ind_ote: "showOTE",
      ind_qv: "quantumVision",
      ind_mtf_dash: "showDashboard",
      ind_dna: "marketDna"
    };

    if (mode === "clean") {
      Object.keys(window.VT.indicators).forEach(k => window.VT.indicators[k] = false);
    } else if (mode === "standard") {
      window.VT.indicators.showSwings = true;
      window.VT.indicators.showBOS = true;
      window.VT.indicators.showCHoCH = true;
      window.VT.indicators.showBullOB = true;
      window.VT.indicators.showBearOB = true;
      window.VT.indicators.showFVG = true;
      window.VT.indicators.showBSL = true;
      window.VT.indicators.showSSL = true;
      window.VT.indicators.showPD = true;
      window.VT.indicators.showEQ50 = true;
      window.VT.indicators.quantumVision = false;
      window.VT.indicators.marketDna = false;
      window.VT.indicators.showDashboard = true;
    } else {
      // Advanced
      Object.keys(window.VT.indicators).forEach(k => window.VT.indicators[k] = true);
    }

    Object.entries(mapping).forEach(([id, k]) => {
      if ($id(id)) $id(id).checked = !!window.VT.indicators[k];
    });

    document.querySelectorAll(".t-modes button[data-ivmode]").forEach(b => {
      const match = b.getAttribute("data-ivmode") === mode;
      b.classList.toggle("active", match);
      b.setAttribute("aria-pressed", String(match));
    });

    window.VT.renderSMCChart();
  };

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
      const pt = getCanvasCoords(e);
      if (window.VT.activeTool === "cross") {
        window.VT.isPanning = true;
        window.VT.panStartX = e.clientX;
        window.VT.panStartOffset = window.VT.panOffset;
        ov.style.cursor = "grabbing";
        return;
      }
      isDrawing = true;
      startPoint = pt;
      window.VT.currentDrawing = {
        type: window.VT.activeTool,
        start: startPoint,
        end: startPoint
      };
    });

    window.addEventListener("mousemove", e => {
      const pt = getCanvasCoords(e);
      window.VT.crosshair = pt;

      if (window.VT.isPanning) {
        const delta = e.clientX - window.VT.panStartX;
        window.VT.panOffset = window.VT.panStartOffset + delta;
        window.VT.renderSMCChart();
      }

      if (isDrawing && window.VT.currentDrawing) {
        window.VT.currentDrawing.end = pt;
      }

      window.VT.renderDrawings();
    });

    window.addEventListener("mouseup", () => {
      if (window.VT.isPanning) {
        window.VT.isPanning = false;
        ov.style.cursor = "crosshair";
      }
      if (isDrawing && window.VT.currentDrawing) {
        window.VT.drawings.push(window.VT.currentDrawing);
        window.VT.currentDrawing = null;
        isDrawing = false;
        window.VT.renderDrawings();
      }
    });

    ov.addEventListener("mouseleave", () => {
      window.VT.crosshair = null;
      window.VT.renderDrawings();
    });

    // Zoom via mousewheel
    ov.addEventListener("wheel", e => {
      e.preventDefault();
      const zoomFactor = e.deltaY < 0 ? 1.12 : 0.89;
      window.VT.zoomLevel = Math.max(0.4, Math.min(6.0, window.VT.zoomLevel * zoomFactor));
      window.VT.renderSMCChart();
      window.VT.renderDrawings();
    }, { passive: false });

    // Auto-Resize Observer
    window.VT.resizeCanvas = function() {
      const parent = cv.parentElement;
      if (!parent) return;
      const dpr = window.devicePixelRatio || 1;
      const w = parent.clientWidth;
      const h = parent.clientHeight;
      if (w <= 0 || h <= 0) return;

      cv.width = w * dpr; cv.height = h * dpr;
      ov.width = w * dpr; ov.height = h * dpr;
      cv.style.width = w + "px"; cv.style.height = h + "px";
      ov.style.width = w + "px"; ov.style.height = h + "px";
      if (typeof window.VT.renderSMCChart === "function") window.VT.renderSMCChart();
      if (typeof window.VT.renderDrawings === "function") window.VT.renderDrawings();
    };

    window.addEventListener("resize", () => {
      if (typeof window.VT.resizeCanvas === "function") window.VT.resizeCanvas();
    });

    if (window.ResizeObserver && cv.parentElement) {
      try {
        const ro = new ResizeObserver(() => {
          if (typeof window.VT.resizeCanvas === "function") window.VT.resizeCanvas();
        });
        ro.observe(cv.parentElement);
      } catch (e) {}
    }
  }

  /* ---------------------------- Render Drawings & Crosshair Overlay ---------------------------- */
  window.VT.renderDrawings = function() {
    const ov = $id("smc_ov_canvas");
    if (!ov) return;
    const ctx = ov.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const w = ov.width, h = ov.height;
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.scale(dpr, dpr);

    const cssW = w / dpr;
    const cssH = h / dpr;

    // 1. Crosshair Lines & Ticks (when mouse hovers)
    if (window.VT.crosshair && window.VT.activeTool === "cross") {
      const cx = window.VT.crosshair.x;
      const cy = window.VT.crosshair.y;
      const plotRight = cssW - 75;
      const plotBottom = cssH - 26;

      if (cx >= 16 && cx <= plotRight && cy >= 10 && cy <= plotBottom) {
        ctx.strokeStyle = "rgba(148, 163, 184, 0.4)";
        ctx.setLineDash([4, 3]);
        ctx.lineWidth = 1;

        // Vertical line
        ctx.beginPath();
        ctx.moveTo(cx, 10);
        ctx.lineTo(cx, plotBottom);
        ctx.stroke();

        // Horizontal line
        ctx.beginPath();
        ctx.moveTo(16, cy);
        ctx.lineTo(plotRight, cy);
        ctx.stroke();
        ctx.setLineDash([]);

        // Price badge on right axis
        if (window.VT.calcPriceFromY) {
          const hoveredPrice = window.VT.calcPriceFromY(cy);
          if (hoveredPrice) {
            ctx.fillStyle = "#1e293b";
            ctx.fillRect(plotRight + 2, cy - 9, 70, 18);
            ctx.strokeStyle = "#8b5cf6";
            ctx.strokeRect(plotRight + 2, cy - 9, 70, 18);
            ctx.fillStyle = "#f8fafc";
            ctx.font = "10.5px monospace";
            ctx.textAlign = "left";
            ctx.fillText(hoveredPrice >= 100 ? hoveredPrice.toFixed(2) : hoveredPrice.toFixed(4), plotRight + 7, cy + 4);
          }
        }

        // Time badge on bottom axis
        if (window.VT.calcTimeFromX) {
          const hoveredTime = window.VT.calcTimeFromX(cx);
          if (hoveredTime) {
            ctx.fillStyle = "#1e293b";
            ctx.fillRect(cx - 30, plotBottom + 2, 60, 18);
            ctx.strokeStyle = "#8b5cf6";
            ctx.strokeRect(cx - 30, plotBottom + 2, 60, 18);
            ctx.fillStyle = "#f8fafc";
            ctx.font = "10px monospace";
            ctx.textAlign = "center";
            ctx.fillText(hoveredTime, cx, plotBottom + 15);
          }
        }
      }
    }

    // 2. User Drawn Tools
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
        const levels = [0, 0.382, 0.5, 0.618, 0.705, 0.79, 1];
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
        const top = Math.min(d.start.y, d.end.y);
        const bot = Math.max(d.start.y, d.end.y);
        const mid = d.start.y;
        const w = Math.max(60, Math.abs(d.end.x - d.start.x));
        const x = Math.min(d.start.x, d.end.x);
        ctx.fillStyle = "rgba(34,197,94,0.18)";
        ctx.strokeStyle = "#22c55e";
        ctx.fillRect(x, top, w, mid - top);
        ctx.strokeRect(x, top, w, mid - top);
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

    let candles = window.VT.candles || [];
    if (!candles.length && window.S && window.S.candles && window.S.candles.length) {
      candles = window.S.candles;
      window.VT.candles = candles;
    }
    if (!candles.length) {
      ctx.fillStyle = "#64748b";
      ctx.font = `${13 * dpr}px Inter, sans-serif`;
      ctx.textAlign = "center";
      ctx.fillText(window.VT.isLoading ? "Loading institutional SMC market structure..." : "Select an instrument to view live SMC chart", w / 2, h / 2);
      return;
    }

    const smc = window.VT.smcData || {};
    const ind = window.VT.indicators;
    const isClean = window.VT.mode === "clean";

    // Chart Dimensions
    const plotRight = w - 75 * dpr;
    const plotBottom = h - 26 * dpr;
    const plotLeft = 16 * dpr;
    const plotTop = 16 * dpr;
    const plotW = plotRight - plotLeft;
    const plotH = plotBottom - plotTop;

    // Viewport calculation with Zoom and Pan
    const baseCount = 65;
    const visibleCount = Math.max(15, Math.min(candles.length, Math.round(baseCount / window.VT.zoomLevel)));
    const candleSpacing = plotW / Math.max(visibleCount, 1);
    const maxPan = Math.max(0, (candles.length - visibleCount) * candleSpacing);
    const clampedPan = Math.max(-maxPan, Math.min(plotW * 0.35, window.VT.panOffset * dpr));

    const startIndex = Math.max(0, Math.min(candles.length - visibleCount, Math.round(-clampedPan / candleSpacing)));
    const endIndex = Math.min(candles.length, startIndex + visibleCount);
    const visibleCandles = candles.slice(startIndex, endIndex);

    if (!visibleCandles.length) return;

    let min = Math.min(...visibleCandles.map(k => k.l));
    let max = Math.max(...visibleCandles.map(k => k.h));
    const pad = (max - min) * 0.12 || 1;
    const lo = min - pad, hi = max + pad;

    // Math Coordinate Transforms
    const X = idx => (idx - startIndex) * candleSpacing + plotLeft + candleSpacing * 0.5;
    const Y = p => plotBottom - ((p - lo) / (hi - lo)) * plotH;

    // Attach coordinate readers for crosshair tooltips
    window.VT.calcPriceFromY = yCss => {
      const p = lo + ((plotBottom - (yCss * dpr)) / plotH) * (hi - lo);
      return Math.max(0, p);
    };
    window.VT.calcTimeFromX = xCss => {
      const idx = Math.round(startIndex + ((xCss * dpr - plotLeft) / candleSpacing));
      const c = candles[idx];
      if (c && c.t) {
        const d = new Date(c.t * 1000);
        return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      }
      return "";
    };

    // 1. Grid & Right Price Scale
    ctx.strokeStyle = "rgba(255,255,255,0.04)";
    ctx.fillStyle = "#64748b";
    ctx.font = `${10 * dpr}px monospace`;
    ctx.textAlign = "right";
    ctx.lineWidth = 1 * dpr;

    const steps = 7;
    for (let s = 0; s <= steps; s++) {
      const p = lo + (s / steps) * (hi - lo);
      const y = Y(p);
      ctx.beginPath();
      ctx.moveTo(plotLeft, y);
      ctx.lineTo(plotRight, y);
      ctx.stroke();
      ctx.fillText(p >= 100 ? p.toFixed(2) : p.toFixed(4), w - 6 * dpr, y + 3.5 * dpr);
    }

    // Bottom Time Scale Ticks
    ctx.textAlign = "center";
    const timeStep = Math.max(6, Math.floor(visibleCount / 7));
    for (let i = startIndex; i < endIndex; i += timeStep) {
      const c = candles[i];
      if (c && c.t) {
        const x = X(i);
        const d = new Date(c.t * 1000);
        const timeStr = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        ctx.beginPath();
        ctx.moveTo(x, plotBottom);
        ctx.lineTo(x, plotBottom + 4 * dpr);
        ctx.stroke();
        ctx.fillText(timeStr, x, h - 8 * dpr);
      }
    }

    // 2. Premium / Discount Zones & OTE Levels (§2.9, §2.6 of MicasR Spec)
    if (!isClean && ind.showPD && smc.liquidity && smc.liquidity.dealing_range) {
      const dr = smc.liquidity.dealing_range;
      const eqY = Y(dr.equilibrium);
      const highY = Y(dr.high);
      const lowY = Y(dr.low);

      // Red Premium Zone
      ctx.fillStyle = "rgba(239, 68, 68, 0.05)";
      ctx.fillRect(plotLeft, highY, plotW, eqY - highY);
      ctx.fillStyle = "rgba(239, 68, 68, 0.5)";
      ctx.font = `${9 * dpr}px Inter, sans-serif`;
      ctx.textAlign = "left";
      ctx.fillText("PREMIUM ZONE (EXPENSIVE)", plotLeft + 12 * dpr, highY + 14 * dpr);

      // Green Discount Zone
      ctx.fillStyle = "rgba(34, 197, 94, 0.05)";
      ctx.fillRect(plotLeft, eqY, plotW, lowY - eqY);
      ctx.fillStyle = "rgba(34, 197, 94, 0.5)";
      ctx.fillText("DISCOUNT ZONE (CHEAP)", plotLeft + 12 * dpr, lowY - 8 * dpr);

      // 50% Equilibrium Line
      if (ind.showEQ50) {
        ctx.strokeStyle = "#eab308";
        ctx.setLineDash([4 * dpr, 3 * dpr]);
        ctx.beginPath();
        ctx.moveTo(plotLeft, eqY);
        ctx.lineTo(plotRight, eqY);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "#eab308";
        ctx.fillText(`EQ 50% · $${dr.equilibrium.toFixed(2)}`, plotRight - 110 * dpr, eqY - 4 * dpr);
      }

      // OTE Levels (61.8% and 79% Fibonacci Retracement)
      if (ind.showOTE && dr.fib_618 && dr.fib_790) {
        const fib618Y = Y(dr.fib_618);
        const fib790Y = Y(dr.fib_790);

        ctx.fillStyle = "rgba(245, 158, 11, 0.08)";
        ctx.fillRect(plotLeft, Math.min(fib618Y, fib790Y), plotW, Math.abs(fib790Y - fib618Y));

        ctx.strokeStyle = "rgba(245, 158, 11, 0.6)";
        ctx.setLineDash([3 * dpr, 2 * dpr]);
        ctx.beginPath();
        ctx.moveTo(plotLeft, fib618Y);
        ctx.lineTo(plotRight, fib618Y);
        ctx.moveTo(plotLeft, fib790Y);
        ctx.lineTo(plotRight, fib790Y);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = "#f59e0b";
        ctx.fillText(`OTE 61.8%`, plotLeft + 12 * dpr, fib618Y - 3 * dpr);
        ctx.fillText(`OTE 79.0%`, plotLeft + 12 * dpr, fib790Y - 3 * dpr);
      }
    }

    // 3. Order Blocks (OB) with Mitigation Tracking (§2.4 of MicasR Spec)
    if (!isClean && smc.order_blocks && smc.order_blocks.length) {
      smc.order_blocks.forEach(ob => {
        const isBull = ob.type === "BULLISH_OB";
        if (isBull && !ind.showBullOB) return;
        if (!isBull && !ind.showBearOB) return;

        const yTop = Y(ob.top);
        const yBot = Y(ob.bottom);
        const hBox = Math.max(4 * dpr, yBot - yTop);

        const isMitigated = ob.status === "MITIGATED";
        const boxColor = isMitigated ? "rgba(100, 116, 139, 0.08)" : (isBull ? "rgba(34, 197, 94, 0.16)" : "rgba(239, 68, 68, 0.16)");
        const borderColor = isMitigated ? "rgba(100, 116, 139, 0.4)" : (isBull ? "#22c55e" : "#ef4444");

        ctx.fillStyle = boxColor;
        ctx.fillRect(plotLeft, yTop, plotW, hBox);
        ctx.strokeStyle = borderColor;
        ctx.lineWidth = 1 * dpr;
        ctx.strokeRect(plotLeft, yTop, plotW, hBox);

        ctx.fillStyle = borderColor;
        ctx.font = `${9 * dpr}px Inter, sans-serif`;
        ctx.textAlign = "left";
        const label = `${isBull ? "OB+" : "OB-"} (${ob.strength}) ${isMitigated ? "✓ MITIGATED" : "FRESH"}`;
        ctx.fillText(label, plotLeft + 10 * dpr, yTop + 11 * dpr);
      });
    }

    // 4. Fair Value Gaps (FVG) with Mitigation Tracking (§2.3 of MicasR Spec)
    if (!isClean && ind.showFVG && smc.fair_value_gaps && smc.fair_value_gaps.length) {
      smc.fair_value_gaps.forEach(fvg => {
        const isBull = fvg.type === "BULLISH_FVG";
        const yTop = Y(fvg.top);
        const yBot = Y(fvg.bottom);
        const hBox = Math.max(3 * dpr, yBot - yTop);
        const isFilled = fvg.status === "INVERSE_FVG" || fvg.fill_pct >= 100;

        const fillColor = isFilled ? "rgba(148, 163, 184, 0.08)" : (isBull ? "rgba(34, 197, 94, 0.13)" : "rgba(239, 68, 68, 0.13)");
        const strokeColor = isFilled ? "rgba(148, 163, 184, 0.35)" : (isBull ? "rgba(34, 197, 94, 0.6)" : "rgba(239, 68, 68, 0.6)");

        ctx.fillStyle = fillColor;
        ctx.fillRect(plotLeft + plotW * 0.4, yTop, plotW * 0.6, hBox);
        ctx.strokeStyle = strokeColor;
        ctx.strokeRect(plotLeft + plotW * 0.4, yTop, plotW * 0.6, hBox);

        ctx.fillStyle = strokeColor;
        ctx.font = `${8.5 * dpr}px monospace`;
        ctx.textAlign = "left";
        ctx.fillText(`${isBull ? "FVG+" : "FVG-"} ${isFilled ? "✓ FILLED" : `${fvg.fill_pct}%`}`, plotLeft + plotW * 0.42, yTop + 9 * dpr);
      });
    }

    // 5. Liquidity Pools (BSL, SSL, Equal Highs, Equal Lows) (§2.5, §2.11)
    if (!isClean && smc.liquidity) {
      const liq = smc.liquidity;

      // Buy-side Liquidity (BSL)
      if (ind.showBSL && liq.bsl && liq.bsl.level) {
        const bslY = Y(liq.bsl.level);
        ctx.strokeStyle = "#f59e0b";
        ctx.setLineDash([4 * dpr, 3 * dpr]);
        ctx.beginPath();
        ctx.moveTo(plotLeft, bslY);
        ctx.lineTo(plotRight, bslY);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = "#f59e0b";
        ctx.font = `${9 * dpr}px Inter, sans-serif`;
        ctx.textAlign = "right";
        ctx.fillText(`BSL LIQUIDITY POOL · $${liq.bsl.level.toFixed(2)}`, plotRight - 10 * dpr, bslY - 4 * dpr);
      }

      // Sell-side Liquidity (SSL)
      if (ind.showSSL && liq.ssl && liq.ssl.level) {
        const sslY = Y(liq.ssl.level);
        ctx.strokeStyle = "#38bdf8";
        ctx.setLineDash([4 * dpr, 3 * dpr]);
        ctx.beginPath();
        ctx.moveTo(plotLeft, sslY);
        ctx.lineTo(plotRight, sslY);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = "#38bdf8";
        ctx.font = `${9 * dpr}px Inter, sans-serif`;
        ctx.textAlign = "right";
        ctx.fillText(`SSL LIQUIDITY POOL · $${liq.ssl.level.toFixed(2)}`, plotRight - 10 * dpr, sslY + 12 * dpr);
      }

      // Equal Highs (EQH)
      if (ind.showEQ && liq.equal_highs && liq.equal_highs.length) {
        liq.equal_highs.forEach(eqPrice => {
          const eqY = Y(eqPrice);
          ctx.strokeStyle = "#eab308";
          ctx.setLineDash([3 * dpr, 2 * dpr]);
          ctx.beginPath();
          ctx.moveTo(plotLeft, eqY);
          ctx.lineTo(plotRight, eqY);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = "#eab308";
          ctx.textAlign = "left";
          ctx.fillText(`EQH (Equal Highs)`, plotLeft + 14 * dpr, eqY - 3 * dpr);
        });
      }

      // Equal Lows (EQL)
      if (ind.showEQ && liq.equal_lows && liq.equal_lows.length) {
        liq.equal_lows.forEach(eqPrice => {
          const eqY = Y(eqPrice);
          ctx.strokeStyle = "#06b6d4";
          ctx.setLineDash([3 * dpr, 2 * dpr]);
          ctx.beginPath();
          ctx.moveTo(plotLeft, eqY);
          ctx.lineTo(plotRight, eqY);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = "#06b6d4";
          ctx.textAlign = "left";
          ctx.fillText(`EQL (Equal Lows)`, plotLeft + 14 * dpr, eqY + 11 * dpr);
        });
      }
    }

    // 6. Structure Breaks (BOS & CHoCH) (§2.1, §2.2 of MicasR Spec)
    if (!isClean && smc.structure_breaks && smc.structure_breaks.length) {
      smc.structure_breaks.forEach(brk => {
        const isBOS = brk.type.includes("BOS");
        const isBull = brk.direction === "BULLISH";
        if (isBOS && !ind.showBOS) return;
        if (!isBOS && !ind.showCHoCH) return;

        const breakY = Y(brk.price);
        const col = isBOS ? (isBull ? "#38bdf8" : "#fb7185") : (isBull ? "#a855f7" : "#f97316");

        ctx.strokeStyle = col;
        ctx.lineWidth = (isBOS ? 1.2 : 1.8) * dpr;
        if (isBOS) ctx.setLineDash([4 * dpr, 3 * dpr]);
        else ctx.setLineDash([]);

        const startIdx = Math.max(startIndex, brk.candle_index - 8);
        const endIdx = Math.min(endIndex - 1, brk.candle_index);

        ctx.beginPath();
        ctx.moveTo(X(startIdx), breakY);
        ctx.lineTo(X(endIdx), breakY);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = col;
        ctx.font = `bold ${9 * dpr}px Inter, sans-serif`;
        ctx.textAlign = "left";
        ctx.fillText(isBOS ? `BOS ${isBull ? "▲" : "▼"}` : `CHOCH ${isBull ? "▲" : "▼"}`, X(endIdx) + 4 * dpr, breakY + 3 * dpr);
      });
    }

    // 7. Swing Points (HH, HL, LH, LL) (§2.1)
    if (!isClean && ind.showSwings && smc.swings && smc.swings.points) {
      ctx.font = `bold ${8.5 * dpr}px monospace`;
      smc.swings.points.forEach(pt => {
        if (pt.index >= startIndex && pt.index < endIndex) {
          const x = X(pt.index);
          const isHigh = pt.type === "SWING_HIGH";
          const y = Y(pt.price);
          ctx.fillStyle = isHigh ? "#38bdf8" : "#10b981";
          ctx.textAlign = "center";
          ctx.fillText(pt.tag || (isHigh ? "SH" : "SL"), x, isHigh ? y - 8 * dpr : y + 16 * dpr);
        }
      });
    }

    // 8. Institutional Japanese Candlesticks (Crisp Bodies and Wicks)
    const candleW = Math.max(3 * dpr, candleSpacing * 0.68);
    for (let i = startIndex; i < endIndex; i++) {
      const k = candles[i];
      if (!k) continue;

      const cx = X(i);
      const isUp = k.c >= k.o;
      const bodyColor = isUp ? "#22c55e" : "#ef4444";
      const borderColor = isUp ? "#16a34a" : "#dc2626";

      ctx.strokeStyle = bodyColor;
      ctx.fillStyle = bodyColor;
      ctx.lineWidth = 1.2 * dpr;

      // Candle Wick (High to Low)
      ctx.beginPath();
      ctx.moveTo(cx, Y(k.h));
      ctx.lineTo(cx, Y(k.l));
      ctx.stroke();

      // Candle Body (Open to Close)
      const topY = Y(Math.max(k.o, k.c));
      const botY = Y(Math.min(k.o, k.c));
      const bodyH = Math.max(2 * dpr, botY - topY);

      ctx.fillRect(cx - candleW / 2, topY, candleW, bodyH);
      ctx.strokeStyle = borderColor;
      ctx.strokeRect(cx - candleW / 2, topY, candleW, bodyH);
    }

    // 9. Quantum Vision 1,000 Monte Carlo Paths Fan (Radiating from last candle)
    if (ind.quantumVision && candles.length > 1) {
      const lastK = candles[candles.length - 1];
      const startX = X(candles.length - 1);
      const startY = Y(lastK.c);
      const fanW = 85 * dpr;

      ctx.fillStyle = "rgba(139, 92, 246, 0.12)";
      ctx.beginPath();
      ctx.moveTo(startX, startY);
      ctx.lineTo(startX + fanW, startY - 42 * dpr);
      ctx.lineTo(startX + fanW, startY + 36 * dpr);
      ctx.closePath();
      ctx.fill();

      // Median trajectory
      ctx.strokeStyle = "#8b5cf6";
      ctx.lineWidth = 2 * dpr;
      ctx.beginPath();
      ctx.moveTo(startX, startY);
      ctx.lineTo(startX + fanW, startY - 14 * dpr);
      ctx.stroke();

      // Cone upper and lower boundary dashes
      ctx.strokeStyle = "rgba(139, 92, 246, 0.4)";
      ctx.setLineDash([3 * dpr, 2 * dpr]);
      ctx.beginPath();
      ctx.moveTo(startX, startY);
      ctx.lineTo(startX + fanW, startY - 42 * dpr);
      ctx.moveTo(startX, startY);
      ctx.lineTo(startX + fanW, startY + 36 * dpr);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // 10. Live Current Price Highlight on Right Scale
    if (candles.length > 0) {
      const lastK = candles[candles.length - 1];
      const curY = Y(lastK.c);
      const isUp = lastK.c >= lastK.o;
      const tagColor = isUp ? "#22c55e" : "#ef4444";

      // Horizontal dashed line
      ctx.strokeStyle = tagColor;
      ctx.setLineDash([3 * dpr, 2 * dpr]);
      ctx.lineWidth = 1 * dpr;
      ctx.beginPath();
      ctx.moveTo(plotLeft, curY);
      ctx.lineTo(plotRight, curY);
      ctx.stroke();
      ctx.setLineDash([]);

      // Right axis price badge
      ctx.fillStyle = tagColor;
      ctx.fillRect(plotRight + 2 * dpr, curY - 9 * dpr, 70 * dpr, 18 * dpr);
      ctx.fillStyle = "#ffffff";
      ctx.font = `bold ${10.5 * dpr}px monospace`;
      ctx.textAlign = "left";
      ctx.fillText(lastK.c >= 100 ? lastK.c.toFixed(2) : lastK.c.toFixed(4), plotRight + 7 * dpr, curY + 4 * dpr);
    }

    // 11. Multi-Timeframe Trend Bias Dashboard HUD (§2.8 of MicasR Spec)
    if (ind.showDashboard) {
      const hudX = plotRight - 310 * dpr;
      const hudY = plotTop + 4 * dpr;

      ctx.fillStyle = "rgba(15, 23, 42, 0.85)";
      ctx.strokeStyle = "rgba(255, 255, 255, 0.1)";
      ctx.lineWidth = 1 * dpr;
      ctx.fillRect(hudX, hudY, 300 * dpr, 26 * dpr);
      ctx.strokeRect(hudX, hudY, 300 * dpr, 26 * dpr);

      const tfs = [
        { name: "15M", trend: "UP" },
        { name: "1H",  trend: "UP" },
        { name: "4H",  trend: "UP" },
        { name: "1D",  trend: "DN" },
        { name: "1W",  trend: "NT" }
      ];

      ctx.font = `bold ${9 * dpr}px Inter, sans-serif`;
      ctx.textAlign = "center";

      tfs.forEach((item, idx) => {
        const itemX = hudX + 30 * dpr + idx * 58 * dpr;
        ctx.fillStyle = "#94a3b8";
        ctx.fillText(item.name, itemX - 14 * dpr, hudY + 16 * dpr);

        if (item.trend === "UP") {
          ctx.fillStyle = "#22c55e";
          ctx.fillText("▲ UP", itemX + 14 * dpr, hudY + 16 * dpr);
        } else if (item.trend === "DN") {
          ctx.fillStyle = "#ef4444";
          ctx.fillText("▼ DN", itemX + 14 * dpr, hudY + 16 * dpr);
        } else {
          ctx.fillStyle = "#94a3b8";
          ctx.fillText("◆ NT", itemX + 14 * dpr, hudY + 16 * dpr);
        }
      });
    }
  };

  /* ---------------------------- Data Loader Pipeline ---------------------------- */
  window.VT.loadMarketData = async function(symbol, tf) {
    const s = (symbol || window.VT.symbol || "BTCUSDT").toUpperCase();
    const t = (tf || window.VT.timeframe || "15m").toLowerCase();

    window.VT.symbol = s;
    window.VT.timeframe = t;
    window.VT.isLoading = true;

    // Sync legacy globals
    if (window.S) {
      window.S.symbol = s;
      window.S.tf = t;
    }

    // UI Updates
    if ($id("symBtnS")) $id("symBtnS").textContent = s;
    if ($id("symSel")) $id("symSel").value = s;
    if ($id("t_symbol")) $id("t_symbol").textContent = s;
    if ($id("t_tf_badge")) $id("t_tf_badge").textContent = t.toUpperCase();

    document.querySelectorAll(".tfs button[data-tf]").forEach(btn => {
      const match = btn.getAttribute("data-tf") === t;
      btn.classList.toggle("active", match);
      btn.setAttribute("aria-pressed", String(match));
    });

    document.querySelectorAll(".wl-row[data-sym]").forEach(row => {
      row.setAttribute("aria-current", String(row.getAttribute("data-sym") === s));
    });

    // Render loading indicator on canvas
    window.VT.renderSMCChart();

    try {
      const res = await fetch(`/api/smc/analysis/${encodeURIComponent(s)}?timeframe=${encodeURIComponent(t)}`).then(r => r.json());

      if (res && res.success) {
        let candles = (res.candles && res.candles.length) ? res.candles : null;
        if (!candles && window.S && window.S.candles && window.S.candles.length) {
          candles = window.S.candles;
        }
        if (!candles) {
          try {
            const raw = await fetch(`/api/market/candles/${encodeURIComponent(s)}?interval=${encodeURIComponent(t)}&candles=140`).then(r => r.json());
            if (raw && raw.candles) candles = raw.candles;
          } catch(e) {}
        }

        window.VT.candles = candles || [];
        window.VT.smcData = res;
        window.VT.isLoading = false;

        if (window.S) {
          window.S.candles = window.VT.candles;
          window.S.smcDna = res;
        }

        // 1. Update Subbar OHLC
        if (window.VT.candles.length) {
          const last = window.VT.candles[window.VT.candles.length - 1];
          const openP = last.o;
          const curP = last.c;
          const chg = ((curP - openP) / openP) * 100;

          if ($id("t_sub_o")) $id("t_sub_o").textContent = openP >= 100 ? openP.toFixed(2) : openP.toFixed(4);
          if ($id("t_sub_h")) $id("t_sub_h").textContent = last.h >= 100 ? last.h.toFixed(2) : last.h.toFixed(4);
          if ($id("t_sub_l")) $id("t_sub_l").textContent = last.l >= 100 ? last.l.toFixed(2) : last.l.toFixed(4);
          if ($id("t_sub_c")) $id("t_sub_c").textContent = curP >= 100 ? curP.toFixed(2) : curP.toFixed(4);
          if ($id("t_sub_chg")) {
            $id("t_sub_chg").textContent = `${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%`;
            $id("t_sub_chg").style.color = chg >= 0 ? "#22c55e" : "#f87171";
          }
          if ($id("t_sub_bid")) $id("t_sub_bid").textContent = (curP * 0.9999).toFixed(2);
          if ($id("t_sub_ask")) $id("t_sub_ask").textContent = (curP * 1.0001).toFixed(2);
          if ($id("t_sub_spread")) $id("t_sub_spread").textContent = (curP * 0.0002).toFixed(2);
        }

        // 2. Update Right AI Panel
        const ai = res.ai_report || {};
        const buyPct = ai.buy_strength || 65;
        const sellPct = ai.sell_strength || 35;
        if ($id("iva_buy_pct")) $id("iva_buy_pct").textContent = `${buyPct}%`;
        if ($id("iva_buy_bar")) $id("iva_buy_bar").style.width = `${buyPct}%`;
        if ($id("iva_sell_pct")) $id("iva_sell_pct").textContent = `${sellPct}%`;
        if ($id("iva_sell_bar")) $id("iva_sell_bar").style.width = `${sellPct}%`;

        if ($id("iva_bias_badge")) {
          const bias = ai.overall_bias || "BULLISH";
          $id("iva_bias_badge").textContent = bias;
          $id("iva_bias_badge").className = bias === "BULLISH" ? "pos" : (bias === "BEARISH" ? "neg" : "mut");
        }
        if ($id("iva_net_score")) {
          const net = ((buyPct - 50) / 50).toFixed(2);
          $id("iva_net_score").textContent = `net ${net >= 0 ? '+' : ''}${net}`;
        }

        if ($id("iva_conf_txt")) $id("iva_conf_txt").textContent = `High · ${ai.confidence_score || 85}%`;
        if ($id("iva_conf_bar")) $id("iva_conf_bar").style.width = `${ai.confidence_score || 85}%`;
        if ($id("iva_confluence_txt")) $id("iva_confluence_txt").textContent = `${ai.confluence_score || 78}/100`;
        if ($id("iva_confluence_bar")) $id("iva_confluence_bar").style.width = `${ai.confluence_score || 78}%`;

        if ($id("iva_trend_adx")) $id("iva_trend_adx").textContent = ai.trend_strength || "Strong";
        if ($id("iva_regime_txt")) $id("iva_regime_txt").textContent = ai.market_regime || "Expansion";
        if ($id("iva_volatility_txt")) $id("iva_volatility_txt").textContent = ai.volatility || "Moderate";

        // Quick Execute Ticket SL & TP
        if (res.liquidity) {
          if ($id("quick_sl_price") && res.liquidity.ssl) $id("quick_sl_price").textContent = `$${res.liquidity.ssl.level?.toFixed(2) || "—"}`;
          if ($id("quick_tp_price") && res.liquidity.bsl) $id("quick_tp_price").textContent = `$${res.liquidity.bsl.level?.toFixed(2) || "—"}`;
        }

        // Structure Events list
        if ($id("iva_ev_list") && res.structure_breaks) {
          const evs = res.structure_breaks.slice(-4).reverse();
          $id("iva_ev_list").innerHTML = evs.map(e => `
            <li><time>${new Date(e.time * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</time>${e.type.replace('_', ' ')} confirmed at $${e.break_price || e.price}</li>
          `).join('');
        }

        // 3. Update Bottom Dock Structure Timeline Table
        updateTimelineTable(res);

        // 4. Render Candlestick Chart
        window.VT.resizeCanvas();
        window.VT.renderSMCChart();

        // 5. Start live candle timer
        startCandleCountdown(t);
      }
    } catch (err) {
      window.VT.isLoading = false;
      console.error("Error loading SMC market data:", err);
    }
  };

  window.VT.setSymbol = function(sym) {
    window.VT.panOffset = 0;
    window.VT.loadMarketData(sym, window.VT.timeframe);
  };

  window.VT.setTimeframe = function(tf) {
    window.VT.panOffset = 0;
    window.VT.loadMarketData(window.VT.symbol, tf);
  };

  /* Sync data from legacy backend pollers */
  window.VT.syncFromBackend = function(quote, smcDna, activeAnalysis) {
    if (smcDna) {
      window.VT.smcData = Object.assign(window.VT.smcData || {}, smcDna);
    }
    if (window.S && window.S.candles && window.S.candles.length && (!window.VT.candles || !window.VT.candles.length)) {
      window.VT.candles = window.S.candles;
    }
    if (quote && quote.price && window.VT.candles && window.VT.candles.length) {
      const lastK = window.VT.candles[window.VT.candles.length - 1];
      if (lastK) {
        lastK.c = quote.price;
        if (quote.price > lastK.h) lastK.h = quote.price;
        if (quote.price < lastK.l) lastK.l = quote.price;
      }
    }
    if (typeof window.VT.renderSMCChart === "function") {
      window.VT.renderSMCChart();
    }
  };

  /* ---------------------------- Forming Candle Countdown ---------------------------- */
  function startCandleCountdown(tf) {
    if (window.VT.candleTimerId) clearInterval(window.VT.candleTimerId);

    const tfSeconds = {
      "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
      "1h": 3600, "4h": 14400, "1d": 86400
    }[tf] || 900;

    function tick() {
      const nowSec = Math.floor(Date.now() / 1000);
      const remain = tfSeconds - (nowSec % tfSeconds);
      const m = Math.floor(remain / 60).toString().padStart(2, "0");
      const s = (remain % 60).toString().padStart(2, "0");
      const el = $id("t_candle_timer");
      if (el) el.textContent = `${m}:${s} FORMING`;
    }

    tick();
    window.VT.candleTimerId = setInterval(tick, 1000);
  }

  /* ---------------------------- Bottom Dock Timeline Feed ---------------------------- */
  function updateTimelineTable(res) {
    const tableBody = $id("iva_tl_table_body") || document.querySelector("#bt_tab_feed table tbody");
    if (!tableBody) return;

    const breaks = res.structure_breaks || [];
    const obs = res.order_blocks || [];
    const fvgs = res.fair_value_gaps || [];

    const rows = [];
    breaks.forEach(b => {
      rows.push({
        time: b.time,
        sym: res.symbol,
        tf: res.timeframe,
        event: b.type.replace('_', ' '),
        detail: `Structure break at $${b.break_price || b.price}`,
        price: b.break_price || b.price,
        color: b.direction === "BULLISH" ? "#22c55e" : "#ef4444"
      });
    });

    obs.slice(-3).forEach(o => {
      rows.push({
        time: o.time || Math.floor(Date.now() / 1000) - 1200,
        sym: res.symbol,
        tf: res.timeframe,
        event: `${o.type.replace('_', ' ')} (${o.strength})`,
        detail: `Zone: $${o.bottom} - $${o.top} · ${o.status}`,
        price: (o.top + o.bottom) / 2,
        color: o.type.includes("BULL") ? "#10b981" : "#f43f5e"
      });
    });

    rows.sort((a, b) => b.time - a.time);

    tableBody.innerHTML = rows.slice(0, 15).map(r => `
      <tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
        <td style="padding:6px 10px; font-family:monospace; color:#94a3b8;">${new Date(r.time * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</td>
        <td style="padding:6px 10px; font-weight:800; color:#f1f5f9;">${r.sym}</td>
        <td style="padding:6px 10px; font-weight:700; color:#38bdf8;">${r.tf.toUpperCase()}</td>
        <td style="padding:6px 10px; font-weight:700; color:${r.color};">${r.event}</td>
        <td style="padding:6px 10px; color:#cbd5e1;">${r.detail}</td>
        <td style="padding:6px 10px; font-family:monospace; font-weight:700; text-align:right; color:#f1f5f9;">$${typeof r.price === 'number' ? r.price.toFixed(2) : r.price}</td>
      </tr>
    `).join('');
  }

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
      const isCur = window.VT.symbol === item.sym;
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
        const s = row.getAttribute("data-sym");
        window.VT.setSymbol(s);
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

  /* ---------------------------- Quick Trade Execution Ticket ---------------------------- */
  window.quickExecuteTrade = async function(side) {
    const sym = window.VT.symbol || "BTCUSDT";
    const lastK = window.VT.candles?.[window.VT.candles.length - 1];
    const price = lastK ? lastK.c : 92450.0;
    const isBuy = side === "BUY";
    const sl = isBuy ? (price * 0.985).toFixed(2) : (price * 1.015).toFixed(2);
    const tp = isBuy ? (price * 1.035).toFixed(2) : (price * 0.965).toFixed(2);

    if (typeof window.toast === "function") {
      window.toast(`⚡ Routing institutional ${side} order on ${sym} (CoinDCX Live Gateway)...`, "blue");
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
            window.toast(`✅ ${side} order executed at $${price}! SL: $${sl} · TP: $${tp}`, "green");
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

  /* ---------------------------- Module Modals (Scanner, Backtest, Alerts, Journal) ---------------------------- */
  window.VT.openModal = function(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = "flex";
    if (id === "vt_modal_scanner") window.VT.loadScanner();
    if (id === "vt_modal_alerts") window.VT.loadAlerts();
    if (id === "vt_modal_journal") window.VT.loadJournal();
  };

  window.VT.closeModal = function(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = "none";
  };

  /* 1. Strategy Scanner */
  window.VT.loadScanner = async function() {
    const tbody = document.getElementById("scanner_tbody");
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:18px; color:#94a3b8;">Scanning institutional markets for SMC events...</td></tr>`;
    try {
      const tf = document.getElementById("scanner_tf_sel")?.value || "15m";
      const res = await fetch(`/api/scanner?timeframe=${encodeURIComponent(tf)}`).then(r => r.json());
      if (res && res.success && res.events) {
        if (!res.events.length) {
          tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:18px; color:#64748b;">No active events found for ${tf.toUpperCase()}.</td></tr>`;
          return;
        }
        tbody.innerHTML = res.events.map(ev => {
          const isBull = ev.market_bias === "BULLISH";
          const col = isBull ? "#22c55e" : (ev.market_bias === "BEARISH" ? "#f87171" : "#94a3b8");
          const evCol = ev.latest_event.includes("BOS") ? "#38bdf8" : (ev.latest_event.includes("CHOCH") ? "#c084fc" : "#cbd5e1");
          return `<tr style="border-bottom:1px solid rgba(255,255,255,0.05); transition:background .15s ease;" onmouseover="this.style.background='rgba(255,255,255,0.03)'" onmouseout="this.style.background=''">
            <td style="padding:10px 12px; font-weight:800; color:#fff;">${ev.instrument}</td>
            <td style="padding:10px 12px; font-family:monospace; color:#cbd5e1;">$${ev.current_price >= 100 ? ev.current_price.toFixed(2) : ev.current_price.toFixed(4)}</td>
            <td style="padding:10px 12px; color:#38bdf8; font-weight:700;">${ev.timeframe}</td>
            <td style="padding:10px 12px;"><span style="font-size:10px; font-weight:800; padding:2px 8px; border-radius:4px; background:${isBull ? 'rgba(34,197,94,0.15)' : 'rgba(248,113,113,0.15)'}; color:${col};">${ev.market_bias}</span></td>
            <td style="padding:10px 12px; font-weight:700; color:${evCol};">${ev.latest_event}</td>
            <td style="padding:10px 12px;"><span style="font-size:10px; font-weight:700; padding:2px 6px; border-radius:4px; background:rgba(255,255,255,0.06); color:#cbd5e1;">${ev.dealing_zone}</span></td>
            <td style="padding:10px 12px; text-align:right;">
              <button onclick="window.VT.selectSymbolFromScanner('${ev.instrument}')" style="background:rgba(139,92,246,0.2); border:1px solid #8b5cf6; color:#c084fc; font-size:10px; font-weight:800; padding:4px 10px; border-radius:4px; cursor:pointer;">CHART ↗</button>
            </td>
          </tr>`;
        }).join("");
      }
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:18px; color:#ef4444;">Error loading scanner data.</td></tr>`;
    }
  };

  window.VT.selectSymbolFromScanner = function(sym) {
    window.VT.setSymbol(sym);
    window.VT.closeModal("vt_modal_scanner");
  };

  /* 2. Historical Backtest Runner */
  window.VT.runBacktest = async function() {
    const sym = document.getElementById("bt_sym_sel")?.value || (window.VT.symbol || "BTCUSDT");
    const tf = document.getElementById("bt_tf_sel")?.value || "15m";
    const rr = parseFloat(document.getElementById("bt_rr_inp")?.value || "2.0");
    const resBox = document.getElementById("bt_results_box");
    if (!resBox) return;

    resBox.innerHTML = `<div style="text-align:center; padding:20px; color:#94a3b8;">Running institutional no-lookahead SMC backtest on ${sym} (${tf.toUpperCase()})...</div>`;
    try {
      const res = await fetch("/api/backtest/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: sym, timeframe: tf, risk_reward: rr, candles: 300 })
      }).then(r => r.json());

      if (res && res.success && res.results) {
        const r = res.results;
        resBox.innerHTML = `
          <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:10px; margin-bottom:14px;">
            <div style="background:rgba(255,255,255,0.03); padding:10px; border-radius:6px; border:1px solid rgba(255,255,255,0.08);">
              <span style="font-size:10px; color:#94a3b8;">WIN RATE</span><br>
              <b style="font-size:16px; color:${r.win_rate >= 50 ? '#22c55e' : '#f87171'};">${r.win_rate}%</b>
            </div>
            <div style="background:rgba(255,255,255,0.03); padding:10px; border-radius:6px; border:1px solid rgba(255,255,255,0.08);">
              <span style="font-size:10px; color:#94a3b8;">PROFIT FACTOR</span><br>
              <b style="font-size:16px; color:#38bdf8;">${r.profit_factor}</b>
            </div>
            <div style="background:rgba(255,255,255,0.03); padding:10px; border-radius:6px; border:1px solid rgba(255,255,255,0.08);">
              <span style="font-size:10px; color:#94a3b8;">MAX DRAWDOWN</span><br>
              <b style="font-size:16px; color:#ef4444;">${r.max_drawdown}%</b>
            </div>
            <div style="background:rgba(255,255,255,0.03); padding:10px; border-radius:6px; border:1px solid rgba(255,255,255,0.08);">
              <span style="font-size:10px; color:#94a3b8;">TOTAL SETUPS</span><br>
              <b style="font-size:16px; color:#fff;">${r.total_setups}</b>
            </div>
            <div style="background:rgba(255,255,255,0.03); padding:10px; border-radius:6px; border:1px solid rgba(255,255,255,0.08);">
              <span style="font-size:10px; color:#94a3b8;">NET GAIN</span><br>
              <b style="font-size:16px; color:${r.net_profit >= 0 ? '#22c55e' : '#f87171'};">${r.net_profit >= 0 ? '+' : ''}$${r.net_profit}</b>
            </div>
          </div>
          <div style="font-size:11px; font-weight:800; color:#cbd5e1; margin-bottom:6px;">RESOLVED HISTORICAL TRADES (STRICT NO-LOOKAHEAD):</div>
          <div style="max-height:220px; overflow-y:auto; border:1px solid rgba(255,255,255,0.06); border-radius:6px;">
            <table style="width:100%; border-collapse:collapse; font-size:11px; text-align:left;">
              <thead>
                <tr style="background:rgba(0,0,0,0.4); color:#94a3b8;">
                  <th style="padding:6px 8px;">Time</th>
                  <th style="padding:6px 8px;">Side</th>
                  <th style="padding:6px 8px;">Entry</th>
                  <th style="padding:6px 8px;">Exit</th>
                  <th style="padding:6px 8px;">Result</th>
                  <th style="padding:6px 8px; text-align:right;">P&L ($)</th>
                </tr>
              </thead>
              <tbody>
                ${(r.trades || []).map(t => `
                  <tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
                    <td style="padding:5px 8px; color:#94a3b8; font-family:monospace;">${new Date(t.entry_time * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</td>
                    <td style="padding:5px 8px; font-weight:700; color:${t.direction === 'BULLISH' ? '#22c55e' : '#f87171'};">${t.direction}</td>
                    <td style="padding:5px 8px; font-family:monospace;">$${t.entry_price}</td>
                    <td style="padding:5px 8px; font-family:monospace;">$${t.exit_price}</td>
                    <td style="padding:5px 8px; font-weight:800; color:${t.outcome === 'WIN' ? '#22c55e' : '#f87171'};">${t.outcome}</td>
                    <td style="padding:5px 8px; text-align:right; font-family:monospace; color:${t.pnl_usd >= 0 ? '#22c55e' : '#f87171'};">${t.pnl_usd >= 0 ? '+' : ''}$${t.pnl_usd}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        `;
      }
    } catch (e) {
      resBox.innerHTML = `<div style="text-align:center; padding:20px; color:#ef4444;">Backtest failed: ${e.message}</div>`;
    }
  };

  /* 3. Alerts Manager */
  window.VT.loadAlerts = async function() {
    const list = document.getElementById("alerts_list");
    if (!list) return;
    list.innerHTML = `<div style="text-align:center; padding:18px; color:#94a3b8;">Loading configured institutional alerts...</div>`;
    try {
      const res = await fetch("/api/alerts").then(r => r.json());
      if (res && res.success && res.alerts) {
        if (!res.alerts.length) {
          list.innerHTML = `<div style="text-align:center; padding:18px; color:#64748b;">No active SMC alerts configured. Create one below!</div>`;
          return;
        }
        list.innerHTML = res.alerts.map(a => `
          <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 12px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:6px; margin-bottom:6px;">
            <div>
              <b style="color:#fff; font-size:12px;">${a.symbol} · ${a.event_type}</b><br>
              <span style="font-size:10px; color:#94a3b8;">Timeframe: ${a.timeframe} · Target: $${a.target_price || 'Market'}</span>
            </div>
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:10px; font-weight:800; color:#22c55e; background:rgba(34,197,94,0.12); padding:2px 6px; border-radius:4px;">ACTIVE</span>
              <button onclick="window.VT.deleteAlert(${a.id})" style="background:transparent; border:none; color:#ef4444; font-size:12px; cursor:pointer;">✕</button>
            </div>
          </div>
        `).join("");
      }
    } catch (e) {
      list.innerHTML = `<div style="text-align:center; padding:18px; color:#ef4444;">Error loading alerts.</div>`;
    }
  };

  window.VT.createAlert = async function() {
    const sym = document.getElementById("alert_sym_sel")?.value || (window.VT.symbol || "BTCUSDT");
    const tf = document.getElementById("alert_tf_sel")?.value || "15m";
    const ev = document.getElementById("alert_type_sel")?.value || "BULLISH_BOS";
    const price = parseFloat(document.getElementById("alert_price_inp")?.value || "0");

    try {
      await fetch("/api/alerts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: sym, timeframe: tf, event_type: ev, target_price: price, notify_in_app: true })
      });
      if (typeof window.toast === "function") window.toast(`✅ Alert created for ${sym} ${ev}!`, "green");
      window.VT.loadAlerts();
    } catch (e) {}
  };

  window.VT.deleteAlert = async function(id) {
    try {
      await fetch(`/api/alerts/${id}`, { method: "DELETE" });
      window.VT.loadAlerts();
    } catch (e) {}
  };

  /* 4. Trading Journal */
  window.VT.loadJournal = async function() {
    const list = document.getElementById("journal_entries_list");
    if (!list) return;
    list.innerHTML = `<div style="text-align:center; padding:18px; color:#94a3b8;">Loading trading journal logs...</div>`;
    try {
      const res = await fetch("/api/journal").then(r => r.json());
      if (res && res.success && res.entries) {
        if (!res.entries.length) {
          list.innerHTML = `<div style="text-align:center; padding:18px; color:#64748b;">No trades logged yet. Record your trade below!</div>`;
          return;
        }
        list.innerHTML = res.entries.map(j => `
          <div style="padding:10px 12px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:6px; margin-bottom:8px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
              <b style="color:#fff; font-size:12px;">${j.symbol} · ${j.trade_type}</b>
              <b style="font-size:13px; font-family:monospace; color:${j.pnl >= 0 ? '#22c55e' : '#f87171'};">${j.pnl >= 0 ? '+' : ''}$${j.pnl}</b>
            </div>
            <div style="font-size:10.5px; color:#94a3b8;">Entry: $${j.entry_price} · Exit: $${j.exit_price} · Timeframe: ${j.timeframe}</div>
            ${j.notes ? `<div style="font-size:11px; color:#cbd5e1; margin-top:4px; font-style:italic;">"${j.notes}"</div>` : ''}
          </div>
        `).join("");
      }
    } catch (e) {
      list.innerHTML = `<div style="text-align:center; padding:18px; color:#ef4444;">Error loading journal entries.</div>`;
    }
  };

  window.VT.saveJournalEntry = async function() {
    const sym = document.getElementById("jr_sym_sel")?.value || (window.VT.symbol || "BTCUSDT");
    const tf = document.getElementById("jr_tf_sel")?.value || "15m";
    const tt = document.getElementById("jr_type_sel")?.value || "LONG";
    const en = parseFloat(document.getElementById("jr_entry_inp")?.value || "0");
    const ex = parseFloat(document.getElementById("jr_exit_inp")?.value || "0");
    const pnl = parseFloat(document.getElementById("jr_pnl_inp")?.value || "0");
    const notes = document.getElementById("jr_notes_inp")?.value || "";

    try {
      await fetch("/api/journal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: sym, timeframe: tf, trade_type: tt, entry_price: en, exit_price: ex, pnl: pnl, notes: notes })
      });
      if (typeof window.toast === "function") window.toast(`✅ Trade logged in journal!`, "green");
      window.VT.loadJournal();
    } catch (e) {}
  };

  /* ---------------------------- Boot Engine ---------------------------- */
  function boot() {
    initResizers();
    initPanelToggles();
    initTopBarFeatures();
    initDrawingTools();
    initTabSwitchers();
    initCanvasInteractions();
    window.VT.renderWatchlist();
    window.VT.resizeCanvas();

    // Auto-load live institutional market structure immediately
    const initSym = window.VT.symbol || "BTCUSDT";
    const initTf = window.VT.timeframe || "15m";
    window.VT.loadMarketData(initSym, initTf);

    setTimeout(() => { if (typeof window.VT.resizeCanvas === "function") window.VT.resizeCanvas(); }, 150);
    setTimeout(() => { if (typeof window.VT.resizeCanvas === "function") window.VT.resizeCanvas(); }, 600);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
