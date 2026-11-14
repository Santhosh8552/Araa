import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend")))

from app import api as app
from database import query, query_one


class TestThemeSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        cls.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def _register_and_login(self, email="theme_tester@araabot.in"):
        self.client.post("/api/auth/register", json={"email": email, "name": "Theme Tester", "password": "Password123!"})
        res = self.client.post("/api/auth/login", json={"email": email, "password": "Password123!"})
        data = res.get_json()
        return data["token"], data["user"]

    def test_01_dark_and_light_design_tokens_present(self):
        with open(os.path.join(self.root_dir, "frontend/styles.css"), "r", encoding="utf-8") as f:
            styles = f.read()
        for token in (
            "--bg-primary: #0B0F14",
            "--bg-secondary: #111821",
            "--bg-card: #151D28",
            "--bg-elevated: #1B2634",
            "--text-primary: #F4F7FA",
            "--text-secondary: #A7B1C2",
            "--border-primary: #263241",
            "--accent-primary: #C8F169",
            "--bg-primary: #F5F7FA",
            "--bg-secondary: #FFFFFF",
            "--text-primary: #111827",
            "--text-secondary: #64748B",
            "--border-primary: #E2E8F0",
            "--accent-primary: #84CC16",
        ):
            self.assertIn(token, styles)

    def test_02_theme_provider_and_chart_theme_in_frontend(self):
        with open(os.path.join(self.root_dir, "frontend/app.js"), "r", encoding="utf-8") as f:
            js = f.read()
        self.assertIn("window.ThemeProvider", js)
        self.assertIn("window.ThemeContext", js)
        self.assertIn("window.useTheme", js)
        self.assertIn("updateLwChartTheme", js)
        self.assertIn("setThemePreference", js)

    def test_03_theme_switchers_in_user_admin_and_settings(self):
        with open(os.path.join(self.root_dir, "frontend/index.html"), "r", encoding="utf-8") as f:
            idx = f.read()
        self.assertIn('id="top_theme_btn"', idx)
        self.assertIn('id="settings_appearance_section"', idx)
        self.assertIn('id="theme_opt_dark"', idx)
        self.assertIn('id="theme_opt_light"', idx)
        self.assertIn('id="theme_opt_system"', idx)

        with open(os.path.join(self.root_dir, "admin/index.html"), "r", encoding="utf-8") as f:
            adm = f.read()
        self.assertIn('id="adm_theme_dark"', adm)
        self.assertIn('id="adm_theme_light"', adm)
        self.assertIn('id="adm_theme_system"', adm)
        self.assertIn("araabot_admin_theme_mode", adm)

    def test_04_theme_persistence_and_isolation_from_trading(self):
        token, user = self._register_and_login()
        headers = {"Authorization": f"Bearer {token}"}
        uid = user["id"]
        pos_before = len(query("SELECT id FROM positions WHERE user_id=?", (uid,)))

        # Switch to light theme
        r_light = self.client.post("/api/user/theme", json={"theme": "light"}, headers=headers)
        self.assertEqual(r_light.status_code, 200)
        self.assertEqual(r_light.get_json()["theme"], "light")

        # Verify persisted across refresh / GET
        r_get = self.client.get("/api/user/theme", headers=headers)
        self.assertEqual(r_get.get_json()["theme"], "light")

        # Verify persisted on re-login
        _, user_relogin = self._register_and_login()
        self.assertEqual(user_relogin["theme_preference"], "light")

        # Switch to system and back to dark
        r_sys = self.client.post("/api/user/theme", json={"theme": "system"}, headers=headers)
        self.assertEqual(r_sys.get_json()["theme"], "system")
        r_dark = self.client.post("/api/user/theme", json={"theme": "dark"}, headers=headers)
        self.assertEqual(r_dark.get_json()["theme"], "dark")

        # Verify theme switching never triggers trades or alters bot state
        pos_after = len(query("SELECT id FROM positions WHERE user_id=?", (uid,)))
        self.assertEqual(pos_before, pos_after)
        u_row = query_one("SELECT bot_enabled FROM users WHERE id=?", (uid,))
        self.assertEqual(int(u_row["bot_enabled"]), int(user["bot_enabled"]))


if __name__ == "__main__":
    unittest.main()
