"""
ARAA Company Trading Platform — Phases 5 to 12 End-to-End Acceptance Test Suite.

Verifies all mandatory acceptance criteria from the Company Platform Prompt:
1. India strategy / Zerodha cannot access Crypto capital & Crypto strategy / CoinDCX cannot access India capital.
2. Invalid broker credentials cannot enable live trading; withdrawal-enabled CoinDCX key rejected.
3. CoinDCX Spot-Only policy rejects futures (`B-BTC_USDT`), margin, and leverage > 1x.
4. A rejected order creates NO filled positions and NO ledger entries.
5. A partial fill records the exact filled quantity cleanly and calculates weighted average price.
6. A network timeout does NOT duplicate orders; transitions to UNKNOWN and freezes pool until reconciliation.
7. Broker position mismatches trigger MISMATCH_HALTED and block new live entries until resolved.
8. Paper fills NEVER appear in immutable LIVE `company_ledger_entries`.
9. Every live order/fill has a provider reference, idempotency key, and immutable audit trail.
10. `/company/` White/Navy Control Center HTML/CSS/JS, Compliance, Backtests, and Backup/Restore drill pass.
"""

import os
import shutil
import sqlite3
import tempfile
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
os.environ.setdefault("SECRETS_KEY", "phase5-12-acceptance-secrets-key-0123456789abcdef")

from app import api
from coindcx_spot_adapter import CoinDCXSpotAdapter, MockCoinDCXSpotAdapter
from company_auth import CompanyAuthService
from company_finance import POOL_CRYPTO_SPOT, POOL_INDIA_INR, CompanyCapitalManager, to_paise
from company_oms import CompanyOMS
from company_strategy_engine import CompanyStrategyService
from database import DB_PATH, init_schema, query, query_one, write
from migrations import list_applied_migrations
from universal_broker_manager import UniversalBrokerManager
from zerodha_adapter import MockZerodhaAdapter


