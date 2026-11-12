"""Regression tests: admin API auth, live-close failure handling, secrets at rest."""
import os, sys, tempfile, time, unittest
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test_araa.db"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import database
from database import init_schema, query_one, write


class AdminAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_schema()
        import app as backend_app
        cls.client = backend_app.api.test_client()

    def setUp(self):
        for k in ("ADMIN_USERNAME", "ADMIN_PASSWORD"):
            os.environ.pop(k, None)

    def test_admin_routes_require_token(self):
        for path in ("/api/admin/users", "/api/admin/overview", "/api/admin/withdrawals"):
            self.assertEqual(self.client.get(path).status_code, 401, path)
        self.assertEqual(self.client.post("/api/admin/users/wipe-all").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/users", headers={"X-Admin-Token": "adm_fake"}).status_code, 401)

    def test_old_hardcoded_credentials_rejected(self):
        r = self.client.post("/api/admin/login", json={"username": "santhosh8552", "password": "Santhosh@09"})
        self.assertIn(r.status_code, (401, 503))

    def test_login_and_token_flow(self):
        os.environ["ADMIN_USERNAME"] = "boss"
        os.environ["ADMIN_PASSWORD"] = "correct horse battery"
        bad = self.client.post("/api/admin/login", json={"username": "boss", "password": "nope"})
        self.assertEqual(bad.status_code, 401)
        good = self.client.post("/api/admin/login", json={"username": "boss", "password": "correct horse battery"})
        self.assertEqual(good.status_code, 200)
        token = good.get_json()["admin_token"]
        self.assertEqual(self.client.get("/api/admin/users", headers={"X-Admin-Token": token}).status_code, 200)


class LiveCloseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_schema()

    def _live_pos(self):
        return write(
            "INSERT INTO positions(user_id, symbol, source, side, qty, entry_price, margin, target_pct, stop_pct, "
            "status, current_price, unrealized_pnl, opened_at, is_live, leverage) "
            "VALUES(9, 'BTCINR', 'COINDCX LIVE', 'LONG', 0.01, 100.0, 50.0, 1.8, 0.85, 'OPEN', 100.0, 0, ?, 1, 10.0)",
            (time.time(),))

    def test_failed_exchange_close_keeps_position_open_then_flags_manual(self):
        import real_broker
        from bot_engine import Bot
        from price_feed import PriceFeed
        orig = real_broker.close_real_order
        real_broker.close_real_order = lambda **kw: {"mode": "LIVE_ERROR", "closed": False, "error": "boom"}
        try:
            bot = Bot(PriceFeed())
            pid = self._live_pos()
            for _ in range(Bot.MAX_LIVE_CLOSE_RETRIES - 1):
                p = query_one("SELECT * FROM positions WHERE id=?", (pid,))
                self.assertIsNone(bot.close(p, 101.0, "TEST"))
                self.assertEqual(query_one("SELECT status FROM positions WHERE id=?", (pid,))["status"], "OPEN")
            p = query_one("SELECT * FROM positions WHERE id=?", (pid,))
            self.assertIsNotNone(bot.close(p, 101.0, "TEST"))
            row = query_one("SELECT status, close_reason FROM positions WHERE id=?", (pid,))
            self.assertEqual(row["status"], "CLOSED")
            self.assertIn("CHECK_MANUALLY", row["close_reason"])
        finally:
            real_broker.close_real_order = orig

    def test_confirmed_close_marks_closed(self):
        import real_broker
        from bot_engine import Bot
        from price_feed import PriceFeed
        orig = real_broker.close_real_order
        real_broker.close_real_order = lambda **kw: {"mode": "LIVE_REAL", "closed": True}
        try:
            bot = Bot(PriceFeed())
            pid = self._live_pos()
            p = query_one("SELECT * FROM positions WHERE id=?", (pid,))
            self.assertIsNotNone(bot.close(p, 101.0, "TEST"))
            self.assertEqual(query_one("SELECT status FROM positions WHERE id=?", (pid,))["status"], "CLOSED")
        finally:
            real_broker.close_real_order = orig


class SecretsAtRestTests(unittest.TestCase):
    def test_roundtrip_and_legacy_plaintext(self):
        os.environ["SECRETS_KEY"] = "unit-test-key"
        try:
            enc = database.encrypt_secret("my-api-secret")
            self.assertTrue(enc.startswith("enc1:") and "my-api-secret" not in enc)
            self.assertEqual(database.decrypt_secret(enc), "my-api-secret")
            self.assertEqual(database.decrypt_secret("legacy-plaintext"), "legacy-plaintext")
        finally:
            os.environ.pop("SECRETS_KEY", None)

    def test_no_key_means_passthrough(self):
        os.environ.pop("SECRETS_KEY", None)
        self.assertEqual(database.encrypt_secret("abc"), "abc")



class CoinDCXCloseRoutingTests(unittest.TestCase):
    """close_real_order must never report closed=True unless the exchange really closed."""

    class _Fut:
        def __init__(self, ok_positions=True, pos=None, exit_ok=True):
            self.is_offline = False
            self._ok, self._pos, self._exit_ok = ok_positions, pos, exit_ok
        def get_positions(self): return self._ok, ([self._pos] if self._pos else [])
        def find_open_position(self, symbol): return self._pos
        def exit_position(self, symbol):
            return (True, {"id": "x"}) if self._exit_ok else (False, {"message": "rejected"})

    class _Cdx:
        is_offline = False
        def __init__(self, fut, spot_ok=False):
            self.futures, self._spot_ok = fut, spot_ok
        def place_order(self, **kw):
            return (True, {"id": "s1"}) if self._spot_ok else (False, {"message": "spot down"})

    @classmethod
    def setUpClass(cls):
        init_schema()
        write("INSERT OR REPLACE INTO broker_connections(user_id, broker_name, connected_at, last_synced_at) VALUES(77, 'COINDCX', ?, ?)", (time.time(), time.time()))

    def _close(self, cdx, side="LONG", lev=10.0):
        import coindcx_gateway, real_broker
        orig = coindcx_gateway.get_user_coindcx_client
        coindcx_gateway.get_user_coindcx_client = lambda uid: cdx
        try:
            return real_broker.close_real_order(symbol="BTCUSDT", side=side, qty=0.01, user_id=77, price=100.0, leverage=lev)
        finally:
            coindcx_gateway.get_user_coindcx_client = orig

    def test_futures_exit_ok(self):
        r = self._close(self._Cdx(self._Fut(pos={"id": 1})))
        self.assertTrue(r["closed"])

    def test_futures_exit_rejected_is_not_closed(self):
        r = self._close(self._Cdx(self._Fut(pos={"id": 1}, exit_ok=False)))
        self.assertFalse(r["closed"])

    def test_positions_api_down_is_not_closed(self):
        r = self._close(self._Cdx(self._Fut(ok_positions=False)))
        self.assertFalse(r["closed"])

    def test_short_already_flat_counts_as_closed(self):
        r = self._close(self._Cdx(self._Fut(pos=None)), side="SHORT")
        self.assertTrue(r["closed"] and r.get("already_flat"))

    def test_spot_failure_is_not_reported_closed(self):
        r = self._close(self._Cdx(self._Fut(pos=None), spot_ok=False), side="LONG", lev=1.0)
        self.assertFalse(r["closed"])
        r = self._close(self._Cdx(self._Fut(pos=None), spot_ok=True), side="LONG", lev=1.0)
        self.assertTrue(r["closed"])


if __name__ == "__main__":
    unittest.main()
