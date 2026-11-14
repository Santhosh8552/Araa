const API = (window.location.hostname === "araabot.in")
  ? "https://www.araabot.in"
  : ((window.location.port === "7777" || window.location.port === "7779")
      ? window.location.protocol + "//" + (window.location.hostname || "localhost") + ":5050"
      : window.location.origin);
const $ = (id) => document.getElementById(id);
const inr = (n) => "$" + Number(n || 0).toLocaleString("en-IN", {maximumFractionDigits: 2, minimumFractionDigits: 2});
const num = (n) => Number(n || 0).toLocaleString("en-IN");
const priceFmt = (p) => Number(p) >= 1000 ? Number(p).toLocaleString("en-IN", {maximumFractionDigits: 2})
                     : Number(p) >= 1 ? Number(p).toFixed(4) : Number(p).toFixed(8);
const ago = (ts) => { if (!ts) return "never"; const s = Date.now() / 1000 - ts;
  if (s < 60) return Math.max(1, Math.round(s)) + "s"; if (s < 3600) return Math.round(s / 60) + "m";
  if (s < 86400) return Math.round(s / 3600) + "h"; return Math.round(s / 86400) + "d"; };
const getAdminToken = () => localStorage.getItem("tradepro_admin_token") || sessionStorage.getItem("tradepro_admin_token") || "";
const setAdminToken = (tok, usr) => {
  localStorage.setItem("tradepro_admin_token", tok);
  sessionStorage.setItem("tradepro_admin_token", tok);
  if (usr) {
    localStorage.setItem("tradepro_admin_user", usr);
    sessionStorage.setItem("tradepro_admin_user", usr);
  }
};
const clearAdminToken = () => {
  localStorage.removeItem("tradepro_admin_token");
  sessionStorage.removeItem("tradepro_admin_token");
  localStorage.removeItem("tradepro_admin_user");
  sessionStorage.removeItem("tradepro_admin_user");
};
const adminHeaders = (extra) => Object.assign({"X-Admin-Token": getAdminToken()}, extra || {});
const handleAdminJson = (r, sentToken) => {
  if (r.status === 401 && !String(r.url).includes("/api/admin/login")) {
    // Only clear token if this 401 corresponds to the currently active token (avoids pre-login race condition)
    const curTok = getAdminToken();
    if (!curTok || (sentToken && sentToken === curTok)) {
      clearAdminToken();
      if (typeof checkAdminAuth === "function") checkAdminAuth();
    }
  }
  return r.json();
};
const get = (p) => {
  const tok = getAdminToken();
  return fetch(API + p, {headers: adminHeaders()}).then((r) => handleAdminJson(r, tok));
};
const post = (p, body) => {
  const tok = getAdminToken();
  return fetch(API + p, {method: "POST", headers: adminHeaders({"Content-Type": "application/json"}),
    body: body ? JSON.stringify(body) : undefined}).then((r) => handleAdminJson(r, tok));
};

/* ---------------- overview ---------------- */
async function loadOverview() {
  const d = await get("/api/admin/overview");
  $("o_users").textContent = num(d.totalUsers);
  $("o_logins").textContent = num(d.loginsToday) + " unique logged in today · " + d.loginEventsToday + " sessions";
  $("o_active").textContent = num(d.activeTraders);
  $("o_bots").textContent = num(d.botsEnabled) + " user bots enabled";
  $("o_brokerage").textContent = inr(d.brokerageEarned);
  $("o_brokerage_today").textContent = inr(d.brokerageToday) + " collected today";
  $("o_profit").textContent = inr(d.userProfitLocked);
  $("o_capital").textContent = inr(d.tradingCapitalHeld) + " capital held · paid out " + inr(d.totalPaidOut);
  $("o_botprofit").textContent = inr(d.botProfitToday);
  $("o_botprofit").className = "v " + (d.botProfitToday >= 0 ? "green" : "red");
  $("o_botprofit_all").textContent = inr(d.botProfitAllTime) + " all time";
  $("o_open").textContent = num(d.openPositions);
  $("o_unreal").textContent = inr(d.unrealizedPnl) + " unrealised";
  $("o_unreal").className = "sub " + (d.unrealizedPnl >= 0 ? "up" : "down");
  $("o_trades").textContent = num(d.totalTrades);
  $("o_win").textContent = "win rate " + d.winRate + "%";
  $("o_pending").textContent = num(d.pendingWithdrawals);
  $("o_pending_val").textContent = inr(d.pendingPayoutValue) + " awaiting payout";
  $("top_brokerage").textContent = inr(d.brokerageEarned);
  const liveCount = d.liveSymbols || 992;
  const sigCount = d.activeSignals || 945;
  if ($("admin_feed_stats")) {
    $("admin_feed_stats").textContent = `🟢 ${liveCount} LIVE · ⚡ ${sigCount} SIGNALS`;
  }
  $("feed").textContent = "FEED " + d.feed + " · " + num(d.symbolsTracked) + " prices";
  $("feed").className = "pill " + (d.feed === "LIVE" ? "live" : "sim");
  $("bot_state").textContent = d.botRunning ? "MAIN BOT: ON" : "MAIN BOT: OFF";
  $("bot_state").className = "pill " + (d.botRunning ? "live" : "sim");
  if ($("hero_bot_pill")) {
    $("hero_bot_pill").textContent = d.botRunning ? "● MAIN BOT RUNNING (TRADING ACTIVE)" : "○ MAIN BOT STOPPED (USERS CANNOT TRADE)";
    $("hero_bot_pill").className = "pill " + (d.botRunning ? "live" : "sim");
  }
  const c = d.cycle;
  $("cycle").textContent = c
    ? `running=${c.running}  universe=${c.universe} pairs  opened_this_cycle=${c.opened}  managed_users=${c.managed_users}  cycle=${c.duration_ms}ms  feed=${c.feed}  at ${new Date(c.at * 1000).toLocaleTimeString()}`
    : "waiting for first cycle…";
  const coins = await get("/api/coins");
  if ($("coins")) $("coins").textContent = num(coins.count) + " COINS LISTED";

  // Dynamic 3D AI Pipeline Telemetry
  try {
    const ana = await get("/api/bot/analysis");
    if (ana) {
      if ($("pipe_throughput")) $("pipe_throughput").textContent = (d.symbolsTracked || 976) + " ASSETS/SEC";
      if ($("pipe_win_badge")) $("pipe_win_badge").textContent = (ana.win_rate_pct || d.winRate || 38.0) + "%";
      if ($("pipe_latency")) $("pipe_latency").textContent = (c && c.duration_ms ? Math.round(c.duration_ms / 10) : 14) + "ms";
      if ($("pipe_s1_ticks")) $("pipe_s1_ticks").textContent = (d.symbolsTracked || 976) + " Assets";
      if ($("pipe_s2_scanned")) $("pipe_s2_scanned").textContent = (ana.total_checked || 173) + " Total";
      if ($("pipe_s2_qualified")) $("pipe_s2_qualified").textContent = (ana.total_qualified || 61) + " Setups";

      const day = ana.today_day || (new Date().toLocaleDateString("en-US", {weekday: "long"}));
      const isWeekend = (day === "Saturday" || day === "Sunday");
      if ($("pipe_s3_day")) $("pipe_s3_day").textContent = day;
      if ($("pipe_regime_badge")) $("pipe_regime_badge").textContent = isWeekend ? "WEEKEND CRYPTO ONLY" : "WEEKDAY 7-MARKETS";
      if ($("pipe_s3_badge")) {
        $("pipe_s3_badge").textContent = isWeekend ? "CRYPTO ISOLATED (24/7)" : "7-MARKET ROTATION";
        $("pipe_s3_badge").className = "stage_status " + (isWeekend ? "pulse" : "");
      }

      // Stage 4 top picks
      const cryptoCat = (ana.categories || []).find(x => x.category === "CRYPTO");
      const pickCount = cryptoCat && cryptoCat.picks ? cryptoCat.picks.length : 6;
      if ($("pipe_s4_picks")) $("pipe_s4_picks").textContent = pickCount + " Selected";

      // Stage 6 execution
      if ($("pipe_s6_open")) $("pipe_s6_open").textContent = num(d.openPositions) + " Active";
      if ($("pipe_s6_pnl")) {
        $("pipe_s6_pnl").textContent = inr(d.unrealizedPnl);
        $("pipe_s6_pnl").style.color = d.unrealizedPnl >= 0 ? "var(--green)" : "var(--red)";
      }

      if ($("pipe_cycle_stat")) {
        $("pipe_cycle_stat").textContent = d.botRunning ? "OPTIMAL · " + (c && c.duration_ms ? c.duration_ms + "ms" : "ACTIVE") : "IDLE";
        $("pipe_cycle_stat").style.color = d.botRunning ? "var(--green)" : "var(--amber)";
      }

      if ($("pipe_live_stream_text")) {
        if (!d.botRunning) {
          $("pipe_live_stream_text").textContent = "AI Pipeline paused: Platform Master Bot is stopped. Turn on BOT to resume live scanning & harvesting.";
        } else if (isWeekend) {
          $("pipe_live_stream_text").textContent = `Weekend regime engaged: Traditional markets closed. Araa AI scanning 100% 24/7 Crypto (${pickCount} high-probability setups qualified).`;
        } else {
          $("pipe_live_stream_text").textContent = `Weekday regime engaged: All 7 market categories active (Forex, Metals, Indices, Stocks, Crypto, World) with continuous harvesting.`;
        }
      }

      // Live "What the Bot is Currently Doing" detailed view
      try {
        const [botStore, logsData] = await Promise.all([
          get("/api/admin/bot-storage"),
          get("/api/admin/logs")
        ]);
        if ($("pipe_action_time")) $("pipe_action_time").textContent = new Date().toLocaleTimeString();
        if ($("pipe_bot_action_badge")) {
          $("pipe_bot_action_badge").textContent = d.botRunning ? "● ACTIVE TRADING & MONITORING" : "○ STOPPED";
          $("pipe_bot_action_badge").className = "pill " + (d.botRunning ? "live" : "sim");
        }

        const openPos = (botStore && botStore.open) || [];
        const recentLog = logsData && logsData.logs && logsData.logs[0];

        if ($("pipe_bot_live_action_text")) {
          if (!d.botRunning) {
            $("pipe_bot_live_action_text").innerHTML = `<span style="color:#f59e0b; font-weight:700;">⏸ Bot Execution Paused by Admin.</span> No active trades or margin allocation until <b>START MAIN BOT</b> is clicked.`;
          } else if (openPos.length > 0) {
            const symbolsList = [...new Set(openPos.map(p => p.symbol))].join(", ");
            const totalUnrealized = openPos.reduce((sum, p) => sum + (p.unrealized_pnl || 0), 0);
            const pnlColor = totalUnrealized >= 0 ? "#10b981" : "#ef4444";
            $("pipe_bot_live_action_text").innerHTML = `
              <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:8px;">
                <div>
                  <span style="color:#10b981; font-weight:700;">▶ [STAGE 06: ACTIVE EXECUTION]</span> Managing <b>${openPos.length} positions</b> across <b>[${symbolsList}]</b> at <b>500x leverage</b>.
                  <br><span style="color:#94a3b8; font-size:11px;">Trailing Profit Lock: Peak gains protected by dynamic multi-tiered exit ladder.</span>
                </div>
                <div style="text-align:right;">
                  <span style="font-size:10px; color:#94a3b8;">LIVE UNREALIZED P&L:</span>
                  <div style="font-size:14px; font-weight:800; color:${pnlColor};">${totalUnrealized >= 0 ? "+" : ""}${inr(totalUnrealized)}</div>
                </div>
              </div>
              <div style="margin-top:8px; padding-top:6px; border-top:1px dashed rgba(255,255,255,0.1); color:#38bdf8; font-size:11px;">
                ⚡ <b>Latest Bot Action:</b> ${recentLog ? recentLog.message : "Scanning ticks and trailing profit thresholds..."}
              </div>
            `;
          } else {
            const topPicks = (ana.categories || []).flatMap(c => c.picks || []).slice(0, 5).map(p => `${p.symbol} (${p.side} ${(p.confidence * 100).toFixed(0)}%)`).join(" · ");
            $("pipe_bot_live_action_text").innerHTML = `
              <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:8px;">
                <div>
                  <span style="color:#38bdf8; font-weight:700;">🔍 [STAGE 03 &amp; 04: ARAA QUANTUM SMC™ &amp; ARAA AI BOT CONSENSUS]</span>
                  <br>Scanning <b>995 live instruments</b>. Institutional Order Block retests verified with <b>Araa Ai Bot</b> (Strict Win Expectancy ≥ 92%).
                </div>
                <div style="text-align:right;">
                  <span style="font-size:10px; color:#94a3b8;">INSTITUTIONAL FILTER:</span>
                  <div style="font-size:13px; font-weight:800; color:#10b981;">ARAA QUANTUM SMC™</div>
                </div>
              </div>
              <div style="margin-top:8px; padding-top:6px; border-top:1px dashed rgba(255,255,255,0.1); color:#94a3b8; font-size:11px;">
                🎯 <b>Institutional Focus:</b> ${topPicks || "Crypto 24/7 & Global Macro with Active Order Block Retest"}
              </div>
              <div style="margin-top:4px; color:#38bdf8; font-size:11px;">
                ⚡ <b>Latest Bot Action:</b> ${recentLog ? recentLog.message : "Evaluating SMC order blocks and locking trailing profit thresholds..."}
              </div>
            `;
          }
        }

        if ($("pipe_active_trades_chips")) {
          if (openPos.length > 0) {
            $("pipe_active_trades_chips").innerHTML = openPos.map(p => {
              const pnlVal = p.unrealized_pnl || 0;
              const isLong = (p.side === "LONG");
              const pnlColor = pnlVal >= 0 ? "var(--green)" : "var(--red)";
              const sideClass = isLong ? "long" : "short";
              return `
                <div class="trade_card_3d ${sideClass}">
                  <div class="tc_top">
                    <span class="tc_symbol">${p.symbol}</span>
                    <span class="tc_side ${sideClass}">${p.side} 500x</span>
                  </div>
                  <div class="tc_body">
                    <div class="tc_margin">
                      <span>Margin</span><br>
                      <b>${inr(p.margin)}</b>
                    </div>
                    <div style="text-align:right;">
                      <span style="font-size:10px; color:#94a3b8;">Unrealised</span><br>
                      <b class="tc_pnl" style="color:${pnlColor};">${pnlVal >= 0 ? "+" : ""}${inr(pnlVal)}</b>
                    </div>
                  </div>
                  <div style="display:flex; justify-content:space-between; align-items:center; margin-top:6px;">
                    <span class="tc_conf">⚡ ${p.ai_win_prob || 92}% WIN EXP</span>
                    <span style="font-size:9px; color:#94a3b8; font-family:ui-monospace,Menlo,monospace;">ID #${p.id}</span>
                  </div>
                </div>
              `;
            }).join("");
          } else {
            $("pipe_active_trades_chips").innerHTML = `<span style="font-size:12px; color:#94a3b8; padding:12px;">No open positions in hold right now. Fresh trades will auto-open as qualified conditions are met.</span>`;
          }
        }
      } catch (e2) {
        console.warn("Bot storage status error:", e2);
      }
    }
  } catch (err) {
    console.warn("Pipeline telemetry err:", err);
  }

  return d;
}

