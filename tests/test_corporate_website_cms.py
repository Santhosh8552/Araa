"""
Automated unit and integration tests for ARAA Corporate Website & Owner Super Admin CMS.
"""
import unittest
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

try:
    from app import api
    from corporate_cms import CorporateCmsService
    from database import query_one
except ImportError:
    from backend.app import api
    from backend.corporate_cms import CorporateCmsService
    from backend.database import query_one


class TestCorporateWebsiteCms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        CorporateCmsService.seed_initial_cms_content()

    def setUp(self):
        self.client = api.test_client()

    def test_01_public_corporate_route_status_200(self):
        """Verify GET /corporate serves 200 OK HTML."""
        res = self.client.get("/corporate")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"ARAA PRIVATE LIMITED", res.data)
        self.assertIn(b"QUANTITATIVE COMPUTATIONAL ARCHITECTURE", res.data)

    def test_02_cms_theme_endpoint(self):
        """Verify GET /api/v1/corporate/theme returns the dark green & neon lime palette."""
        res = self.client.get("/api/v1/corporate/theme")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        theme = data.get("theme", {})
        self.assertEqual(theme.get("primary_color"), "#00FF88")
        self.assertEqual(theme.get("secondary_color"), "#004D25")
        self.assertEqual(theme.get("background_dark"), "#050B08")

    def test_03_seventeen_public_corporate_pages_seeded(self):
        """Verify all 17 public corporate pages exist and are published."""
        pages = CorporateCmsService.list_all_pages()
        self.assertEqual(len(pages), 17)
        slugs = [p["slug"] for p in pages]
        self.assertIn("home", slugs)
        self.assertIn("about", slugs)
        self.assertIn("technology", slugs)
        self.assertIn("quantitative-research", slugs)
        self.assertIn("prop-desk", slugs)
        self.assertIn("brokerage-infrastructure", slugs)
        self.assertIn("wallet-custody", slugs)
        self.assertIn("leadership", slugs)
        self.assertIn("corporate-governance", slugs)
        self.assertIn("security-compliance", slugs)
        self.assertIn("careers", slugs)
        self.assertIn("news-insights", slugs)
        self.assertIn("contact", slugs)

    def test_04_public_page_detail_and_sections(self):
        """Verify GET /api/v1/corporate/pages/technology returns sections."""
        res = self.client.get("/api/v1/corporate/pages/technology")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        page = data.get("page", {})
        self.assertEqual(page.get("slug"), "technology")
        self.assertGreaterEqual(len(page.get("sections", [])), 1)

    def test_05_contact_enquiry_submission(self):
        """Verify POST /api/v1/corporate/enquiries records new corporate inquiry."""
        payload = {
            "full_name": "Dr. Alexander Wright",
            "email": "awright@quant-capital.com",
            "subject": "Institutional Technology Partnership",
            "message": "Interested in evaluating ARAA low-latency OMS and deterministic execution pipeline.",
            "category": "INSTITUTIONAL"
        }
        res = self.client.post("/api/v1/corporate/enquiries", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        eid = data.get("enquiry_id")
        self.assertTrue(eid.startswith("enq_"))

        # Confirm in database
        enq = query_one("SELECT * FROM cms_contact_enquiries WHERE enquiry_id=?", (eid,))
        self.assertIsNotNone(enq)
        self.assertEqual(enq["full_name"], "Dr. Alexander Wright")
        self.assertEqual(enq["email"], "awright@quant-capital.com")


if __name__ == "__main__":
    unittest.main()
