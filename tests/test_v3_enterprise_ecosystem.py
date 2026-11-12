"""
ARAA BOT V3 — ENTERPRISE ECOSYSTEM END-TO-END ACCEPTANCE TEST SUITE
Verifies:
1. EventBus persistent outbox & publishing
2. DoubleEntryLedger balance & trial balance
3. Multi-Bot Supervisor lifecycle (create, start, pause, stop, clone)
4. Institutional Risk Guardian pre-trade validation & kill switch
5. OMS/EMS Order creation, execution, and position management
6. Universal ARAA AI Core context-aware execution
7. Enterprise /api/v1/* REST API endpoints
"""

import os
import sys
import unittest
import time
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from database import init_schema, query, query_one, write, hash_password
from event_bus import get_event_bus, Events
from financial_ledger import DoubleEntryLedger
from bot_supervisor import BotSupervisor, BotLifecycleState
from risk_engine import InstitutionalRiskEngine, RiskGuardian
from oms_engine import OrderManagementSystem, ExecutionManagementSystem, PositionManager, PortfolioManager, OrderStatus
from araa_ai_core import get_araa_ai
from app import api


class TestV3EnterpriseEcosystem(unittest.TestCase):

    @classmethod
    def _cleanup_test_user(cls):
        for tbl in (
            "orders", "positions", "trades", "trading_bots",
            "deposits", "ledger_entries", "real_bot_configs",
            "bot_log", "broker_connections", "wallets", "sessions"
        ):
            write(f"DELETE FROM {tbl} WHERE user_id=?", (cls.user_id,))
        write("DELETE FROM users WHERE id=?", (cls.user_id,))

    @classmethod
    def setUpClass(cls):
        init_schema()
        cls.user_id = 999
        cls._cleanup_test_user()
        salt, pw_h = hash_password("test1234")
        write(
            "INSERT INTO users(id, email, name, pw_salt, pw_hash, bot_enabled, bot_max_positions, bot_trade_direction, bot_leverage, created_at) "
            "VALUES(?, 'v3test@araabot.ai', 'V3 Tester', ?, ?, 1, 5, 'SHORT', 100.0, ?)",
            (cls.user_id, salt, pw_h, time.time())
        )
        write("INSERT INTO wallets(user_id, deposit_balance, profit_balance, locked_balance) VALUES(?, 1000.0, 50.0, 0.0)",
              (cls.user_id,))
        write(
            "INSERT INTO broker_connections(user_id, broker_name, status, is_live_active, live_balance, live_equity, free_margin, max_positions, connected_at, last_synced_at) "
            "VALUES(?, 'COINDCX', 'CONNECTED_OFFLINE', 0, 1050.0, 1050.0, 1050.0, 5, ?, ?)",
            (cls.user_id, time.time(), time.time())
        )

    @classmethod
    def tearDownClass(cls):
        cls._cleanup_test_user()

    def test_1_event_bus_outbox_persistence(self):
        bus = get_event_bus()
        received = []
        bus.subscribe(Events.ORDER_CREATED, lambda ev: received.append(ev))

        evt_id = bus.publish(
            Events.ORDER_CREATED,
            aggregate_type="ORDER",
            aggregate_id="ORD-101",
            payload={"symbol": "BTCUSDT", "quantity": 0.05},
            user_id=self.user_id,
            sync_dispatch=True
        )
        self.assertTrue(evt_id.startswith("evt_"))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["payload"]["symbol"], "BTCUSDT")

        # Verify persisted into event_outbox
        row = query_one("SELECT * FROM event_outbox WHERE event_id=?", (evt_id,))
        self.assertIsNotNone(row)
        self.assertEqual(row["event_type"], Events.ORDER_CREATED)

    def test_2_double_entry_ledger_and_trial_balance(self):
        # 1. Customer deposits $500
        dep_res = DoubleEntryLedger.deposit_capital(self.user_id, 500.0, currency="USD", gateway="COINDCX")
        self.assertTrue(dep_res["success"])

        # 2. Process $100 realized profit with 30% brokerage
        brok_res = DoubleEntryLedger.process_profit_brokerage(self.user_id, realized_pnl=100.0)
        self.assertEqual(brok_res["brokerage_usd"], 30.0)
        self.assertEqual(brok_res["net_profit_usd"], 70.0)

        # 3. Trial balance verification: Debits == Credits
        tb = DoubleEntryLedger.get_trial_balance()
        self.assertTrue(tb["is_balanced"], f"Trial balance out of balance: {tb}")
        self.assertLess(tb["discrepancy"], 0.01)

    def test_3_multi_bot_supervisor_lifecycle(self):
        # Create bot
        b_res = BotSupervisor.create_bot(
            user_id=self.user_id,
            bot_name="Alpha Scalper 1",
            allocated_capital=250.0,
            max_leverage=50.0,
            execution_mode="PAPER"
        )
        self.assertTrue(b_res["success"])
        bot_id = b_res["bot_id"]

        # Start bot
        s_res = BotSupervisor.start_bot(bot_id, self.user_id)
        self.assertTrue(s_res["success"])
        self.assertEqual(s_res["status"], BotLifecycleState.PAPER_TRADING)

        # Pause bot
        p_res = BotSupervisor.pause_bot(bot_id, self.user_id)
        self.assertTrue(p_res["success"])
        self.assertEqual(p_res["status"], BotLifecycleState.PAUSED)

        # Clone bot
        c_res = BotSupervisor.clone_bot(bot_id, self.user_id, new_name="Alpha Scalper 2")
        self.assertTrue(c_res["success"])
        self.assertNotEqual(c_res["bot_id"], bot_id)

        # List user bots
        bots = BotSupervisor.list_user_bots(self.user_id)
        self.assertGreaterEqual(len(bots), 2)

    def test_4_risk_guardian_limits_and_kill_switch(self):
        status = RiskGuardian.evaluate_user_risk_status(self.user_id)
        self.assertIn("risk_status", status)
        self.assertTrue(status["can_trade"])

        # Activate user bot kill switch
        RiskGuardian.set_bot_kill_switch(self.user_id, enabled=True, reason="Unit test emergency halt")
        status_halted = RiskGuardian.evaluate_user_risk_status(self.user_id)
        self.assertFalse(status_halted["can_trade"])
        self.assertEqual(status_halted["risk_status"], "CRITICAL_BREACH")

        # Restore
        RiskGuardian.set_bot_kill_switch(self.user_id, enabled=False)

    def test_5_oms_ems_order_lifecycle(self):
        # Create order
        o_res = OrderManagementSystem.create_order(
            user_id=self.user_id,
            symbol="BTCUSDT",
            side="SHORT",
            order_type="MARKET",
            quantity=0.01,
            price=75000.0,
            leverage=20.0,
            is_paper=True
        )
        self.assertTrue(o_res["success"])
        order_id = o_res["order_id"]

        # Execute through EMS
        e_res = ExecutionManagementSystem.execute_order(order_id)
        self.assertTrue(e_res["success"])
        self.assertEqual(e_res["status"], OrderStatus.FILLED)
        pos_id = e_res["position_id"]

        # Close position
        c_res = PositionManager.close_position(pos_id, close_price=74000.0, reason="TAKE_PROFIT")
        self.assertTrue(c_res["success"])
        self.assertGreater(c_res["realized_pnl"], 0.0)

    def test_6_araa_ai_core_assistant(self):
        ai = get_araa_ai()
        chat_res = ai.process_chat(self.user_id, "Show my portfolio balance")
        self.assertIn("Portfolio Overview", chat_res["reply"])
        self.assertIn("Today P&L", chat_res["reply"])
        self.assertEqual(chat_res["tool_used"], "get_user_portfolio")

        pnl_res = ai.process_chat(self.user_id, "Show my profit and loss and trades")
        self.assertIn("Total Net P&L", pnl_res["reply"])
        self.assertEqual(pnl_res["tool_used"], "get_user_portfolio")

        analyze_res = ai.process_chat(self.user_id, "Analyze BTCUSDT trend and risk")
        self.assertIn("BTCUSDT", analyze_res["reply"])
        self.assertNotIn("Absorbing liquidity at support", analyze_res["reply"])
        self.assertIn("GRU Neural Forecast", analyze_res["reply"])
        self.assertEqual(analyze_res["engine"], "ARAA Quant AI v4.0")

        gold_res = ai.process_chat(self.user_id, "Should I buy GOLD today?")
        self.assertIn("XAUUSD", gold_res["reply"])

        scan_res = ai.process_chat(self.user_id, "What should I trade today best setups")
        self.assertEqual(scan_res["tool_used"], "scan_best_opportunities")

        size_res = ai.process_chat(self.user_id, "Calculate position size for 50000 with 1.5% risk on ETHUSDT")
        self.assertEqual(size_res["tool_used"], "position_size_calculator")
        self.assertIn("ETHUSDT", size_res["reply"])

        conn_res = ai.process_chat(self.user_id, "Check system connectivity and all engines")
        self.assertEqual(conn_res["tool_used"], "get_system_connectivity")
        self.assertIn("9/9", conn_res["reply"])

        bot_list_res = ai.process_chat(self.user_id, "List my trading bots")
        self.assertEqual(bot_list_res["tool_used"], "get_bot_status")

        bot_start_res = ai.process_chat(self.user_id, "Start my bot")
        self.assertEqual(bot_start_res["tool_used"], "control_user_bot")
        self.assertIn("RUNNING", bot_start_res["reply"])

        bot_pause_res = ai.process_chat(self.user_id, "Pause my bot")
        self.assertEqual(bot_pause_res["tool_used"], "control_user_bot")
        self.assertIn("PAUSED", bot_pause_res["reply"])

    def test_7_enterprise_v1_rest_api_endpoints(self):
        client = api.test_client()

        # 1. Health + ARAA AI Copilot + Gatekeeper status
        h = client.get("/api/v1/ai/health")
        self.assertEqual(h.status_code, 200)
        h_json = h.get_json()
        self.assertEqual(h_json["data"]["status"], "HEALTHY")
        self.assertEqual(h_json["data"]["connected_engines"], 9)

        gs = client.get("/api/gemini/status")
        self.assertEqual(gs.status_code, 200)
        self.assertTrue(gs.get_json()["connected"])
        self.assertTrue(gs.get_json()["araa_ai_active"])

        cp = client.get("/api/ai/copilot?symbol=BTCUSDT")
        self.assertEqual(cp.status_code, 200)
        self.assertEqual(cp.get_json()["guidance"]["engine"], "ARAA Quant AI v4.0")

        gk_unauth = client.get("/api/admin/adapter-gatekeeper")
        self.assertEqual(gk_unauth.status_code, 401)
        with api.test_request_context("/api/admin/adapter-gatekeeper"):
            from app import admin_adapter_gatekeeper
            gk_resp = admin_adapter_gatekeeper()
            rule6 = [r for r in gk_resp.get_json()["rules"] if r["id"] == 6][0]
            self.assertEqual(rule6["status"], "PASS")

        # 2. Markets prices
        p = client.get("/api/v1/markets/prices")
        self.assertEqual(p.status_code, 200)
        self.assertIn("BTCUSDT", p.get_json()["prices"])

        # 3. Risk status
        r = client.get("/api/v1/risk/status")
        self.assertEqual(r.status_code, 200)

        # 4. Bots
        b = client.get("/api/v1/bots")
        self.assertEqual(b.status_code, 200)

        # 5. Orders
        o = client.get("/api/v1/orders")
        self.assertEqual(o.status_code, 200)

        # 6. Positions
        pos = client.get("/api/v1/positions")
        self.assertEqual(pos.status_code, 200)

        # 7. Portfolio
        pf = client.get("/api/v1/portfolio")
        self.assertEqual(pf.status_code, 200)

        # 8. Wallet balances
        w = client.get("/api/v1/wallet/balances")
        self.assertEqual(w.status_code, 200)

        # 9. Admin Overview & System Health
        adm = client.get("/api/v1/admin/overview")
        self.assertEqual(adm.status_code, 200)
        self.assertTrue(adm.get_json()["overview"]["trial_balance_healthy"])

        sh = client.get("/api/v1/admin/system-health")
        self.assertEqual(sh.status_code, 200)
        self.assertTrue(sh.get_json()["financial_health"]["balanced"])

        # 10. Strategies & Ledger
        st = client.get("/api/v1/strategies")
        self.assertEqual(st.status_code, 200)
        lg = client.get("/api/v1/wallet/ledger")
        self.assertEqual(lg.status_code, 200)

        # 11. Universal ARAA AI Chat via X-Token session
        from database import set_state
        now_ts = time.time()
        write(
            "INSERT OR REPLACE INTO sessions(token, user_id, created_at, last_seen) VALUES('v3_test_tok', ?, ?, ?)",
            (self.user_id, now_ts, now_ts)
        )
        chat_res = client.post(
            "/api/v1/ai/chat",
            json={"message": "Show my portfolio balance"},
            headers={"X-Token": "v3_test_tok"}
        )
        self.assertEqual(chat_res.status_code, 200)
        self.assertIn("Portfolio Overview", chat_res.get_json()["reply"])
        write("DELETE FROM sessions WHERE token='v3_test_tok'")

        # 12. Admin Global Kill Switch toggle via X-Admin-Token
        adm_tok = "adm_test_v3_enterprise_tok"
        set_state(f"admin_session_{adm_tok}", json.dumps({"user": "test_admin", "time": time.time()}))
        ks_on = client.post(
            "/api/v1/risk/kill-switch",
            json={"enabled": True, "scope": "GLOBAL"},
            headers={"X-Admin-Token": adm_tok}
        )
        self.assertEqual(ks_on.status_code, 200)
        self.assertTrue(ks_on.get_json()["enabled"])
        ks_off = client.post(
            "/api/v1/risk/kill-switch",
            json={"enabled": False, "scope": "GLOBAL"},
            headers={"X-Admin-Token": adm_tok}
        )
        self.assertEqual(ks_off.status_code, 200)
        self.assertFalse(ks_off.get_json()["enabled"])
        write("DELETE FROM platform_state WHERE key=?", (f"admin_session_{adm_tok}",))

    def test_8_universal_real_mode_500x_and_az_rules(self):
        from real_broker import verify_universal_real_bot_rules, execute_real_order
        from risk_engine import RiskGuardian
        now_ts = time.time()
        # Reset user & global risk state cleanly for test
        RiskGuardian.set_global_kill_switch(False, "TEST_RESET")
        write("UPDATE users SET bot_trade_direction='BOTH', bot_leverage=500.0, bot_max_positions=10 WHERE id=?", (self.user_id,))
        write(
            "INSERT INTO real_bot_configs(user_id, provider_id, strategy_mode, max_order_size, max_daily_loss, max_leverage, bot_status, emergency_shutdown, created_at, updated_at) "
            "VALUES(?, 'COINDCX', 'PURE_CRYPTO', 50000.0, 250.0, 500.0, 'RUNNING', 0, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET max_order_size=50000.0, max_daily_loss=250.0, max_leverage=500.0, emergency_shutdown=0",
            (self.user_id, now_ts, now_ts)
        )

        # 1. Clean 500x leverage order passes all A-Z rules
        ok_500, msg_500, eff_lev = verify_universal_real_bot_rules(
            user_id=self.user_id, symbol="BTCUSDT", side="BUY", qty=0.05, leverage=500.0, price=70000.0, ai_win_prob=86
        )
        self.assertTrue(ok_500, msg_500)
        self.assertEqual(eff_lev, 500.0)

        # 2. Low ARAA AI win probability (<75%) blocks live execution across ANY broker
        blocked_ai = execute_real_order(
            symbol="BTCUSDT", side="BUY", qty=0.05, leverage=500.0, user_id=self.user_id, price=70000.0, ai_win_prob=55
        )
        self.assertFalse(blocked_ai["executed"])
        self.assertEqual(blocked_ai["mode"], "LIVE_REJECTED")
        self.assertIn("Rule 6", blocked_ai["error"])

        # 3. Trade direction rule (LONG only blocks SELL)
        write("UPDATE users SET bot_trade_direction='LONG' WHERE id=?", (self.user_id,))
        blocked_dir = execute_real_order(
            symbol="BTCUSDT", side="SELL", qty=0.05, leverage=500.0, user_id=self.user_id, price=70000.0, ai_win_prob=90
        )
        self.assertFalse(blocked_dir["executed"])
        self.assertEqual(blocked_dir["mode"], "LIVE_REJECTED")
        write("UPDATE users SET bot_trade_direction='BOTH' WHERE id=?", (self.user_id,))

        # 4. Emergency shutdown blocks any real order
        write("UPDATE real_bot_configs SET emergency_shutdown=1 WHERE user_id=?", (self.user_id,))
        blocked_em = execute_real_order(
            symbol="BTCUSDT", side="BUY", qty=0.05, leverage=500.0, user_id=self.user_id, price=70000.0, ai_win_prob=92
        )
        self.assertFalse(blocked_em["executed"])
        self.assertIn("Rule 0", blocked_em["error"])
        write("UPDATE real_bot_configs SET emergency_shutdown=0 WHERE user_id=?", (self.user_id,))

        # 5. Admin Main Bot ON enables user bots; Admin Main Bot OFF stops all user bots and closes open trades
        from app import api as flask_api
        from database import set_state
        adm_tok = "adm_main_bot_test_tok"
        set_state(f"admin_session_{adm_tok}", json.dumps({"user": "test_admin", "time": time.time()}))
        c = flask_api.test_client()
        on_res = c.post("/api/admin/bot/start", headers={"X-Admin-Token": adm_tok})
        self.assertEqual(on_res.status_code, 200)
        self.assertTrue(on_res.get_json()["botRunning"])
        u_after_on = query_one("SELECT bot_enabled FROM users WHERE id=?", (self.user_id,))
        self.assertEqual(u_after_on["bot_enabled"], 1)

        write(
            "INSERT INTO positions(user_id,symbol,source,side,qty,entry_price,margin,target_pct,stop_pct,status,current_price,unrealized_pnl,opened_at,leverage,category,is_live) "
            "VALUES(?, 'BTCUSDT', 'BOT', 'LONG', 0.01, 73600.0, 50.0, 50.0, 50.0, 'OPEN', 73600.0, 0.0, ?, 500.0, 'CRYPTO', 0)",
            (self.user_id, now_ts)
        )
        off_res = c.post("/api/admin/bot/stop", headers={"X-Admin-Token": adm_tok})
        self.assertEqual(off_res.status_code, 200)
        self.assertFalse(off_res.get_json()["botRunning"])
        self.assertIn("closed_positions", off_res.get_json())
        u_after_off = query_one("SELECT bot_enabled FROM users WHERE id=?", (self.user_id,))
        self.assertEqual(u_after_off["bot_enabled"], 0)
        rem_open = query_one("SELECT COUNT(*) as c FROM positions WHERE user_id=? AND status='OPEN'", (self.user_id,))
        self.assertEqual(rem_open["c"], 0)
        write("DELETE FROM platform_state WHERE key=?", (f"admin_session_{adm_tok}",))


if __name__ == "__main__":
    unittest.main()