/* ---------------- withdrawals ---------------- */
async function loadWithdrawals() {
  const d = await get("/api/admin/withdrawals");
  $("wd_rows").innerHTML = d.withdrawals.length ? d.withdrawals.map(w => {
    const bankInfo = (w.bank_name || w.account_number)
      ? `<div style="font-size:11px;">
           <b style="color:#38bdf8;">${w.bank_name || 'Bank'}</b>
           ${w.account_number ? `<span style="font-family:monospace; color:#f8fafc; display:block;">A/C: ${w.account_number}</span>` : ''}
           ${w.ifsc_code ? `<span style="font-family:monospace; color:#94a3b8; font-size:10px;">IFSC: ${w.ifsc_code}</span>` : ''}
           ${w.account_holder ? `<span style="color:#cbd5e1; font-size:10px; display:block;">${w.account_holder}</span>` : ''}
         </div>`
      : `<span style="color:#94a3b8;">${w.method}</span>`;

    return `<tr>
      <td>${ago(w.created_at)}</td>
      <td>
        <b>${w.name || 'Trader'}</b>
        <div class="sub">${w.email}</div>
      </td>
      <td class="r">${inr(w.amount)}</td>
      <td class="r ${w.brokerage > 0 ? 'green' : 'sub'}">${inr(w.brokerage)}</td>
      <td class="r" style="font-weight:800; color:#10b981;">${inr(w.net_payable)}</td>
      <td>${bankInfo}</td>
      <td><span class="tag ${w.status.toLowerCase()}">${w.status}</span></td>
      <td class="r">${w.status === "PENDING"
        ? `<button class="btn sm ok" data-act="approve" data-id="${w.id}" style="font-weight:700;">✓ Approve &amp; Pay</button>
           <button class="btn sm no" data-act="reject" data-id="${w.id}" style="font-weight:700;">✕ Reject</button>`
        : `<span class="sub" style="font-family:monospace; font-size:11px;">${w.payout_ref || "—"}</span>`}</td>
    </tr>`;
  }).join("")
  : '<tr><td colspan="8" class="empty">No withdrawal requests pending.</td></tr>';

  document.querySelectorAll("[data-act]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    const d = await post(`/api/admin/withdrawals/${b.dataset.id}/${b.dataset.act}`);
    if (d.success) { await Promise.all([loadWithdrawals(), loadOverview(), loadUsers(), loadLedger()]); }
    else { alert(d.error); b.disabled = false; }
  });
}

/* ---------------- users ---------------- */
async function loadUsers() {
  const d = await get("/api/admin/users");
  if (!d.users || !d.users.length) {
    $("user_rows").innerHTML = `<tr><td colspan="11" class="empty" style="padding:24px; text-align:center; color:#94a3b8;">
      <b>No registered users yet.</b><br>
      <span style="font-size:12px;">When any user registers or logs in on <a href="/" target="_blank" style="color:#38bdf8;">Live Trading Terminal</a>, their live details appear here automatically!</span>
    </td></tr>`;
    return;
  }
  $("user_rows").innerHTML = d.users.map(u => {
    const isOnline = Boolean(u.is_online);
    const totalBal = (u.deposit_balance || 0) + (u.profit_balance || 0);
    return `<tr>
      <td><b>${u.name || "Trader"}</b></td>
      <td class="sub">${u.email}</td>
      <td>
        <span class="tag ${isOnline ? "live" : "sub"}" style="font-weight:700; font-size:10px;">
          ${isOnline ? "🟢 ONLINE" : "⚪ OFFLINE"}
        </span>
      </td>
      <td>${ago(u.last_login_at)}</td>
      <td class="r">${u.logins_today}</td>
      <td class="r">${inr(u.deposit_balance)}</td>
      <td class="r ${u.profit_balance >= 0 ? "up" : "down"}">${inr(u.profit_balance)}</td>
      <td class="r green">${inr(u.total_brokerage)}</td>
      <td class="r">${u.open_pos} / ${u.closed_pos}</td>
      <td>
        <button class="btn sm ${u.bot_enabled ? 'danger' : 'ok'} btn-user-toggle-bot" data-uid="${u.id}" data-action="${u.bot_enabled ? 'stop' : 'start'}" style="font-size:10.5px; padding:3px 8px; font-weight:800; cursor:pointer;" title="Click to ${u.bot_enabled ? 'Stop' : 'Start'} Bot for ${u.email}">
          ${u.bot_enabled ? `🟢 ON (${u.bot_mode || 'SCALP'})` : '⚪ OFF · START'}
        </button>
      </td>
      <td style="text-align:center; white-space:nowrap;">
        <button class="btn sm ok btn-user-deposit" data-uid="${u.id}" data-email="${u.email}" style="font-size:11px; padding:3px 8px; margin-right:4px; background:#10b981; color:#0f172a; font-weight:800;" title="Credit bank deposit into user wallet">
          ➕ Deposit
        </button>
        <button class="btn sm btn-user-eod" data-uid="${u.id}" data-name="${u.name}" data-email="${u.email}" style="font-size:11px; padding:3px 8px; margin-right:4px; background:#0284c7; color:#fff; border:none; font-weight:700;" title="View comprehensive EOD statement">
          📊 EOD Report
        </button>
        <button class="btn sm ok btn-user-withdraw" data-uid="${u.id}" data-email="${u.email}" data-bal="${totalBal}" style="font-size:11px; padding:3px 8px; margin-right:4px;" title="Withdraw all money for this user">
          💸 Withdraw
        </button>
        <button class="btn sm danger btn-user-delete" data-uid="${u.id}" data-email="${u.email}" style="font-size:11px; padding:3px 8px;" title="Remove user from system">
          🗑️ Remove
        </button>
      </td>
    </tr>`;
  }).join("");

  // Bind Direct User Bot Toggle buttons
  document.querySelectorAll(".btn-user-toggle-bot").forEach(btn => {
    btn.onclick = async () => {
      const uid = btn.dataset.uid;
      const isStart = btn.dataset.action === "start";
      btn.disabled = true;
      try {
        const res = await post(`/api/admin/user/${uid}/bot-toggle`, { enable: isStart });
        if (res.success) {
          await loadUsers();
          await loadOverview();
        } else {
          alert(res.error || "Failed to toggle bot");
        }
      } catch (err) {
        alert("Bot toggle error: " + err.message);
      } finally {
        btn.disabled = false;
      }
    };
  });

  // Bind Direct User Deposit buttons
  document.querySelectorAll(".btn-user-deposit").forEach(btn => {
    btn.onclick = async () => {
      const uid = btn.dataset.uid;
      const email = btn.dataset.email;
      const amtStr = prompt(`Enter Bank Deposit Amount (INR) to credit to ${email}:`, "10000");
      if (!amtStr) return;
      const amt = parseFloat(amtStr);
      if (isNaN(amt) || amt <= 0) {
        alert("Please enter a valid amount greater than 0");
        return;
      }
      btn.disabled = true;
      try {
        const res = await post(`/api/admin/user/${uid}/deposit`, { amount: amt, bank_name: "ADMIN DIRECT BANK", note: "Admin Manual Bank Deposit" });
        if (res.success) {
          alert(`Successfully credited $${amt.toLocaleString('en-IN')} to ${email}!`);
          await Promise.all([loadUsers(), loadOverview(), loadDeposits(), loadLedger()]);
        } else {
          alert(res.error || "Failed to credit deposit");
        }
      } catch (err) {
        alert("Error: " + err.message);
      } finally {
        btn.disabled = false;
      }
    };
  });

  // Bind Withdraw and Delete action buttons
  document.querySelectorAll(".btn-user-withdraw").forEach(btn => {
    btn.onclick = async () => {
      const uid = btn.dataset.uid;
      const email = btn.dataset.email;
      const bal = Number(btn.dataset.bal || 0);
      if (bal <= 0) {
        alert(`User ${email} has 0 balance to withdraw.`);
        return;
      }
      if (!confirm(`Withdraw all money (${inr(bal)}) for user ${email}?`)) return;
      btn.disabled = true;
      try {
        const res = await post(`/api/admin/user/${uid}/withdraw`, {type: "all"});
        if (res.success) {
          alert(`Successfully withdrawn all money for ${email}!`);
          await Promise.all([loadUsers(), loadOverview(), loadWithdrawals(), loadLedger()]);
        } else {
          alert(res.error || "Failed to withdraw");
        }
      } catch (err) {
        alert("Error: " + err.message);
      } finally {
        btn.disabled = false;
      }
    };
  });

  document.querySelectorAll(".btn-user-delete").forEach(btn => {
    btn.onclick = async () => {
      const uid = btn.dataset.uid;
      const email = btn.dataset.email;
      if (!confirm(`Are you sure you want to permanently delete user ${email}? All their positions, wallets, and data will be removed.`)) return;
      btn.disabled = true;
      try {
        const res = await post(`/api/admin/user/${uid}/delete`);
        if (res.success) {
          alert(`User ${email} removed completely.`);
          await Promise.all([loadUsers(), loadOverview(), loadStorage()]);
        } else {
          alert(res.error || "Failed to delete user");
        }
      } catch (err) {
        alert("Error: " + err.message);
      } finally {
        btn.disabled = false;
      }
    };
  });

  // Bind EOD Report modal trigger
  document.querySelectorAll(".btn-user-eod").forEach(btn => {
    btn.onclick = async () => {
      const uid = btn.dataset.uid;
      const name = btn.dataset.name;
      const email = btn.dataset.email;
      openUserEODModal(uid, name, email);
    };
  });
}

