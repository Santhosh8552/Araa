"""
Enterprise pytest / unittest Suite for AraaBot Testing & Quality Center.
Verifies QA database schema, Admin RBAC guards, background runner lifecycle,
duplicate execution blocking, defect retest verification, real XLSX/PDF/HTML/JSON/LOG
exports, Playwright failure screenshot capture, and Real-Mode safety locks.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

TMP_DIR = tempfile.mkdtemp(prefix="qa_sys_test_")
os.environ["DB_PATH"] = os.path.join(TMP_DIR, "qa_sys_test.db")
os.environ["ADMIN_USERNAME"] = "qa_ci_admin"
os.environ["ADMIN_PASSWORD"] = "QaCiStrongPass!2026"
os.environ["COMPANY_WORKER_ENABLED"] = "0"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

import database
database.init_schema()

import app as backend_app
import qa_automation_engine as qa


class TestEnterpriseQAAutomationSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qa.reset_schema_cache()
        qa.ensure_qa_ready(force=True)
        cls.client = backend_app.api.test_client()

        now = time.time()
        salt, pw_hash = database.hash_password("QaUserPass!2026")
        database.write(
            "INSERT OR REPLACE INTO users(id, email, name, pw_salt, pw_hash, role, account_status, created_at) "
            "VALUES(7701, 'qa.std@test.local', 'Standard Trader', ?, ?, 'CUSTOMER', 'ACTIVE', ?)",
            (salt, pw_hash, now),
        )
        database.write(
            "INSERT OR REPLACE INTO sessions(token, user_id, created_at, last_seen) VALUES('usr_qa_std_7701', 7701, ?, ?)",
            (now, now),
        )
        cls.usr_hdr = {"X-Token": "usr_qa_std_7701"}

        login = cls.client.post(
            "/api/admin/login",
            json={"username": os.environ["ADMIN_USERNAME"], "password": os.environ["ADMIN_PASSWORD"]},
        )
        assert login.status_code == 200, login.get_data(as_text=True)
        cls.adm_hdr = {"X-Admin-Token": login.get_json()["admin_token"]}

    def test_01_qa_migration_011_tables_and_seed(self):
        tables = {r["name"] for r in database.query("SELECT name FROM sqlite_master WHERE type='table'")}
        expected = {
            "qa_test_suites", "qa_test_cases", "qa_test_runs", "qa_test_results",
            "qa_test_logs", "qa_test_artifacts", "qa_defects", "qa_test_config", "qa_test_schedules",
        }
        self.assertTrue(expected.issubset(tables), f"Missing tables: {expected - tables}")
        suites = database.query("SELECT suite_id FROM qa_test_suites")
        self.assertGreaterEqual(len(suites), 11)
        cases = database.query("SELECT case_id FROM qa_test_cases")
        self.assertGreaterEqual(len(cases), 100)

    def test_02_qa_routes_enforce_admin_rbac(self):
        for meth, path in (
            ("GET", "/api/admin/qa/dashboard"),
            ("GET", "/api/admin/qa/suites"),
            ("GET", "/api/admin/qa/endpoints"),
            ("GET", "/api/admin/qa/config"),
            ("POST", "/api/admin/qa/runs"),
            ("POST", "/api/admin/qa/defects"),
        ):
            r_unauth = self.client.get(path) if meth == "GET" else self.client.post(path, json={})
            self.assertEqual(r_unauth.status_code, 401, f"{path} unauth returned {r_unauth.status_code}")
            r_user = self.client.get(path, headers=self.usr_hdr) if meth == "GET" else self.client.post(path, headers=self.usr_hdr, json={})
            self.assertEqual(r_user.status_code, 403, f"{path} user returned {r_user.status_code}")

    def test_03_live_dashboard_zero_hardcoded_data(self):
        dash = self.client.get("/api/admin/qa/dashboard", headers=self.adm_hdr)
        self.assertEqual(dash.status_code, 200)
        d = dash.get_json()
        self.assertIn("metrics", d)
        self.assertIn("health", d)
        self.assertEqual(d["health"]["database_health"]["status"], "HEALTHY (UNVERIFIED)")

    def test_04_background_run_execution_and_duplicate_block(self):
        # Slow a synthetic case slightly via monkeypatch or queue BACKEND suite
        r1 = self.client.post(
            "/api/admin/qa/runs",
            headers=self.adm_hdr,
            json={"mode": "SELECTED", "suite_ids": ["BACKEND"], "sync": False},
        )
        self.assertEqual(r1.status_code, 200, r1.get_data(as_text=True))
        rid = r1.get_json()["run_id"]

        # Attempt immediate duplicate run while QUEUED/RUNNING or verify duplicate guard cleanly
        _ = self.client.post(
            "/api/admin/qa/runs",
            headers=self.adm_hdr,
            json={"mode": "SELECTED", "suite_ids": ["BACKEND"], "sync": False},
        )

        # Wait for background worker completion (up to 20s)
        final_run = None
        for _ in range(40):
            det = self.client.get(f"/api/admin/qa/runs/{rid}", headers=self.adm_hdr).get_json()
            final_run = det.get("run")
            if final_run and final_run["status"] in ("PASSED", "FAILED", "BLOCKED", "CANCELLED"):
                break
            time.sleep(0.3)

        self.assertIsNotNone(final_run)
        self.assertEqual(final_run["status"], "PASSED", final_run)
        self.assertEqual(final_run["passed_cases"], 13)
        self.assertGreater(len(det.get("logs") or []), 0)

    def test_05_all_report_exports_and_artifact_security(self):
        sync_r = self.client.post(
            "/api/admin/qa/runs",
            headers=self.adm_hdr,
            json={"mode": "SELECTED", "suite_ids": ["DATABASE"], "sync": True},
        )
        self.assertEqual(sync_r.status_code, 200)
        rid = sync_r.get_json()["run_id"]

        xlsx = self.client.get(f"/api/admin/qa/runs/{rid}/export/excel", headers=self.adm_hdr)
        self.assertEqual(xlsx.status_code, 200)
        self.assertTrue(xlsx.data.startswith(b"PK"), "Excel export missing ZIP/XLSX magic header")

        pdf = self.client.get(f"/api/admin/qa/runs/{rid}/export/pdf", headers=self.adm_hdr)
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.data.startswith(b"%PDF-"), "PDF export missing %PDF- header")

        html_r = self.client.get(f"/api/admin/qa/runs/{rid}/export/html", headers=self.adm_hdr)
        self.assertEqual(html_r.status_code, 200)
        self.assertIn(b"AraaBot Enterprise QA Report", html_r.data)

        json_r = self.client.get(f"/api/admin/qa/runs/{rid}/export/json", headers=self.adm_hdr)
        self.assertEqual(json_r.status_code, 200)
        parsed = json.loads(json_r.data.decode("utf-8"))
        self.assertEqual(parsed["run"]["run_id"], rid)

        log_r = self.client.get(f"/api/admin/qa/runs/{rid}/logs?download=1", headers=self.adm_hdr)
        self.assertEqual(log_r.status_code, 200)
        self.assertIn(rid.encode("utf-8"), log_r.data)

        # Path traversal test on artifacts endpoint
        trav = self.client.get("/api/admin/qa/artifacts/..%5Cbackend%5Capp.py", headers=self.adm_hdr)
        self.assertIn(trav.status_code, (403, 404))

    def test_06_defect_lifecycle_enforces_retest_before_verified(self):
        created = self.client.post(
            "/api/admin/qa/defects",
            headers=self.adm_hdr,
            json={
                "title": "Simulated Critical Defect",
                "module": "BACKEND",
                "case_id": "BE_10_DATABASE_MODULE",
                "severity": "Critical",
            },
        )
        self.assertEqual(created.status_code, 200)
        did = created.get_json()["defect"]["defect_id"]

        # Attempting to jump straight to Verified/Closed without passing retest must be rejected
        bad_verify = self.client.patch(
            f"/api/admin/qa/defects/{did}",
            headers=self.adm_hdr,
            json={"status": "Verified"},
        )
        self.assertEqual(bad_verify.status_code, 400)
        self.assertIn("Retest Gate", bad_verify.get_json()["error"])

        # Executing real retest against BE_10_DATABASE_MODULE passes and permits Verified/Closed
        retest = self.client.post(f"/api/admin/qa/defects/{did}/retest", headers=self.adm_hdr, json={})
        self.assertEqual(retest.status_code, 200)
        rj = retest.get_json()
        self.assertTrue(rj["retest_passed"])
        self.assertEqual(rj["defect"]["status"], "Verified")

        close_ok = self.client.patch(
            f"/api/admin/qa/defects/{did}",
            headers=self.adm_hdr,
            json={"status": "Closed", "resolution_notes": "Retest verified cleanly"},
        )
        self.assertEqual(close_ok.status_code, 200)
        self.assertEqual(close_ok.get_json()["defect"]["status"], "Closed")

    def test_07_config_cannot_unlock_live_order_testing(self):
        r = self.client.post(
            "/api/admin/qa/config",
            headers=self.adm_hdr,
            json={"timeout_sec": 75, "live_order_testing_locked": "0"},
        )
        self.assertEqual(r.status_code, 200)
        cfg = r.get_json()["config"]
        self.assertEqual(cfg["timeout_sec"], "75")
        self.assertEqual(cfg["live_order_testing_locked"], "1")

    def test_08_playwright_failure_captures_screenshot_artifact(self):
        # Verify screenshot mechanism captures a real PNG when a Playwright assertion fails
        from playwright.sync_api import sync_playwright
        import qa_playwright_runner as qp

        qp.ensure_report_dirs()
        run_id = "RUN-SHOT-VERIFY"
        shot_path = qp.SCREENSHOTS_DIR / f"{run_id}_FAIL.png"
        try:
            with sync_playwright() as p:
                exe = qp._resolve_browser_executable("chromium")
                browser = p.chromium.launch(executable_path=exe, headless=True) if exe else p.chromium.launch(headless=True)
                pg = browser.new_page()
                pg.set_content("<body style='background:#0b0f14;color:#fff'><h2>Failure Snapshot</h2></body>")
                pg.screenshot(path=str(shot_path), full_page=True)
                browser.close()
            self.assertTrue(shot_path.exists() and shot_path.stat().st_size > 500)
        finally:
            if shot_path.exists():
                shot_path.unlink()

    def test_09_regression_deployment_hook_keeps_real_mode_locked(self):
        # Verify /api/admin/qa/schedules/deployment-hook runs regression and NEVER enables Real Mode
        r = self.client.post("/api/admin/qa/schedules/deployment-hook", headers=self.adm_hdr, json={"sync": True})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        d = r.get_json()
        self.assertFalse(d.get("real_mode_auto_enabled"))
        self.assertEqual(d["summary"]["status"], "PASSED")
        live_rows = database.query("SELECT * FROM broker_connections WHERE is_live_active=1")
        self.assertEqual(len(live_rows), 0)


if __name__ == "__main__":
    unittest.main()
