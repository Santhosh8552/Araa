"""
ARAA PRIVATE LIMITED — Dual-Mode Brokerage Architecture & Regulatory Gateway Service.

Modes:
- MODE A: Company Proprietary Trading (ACTIVE — Strictly Company Capital).
- MODE B: Customer Retail Brokerage (STRICTLY GATED / DISABLED until SEBI & legal authorization).
"""

import hashlib
import json
import time
import uuid
from typing import Any, Dict, List, Optional

try:
    from database import query, query_one, write, writes
except ImportError:
    from backend.database import query, query_one, write, writes


DEFAULT_SERVICES = [
    ("SVC_PROP_DESK_EQUITY", "ARAA Prop Trading Desk (NSE/BSE Equities)", "PROP_DESK", 1, "COMPANY_OWN_CAPITAL", "Active company proprietary trading desk"),
    ("SVC_PROP_DESK_CRYPTO", "ARAA Prop Trading Desk (Spot Crypto 1x)", "PROP_DESK", 1, "COMPANY_OWN_CAPITAL", "Active company proprietary crypto spot desk"),
    ("SVC_TREASURY_WALLET", "Internal Corporate Treasury Wallet", "WALLET", 1, "COMPANY_INTERNAL", "Internal operating capital and payroll management"),
    ("SVC_CUSTOMER_BROKERAGE", "Retail Customer Stock Brokerage", "BROKERAGE", 0, "PENDING_SEBI_STOCK_BROKER_REGISTRATION", "Third-party customer brokerage trading is legally prohibited without SEBI license"),
    ("SVC_CUSTOMER_CRYPTO_CUSTODY", "Retail Customer Crypto Wallet Custody", "WALLET", 0, "PENDING_VDA_CUSTODY_FIU_REGISTRATION", "Customer third-party digital asset deposits/withdrawals strictly locked"),
    ("SVC_CUSTOMER_MARGIN_LENDING", "Customer Margin Trading Facility (MTF)", "BROKERAGE", 0, "PENDING_NBFC_MARGIN_LICENSE", "Margin lending to external customers is strictly disabled"),
]

DEFAULT_PRODUCTS = [
    ("NSE_CASH_CNC", "NSE Cash Delivery (CNC)", "NSE", "EQUITY_CASH", "PROP_ONLY", 1, 1.0, 10.0, 0.1),
    ("BSE_CASH_CNC", "BSE Cash Delivery (CNC)", "BSE", "EQUITY_CASH", "PROP_ONLY", 1, 1.0, 10.0, 0.1),
    ("CDX_SPOT_INR", "CoinDCX Spot Crypto Pairs (INR)", "COINDCX", "CRYPTO_SPOT", "PROP_ONLY", 1, 1.0, 0.0, 0.0),
    ("CDX_SPOT_USDT", "CoinDCX Spot Crypto Pairs (USDT)", "COINDCX", "CRYPTO_SPOT", "PROP_ONLY", 1, 1.0, 0.0, 0.0),
    ("NSE_RETAIL_EQUITY", "Retail Customer Equities", "NSE", "EQUITY_CASH", "CUSTOMER_RETAIL", 0, 1.0, 10.0, 0.1),
]


class BrokerageGatewayService:
    """Controls product catalogue, mode isolation, and legal feature gates."""

    @classmethod
    def seed_initial_brokerage_state(cls):
        now = time.time()
        for code, name, div, auth, lic, reason in DEFAULT_SERVICES:
            write(
                """
                INSERT INTO service_authorization_register(service_code, service_name, division, is_authorized, regulatory_license_ref, reason_for_gate, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(service_code) DO UPDATE SET service_name=excluded.service_name, is_authorized=excluded.is_authorized
                """,
                (code, name, div, auth, lic, reason, now),
            )

        for p_code, name, exch, a_class, b_mode, enabled, mult, stt, sebi in DEFAULT_PRODUCTS:
            write(
                """
                INSERT INTO brokerage_products(product_code, name, exchange, asset_class, brokerage_mode, is_trading_enabled, margin_multiplier, stt_tax_bps, sebi_turnover_bps, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_code) DO UPDATE SET is_trading_enabled=excluded.is_trading_enabled
                """,
                (p_code, name, exch, a_class, b_mode, enabled, mult, stt, sebi, now),
            )

    @classmethod
    def is_service_authorized(cls, service_code: str) -> Tuple[bool, str]:
        row = query_one("SELECT is_authorized, reason_for_gate FROM service_authorization_register WHERE service_code=?", (service_code,))
        if not row:
            return False, f"Service '{service_code}' not found in registry"
        if not bool(row["is_authorized"]):
            return False, f"LEGAL_GATE: {row['reason_for_gate']}"
        return True, "AUTHORIZED"

    @classmethod
    def list_service_authorizations(cls) -> List[Dict[str, Any]]:
        return query("SELECT * FROM service_authorization_register ORDER BY division ASC, service_code ASC")

    @classmethod
    def list_products(cls, mode: Optional[str] = None) -> List[Dict[str, Any]]:
        if mode:
            return query("SELECT * FROM brokerage_products WHERE brokerage_mode=? ORDER BY product_code ASC", (mode,))
        return query("SELECT * FROM brokerage_products ORDER BY product_code ASC")

    @classmethod
    def attempt_customer_onboarding(cls, customer_id: str, pan: str) -> Dict[str, Any]:
        """Strictly blocks customer onboarding until retail brokerage service is legally authorized."""
        auth, reason = cls.is_service_authorized("SVC_CUSTOMER_BROKERAGE")
        if not auth:
            return {
                "success": False,
                "error": "RETAIL_BROKERAGE_LOCKED",
                "message": reason,
                "status": "SUSPENDED_PENDING_REGULATORY_LICENSE",
            }
        return {"success": True, "customer_id": customer_id, "status": "ONBOARDING_AUTHORIZED"}