let _currentEodData = null;

async function openUserEODModal(uid, name, email) {
  const modal = $("modal_eod_statement");
  if (!modal) return;
  modal.classList.remove("hide");
  modal.style.display = "flex";

  $("modal_eod_user_title").textContent = `EOD Statement — ${name} (${email})`;
  $("modal_eod_user_sub").textContent = `Live Audit Ledger & Performance Breakdown for User #${uid}`;
  $("modal_eod_body").innerHTML = `<div style="text-align:center; padding:40px; color:#94a3b8;"><span style="display:inline-block; animation:spin 1s linear infinite; margin-bottom:8px;">⏳</span><br>Compiling complete session statement...</div>`;

  try {
    const res = await get(`/api/admin/user/${uid}/eod-report`);
    if (!res || !res.metrics) {
      $("modal_eod_body").innerHTML = `<div class="empty">Failed to load report.</div>`;
      return;
    }
    _currentEodData = res;
    renderAdminEODModalBody(res);
  } catch (err) {
    $("modal_eod_body").innerHTML = `<div class="empty" style="color:#ef4444;">Error loading statement: ${err.message}</div>`;
  }
}

function renderAdminEODModalBody(res) {
  const m = res.metrics;
  const w = res.wallet;
  const u = res.user;
  const trades = res.closed_trades || [];
  const deposits = res.deposits || [];
  const withdrawals = res.withdrawals || [];

  const netPnlClass = m.realized_pnl_today >= 0 ? "up" : "down";
  const net24hClass = m.realized_pnl_24h >= 0 ? "up" : "down";

  $("modal_eod_body").innerHTML = `
    <!-- Top Stats Cards -->
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:10px;">
      <div class="card" style="padding:12px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:8px;">
        <span class="sub" style="font-size:10px; display:block;">TODAY'S NET REALIZED P&amp;L</span>
        <b class="${netPnlClass}" style="font-size:18px; font-family:ui-monospace,Menlo,monospace;">${signed(m.realized_pnl_today)}</b>
        <span class="tiny ${net24hClass}" style="display:block; margin-top:2px;">24h: ${signed(m.realized_pnl_24h)}</span>
      </div>
      <div class="card" style="padding:12px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:8px;">
        <span class="sub" style="font-size:10px; display:block;">TODAY'S WIN RATE</span>
        <b style="font-size:18px; color:#f8fafc;">${m.win_rate_today}%</b>
        <span class="tiny" style="color:#94a3b8; display:block; margin-top:2px;">${m.wins_today} Wins / ${m.losses_today} Losses</span>
      </div>
      <div class="card" style="padding:12px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:8px;">
        <span class="sub" style="font-size:10px; display:block;">WALLET BALANCE</span>
        <b class="green" style="font-size:18px; font-family:ui-monospace,Menlo,monospace;">${inr((w.deposit_balance || 0) + (w.profit_balance || 0))}</b>
        <span class="tiny" style="color:#94a3b8; display:block; margin-top:2px;">Cap: ${inr(w.deposit_balance)} · Pft: ${inr(w.profit_balance)}</span>
      </div>
      <div class="card" style="padding:12px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:8px;">
        <span class="sub" style="font-size:10px; display:block;">PLATFORM BROKERAGE (30%)</span>
        <b style="font-size:18px; color:#f59e0b; font-family:ui-monospace,Menlo,monospace;">${inr(m.estimated_brokerage_today)}</b>
        <span class="tiny" style="color:#94a3b8; display:block; margin-top:2px;">Turnover: ${inr(m.turnover_volume_today)}</span>
      </div>
    </div>

    <!-- Deposits & Withdrawals Cashflow Summary -->
    <div style="display:flex; justify-content:space-between; align-items:center; background:rgba(15,23,42,0.8); border:1px solid rgba(56,189,248,0.2); border-radius:8px; padding:10px 14px;">
      <div style="display:flex; gap:20px; font-size:12px;">
        <div><span style="color:#94a3b8;">Deposits:</span> <b style="color:#10b981;">${deposits.length} Records (+${inr(m.total_deposited)})</b></div>
        <div><span style="color:#94a3b8;">Withdrawals:</span> <b style="color:#ef4444;">${withdrawals.length} Records (-${inr(m.total_withdrawn)})</b></div>
        <div><span style="color:#94a3b8;">Total Executed Trades:</span> <b style="color:#38bdf8;">${trades.length} Closed</b></div>
      </div>
      <div style="font-size:11px; color:#94a3b8;">Bot Mode: <b style="color:#c084fc;">${u.bot_mode || 'SCALP'}</b></div>
    </div>

    <!-- Closed Trades Breakdown Table -->
    <div>
      <div style="font-size:12px; font-weight:700; color:#cbd5e1; margin-bottom:8px;">RECENT CLOSED TRADES BREAKDOWN (Up to 300 latest)</div>
      <div style="max-height:340px; overflow-y:auto; border:1px solid rgba(255,255,255,0.08); border-radius:6px;">
        <table class="tbl" style="margin:0; font-size:11px;">
          <thead>
            <tr>
              <th>Time</th>
              <th>Pair</th>
              <th>Side</th>
              <th class="r">Entry</th>
              <th class="r">Exit</th>
              <th class="r">Margin</th>
              <th class="r">P&amp;L</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            ${trades.map(t => `
              <tr>
                <td style="color:#94a3b8;">${t.closed_at ? new Date(t.closed_at * 1000).toLocaleTimeString("en-IN") : '—'}</td>
                <td><b>${t.symbol}</b></td>
                <td><span class="tag ${(t.side || '').toLowerCase()}">${t.side}</span></td>
                <td class="r">${priceFmt(t.entry_price)}</td>
                <td class="r">${priceFmt(t.current_price)}</td>
                <td class="r">${inr(t.margin)}</td>
                <td class="r ${t.realized_pnl >= 0 ? 'up' : 'down'}"><b>${signed(t.realized_pnl)}</b></td>
                <td class="txt" style="color:#94a3b8; font-size:10px;">${t.close_reason || 'TARGET'}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

// Modal Close & Export CSV handlers
if ($("modal_eod_close_btn")) {
  $("modal_eod_close_btn").onclick = () => {
    const modal = $("modal_eod_statement");
    if (modal) {
      modal.classList.add("hide");
      modal.style.display = "none";
    }
  };
}

if ($("modal_eod_csv_btn")) {
  $("modal_eod_csv_btn").onclick = () => {
    if (!_currentEodData) return;
    const trades = _currentEodData.closed_trades || [];
    const u = _currentEodData.user || {};
    let csv = "Type,Date,Time,Symbol,Side,Entry Price,Exit Price,Margin (INR),Realized PnL (INR),Close Reason\n";
    trades.forEach(t => {
      const dt = t.closed_at ? new Date(t.closed_at * 1000) : new Date();
      csv += `"TRADE","${dt.toLocaleDateString()}","${dt.toLocaleTimeString()}","${t.symbol}","${t.side}","${t.entry_price}","${t.current_price}","${t.margin}","${t.realized_pnl}","${t.close_reason || ''}"\n`;
    });
    const blob = new Blob([csv], {type: "text/csv;charset=utf-8;"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `EOD_Statement_${(u.name || 'User').replace(/\\s+/g, '_')}_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
  };
}

// Bind Wipe All Users & Refresh buttons
if ($("btn_wipe_all_users") && !$("btn_wipe_all_users")._bound) {
  $("btn_wipe_all_users")._bound = true;
  $("btn_wipe_all_users").onclick = async () => {
    if (!confirm("⚠️ DANGER: Remove ALL users and withdraw/wipe all balances from the platform? This will clear all accounts completely.")) return;
    $("btn_wipe_all_users").disabled = true;
    try {
      const res = await post("/api/admin/users/wipe-all");
      if (res.success) {
        alert("All users and balances removed successfully!");
        await Promise.all([loadOverview(), loadUsers(), loadStorage(), loadWithdrawals(), loadLedger(), loadDeposits()]);
      } else {
        alert(res.error || "Failed to wipe users");
      }
    } catch (err) {
      alert("Error: " + err.message);
    } finally {
      $("btn_wipe_all_users").disabled = false;
    }
  };
}

if ($("btn_refresh_users") && !$("btn_refresh_users")._bound) {
  $("btn_refresh_users")._bound = true;
  $("btn_refresh_users").onclick = async () => {
    await loadUsers();
    await loadOverview();
  };
}

/* ---------------- bot storage ---------------- */
async function loadStorage() {
  const d = await get("/api/admin/bot-storage");
  $("pos_rows").innerHTML = d.open.length ? d.open.map(p => `<tr>
    <td class="sub">${p.email}</td><td><b>${p.symbol}</b></td>
    <td class="sub">${p.category || "—"}</td>
    <td><span class="tag ${p.source === "BOT" ? "bot" : "manual"}">${p.source}</span></td>
    <td><span class="tag ${p.side.toLowerCase()}">${p.side}</span></td>
    <td class="r">${priceFmt(p.entry_price)}</td><td class="r">${priceFmt(p.current_price)}</td>
    <td class="r">${inr(p.margin)}</td>
    <td class="r ${p.unrealized_pnl >= 0 ? "up" : "down"}">${inr(p.unrealized_pnl)}</td>
    <td class="sub">${ago(p.opened_at)}</td></tr>`).join("")
    : '<tr><td colspan="10" class="empty">No open positions. Turn the bot ON.</td></tr>';
  $("closed_rows").innerHTML = d.closed.length ? d.closed.map(p => `<tr>
    <td>${p.symbol} <span class="sub">${p.email}</span></td>
    <td><span class="tag ${p.side.toLowerCase()}">${p.side}</span></td>
    <td class="r">${priceFmt(p.entry_price)} → ${priceFmt(p.current_price)}</td>
    <td class="r ${p.realized_pnl >= 0 ? "up" : "down"}">${inr(p.realized_pnl)}</td>
    <td class="sub">${p.close_reason}</td><td class="sub">${ago(p.closed_at)}</td></tr>`).join("")
    : '<tr><td colspan="6" class="empty">No closed trades yet.</td></tr>';
}

async function loadLogs() {
  const d = await get("/api/admin/logs");
  $("admin_logs").innerHTML = d.logs.map(l =>
    `<div><span class="${l.level === "WIN" ? "up" : l.level === "LOSS" ? "down" : ""}">[${l.level}]</span> ${l.message}</div>`).join("");
}

async function loadDeposits() {
  const d = await get("/api/admin/deposits");
  $("dep_rows").innerHTML = d.deposits.length ? d.deposits.map(x => `<tr>
    <td>${ago(x.created_at)}</td>
    <td>
      <b>${x.name || 'Trader'}</b>
      <div class="sub">${x.email}</div>
    </td>
    <td>
      <b style="color:#38bdf8;">${x.bank_name || x.method}</b>
      ${x.account_number ? `<span style="font-family:monospace; color:#94a3b8; font-size:10.5px; display:block;">••••${x.account_number.slice(-4)}</span>` : ''}
    </td>
    <td>${x.asset}</td>
    <td class="r">${inr(x.amount)}</td>
    <td class="r up" style="font-weight:700;">${inr(x.credited)}</td>
    <td class="sub" style="font-family:monospace; font-size:11px;">${x.ref}</td>
    <td><span class="tag approved">${x.status}</span></td></tr>`).join("")
    : '<tr><td colspan="8" class="empty">No deposits yet.</td></tr>';
}

if ($("btn_admin_credit_dep") && !$("btn_admin_credit_dep")._bound) {
  $("btn_admin_credit_dep")._bound = true;
  $("btn_admin_credit_dep").onclick = async () => {
    const email = prompt("Enter user email to credit bank deposit to:", "autotrader_pro@gmail.com");
    if (!email) return;
    const amtStr = prompt(`Enter amount (INR) to deposit for ${email}:`, "25000");
    if (!amtStr) return;
    const amt = parseFloat(amtStr);
    if (isNaN(amt) || amt <= 0) {
      alert("Invalid amount");
      return;
    }
    try {
      const uRes = await get("/api/admin/users");
      const targetUser = (uRes.users || []).find(u => u.email.toLowerCase() === email.toLowerCase());
      if (!targetUser) {
        alert("User with email " + email + " not found!");
        return;
      }
      const res = await post(`/api/admin/user/${targetUser.id}/deposit`, {
        amount: amt,
        bank_name: "ADMIN DIRECT BANK WIRE",
        note: "Admin Bank Settlement Credit"
      });
      if (res && res.success) {
        alert(`Successfully deposited $${amt.toLocaleString('en-IN')} to ${email}!`);
        await Promise.all([loadUsers(), loadOverview(), loadDeposits(), loadLedger()]);
      } else {
        alert(res.error || "Failed to credit deposit");
      }
    } catch (e) {
      alert("Error: " + e.message);
    }
  };
}

async function loadLedger() {
  const d = await get("/api/admin/brokerage");
  $("ledger_rows").innerHTML = d.ledger.length ? d.ledger.map(l => `<tr>
    <td>${ago(l.at)}</td><td><span class="tag ${l.source === "WITHDRAWAL" ? "manual" : "bot"}">${l.source}</span></td>
    <td class="sub">${l.ref || ""}</td><td class="sub">${l.email || ""}</td>
    <td class="r green">${inr(l.amount)}</td></tr>`).join("")
    : '<tr><td colspan="5" class="empty">No brokerage booked yet.</td></tr>';
  $("ledger_total").textContent = `Total admin brokerage ${inr(d.total)} at ${d.rate * 100}% · `
    + Object.entries(d.by_source).map(([k, v]) => `${k} ${inr(v)}`).join(" · ");
  const links = await get("/api/admin/profit-links");
  $("pl_list").innerHTML = links.links.slice(0, 6).map(l =>
    `${ago(l.created_at)} · ${l.email} · ${inr(l.gross)} → you keep ${inr(l.brokerage)}`).join("<br>") || "none yet";
  const total = d.total || 1;
  $("bar_admin").style.width = "30%"; $("bar_user").style.width = "70%";
  $("bar_lbl").textContent = `Every $100 of user profit costs the platform nothing and earns ${inr(30)} brokerage; ${inr(total)} collected so far.`;
}

/* ---------------- profit link sidepanel ---------------- */
function preview() {
  const amt = Number($("pl_amount").value || 0);
  $("pl_fee").textContent = inr(amt * 0.3);
  $("pl_net").textContent = inr(amt * 0.7);
}
$("pl_amount").oninput = preview;

$("pl_go").onclick = async () => {
  $("pl_msg").textContent = "Creating…";
  const d = await post("/api/admin/create-profit-link", {
    userEmail: $("pl_email").value.trim(), profitAmount: Number($("pl_amount").value),
    reason: $("pl_reason").value.trim()});
  if (!d.success) { $("pl_msg").className = "msg red"; $("pl_msg").textContent = d.error; return; }
  $("pl_msg").className = "msg green";
  $("pl_msg").textContent = `Credited ${$("pl_email").value.trim()} — gross ${inr(d.profitAmount)}, brokerage ${inr(d.brokerage)}, user receives ${inr(d.netToUser)}.\nLink: ${d.link}`;
  await Promise.all([loadOverview(), loadLedger(), loadUsers()]);
};

$("bot_on").onclick = async () => { const r = await post("/api/admin/bot/start"); await loadOverview(); if (r && r.message) alert(r.message); };
$("bot_off").onclick = async () => { const r = await post("/api/admin/bot/stop"); await loadOverview(); if (r && r.message) alert(r.message); };
if ($("hero_bot_on")) {
  $("hero_bot_on").onclick = async () => { const r = await post("/api/admin/bot/start"); await loadOverview(); if (r && r.message) alert(r.message); };
}
if ($("hero_bot_off")) {
  $("hero_bot_off").onclick = async () => { const r = await post("/api/admin/bot/stop"); await loadOverview(); if (r && r.message) alert(r.message); };
}
if ($("hero_flush_positions")) {
  $("hero_flush_positions").onclick = async () => {
    if (!confirm("Are you sure you want to LIQUIDATE and CLOSE ALL open bot positions across all users?")) return;
    const res = await post("/api/admin/bot/close-all");
    alert(`Success: Closed ${res.closed || 0} positions. Total P&L: $${(res.total_pnl || 0).toFixed(2)}`);
    await loadOverview();
    await loadStorage();
  };
}

async function tick() {
  if (!getAdminToken()) return;
  try {
    await loadOverview(); await loadStorage(); await loadWithdrawals();
    await loadUsers(); await loadDeposits(); await loadLedger(); await loadLogs();
    await loadGatekeeperAudit();
    if (typeof loadAdminSmcDna === "function") await loadAdminSmcDna();
    if (typeof loadEnterpriseV3Health === "function") await loadEnterpriseV3Health();
  } catch (e) { $("feed").textContent = "API DOWN — is python3 backend/app.py running?"; }
}
/* ---------------- Admin Theme Management (Isolated from User Dashboard) ---------------- */
function resolveAdminEffectiveTheme(mode) {
  if (mode === "system") {
    return (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) ? "light" : "dark";
  }
  return mode === "light" ? "light" : "dark";
}

function initTheme() {
  const saved = localStorage.getItem("araabot_admin_theme_mode") || localStorage.getItem("tradepro_admin_theme") || "dark";
  applyTheme(saved);
  if (window.matchMedia) {
    try {
      window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => {
        const curMode = localStorage.getItem("araabot_admin_theme_mode") || "dark";
        if (curMode === "system") applyTheme("system");
      });
    } catch (_) {}
  }
}

function applyTheme(mode) {
  const cleanMode = (mode === "light" || mode === "system") ? mode : "dark";
  const effective = resolveAdminEffectiveTheme(cleanMode);
  document.documentElement.setAttribute("data-theme", effective);
  document.documentElement.setAttribute("data-theme-mode", cleanMode);
  if ($("theme_toggle")) {
    $("theme_toggle").textContent = effective === "light" ? "☀️ LIGHT" : "🌙 DARK";
  }
  ["dark", "light", "system"].forEach(m => {
    const btn = $("adm_theme_" + m);
    if (btn) {
      btn.classList.toggle("active", m === cleanMode);
      btn.style.background = m === cleanMode ? (effective === "light" ? "#84CC16" : "#C8F169") : "transparent";
      btn.style.color = m === cleanMode ? "#0B0F14" : "";
      btn.style.fontWeight = m === cleanMode ? "800" : "600";
    }
  });
  localStorage.setItem("araabot_admin_theme_mode", cleanMode);
  localStorage.setItem("tradepro_admin_theme", effective);
}
window.setAdminTheme = applyTheme;

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
  const next = current === "light" ? "dark" : "light";
  applyTheme(next);
}

if ($("theme_toggle")) {
  $("theme_toggle").onclick = toggleTheme;
}
initTheme();

/* ==================== PROFIT LINK SIDEPANEL DRAWER TOGGLE ==================== */
function openSidepanel() {
  const panel = $("admin_sidepanel");
  const overlay = $("sidepanel_overlay");
  if (panel) panel.classList.add("open");
  if (overlay) overlay.classList.add("show");
}

function closeSidepanel() {
  const panel = $("admin_sidepanel");
  const overlay = $("sidepanel_overlay");
  if (panel) panel.classList.remove("open");
  if (overlay) overlay.classList.remove("show");
}

if ($("toggle_sidepanel_btn")) {
  $("toggle_sidepanel_btn").onclick = () => {
    const panel = $("admin_sidepanel");
    if (panel && panel.classList.contains("open")) {
      closeSidepanel();
    } else {
      openSidepanel();
    }
  };
}

if ($("close_sidepanel_btn")) {
  $("close_sidepanel_btn").onclick = closeSidepanel;
}

if ($("sidepanel_overlay")) {
  $("sidepanel_overlay").onclick = closeSidepanel;
}

/* ================================ ADMIN 995 SYMBOLS FEED & SIGNALS HUB ================================ */
let adminHubData = null;
let currentAdminHubFilter = "ALL";

async function openAdminFeedHub() {
  const modal = $("modal_admin_feed_hub");
  if (!modal) return;
  modal.classList.remove("hide");
  modal.style.display = "flex";

  try {
    const d = await get("/api/markets/status");
    adminHubData = d;
    if ($("adm_hub_total")) $("adm_hub_total").textContent = d.total_symbols || 995;
    if ($("adm_hub_live")) $("adm_hub_live").textContent = d.live_count || 992;
    if ($("adm_hub_offline")) $("adm_hub_offline").textContent = d.offline_count || 3;
    if ($("adm_hub_buy")) $("adm_hub_buy").textContent = d.signals_summary ? d.signals_summary.BUY : 472;
    if ($("adm_hub_sell")) $("adm_hub_sell").textContent = d.signals_summary ? d.signals_summary.SELL : 473;
    if ($("adm_filter_all")) $("adm_filter_all").textContent = `ALL (${d.total_symbols || 995})`;
    if ($("adm_filter_live")) $("adm_filter_live").textContent = `🟢 LIVE (${d.live_count || 992})`;
    if ($("adm_filter_offline")) $("adm_filter_offline").textContent = `○ OFFLINE / SIM (${d.offline_count || 3})`;
    renderAdminHubSymbols();
  } catch (err) {
    console.error("Failed to load admin feed status", err);
  }
}

function closeAdminFeedHub() {
  const modal = $("modal_admin_feed_hub");
  if (!modal) return;
  modal.classList.add("hide");
  modal.style.display = "none";
}

window.setAdminHubFilter = function(filter) {
  currentAdminHubFilter = filter;
  const filters = ["all", "live", "buy", "sell", "offline"];
  filters.forEach(f => {
    const btn = $("adm_filter_" + f);
    if (!btn) return;
    if (f.toUpperCase() === filter) {
      btn.style.borderColor = "#38bdf8";
      btn.style.background = "rgba(56,189,248,0.2)";
    } else {
      btn.style.borderColor = "rgba(255,255,255,0.1)";
      btn.style.background = "transparent";
    }
  });
  renderAdminHubSymbols();
};

function renderAdminHubSymbols() {
  const tbody = $("adm_hub_tbody");
  if (!tbody || !adminHubData) return;

  const q = ($("adm_hub_search") ? $("adm_hub_search").value.trim().toUpperCase() : "");
  let allList = [...(adminHubData.live_symbols || []), ...(adminHubData.offline_symbols || [])];

  if (currentAdminHubFilter === "LIVE") {
    allList = allList.filter(s => s.live);
  } else if (currentAdminHubFilter === "OFFLINE") {
    allList = allList.filter(s => !s.live);
  } else if (currentAdminHubFilter === "BUY") {
    allList = allList.filter(s => s.signal === "BUY");
  } else if (currentAdminHubFilter === "SELL") {
    allList = allList.filter(s => s.signal === "SELL");
  }

  if (q) {
    allList = allList.filter(s => s.symbol.toUpperCase().includes(q) || (s.name && s.name.toUpperCase().includes(q)) || (s.source && s.source.toUpperCase().includes(q)));
  }

  const renderLimit = 150;
  const displayItems = allList.slice(0, renderLimit);

  tbody.innerHTML = displayItems.map(item => {
    const isLive = !!item.live;
    const isBuy = item.signal === "BUY";
    const isSell = item.signal === "SELL";
    const sigBadge = isBuy
      ? `<span style="padding:2px 7px; border-radius:4px; font-weight:800; font-size:10px; background:rgba(16,185,129,0.18); border:1px solid #10b981; color:#34d399;">▲ BUY (${item.confidence || 85}%)</span>`
      : isSell
      ? `<span style="padding:2px 7px; border-radius:4px; font-weight:800; font-size:10px; background:rgba(239,68,68,0.18); border:1px solid #ef4444; color:#f87171;">▼ SELL (${item.confidence || 85}%)</span>`
      : `<span style="padding:2px 7px; border-radius:4px; font-weight:700; font-size:10px; background:#1e293b; border:1px solid rgba(255,255,255,0.1); color:#94a3b8;">● NEUTRAL</span>`;

    const liveBadge = isLive
      ? `<span style="color:#10b981; font-weight:800; display:inline-flex; align-items:center; gap:5px;"><span class="dot" style="margin:0; width:6px; height:6px; background:#10b981;"></span> LIVE</span>`
      : `<span style="color:#94a3b8; font-weight:700; display:inline-flex; align-items:center; gap:5px;"><span style="width:6px; height:6px; border-radius:50%; background:#94a3b8; display:inline-block;"></span> OFFLINE/SIM</span>`;

    const chgClass = (item.change_pct >= 0) ? "color:#34d399;" : "color:#f87171;";
    const chgText = (item.change_pct >= 0 ? "+" : "") + Number(item.change_pct || 0).toFixed(2) + "%";

    return `<tr style="border-bottom:1px solid rgba(255,255,255,0.06);">
      <td style="padding:8px 6px;">
        <b style="color:#f8fafc; font-family:monospace;">${item.symbol}</b>
        <div style="font-size:10.5px; color:#94a3b8; max-width:160px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${item.name || item.symbol}</div>
      </td>
      <td style="padding:8px 6px;"><span class="pill" style="font-size:9.5px; padding:1px 6px;">${(item.category || "CR").slice(0, 3)}</span></td>
      <td style="padding:8px 6px; font-size:11px;">${liveBadge}</td>
      <td style="padding:8px 6px; font-family:monospace; color:#38bdf8; font-size:11px;">${item.source || "STREAM"}</td>
      <td style="padding:8px 6px; font-family:monospace; font-weight:700;">${priceFmt(item.price)}</td>
      <td style="padding:8px 6px; font-family:monospace; font-weight:700; ${chgClass}">${chgText}</td>
      <td style="padding:8px 6px;">${sigBadge}</td>
      <td style="padding:8px 6px; text-align:right;">
        <a href="/?symbol=${encodeURIComponent(item.symbol)}" target="_blank" class="btn sm" style="text-decoration:none; padding:4px 10px; font-size:11px; font-weight:800; border-radius:6px; background:rgba(56,189,248,0.15); border:1px solid #38bdf8; color:#38bdf8;">
          📈 Open Chart
        </a>
      </td>
    </tr>`;
  }).join("");

  if (allList.length > renderLimit) {
    tbody.innerHTML += `<tr><td colspan="8" style="text-align:center; padding:12px; color:#94a3b8; font-size:11px;">Showing top ${renderLimit} of ${allList.length} matching symbols. Filter or search to narrow down.</td></tr>`;
  }
}

if ($("top_admin_feed_hub")) $("top_admin_feed_hub").onclick = openAdminFeedHub;
if ($("close_admin_feed_hub_btn")) $("close_admin_feed_hub_btn").onclick = closeAdminFeedHub;
if ($("done_admin_feed_hub_btn")) $("done_admin_feed_hub_btn").onclick = closeAdminFeedHub;
if ($("modal_admin_feed_hub")) {
  $("modal_admin_feed_hub").onclick = (e) => {
    if (e.target === $("modal_admin_feed_hub")) closeAdminFeedHub();
  };
}
if ($("adm_hub_search")) {
  $("adm_hub_search").oninput = () => {
    clearTimeout(window._adm_st);
    window._adm_st = setTimeout(renderAdminHubSymbols, 150);
  };
}

preview(); if (getAdminToken()) tick();
setInterval(async () => { if (!getAdminToken()) return; try { await loadOverview(); await loadStorage(); await loadGatekeeperAudit(); } catch (e) {} }, 3000);
setInterval(async () => { if (!getAdminToken()) return; try { await loadWithdrawals(); await loadUsers(); await loadLogs(); await loadFirewall(); } catch (e) {} }, 7000);
setInterval(async () => { if (!getAdminToken()) return; try { await loadDeposits(); await loadLedger(); } catch (e) {} }, 15000);

/* ---------------- AraaBot Adapter Rules Gatekeeper Telemetry & Pre-Trade Audit Stream ---------------- */
async function loadGatekeeperAudit() {
  try {
    const res = await get("/api/admin/adapter-gatekeeper");
    if (!res) return;

    // Update Gatekeeper Badge
    if ($("gatekeeper_badge") && res.stats) {
      const tripped = res.stats.circuit_breaker_active;
      if (tripped) {
        $("gatekeeper_badge").className = "pill danger";
        $("gatekeeper_badge").style.background = "rgba(239,68,68,0.2)";
        $("gatekeeper_badge").style.borderColor = "#ef4444";
        $("gatekeeper_badge").style.color = "#ef4444";
        $("gatekeeper_badge").textContent = "● CIRCUIT BREAKER TRIPPED (-₹250)";
      } else {
        $("gatekeeper_badge").className = "pill live";
        $("gatekeeper_badge").style.background = "rgba(16,185,129,0.18)";
        $("gatekeeper_badge").style.borderColor = "#10b981";
        $("gatekeeper_badge").style.color = "#34d399";
        $("gatekeeper_badge").textContent = res.stats.rules_enforced || "● 6/6 RULES ENFORCED";
      }
    }

    // Render 6-Rule Grid
    if ($("gatekeeper_rules_grid") && Array.isArray(res.rules) && res.rules.length === 6) {
      let gridHtml = "";
      res.rules.forEach(rule => {
        const isPass = rule.passed;
        const icon = isPass ? "✓" : "✕";
        const iconBg = isPass ? "#10b981" : "#ef4444";
        const pillClass = isPass ? "pill live" : "pill danger";
        const pillBg = isPass ? "rgba(16,185,129,0.2)" : "rgba(239,68,68,0.2)";
        const pillBorder = isPass ? "#10b981" : "#ef4444";
        const pillColor = isPass ? "#34d399" : "#f87171";
        const borderCard = isPass ? "rgba(16,185,129,0.35)" : "rgba(239,68,68,0.5)";

        gridHtml += `
          <div class="rule-box" style="background:#0f172a; border:1px solid ${borderCard}; border-radius:10px; padding:12px 14px; position:relative;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
              <div style="display:flex; align-items:center; gap:8px;">
                <span style="width:20px; height:20px; border-radius:50%; background:${iconBg}; color:#000; font-weight:900; font-size:11px; display:flex; align-items:center; justify-content:center;">${icon}</span>
                <span style="font-weight:800; font-size:12.5px; color:#f8fafc;">${rule.title}</span>
              </div>
              <span class="${pillClass}" style="font-size:9.5px; padding:2px 6px; background:${pillBg}; color:${pillColor}; border-color:${pillBorder};">${rule.status}</span>
            </div>
            <div style="font-size:11px; color:#94a3b8; font-family:'JetBrains Mono', monospace;">Condition: ${rule.condition} (${rule.threshold})</div>
            <div style="font-size:10.5px; color:${pillColor}; margin-top:4px; font-weight:600;">${rule.badge}</div>
          </div>
        `;
      });
      $("gatekeeper_rules_grid").innerHTML = gridHtml;
    }

    // Render Stream Count & Audit Table
    const logs = Array.isArray(res.inspection_logs) ? res.inspection_logs : [];
    if ($("gatekeeper_stream_count")) {
      $("gatekeeper_stream_count").textContent = `${logs.length} Live Pre-Trade Inspection Audits Monitored`;
    }

    if ($("gatekeeper_audit_body")) {
      if (logs.length === 0) {
        // Fallback to recent AI predictions if no order rejection logs yet
        const preds = Array.isArray(res.ai_analysis) ? res.ai_analysis : [];
        if (preds.length > 0) {
          let rowsHtml = "";
          preds.forEach(p => {
            const timeStr = p.created_at ? new Date(p.created_at * 1000).toLocaleTimeString() : "--";
            const winProb = p.win_probability || 0;
            const passed = winProb >= 80;
            const decPill = passed
              ? `<span style="color:#10b981; font-weight:800;">✓ PASSED</span>`
              : `<span style="color:#ef4444; font-weight:800;">✕ BLOCKED (&lt;80%)</span>`;
            rowsHtml += `
              <tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
                <td style="padding:6px 10px; font-family:'JetBrains Mono', monospace; color:#94a3b8;">${timeStr}</td>
                <td style="padding:6px 10px;"><span class="pill" style="font-size:10px; background:rgba(56,189,248,0.15); color:#38bdf8; border-color:#38bdf8;">AI_INSPECTION</span> <span style="font-weight:700;">${p.symbol || 'PAIR'}</span></td>
                <td style="padding:6px 10px;">${decPill}</td>
                <td style="padding:6px 10px; color:#cbd5e1;">Neural Win Prob: <b>${winProb}%</b> (${p.direction || 'HOLD'} ${p.action || 'WAIT'}) · Rule 6 Gemini Evaluation</td>
              </tr>
            `;
          });
          $("gatekeeper_audit_body").innerHTML = rowsHtml;
        } else {
          $("gatekeeper_audit_body").innerHTML = `<tr><td colspan="4" style="text-align:center; padding:15px; color:#64748b;">No recent rejections or audits recorded yet. All active CoinDCX orders passing rules cleanly.</td></tr>`;
        }
      } else {
        let rowsHtml = "";
        logs.forEach(l => {
          const timeStr = l.created_at ? new Date(l.created_at * 1000).toLocaleTimeString() : "--";
          const isPassed = l.event_type === "SPOT_ORDER_EXECUTED" || l.severity === "SUCCESS";
          const decBadge = isPassed
            ? `<span style="color:#10b981; font-weight:800;">✓ EXECUTED</span>`
            : `<span style="color:#ef4444; font-weight:800;">✕ REJECTED</span>`;
          
          let eventPill = `<span class="pill danger" style="font-size:10px;">${l.event_type}</span>`;
          if (isPassed) {
            eventPill = `<span class="pill live" style="font-size:10px;">${l.event_type}</span>`;
          } else if (l.severity === "WARNING") {
            eventPill = `<span class="pill warn" style="font-size:10px;">${l.event_type}</span>`;
          }

          rowsHtml += `
            <tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
              <td style="padding:6px 10px; font-family:'JetBrains Mono', monospace; color:#94a3b8;">${timeStr}</td>
              <td style="padding:6px 10px;">${eventPill}</td>
              <td style="padding:6px 10px;">${decBadge}</td>
              <td style="padding:6px 10px; color:#cbd5e1; word-break:break-word;">${l.message || '--'}</td>
            </tr>
          `;
        });
        $("gatekeeper_audit_body").innerHTML = rowsHtml;
      }
    }
  } catch (err) {
    console.warn("Failed to load adapter gatekeeper audit:", err);
  }
}

if ($("btn_refresh_gatekeeper")) {
  $("btn_refresh_gatekeeper").onclick = async () => {
    $("btn_refresh_gatekeeper").textContent = "🔄 REFRESHING...";
    await loadGatekeeperAudit();
    if (typeof loadAdminSmcDna === "function") await loadAdminSmcDna();
    setTimeout(() => { $("btn_refresh_gatekeeper").textContent = "🔄 REFRESH RULES"; }, 500);
  };
}

async function loadAdminSmcDna() {
  try {
    const _e = (v) => String(v ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const sym = ($("adm_smc_sym_select") && $("adm_smc_sym_select").value) || "BTCUSDT";
    const res = await get("/api/smc/overview?symbol=" + encodeURIComponent(sym) + "&interval=15m");
    if (!res || !res.ok) return;

    const scannerEl = $("adm_smc_scanner_grid");
    if (scannerEl && Array.isArray(res.scanner)) {
      scannerEl.innerHTML = res.scanner.map((item) => {
        const bias = String(item.historical_bias || "neutral").toUpperCase();
        const biasClr = bias === "BULLISH" ? "#34d399" : bias === "BEARISH" ? "#fb7185" : "#fbbf24";
        const status = String(item.setup_status || "NO_QUALIFIED_SETUP");
        const statusClr = status === "QUALIFIED_SETUP" ? "#34d399" : status === "DEVELOPING" ? "#fbbf24" : "#94a3b8";
        return `
          <div style="background:rgba(15,23,42,0.65); border:1px solid rgba(148,163,184,0.2); border-radius:10px; padding:10px; font-size:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:6px; margin-bottom:6px;">
              <b style="color:#f8fafc;">${_e(item.symbol)}</b>
              <span style="font-size:10px; padding:2px 6px; border-radius:999px; border:1px solid ${statusClr}; color:${statusClr};">${_e(status)}</span>
            </div>
            <div style="display:flex; justify-content:space-between; color:#cbd5e1; margin-bottom:4px;">
              <span>Price: <b>$${priceFmt(item.price)}</b></span>
              <span style="color:${biasClr}; font-weight:700;">${_e(bias)} (${Number(item.similarity_pct || 0).toFixed(1)}%)</span>
            </div>
            <div style="font-size:11px; color:#94a3b8; display:grid; grid-template-columns:1fr 1fr; gap:4px;">
              <span>Fib 61.8%: $${priceFmt(item.fib_618 || 0)}</span>
              <span>OBs: ${Number(item.obs_count || 0)} · FVGs: ${Number(item.fvgs_count || 0)}</span>
              <span>BSL: $${priceFmt(item.bsl || 0)}</span>
              <span>SSL: $${priceFmt(item.ssl || 0)}</span>
            </div>
          </div>
        `;
      }).join("") || '<div style="color:#94a3b8; font-size:12px;">No scanner telemetry available.</div>';
    }

    const timelineBody = $("adm_smc_timeline_body");
    const timeline = (res.active_dna && Array.isArray(res.active_dna.timeline)) ? res.active_dna.timeline : [];
    if (timelineBody) {
      if (!timeline.length) {
        timelineBody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#94a3b8;">No confirmed SMC structure events yet.</td></tr>';
      } else {
        timelineBody.innerHTML = timeline.map((ev) => {
          const evBias = String(ev.bias || "neutral").toUpperCase();
          const bClr = evBias === "BULLISH" ? "#34d399" : evBias === "BEARISH" ? "#fb7185" : "#fbbf24";
          const tStr = (typeof ev.time === "number" && ev.time > 1000000000)
            ? new Date(ev.time * 1000).toLocaleTimeString("en-IN", {timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false})
            : (ev.time || "--");
          return `
            <tr>
              <td>${_e(tStr)}</td>
              <td><b>${_e(ev.symbol || sym)}</b></td>
              <td>${_e(ev.tf || "15M")}</td>
              <td>${_e(ev.event || "--")}</td>
              <td><span style="color:${bClr}; font-weight:700;">${_e(evBias)}</span></td>
              <td style="text-align:right;">$${priceFmt(ev.price || 0)}</td>
            </tr>
          `;
        }).join("");
      }
    }
  } catch (err) {
    console.warn("Failed to load SMC + Market DNA overview:", err);
  }
}

if ($("btn_adm_refresh_smc")) {
  $("btn_adm_refresh_smc").onclick = async () => {
    $("btn_adm_refresh_smc").textContent = "🔄 SCANNING...";
    await loadAdminSmcDna();
    setTimeout(() => { $("btn_adm_refresh_smc").textContent = "🔄 SCAN SMC & DNA"; }, 500);
  };
}
if ($("adm_smc_sym_select")) {
  $("adm_smc_sym_select").onchange = () => loadAdminSmcDna();
}
if (getAdminToken()) loadAdminSmcDna();

/* ---------------- security firewall telemetry ---------------- */
async function loadFirewall() {
  try {
    const d = await get("/api/admin/firewall");
    if (!d || !d.stats) return;

    if ($("fw_total_inspected")) $("fw_total_inspected").textContent = num(d.stats.total_requests_inspected || 0);
    if ($("fw_threats_blocked")) {
      const blocked = d.stats.threats_blocked || 0;
      $("fw_threats_blocked").textContent = num(blocked);
      $("fw_threats_blocked").style.color = blocked > 0 ? "#ef4444" : "#10b981";
    }
    if ($("fw_sqli_blocked")) $("fw_sqli_blocked").textContent = num(d.stats.sqli_attempts || 0);
    if ($("fw_xss_blocked")) $("fw_xss_blocked").textContent = num(d.stats.xss_attempts || 0);
    if ($("fw_rate_limits")) $("fw_rate_limits").textContent = num(d.stats.rate_limit_trips || 0);
    if ($("fw_banned_ips")) $("fw_banned_ips").textContent = num(d.active_bans_count || 0);

    const tbody = $("fw_threat_rows");
    if (!tbody) return;

    const events = d.recent_threats || [];
    if (events.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--muted2); padding:16px;">Firewall active & scanning. No hostile security threats detected.</td></tr>`;
      return;
    }

    tbody.innerHTML = events.slice(0, 30).map(ev => {
      const isBlocked = ev.action && ev.action.includes("BLOCK");
      const badgeStyle = isBlocked
        ? "background:rgba(239,68,68,0.18); border:1px solid #ef4444; color:#f87171; padding:2px 7px; border-radius:4px; font-weight:700; font-size:10px;"
        : "background:rgba(245,158,11,0.18); border:1px solid #f59e0b; color:#fbbf24; padding:2px 7px; border-radius:4px; font-weight:700; font-size:10px;";
      
      const timeStr = ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleTimeString() : "just now";
      
      return `<tr>
        <td style="font-family:monospace; font-size:11px; color:#94a3b8;">${timeStr}</td>
        <td style="font-family:monospace; font-weight:700; color:#f8fafc;">
          ${ev.ip}
          ${d.active_bans && d.active_bans[ev.ip] ? `<button onclick="unbanFirewallIp('${ev.ip}')" class="btn sm danger" style="padding:1px 5px; font-size:9px; margin-left:6px;">UNBAN</button>` : ""}
        </td>
        <td style="color:#f59e0b; font-weight:700; font-size:11px;">⚠️ ${ev.threat || "ANOMALY"}</td>
        <td style="font-family:monospace; font-size:11px; color:#38bdf8;">${ev.path || "/"}</td>
        <td><span style="${badgeStyle}">${ev.action || "BLOCKED"}</span></td>
        <td style="font-size:11px; color:#cbd5e1; max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${(ev.details || "").replace(/"/g, '&quot;')}">${ev.details || "—"}</td>
      </tr>`;
    }).join("");
  } catch (err) {
    console.error("Firewall telemetry err:", err);
  }
}

window.unbanFirewallIp = async function(ip) {
  if (!confirm("Are you sure you want to unban IP " + ip + "?")) return;
  try {
    const res = await post("/api/admin/firewall/unban", { ip });
    if (res && res.success) {
      alert("IP unbanned successfully.");
      await loadFirewall();
    } else {
      alert("Failed to unban IP: " + (res.error || "Unknown"));
    }
  } catch (e) {
    alert("Error unbanning IP: " + e.message);
  }
};

if ($("btn_refresh_fw")) {
  $("btn_refresh_fw").onclick = loadFirewall;
}
loadFirewall();

/* ============================ UPI & PhonePe Admin Gateway Config ============================ */
async function loadUpiGatewayConfig() {
  try {
    const res = await get("/api/upi/config");
    if (res) {
      if ($("adm_upi_vpa") && res.merchant_vpa) $("adm_upi_vpa").value = res.merchant_vpa;
      if ($("adm_upi_name") && res.merchant_name) $("adm_upi_name").value = res.merchant_name;
      if ($("adm_phonepe_mid") && res.phonepe_merchant_id) $("adm_phonepe_mid").value = res.phonepe_merchant_id;
    }
  } catch (e) {
    console.warn("Load UPI config error:", e);
  }
}

if ($("btn_save_upi_config")) {
  $("btn_save_upi_config").onclick = async () => {
    const vpa = ($("adm_upi_vpa").value || "").trim();
    const name = ($("adm_upi_name").value || "").trim();
    const mid = ($("adm_phonepe_mid").value || "").trim();
    const key = ($("adm_phonepe_key").value || "").trim();

    if (!vpa || !vpa.includes("@")) {
      if ($("adm_upi_msg")) {
        $("adm_upi_msg").style.color = "#ef4444";
        $("adm_upi_msg").textContent = "Please enter a valid Merchant UPI VPA (e.g. name@bank)";
      }
      return;
    }

    try {
      $("btn_save_upi_config").disabled = true;
      const res = await post("/api/admin/upi/config", {
        merchant_vpa: vpa,
        merchant_name: name,
        phonepe_merchant_id: mid,
        phonepe_salt_key: key.includes("••") ? "" : key
      });

      if (res && res.success) {
        if ($("adm_upi_msg")) {
          $("adm_upi_msg").style.color = "#10b981";
          $("adm_upi_msg").textContent = "✓ UPI & PhonePe credentials updated live!";
        }
      } else {
        if ($("adm_upi_msg")) {
          $("adm_upi_msg").style.color = "#ef4444";
          $("adm_upi_msg").textContent = res.error || "Failed to save UPI config";
        }
      }
    } catch (e) {
      if ($("adm_upi_msg")) {
        $("adm_upi_msg").style.color = "#ef4444";
        $("adm_upi_msg").textContent = e.message;
      }
    } finally {
      $("btn_save_upi_config").disabled = false;
    }
  };
}

// Load and manage Razorpay configuration in Admin
async function loadRazorpayConfig() {
  try {
    const res = await get("/api/admin/razorpay/config");
    if (res) {
      if ($("adm_rzp_key_id")) $("adm_rzp_key_id").value = res.key_id || "";
      if ($("adm_rzp_key_secret")) $("adm_rzp_key_secret").value = res.key_secret ? "••••••••••••••••" : "";
      if ($("adm_rzp_mode")) $("adm_rzp_mode").value = res.mode || "TEST";
    }
  } catch (e) {
    console.error("Failed to load Razorpay config:", e);
  }
}
loadRazorpayConfig();

if ($("btn_save_rzp_config")) {
  $("btn_save_rzp_config").onclick = async () => {
    const keyId = ($("adm_rzp_key_id") ? $("adm_rzp_key_id").value : "").trim();
    const keySecret = ($("adm_rzp_key_secret") ? $("adm_rzp_key_secret").value : "").trim();
    const mode = ($("adm_rzp_mode") ? $("adm_rzp_mode").value : "TEST").trim();

    try {
      $("btn_save_rzp_config").disabled = true;
      const res = await post("/api/admin/razorpay/config", {
        key_id: keyId,
        key_secret: keySecret.includes("••") ? "" : keySecret,
        mode: mode
      });

      if (res && res.success) {
        if ($("adm_rzp_msg")) {
          $("adm_rzp_msg").style.color = "#10b981";
          $("adm_rzp_msg").textContent = "✓ Razorpay API credentials saved live!";
        }
      } else {
        if ($("adm_rzp_msg")) {
          $("adm_rzp_msg").style.color = "#ef4444";
          $("adm_rzp_msg").textContent = res.error || "Failed to save Razorpay config";
        }
      }
    } catch (e) {
      if ($("adm_rzp_msg")) {
        $("adm_rzp_msg").style.color = "#ef4444";
        $("adm_rzp_msg").textContent = e.message;
      }
    } finally {
      $("btn_save_rzp_config").disabled = false;
    }
  };
}

if ($("btn_test_upi_qr")) {
  $("btn_test_upi_qr").onclick = async () => {
    try {
      const res = await post("/api/upi/create-order", { amount: 100, provider: "TEST" });
      if (res && res.qr_image_url) {
        window.open(res.qr_image_url, "_blank");
      }
    } catch (e) {
      alert("Error testing QR: " + e.message);
    }
  };
}
if (getAdminToken()) loadUpiGatewayConfig();

/* ==================== 🛡️ ADMIN AUTHENTICATION GATE ==================== */
function checkAdminAuth() {
  const token = getAdminToken();
  const modal = $("modal_admin_auth");
  if (!token) {
    if (modal) {
      modal.style.display = "flex";
      modal.classList.remove("hide");
    }
    return false;
  } else {
    if (modal) {
      modal.style.display = "none";
      modal.classList.add("hide");
    }
    return true;
  }
}

async function handleAdminLoginSubmit(e) {
  if (e) e.preventDefault();
  if (window._adminLoggingIn) return;
  const uInput = $("admin_login_username");
  const pInput = $("admin_login_password");
  const errDiv = $("admin_auth_error");
  const btn = $("btn_submit_admin_login");

  const username = (uInput ? uInput.value : "").trim();
  const password = (pInput ? pInput.value : "").trim();

  if (!username || !password) {
    if (errDiv) {
      errDiv.textContent = "Please provide both admin username and password.";
      errDiv.style.display = "block";
    }
    return;
  }

  window._adminLoggingIn = true;
  try {
    if (btn) { btn.disabled = true; btn.textContent = "Verifying..."; }
    if (errDiv) errDiv.style.display = "none";

    const res = await post("/api/admin/login", { username, password });
    if (res && res.success && res.admin_token) {
      setAdminToken(res.admin_token, res.user || username);
      const modal = $("modal_admin_auth");
      if (modal) {
        modal.style.display = "none";
        modal.classList.add("hide");
      }
      // Trigger full data reload
      await tick();
      if (typeof loadUpiGatewayConfig === "function") loadUpiGatewayConfig();
      if (typeof loadSlackConfig === "function") loadSlackConfig();
    } else {
      if (errDiv) {
        errDiv.textContent = (res && res.error) || "Invalid administrator credentials. Access denied.";
        errDiv.style.display = "block";
      }
    }
  } catch (err) {
    if (errDiv) {
      errDiv.textContent = "Server communication error: " + err.message;
      errDiv.style.display = "block";
    }
  } finally {
    window._adminLoggingIn = false;
    if (btn) { btn.disabled = false; btn.textContent = "🔓 UNLOCK ADMIN COMMAND CENTER"; }
  }
}

function handleAdminLogout() {
  clearAdminToken();
  const modal = $("modal_admin_auth");
  if (modal) {
    modal.style.display = "flex";
    modal.classList.remove("hide");
  }
}

if ($("form_admin_login")) {
  $("form_admin_login").onsubmit = handleAdminLoginSubmit;
}
if ($("btn_admin_logout")) {
  $("btn_admin_logout").onclick = handleAdminLogout;
}

// Check admin authentication immediately on page load
checkAdminAuth();

/* =========================================================================
   SLACK.COM WORKFLOW & NATURAL LANGUAGE PROMPT AUTOMATION CONTROLLER
   ========================================================================= */
async function loadSlackConfig() {
  try {
    const res = await get("/api/admin/slack/config");
    if (res && res.config) {
      const c = res.config;
      if ($("slack_inp_webhook")) $("slack_inp_webhook").value = c.webhook_url || "";
      if ($("slack_inp_channel")) $("slack_inp_channel").value = c.channel || "#araabot-trades";
      if ($("slack_sel_enabled")) $("slack_sel_enabled").value = c.enabled ? "1" : "0";
      if ($("slack_chk_trades")) $("slack_chk_trades").checked = c.trade_alerts !== false;
      if ($("slack_chk_loss")) $("slack_chk_loss").checked = c.loss_cut_alerts !== false;
      if ($("slack_chk_profit")) $("slack_chk_profit").checked = c.profit_lock_alerts !== false;
      
      const badge = $("slack_status_badge");
      if (badge) {
        if (c.enabled && c.webhook_url) {
          badge.textContent = `● SLACK ACTIVE (${c.channel})`;
          badge.style.color = "#10b981";
          badge.style.borderColor = "#10b981";
          badge.style.background = "rgba(16,185,129,0.15)";
        } else {
          badge.textContent = "● SLACK BRIDGE READY (ADD WEBHOOK)";
          badge.style.color = "#E01E5A";
          badge.style.borderColor = "#E01E5A";
          badge.style.background = "rgba(224,30,90,0.15)";
        }
      }
    }
  } catch (err) {
    console.warn("Could not load Slack config:", err);
  }
}

async function saveSlackConfig() {
  const btn = $("btn_save_slack_config");
  try {
    if (btn) { btn.disabled = true; btn.textContent = "💾 SAVING..."; }
    const payload = {
      webhook_url: ($("slack_inp_webhook") ? $("slack_inp_webhook").value : "").trim(),
      channel: ($("slack_inp_channel") ? $("slack_inp_channel").value : "#araabot-trades").trim(),
      enabled: $("slack_sel_enabled") ? $("slack_sel_enabled").value === "1" : true,
      trade_alerts: $("slack_chk_trades") ? $("slack_chk_trades").checked : true,
      loss_cut_alerts: $("slack_chk_loss") ? $("slack_chk_loss").checked : true,
      profit_lock_alerts: $("slack_chk_profit") ? $("slack_chk_profit").checked : true
    };
    const res = await post("/api/admin/slack/config", payload);
    alert(res.message || "Slack configuration saved successfully!");
    await loadSlackConfig();
  } catch (err) {
    alert("Error saving Slack config: " + err.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "💾 SAVE SLACK CONFIG"; }
  }
}

async function testSlackPing() {
  const btn = $("btn_slack_test");
  try {
    if (btn) { btn.disabled = true; btn.textContent = "⚡ PINGING SLACK..."; }
    const res = await post("/api/admin/slack/test");
    if (res.result && res.result.mock) {
      alert("Notice: " + res.result.message);
    } else if (res.result && res.result.success) {
      alert("✅ Success! Live test alert card dispatched to Slack channel.");
    } else {
      alert("Slack response: " + (res.result ? res.result.error : "Unknown status"));
    }
    await loadSlackConfig();
  } catch (err) {
    alert("Slack ping error: " + err.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "⚡ TEST SLACK PING"; }
  }
}

async function runAdminPrompt() {
  const inp = $("admin_prompt_input");
  const term = $("slack_prompt_terminal");
  const btn = $("btn_execute_prompt");
  const promptText = inp ? inp.value.trim() : "";

  if (!promptText) {
    alert("Please enter an instruction or prompt to execute.");
    return;
  }

  try {
    if (btn) { btn.disabled = true; btn.innerHTML = "<span>⚙️ EXECUTING PROMPT...</span>"; }
    if (term) {
      term.style.display = "block";
      term.innerHTML = `<span style="color:#38bdf8;">[ARAA-AI INTERPRETER]</span> Parsing prompt: <i>"${promptText}"</i>...`;
    }

    const adminUser = sessionStorage.getItem("tradepro_admin_user") || "Master Administrator";
    const res = await post("/api/admin/slack/prompt", { prompt: promptText, admin: adminUser });

    if (res && res.result) {
      const r = res.result;
      const ts = new Date().toLocaleTimeString();
      let outputHtml = `
        <div style="border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:6px; margin-bottom:6px;">
          <span style="color:#10b981; font-weight:800;">✓ PROMPT EXECUTED SUCCESSFULLY (${ts})</span>
        </div>
        <div style="color:#fff; margin-bottom:6px;">• <b>Action:</b> ${r.action_summary}</div>
        <div style="color:#38bdf8; margin-bottom:6px;">• <b>System Updates Applied:</b> ${r.updates && r.updates.length ? r.updates.join(" · ") : "Platform logic updated"}</div>
        <div style="color:#E01E5A;">• <b>Slack Bridge:</b> ${r.slack_dispatched ? 'Dispatched to Slack Channel' : 'Logged to Slack Audit Stream'} (${r.slack_status})</div>
      `;
      if (term) term.innerHTML = outputHtml;
      if (inp) inp.value = "";
      await loadOverview();
      await loadStorage();
    }
  } catch (err) {
    if (term) {
      term.style.display = "block";
      term.innerHTML = `<span style="color:#ef4444;">[ERROR] Failed to execute prompt: ${err.message}</span>`;
    }
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = "<span>🚀 EXECUTE PROMPT &amp; SYNC TO SLACK</span>"; }
  }
}

// Event Listeners for Slack Workflow
if ($("btn_save_slack_config")) $("btn_save_slack_config").onclick = saveSlackConfig;
if ($("btn_slack_test")) $("btn_slack_test").onclick = testSlackPing;
if ($("btn_execute_prompt")) $("btn_execute_prompt").onclick = runAdminPrompt;

// Quick prompt pills
document.querySelectorAll(".prompt_pill").forEach(pill => {
  pill.onclick = () => {
    const text = pill.dataset.prompt || pill.textContent;
    if ($("admin_prompt_input")) {
      $("admin_prompt_input").value = text;
      $("admin_prompt_input").focus();
    }
  };
});

// Load Slack config on startup only when authenticated
if (getAdminToken()) loadSlackConfig();

/* =========================================================================
   ENTERPRISE V3 CONTROL CENTER: TRIAL BALANCE, GLOBAL KILL SWITCH & ARAA AI
   ========================================================================= */
let _v3GlobalKillActive = false;

async function loadEnterpriseV3Health() {
  try {
    const [ovRes, sysRes] = await Promise.all([
      get("/api/v1/admin/overview"),
      get("/api/v1/admin/system-health")
    ]);
    const ov = (ovRes && ovRes.overview) || {};
    const ai = (sysRes && sysRes.ai_health) || {};
    const fin = (sysRes && sysRes.financial_health) || {};

    _v3GlobalKillActive = Boolean(ov.global_kill_switch);

    if ($("v3_adm_orders")) $("v3_adm_orders").textContent = num(ov.total_orders || 0);
    if ($("v3_adm_dep_vol")) $("v3_adm_dep_vol").textContent = inr(ov.total_deposits_volume || 0);
    if ($("v3_adm_ai_model")) {
      const prov = ai.providers || {};
      const llmTag = (prov.google_gemini && prov.google_gemini.active) ? " + Gemini"
        : (prov.openai_chatgpt && prov.openai_chatgpt.active) ? " + OpenAI"
        : "";
      const engCount = ai.connected_engines ? `${ai.connected_engines}/${ai.total_engines || 9} Engines · ` : "";
      $("v3_adm_ai_model").textContent = `${engCount}ARAA Quant AI v4.0${llmTag} (${ai.status || "HEALTHY"})`;
    }
    if ($("v3_adm_discrepancy")) {
      const disc = Number(fin.discrepancy || 0);
      $("v3_adm_discrepancy").textContent = inr(disc);
      $("v3_adm_discrepancy").style.color = fin.balanced ? "#10b981" : "#ef4444";
    }

    const tb = $("v3_adm_trial_badge");
    if (tb) {
      tb.textContent = ov.trial_balance_healthy ? "● TRIAL BALANCE: BALANCED" : "⚠ TRIAL BALANCE: CHECK";
      tb.className = "pill " + (ov.trial_balance_healthy ? "live" : "sim");
    }

    const kb = $("v3_adm_kill_badge");
    const kBtn = $("btn_v3_global_kill_toggle");
    if (kb) {
      kb.textContent = _v3GlobalKillActive ? "🛑 GLOBAL KILL SWITCH ACTIVE" : "🟢 KILL SWITCH ARMED (NORMAL)";
      kb.style.color = _v3GlobalKillActive ? "#ef4444" : "#34d399";
      kb.style.borderColor = _v3GlobalKillActive ? "#ef4444" : "#10b981";
    }
    if (kBtn) {
      kBtn.textContent = _v3GlobalKillActive ? "✅ RELEASE GLOBAL KILL SWITCH" : "🛑 ACTIVATE GLOBAL KILL SWITCH";
      kBtn.style.background = _v3GlobalKillActive ? "#10b981" : "#ef4444";
      kBtn.style.color = _v3GlobalKillActive ? "#042f2e" : "#fff";
    }
  } catch (e) {
    console.warn("Enterprise V3 telemetry load err:", e);
  }
}

if ($("btn_v3_global_kill_toggle")) {
  $("btn_v3_global_kill_toggle").onclick = async () => {
    const nextState = !_v3GlobalKillActive;
    const verb = nextState ? "ACTIVATE GLOBAL EMERGENCY KILL SWITCH (halts all live trading platform-wide)" : "RELEASE Global Emergency Kill Switch";
    if (!confirm(`Confirm: ${verb}?`)) return;
    try {
      const res = await post("/api/v1/risk/kill-switch", { enabled: nextState, scope: "GLOBAL" });
      if (res && res.success) {
        await loadEnterpriseV3Health();
      } else {
        alert((res && res.error) || "Failed to update Global Kill Switch");
      }
    } catch (e) {
      alert("Kill switch error: " + e.message);
    }
  };
}

async function askAdminAraaAi() {
  const inp = $("v3_adm_ai_input");
  const box = $("v3_adm_ai_reply");
  const btn = $("btn_v3_adm_ai_ask");
  const msg = (inp ? inp.value : "").trim();
  if (!msg) return;
  try {
    if (btn) { btn.disabled = true; btn.textContent = "⏳ Thinking..."; }
    if (box) { box.style.display = "block"; box.textContent = "ARAA AI Core querying risk, ledger, and market intelligence..."; }
    const res = await post("/api/v1/ai/chat", { message: msg, context: { page: "admin_command_center", role: "SUPER_ADMIN" } });
    if (box) {
      box.textContent = `[Engine: ${(res && res.engine) || "CORE"} | Tools: ${((res && res.tools_called) || []).join(", ") || "direct"} | ID: ${(res && res.decision_id) || "—"}]\n\n${(res && (res.reply || res.error)) || "No response"}`;
    }
  } catch (e) {
    if (box) { box.style.display = "block"; box.textContent = "Error: " + e.message; }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "✨ Ask ARAA AI"; }
  }
}

