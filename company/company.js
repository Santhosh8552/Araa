/* ARAA Company Proprietary Trading Control Center JS */
(function () {
  const STORAGE_KEY = "araa_company_token";
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  const tsFmt = (ts) => (ts ? new Date(Number(ts) * 1000).toLocaleString("en-IN", { hour12: false }) : "—");

  const VIEW_TITLES = {
    dashboard: "Company Dashboard",
    erp_hub: "Corporate Governance & ERP Portal",
    india: "India Capital Pool · Zerodha Kite Connect",
    crypto: "Crypto Spot Capital Pool · CoinDCX",
    ai_hub: "ARAA Unified AI Hub & Copilot (All Engines Connected)",
    strategies: "Strategies & AI Signal Proposals",
    orders: "16-State OMS & Idempotent Orders",
    positions: "Company Positions & Controlled Flatten",
    finance: "Independent Capital Pools & Finance",
    ledger: "Immutable Company Ledger",
    reconciliation: "Broker Reconciliation Inspector",
    risk: "Independent Risk Guardian",
    backtest: "Backtesting & Performance Analytics",
    company_profile: "Company Legal Profile & Compliance",
    employees: "Employees, 7-Role RBAC, MFA & Approvals",
    audit: "Audit Logs & System Health",
  };

  const state = {
    token: sessionStorage.getItem(STORAGE_KEY) || "",
    user: null,
    view: "dashboard",
    needsBootstrap: false,
  };

  function notice(msg, type = "info") {
    const el = $("global_notice");
    if (!el) return;
    el.className = `alert-banner ${type}`;
    el.textContent = msg;
    el.classList.remove("hide");
    setTimeout(() => el.classList.add("hide"), 6000);
  }

  async function api(path, opts = {}) {
    const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    if (state.token) headers["X-Company-Token"] = state.token;
    const res = await fetch(path, {
      method: opts.method || "GET",
      headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    const data = await res.json().catch(() => ({ success: false, error: `HTTP ${res.status}` }));
    if (res.status === 401 && !path.includes("/company/auth/")) {
      state.token = "";
      sessionStorage.removeItem(STORAGE_KEY);
      await checkAuth();
      throw new Error(data.error || "Session expired");
    }
    if (!res.ok && data.success === false) {
      throw Object.assign(new Error(data.error || `HTTP ${res.status}`), { payload: data, status: res.status });
    }
    return data;
  }

  async function checkAuth() {
    if (!state.token) {
      try {
        const bs = await fetch("/api/v1/company/auth/bootstrap-status").then((r) => r.json());
        state.needsBootstrap = Boolean(bs && bs.needs_bootstrap);
      } catch (e) {
        state.needsBootstrap = false;
      }
      showAuthOverlay();
      return false;
    }
    try {
      const me = await api("/api/v1/company/auth/me");
      state.user = me.employee;
      $("auth_overlay").classList.add("hide");
      $("top_user_badge").textContent = `${state.user.full_name} · ${state.user.role_code}${state.user.mfa_enabled ? " (MFA)" : ""}`;
      return true;
    } catch (e) {
      showAuthOverlay();
      return false;
    }
  }

  function showAuthOverlay() {
    $("auth_overlay").classList.remove("hide");
    if (state.needsBootstrap) {
      $("auth_subtitle").textContent = "First-time setup: create initial Company Director account";
      $("bootstrap_name_wrap").classList.remove("hide");
      $("auth_submit_btn").textContent = "Initialize Company Director";
    } else {
      $("auth_subtitle").textContent = "Sign in with your company operator credentials";
      $("bootstrap_name_wrap").classList.add("hide");
      $("auth_submit_btn").textContent = "Sign In";
    }
  }

  async function submitAuth() {
    $("auth_err").classList.add("hide");
    const email = $("auth_email").value.trim();
    const password = $("auth_pw").value;
    const totp = $("auth_totp").value.trim();
    const full_name = $("auth_full_name").value.trim();

    try {
      const url = state.needsBootstrap ? "/api/v1/company/auth/bootstrap" : "/api/v1/company/auth/login";
      const body = state.needsBootstrap ? { email, password, full_name } : { email, password, totp };
      const res = await api(url, { method: "POST", body });
      state.token = res.token;
      sessionStorage.setItem(STORAGE_KEY, res.token);
      state.needsBootstrap = false;
      await checkAuth();
      await refreshCurrent();
    } catch (e) {
      if (e.payload && e.payload.mfa_required) {
        $("mfa_input_wrap").classList.remove("hide");
      }
      $("auth_err").textContent = e.message;
      $("auth_err").classList.remove("hide");
    }
  }

  async function logout() {
    try {
      if (state.token) await api("/api/v1/company/auth/logout", { method: "POST" });
    } catch (e) {}
    state.token = "";
    sessionStorage.removeItem(STORAGE_KEY);
    location.reload();
  }

  function nav(view) {
    state.view = view;
    document.querySelectorAll(".view-sec").forEach((s) => s.classList.add("hide"));
    const target = $(`view_${view}`);
    if (target) target.classList.remove("hide");
    document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
    $("top_view_title").textContent = VIEW_TITLES[view] || "ARAA Prop Desk";
    refreshCurrent();
  }

  async function refreshCurrent() {
    if (!state.token) return;
    try {
      await loadSystemBanner();
      const v = state.view;
      if (v === "dashboard") await loadDashboard();
      else if (v === "erp_hub") await loadErpHub();
      else if (v === "india") await loadZerodhaView();
      else if (v === "crypto") await loadCoinDCXView();
      else if (v === "ai_hub") await loadAiHubView();
      else if (v === "strategies") await loadStrategiesView();
      else if (v === "orders") await loadOrdersView();
      else if (v === "positions") await loadPositionsView();
      else if (v === "finance") await loadFinanceView();
      else if (v === "ledger") await loadLedgerView();
      else if (v === "reconciliation") await loadReconciliationView();
      else if (v === "risk") await loadRiskView();
      else if (v === "company_profile") await loadCompanyProfileView();
      else if (v === "employees") await loadEmployeesView();
      else if (v === "audit") await loadAuditView();
    } catch (e) {
      notice(e.message, "err");
    }
  }

  async function loadSystemBanner() {
    try {
      const h = await fetch("/api/v1/company/system/health").then((r) => r.json());
      const badge = $("top_sys_badge");
      if (badge && h && h.status) {
        badge.textContent = `${h.status} · Enc: ${h.secrets_encryption_enabled ? "ON" : "DEV"}`;
        badge.className = `badge ${h.status === "HEALTHY" ? "ok" : "warn"}`;
      }
    } catch (e) {}
  }

  async function loadDashboard() {
    const [pfRes, accRes] = await Promise.all([
      api("/api/v1/company/portfolio"),
      api("/api/v1/company/accounts"),
    ]);
    const pf = pfRes.portfolio || {};
    const pools = pf.pools || {};
    const ind = pools.POOL_INDIA_INR || {};
    const crp = pools.POOL_CRYPTO_SPOT || {};

    $("dash_kpis").innerHTML = `
      <div class="card"><div class="kpi-label">Combined Allocated Capital (Reporting)</div><div class="kpi-val mono">₹${esc(pf.total_allocated_capital_inr)}</div><div class="kpi-sub">Separate risk budgets enforced</div></div>
      <div class="card"><div class="kpi-label">Broker-Confirmed Equity (Total)</div><div class="kpi-val mono" style="color:var(--green);">₹${esc(pf.total_broker_confirmed_equity_inr)}</div><div class="kpi-sub">Free ₹${esc(pf.total_free_funds_inr)} · Locked ₹${esc(pf.total_locked_funds_inr)}</div></div>
      <div class="card"><div class="kpi-label">Realized / Unrealized P&amp;L</div><div class="kpi-val mono">₹${esc(pf.total_realized_pnl_inr)}</div><div class="kpi-sub">Unrealized ₹${esc(pf.total_unrealized_pnl_inr)}</div></div>
      <div class="card"><div class="kpi-label">Fees &amp; Taxes Recorded</div><div class="kpi-val mono">₹${esc(pf.total_fees_inr)}</div><div class="kpi-sub">Taxes/Expenses ₹${esc(pf.total_taxes_expenses_inr)}</div></div>
    `;

    $("dash_pools").innerHTML = [ind, crp].map((p) => {
      const badgeCls = p.reconciliation_status === "MATCHED" ? "ok" : (p.reconciliation_status === "MISMATCH_HALTED" ? "err" : "warn");
      return `
        <div class="card">
          <div class="card-h">
            <h3 class="card-title">${esc(p.pool_name)} (${esc(p.pool_id)})</h3>
            <span class="badge ${badgeCls}">Recon: ${esc(p.reconciliation_status)}</span>
          </div>
          <div class="form-row">
            <div><div class="kpi-label">Allocated Capital</div><b class="mono">₹${esc(p.allocated_capital_inr)}</b></div>
            <div><div class="kpi-label">Broker Equity</div><b class="mono" style="color:var(--green);">₹${esc(p.broker_confirmed_equity_inr)}</b></div>
            <div><div class="kpi-label">Free Funds</div><b class="mono">₹${esc(p.free_funds_inr)}</b></div>
            <div><div class="kpi-label">Open Pos / Orders</div><b class="mono">${esc(p.open_positions_count)} / ${esc(p.pending_orders_count)}</b></div>
          </div>
        </div>
      `;
    }).join("");

    const accs = accRes.accounts || [];
    $("dash_accounts_tbl").innerHTML = accs.length ? `
      <table class="tbl"><thead><tr><th>Account ID</th><th>Provider</th><th>Market Pool</th><th>Legal Holder</th><th>Connection</th><th>Permissions</th><th>Mode</th></tr></thead>
      <tbody>${accs.map((a) => `
        <tr>
          <td class="mono">${esc(a.account_id)}</td>
          <td><b>${esc(a.provider)}</b></td>
          <td>${esc(a.market_scope)}</td>
          <td>${esc(a.legal_holder)}</td>
          <td><span class="badge ${a.connection_status === "CONNECTED" ? "ok" : "warn"}">${esc(a.connection_status)}</span></td>
          <td><span class="badge ${a.api_permission_status === "VERIFIED" ? "ok" : "neutral"}">${esc(a.api_permission_status)}</span></td>
          <td>${esc(a.execution_mode)}</td>
        </tr>`).join("")}
      </tbody></table>` : `<div class="kpi-sub">No broker accounts registered yet. Register Zerodha or CoinDCX accounts from the Trading Desks menu.</div>`;
  }

  async function loadErpHub() {
    try {
      const data = await api("/api/v1/company/erp/overview");
      const summary = data.summary || {};
      if ($("erp_kpi_directors")) $("erp_kpi_directors").textContent = `${summary.total_directors || 0} Active`;
      if ($("erp_kpi_banks")) $("erp_kpi_banks").textContent = `${summary.total_bank_accounts || 0} Connected`;
      if ($("erp_kpi_treasury")) $("erp_kpi_treasury").textContent = `₹${summary.total_treasury_inr || "0.00"}`;
      if ($("erp_kpi_depts")) $("erp_kpi_depts").textContent = `${summary.total_departments || 0} Configured`;

      const directors = data.directors || [];
      if ($("erp_directors_body") && directors.length) {
        $("erp_directors_body").innerHTML = directors.map((d) => `
          <tr>
            <td><strong>${esc(d.full_name)}</strong><br><small style="color:#64748b;">${esc(d.email)}</small></td>
            <td><code>${esc(d.din)}</code></td>
            <td>${esc(d.designation)}</td>
            <td><span class="badge ${d.is_active ? "ok" : "warn"}">${d.is_active ? "ACTIVE" : "INACTIVE"}</span></td>
          </tr>
        `).join("");
      }

      const banks = data.bank_accounts || [];
      if ($("erp_banks_body") && banks.length) {
        $("erp_banks_body").innerHTML = banks.map((b) => `
          <tr>
            <td><strong>${esc(b.bank_name)}</strong><br><small style="color:#64748b;">${esc(b.branch)}</small></td>
            <td><code>${esc(b.account_number_masked)}</code></td>
            <td>${esc(b.ifsc_code)}</td>
            <td><strong style="color:var(--green);">₹${esc(b.balance_inr)}</strong></td>
          </tr>
        `).join("");
      }

      const depts = data.departments || [];
      if ($("erp_depts_body") && depts.length) {
        $("erp_depts_body").innerHTML = depts.map((d) => `
          <tr>
            <td><code>${esc(d.dept_code)}</code></td>
            <td>${esc(d.dept_name)}</td>
            <td>Operational Department</td>
            <td>₹${(Number(d.budget_paise || 0) / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
          </tr>
        `).join("");
      }
    } catch (e) {
      notice("Failed to load ERP overview: " + e.message, "err");
    }
  }

  async function registerBroker(provider) {
    const isZd = provider === "ZERODHA";
    const body = {
      provider,
      account_name: $(isZd ? "zd_name" : "cdx_name").value,
      api_key: $(isZd ? "zd_key" : "cdx_key").value,
      api_secret: $(isZd ? "zd_secret" : "cdx_secret").value,
      static_egress_ip: $(isZd ? "zd_ip" : "cdx_ip").value,
      withdrawal_disabled: true,
    };
    const path = isZd ? "/api/v1/company/accounts" : "/api/v1/brokers/coindcx/connect";
    await api(path, { method: "POST", body });
    notice(`${provider} company account saved with encrypted credentials.`, "ok");
    await refreshCurrent();
  }

  async function zerodhaConnectUrl() {
    const res = await api("/api/v1/brokers/zerodha/connect");
    const box = $("zd_login_box");
    box.classList.remove("hide");
    box.innerHTML = `<strong>Kite Login URL (${esc(res.account_id)}):</strong> <a href="${esc(res.login_url)}" target="_blank">${esc(res.login_url)}</a>`;
  }

  async function zerodhaCallback() {
    const req_token = $("zd_req_token").value.trim();
    const res = await api("/api/v1/brokers/zerodha/callback", { method: "POST", body: { request_token: req_token } });
    notice(`Zerodha session verified for ${res.broker_user_id || "account"}.`, "ok");
    await refreshCurrent();
  }

  async function brokerSync(prov) {
    await api(`/api/v1/brokers/${prov}/sync`, { method: "POST", body: {} });
    notice(`${prov.toUpperCase()} verified & synced into its independent capital pool.`, "ok");
    await refreshCurrent();
  }

  async function brokerDisconnect(prov) {
    await api(`/api/v1/brokers/${prov}/disconnect`, { method: "POST", body: {} });
    notice(`${prov.toUpperCase()} session disconnected (open broker positions remain untouched).`, "warn");
    await refreshCurrent();
  }

  async function loadZerodhaView() {
    const st = await api("/api/v1/brokers/zerodha/status");
    const box = $("zd_status_box");
    if (!st.configured) {
      box.innerHTML = "No Zerodha company account registered yet.";
      return;
    }
    const a = st.account || {};
    const p = st.pool || {};
    box.innerHTML = `
      <div><b>Account:</b> <span class="mono">${esc(a.account_id)}</span> (${esc(a.connection_status)} · ${esc(a.api_permission_status)})</div>
      <div><b>Pool Equity (INR):</b> ₹${esc(p.broker_confirmed_equity_inr)} · Free: ₹${esc(p.free_funds_inr)} · Reconciliation: ${esc(p.reconciliation_status)}</div>
      <div><b>Token Expiry:</b> ${tsFmt(a.token_expires_at)}</div>
    `;
  }

  async function loadCoinDCXView() {
    const st = await api("/api/v1/brokers/coindcx/status");
    const box = $("cdx_status_box");
    if (!st.configured) {
      box.innerHTML = "No CoinDCX Spot company account registered yet.";
      return;
    }
    const a = st.account || {};
    const p = st.pool || {};
    const cap = a.capabilities || {};
    box.innerHTML = `
      <div><b>Account:</b> <span class="mono">${esc(a.account_id)}</span> (${esc(a.connection_status)} · ${esc(a.api_permission_status)})</div>
      <div><b>Capabilities:</b> Spot=${cap.supports_spot ? "YES" : "NO"} · Futures=${cap.supports_futures ? "YES" : "NO (BLOCKED)"} · Leverage=${cap.leverage_allowed ? "YES" : "1x ONLY"}</div>
      <div><b>Pool Equity (INR Eqv):</b> ₹${esc(p.broker_confirmed_equity_inr)} · Free: ₹${esc(p.free_funds_inr)}</div>
    `;
  }

  async function tradingControl(pool_id, action) {
    await api(`/api/v1/company/trading/${action}`, { method: "POST", body: { pool_id } });
    notice(`${pool_id}: ${action.toUpperCase()} executed.`, action === "emergency-stop" ? "err" : "ok");
    await refreshCurrent();
  }

  async function flattenPreview(pool_id, execution_mode) {
    const prev = await api("/api/v1/company/trading/flatten-preview", { method: "POST", body: { pool_id, execution_mode } });
    if (prev.open_positions_count === 0) {
      notice(`No open ${execution_mode} positions in ${pool_id}.`, "info");
      return;
    }
    if (confirm(`Preview found ${prev.open_positions_count} open ${execution_mode} positions in ${pool_id}. Confirm submit market exits?`)) {
      await api("/api/v1/company/trading/flatten-confirm", {
        method: "POST",
        body: { pool_id, execution_mode, confirm_token: `CONFIRM_FLATTEN_${pool_id}` },
      });
      notice(`Flatten intents submitted for ${pool_id}.`, "warn");
      await refreshCurrent();
    }
  }

  async function loadStrategiesView() {
    const [sRes, sigRes] = await Promise.all([api("/api/v1/company/strategies"), api("/api/v1/company/signals")]);
    const strats = sRes.strategies || [];
    if ($("sig_strategy_id")) {
      const prev = $("sig_strategy_id").value;
      $("sig_strategy_id").innerHTML = strats
        .map((s) => `<option value="${esc(s.strategy_id)}">${esc(s.strategy_code)} (${esc(s.market_scope)})</option>`)
        .join("");
      if (prev && strats.some((s) => s.strategy_id === prev)) $("sig_strategy_id").value = prev;
    }
    $("strategies_tbl").innerHTML = `
      <table class="tbl"><thead><tr><th>Code</th><th>Market</th><th>Version</th><th>Timeframe</th><th>SL / TP %</th><th>Status</th><th>Paper / Live Pos</th><th>Action</th></tr></thead>
      <tbody>${strats.map((s) => `
        <tr>
          <td><b>${esc(s.strategy_code)}</b><div class="kpi-sub">${esc(s.strategy_name)}</div></td>
          <td>${esc(s.market_scope)}</td>
          <td class="mono">v${esc((s.active_version || {}).version_number || 1)}</td>
          <td>${esc((s.active_version || {}).timeframe)}</td>
          <td class="mono">${esc((s.active_version || {}).stop_loss_pct)}% / ${esc((s.active_version || {}).take_profit_pct)}%</td>
          <td><span class="badge ${s.status === "ACTIVE" ? "ok" : "warn"}">${esc(s.status)}</span></td>
          <td class="mono">${esc(s.paper_positions_count)} / ${esc(s.live_positions_count)}</td>
          <td>
            <button class="btn sm green" onclick="App.setStrategyStatus('${esc(s.strategy_id)}','ACTIVE')">Activate</button>
            <button class="btn sm amber" onclick="App.setStrategyStatus('${esc(s.strategy_id)}','PAUSED')">Pause</button>
            <button class="btn sm" onclick="App.scanStrategy('${esc(s.strategy_id)}', false)">Scan</button>
            <button class="btn sm primary" onclick="App.scanStrategy('${esc(s.strategy_id)}', true)">Scan &amp; Paper OMS</button>
          </td>
        </tr>`).join("")}
      </tbody></table>`;

    const sigs = sigRes.signals || [];
    $("signals_tbl").innerHTML = sigs.length ? `
      <table class="tbl"><thead><tr><th>Time</th><th>Symbol</th><th>Dir</th><th>Entry / SL / TP</th><th>R:R</th><th>Conf</th><th>Status</th><th>Explanation</th><th>OMS Route</th></tr></thead>
      <tbody>${sigs.map((g) => `
        <tr>
          <td>${tsFmt(g.created_at)}</td>
          <td><b>${esc(g.exchange)}:${esc(g.symbol)}</b></td>
          <td><span class="badge info">${esc(g.direction)}</span></td>
          <td class="mono">₹${esc(g.entry_price_str)} / ₹${esc(g.stop_loss_str)} / ₹${esc(g.target_price_str)}</td>
          <td class="mono">${esc(g.risk_reward_ratio)}:1</td>
          <td class="mono">${esc(g.confidence_score)}%</td>
          <td><span class="badge ${String(g.status || "").startsWith("ROUTED_") ? "ok" : (g.status === "RISK_REJECTED" ? "err" : "warn")}">${esc(g.status || "PROPOSED")}</span></td>
          <td>${esc(g.explanation)}</td>
          <td>${g.status === "PROPOSED" ? `<button class="btn sm primary" onclick="App.routeSignalToOms('${esc(g.signal_id)}','PAPER')">Route Paper OMS</button>` : "—"}</td>
        </tr>`).join("")}
      </tbody></table>` : `<div class="kpi-sub">No signals generated yet.</div>`;
  }

  async function createStrategy() {
    const syms = $("st_syms").value.split(",").map((x) => x.trim().toUpperCase()).filter(Boolean);
    await api("/api/v1/company/strategies", {
      method: "POST",
      body: {
        strategy_code: $("st_code").value,
        strategy_name: $("st_name").value,
        market_scope: $("st_scope").value,
        instruments: syms,
        stop_loss_pct: $("st_sl").value,
        take_profit_pct: $("st_tp").value,
      },
    });
    notice("Strategy & immutable v1 snapshot created.", "ok");
    await loadStrategiesView();
  }

  async function setStrategyStatus(id, status) {
    await api(`/api/v1/company/strategies/${id}/status`, { method: "POST", body: { status } });
    await loadStrategiesView();
  }

  async function proposeSignal() {
    const sel = $("sig_strategy_id") ? $("sig_strategy_id").value : "";
    let stratId = sel;
    if (!stratId) {
      const sRes = await api("/api/v1/company/strategies");
      const first = (sRes.strategies || [])[0];
      if (!first) return notice("Create a strategy first.", "warn");
      stratId = first.strategy_id;
    }
    await api("/api/v1/company/signals/propose", {
      method: "POST",
      body: { strategy_id: stratId, symbol: $("sig_symbol").value.trim().toUpperCase() },
    });
    notice("AI Signal proposal generated.", "ok");
    await loadStrategiesView();
  }

  async function scanStrategy(strategyId, autoRoutePaper) {
    const res = await api(`/api/v1/company/strategies/${strategyId}/scan`, {
      method: "POST",
      body: { auto_route_paper: Boolean(autoRoutePaper), use_llm: false },
    });
    notice(`Scanned ${res.scanned_count || 0} instruments via all 8 AraaBot AI engines.`, "ok");
    await loadStrategiesView();
  }

  async function routeSignalToOms(signalId, executionMode) {
    try {
      const res = await api(`/api/v1/company/signals/${signalId}/route-oms`, {
        method: "POST",
        body: { execution_mode: executionMode || "PAPER" },
      });
      notice(`Signal routed to 16-State OMS (${res.signal_status || executionMode}).`, "ok");
    } catch (e) {
      notice(e.message, "warn");
    }
    await loadStrategiesView();
  }

  async function loadOrdersView() {
    const [accRes, ordRes] = await Promise.all([api("/api/v1/company/accounts"), api("/api/v1/company/orders")]);
    const accs = accRes.accounts || [];
    $("ord_acc").innerHTML = accs.length
      ? accs.map((a) => `<option value="${esc(a.account_id)}">${esc(a.provider)} · ${esc(a.account_name)} (${esc(a.account_id)})</option>`).join("")
      : `<option value="">No registered accounts</option>`;

    const orders = ordRes.orders || [];
    $("orders_tbl").innerHTML = orders.length ? `
      <table class="tbl"><thead><tr><th>Order ID</th><th>Provider Ref</th><th>Pool / Mode</th><th>Symbol</th><th>Side</th><th>Qty / Filled</th><th>Avg Fill</th><th>State</th><th>Action</th></tr></thead>
      <tbody>${orders.map((o) => `
        <tr>
          <td class="mono">${esc(o.order_id)}</td>
          <td class="mono">${esc(o.provider_order_id || "—")}</td>
          <td>${esc(o.pool_id)} · <b>${esc(o.execution_mode)}</b></td>
          <td><b>${esc(o.exchange)}:${esc(o.symbol)}</b></td>
          <td>${esc(o.side)}</td>
          <td class="mono">${esc(o.quantity_str)} / ${esc(o.filled_qty_str)}</td>
          <td class="mono">₹${esc(o.avg_fill_price_str)}</td>
          <td><span class="badge ${o.status === "FILLED" ? "ok" : (["REJECTED","RISK_REJECTED","UNKNOWN"].includes(o.status) ? "err" : "warn")}">${esc(o.status)}</span></td>
          <td>${["OPEN","SUBMITTED","ACKNOWLEDGED","PARTIALLY_FILLED"].includes(o.status) ? `<button class="btn sm red" onclick="App.cancelOrder('${esc(o.order_id)}')">Cancel</button>` : "—"}</td>
        </tr>`).join("")}
      </tbody></table>` : `<div class="kpi-sub">No OMS orders recorded yet.</div>`;
  }

  async function submitOrderIntent() {
    const account_id = $("ord_acc").value;
    if (!account_id) return notice("Register a Zerodha or CoinDCX account first.", "warn");
    await api("/api/v1/company/orders/intents", {
      method: "POST",
      body: {
        account_id,
        symbol: $("ord_sym").value,
        side: $("ord_side").value,
        order_type: $("ord_type").value,
        quantity: $("ord_qty").value,
        stop_loss: $("ord_sl").value,
        execution_mode: $("ord_mode").value,
        idempotency_key: `ui_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      },
    });
    notice("Order intent processed through Risk Guardian & OMS.", "ok");
    await loadOrdersView();
  }

  async function cancelOrder(orderId) {
    await api(`/api/v1/company/orders/${orderId}/cancel`, { method: "POST", body: {} });
    notice(`Order ${orderId} cancellation requested.`, "warn");
    await loadOrdersView();
  }

  async function loadPositionsView() {
    const res = await api("/api/v1/company/positions");
    const pos = res.positions || [];
    $("positions_tbl").innerHTML = pos.length ? `
      <table class="tbl"><thead><tr><th>Position ID</th><th>Pool / Mode</th><th>Symbol</th><th>Qty</th><th>Avg Entry</th><th>Current</th><th>Stop Loss</th><th>Realized (Paise)</th><th>Status</th></tr></thead>
      <tbody>${pos.map((p) => `
        <tr>
          <td class="mono">${esc(p.position_id)}</td>
          <td>${esc(p.pool_id)} · <b>${esc(p.execution_mode)}</b></td>
          <td><b>${esc(p.exchange)}:${esc(p.symbol)}</b></td>
          <td class="mono">${esc(p.quantity_str)}</td>
          <td class="mono">₹${esc(p.avg_entry_price_str)}</td>
          <td class="mono">₹${esc(p.current_price_str)}</td>
          <td class="mono">₹${esc(p.stop_loss_str || "—")}</td>
          <td class="mono">${esc(p.realized_pnl_paise)}</td>
          <td><span class="badge ${p.status === "OPEN" ? "info" : "neutral"}">${esc(p.status)}</span></td>
        </tr>`).join("")}
      </tbody></table>` : `<div class="kpi-sub">No open or closed company positions yet.</div>`;
  }

  async function loadFinanceView() {
    const res = await api("/api/v1/company/finance/report");
    const rep = res.report || {};
    const pf = rep.portfolio || {};
    const pools = Object.values(pf.pools || {});
    if ($("finance_pools_cards")) {
      $("finance_pools_cards").innerHTML = pools.map((p) => `
        <div class="card">
          <div class="card-h"><h3 class="card-title">${esc(p.pool_name)} (${esc(p.pool_id)})</h3><span class="badge info">${esc(p.market_scope)}</span></div>
          <div class="form-row">
            <div><div class="kpi-label">Allocated</div><b class="mono">₹${esc(p.allocated_capital_inr)}</b></div>
            <div><div class="kpi-label">Broker Equity</div><b class="mono" style="color:var(--green);">₹${esc(p.broker_confirmed_equity_inr)}</b></div>
            <div><div class="kpi-label">Free Funds</div><b class="mono">₹${esc(p.free_funds_inr)}</b></div>
            <div><div class="kpi-label">Fees / Taxes</div><b class="mono">₹${esc(p.fees_inr)} / ₹${esc(p.taxes_expenses_inr)}</b></div>
          </div>
        </div>`).join("");
    }
    const mvs = rep.movements || [];
    $("finance_mv_tbl").innerHTML = mvs.length ? `
      <table class="tbl"><thead><tr><th>When</th><th>Movement ID</th><th>Pool</th><th>Type</th><th>Amount (INR)</th><th>Classification</th><th>Ref</th></tr></thead>
      <tbody>${mvs.map((m) => `
        <tr>
          <td>${tsFmt(m.created_at)}</td>
          <td class="mono">${esc(m.movement_id)}</td>
          <td>${esc(m.pool_id)}</td>
          <td><b>${esc(m.movement_type)}</b></td>
          <td class="mono">₹${esc(m.amount_inr)}</td>
          <td><span class="badge info">${esc(m.source_classification)}</span></td>
          <td class="mono">${esc(m.reference_no || "—")}</td>
        </tr>`).join("")}
      </tbody></table>` : `<div class="kpi-sub">No capital movements posted yet.</div>`;
  }

  async function recordCapitalMove() {
    await api("/api/v1/company/capital-pools", {
      method: "POST",
      body: {
        pool_id: $("fin_pool").value,
        movement_type: $("fin_type").value,
        amount_inr: $("fin_amt").value,
        reference_no: $("fin_ref").value,
      },
    });
    notice("Accounting capital entry posted to isolated pool.", "ok");
    await loadFinanceView();
  }

  async function exportFinanceCsv() {
    const res = await fetch("/api/v1/company/finance/report?format=csv", {
      headers: { "X-Company-Token": state.token },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
      throw new Error(err.error || `CSV export failed (HTTP ${res.status})`);
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "araa_company_finance.csv";
    a.click();
  }

  async function loadLedgerView() {
    const res = await api("/api/v1/company/ledger");
    const rows = res.entries || [];
    $("ledger_tbl").innerHTML = rows.length ? `
      <table class="tbl"><thead><tr><th>When</th><th>Entry ID</th><th>Pool</th><th>Type</th><th>DR -> CR</th><th>Amount (INR)</th><th>Fee (INR)</th><th>Narration</th></tr></thead>
      <tbody>${rows.map((e) => `
        <tr>
          <td>${tsFmt(e.created_at)}</td>
          <td class="mono">${esc(e.entry_id)}</td>
          <td>${esc(e.pool_id)}</td>
          <td><b>${esc(e.entry_type)}</b></td>
          <td class="mono">${esc(e.debit_account)} -> ${esc(e.credit_account)}</td>
          <td class="mono">₹${esc(e.amount_inr)}</td>
          <td class="mono">₹${esc(e.fee_inr)}</td>
          <td>${esc(e.narration)}</td>
        </tr>`).join("")}
      </tbody></table>` : `<div class="kpi-sub">No LIVE broker-confirmed ledger entries yet (PAPER trades are never written here).</div>`;
  }

  async function loadReconciliationView() {
    const [accRes, rRes] = await Promise.all([api("/api/v1/company/accounts"), api("/api/v1/company/reconciliation")]);
    const accs = accRes.accounts || [];
    $("recon_acc").innerHTML = accs.length
      ? accs.map((a) => `<option value="${esc(a.account_id)}">${esc(a.provider)} (${esc(a.account_id)})</option>`).join("")
      : `<option value="">No registered accounts</option>`;

    const runs = rRes.runs || [];
    $("recon_runs_tbl").innerHTML = runs.length ? `
      <table class="tbl"><thead><tr><th>Run ID</th><th>Pool</th><th>Trigger</th><th>Status</th><th>Mismatches</th><th>Completed</th></tr></thead>
      <tbody>${runs.map((r) => `
        <tr>
          <td class="mono">${esc(r.run_id)}</td>
          <td>${esc(r.pool_id)}</td>
          <td>${esc(r.trigger_source)}</td>
          <td><span class="badge ${r.status === "MATCHED" ? "ok" : "err"}">${esc(r.status)}</span></td>
          <td class="mono">${esc(r.discrepancies_count)}</td>
          <td>${tsFmt(r.completed_at)}</td>
        </tr>`).join("")}
      </tbody></table>` : `<div class="kpi-sub">No reconciliation runs executed yet.</div>`;

    const diffs = rRes.differences || [];
    $("recon_diffs_tbl").innerHTML = diffs.length ? `
      <table class="tbl"><thead><tr><th>Diff ID</th><th>Pool</th><th>Type</th><th>Entity</th><th>Status</th><th>Action</th></tr></thead>
      <tbody>${diffs.map((d) => `
        <tr>
          <td class="mono">${esc(d.diff_id)}</td>
          <td>${esc(d.pool_id)}</td>
          <td><b>${esc(d.diff_type)}</b></td>
          <td>${esc(d.entity_ref)}</td>
          <td><span class="badge ${d.status === "OPEN" ? "err" : "ok"}">${esc(d.status)}</span></td>
          <td>${d.status === "OPEN" ? `<button class="btn sm primary" onclick="App.resolveDiff('${esc(d.diff_id)}')">Resolve</button>` : esc(d.resolution_note)}</td>
        </tr>`).join("")}
      </tbody></table>` : `<div class="kpi-sub">Zero discrepancies recorded.</div>`;
  }

  async function runReconciliation() {
    const account_id = $("recon_acc").value;
    if (!account_id) return notice("Register a broker account first.", "warn");
    await api("/api/v1/company/reconciliation/run", { method: "POST", body: { account_id } });
    notice("Reconciliation scan completed.", "ok");
    await loadReconciliationView();
  }

  async function resolveDiff(diffId) {
    const note = prompt("Enter reconciliation verification / resolution note:");
    if (!note) return;
    await api(`/api/v1/company/reconciliation/differences/${diffId}/resolve`, { method: "POST", body: { resolution_note: note } });
    notice("Discrepancy marked RESOLVED.", "ok");
    await loadReconciliationView();
  }

  async function loadRiskView() {
    const [pRes, eRes] = await Promise.all([api("/api/v1/company/risk/policies"), api("/api/v1/company/risk/events")]);
    const pols = pRes.policies || [];
    $("risk_policies_tbl").innerHTML = `
      <table class="tbl"><thead><tr><th>Pool ID</th><th>Max Order</th><th>Max Position</th><th>Max Open Pos</th><th>Max Daily Loss</th><th>Paused</th><th>Emergency Stop</th></tr></thead>
      <tbody>${pols.map((p) => `
        <tr>
          <td><b>${esc(p.pool_id)}</b></td>
          <td class="mono">₹${esc(p.max_order_value_inr)}</td>
          <td class="mono">₹${esc(p.max_position_size_inr)}</td>
          <td class="mono">${esc(p.max_open_positions)}</td>
          <td class="mono">₹${esc(p.max_daily_loss_inr)}</td>
          <td><span class="badge ${p.paused ? "warn" : "ok"}">${p.paused ? "PAUSED" : "ACTIVE"}</span></td>
          <td><span class="badge ${p.emergency_stop ? "err" : "ok"}">${p.emergency_stop ? "STOPPED" : "ARMED"}</span></td>
        </tr>`).join("")}
      </tbody></table>`;

    const evs = eRes.events || [];
    $("risk_events_tbl").innerHTML = evs.length ? `
      <table class="tbl"><thead><tr><th>When</th><th>Pool</th><th>Rule</th><th>Severity</th><th>Message</th></tr></thead>
      <tbody>${evs.map((e) => `
        <tr>
          <td>${tsFmt(e.created_at)}</td>
          <td>${esc(e.pool_id)}</td>
          <td class="mono">${esc(e.rule_code)}</td>
          <td><span class="badge ${e.severity === "CRITICAL" ? "err" : "warn"}">${esc(e.severity)}</span></td>
          <td>${esc(e.message)}</td>
        </tr>`).join("")}
      </tbody></table>` : `<div class="kpi-sub">No risk vetoes or alerts recorded yet.</div>`;
  }

  async function runBacktest() {
    const res = await api("/api/v1/company/backtests", {
      method: "POST",
      body: {
        symbol: $("bt_sym").value,
        strategy_mode: $("bt_strat").value,
        timeframe: $("bt_tf").value,
        initial_capital: $("bt_cap").value,
      },
    });
    const b = res.backtest || {};
    $("bt_result_box").innerHTML = `
      <div class="alert-banner warn">${esc(res.disclaimer)}</div>
      <div class="grid-4">
        <div class="card"><div class="kpi-label">Net P&amp;L (Sim)</div><div class="kpi-val mono">${esc(b.net_pnl_usd)}</div></div>
        <div class="card"><div class="kpi-label">Win Rate</div><div class="kpi-val mono">${esc(b.win_rate)}% (${esc(b.total_trades)} trades)</div></div>
        <div class="card"><div class="kpi-label">Profit Factor / Sharpe</div><div class="kpi-val mono">${esc(b.profit_factor)} / ${esc(b.sharpe_ratio)}</div></div>
        <div class="card"><div class="kpi-label">Max Drawdown</div><div class="kpi-val mono">${esc(b.max_drawdown_pct)}%</div></div>
      </div>
    `;
  }

  async function loadCompanyProfileView() {
    const [coRes, compRes] = await Promise.all([api("/api/v1/company/profile"), api("/api/v1/company/compliance")]);
    const c = coRes.company || {};
    $("co_name").value = c.legal_name || "";
    $("co_cin").value = c.cin_or_reg_no || "";
    $("co_pan").value = c.pan || "";
    $("co_gst").value = c.gstin || "";

    const recs = compRes.records || [];
    $("compliance_tbl").innerHTML = `
      <table class="tbl"><thead><tr><th>Category</th><th>Requirement</th><th>Authority</th><th>Status</th><th>Update Evidence</th></tr></thead>
      <tbody>${recs.map((r) => `
        <tr>
          <td><b>${esc(r.category)}</b></td>
          <td>${esc(r.title)}<div class="kpi-sub">${esc(r.notes)}</div></td>
          <td>${esc(r.authority)}</td>
          <td><span class="badge ${["VERIFIED_BY_COUNSEL","APPROVED"].includes(r.status) ? "ok" : "warn"}">${esc(r.status)}</span></td>
          <td>
            <div style="display:flex; gap:6px; align-items:center;">
              <select id="cmp_st_${esc(r.record_id)}" style="width:155px;">
                <option value="REQUIRES_REVIEW" ${r.status === "REQUIRES_REVIEW" ? "selected" : ""}>REQUIRES_REVIEW</option>
                <option value="IN_PROGRESS" ${r.status === "IN_PROGRESS" ? "selected" : ""}>IN_PROGRESS</option>
                <option value="VERIFIED_BY_COUNSEL" ${r.status === "VERIFIED_BY_COUNSEL" ? "selected" : ""}>VERIFIED_BY_COUNSEL</option>
              </select>
              <button class="btn sm primary" onclick="App.updateComplianceRecord('${esc(r.record_id)}')">Save</button>
            </div>
          </td>
        </tr>`).join("")}
      </tbody></table>`;
  }

  async function updateComplianceRecord(recordId) {
    const st = $(`cmp_st_${recordId}`) ? $(`cmp_st_${recordId}`).value : "IN_PROGRESS";
    await api(`/api/v1/company/compliance/${recordId}`, {
      method: "PUT",
      body: { status: st, notes: `Updated via Control Center (${st})` },
    });
    notice(`Compliance record ${recordId} updated to ${st}.`, "ok");
    await loadCompanyProfileView();
  }

  async function saveCompanyProfile() {
    await api("/api/v1/company/profile", {
      method: "PUT",
      body: {
        legal_name: $("co_name").value,
        cin_or_reg_no: $("co_cin").value,
        pan: $("co_pan").value,
        gstin: $("co_gst").value,
      },
    });
    notice("Company profile updated.", "ok");
  }

  async function loadEmployeesView() {
    const [rRes, eRes, aRes] = await Promise.all([
      api("/api/v1/company/roles"),
      api("/api/v1/company/employees"),
      api("/api/v1/company/approvals"),
    ]);
    $("emp_role").innerHTML = (rRes.roles || []).map((r) => `<option value="${esc(r.role_code)}">${esc(r.role_name)} (${esc(r.role_code)})</option>`).join("");
    const emps = eRes.employees || [];
    $("employees_tbl").innerHTML = `
      <table class="tbl"><thead><tr><th>ID</th><th>Full Name</th><th>Email</th><th>Role</th><th>MFA</th><th>Status</th><th>Last Login</th></tr></thead>
      <tbody>${emps.map((e) => `
        <tr>
          <td class="mono">${esc(e.id)}</td>
          <td><b>${esc(e.full_name)}</b></td>
          <td class="mono">${esc(e.email)}</td>
          <td><span class="badge info">${esc(e.role_code)}</span></td>
          <td><span class="badge ${e.mfa_enabled ? "ok" : "warn"}">${e.mfa_enabled ? "ENABLED" : "OFF"}</span></td>
          <td><span class="badge ${e.status === "ACTIVE" ? "ok" : "err"}">${esc(e.status)}</span></td>
          <td>${tsFmt(e.last_login_at)}</td>
        </tr>`).join("")}
      </tbody></table>`;

    const aprs = aRes.approvals || [];
    $("approvals_tbl").innerHTML = aprs.length ? `
      <table class="tbl"><thead><tr><th>Approval ID</th><th>Type</th><th>Target</th><th>Requester ID</th><th>Status</th><th>Action</th></tr></thead>
      <tbody>${aprs.map((a) => `
        <tr>
          <td class="mono">${esc(a.approval_id)}</td>
          <td><b>${esc(a.approval_type)}</b></td>
          <td>${esc(a.target_ref)}</td>
          <td class="mono">${esc(a.requested_by)}</td>
          <td><span class="badge ${a.status === "APPROVED" ? "ok" : (a.status === "PENDING" ? "warn" : "err")}">${esc(a.status)}</span></td>
          <td>${a.status === "PENDING" ? `<button class="btn sm green" onclick="App.decideApproval('${esc(a.approval_id)}','APPROVED')">Approve</button> <button class="btn sm red" onclick="App.decideApproval('${esc(a.approval_id)}','REJECTED')">Reject</button>` : esc(a.decision_note || "Finalized")}</td>
        </tr>`).join("")}
      </tbody></table>` : `<div class="kpi-sub">No dual-control approval requests yet.</div>`;
  }

  async function createEmployee() {
    await api("/api/v1/company/employees", {
      method: "POST",
      body: { email: $("emp_email").value, full_name: $("emp_name").value, password: $("emp_pw").value, role_code: $("emp_role").value },
    });
    notice("Employee account created cleanly.", "ok");
    await loadEmployeesView();
  }

  async function enrollMfa() {
    const res = await api("/api/v1/company/auth/mfa/enroll", { method: "POST" });
    const box = $("mfa_enroll_box");
    box.classList.remove("hide");
    box.innerHTML = `
      <div style="font-size:12px; background:#f8fafc; padding:10px; border:1px solid var(--border); border-radius:8px;">
        <div><b>TOTP Secret:</b> <span class="mono">${esc(res.secret)}</span></div>
        <div class="form-row" style="margin-top:8px;">
          <div><input id="mfa_confirm_code" placeholder="Enter 6-digit app code" /></div>
          <div><button class="btn green sm" onclick="App.confirmMfa()">Verify &amp; Enable</button></div>
        </div>
      </div>
    `;
  }

  async function confirmMfa() {
    const code = $("mfa_confirm_code").value.trim();
    const res = await api("/api/v1/company/auth/mfa/verify", { method: "POST", body: { totp: code } });
    notice(`MFA enabled! Save backup codes: ${(res.backup_codes || []).join(", ")}`, "ok");
    await loadEmployeesView();
  }

  async function requestLiveApproval() {
    await api("/api/v1/company/approvals", { method: "POST", body: { approval_type: "LIVE_ACTIVATION", target_ref: "COMPANY_DESK" } });
    notice("Dual-control approval requested (requires a second authorized approver).", "info");
    await loadEmployeesView();
  }

  async function decideApproval(id, decision) {
    await api(`/api/v1/company/approvals/${id}/decide`, { method: "POST", body: { decision, note: `Decided via Control Center` } });
    notice(`Approval ${id}: ${decision}`, "ok");
    await loadEmployeesView();
  }

  async function loadAuditView() {
    const [hRes, aRes] = await Promise.all([
      fetch("/api/v1/company/system/health").then((r) => r.json()),
      api("/api/v1/company/audit-logs"),
    ]);
    const wk = hRes.worker || {};
    $("sys_health_box").innerHTML = `
      <div class="grid-4">
        <div class="card"><div class="kpi-label">Service Status</div><div class="kpi-val">${esc(hRes.status)}</div></div>
        <div class="card"><div class="kpi-label">Secrets Encryption (SECRETS_KEY)</div><div class="kpi-val">${hRes.secrets_encryption_enabled ? "ENABLED" : "NOT SET"}</div></div>
        <div class="card"><div class="kpi-label">Tracked Feed Symbols</div><div class="kpi-val mono">${esc(hRes.tracked_prices_count)}</div></div>
        <div class="card"><div class="kpi-label">Applied DB Migrations</div><div class="kpi-val mono">${esc(hRes.migrations_count)}</div></div>
      </div>
      <div class="kpi-sub" style="margin-top:8px;">
        <b>Background Worker:</b> ${wk.running ? "RUNNING" : "IDLE"} · Cycles: ${esc(wk.cycles_completed || 0)} · Last Run: ${tsFmt(wk.last_run_at)}
      </div>
    `;
    const logs = aRes.audit_logs || [];
    $("audit_tbl").innerHTML = logs.length ? `
      <table class="tbl"><thead><tr><th>When</th><th>Actor</th><th>Role</th><th>Action</th><th>Resource</th><th>Status</th></tr></thead>
      <tbody>${logs.map((l) => `
        <tr>
          <td>${tsFmt(l.created_at)}</td>
          <td class="mono">${esc(l.actor_email || "SYSTEM")}</td>
          <td>${esc(l.actor_role || "—")}</td>
          <td><b>${esc(l.action)}</b></td>
          <td class="mono">${esc(l.resource_type)}:${esc(l.resource_id)}</td>
          <td><span class="badge ${l.status === "SUCCESS" ? "ok" : "err"}">${esc(l.status)}</span></td>
        </tr>`).join("")}
      </tbody></table>` : `<div class="kpi-sub">No audit records yet.</div>`;
  }

  async function loadAiHubView() {
    const hub = await api("/api/v1/company/ai/hub");
    const health = hub.health || {};
    const engines = health.engines || {};
    const providers = health.providers || {};

    $("ai_engines_grid").innerHTML = Object.entries(engines).map(([key, e]) => `
      <div class="card">
        <div class="kpi-label">${esc(key)}</div>
        <div class="kpi-val" style="font-size:15px;">${esc(e.name)}</div>
        <div class="kpi-sub" style="margin-top:6px;">
          <span class="badge ${e.active ? "ok" : "err"}">${e.active ? "CONNECTED" : "OFFLINE"}</span>
          ${esc(e.role)}
        </div>
      </div>
    `).join("");

    const activeLlms = Object.entries(providers)
      .filter(([, p]) => p && p.active)
      .map(([k]) => k.replace(/_/g, " ").toUpperCase());
    $("ai_llm_status_badge").textContent = `${health.connected_engines || 0}/${health.total_engines || 0} Engines · ${activeLlms.join(", ") || "Deterministic Active"}`;
    $("ai_llm_status_badge").className = `badge ${health.status === "HEALTHY" ? "ok" : "info"}`;

    const tr = hub.training || {};
    $("ai_trainer_badge").textContent = `Trainer Runs: ${tr.runs || 0} · Top Symbols: ${(tr.top_symbols || []).join(", ") || "None yet"}`;

    const models = hub.models || [];
    $("ai_models_tbl").innerHTML = models.length ? `
      <table class="tbl"><thead><tr><th>Model ID</th><th>Name</th><th>Provider</th><th>Type</th><th>Accuracy</th><th>Approval</th><th>Default</th></tr></thead>
      <tbody>${models.map((m) => `
        <tr>
          <td class="mono">${esc(m.model_id)}</td>
          <td><b>${esc(m.name)}</b></td>
          <td>${esc(m.provider)}</td>
          <td>${esc(m.model_type)}</td>
          <td class="mono">${esc(m.accuracy_score)}%</td>
          <td><span class="badge ${m.approval_status === "APPROVED" ? "ok" : "warn"}">${esc(m.approval_status)}</span></td>
          <td>${m.is_default ? '<span class="badge info">DEFAULT</span>' : "—"}</td>
        </tr>`).join("")}
      </tbody></table>` : `<div class="kpi-sub">No AI models registered.</div>`;
  }

  async function runAllAiConsensus() {
    const symbol = $("ai_sym").value.trim().toUpperCase();
    const market_scope = $("ai_scope").value;
    const timeframe = $("ai_tf").value;
    const box = $("ai_consensus_result");
    box.innerHTML = "Running all 9 ARAA AI engines...";
    const r = await api("/api/v1/company/ai/analyze", {
      method: "POST",
      body: { symbol, market_scope, timeframe, use_llm: true },
    });
    const eng = r.engines || {};
    box.innerHTML = `
      <div style="border:1px solid var(--border); border-radius:8px; padding:12px; background:#f8fafc;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
          <div><b>${esc(r.symbol)}</b> (${esc(r.pool_id)}) · Spot Price: <span class="mono">${esc(r.price)}</span></div>
          <div>
            <span class="badge ${r.verdict === "PROPOSE_ENTRY" ? "ok" : "warn"}">${esc(r.verdict)} · ${esc(r.direction)}</span>
            <span class="badge info">Ensemble: ${esc(r.ensemble_score)}%</span>
          </div>
        </div>
        <div style="margin-top:8px; font-size:12px; display:grid; grid-template-columns:1fr 1fr; gap:6px;">
          <div><b>Analysis Engine:</b> ${esc((eng.analysis_engine || {}).status)} (RSI ${esc((eng.analysis_engine || {}).rsi_14)})</div>
          <div><b>GRU Prediction:</b> ${esc((eng.prediction_engine || {}).prediction)} (${esc((eng.prediction_engine || {}).confidence)}%)</div>
          <div><b>3-Agent Committee:</b> ${esc((eng.ai_committee || {}).final_action)} (${esc((eng.ai_committee || {}).consensus_score)}%)</div>
          <div><b>Quantum Engine:</b> ${esc((eng.quantum_engine || {}).regime)} (${esc((eng.quantum_engine || {}).consensus_score)}%)</div>
          <div><b>Advisor:</b> ${esc((eng.llm_advisor || {}).name)} -> ${esc((eng.llm_advisor || {}).action)} (${esc((eng.llm_advisor || {}).win_probability)}%)</div>
          <div><b>Bot Trainer:</b> Boost ${esc((eng.bot_trainer || {}).boost)} (${esc((eng.bot_trainer || {}).note)})</div>
          <div><b>SMC + Market DNA:</b> ${esc(((eng.smc_dna || {}).dna || {}).setup_status || "READY")} · Bias ${esc(String(((eng.smc_dna || {}).dna || {}).historical_bias || "neutral").toUpperCase())} (${esc(((eng.smc_dna || {}).dna || {}).similarity_pct || 0)}% twin)</div>
          <div><b>Liquidity &amp; Fib 61.8%:</b> Fib $${esc(((eng.smc_dna || {}).liquidity || {}).fib_618 || "--")} · OBs ${esc((((eng.smc_dna || {}).order_blocks) || []).length)} · FVGs ${esc((((eng.smc_dna || {}).fvgs) || []).length)}</div>
        </div>
        <div class="kpi-sub" style="margin-top:8px;">${esc(r.rationale)}</div>
        <div style="margin-top:10px; display:flex; gap:8px; flex-wrap:wrap;">
          <button class="btn sm primary" onclick="App.proposeFromAiHub('${esc(r.symbol)}','${esc(r.market_scope)}', false)">Save Signal Proposal</button>
          <button class="btn sm green" onclick="App.proposeFromAiHub('${esc(r.symbol)}','${esc(r.market_scope)}', true)">Save &amp; Route Paper OMS</button>
        </div>
      </div>
    `;

    const smc = eng.smc_dna || {};
    const dna = smc.dna || {};
    const liq = smc.liquidity || {};
    const obs = Array.isArray(smc.order_blocks) ? smc.order_blocks : [];
    const fvgs = Array.isArray(smc.fvgs) ? smc.fvgs : [];
    const timeline = Array.isArray(smc.timeline) ? smc.timeline : [];
    if ($("company_smc_status_badge")) {
      $("company_smc_status_badge").textContent = `${esc(r.symbol)} · ${esc(dna.setup_status || "NO_QUALIFIED_SETUP")} (${esc(dna.similarity_pct || 0)}% DNA twin)`;
    }
    if ($("company_smc_dna_box")) {
      const bias = String(dna.historical_bias || "neutral").toUpperCase();
      const biasBadge = bias === "BULLISH" ? "ok" : bias === "BEARISH" ? "warn" : "info";
      const bsl = (liq.bsl || {}).price;
      const ssl = (liq.ssl || {}).price;
      $("company_smc_dna_box").innerHTML = `
        <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:10px; margin-bottom:12px;">
          <div style="padding:10px; border:1px solid var(--border); border-radius:8px; background:#f8fafc;">
            <div class="kpi-sub">Market DNA Twin Match</div>
            <div style="font-size:16px; font-weight:700;">${esc(dna.similarity_pct || 0)}% <span class="badge ${biasBadge}">${esc(bias)}</span></div>
          </div>
          <div style="padding:10px; border:1px solid var(--border); border-radius:8px; background:#f8fafc;">
            <div class="kpi-sub">BSL / SSL Liquidity</div>
            <div class="mono" style="font-size:13px; font-weight:700;">BSL $${esc(bsl ?? "--")} / SSL $${esc(ssl ?? "--")}</div>
          </div>
          <div style="padding:10px; border:1px solid var(--border); border-radius:8px; background:#f8fafc;">
            <div class="kpi-sub">Fib 61.8% / 50%</div>
            <div class="mono" style="font-size:13px; font-weight:700;">$${esc(liq.fib_618 ?? "--")} / $${esc(liq.fib_50 ?? "--")}</div>
          </div>
          <div style="padding:10px; border:1px solid var(--border); border-radius:8px; background:#f8fafc;">
            <div class="kpi-sub">Institutional Zones</div>
            <div style="font-size:13px; font-weight:700;">${obs.length} Order Blocks · ${fvgs.length} FVGs</div>
          </div>
        </div>
        <div class="kpi-sub" style="margin-bottom:8px;">${esc(dna.condition_note || "Historical Market DNA & Smart Money structure overview.")}</div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:12px;">
          <div style="padding:8px; border:1px solid var(--border); border-radius:8px;">
            <b>Active Order Blocks (${obs.length})</b>
            ${obs.length ? obs.slice(0, 4).map((o) => `<div style="margin-top:4px;">${esc(String(o.type || "").toUpperCase())} OB · $${esc(o.low)}–$${esc(o.high)} (${o.mitigated ? "Mitigated" : "Unmitigated"})</div>`).join("") : '<div class="kpi-sub">None detected</div>'}
          </div>
          <div style="padding:8px; border:1px solid var(--border); border-radius:8px;">
            <b>Fair Value Gaps (${fvgs.length})</b>
            ${fvgs.length ? fvgs.slice(0, 4).map((f) => `<div style="margin-top:4px;">${esc(String(f.type || "").toUpperCase())} FVG · $${esc(f.low)}–$${esc(f.high)} (${f.mitigated ? "Mitigated" : "Open"})</div>`).join("") : '<div class="kpi-sub">None detected</div>'}
          </div>
        </div>
        <div class="tbl-wrap">
          <table class="tbl">
            <thead><tr><th>Time</th><th>Symbol</th><th>TF</th><th>Event</th><th>Bias</th><th>Price</th></tr></thead>
            <tbody>${timeline.length ? timeline.map((ev) => `
              <tr>
                <td>${esc(ev.time || "--")}</td>
                <td><b>${esc(ev.symbol || r.symbol)}</b></td>
                <td>${esc(ev.tf || timeframe)}</td>
                <td>${esc(ev.event || "--")}</td>
                <td><span class="badge ${String(ev.bias || "").toLowerCase() === "bullish" ? "ok" : String(ev.bias || "").toLowerCase() === "bearish" ? "warn" : "info"}">${esc(String(ev.bias || "neutral").toUpperCase())}</span></td>
                <td class="mono">$${esc(ev.price ?? "--")}</td>
              </tr>`).join("") : '<tr><td colspan="6" class="kpi-sub">No confirmed structure events yet.</td></tr>'}
            </tbody>
          </table>
        </div>
      `;
    }
  }

  async function proposeFromAiHub(symbol, marketScope, routePaper) {
    const sRes = await api("/api/v1/company/strategies");
    const match = (sRes.strategies || []).find((s) => s.market_scope === marketScope) || (sRes.strategies || [])[0];
    if (!match) return notice("No matching strategy found for pool.", "warn");
    const sigRes = await api("/api/v1/company/signals/propose", {
      method: "POST",
      body: { strategy_id: match.strategy_id, symbol, use_llm: false },
    });
    if (routePaper && sigRes.signal && sigRes.signal.signal_id) {
      await routeSignalToOms(sigRes.signal.signal_id, "PAPER");
    } else {
      notice(`Signal proposal created for ${symbol}.`, "ok");
    }
  }

  async function sendAiChat() {
    const inp = $("ai_chat_input");
    const msg = inp.value.trim();
    if (!msg) return;
    inp.value = "";
    const log = $("ai_chat_log");
    log.textContent += `\n\n> You: ${msg}\nThinking across all AI engines...`;
    log.scrollTop = log.scrollHeight;
    try {
      const res = await api("/api/v1/company/ai/chat", {
        method: "POST",
        body: { message: msg, current_page: "AI_HUB", symbol: $("ai_sym") ? $("ai_sym").value.trim() : "" },
      });
      log.textContent = log.textContent.replace(/\nThinking across all AI engines\.\.\.$/, "") + `\n[ARAA AI · ${res.latency_ms}ms]\n${res.response}`;
      log.scrollTop = log.scrollHeight;
    } catch (e) {
      log.textContent += `\n[Error] ${e.message}`;
    }
  }

  function quickAiPrompt(msg) {
    $("ai_chat_input").value = msg;
    sendAiChat();
  }

  async function runAiTrainer() {
    const res = await api("/api/v1/company/ai/train", { method: "POST", body: {} });
    notice(`Walk-forward Bot Trainer complete (run #${(res.training || {}).runs || 1}).`, "ok");
    await loadAiHubView();
  }

  async function runWorkerOnce() {
    const res = await api("/api/v1/company/worker/run-once", { method: "POST", body: { auto_route_paper: false } });
    notice(`Worker cycle complete: ${((res.reconciled_accounts || []).length)} accounts reconciled, ${((res.scanned_strategies || []).length)} active strategies scanned.`, "ok");
    await loadAuditView();
  }

  function _wrapAction(fn) {
    return function (...args) {
      try {
        const ret = fn.apply(this, args);
        if (ret && typeof ret.catch === "function") {
          return ret.catch((e) => {
            notice((e && e.message) || "Action failed", "err");
          });
        }
        return ret;
      } catch (e) {
        notice((e && e.message) || "Action failed", "err");
      }
    };
  }

  function applyCompanyTheme(theme) {
    if (theme === "dark") {
      document.documentElement.setAttribute("data-theme", "dark");
      if ($("co_theme_btn")) $("co_theme_btn").innerHTML = "☀️ Light";
    } else {
      document.documentElement.removeAttribute("data-theme");
      if ($("co_theme_btn")) $("co_theme_btn").innerHTML = "🌙 Dark";
    }
    localStorage.setItem("araa_theme", theme);
  }

  function toggleTheme() {
    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
    applyCompanyTheme(isDark ? "light" : "dark");
  }

  const _rawApp = {
    toggleTheme,
    nav,
    refreshCurrent,
    submitAuth,
    logout,
    registerBroker,
    zerodhaConnectUrl,
    zerodhaCallback,
    brokerSync,
    brokerDisconnect,
    tradingControl,
    flattenPreview,
    loadAiHubView,
    runAllAiConsensus,
    sendAiChat,
    quickAiPrompt,
    runAiTrainer,
    runWorkerOnce,
    proposeFromAiHub,
    createStrategy,
    setStrategyStatus,
    scanStrategy,
    proposeSignal,
    routeSignalToOms,
    submitOrderIntent,
    cancelOrder,
    recordCapitalMove,
    exportFinanceCsv,
    runReconciliation,
    resolveDiff,
    runBacktest,
    saveCompanyProfile,
    updateComplianceRecord,
    createEmployee,
    enrollMfa,
    confirmMfa,
    requestLiveApproval,
    decideApproval,
  };
  window.App = Object.fromEntries(Object.entries(_rawApp).map(([k, v]) => [k, _wrapAction(v)]));

  window.addEventListener("DOMContentLoaded", async () => {
    applyCompanyTheme(localStorage.getItem("araa_theme") || "dark");
    const ok = await checkAuth();
    if (ok) await refreshCurrent();
  });
})();

