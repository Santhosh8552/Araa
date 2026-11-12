"""
Automated unit tests for ARAA Brokerage & Wallet Legal Authorization Gates.
"""
import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

try:
    from brokerage_engine import BrokerageGatewayService
    from wallet_infrastructure import WalletInfrastructureService
    from migrations import run_migrations
except ImportError:
    from backend.brokerage_engine import BrokerageGatewayService
    from backend.wallet_infrastructure import WalletInfrastructureService
    from backend.migrations import run_migrations


class TestWalletAndBrokerageGates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run_migrations()
        BrokerageGatewayService.seed_initial_brokerage_state()
        WalletInfrastructureService.seed_initial_vaults()

    def test_01_company_prop_services_authorized(self):
        """Company Prop Desk Equity & Crypto Spot services must be active and authorized."""
        eq_auth, _ = BrokerageGatewayService.is_service_authorized("SVC_PROP_DESK_EQUITY")
        self.assertTrue(eq_auth)

        cr_auth, _ = BrokerageGatewayService.is_service_authorized("SVC_PROP_DESK_CRYPTO")
        self.assertTrue(cr_auth)

        tr_auth, _ = BrokerageGatewayService.is_service_authorized("SVC_TREASURY_WALLET")
        self.assertTrue(tr_auth)

    def test_02_retail_customer_services_strictly_gated(self):
        """Customer retail brokerage and crypto custody MUST be strictly blocked."""
        brok_auth, brok_reason = BrokerageGatewayService.is_service_authorized("SVC_CUSTOMER_BROKERAGE")
        self.assertFalse(brok_auth)
        self.assertIn("LEGAL_GATE", brok_reason)

        cust_auth, cust_reason = BrokerageGatewayService.is_service_authorized("SVC_CUSTOMER_CRYPTO_CUSTODY")
        self.assertFalse(cust_auth)
        self.assertIn("LEGAL_GATE", cust_reason)

        mtf_auth, mtf_reason = BrokerageGatewayService.is_service_authorized("SVC_CUSTOMER_MARGIN_LENDING")
        self.assertFalse(mtf_auth)

    def test_03_customer_onboarding_and_deposits_blocked(self):
        """Attempting customer retail onboarding or crypto deposits returns explicit legal lock."""
        onb_res = BrokerageGatewayService.attempt_customer_onboarding("cust_001", "ABCDE1234F")
        self.assertFalse(onb_res["success"])
        self.assertEqual(onb_res["error"], "RETAIL_BROKERAGE_LOCKED")
        self.assertEqual(onb_res["status"], "SUSPENDED_PENDING_REGULATORY_LICENSE")

        dep_res = WalletInfrastructureService.attempt_customer_wallet_deposit("cust_001", "USDT", 1000.0)
        self.assertFalse(dep_res["success"])
        self.assertEqual(dep_res["error"], "CUSTOMER_CUSTODY_LOCKED")
        self.assertEqual(dep_res["status"], "DISABLED_PENDING_VDA_CUSTODY_AUTHORIZATION")

    def test_04_company_treasury_vaults_active(self):
        """Internal corporate treasury vaults (INR, USDT, BTC) are active with multisig thresholds."""
        vaults = WalletInfrastructureService.list_treasury_vaults()
        self.assertGreaterEqual(len(vaults), 4)
        v_types = [v["vault_type"] for v in vaults]
        self.assertIn("FIAT_INR", v_types)
        self.assertIn("CRYPTO_COLD_MPC", v_types)

    def test_05_eleven_state_ledger_movement(self):
        """Treasury movements are recorded into the 11-state immutable ledger with signoff hashes."""
        res = WalletInfrastructureService.request_treasury_movement(
            vault_id="vlt_inr_ops",
            entry_type="BROKER_ALLOCATION",
            currency="INR",
            amount_paise=2500000,
            requested_by="CEO_SANTHOSH",
        )
        self.assertTrue(res["success"])
        self.assertTrue(res["entry_id"].startswith("wle_"))
        self.assertIn("signoff_hash", res)


if __name__ == "__main__":
    unittest.main()