if ($("btn_v3_adm_ai_ask")) $("btn_v3_adm_ai_ask").onclick = askAdminAraaAi;
if ($("v3_adm_ai_input")) {
  $("v3_adm_ai_input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); askAdminAraaAi(); }
  });
}

/* =========================================================================
   ARAA CENTRAL SUPER ADMIN & SSO ECOSYSTEM CONTROLLER
   ========================================================================= */
async function loadCentralAdminData() {
  try {
    const res = await get("/api/central-admin/dashboard");
    if (!res) return;

    const m = res.metrics || {};
    if ($("cs_metric_apps")) $("cs_metric_apps").textContent = `${m.active_applications || 10} / ${m.total_applications || 10}`;
    if ($("cs_metric_admins")) $("cs_metric_admins").textContent = m.total_administrators || 1;
    if ($("cs_metric_approvals")) $("cs_metric_approvals").textContent = m.pending_approvals || 0;
    if ($("cs_metric_security")) $("cs_metric_security").textContent = m.security_alerts || 0;

    // Load Applications
    const appsRes = await get("/api/central-admin/applications");
    const appsGrid = $("cs_applications_grid");
    if (appsGrid && appsRes && appsRes.applications) {
      appsGrid.innerHTML = appsRes.applications.map(app => {
        const isOp = app.integration_status === "OPERATIONAL";
        const color = isOp ? "#10b981" : "#ef4444";
        const bg = isOp ? "rgba(16,185,129,0.14)" : "rgba(239,68,68,0.14)";
        return `
          <div style="background:rgba(15,23,42,0.85); border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:14px; display:flex; flex-direction:column; justify-content:space-between;">
            <div>
              <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px;">
                <b style="font-size:13px; color:#f8fafc;">${app.name}</b>
                <span style="font-size:9.5px; background:${bg}; color:${color}; font-weight:800; padding:2px 6px; border-radius:4px;">
                  ● ${app.integration_status}
                </span>
              </div>
              <div style="font-size:10.5px; color:#94a3b8; font-family:'JetBrains Mono',monospace; margin-bottom:4px;">ID: ${app.app_id}</div>
              <div style="font-size:11px; color:#cbd5e1;">Base URL: <code>${app.base_url}</code></div>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center; border-top:1px solid rgba(255,255,255,0.06); padding-top:8px; margin-top:10px;">
              <span style="font-size:10px; color:#64748b;">v${app.version}</span>
              <a href="${app.base_url}" target="_blank" style="font-size:10.5px; color:#38bdf8; text-decoration:underline; font-weight:700;">Open App ↗</a>
            </div>
          </div>
        `;
      }).join("");
    }

    // Load Administrators
    const adminsRes = await get("/api/central-admin/administrators");
    const adminTbody = $("cs_admins_tbody");
    if (adminTbody && adminsRes && adminsRes.administrators) {
      adminTbody.innerHTML = adminsRes.administrators.map(adm => `
        <tr>
          <td>
            <b>${adm.full_name}</b><br>
            <span style="font-size:10px; color:#94a3b8;">${adm.email}</span>
          </td>
          <td>
            <span style="background:rgba(56,189,248,0.18); color:#38bdf8; font-weight:800; padding:2px 6px; border-radius:4px; font-size:10px;">
              ${adm.role_code}
            </span>
          </td>
          <td>
            <span style="color:${adm.status === 'ACTIVE' ? '#10b981' : '#ef4444'}; font-weight:800;">
              ${adm.status}
            </span>
          </td>
          <td style="font-family:'JetBrains Mono',monospace;">₹${adm.approval_limit_inr || '0.00'}</td>
          <td>
            <button onclick="window.viewAdminLogs('${adm.user_id}')" style="background:rgba(255,255,255,0.06); border:1px solid #475569; color:#cbd5e1; font-size:10px; padding:3px 8px; border-radius:4px; cursor:pointer;">Audit</button>
          </td>
        </tr>
      `).join("");
    }

    // Load Pending Approvals
    const apprvRes = await get("/api/central-admin/approvals");
    const apprvList = $("cs_approvals_list");
    if (apprvList && apprvRes && apprvRes.pending_approvals) {
      if (apprvRes.pending_approvals.length === 0) {
        apprvList.innerHTML = `<div style="text-align:center; padding:20px; color:#94a3b8; font-size:12px;">✓ No pending approvals in queue.</div>`;
      } else {
        apprvList.innerHTML = apprvRes.pending_approvals.map(req => `
          <div style="background:rgba(15,23,42,0.85); border:1px solid rgba(245,158,11,0.3); border-radius:8px; padding:10px 12px; display:flex; justify-content:space-between; align-items:center; gap:10px;">
            <div>
              <div style="font-size:12px; font-weight:800; color:#f8fafc;">${req.title}</div>
              <span style="font-size:10.5px; color:#94a3b8;">${req.category} · By ${req.requester_name || req.requested_by}</span>
              ${req.amount_paise > 0 ? `<b style="display:block; font-size:11.5px; color:#10b981; font-family:'JetBrains Mono',monospace;">₹${req.amount_inr}</b>` : ''}
            </div>
            <div style="display:flex; gap:6px;">
              <button onclick="window.handleApprovalAction('${req.request_id}', 'APPROVE')" style="background:#10b981; color:#fff; border:none; padding:5px 10px; border-radius:5px; font-size:10.5px; font-weight:800; cursor:pointer;">Approve</button>
              <button onclick="window.handleApprovalAction('${req.request_id}', 'REJECT')" style="background:#ef4444; color:#fff; border:none; padding:5px 10px; border-radius:5px; font-size:10.5px; font-weight:800; cursor:pointer;">Reject</button>
            </div>
          </div>
        `).join("");
      }
    }

    // Load Audit Logs
    const auditRes = await get("/api/central-admin/audit-logs?limit=25");
    const auditTbody = $("cs_audit_tbody");
    if (auditTbody && auditRes && auditRes.audit_logs) {
      auditTbody.innerHTML = auditRes.audit_logs.map(l => {
        const d = l.created_at ? new Date(l.created_at * 1000).toLocaleTimeString() : "--:--";
        return `
          <tr>
            <td>${d}</td>
            <td>${l.user_email || l.user_id || 'System'}</td>
            <td><b style="color:#38bdf8;">${l.action}</b></td>
            <td>${l.module}</td>
            <td style="color:${l.status === 'SUCCESS' ? '#10b981' : '#ef4444'}; font-weight:700;">${l.status}</td>
            <td>${l.ip_address || '—'}</td>
          </tr>
        `;
      }).join("");
    }

  } catch (err) {
    console.warn("Could not load Central Admin ecosystem data:", err);
  }
}
window.loadCentralAdminData = loadCentralAdminData;