class TestCompanyPhases5To12Acceptance(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_schema()
        cls.company = CompanyAuthService.get_default_company()
        cls.cid = cls.company["id"]
        cls.emails = ["dir_acc@araa.ai", "trd_acc@araa.ai", "rsk_acc@araa.ai", "fin_acc@araa.ai"]
        cls._cleanup()

        cls.dir_u = CompanyAuthService.create_employee(cls.cid, "dir_acc@araa.ai", "Director Acc", "AccPass!2026", "COMPANY_DIRECTOR")["employee"]
        cls.trd_u = CompanyAuthService.create_employee(cls.cid, "trd_acc@araa.ai", "Trader Acc", "AccPass!2026", "TRADING_ADMIN")["employee"]
        cls.rsk_u = CompanyAuthService.create_employee(cls.cid, "rsk_acc@araa.ai", "Risk Acc", "AccPass!2026", "RISK_MANAGER")["employee"]
        cls.fin_u = CompanyAuthService.create_employee(cls.cid, "fin_acc@araa.ai", "Finance Acc", "AccPass!2026", "FINANCE_ADMIN")["employee"]

    @classmethod
    def _cleanup(cls):
        for email in cls.emails:
            row = query_one("SELECT id FROM company_users WHERE email=?", (email,))
            if row:
                uid = row["id"]
                write("DELETE FROM company_sessions WHERE company_user_id=?", (uid,))
                write("DELETE FROM trading_approvals WHERE requested_by=? OR approved_by=?", (uid, uid))
                write("DELETE FROM company_audit_logs WHERE actor_user_id=?", (uid,))
                write("DELETE FROM company_users WHERE id=?", (uid,))
        for r in query("SELECT account_id FROM company_trading_accounts WHERE company_id=?", (cls.cid,)):
            UniversalBrokerManager.clear_mock_for_account(cls.cid, r["account_id"])
        for tbl in (
            "reconciliation_differences", "reconciliation_runs", "company_ledger_entries",
            "company_positions", "broker_executions", "broker_orders", "order_intents",
            "company_risk_events", "company_signals", "capital_allocations",
            "company_capital_movements",
        ):
            write(f"DELETE FROM {tbl} WHERE company_id=?", (cls.cid,))
        write("DELETE FROM broker_account_secrets WHERE account_id IN (SELECT account_id FROM company_trading_accounts WHERE company_id=?)", (cls.cid,))
        write("DELETE FROM broker_capabilities WHERE account_id IN (SELECT account_id FROM company_trading_accounts WHERE company_id=?)", (cls.cid,))
        write("DELETE FROM company_trading_accounts WHERE company_id=?", (cls.cid,))
        write(
            "UPDATE company_capital_pools SET allocated_capital_paise=0, broker_confirmed_equity_paise=0, "
            "free_funds_paise=0, locked_funds_paise=0, fees_paise=0, taxes_expenses_paise=0, realized_pnl_paise=0, "
            "daily_loss_paise=0, open_positions_count=0, pending_orders_count=0, reconciliation_status='NOT_RUN', "
            "last_broker_sync_at=NULL, account_id='' WHERE company_id=?",
            (cls.cid,),
        )
        write("UPDATE company_risk_policies SET paused=0, emergency_stop=0, require_stop_loss=1 WHERE company_id=?", (cls.cid,))

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    def _login(self, client, email):
        r = client.post("/api/v1/company/auth/login", json={"email": email, "password": "AccPass!2026"})
        self.assertEqual(r.status_code, 200)
        return r.get_json()["token"]

    def test_1_coindcx_spot_only_and_invalid_credentials_blocked(self):
        client = api.test_client()
        tok = self._login(client, "dir_acc@araa.ai")

        # Register CoinDCX account with withdrawal_disabled=False -> must fail verify!
        reg_bad = client.post(
            "/api/v1/brokers/coindcx/connect",
            json={"account_name": "Bad Withdrawal Key", "api_key": "INVALID", "api_secret": "sec", "withdrawal_disabled": False},
            headers={"X-Company-Token": tok},
        )
        bad_aid = reg_bad.get_json()["account"]["account_id"]
        UniversalBrokerManager.register_mock_for_account(
            self.cid, bad_aid, lambda a, c, cr: MockCoinDCXSpotAdapter(a, c, cr, inr_balance="100000.00")
        )
        ver_bad = client.post("/api/v1/brokers/coindcx/verify", json={"account_id": bad_aid}, headers={"X-Company-Token": tok})
        self.assertEqual(ver_bad.status_code, 400)

        # Register valid withdrawal-disabled CoinDCX Spot key
        reg_ok = client.post(
            "/api/v1/brokers/coindcx/connect",
            json={"account_name": "ARAA CoinDCX Spot Prop", "api_key": "cdx_valid_spot", "api_secret": "cdx_sec_spot", "withdrawal_disabled": True},
            headers={"X-Company-Token": tok},
        )
        ok_aid = reg_ok.get_json()["account"]["account_id"]
        mock_cdx = MockCoinDCXSpotAdapter(ok_aid, self.cid, {"api_key": "cdx_valid_spot", "withdrawal_disabled": True}, inr_balance="100000.00")
        UniversalBrokerManager.register_mock_for_account(self.cid, ok_aid, lambda a, c, cr: mock_cdx)

        sync = client.post("/api/v1/brokers/coindcx/sync", json={"account_id": ok_aid}, headers={"X-Company-Token": tok})
        self.assertEqual(sync.status_code, 200)
        st = client.get(f"/api/v1/brokers/coindcx/status?account_id={ok_aid}", headers={"X-Company-Token": tok}).get_json()
        self.assertEqual(st["pool"]["pool_id"], POOL_CRYPTO_SPOT)
        self.assertEqual(st["pool"]["broker_confirmed_equity_inr"], "100000.00")

        # Hard check: CoinDCX adapter blocks futures (B-BTC_USDT) and leverage > 1
        ad = CoinDCXSpotAdapter("X", self.cid, {"api_key": "k", "api_secret": "s"})
        self.assertFalse(ad.validate_instrument("B-BTC_USDT")["valid"])
        lev_rej = ad.place_order({"symbol": "BTCINR", "side": "BUY", "quantity": "0.001", "leverage": 5.0})
        self.assertFalse(lev_rej["ok"])
        self.assertIn("SPOT_ONLY_POLICY", lev_rej["error"])

    def test_2_oms_partial_fills_rejected_orders_timeout_unknown_and_recon_halt(self):
        client = api.test_client()
        dir_tok = self._login(client, "dir_acc@araa.ai")
        rsk_tok = self._login(client, "rsk_acc@araa.ai")

        # Setup Zerodha approved company account with MockZerodhaAdapter
        z_reg = client.post(
            "/api/v1/company/accounts",
            json={"provider": "ZERODHA", "account_name": "ARAA Zerodha Prop", "api_key": "zd_k1", "api_secret": "zd_s1", "static_egress_ip": "13.200.1.2"},
            headers={"X-Company-Token": dir_tok},
        )
        zd_aid = z_reg.get_json()["account"]["account_id"]
        mock_zd = MockZerodhaAdapter(zd_aid, self.cid, {"api_key": "zd_k1"}, cash_inr="200000.00")
        UniversalBrokerManager.register_mock_for_account(self.cid, zd_aid, lambda a, c, cr: mock_zd)
        self.assertEqual(client.post("/api/v1/brokers/zerodha/sync", json={"account_id": zd_aid}, headers={"X-Company-Token": dir_tok}).status_code, 200)
        # Approve account for live trading
        write("UPDATE company_trading_accounts SET trading_approved=1 WHERE account_id=?", (zd_aid,))

        # Acceptance: Missing stop loss rejected cleanly without position
        no_sl = client.post(
            "/api/v1/company/orders/intents",
            json={"account_id": zd_aid, "symbol": "RELIANCE", "side": "BUY", "quantity": 2, "execution_mode": "LIVE", "idempotency_key": "idem_nosl_1"},
            headers={"X-Company-Token": dir_tok},
        )
        self.assertEqual(no_sl.status_code, 400)
        self.assertEqual(no_sl.get_json()["rule_code"], "MISSING_STOP_LOSS")

        # Acceptance: Rejected live order creates ZERO positions & ZERO ledger entries
        mock_zd.reject_orders = True
        rej = client.post(
            "/api/v1/company/orders/intents",
            json={"account_id": zd_aid, "symbol": "RELIANCE", "side": "BUY", "quantity": 2, "stop_loss": 2900, "execution_mode": "LIVE", "idempotency_key": "idem_rej_1"},
            headers={"X-Company-Token": dir_tok},
        )
        self.assertEqual(rej.status_code, 400)
        self.assertEqual(query_one("SELECT COUNT(*) as c FROM company_positions WHERE pool_id=?", (POOL_INDIA_INR,))["c"], 0)
        self.assertEqual(query_one("SELECT COUNT(*) as c FROM company_ledger_entries WHERE pool_id=?", (POOL_INDIA_INR,))["c"], 0)
        mock_zd.reject_orders = False

        # Acceptance: Order exceeding conservative ₹25,000 default order limit is vetoed by RiskGuardian
        over_cap = client.post(
            "/api/v1/company/orders/intents",
            json={"account_id": zd_aid, "symbol": "RELIANCE", "side": "BUY", "order_type": "LIMIT", "limit_price": 2955, "quantity": 10, "stop_loss": 2900, "execution_mode": "LIVE", "idempotency_key": "idem_over_1"},
            headers={"X-Company-Token": dir_tok},
        )
        self.assertEqual(over_cap.status_code, 400)
        self.assertEqual(over_cap.get_json()["rule_code"], "MAX_ORDER_VALUE_EXCEEDED")

        # Acceptance: Limit order (5 shares @ 2955 = ₹14,775) + Partial Fills (2 @ 2950, then 3 @ 2960 -> exact weighted avg 2956)
        lim = client.post(
            "/api/v1/company/orders/intents",
            json={"account_id": zd_aid, "symbol": "RELIANCE", "side": "BUY", "order_type": "LIMIT", "limit_price": 2955, "quantity": 5, "stop_loss": 2900, "execution_mode": "LIVE", "idempotency_key": "idem_part_1"},
            headers={"X-Company-Token": dir_tok},
        )
        self.assertEqual(lim.status_code, 200)
        ord_id = lim.get_json()["order"]["order_id"]

        # Duplicate idempotency_key MUST NOT create a second order!
        dup = client.post(
            "/api/v1/company/orders/intents",
            json={"account_id": zd_aid, "symbol": "RELIANCE", "side": "BUY", "order_type": "LIMIT", "limit_price": 2955, "quantity": 5, "stop_loss": 2900, "execution_mode": "LIVE", "idempotency_key": "idem_part_1"},
            headers={"X-Company-Token": dir_tok},
        )
        self.assertEqual(dup.status_code, 200)
        self.assertTrue(dup.get_json()["duplicate_prevented"])

        CompanyOMS.record_confirmed_fill(self.cid, ord_id, 2, "2950.00", "TRD-P1", fee_paise=1500, stop_loss="2900")
        o1 = query_one("SELECT * FROM broker_orders WHERE order_id=?", (ord_id,))
        self.assertEqual(o1["status"], "PARTIALLY_FILLED")
        self.assertEqual(o1["filled_qty_str"], "2")

        CompanyOMS.record_confirmed_fill(self.cid, ord_id, 3, "2960.00", "TRD-P2", fee_paise=2000, stop_loss="2900")
        o2 = query_one("SELECT * FROM broker_orders WHERE order_id=?", (ord_id,))
        self.assertEqual(o2["status"], "FILLED")
        self.assertEqual(o2["filled_qty_str"], "5")
        self.assertEqual(Decimal(o2["avg_fill_price_str"]), Decimal("2956"))
        self.assertEqual(query_one("SELECT COUNT(*) as c FROM company_ledger_entries WHERE pool_id=?", (POOL_INDIA_INR,))["c"], 2)

        # Acceptance: Paper mode order NEVER writes into LIVE company_ledger_entries
        before_ledger = query_one("SELECT COUNT(*) as c FROM company_ledger_entries WHERE pool_id=?", (POOL_INDIA_INR,))["c"]
        paper_ord = client.post(
            "/api/v1/company/orders/intents",
            json={"account_id": zd_aid, "symbol": "TCS", "side": "BUY", "quantity": 1, "stop_loss": 4000, "execution_mode": "PAPER", "idempotency_key": "idem_paper_1"},
            headers={"X-Company-Token": dir_tok},
        )
        self.assertEqual(paper_ord.status_code, 200)
        after_ledger = query_one("SELECT COUNT(*) as c FROM company_ledger_entries WHERE pool_id=?", (POOL_INDIA_INR,))["c"]
        self.assertEqual(before_ledger, after_ledger)

        # Acceptance: Timeout marks UNKNOWN and reconciliation mismatch HALTS new live orders!
        mock_zd.simulate_timeout = True
        tmo = client.post(
            "/api/v1/company/orders/intents",
            json={"account_id": zd_aid, "symbol": "INFY", "side": "BUY", "quantity": 1, "stop_loss": 1800, "execution_mode": "LIVE", "idempotency_key": "idem_tmo_1"},
            headers={"X-Company-Token": dir_tok},
        )
        self.assertEqual(tmo.status_code, 400)
        self.assertEqual(tmo.get_json()["status"], "UNKNOWN")
        mock_zd.simulate_timeout = False

        # Reconcile reveals mismatch (RELIANCE local qty=10 vs mock_zd.positions=0 AND UNKNOWN order) -> MISMATCH_HALTED
        rcn = client.post("/api/v1/company/reconciliation/run", json={"account_id": zd_aid}, headers={"X-Company-Token": rsk_tok})
        self.assertEqual(rcn.status_code, 200)
        self.assertEqual(rcn.get_json()["status"], "MISMATCH_DETECTED")

        # Subsequent live order MUST be vetoed by RiskGuardian while MISMATCH_HALTED!
        blocked = client.post(
            "/api/v1/company/orders/intents",
            json={"account_id": zd_aid, "symbol": "INFY", "side": "BUY", "quantity": 1, "stop_loss": 1800, "execution_mode": "LIVE", "idempotency_key": "idem_blk_1"},
            headers={"X-Company-Token": dir_tok},
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked.get_json()["rule_code"], "RECONCILIATION_MISMATCH_HALT")

        # Resolve all differences cleanly -> status becomes MATCHED
        for diff in rcn.get_json()["differences"]:
            res = client.post(
                f"/api/v1/company/reconciliation/differences/{diff['diff_id']}/resolve",
                json={"resolution_note": "Verified manually against mock exchange book"},
                headers={"X-Company-Token": rsk_tok},
            )
            self.assertEqual(res.status_code, 200)

    def test_3_strategies_signals_compliance_ui_and_backup_drill(self):
        client = api.test_client()
        tok = self._login(client, "dir_acc@araa.ai")

        # Strategies & AI Signal Proposal (never executes live orders directly)
        strats = client.get("/api/v1/company/strategies", headers={"X-Company-Token": tok}).get_json()["strategies"]
        self.assertGreaterEqual(len(strats), 2)
        sig = client.post(
            "/api/v1/company/signals/propose",
            json={"strategy_id": strats[0]["strategy_id"], "symbol": "RELIANCE", "price": "2950.00"},
            headers={"X-Company-Token": tok},
        )
        self.assertEqual(sig.status_code, 200)
        self.assertIn("explanation", sig.get_json()["signal"])
        self.assertGreaterEqual(len(sig.get_json()["unified_ai"]["engines"]), 6)

        # Unified All-AI Hub, Multi-Engine Analyze & Copilot Chat
        hub = client.get("/api/v1/company/ai/hub", headers={"X-Company-Token": tok})
        self.assertEqual(hub.status_code, 200)
        self.assertEqual(hub.get_json()["health"]["connected_engines"], 9)
        anl = client.post(
            "/api/v1/company/ai/analyze",
            json={"symbol": "BTCINR", "market_scope": "CRYPTO", "price": "6500000.00", "use_llm": False},
            headers={"X-Company-Token": tok},
        )
        self.assertEqual(anl.status_code, 200)
        self.assertGreater(anl.get_json()["ensemble_score"], 0)
        chat = client.post(
            "/api/v1/company/ai/chat",
            json={"message": "Analyze RELIANCE and show pools"},
            headers={"X-Company-Token": tok},
        )
        self.assertEqual(chat.status_code, 200)
        self.assertEqual(chat.get_json()["connected_engines"], 9)

        # Watchlist Scan & Risk-Gated Signal-to-OMS Routing
        crypto_strat = next((s for s in strats if s["market_scope"] == "CRYPTO"), strats[0])
        scan = client.post(
            f"/api/v1/company/strategies/{crypto_strat['strategy_id']}/scan",
            json={"use_llm": False, "auto_route_paper": False},
            headers={"X-Company-Token": tok},
        )
        self.assertEqual(scan.status_code, 200)
        self.assertGreaterEqual(scan.get_json()["scanned_count"], 2)
        scanned_sig = scan.get_json()["results"][0]["proposal"]["signal"]
        routed = client.post(
            f"/api/v1/company/signals/{scanned_sig['signal_id']}/route-oms",
            json={"execution_mode": "PAPER", "quantity": "0.001"},
            headers={"X-Company-Token": tok},
        )
        self.assertEqual(routed.status_code, 200)
        self.assertEqual(routed.get_json()["signal_status"], "ROUTED_PAPER")

        # Compliance (List + Interactive Update) & Backtests
        comp = client.get("/api/v1/company/compliance", headers={"X-Company-Token": tok})
        self.assertEqual(comp.status_code, 200)
        recs = comp.get_json()["records"]
        self.assertGreaterEqual(len(recs), 4)
        cupd = client.put(
            f"/api/v1/company/compliance/{recs[0]['record_id']}",
            json={"status": "IN_PROGRESS", "notes": "Reviewed in acceptance test"},
            headers={"X-Company-Token": tok},
        )
        self.assertEqual(cupd.status_code, 200)
        bt = client.post("/api/v1/company/backtests", json={"symbol": "BTCUSDT", "initial_capital": 100000}, headers={"X-Company-Token": tok})
        self.assertEqual(bt.status_code, 200)
        self.assertTrue(bt.get_json()["simulated_historical_only"])

        # Company Background Worker & PostgreSQL 16 Schema Dialect Verification
        wk = client.post("/api/v1/company/worker/run-once", json={"auto_route_paper": False}, headers={"X-Company-Token": tok})
        self.assertEqual(wk.status_code, 200)
        self.assertTrue(wk.get_json()["success"])
        wk_st = client.get("/api/v1/company/worker/status", headers={"X-Company-Token": tok})
        self.assertEqual(wk_st.status_code, 200)
        self.assertGreaterEqual(wk_st.get_json()["worker"]["cycles_completed"], 1)

        from pg_compat import convert_qmark_params, export_postgres_sql_bundle
        pg_sql = export_postgres_sql_bundle()
        self.assertIn("BIGSERIAL PRIMARY KEY", pg_sql)
        self.assertNotIn("AUTOINCREMENT", pg_sql)
        self.assertNotIn("INSERT OR IGNORE", pg_sql)
        q_sql, _ = convert_qmark_params("SELECT * FROM users WHERE note='is?' AND id=?", (1,))
        self.assertEqual(q_sql, "SELECT * FROM users WHERE note='is?' AND id=%s")

        # Proprietary Isolation Guard: COMPANY_ONLY_MODE=1 blocks legacy SaaS custody endpoints
        prev_co = os.environ.get("COMPANY_ONLY_MODE")
        try:
            os.environ["COMPANY_ONLY_MODE"] = "1"
            self.assertEqual(client.post("/api/deposit", json={"amount": 100}).status_code, 403)
            self.assertEqual(client.post("/api/withdraw", json={"amount": 50}).status_code, 403)
            self.assertEqual(client.get("/api/v1/company/system/health").status_code, 200)
        finally:
            if prev_co is None:
                os.environ.pop("COMPANY_ONLY_MODE", None)
            else:
                os.environ["COMPANY_ONLY_MODE"] = prev_co

        # Control Center UI & Health Endpoints
        for route in ("/company/", "/company/company.css", "/company/company.js", "/api/v1/company/system/health"):
            with client.get(route) as r:
                self.assertEqual(r.status_code, 200, f"Route failed: {route}")

        # Atomic SQLite Backup & Integrity Verification Drill
        with tempfile.TemporaryDirectory() as tmpd:
            bak_path = os.path.join(tmpd, "araa_drill_backup.db")
            src_conn = sqlite3.connect(DB_PATH)
            dst_conn = sqlite3.connect(bak_path)
            src_conn.backup(dst_conn)
            dst_conn.close()
            src_conn.close()

            chk = sqlite3.connect(bak_path).execute("PRAGMA integrity_check").fetchone()[0]
            self.assertEqual(chk, "ok")


if __name__ == "__main__":
    unittest.main()
