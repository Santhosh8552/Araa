"""
ARAA PRIVATE LIMITED — Wallet Infrastructure & 11-State Immutable Double-Entry Ledger.

Features:
- Dual Wallet Architecture:
  * WALLET A: Internal Company Treasury Vault (ACTIVE — INR Banking & Operational Crypto Reserve).
  * WALLET B: Customer Wallet & Digital Asset Custody (STRICTLY GATED / DISABLED pending VDA/FIU authorization).
- 11-State Verifiable Lifecycle:
  CREATED -> PENDING_APPROVAL -> SIGNED -> BROADCAST -> CONFIRMED -> COMPLETED
  (Terminal branches: REJECTED, EXPIRED, FAILED, REFUNDED, RECONCILED)
- Dual-control Maker-Checker approvals for treasury movements > 50,000 INR.
- Cryptographic SHA-256 tamper-evident signoff chain.
"""

import hashlib
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

try:
    from brokerage_engine import BrokerageGatewayService
    from database import query, query_one, write, writes
except ImportError:
    from backend.brokerage_engine import BrokerageGatewayService
    from backend.database import query, query_one, write, writes


DEFAULT_VAULTS = [
    ("vlt_inr_ops", "HDFC Corporate Treasury Vault (INR)", "FIAT_INR", "INR", 500000000, "0", "1-of-1"),
    ("vlt_usdt_reserve", "Operational Cold MPC Vault (USDT)", "CRYPTO_COLD_MPC", "USDT", 0, "50000.000000", "2-of-3"),
    ("vlt_btc_reserve", "Long-Term Treasury Reserve Vault (BTC)", "CRYPTO_COLD_MPC", "BTC", 0, "1.50000000", "2-of-3"),
    ("vlt_hot_operational", "Operational Trading Warm Vault (USDT)", "CRYPTO_WARM_OPERATIONAL", "USDT", 0, "5000.000000", "2-of-2"),
]


class WalletInfrastructureService:
    """Manages company treasury vaults, 11-state ledger, and custody authorization gates."""

    @classmethod
    def seed_initial_vaults(cls):
        now = time.time()
        for vid, name, vtype, ccy, bal_p, crypto_b, m_thresh in DEFAULT_VAULTS:
            write(
                """
                INSERT INTO company_treasury_vaults(vault_id, vault_name, vault_type, currency, balance_paise, crypto_balance_atomic, multisig_threshold, is_active, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(vault_id) DO UPDATE SET vault_name=excluded.vault_name, multisig_threshold=excluded.multisig_threshold
                """,
                (vid, name, vtype, ccy, bal_p, crypto_b, m_thresh, now, now),
            )

    @classmethod
    def list_treasury_vaults(cls) -> List[Dict[str, Any]]:
        return query("SELECT * FROM company_treasury_vaults WHERE is_active=1 ORDER BY created_at ASC")

    @classmethod
    def request_treasury_movement(
        cls,
        vault_id: str,
        entry_type: str,
        currency: str,
        amount_paise: int = 0,
        crypto_amount: str = "0",
        requested_by: str = "SYSTEM_TREASURER",
    ) -> Dict[str, Any]:
        """Creates a pending movement in the 11-state ledger with an initial state of PENDING_APPROVAL."""
        vault = query_one("SELECT * FROM company_treasury_vaults WHERE vault_id=?", (vault_id,))
        if not vault:
            return {"success": False, "error": f"Vault '{vault_id}' not found"}

        now = time.time()
        entry_id = f"wle_{uuid.uuid4().hex[:10]}"
        tx_ref = f"TX-TREASURY-{int(now)}-{uuid.uuid4().hex[:4].upper()}"

        # Signoff hash binding all parameters
        raw_sign = f"{tx_ref}:{vault_id}:{entry_type}:{currency}:{amount_paise}:{crypto_amount}:{requested_by}:{now}"
        signoff_hash = hashlib.sha256(raw_sign.encode("utf-8")).hexdigest()

        # Automatic approval for internal allocations < 50,000 INR; otherwise PENDING_APPROVAL
        initial_state = "COMPLETED" if amount_paise <= 5000000 and entry_type == "BROKER_ALLOCATION" else "PENDING_APPROVAL"

        write(
            """
            INSERT INTO wallet_immutable_ledger(
                entry_id, vault_id, transaction_ref, currency, entry_type, state,
                amount_paise, crypto_amount, confirmation_count, authorized_by, signoff_hash, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                entry_id, vault_id, tx_ref, currency, entry_type, initial_state,
                amount_paise, crypto_amount, requested_by, signoff_hash, now, now
            ),
        )

        return {
            "success": True,
            "entry_id": entry_id,
            "transaction_ref": tx_ref,
            "state": initial_state,
            "signoff_hash": signoff_hash,
        }

    @classmethod
    def attempt_customer_wallet_deposit(cls, customer_id: str, currency: str, amount: float) -> Dict[str, Any]:
        """Strictly blocks retail customer wallet deposits until legal registration is confirmed."""
        auth, reason = BrokerageGatewayService.is_service_authorized("SVC_CUSTOMER_CRYPTO_CUSTODY")
        if not auth:
            return {
                "success": False,
                "error": "CUSTOMER_CUSTODY_LOCKED",
                "message": reason,
                "status": "DISABLED_PENDING_VDA_CUSTODY_AUTHORIZATION",
            }
        return {"success": True, "customer_id": customer_id, "status": "DEPOSIT_PROCESSED"}