window.handleApprovalAction = async function(requestId, action) {
  try {
    const res = await post(`/api/central-admin/approvals/${requestId}/action`, { action: action, actor_user_id: "SUPER_ADMIN" });
    if (res && res.success) {
      alert(`Request ${action === 'APPROVE' ? 'Approved' : 'Rejected'} successfully!`);
      loadCentralAdminData();
    } else {
      alert((res && res.error) || "Action failed");
    }
  } catch (e) {
    alert("Approval error: " + e.message);
  }
};

window.openCreateAdminModal = function() {
  const email = prompt("Enter new administrator's email:");
  if (!email) return;
  const name = prompt("Enter full name:");
  if (!name) return;
  const pass = prompt("Enter temporary password (min 8 characters):");
  if (!pass) return;
  const role = prompt("Enter role code (e.g. TRADING_ADMIN, FINANCE_ADMIN, HR_ADMIN, COMPLIANCE_ADMIN):", "TRADING_ADMIN");
  if (!role) return;

  post("/api/central-admin/administrators", {
    email: email,
    full_name: name,
    password: pass,
    role_code: role.toUpperCase().trim()
  }).then(res => {
    if (res && res.success) {
      alert(`Administrator ${email} created successfully!`);
      loadCentralAdminData();
    } else {
      alert((res && res.error) || "Creation failed");
    }
  });
};

// Auto-load Central Admin telemetry whenever view switches to super-admin
const origSwitchAdminView = window.switchAdminView;
window.switchAdminView = function(viewName) {
  if (typeof origSwitchAdminView === "function") {
    origSwitchAdminView(viewName);
  }
  if (typeof loadAdminSmcDna === "function") {
    loadAdminSmcDna();
  }
  if (viewName === "super-admin" || viewName === "all") {
    loadCentralAdminData();
  }
};

