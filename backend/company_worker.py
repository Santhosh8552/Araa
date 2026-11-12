"""
ARAA Company Trading Platform — Automated Background Worker & Alert Dispatcher (Phase 11).

Responsibilities:
- Periodic reconciliation of all CONNECTED Zerodha & CoinDCX Spot company accounts.
- Token expiry monitoring (Zerodha daily ~06:00 IST session renewal reminders).
- Scheduled scanning of ACTIVE company strategies via all 8 AraaBot AI engines (Paper-safe unless explicitly gated).
- Operational alert dispatch to `system_incidents` + optional Slack / Telegram channels.
"""

import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

try:
    from company_auth import log_company_audit
    from company_finance import CompanyAccountManager
    from company_ledger_recon import CompanyReconciliationService
    from company_strategy_engine import CompanyStrategyService
    from database import query, write
except ImportError:
    from backend.company_auth import log_company_audit
    from backend.company_finance import CompanyAccountManager
    from backend.company_ledger_recon import CompanyReconciliationService
    from backend.company_strategy_engine import CompanyStrategyService
    from backend.database import query, write

logger = logging.getLogger("company_worker")


def dispatch_operational_alert(
    title: str,
    message: str,
    severity: str = "WARNING",
    service_name: str = "COMPANY_WORKER",
) -> Dict[str, Any]:
    """Records an operational incident and fans out best-effort Slack/Telegram alerts."""
    inc_id = f"inc_{uuid.uuid4().hex[:14].upper()}"
    now = time.time()
    try:
        write(
            "INSERT INTO system_incidents(incident_id, service_name, severity, title, description, status, detected_at) "
            "VALUES(?,?,?,?,?,'OPEN',?)",
            (inc_id, service_name, severity.upper(), title, message, now),
        )
    except Exception as exc:
        logger.warning(f"Incident persist failed: {exc}")

    channels: List[str] = []
    try:
        try:
            from slack_service import send_slack_message
        except ImportError:
            from backend.slack_service import send_slack_message
        if send_slack_message(f"[{severity.upper()}] {title}: {message}", title=title):
            channels.append("slack")
    except Exception:
        pass

    try:
        try:
            from telegram_notifier import send_telegram_message
        except ImportError:
            from backend.telegram_notifier import send_telegram_message
        if send_telegram_message(f"[{severity.upper()}] <b>{title}</b>\n{message}"):
            channels.append("telegram")
    except Exception:
        pass

    return {"incident_id": inc_id, "severity": severity.upper(), "channels": channels}


class CompanyBackgroundWorker:
    """Periodic supervisor for company reconciliation, token hygiene, and AI strategy scans."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.running = False
        self.interval_sec = int(os.environ.get("COMPANY_WORKER_INTERVAL_SEC", "300") or 300)
        self.cycles_completed = 0
        self.last_run_at: Optional[float] = None
        self.last_summary: Dict[str, Any] = {}
        self.last_error: str = ""

    def run_once(
        self,
        company_id: int = 1,
        auto_route_paper: bool = False,
        actor: Optional[Dict[str, Any]] = None,
        ip_address: str = "worker",
    ) -> Dict[str, Any]:
        """Executes a single reconciliation + token-expiry + active-strategy AI scan cycle."""
        now = time.time()
        reconciled: List[Dict[str, Any]] = []
        token_warnings: List[Dict[str, Any]] = []
        scanned_strategies: List[Dict[str, Any]] = []

        accounts = [a for a in CompanyAccountManager.list_accounts(company_id) if a]
        for acc in accounts:
            if acc.get("provider") == "ZERODHA" and acc.get("token_expires_at"):
                remaining = float(acc["token_expires_at"]) - now
                if remaining < 3600:
                    w = {"account_id": acc["account_id"], "remaining_sec": int(remaining)}
                    token_warnings.append(w)
                    dispatch_operational_alert(
                        title="Zerodha Token Expiring Soon",
                        message=f"Account {acc['account_id']} token expires in {int(remaining)}s. Renew daily OAuth session.",
                        severity="HIGH" if remaining <= 0 else "WARNING",
                    )

            if acc.get("connection_status") == "CONNECTED":
                rcn = CompanyReconciliationService.run_reconciliation(
                    company_id=company_id,
                    account_id=acc["account_id"],
                    trigger_source="WORKER",
                    actor=actor,
                    ip_address=ip_address,
                )
                reconciled.append({
                    "account_id": acc["account_id"],
                    "pool_id": rcn.get("pool_id"),
                    "status": rcn.get("status"),
                    "discrepancies_count": rcn.get("discrepancies_count", 0),
                })
                if rcn.get("status") == "MISMATCH":
                    dispatch_operational_alert(
                        title="Reconciliation Mismatch Halted Pool",
                        message=f"{rcn.get('pool_id')} halted by automated worker ({rcn.get('discrepancies_count')} diffs).",
                        severity="CRITICAL",
                    )

        active_strats = query(
            "SELECT strategy_id, strategy_code FROM company_strategies WHERE company_id=? AND status='ACTIVE'",
            (company_id,),
        )
        for s in active_strats:
            sc = CompanyStrategyService.scan_strategy_watchlist(
                company_id=company_id,
                strategy_id=s["strategy_id"],
                use_llm=False,
                auto_route_paper=auto_route_paper,
                actor=actor,
                ip_address=ip_address,
            )
            scanned_strategies.append({
                "strategy_id": s["strategy_id"],
                "strategy_code": s["strategy_code"],
                "scanned_count": sc.get("scanned_count", 0),
            })

        summary = {
            "company_id": company_id,
            "completed_at": time.time(),
            "reconciled_accounts": reconciled,
            "token_warnings": token_warnings,
            "scanned_strategies": scanned_strategies,
        }
        with self._lock:
            self.cycles_completed += 1
            self.last_run_at = summary["completed_at"]
            self.last_summary = summary
            self.last_error = ""

        log_company_audit(
            company_id=company_id,
            action="COMPANY_WORKER_CYCLE",
            actor=actor,
            resource_type="COMPANY_WORKER",
            resource_id=f"cycle_{self.cycles_completed}",
            after={
                "reconciled": len(reconciled),
                "token_warnings": len(token_warnings),
                "scanned_strategies": len(scanned_strategies),
            },
            ip_address=ip_address,
        )
        return {"success": True, **summary}

    def _loop(self) -> None:
        while not self._stop_event.wait(self.interval_sec):
            try:
                self.run_once(company_id=1, auto_route_paper=False)
            except Exception as exc:
                with self._lock:
                    self.last_error = str(exc)
                logger.warning(f"Company worker cycle failed: {exc}")

    def start(self, interval_sec: Optional[int] = None) -> None:
        if interval_sec:
            self.interval_sec = max(30, int(interval_sec))
        with self._lock:
            if self.running:
                return
            self._stop_event.clear()
            self.running = True
            self._thread = threading.Thread(target=self._loop, daemon=True, name="araa-company-worker")
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            self.running = False

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running": self.running,
                "interval_sec": self.interval_sec,
                "cycles_completed": self.cycles_completed,
                "last_run_at": self.last_run_at,
                "last_summary": self.last_summary,
                "last_error": self.last_error,
            }


company_worker = CompanyBackgroundWorker()

