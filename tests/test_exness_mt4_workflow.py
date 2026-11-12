import unittest
import json
import time
import os
import sys

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from database import init_schema, query, query_one, write
from exness_gateway import (
    CONNECTION_STATUSES,
    generate_pairing_token,
    register_mt4_terminal,
    sync_mt4_state,
    pop_pending_action,
    register_order_callback,
    get_exness_client,
    manage_terminal_connection,
    validate_mt4_order_params,
)


class TestExnessMT4Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_schema()

    def setUp(self):
        self.user_id = 88001
        self.other_user_id = 88002
        self.account_login = "55019283"
        self.server = "Exness-Trial9"
        write("DELETE FROM mt4_pairing_tokens WHERE user_id IN (?, ?)", (self.user_id, self.other_user_id))
        write("DELETE FROM mt4_terminals WHERE user_id IN (?, ?)", (self.user_id, self.other_user_id))
        write("DELETE FROM mt4_commands WHERE user_id IN (?, ?)", (self.user_id, self.other_user_id))
        write("DELETE FROM broker_connections WHERE user_id IN (?, ?)", (self.user_id, self.other_user_id))
        write("DELETE FROM positions WHERE user_id IN (?, ?)", (self.user_id, self.other_user_id))

    def test_1_complete_demo_pairing_sync_and_broker_confirmed_execution(self):
        """
        Tests the full end-to-end workflow:
        Exness MT4 -> Customer MT4 Terminal -> ARAA MT4 Bridge -> Secure Backend ->
        AI Trading Engine -> Authenticated MT4 Order -> Exness Broker Execution -> ARAA Dashboard.
        """
        # 1. Verify all 8 required connection statuses exist
        for st in ("DISCONNECTED", "PAIRING", "CONNECTING", "CONNECTED", "SYNCING", "READY", "ERROR", "SUSPENDED"):
            self.assertIn(st, CONNECTION_STATUSES)

        # 2. Customer clicks Generate Connection Token (no password collected)
        tok_res = generate_pairing_token(
            user_id=self.user_id,
            brand_id="ARAA",
            account_login=self.account_login,
            expected_server=self.server,
            account_type="DEMO"
        )
        self.assertTrue(tok_res["success"])
        self.assertEqual(tok_res["status"], "PAIRING")
        pairing_token = tok_res["pairing_token"]
        self.assertTrue(pairing_token.startswith("ARAA-MT4-"))

        # Verify status in DB is PAIRING and NOT prematurely marked CONNECTED
        b_conn = query_one("SELECT * FROM broker_connections WHERE user_id=?", (self.user_id,))
        self.assertEqual(b_conn["status"], "PAIRING")
        self.assertEqual(b_conn["is_live_active"], 0)

        # 3. EA securely registers the terminal with the ARAA backend
        reg_res = register_mt4_terminal(
            pairing_token=pairing_token,
            account_login=self.account_login,
            server=self.server,
            terminal_id=f"TERM-ARAA-{self.account_login}",
            account_type="DEMO",
            currency="USD",
            balance=5000.00,
            equity=5000.00,
            free_margin=5000.00,
            margin=0.0,
            margin_level=0.0,
            leverage=500.0,
            trading_allowed=True,
            expert_enabled=True,
            brand_id="ARAA"
        )
        self.assertTrue(reg_res["success"])
        self.assertEqual(reg_res["status"], "READY")
        self.assertEqual(reg_res["account_type"], "DEMO")
        self.assertFalse(reg_res["live_trading_enabled"])
        terminal_id = reg_res["terminal_id"]
        session_token = reg_res["session_token"]

        # 4. Enforce customer isolation: Another user or wrong account number cannot reuse the pairing token
        hijack_res = register_mt4_terminal(
            pairing_token=pairing_token,
            account_login="99999999",
            server=self.server,
            brand_id="ARAA"
        )
        self.assertFalse(hijack_res["success"])

        # 5. EA sends heartbeat & full telemetry sync
        sync_res = sync_mt4_state(
            account_login=self.account_login,
            server=self.server,
            balance=5000.00,
            equity=5000.00,
            free_margin=5000.00,
            margin=0.0,
            token=session_token,
            terminal_id=terminal_id,
            account_type="DEMO",
            currency="USD",
            leverage=500.0,
            margin_level=0.0,
            trading_allowed=True,
            expert_enabled=True,
            open_positions=[]
        )
        self.assertTrue(sync_res["success"])
        self.assertEqual(sync_res["status"], "READY")

        # 6. AI Engine / Gateway queues an authenticated BUY order on XAUUSD
        client = get_exness_client(self.user_id, terminal_id)
        self.assertIsNotNone(client)
        self.assertTrue(client.is_heartbeat_alive)
        self.assertEqual(len(client.positions), 0)

        order_req = client.open_order(
            symbol="XAUUSD",
            side="BUY",
            price=2750.00,
            stop_loss=2740.00,
            take_profit=2770.00,
            custom_lot=0.10
        )
        self.assertTrue(order_req["success"])
        self.assertEqual(order_req["status"], "QUEUED_FOR_BROKER")
        self.assertFalse(order_req["broker_confirmed"])
        command_id = order_req["command_id"]
        nonce = order_req["nonce"]

        # CRITICAL RULE: Order must NOT appear in client.positions before broker confirmation!
        self.assertEqual(len(client.positions), 0)

        # Duplicate order prevention: Queuing the same symbol while in-flight is blocked
        dup_req = client.open_order(
            symbol="XAUUSD",
            side="BUY",
            price=2750.00,
            stop_loss=2740.00,
            take_profit=2770.00,
            custom_lot=0.10
        )
        self.assertFalse(dup_req["success"])
        self.assertIn("Duplicate order prevented", dup_req["error"])

        # 7. MT4 EA polls /api/mt4/poll with authenticated token
        polled = pop_pending_action(self.account_login, token=session_token, terminal_id=terminal_id)
        self.assertEqual(polled["action"], "ORDER_OPEN")
        self.assertEqual(polled["command_id"], command_id)
        self.assertEqual(polled["nonce"], nonce)
        self.assertEqual(polled["symbol"], "XAUUSD")
        self.assertEqual(polled["side"], "BUY")
        self.assertEqual(polled["lots"], 0.10)

        # 8. MT4 EA executes order on Exness Demo broker and reports real broker ticket & fill price
        real_broker_ticket = 104928371
        real_fill_price = 2750.15
        cb_res = register_order_callback(
            account_login=self.account_login,
            data={
                "command_id": command_id,
                "nonce": nonce,
                "status": "ORDER_OPENED",
                "mt4_ticket": real_broker_ticket,
                "symbol": "XAUUSD",
                "side": "BUY",
                "lots": 0.10,
                "price": real_fill_price,
            },
            token=session_token,
            terminal_id=terminal_id
        )
        self.assertTrue(cb_res["success"])
        self.assertEqual(cb_res["status"], "BROKER_CONFIRMED")
        self.assertEqual(cb_res["mt4_ticket"], real_broker_ticket)

        # Now — and only now — the position is recorded as OPEN with the broker's real ticket!
        self.assertEqual(len(client.positions), 1)
        self.assertEqual(client.positions[0]["mt4_ticket"], real_broker_ticket)
        self.assertEqual(client.positions[0]["entry_price"], real_fill_price)
        self.assertTrue(client.positions[0]["broker_confirmed"])

        # 9. Replay attack prevention: Re-sending the same callback/nonce is rejected
        replay_res = register_order_callback(
            account_login=self.account_login,
            data={
                "command_id": command_id,
                "nonce": nonce,
                "status": "ORDER_OPENED",
                "mt4_ticket": real_broker_ticket,
                "symbol": "XAUUSD",
                "side": "BUY",
                "lots": 0.10,
                "price": real_fill_price,
            },
            token=session_token,
            terminal_id=terminal_id
        )
        self.assertFalse(replay_res["success"])
        self.assertEqual(replay_res["code"], 409)

        # 10. Close order & reconcile final broker P&L
        close_req = client.close_order(str(real_broker_ticket), close_price=2758.15, reason="TARGET_HIT")
        self.assertTrue(close_req["success"])
        self.assertEqual(close_req["status"], "CLOSE_QUEUED")

        polled_close = pop_pending_action(self.account_login, token=session_token, terminal_id=terminal_id)
        self.assertEqual(polled_close["action"], "ORDER_CLOSE")
        self.assertEqual(polled_close["ticket"], real_broker_ticket)

        close_cb = register_order_callback(
            account_login=self.account_login,
            data={
                "command_id": polled_close["command_id"],
                "nonce": polled_close["nonce"],
                "status": "ORDER_CLOSED",
                "mt4_ticket": real_broker_ticket,
                "symbol": "XAUUSD",
                "lots": 0.10,
                "price": 2758.15,
                "profit": 80.00,
            },
            token=session_token,
            terminal_id=terminal_id
        )
        self.assertTrue(close_cb["success"])
        self.assertEqual(close_cb["status"], "CLOSE_CONFIRMED")
        self.assertEqual(len(client.positions), 0)

        pos_db = query_one("SELECT * FROM positions WHERE user_id=? AND mt4_ticket=?", (self.user_id, real_broker_ticket))
        self.assertIsNotNone(pos_db)
        self.assertEqual(pos_db["status"], "CLOSED")
        self.assertEqual(pos_db["realized_pnl"], 80.00)

    def test_2_security_live_approval_and_connection_management(self):
        """Tests Real account live trading lock, parameter validation, and connection actions."""
        # Validate parameter checks (symbol, lot size, SL/TP direction, free margin)
        bad_sym = validate_mt4_order_params("FAKESYMBOL", "BUY", 0.10, 100.0)
        self.assertFalse(bad_sym["valid"])

        bad_sl = validate_mt4_order_params("EURUSD", "BUY", 0.10, price=1.0850, sl=1.0900, tp=1.0950)
        self.assertFalse(bad_sl["valid"])

        # Connect a REAL account -> Live trading must be disabled by default
        tok = generate_pairing_token(self.user_id, account_login="77001122", expected_server="Exness-Real10", account_type="REAL")
        reg = register_mt4_terminal(
            pairing_token=tok["pairing_token"],
            account_login="77001122",
            server="Exness-Real10",
            account_type="REAL",
            balance=2000.0,
            equity=2000.0,
            free_margin=2000.0
        )
        self.assertTrue(reg["success"])
        client = get_exness_client(self.user_id, reg["terminal_id"])

        # Order on REAL account must be blocked before customer approves Live trading
        blocked = client.open_order("EURUSD", "BUY", 1.0850, stop_loss=1.0820, take_profit=1.0910, custom_lot=0.05)
        self.assertFalse(blocked["success"])
        self.assertIn("disabled by default", blocked["error"])

        # Approve Live trading explicitly
        app_res = manage_terminal_connection(self.user_id, "APPROVE_LIVE", terminal_id=reg["terminal_id"], live_approved=True)
        self.assertTrue(app_res["success"])
        self.assertTrue(app_res["live_trading_approved"])

        # Now order queuing succeeds
        allowed = client.open_order("EURUSD", "BUY", 1.0850, stop_loss=1.0820, take_profit=1.0910, custom_lot=0.05)
        self.assertTrue(allowed["success"])

        # Test connection management actions: TEST_CONNECTION, REFRESH_ACCOUNT, DISCONNECT, RECONNECT, REMOVE_ACCOUNT
        t_conn = manage_terminal_connection(self.user_id, "TEST_CONNECTION", terminal_id=reg["terminal_id"])
        self.assertTrue(t_conn["success"])

        r_acct = manage_terminal_connection(self.user_id, "REFRESH_ACCOUNT", terminal_id=reg["terminal_id"])
        self.assertTrue(r_acct["success"])

        disc = manage_terminal_connection(self.user_id, "DISCONNECT", terminal_id=reg["terminal_id"])
        self.assertEqual(disc["connection_status"], "DISCONNECTED")

        reconn = manage_terminal_connection(self.user_id, "RECONNECT", terminal_id=reg["terminal_id"])
        self.assertTrue(reconn["success"])

        rem = manage_terminal_connection(self.user_id, "REMOVE_ACCOUNT", terminal_id=reg["terminal_id"])
        self.assertTrue(rem["success"])
        self.assertIsNone(get_exness_client(self.user_id, reg["terminal_id"]))

    def test_3_flask_http_endpoints_end_to_end(self):
        """Tests the actual Flask REST endpoints (/api/mt4/register, /api/mt4/sync, /api/mt4/poll, /api/mt4/order_callback)."""
        from app import api
        client_http = api.test_client()

        # Generate pairing token
        tok = generate_pairing_token(self.user_id, account_login="66009911", expected_server="Exness-Trial2", account_type="DEMO")
        pairing_token = tok["pairing_token"]

        # 1. POST /api/mt4/register (EA Step 13)
        reg_resp = client_http.post(
            "/api/mt4/register",
            json={
                "pairing_token": pairing_token,
                "account": "66009911",
                "server": "Exness-Trial2",
                "account_type": "DEMO",
                "currency": "USD",
                "balance": 10000.0,
                "equity": 10000.0,
                "free_margin": 10000.0,
                "trading_allowed": True,
                "expert_enabled": True,
            },
            headers={"X-Araa-Token": pairing_token}
        )
        self.assertEqual(reg_resp.status_code, 200)
        reg_data = reg_resp.get_json()
        self.assertTrue(reg_data["success"])
        self.assertEqual(reg_data["status"], "READY")
        term_id = reg_data["terminal_id"]
        sess_token = reg_data["session_token"]

        # 2. Queue an order via ExnessMT4Client
        ex_client = get_exness_client(self.user_id, term_id)
        q_res = ex_client.open_order("EURUSD", "SELL", 1.0845, stop_loss=1.0880, take_profit=1.0780, custom_lot=0.20)
        self.assertTrue(q_res["success"])
        self.assertEqual(len(ex_client.positions), 0)

        # 3. GET /api/mt4/poll (EA polls authenticated command)
        poll_resp = client_http.get(
            f"/api/mt4/poll?account=66009911&terminal_id={term_id}",
            headers={"X-Araa-Token": sess_token}
        )
        self.assertEqual(poll_resp.status_code, 200)
        poll_data = poll_resp.get_json()
        self.assertEqual(poll_data["action"], "ORDER_OPEN")
        self.assertEqual(poll_data["command_id"], q_res["command_id"])

        # 4. POST /api/mt4/order_callback (EA reports broker execution)
        cb_resp = client_http.post(
            "/api/mt4/order_callback",
            json={
                "account": "66009911",
                "terminal_id": term_id,
                "command_id": poll_data["command_id"],
                "nonce": poll_data["nonce"],
                "status": "ORDER_OPENED",
                "mt4_ticket": 88991122,
                "symbol": "EURUSD",
                "side": "SELL",
                "lots": 0.20,
                "price": 1.0844,
            },
            headers={"X-Araa-Token": sess_token}
        )
        self.assertEqual(cb_resp.status_code, 200)
        cb_data = cb_resp.get_json()
        self.assertTrue(cb_data["success"])
        self.assertEqual(cb_data["mt4_ticket"], 88991122)

        # 5. POST /api/mt4/sync (EA syncs open position & equity)
        sync_resp = client_http.post(
            "/api/mt4/sync",
            json={
                "account": "66009911",
                "terminal_id": term_id,
                "server": "Exness-Trial2",
                "balance": 10000.0,
                "equity": 10024.50,
                "free_margin": 9980.0,
                "margin": 44.50,
                "margin_level": 22526.9,
                "trading_allowed": True,
                "expert_enabled": True,
                "open_positions": [
                    {
                        "ticket": 88991122,
                        "symbol": "EURUSD",
                        "side": "SELL",
                        "lots": 0.20,
                        "entry_price": 1.0844,
                        "current_price": 1.0832,
                        "sl": 1.0880,
                        "tp": 1.0780,
                        "profit": 24.50,
                    }
                ],
            },
            headers={"X-Araa-Token": sess_token}
        )
        self.assertEqual(sync_resp.status_code, 200)
        sync_data = sync_resp.get_json()
        self.assertEqual(sync_data["status"], "READY")
        self.assertEqual(sync_data["open_positions_count"], 1)
        self.assertEqual(ex_client.positions[0]["unrealized_pnl"], 24.50)


if __name__ == "__main__":
    unittest.main()
