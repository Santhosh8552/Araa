"""
ARAA Company Trading Platform — Universal Broker Manager & Adapter Interface.

Guarantees:
- No global shared broker client (`_EXCHANGE_CLIENT` pattern eliminated).
- Every call resolves isolated company account credentials (`CompanyAccountManager`).
- Strict Pool Isolation enforcement (`POOL_INDIA_INR` <-> ZERODHA, `POOL_CRYPTO_SPOT` <-> COINDCX).
- Strict Capability & Permission validation before order routing.
- 14-method abstract `BrokerAdapter` interface for Zerodha, CoinDCX, and test mocks.
"""

import json
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from company_auth import log_company_audit
    from company_finance import CompanyAccountManager, CompanyCapitalManager, paise_to_inr_str, to_paise
    from database import query, query_one, write
except ImportError:
    from backend.company_auth import log_company_audit
    from backend.company_finance import CompanyAccountManager, CompanyCapitalManager, paise_to_inr_str, to_paise
    from backend.database import query, query_one, write


class BrokerAdapter(ABC):
    """Unified interface required for every ARAA company broker integration."""

    provider: str = "BASE"
    market_scope: str = "NONE"

    def __init__(self, account_id: str, company_id: int, credentials: Dict[str, Any]):
        self.account_id = account_id
        self.company_id = company_id
        self.credentials = credentials

    @abstractmethod
    def verify_connection(self) -> Dict[str, Any]:
        """Verifies live authentication and authorized segments/products."""

    @abstractmethod
    def get_profile(self) -> Dict[str, Any]:
        """Returns actual legal holder / user profile & API permissions from provider."""

    @abstractmethod
    def get_balances(self) -> Dict[str, Any]:
        """Returns actual available, locked, and total equity funds from provider."""

    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """Returns actual open/net positions reported by the broker."""

    @abstractmethod
    def get_open_orders(self) -> List[Dict[str, Any]]:
        """Returns currently active/open orders from the broker."""

    @abstractmethod
    def get_instruments(self, exchange: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetches supported instrument metadata from provider."""

    @abstractmethod
    def get_quote(self, symbol: str, exchange: Optional[str] = None) -> Dict[str, Any]:
        """Fetches current LTP/quote/OHLC snapshot with source timestamp."""

    @abstractmethod
    def validate_instrument(
        self,
        symbol: str,
        exchange: Optional[str] = None,
        quantity: Optional[Any] = None,
        order_type: str = "MARKET",
        product: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validates tradability, segment, lot/step size, and product eligibility."""

    @abstractmethod
    def calculate_margin(self, order_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Queries or computes required capital/margin for the proposed order."""

    @abstractmethod
    def place_order(self, order_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Submits an authorized order. Never retries blindly on timeout."""

    @abstractmethod
    def get_order_status(self, provider_order_id: str) -> Dict[str, Any]:
        """Queries current provider status and fills for a submitted order."""

    @abstractmethod
    def get_trades(self) -> List[Dict[str, Any]]:
        """Fetches executed fills/trades from the broker."""

    @abstractmethod
    def cancel_order(self, provider_order_id: str, variety: str = "regular") -> Dict[str, Any]:
        """Cancels an eligible open broker order."""

    @abstractmethod
    def disconnect(self) -> Dict[str, Any]:
        """Revokes/clears active session credentials cleanly without touching open positions."""


class UniversalBrokerManager:
    """
    Account-isolated broker orchestration registry.
    Never caches mutable global exchange sessions across accounts.
    """

    _ADAPTER_FACTORIES: Dict[str, Callable[[str, int, Dict[str, Any]], BrokerAdapter]] = {}
    # Optional test-only override keyed by (company_id, account_id) -> factory/instance
    _MOCK_OVERRIDES: Dict[Tuple[int, str], Callable[[str, int, Dict[str, Any]], BrokerAdapter]] = {}

    @classmethod
    def register_provider(cls, provider: str, factory: Callable[[str, int, Dict[str, Any]], BrokerAdapter]) -> None:
        cls._ADAPTER_FACTORIES[provider.strip().upper()] = factory

    @classmethod
    def register_mock_for_account(
        cls, company_id: int, account_id: str, factory: Callable[[str, int, Dict[str, Any]], BrokerAdapter]
    ) -> None:
        """Registers an isolated mock adapter solely for automated testing of a specific account_id."""
        cls._MOCK_OVERRIDES[(company_id, account_id)] = factory

    @classmethod
    def clear_mock_for_account(cls, company_id: int, account_id: str) -> None:
        cls._MOCK_OVERRIDES.pop((company_id, account_id), None)

    @classmethod
    def _ensure_builtin_providers(cls) -> None:
        if "ZERODHA" not in cls._ADAPTER_FACTORIES:
            try:
                from zerodha_adapter import ZerodhaKiteAdapter
            except ImportError:
                from backend.zerodha_adapter import ZerodhaKiteAdapter
            cls.register_provider("ZERODHA", lambda aid, cid, creds: ZerodhaKiteAdapter(aid, cid, creds))
        if "COINDCX" not in cls._ADAPTER_FACTORIES:
            try:
                pass
            except ImportError:
                from coindcx_spot_adapter import CoinDCXSpotAdapter
                cls.register_provider("COINDCX", lambda aid, cid, creds: CoinDCXSpotAdapter(aid, cid, creds))

    @classmethod
    def get_adapter(cls, company_id: int, account_id: str) -> BrokerAdapter:
        """Instantiates a fresh, credential-isolated BrokerAdapter for one company account."""
        cls._ensure_builtin_providers()
        creds = CompanyAccountManager.resolve_decrypted_credentials(company_id, account_id)
        if not creds:
            raise PermissionError(f"Company trading account '{account_id}' not found or unauthorized")

        provider = creds["provider"].upper()
        override = cls._MOCK_OVERRIDES.get((company_id, account_id))
        if override:
            return override(account_id, company_id, creds)

        factory = cls._ADAPTER_FACTORIES.get(provider)
        if not factory:
            raise RuntimeError(f"No broker adapter registered for provider '{provider}'")
        return factory(account_id, company_id, creds)

    @classmethod
    def sync_account_and_pool(
        cls,
        company_id: int,
        account_id: str,
        actor: Optional[Dict[str, Any]] = None,
        ip_address: str = "",
    ) -> Dict[str, Any]:
        """Synchronizes verified profile, balances, positions, and open orders into company DB & pool."""
        adapter = cls.get_adapter(company_id, account_id)
        acc = query_one(
            "SELECT * FROM company_trading_accounts WHERE company_id=? AND account_id=?",
            (company_id, account_id),
        )
        if not acc:
            return {"success": False, "error": "Account not found"}

        pool = CompanyCapitalManager.get_pool_for_market(company_id, acc["market_scope"])
        CompanyCapitalManager.assert_pool_isolation(pool["pool_id"], acc["market_scope"], acc["provider"])

        ver = adapter.verify_connection()
        if not ver.get("ok"):
            write(
                "UPDATE company_trading_accounts SET connection_status=?, api_permission_status=?, updated_at=? "
                "WHERE account_id=?",
                ("ERROR", ver.get("error", "VERIFICATION_FAILED"), time.time(), account_id),
            )
            return {"success": False, "error": ver.get("error", "Broker verification failed"), "verification": ver}

        bal = adapter.get_balances()
        if not bal.get("ok"):
            return {"success": False, "error": bal.get("error", "Failed to fetch broker balances")}

        positions = adapter.get_positions()
        open_orders = adapter.get_open_orders()
        now = time.time()

        eq_paise = int(bal.get("equity_paise", 0))
        free_paise = int(bal.get("free_paise", 0))
        locked_paise = int(bal.get("locked_paise", 0))
        broker_user_id = str(ver.get("broker_user_id") or acc.get("broker_user_id") or "")

        write(
            "UPDATE company_trading_accounts SET broker_user_id=?, connection_status='CONNECTED', "
            "api_permission_status='VERIFIED', last_synced_at=?, updated_at=? WHERE account_id=?",
            (broker_user_id, now, now, account_id),
        )
        write(
            "UPDATE company_capital_pools SET account_id=?, broker_confirmed_equity_paise=?, "
            "free_funds_paise=?, locked_funds_paise=?, open_positions_count=?, pending_orders_count=?, "
            "last_broker_sync_at=?, updated_at=? WHERE company_id=? AND pool_id=?",
            (
                account_id,
                eq_paise,
                free_paise,
                locked_paise,
                len(positions),
                len(open_orders),
                now,
                now,
                company_id,
                pool["pool_id"],
            ),
        )

        # Update authorized broker capabilities reported by provider
        if ver.get("authorized_segments") is not None:
            write(
                "UPDATE broker_capabilities SET allowed_segments_json=?, updated_at=? WHERE account_id=?",
                (json.dumps(ver["authorized_segments"]), now, account_id),
            )

        log_company_audit(
            company_id=company_id,
            action="BROKER_ACCOUNT_SYNCED",
            actor=actor,
            resource_type="COMPANY_TRADING_ACCOUNT",
            resource_id=account_id,
            after={
                "pool_id": pool["pool_id"],
                "broker_confirmed_equity_inr": paise_to_inr_str(eq_paise),
                "free_funds_inr": paise_to_inr_str(free_paise),
                "open_positions": len(positions),
                "open_orders": len(open_orders),
            },
            ip_address=ip_address,
        )

        return {
            "success": True,
            "account_id": account_id,
            "pool_id": pool["pool_id"],
            "profile": ver.get("profile", {}),
            "balances": bal,
            "positions": positions,
            "open_orders": open_orders,
        }

    @classmethod
    def route_order_for_account(
        cls,
        company_id: int,
        account_id: str,
        pool_id: str,
        order_spec: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Validates pool isolation, account approval, capabilities, and instrument before calling adapter.place_order."""
        acc = query_one(
            "SELECT * FROM company_trading_accounts WHERE company_id=? AND account_id=?",
            (company_id, account_id),
        )
        if not acc:
            return {"ok": False, "status": "REJECTED", "error": "Company account not found"}
        if acc["connection_status"] != "CONNECTED":
            return {"ok": False, "status": "REJECTED", "error": f"Account not connected ({acc['connection_status']})"}
        if acc["api_permission_status"] != "VERIFIED":
            return {"ok": False, "status": "REJECTED", "error": "Account API permissions not verified"}

        CompanyCapitalManager.assert_pool_isolation(pool_id, acc["market_scope"], acc["provider"])

        cap = query_one("SELECT * FROM broker_capabilities WHERE account_id=?", (account_id,)) or {}
        order_type = str(order_spec.get("order_type") or "MARKET").upper()
        try:
            allowed_otypes = json.loads(cap.get("allowed_order_types_json") or '["MARKET","LIMIT"]')
        except Exception:
            allowed_otypes = ["MARKET", "LIMIT"]
        if order_type not in allowed_otypes:
            return {"ok": False, "status": "REJECTED", "error": f"Order type {order_type} not permitted for {account_id}"}

        adapter = cls.get_adapter(company_id, account_id)
        val = adapter.validate_instrument(
            symbol=order_spec.get("symbol", ""),
            exchange=order_spec.get("exchange"),
            quantity=order_spec.get("quantity"),
            order_type=order_type,
            product=order_spec.get("product"),
        )
        if not val.get("valid"):
            return {"ok": False, "status": "REJECTED", "error": val.get("error", "Instrument validation failed")}

        return adapter.place_order(order_spec)

