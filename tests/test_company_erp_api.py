"""
Unit and integration tests for ARAA Corporate ERP & Governance API endpoints.
"""
import unittest
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

try:
    from app import api
    from company_erp import CorporateGovernanceService, CompanyTreasuryService, HumanResourcesService
    from database import query_one
except ImportError:
    from backend.app import api
    from backend.company_erp import CorporateGovernanceService, CompanyTreasuryService, HumanResourcesService
    from backend.database import query_one


class TestCompanyErpApi(unittest.TestCase):
    def setUp(self):
        self.client = api.test_client()

    def test_01_erp_overview_endpoint(self):
        """Verify GET /api/v1/company/erp/overview returns 200 and populated metrics."""
        res = self.client.get("/api/v1/company/erp/overview")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        summary = data.get("summary", {})
        self.assertGreaterEqual(summary.get("total_directors", 0), 1)
        self.assertGreaterEqual(summary.get("total_bank_accounts", 0), 1)
        self.assertGreaterEqual(summary.get("total_departments", 0), 1)

    def test_02_erp_directors_endpoint(self):
        """Verify GET /api/v1/company/erp/directors returns list of company directors."""
        res = self.client.get("/api/v1/company/erp/directors")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        directors = data.get("directors", [])
        self.assertTrue(any(d.get("din") == "09876543" for d in directors))

    def test_03_erp_bank_accounts_endpoint(self):
        """Verify GET /api/v1/company/erp/bank-accounts returns company treasury accounts."""
        res = self.client.get("/api/v1/company/erp/bank-accounts")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        banks = data.get("bank_accounts", [])
        self.assertTrue(any(b.get("bank_name") == "HDFC Bank Ltd" for b in banks))

    def test_04_erp_departments_endpoint(self):
        """Verify GET /api/v1/company/erp/departments returns operational departments."""
        res = self.client.get("/api/v1/company/erp/departments")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        depts = data.get("departments", [])
        dept_codes = [d.get("dept_code") for d in depts]
        self.assertIn("TRD", dept_codes)
        self.assertIn("QRA", dept_codes)


if __name__ == "__main__":
    unittest.main()
