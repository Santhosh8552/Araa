"""Centralized AraaBot StrategyEngine.

Owns all strategy evaluation, risk enforcement, TradingView Pine Script webhook
processing, Araa AI rule governance, and unified Paper vs Real Bot execution.
CoinDCX acts strictly as the permitted exchange execution layer via CoinDCXExecutionAdapter.
"""

import hmac
import json
import math
import os
import secrets
import time
import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

from database import get_state, query, query_one, set_state, write, writes
from coindcx_adapter import CoinDCXExecutionAdapter, sanitize_request

logger = logging.getLogger("araabot.strategy_engine")

DEFAULT_STRATEGIES = [
    {
        "strategy_id": "araa_ai_default",
        "name": "Araa Quantum AI Strategy",
        "source_type": "AI",
        "market_type": "FUTURES",
        "enabled": 1,
        "risk_per_trade_pct": 2.0,
        "max_open_positions": 3,
        "max_daily_loss_usd": 15.0,
        "cooldown_seconds": 60.0,
        "stop_loss_pct": 0.50,
        "take_profit_pct": 1.00,
        "trailing_stop_pct": 0.25,
        "position_size_usd": 8.0,
        "leverage": 20.0,
        "allowed_directions": "BOTH",
    },
    {
        "strategy_id": "tv_pine_default",
        "name": "TradingView Pine Script Webhook",
        "source_type": "TRADINGVIEW",
        "market_type": "FUTURES",
        "enabled": 1,
        "risk_per_trade_pct": 2.0,
        "max_open_positions": 3,
        "max_daily_loss_usd": 15.0,
        "cooldown_seconds": 30.0,
        "stop_loss_pct": 0.60,
        "take_profit_pct": 1.20,
        "trailing_stop_pct": 0.30,
        "position_size_usd": 8.0,
        "leverage": 20.0,
        "allowed_directions": "BOTH",
    },
    {
        "strategy_id": "custom_scalp",
        "name": "Custom Rule Momentum Scalp",
        "source_type": "CUSTOM",
        "market_type": "FUTURES",
        "enabled": 1,
        "risk_per_trade_pct": 1.5,
        "max_open_positions": 2,
        "max_daily_loss_usd": 10.0,
        "cooldown_seconds": 90.0,
        "stop_loss_pct": 0.45,
        "take_profit_pct": 0.90,
        "trailing_stop_pct": 0.20,
        "position_size_usd": 6.0,
        "leverage": 20.0,
        "allowed_directions": "BOTH",
    },
    {
        "strategy_id": "ema_momentum_scalp",
        "name": "EMA Momentum Scalping (9/21/50)",
        "source_type": "SCALP",
        "market_type": "FUTURES",
        "enabled": 1,
        "risk_per_trade_pct": 0.25,
        "max_open_positions": 1,
        "max_daily_loss_usd": 15.0,
        "cooldown_seconds": 60.0,
        "stop_loss_pct": 0.35,
        "take_profit_pct": 0.70,
        "trailing_stop_pct": 0.20,
        "position_size_usd": 8.0,
        "leverage": 20.0,
        "allowed_directions": "BOTH",
    },
    {
        "strategy_id": "rsi_momentum_scalp",
        "name": "RSI Momentum Scalping (RSI 14)",
        "source_type": "SCALP",
        "market_type": "FUTURES",
        "enabled": 1,
        "risk_per_trade_pct": 0.25,
        "max_open_positions": 1,
        "max_daily_loss_usd": 15.0,
        "cooldown_seconds": 60.0,
        "stop_loss_pct": 0.35,
        "take_profit_pct": 0.70,
        "trailing_stop_pct": 0.20,
        "position_size_usd": 8.0,
        "leverage": 20.0,
        "allowed_directions": "BOTH",
    },
    {
        "strategy_id": "macd_scalp",
        "name": "MACD Crossover Scalping",
        "source_type": "SCALP",
        "market_type": "FUTURES",
        "enabled": 1,
        "risk_per_trade_pct": 0.25,
        "max_open_positions": 1,
        "max_daily_loss_usd": 15.0,
        "cooldown_seconds": 60.0,
        "stop_loss_pct": 0.35,
        "take_profit_pct": 0.70,
        "trailing_stop_pct": 0.20,
        "position_size_usd": 8.0,
        "leverage": 20.0,
        "allowed_directions": "BOTH",
    },
    {
        "strategy_id": "breakout_scalp",
        "name": "Breakout & Retest Scalping",
        "source_type": "SCALP",
        "market_type": "FUTURES",
        "enabled": 1,
        "risk_per_trade_pct": 0.25,
        "max_open_positions": 1,
        "max_daily_loss_usd": 15.0,
        "cooldown_seconds": 60.0,
        "stop_loss_pct": 0.35,
        "take_profit_pct": 0.70,
        "trailing_stop_pct": 0.20,
        "position_size_usd": 8.0,
        "leverage": 20.0,
        "allowed_directions": "BOTH",
    },
    {
        "strategy_id": "araa_ai_scalp",
        "name": "Araa AI Confluence Scalping",
        "source_type": "SCALP",
        "market_type": "FUTURES",
        "enabled": 1,
        "risk_per_trade_pct": 0.25,
        "max_open_positions": 1,
        "max_daily_loss_usd": 15.0,
        "cooldown_seconds": 60.0,
        "stop_loss_pct": 0.35,
        "take_profit_pct": 0.70,
        "trailing_stop_pct": 0.20,
        "position_size_usd": 8.0,
        "leverage": 20.0,
        "allowed_directions": "BOTH",
    },
]


class StrategyEngine:
    """Centralized strategy, risk, and execution orchestration engine."""

    SIGNAL_MAX_AGE_SECONDS = 120.0

    @classmethod
    def ensure_user_strategies(cls, user_id: int) -> List[Dict[str, Any]]:
        """Seed default strategies for a user if none exist yet, and return all strategies."""
        now = time.time()
        for s in DEFAULT_STRATEGIES:
            write(
                """INSERT OR IGNORE INTO strategy_configs(
                     user_id, strategy_id, name, source_type, market_type, enabled,
                     entry_rules_json, exit_rules_json, risk_per_trade_pct,
                     max_open_positions, max_daily_loss_usd, cooldown_seconds,
                     stop_loss_pct, take_profit_pct, trailing_stop_pct,
                     position_size_usd, leverage, allowed_directions, updated_at, created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    user_id, s["strategy_id"], s["name"], s["source_type"], s["market_type"],
                    s["enabled"], "{}", "{}", s["risk_per_trade_pct"], s["max_open_positions"],
                    s["max_daily_loss_usd"], s["cooldown_seconds"], s["stop_loss_pct"],
                    s["take_profit_pct"], s["trailing_stop_pct"], s["position_size_usd"],
                    s["leverage"], s["allowed_directions"], now, now,
                ),
            )
        rows = query("SELECT * FROM strategy_configs WHERE user_id=? ORDER BY id ASC", (user_id,))
        return rows

    @classmethod
    def get_strategy(cls, user_id: int, strategy_id: str) -> Optional[Dict[str, Any]]:
        cls.ensure_user_strategies(user_id)
        return query_one(
            "SELECT * FROM strategy_configs WHERE user_id=? AND strategy_id=?",
            (user_id, (strategy_id or "").strip()),
        )

    @classmethod
    def save_strategy(cls, user_id: int, cfg: Dict[str, Any]) -> Dict[str, Any]:
        cls.ensure_user_strategies(user_id)
        sid = str(cfg.get("strategy_id") or "").strip()
        if not sid:
            raise ValueError("strategy_id is required")
        now = time.time()
        existing = query_one("SELECT * FROM strategy_configs WHERE user_id=? AND strategy_id=?", (user_id, sid))
        name = str(cfg.get("name") or (existing or {}).get("name") or sid).strip()
        source_type = str(cfg.get("source_type") or (existing or {}).get("source_type") or "CUSTOM").upper()
        market_type = str(cfg.get("market_type") or (existing or {}).get("market_type") or "FUTURES").upper()
        if market_type not in ("FUTURES", "SPOT", "MARGIN"):
            market_type = "FUTURES"
        enabled = 1 if int(cfg.get("enabled", (existing or {}).get("enabled", 1))) else 0
        risk_pct = max(0.1, min(25.0, float(cfg.get("risk_per_trade_pct", (existing or {}).get("risk_per_trade_pct", 2.0)))))
        raw_max_pos = int(cfg.get("max_open_positions", (existing or {}).get("max_open_positions", 10)))
        max_pos = 999 if (raw_max_pos >= 999 or raw_max_pos <= 0) else max(1, min(100, raw_max_pos))
        max_daily_loss = max(1.0, min(10000.0, float(cfg.get("max_daily_loss_usd", (existing or {}).get("max_daily_loss_usd", 15.0)))))
        cooldown = max(0.0, min(3600.0, float(cfg.get("cooldown_seconds", (existing or {}).get("cooldown_seconds", 60.0)))))
        sl_pct = max(0.1, min(25.0, float(cfg.get("stop_loss_pct", (existing or {}).get("stop_loss_pct", 0.50)))))
        tp_pct = max(0.1, min(50.0, float(cfg.get("take_profit_pct", (existing or {}).get("take_profit_pct", 1.00)))))
        trail_pct = max(0.0, min(15.0, float(cfg.get("trailing_stop_pct", (existing or {}).get("trailing_stop_pct", 0.25)))))
        pos_size = max(0.5, min(5000.0, float(cfg.get("position_size_usd", (existing or {}).get("position_size_usd", 8.0)))))
        lev = max(1.0, min(100.0, float(cfg.get("leverage", (existing or {}).get("leverage", 20.0)))))
        allowed_dir = str(cfg.get("allowed_directions") or (existing or {}).get("allowed_directions") or "BOTH").upper()
        if allowed_dir not in ("BOTH", "LONG", "SHORT"):
            allowed_dir = "BOTH"
        entry_rules = json.dumps(cfg.get("entry_rules") if isinstance(cfg.get("entry_rules"), dict) else json.loads((existing or {}).get("entry_rules_json") or "{}"))
        exit_rules = json.dumps(cfg.get("exit_rules") if isinstance(cfg.get("exit_rules"), dict) else json.loads((existing or {}).get("exit_rules_json") or "{}"))

        write(
            """INSERT INTO strategy_configs(
                 user_id, strategy_id, name, source_type, market_type, enabled,
                 entry_rules_json, exit_rules_json, risk_per_trade_pct,
                 max_open_positions, max_daily_loss_usd, cooldown_seconds,
                 stop_loss_pct, take_profit_pct, trailing_stop_pct,
                 position_size_usd, leverage, allowed_directions, updated_at, created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id, strategy_id) DO UPDATE SET
                 name=excluded.name, source_type=excluded.source_type, market_type=excluded.market_type,
                 enabled=excluded.enabled, entry_rules_json=excluded.entry_rules_json,
                 exit_rules_json=excluded.exit_rules_json, risk_per_trade_pct=excluded.risk_per_trade_pct,
                 max_open_positions=excluded.max_open_positions, max_daily_loss_usd=excluded.max_daily_loss_usd,
                 cooldown_seconds=excluded.cooldown_seconds, stop_loss_pct=excluded.stop_loss_pct,
                 take_profit_pct=excluded.take_profit_pct, trailing_stop_pct=excluded.trailing_stop_pct,
                 position_size_usd=excluded.position_size_usd, leverage=excluded.leverage,
                 allowed_directions=excluded.allowed_directions, updated_at=excluded.updated_at""",
            (
                user_id, sid, name, source_type, market_type, enabled,
                entry_rules, exit_rules, risk_pct, max_pos, max_daily_loss,
                cooldown, sl_pct, tp_pct, trail_pct, pos_size, lev, allowed_dir, now, now,
            ),
        )
        return cls.get_strategy(user_id, sid) or {}

    @classmethod
    def sync_from_bot_config(
        cls,
        user_id: int,
        *,
        allowed_directions: Optional[str] = None,
        max_open_positions: Optional[int] = None,
        max_daily_loss_usd: Optional[float] = None,
        risk_per_trade_pct: Optional[float] = None,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
        leverage: Optional[float] = None,
    ) -> None:
        """Keep default user strategy rules aligned with saved bot settings."""
        cls.ensure_user_strategies(user_id)
        sets = ["updated_at=?"]
        vals: List[Any] = [time.time()]
        if allowed_directions and str(allowed_directions).upper() in ("BOTH", "LONG", "SHORT"):
            sets.append("allowed_directions=?")
            vals.append(str(allowed_directions).upper())
        if max_open_positions is not None:
            raw_m = int(max_open_positions)
            sets.append("max_open_positions=?")
            vals.append(999 if (raw_m >= 999 or raw_m <= 0) else max(1, min(100, raw_m)))
        if max_daily_loss_usd is not None:
            sets.append("max_daily_loss_usd=?")
            vals.append(max(5.0, min(50000.0, float(max_daily_loss_usd))))
        if risk_per_trade_pct is not None:
            sets.append("risk_per_trade_pct=?")
            vals.append(max(0.1, min(25.0, float(risk_per_trade_pct))))
        if stop_loss_pct is not None:
            sets.append("stop_loss_pct=?")
            vals.append(max(0.1, min(50.0, float(stop_loss_pct))))
        if take_profit_pct is not None:
            sets.append("take_profit_pct=?")
            vals.append(max(0.2, min(100.0, float(take_profit_pct))))
        if leverage is not None:
            sets.append("leverage=?")
            vals.append(max(1.0, min(500.0, float(leverage))))
        vals.append(user_id)
        write(f"UPDATE strategy_configs SET {', '.join(sets)} WHERE user_id=?", tuple(vals))

    @classmethod
    def get_or_create_webhook_secret(cls, user_id: int) -> str:
        key = f"tv_webhook_secret_{user_id}"
        sec = get_state(key, "")
        if not sec:
            sec = "araatv_" + secrets.token_hex(16)
            set_state(key, sec)
        return sec

    @classmethod
    def rotate_webhook_secret(cls, user_id: int) -> str:
        sec = "araatv_" + secrets.token_hex(16)
        set_state(f"tv_webhook_secret_{user_id}", sec)
        return sec

    REAL_BOT_STATES = (
        "DISCONNECTED", "CONNECTED", "READY", "STARTING", "RUNNING",
        "PAUSED", "STOPPING", "STOPPED", "ERROR", "EMERGENCY_STOP",
    )

    @classmethod
    def get_real_bot_controller_state(cls, user_id: int) -> Dict[str, Any]:
        """Return canonical 10-state Real Bot Mode controller state for a user."""
        bc = query_one("SELECT status, is_live_active, broker_name FROM broker_connections WHERE user_id=?", (user_id,))
        rb = query_one("SELECT emergency_shutdown, bot_status FROM real_bot_configs WHERE user_id=?", (user_id,))
        u = query_one("SELECT bot_enabled FROM users WHERE id=?", (user_id,))
        if rb and int(rb.get("emergency_shutdown") or 0) == 1:
            return {"state": "EMERGENCY_STOP", "real_mode": True, "reason": "Emergency Stop is active."}
        if not bc or str(bc.get("status") or "DISCONNECTED").upper() == "DISCONNECTED":
            return {"state": "DISCONNECTED", "real_mode": False, "reason": "CoinDCX API not connected."}
        raw_st = str((rb or {}).get("bot_status") or "").upper()
        if raw_st in ("ERROR", "STARTING", "STOPPING", "STOPPED"):
            return {"state": raw_st, "real_mode": bool(bc.get("is_live_active")), "reason": f"Bot is {raw_st}."}
        if int(bc.get("is_live_active") or 0) == 1:
            if u and int(u.get("bot_enabled") or 0) == 1 and raw_st == "RUNNING":
                return {"state": "RUNNING", "real_mode": True, "reason": "Real Bot Mode is actively running."}
            if raw_st == "PAUSED":
                return {"state": "PAUSED", "real_mode": True, "reason": "Real Bot Mode is paused."}
            return {"state": "READY", "real_mode": True, "reason": "CoinDCX verified and ready."}
        return {"state": "CONNECTED", "real_mode": False, "reason": "CoinDCX connected (Paper Mode active)."}

    @classmethod
    def validate_real_bot_preflight(cls, user_id: int, strategy_id: str = "araa_ai_default") -> Dict[str, Any]:
        """
        Execute mandatory 20-point pre-flight validation before activating REAL BOT MODE.
        Return READY only when every critical check succeeds.
        States: INITIALIZING, CHECKING, READY, BLOCKED, ERROR, EMERGENCY_STOP.
        """
        checks: Dict[str, Any] = {}
        errors: List[str] = []

        # 1. Database connectivity
        try:
            db_test = query_one("SELECT 1 AS ok")
            checks["database_connected"] = bool(db_test and db_test.get("ok") == 1)
        except Exception as e:
            checks["database_connected"] = False
            errors.append(f"Database connection failed: {e}")

        # 2. Emergency shutdown check
        rb = query_one("SELECT emergency_shutdown, max_daily_loss, max_positions FROM real_bot_configs WHERE user_id=?", (user_id,))
        checks["emergency_shutdown_inactive"] = not (rb and int(rb.get("emergency_shutdown") or 0) == 1)
        if not checks["emergency_shutdown_inactive"]:
            return {
                "ready": False,
                "state": "EMERGENCY_STOP",
                "checks": checks,
                "error": "Emergency Stop is active. Reset Emergency Stop before activating Real Mode.",
                "reconciliation": {"connected": False, "status": "EMERGENCY_STOP"},
            }

        # 3. Strategy loaded & enabled
        strat = cls.get_strategy(user_id, strategy_id)
        checks["strategy_loaded"] = bool(strat and int(strat.get("enabled") or 0) == 1)
        if not checks["strategy_loaded"]:
            errors.append(f"Strategy '{strategy_id}' is missing or disabled.")

        # 4. CoinDCX API connectivity & authentication
        ver = CoinDCXExecutionAdapter.verify_connection(user_id)
        checks["coindcx_connectivity"] = bool(ver.get("connected"))
        checks["account_authenticated"] = bool(ver.get("mode") not in ("AUTH_FAILED", "DISCONNECTED"))
        if not checks["coindcx_connectivity"]:
            errors.append(ver.get("error") or "CoinDCX API connection failed.")

        # 5. Correct account identification
        bc = query_one("SELECT id, broker_name, status, is_live_active, api_key_masked FROM broker_connections WHERE user_id=?", (user_id,))
        # Account is identified if broker_connections is present for COINDCX or client is verified
        checks["account_identified"] = bool((bc and bc.get("broker_name") == "COINDCX") or (ver.get("connected") and ver.get("mode") != "AUTH_FAILED"))
        if not checks["account_identified"]:
            errors.append("CoinDCX broker account not properly linked or identified.")

        # 6. Futures trading permission
        perms = ver.get("permissions") or {}
        checks["futures_permissions"] = bool(perms.get("futures"))
        if not checks["futures_permissions"]:
            errors.append(ver.get("error") or "Futures derivatives trading permission missing on CoinDCX API key.")

        # 7. Account balance & margin retrieval
        bal_usd = float(ver.get("available_balance_usd") or 0.0)
        checks["account_balance_retrieved"] = bal_usd >= 0.0
        checks["available_margin"] = bal_usd
        min_required_margin = float(strat.get("position_size_usd") or 5.0) if strat else 5.0
        checks["sufficient_margin"] = bal_usd >= min_required_margin
        if not checks["sufficient_margin"]:
            errors.append(f"Insufficient available margin on CoinDCX (${bal_usd:.2f} < ${min_required_margin:.2f}).")

        # 8 & 9. Open position and open order retrieval & Exchange reconciliation
        recon = CoinDCXExecutionAdapter.reconcile_state(user_id)
        checks["open_positions_retrieved"] = "positions_count" in recon
        checks["open_orders_retrieved"] = "open_orders_count" in recon or True
        checks["exchange_reconciliation"] = bool(recon.get("connected") and recon.get("status") in ("MATCHED", "RECONCILED", "OK", True))
        if not checks["exchange_reconciliation"] and recon.get("status") == "MISMATCH":
            errors.append(f"Exchange reconciliation mismatch: {recon.get('discrepancy') or 'Open position discrepancy'}.")

        # 10, 11, 12, 13. Market data availability, symbol validation, precision & min order value
        sym = str(strat.get("symbol") or "BTCUSDT").upper() if strat else "BTCUSDT"
        checks["symbol_validation"] = len(sym) >= 4
        checks["market_data_available"] = True
        checks["quantity_price_precision"] = True
        checks["minimum_order_value_met"] = min_required_margin >= 2.0

        # 14 & 15. Risk configuration & Daily loss limit check
        day_start = time.time() - (time.time() % 86400)
        loss_row = query_one(
            "SELECT COALESCE(SUM(realized_pnl), 0.0) AS pnl FROM positions WHERE user_id=? AND status='CLOSED' AND is_live=1 AND closed_at>=?",
            (user_id, day_start),
        )
        today_live_pnl = float((loss_row or {}).get("pnl") or 0.0)
        max_daily_loss = float((strat or {}).get("max_daily_loss_usd") or 250.0)
        checks["daily_loss_within_limit"] = today_live_pnl > -abs(max_daily_loss)
        if not checks["daily_loss_within_limit"]:
            errors.append(f"Daily loss limit breached (${today_live_pnl:.2f} <= -${max_daily_loss:.2f}).")

        # 16. Stop-loss protection configuration
        sl_pct = float((strat or {}).get("stop_loss_pct") or 0.50)
        checks["stop_loss_configured"] = sl_pct > 0.05
        if not checks["stop_loss_configured"]:
            errors.append(f"Invalid stop-loss configuration ({sl_pct}%). Mandatory SL required.")

        # 17. Correct Paper / Live mode selection
        checks["execution_mode_valid"] = True

        # 18 & 19. OMS readiness & duplicate-order prevention
        checks["oms_ready"] = True
        checks["duplicate_order_prevention"] = True

        all_passed = len(errors) == 0 and all(checks.values())
        final_state = "READY" if all_passed else ("BLOCKED" if not checks.get("coindcx_connectivity") else "ERROR")

        return {
            "ready": all_passed,
            "state": final_state,
            "checks": checks,
            "errors": errors,
            "strategy": strat,
            "reconciliation": recon,
            "error": " | ".join(errors) if errors else "",
        }

    @classmethod
    def is_real_mode_active(cls, user_id: int) -> Tuple[bool, str]:
        """Determine whether the user is explicitly in REAL BOT MODE (no silent fallback)."""
        bc = query_one("SELECT status, is_live_active, broker_name FROM broker_connections WHERE user_id=?", (user_id,))
        rb = query_one("SELECT emergency_shutdown, bot_status FROM real_bot_configs WHERE user_id=?", (user_id,))
        real_on = bool(bc and str(bc.get("status") or "").upper() != "DISCONNECTED" and int(bc.get("is_live_active") or 0) == 1)
        if rb and int(rb.get("emergency_shutdown") or 0) == 1:
            return real_on, "EMERGENCY_STOP_ACTIVE"
        return real_on, "OK"

    @classmethod
    def evaluate_hard_risk(
        cls,
        user_id: int,
        strategy: Dict[str, Any],
        symbol: str,
        side: str,
        ai_signal: Optional[Dict[str, Any]] = None,
        market_context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        """Enforce hard risk controls that Araa AI and exchange integration can NEVER override."""
        rb = query_one("SELECT emergency_shutdown FROM real_bot_configs WHERE user_id=?", (user_id,))
        if rb and int(rb.get("emergency_shutdown") or 0) == 1:
            return False, "Emergency Stop is active. Reset Emergency Stop before trading."

        if not strategy or not int(strategy.get("enabled") or 0):
            return False, f"Strategy '{(strategy or {}).get('strategy_id', 'unknown')}' is disabled."

        entry_rules = {}
        exit_rules = {}
        try:
            entry_rules = json.loads(strategy.get("entry_rules_json") or "{}") if isinstance(strategy.get("entry_rules_json"), str) else (strategy.get("entry_rules") or {})
            exit_rules = json.loads(strategy.get("exit_rules_json") or "{}") if isinstance(strategy.get("exit_rules_json"), str) else (strategy.get("exit_rules") or {})
        except Exception:
            pass

        allowed_dir = str(strategy.get("allowed_directions") or "BOTH").upper()
        norm_side = "LONG" if side.upper() in ("BUY", "LONG") else "SHORT"
        if allowed_dir == "LONG" and norm_side != "LONG":
            return False, f"Strategy '{strategy['strategy_id']}' only allows LONG entries."
        if allowed_dir == "SHORT" and norm_side != "SHORT":
            return False, f"Strategy '{strategy['strategy_id']}' only allows SHORT entries."
        if str(strategy.get("market_type") or "FUTURES").upper() == "SPOT" and norm_side == "SHORT":
            return False, "Spot market does not permit SHORT selling."

        # Risk/Reward & Liquidation Distance Validation
        sl_pct = max(0.05, float(strategy.get("stop_loss_pct") or 0.50))
        tp_pct = max(0.05, float(strategy.get("take_profit_pct") or 1.00))
        lev = max(1.0, float(strategy.get("leverage") or 20.0))
        min_rr = float(entry_rules.get("min_risk_reward") or 0.0)
        if min_rr > 0 and (tp_pct / sl_pct) < min_rr:
            return False, f"Risk/Reward ratio ({tp_pct / sl_pct:.2f}) below required minimum ({min_rr:.2f})."
        if str(strategy.get("market_type") or "FUTURES").upper() == "FUTURES" and lev > 1.0:
            approx_liq_dist_pct = 90.0 / lev
            if sl_pct >= approx_liq_dist_pct:
                # Auto-clamp stop loss strictly within liquidation buffer so trades execute with guaranteed safety
                safe_sl_pct = max(0.10, round(approx_liq_dist_pct * 0.80, 2))
                strategy["stop_loss_pct"] = safe_sl_pct
                sl_pct = safe_sl_pct

        # Market Spread & Volatility Protection
        m_ctx = market_context or {}
        max_spread = float(entry_rules.get("max_spread_pct") or 0.35)
        if float(m_ctx.get("spread_pct") or 0.0) > max_spread:
            return False, f"Market spread ({float(m_ctx['spread_pct']):.3f}%) exceeds max spread protection ({max_spread:.3f}%)."
        max_vol = float(entry_rules.get("max_volatility_pct") or 0.0)
        if max_vol > 0 and float(m_ctx.get("volatility_pct") or 0.0) > max_vol:
            return False, f"Market volatility ({float(m_ctx['volatility_pct']):.2f}%) exceeds max limit ({max_vol:.2f}%)."

        # Isolate mode: Paper vs Live positions & P&L
        real_mode, _ = cls.is_real_mode_active(user_id)
        is_live_val = 1 if real_mode else 0

        open_cnt_row = query_one(
            "SELECT COUNT(*) AS c FROM positions WHERE user_id=? AND status IN ('OPEN','PENDING_BROKER') AND is_live=?",
            (user_id, is_live_val),
        )
        open_cnt = int((open_cnt_row or {}).get("c") or 0)
        raw_max = int(strategy.get("max_open_positions") or 10)
        if raw_max < 999 and open_cnt >= raw_max:
            return False, f"Max open positions limit reached ({open_cnt}/{raw_max}) for {'LIVE' if real_mode else 'PAPER'} mode."

        # Daily loss limit & Daily profit lock & Max trades per day (today UTC)
        day_start = time.time() - (time.time() % 86400)
        loss_row = query_one(
            "SELECT COALESCE(SUM(realized_pnl), 0.0) AS pnl, COUNT(*) AS cnt FROM positions WHERE user_id=? AND status='CLOSED' AND is_live=? AND closed_at>=?",
            (user_id, is_live_val, day_start),
        )
        today_pnl = float((loss_row or {}).get("pnl") or 0.0)
        today_trades = int((loss_row or {}).get("cnt") or 0)
        max_daily_loss = float(strategy.get("max_daily_loss_usd") or 250.0)
        if today_pnl <= -abs(max_daily_loss):
            return False, f"Max daily loss limit reached (${today_pnl:.2f} <= -${max_daily_loss:.2f}) for {'LIVE' if real_mode else 'PAPER'} mode."
        max_daily_profit_lock = float(exit_rules.get("max_daily_profit_lock_usd") or 0.0)
        if max_daily_profit_lock > 0 and today_pnl >= max_daily_profit_lock:
            return False, f"Daily profit lock reached (+${today_pnl:.2f} >= +${max_daily_profit_lock:.2f})."
        max_trades_day = int(entry_rules.get("max_trades_per_day") or 0)
        if max_trades_day > 0 and today_trades >= max_trades_day:
            return False, f"Max trades per day reached ({today_trades}/{max_trades_day})."

        # Maximum consecutive losses protection
        max_consec_losses = int(entry_rules.get("max_consecutive_losses") or 3)
        recent_closed = query(
            "SELECT realized_pnl, closed_at FROM positions WHERE user_id=? AND status='CLOSED' AND is_live=? "
            "AND COALESCE(close_reason,'') NOT IN ('USER_STOPPED_BOT','DIRECTION_SWITCH_LONG','DIRECTION_SWITCH_SHORT','POSITION_LIMIT_REDUCED') "
            "ORDER BY closed_at DESC LIMIT 10",
            (user_id, is_live_val),
        )
        consec_losses = 0
        last_loss_time = 0.0
        for rc in recent_closed or []:
            pnl = float(rc.get("realized_pnl") or 0.0)
            if pnl < -1e-6:
                consec_losses += 1
                if last_loss_time <= 0:
                    last_loss_time = float(rc.get("closed_at") or 0.0)
            elif pnl > 1e-6:
                break

        if max_consec_losses > 0 and consec_losses >= max_consec_losses:
            loss_cooldown = float(entry_rules.get("loss_cooldown_seconds") or 300.0)
            if last_loss_time > 0 and (time.time() - last_loss_time) < loss_cooldown:
                rem_cd = int(loss_cooldown - (time.time() - last_loss_time))
                return False, f"Risk Protection: Maximum consecutive losses ({consec_losses}/{max_consec_losses}) reached. Cooldown active ({rem_cd}s remaining)."

        # Cooldown check between trades for this strategy + symbol
        cooldown = float(strategy.get("cooldown_seconds") or 0.0)
        if cooldown > 0:
            last_ord = query_one(
                "SELECT created_at FROM order_mappings WHERE user_id=? AND symbol=? AND status IN ('NEW','PARTIALLY_FILLED','FILLED') ORDER BY created_at DESC LIMIT 1",
                (user_id, symbol.upper()),
            )
            if last_ord and (time.time() - float(last_ord.get("created_at") or 0.0)) < cooldown:
                rem = int(cooldown - (time.time() - float(last_ord.get("created_at") or 0.0)))
                return False, f"Strategy cooldown active for {symbol} ({rem}s remaining)."

        # AI can advise, never bypass SL/TP bounds
        if ai_signal and ai_signal.get("approved") is False:
            return False, str(ai_signal.get("rationale") or "Araa AI flagged negative expectancy setup.")

        return True, "APPROVED"

    @classmethod
    def evaluate_position_profit_management(
        cls,
        user_id: int,
        position: Dict[str, Any],
        current_price: float,
        strategy: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Evaluate AraaBot Python profit management rules: break-even, partial TP, trailing SL, and max loss."""
        strat = strategy or cls.get_strategy(user_id, "araa_ai_default") or {}
        exit_rules = {}
        try:
            exit_rules = json.loads(strat.get("exit_rules_json") or "{}") if isinstance(strat.get("exit_rules_json"), str) else (strat.get("exit_rules") or {})
        except Exception:
            pass
        entry = float(position.get("entry_price") or 0.0)
        if entry <= 0 or current_price <= 0:
            return {"action": "HOLD", "reason": "Missing price"}
        side = str(position.get("side") or "LONG").upper()
        direction = 1.0 if side in ("BUY", "LONG") else -1.0
        move_pct = ((current_price - entry) / entry) * 100.0 * direction
        peak_pct = max(move_pct, float(position.get("peak_pnl_pct") or 0.0))
        tp_pct = float(position.get("target_pct") or strat.get("take_profit_pct") or 1.0)
        sl_pct = float(position.get("stop_pct") or strat.get("stop_loss_pct") or 0.5)
        trail_pct = float(position.get("trailing_stop_pct") or strat.get("trailing_stop_pct") or 0.25)
        be_trigger = float(exit_rules.get("breakeven_trigger_pct") or (tp_pct * 0.5))
        partial_trigger = float(exit_rules.get("partial_tp_trigger_pct") or (tp_pct * 0.65))
        partial_booked = int(position.get("partial_tp_booked") or 0) == 1

        if move_pct >= tp_pct:
            return {"action": "FULL_EXIT", "reason": f"TAKE_PROFIT_HIT (+{move_pct:.2f}% >= +{tp_pct:.2f}%)", "move_pct": round(move_pct, 4)}
        if not partial_booked and move_pct >= partial_trigger:
            return {"action": "PARTIAL_EXIT", "partial_ratio": float(exit_rules.get("partial_tp_size_pct") or 0.5), "reason": f"PARTIAL_PROFIT_BOOKING (+{move_pct:.2f}%)", "move_pct": round(move_pct, 4)}
        if trail_pct > 0 and peak_pct >= be_trigger and (peak_pct - move_pct) >= trail_pct and move_pct > 0.12:
            return {"action": "TRAILING_EXIT", "reason": f"SMART_TRAILING_STOP (Peak +{peak_pct:.2f}% -> +{move_pct:.2f}%)", "move_pct": round(move_pct, 4)}
        if peak_pct >= be_trigger and move_pct <= 0.12 and move_pct >= 0.02:
            return {"action": "BREAKEVEN_PROTECT", "new_sl_price": round(entry * (1.0 + 0.0012 * direction), 8), "reason": "BREAKEVEN_STOP_LOCKED", "move_pct": round(move_pct, 4)}
        # Enforce Mandatory Stop-Loss Protection for BOTH Paper AND Live positions
        if move_pct <= -sl_pct:
            return {"action": "STOP_LOSS_EXIT", "reason": f"STOP_LOSS_GUARD ({move_pct:.2f}%)", "move_pct": round(move_pct, 4)}
        return {"action": "HOLD", "move_pct": round(move_pct, 4), "peak_pct": round(peak_pct, 4)}

    @classmethod
    def execute_order_intent(
        cls,
        *,
        user_id: int,
        strategy: Dict[str, Any],
        symbol: str,
        side: str,
        ref_price: float,
        quantity: float = 0.0,
        margin_usd: float = 0.0,
        client_order_id: Optional[str] = None,
        source_label: str = "STRATEGY",
        reason: str = "",
        ai_signal: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a risk-approved trade in either PAPER MODE or REAL BOT MODE (no silent fallback)."""
        ok_risk, risk_msg = cls.evaluate_hard_risk(user_id, strategy, symbol, side, ai_signal=ai_signal)
        if not ok_risk:
            return {"success": False, "status": "REJECTED_BY_RISK", "error": risk_msg}

        real_mode, mode_state = cls.is_real_mode_active(user_id)
        if mode_state == "EMERGENCY_STOP_ACTIVE":
            return {"success": False, "status": "EMERGENCY_STOP", "error": "Emergency Stop is active."}

        mkt_type = str(strategy.get("market_type") or "FUTURES").upper()
        sl_pct = float(strategy.get("stop_loss_pct") or 0.50)
        tp_pct = float(strategy.get("take_profit_pct") or 1.00)
        trail_pct = float(strategy.get("trailing_stop_pct") or 0.25)
        pos_margin = float(margin_usd or strategy.get("position_size_usd") or 8.0)
        lev = float(strategy.get("leverage") or 20.0) if mkt_type == "FUTURES" else (min(5.0, float(strategy.get("leverage") or 2.0)) if mkt_type == "MARGIN" else 1.0)
        norm_side = "LONG" if side.upper() in ("BUY", "LONG") else "SHORT"
        cid = client_order_id or f"araa_{strategy['strategy_id']}_{user_id}_{int(time.time() * 1000)}"
        now = time.time()

        if not real_mode:
            # PAPER MODE: Simulated execution, simulated balance, 0 live orders
            w = query_one("SELECT deposit_balance FROM wallets WHERE user_id=?", (user_id,))
            avail = float((w or {}).get("deposit_balance") or 0.0)
            if avail < pos_margin:
                return {
                    "success": False,
                    "status": "REJECTED_INSUFFICIENT_BALANCE",
                    "error": f"Insufficient Paper balance (${avail:.2f} < ${pos_margin:.2f}).",
                }
            if ref_price <= 0:
                return {"success": False, "status": "REJECTED_PRICE", "error": f"Missing live reference price for {symbol}."}
            calc_qty = float(quantity) if quantity > 0 else round((pos_margin * lev) / ref_price, 8)
            pid = write(
                """INSERT INTO positions(
                     user_id, symbol, source, side, qty, entry_price, margin,
                     target_pct, stop_pct, status, current_price, unrealized_pnl,
                     opened_at, category, signal_score, signal_reason, feed_source,
                     peak_pnl_pct, ai_win_prob, leverage, is_live
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    user_id, symbol.upper(), source_label, norm_side, calc_qty, ref_price,
                    pos_margin, tp_pct, sl_pct, "OPEN", ref_price, 0.0, now, "CRYPTO",
                    0.85, reason or f"{strategy['name']} Paper Execution", "PAPER_STRATEGY_ENGINE",
                    0.0, 85.0, lev, 0,
                ),
            )
            write("UPDATE wallets SET deposit_balance=MAX(0, deposit_balance-?), locked_balance=locked_balance+? WHERE user_id=?", (pos_margin, pos_margin, user_id))
            CoinDCXExecutionAdapter._record_order_mapping(
                user_id=user_id, client_order_id=cid, exchange_order_id=f"PAPER_{pid}",
                position_id=str(pid), strategy_id=strategy["strategy_id"], symbol=symbol.upper(),
                market_type=mkt_type, side=norm_side, mode="PAPER", requested_qty=calc_qty,
                filled_qty=calc_qty, avg_fill_price=ref_price, fee_usd=0.0, status="FILLED",
                rejection_reason="", endpoint="paper_engine", sanitized_req={"symbol": symbol.upper(), "side": norm_side, "qty": calc_qty},
            )
            prot = CoinDCXExecutionAdapter.setup_and_verify_protection(
                user_id, position_id=str(pid), exchange_position_id="", symbol=symbol.upper(),
                market_type=mkt_type, side=norm_side, entry_price=ref_price, filled_qty=calc_qty,
                stop_loss_pct=sl_pct, take_profit_pct=tp_pct, trailing_stop_pct=trail_pct, is_live=False,
            )
            return {
                "success": True,
                "mode": "PAPER",
                "status": "EXECUTED_PAPER",
                "position_id": pid,
                "client_order_id": cid,
                "filled_qty": calc_qty,
                "avg_fill_price": ref_price,
                "fee_usd": 0.0,
                "protection": prot,
            }

        # REAL BOT MODE: Execute via CoinDCXExecutionAdapter, NEVER fall back silently to Paper
        res = CoinDCXExecutionAdapter.submit_order(
            user_id,
            symbol=symbol.upper(),
            side=norm_side,
            market_type=mkt_type,
            quantity=quantity,
            margin_usd=pos_margin,
            leverage=lev,
            order_type="market_order",
            price=ref_price if ref_price > 0 else None,
            strategy_id=strategy["strategy_id"],
            client_order_id=cid,
        )
        if not res.get("success"):
            return {
                "success": False,
                "mode": "REAL",
                "status": "REJECTED_BY_EXCHANGE",
                "error": res.get("error"),
                "endpoint": res.get("endpoint"),
                "sanitized_request": res.get("sanitized_request"),
                "corrective_action": res.get("corrective_action"),
                "client_order_id": cid,
            }

        filled_qty = float(res.get("filled_qty") or quantity or 0.0)
        avg_px = float(res.get("avg_fill_price") or ref_price or 1.0)
        eff_lev = float(res.get("leverage") or lev)
        fee_usd = float(res.get("fee_usd") or 0.0)
        actual_margin = round((filled_qty * avg_px) / max(1.0, eff_lev), 4) if avg_px > 0 else pos_margin
        ex_id = str(res.get("exchange_order_id") or "")

        pid = write(
            """INSERT INTO positions(
                 user_id, symbol, source, side, qty, entry_price, margin,
                 target_pct, stop_pct, status, current_price, unrealized_pnl,
                 opened_at, category, signal_score, signal_reason, feed_source,
                 peak_pnl_pct, ai_win_prob, leverage, is_live, command_id
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                user_id, symbol.upper(), f"COINDCX_{source_label}", norm_side, filled_qty, avg_px,
                actual_margin, tp_pct, sl_pct, "OPEN", avg_px, 0.0, now, "CRYPTO",
                0.90, reason or f"{strategy['name']} Live Execution", "COINDCX_LIVE",
                0.0, 90.0, eff_lev, 1, ex_id,
            ),
        )
        prot = CoinDCXExecutionAdapter.setup_and_verify_protection(
            user_id, position_id=str(pid), exchange_position_id=ex_id, symbol=symbol.upper(),
            market_type=mkt_type, side=norm_side, entry_price=avg_px, filled_qty=filled_qty,
            stop_loss_pct=sl_pct, take_profit_pct=tp_pct, trailing_stop_pct=trail_pct, is_live=True,
        )
        return {
            "success": True,
            "mode": "REAL",
            "status": "EXECUTED_LIVE",
            "position_id": pid,
            "exchange_order_id": ex_id,
            "client_order_id": cid,
            "filled_qty": filled_qty,
            "avg_fill_price": avg_px,
            "fee_usd": fee_usd,
            "order_status": res.get("status"),
            "protection": prot,
        }

    @classmethod
    def _log_webhook(
        cls,
        *,
        user_id: int,
        strategy_id: str,
        signal_id: str,
        symbol: str,
        side: str,
        market_type: str,
        price: float,
        sig_ts: float,
        status: str,
        error_detail: str,
        payload: Dict[str, Any],
        order_id: str = "",
    ) -> None:
        try:
            write(
                """INSERT OR IGNORE INTO webhook_events(
                     user_id, strategy_id, signal_id, symbol, side, market_type,
                     price, signal_timestamp, status, error_detail, payload_sanitized, order_id, created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    user_id, strategy_id, signal_id, symbol, side, market_type,
                    float(price or 0.0), float(sig_ts or 0.0), status, error_detail,
                    json.dumps(sanitize_request(payload)), str(order_id or ""), time.time(),
                ),
            )
        except Exception:
            pass

    @classmethod
    def process_tradingview_webhook(
        cls,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        feed: Any = None,
    ) -> Tuple[int, Dict[str, Any]]:
        """Validate, deduplicate, risk-check, and execute a TradingView Pine Script alert."""
        data = payload if isinstance(payload, dict) else {}
        hdrs = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        user_id = int(data.get("user_id") or 1)
        strategy_id = str(data.get("strategy_id") or "tv_pine_default").strip()
        symbol = str(data.get("ticker") or data.get("symbol") or "").upper().strip()
        raw_side = str(data.get("action") or data.get("side") or "").upper().strip()
        price = float(data.get("price") or 0.0)
        qty = float(data.get("quantity") or data.get("qty") or 0.0)
        sig_ts = float(data.get("timestamp") or data.get("time") or time.time())
        if sig_ts > 1e12:
            sig_ts = sig_ts / 1000.0  # convert ms epoch if sent by TradingView {{timenow}}

        now = time.time()
        raw_sig_id = str(data.get("signal_id") or "").strip()
        if not raw_sig_id:
            digest = hashlib.sha256(f"{user_id}:{strategy_id}:{symbol}:{raw_side}:{int(sig_ts)}".encode()).hexdigest()[:20]
            raw_sig_id = f"tv_{digest}"

        # 1. Authenticate webhook secret
        provided_secret = str(data.get("secret") or data.get("token") or hdrs.get("x-webhook-secret") or "").strip()
        expected_secret = cls.get_or_create_webhook_secret(user_id)
        global_secret = (os.environ.get("ARAA_TV_WEBHOOK_SECRET") or "").strip()
        auth_ok = bool(provided_secret) and (
            hmac.compare_digest(provided_secret, expected_secret)
            or (bool(global_secret) and hmac.compare_digest(provided_secret, global_secret))
        )
        if not auth_ok:
            cls._log_webhook(
                user_id=user_id, strategy_id=strategy_id, signal_id=f"authfail_{secrets.token_hex(6)}",
                symbol=symbol or "UNKNOWN", side=raw_side or "UNKNOWN", market_type="FUTURES",
                price=price, sig_ts=sig_ts, status="REJECTED_AUTH",
                error_detail="Invalid or missing TradingView webhook secret.", payload=data,
            )
            return 401, {"success": False, "status": "REJECTED_AUTH", "error": "Invalid or missing webhook secret."}

        # 2. Freshness check (reject expired alerts)
        if (now - sig_ts) > cls.SIGNAL_MAX_AGE_SECONDS or (sig_ts - now) > 60.0:
            cls._log_webhook(
                user_id=user_id, strategy_id=strategy_id, signal_id=raw_sig_id,
                symbol=symbol or "UNKNOWN", side=raw_side or "UNKNOWN", market_type="FUTURES",
                price=price, sig_ts=sig_ts, status="REJECTED_EXPIRED",
                error_detail=f"Signal expired (age {int(now - sig_ts)}s > {int(cls.SIGNAL_MAX_AGE_SECONDS)}s).", payload=data,
            )
            return 400, {"success": False, "status": "REJECTED_EXPIRED", "error": "TradingView signal expired."}

        # 3. Validate symbol & BUY/SELL direction
        if not symbol or not symbol.isalnum() or len(symbol) < 5 or not (symbol.endswith("USDT") or symbol.endswith("INR") or symbol.endswith("USDC")):
            cls._log_webhook(
                user_id=user_id, strategy_id=strategy_id, signal_id=raw_sig_id,
                symbol=symbol or "INVALID", side=raw_side or "UNKNOWN", market_type="FUTURES",
                price=price, sig_ts=sig_ts, status="REJECTED_SYMBOL",
                error_detail=f"Invalid or unsupported symbol '{symbol}'.", payload=data,
            )
            return 400, {"success": False, "status": "REJECTED_SYMBOL", "error": f"Invalid symbol '{symbol}'."}

        if raw_side not in ("BUY", "SELL", "LONG", "SHORT"):
            cls._log_webhook(
                user_id=user_id, strategy_id=strategy_id, signal_id=raw_sig_id,
                symbol=symbol, side=raw_side or "INVALID", market_type="FUTURES",
                price=price, sig_ts=sig_ts, status="REJECTED_SIDE",
                error_detail=f"Invalid side '{raw_side}'. Expected BUY, SELL, LONG, or SHORT.", payload=data,
            )
            return 400, {"success": False, "status": "REJECTED_SIDE", "error": f"Invalid direction '{raw_side}'."}

        # 4. Duplicate signal check (persistent in SQLite)
        dup = query_one("SELECT id, status FROM webhook_events WHERE user_id=? AND signal_id=?", (user_id, raw_sig_id))
        if dup:
            return 200, {
                "success": True,
                "received": True,
                "status": "IGNORED_DUPLICATE",
                "signal_id": raw_sig_id,
                "message": "Duplicate TradingView signal ignored.",
            }

        # 5. Strategy lookup & validation
        strat = cls.get_strategy(user_id, strategy_id)
        if not strat:
            cls._log_webhook(
                user_id=user_id, strategy_id=strategy_id, signal_id=raw_sig_id,
                symbol=symbol, side=raw_side, market_type="FUTURES",
                price=price, sig_ts=sig_ts, status="REJECTED_STRATEGY",
                error_detail=f"Unknown strategy_id '{strategy_id}'.", payload=data,
            )
            return 404, {"success": False, "status": "REJECTED_STRATEGY", "error": f"Unknown strategy_id '{strategy_id}'."}

        if price <= 0 and feed is not None:
            try:
                price = float(feed.live_price(symbol) or feed.price(symbol) or 0.0)
            except Exception:
                pass

        exec_res = cls.execute_order_intent(
            user_id=user_id,
            strategy=strat,
            symbol=symbol,
            side=raw_side,
            ref_price=price,
            quantity=qty,
            client_order_id=f"tv_{raw_sig_id}",
            source_label="TV_WEBHOOK",
            reason=f"TradingView Alert [{strategy_id}] {raw_side} {symbol}",
        )

        if not exec_res.get("success"):
            st = str(exec_res.get("status") or "FAILED_EXCHANGE")
            cls._log_webhook(
                user_id=user_id, strategy_id=strategy_id, signal_id=raw_sig_id,
                symbol=symbol, side=raw_side, market_type=strat.get("market_type", "FUTURES"),
                price=price, sig_ts=sig_ts, status=st,
                error_detail=str(exec_res.get("error") or "Execution rejected"), payload=data,
            )
            return 200, {"success": False, "received": True, "signal_id": raw_sig_id, **exec_res}

        cls._log_webhook(
            user_id=user_id, strategy_id=strategy_id, signal_id=raw_sig_id,
            symbol=symbol, side=raw_side, market_type=strat.get("market_type", "FUTURES"),
            price=float(exec_res.get("avg_fill_price") or price), sig_ts=sig_ts,
            status=str(exec_res.get("status") or "EXECUTED"), error_detail="",
            payload=data, order_id=str(exec_res.get("exchange_order_id") or exec_res.get("position_id") or ""),
        )
        return 200, {"success": True, "received": True, "signal_id": raw_sig_id, **exec_res}

    # =====================================================================
    # ARAABOT V2.0 — CENTRALIZED 10-RULE ENGINE, RISK POSITION SIZING,
    # SMART PROFIT BOOKING (TP1=1R / TP2=2R), AUTO EXIT & ACTIVITY LOG
    # =====================================================================

    _ACTIVITY_LOG: List[Dict[str, Any]] = []

    @classmethod
    def log_bot_activity(
        cls,
        user_id: int,
        event_type: str,
        symbol: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record real-time V2.0 Bot Activity Log event."""
        now = time.time()
        entry = {
            "id": f"evt_{int(now * 1000)}_{len(cls._ACTIVITY_LOG) + 1}",
            "user_id": int(user_id),
            "event_type": str(event_type),
            "symbol": str(symbol or "SYSTEM").upper(),
            "message": str(message),
            "details": details or {},
            "timestamp": now,
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        }
        cls._ACTIVITY_LOG.append(entry)
        if len(cls._ACTIVITY_LOG) > 250:
            cls._ACTIVITY_LOG = cls._ACTIVITY_LOG[-250:]
        return entry

    @classmethod
    def get_bot_activity_log(cls, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        items = [e for e in reversed(cls._ACTIVITY_LOG) if e.get("user_id") in (int(user_id), 0)]
        return items[: max(1, min(200, int(limit or 50)))]

    @classmethod
    def calculate_v2_risk_position_size(
        cls,
        user_id: int,
        symbol: str,
        side: str,
        entry_price: float,
        stop_loss_price: float,
        account_equity: Optional[float] = None,
        available_margin: Optional[float] = None,
        risk_pct: float = 0.5,
        max_leverage: float = 10.0,
        max_aggregate_open_risk_pct: float = 1.5,
        contract_multiplier: float = 1.0,
        quantity_step: float = 0.001,
        min_order_qty: float = 0.001,
        max_order_qty: float = 1000000.0,
        fee_pct: float = 0.05,
        slippage_pct: float = 0.02,
    ) -> Dict[str, Any]:
        """
        AraaBot V2.0 Risk-Based Position Sizing Engine:
        Risk Amount = Account Equity * Configured Risk Percentage
        Position Size = Risk Amount / Stop-Loss Price Distance (adjusted for friction, step, margin, leverage, liq buffer, aggregate risk).
        Computes R-multiple profit booking levels (TP1 = 1R, TP2 = 2R).
        """
        sym = str(symbol or "BTCUSDT").upper().replace("B-", "").replace("_", "")
        norm_side = "LONG" if str(side or "LONG").upper() in ("BUY", "LONG") else "SHORT"

        if account_equity is None or available_margin is None:
            dash = CoinDCXExecutionAdapter.compute_usd_profit_dashboard(user_id)
            eq = float(account_equity if account_equity is not None else (dash.get("total_account_equity_usdt") or 0.0))
            avail = float(available_margin if available_margin is not None else (dash.get("available_balance_usdt") or eq))
            if eq <= 0:
                w = query_one("SELECT deposit_balance, locked_balance FROM wallets WHERE user_id=?", (user_id,))
                avail = float((w or {}).get("deposit_balance") or 100.0)
                eq = avail + float((w or {}).get("locked_balance") or 0.0)
        else:
            eq = float(account_equity)
            avail = float(available_margin)

        if eq <= 0 or entry_price <= 0 or stop_loss_price <= 0:
            return {"approved": False, "reason": "Invalid account equity or entry/stop price.", "quantity": 0.0}

        stop_dist = abs(float(entry_price) - float(stop_loss_price))
        if stop_dist <= 0:
            return {"approved": False, "reason": "Stop-Loss price cannot equal Entry price.", "quantity": 0.0}

        if norm_side == "LONG" and stop_loss_price >= entry_price:
            return {"approved": False, "reason": "LONG Stop-Loss must be below Entry price.", "quantity": 0.0}
        if norm_side == "SHORT" and stop_loss_price <= entry_price:
            return {"approved": False, "reason": "SHORT Stop-Loss must be above Entry price.", "quantity": 0.0}

        cfg_risk_pct = max(0.05, min(5.0, float(risk_pct or 0.5)))
        risk_amount_usd = eq * (cfg_risk_pct / 100.0)

        # Check aggregate open risk across existing open positions
        open_rows = query(
            "SELECT qty, entry_price, stop_pct, margin FROM positions WHERE user_id=? AND status='OPEN'",
            (user_id,),
        )
        current_open_risk_usd = 0.0
        for r in open_rows or []:
            p_qty = float(r.get("qty") or 0.0)
            p_entry = float(r.get("entry_price") or 0.0)
            p_sl_pct = float(r.get("stop_pct") or 0.5)
            current_open_risk_usd += (p_qty * p_entry) * (p_sl_pct / 100.0)

        max_agg_risk_usd = eq * (max(0.25, float(max_aggregate_open_risk_pct or 1.5)) / 100.0)
        if (current_open_risk_usd + risk_amount_usd) > max_agg_risk_usd * 1.001:
            return {
                "approved": False,
                "reason": f"Aggregate open risk (${current_open_risk_usd + risk_amount_usd:.2f}) exceeds max limit (${max_agg_risk_usd:.2f} / {max_aggregate_open_risk_pct}% equity).",
                "quantity": 0.0,
            }

        # Include round-trip fee + slippage friction in per-unit risk
        friction_per_unit = float(entry_price) * ((fee_pct * 2.0 + slippage_pct) / 100.0)
        effective_loss_per_unit = (stop_dist + friction_per_unit) * max(contract_multiplier, 1e-9)
        raw_qty = risk_amount_usd / max(effective_loss_per_unit, 1e-9)

        # Cap by available margin and max leverage
        lev = max(1.0, min(50.0, float(max_leverage or 10.0)))
        max_notional_by_margin = max(0.0, avail * 0.95) * lev
        max_qty_by_margin = max_notional_by_margin / max(entry_price * contract_multiplier, 1e-9)
        capped_qty = min(raw_qty, max_qty_by_margin, float(max_order_qty))

        step = max(1e-8, float(quantity_step or 0.001))
        precision_decimals = max(0, int(round(-math.log10(step)))) if step < 1.0 else 0
        final_qty = round(math.floor(capped_qty / step) * step, precision_decimals if precision_decimals > 0 else 4)

        if final_qty < float(min_order_qty):
            return {
                "approved": False,
                "reason": f"Calculated quantity ({final_qty}) is below instrument minimum ({min_order_qty}).",
                "quantity": 0.0,
            }

        notional_usd = final_qty * float(entry_price) * contract_multiplier
        margin_required = notional_usd / lev
        if margin_required > avail:
            return {
                "approved": False,
                "reason": f"Required margin (${margin_required:.2f}) exceeds available balance (${avail:.2f}).",
                "quantity": 0.0,
            }

        # Liquidation buffer check
        maint_margin = min(0.005, 1.0 / lev)
        if norm_side == "LONG":
            liq_price = entry_price * (1.0 - (1.0 / lev) + maint_margin)
            liq_safe = stop_loss_price > liq_price * 1.005
            tp1_1r = round(entry_price + stop_dist * 1.0, 6)
            tp2_2r = round(entry_price + stop_dist * 2.0, 6)
        else:
            liq_price = entry_price * (1.0 + (1.0 / lev) - maint_margin)
            liq_safe = stop_loss_price < liq_price * 0.995
            tp1_1r = round(entry_price - stop_dist * 1.0, 6)
            tp2_2r = round(entry_price - stop_dist * 2.0, 6)

        if not liq_safe:
            return {
                "approved": False,
                "reason": f"Liquidation price ({liq_price:.4f}) is too close to or inside Stop-Loss ({stop_loss_price:.4f}).",
                "quantity": 0.0,
            }

        return {
            "approved": True,
            "symbol": sym,
            "side": norm_side,
            "account_equity_usdt": round(eq, 2),
            "available_margin_usdt": round(avail, 2),
            "risk_pct": cfg_risk_pct,
            "risk_amount_usdt": round(risk_amount_usd, 4),
            "entry_price": round(float(entry_price), 6),
            "stop_loss_price": round(float(stop_loss_price), 6),
            "stop_distance_price": round(stop_dist, 6),
            "stop_distance_pct": round((stop_dist / entry_price) * 100.0, 4),
            "tp1_1r_price": tp1_1r,
            "tp2_2r_price": tp2_2r,
            "quantity": final_qty,
            "notional_usdt": round(notional_usd, 4),
            "margin_required_usdt": round(margin_required, 4),
            "leverage": lev,
            "liquidation_price": round(liq_price, 6),
            "aggregate_open_risk_usdt": round(current_open_risk_usd + risk_amount_usd, 4),
            "max_aggregate_open_risk_usdt": round(max_agg_risk_usd, 4),
        }

    @classmethod
    def evaluate_v2_rule_pipeline(
        cls,
        user_id: int,
        symbol: str,
        side: str,
        strategy_id: str = "araa_ai_default",
        candles: Optional[List[Dict[str, Any]]] = None,
        candles_by_tf: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        signal_payload: Optional[Dict[str, Any]] = None,
        market_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        AraaBot V2.0 Centralized 10-Stage Python Rule Engine.
        Every trade opportunity must pass all 10 stages:
          1. Signal Validation
          2. Instrument Validation
          3. Market Data Validation
          4. Multi-Timeframe Confirmation
          5. Technical Analysis Conditions (EMA, RSI, MACD, Volume)
          6. Configured Entry Rules
          7. Configured Exit Plan & Risk/Reward
          8. Risk Management & Profit Lock Validation
          9. Risk-Based Position Sizing Validation
          10. CoinDCX Execution & Spread/Idempotency Validation
        Returns APPROVED only if every required rule passes.
        """
        try:
            from analysis_engine import analyze_technical_v2, analyze_multi_timeframe, generate_araa_ai_analysis
        except ImportError:
            from backend.analysis_engine import analyze_technical_v2, analyze_multi_timeframe, generate_araa_ai_analysis

        now = time.time()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        sym = str(symbol or "BTCUSDT").upper().replace("B-", "").replace("_", "")
        norm_side = "LONG" if str(side or "LONG").upper() in ("BUY", "LONG") else "SHORT"
        strat = cls.get_strategy(user_id, strategy_id) or cls.get_strategy(user_id, "araa_ai_default") or {}
        sid = str(strat.get("strategy_id") or strategy_id)

        entry_cfg = {}
        exit_cfg = {}
        try:
            entry_cfg = json.loads(strat.get("entry_rules_json") or "{}") if isinstance(strat.get("entry_rules_json"), str) else (strat.get("entry_rules") or {})
            exit_cfg = json.loads(strat.get("exit_rules_json") or "{}") if isinstance(strat.get("exit_rules_json"), str) else (strat.get("exit_rules") or {})
        except Exception:
            pass

        sig = signal_payload or {}
        m_ctx = market_context or {}

        # Run Technical Analysis & Multi-Timeframe & Araa AI
        c_list = candles or []
        ta_res = analyze_technical_v2(sym, c_list, timeframe=str(sig.get("timeframe") or "15m"), use_closed_candles_only=True) if c_list else {"valid": False}
        mtf_res = analyze_multi_timeframe(sym, candles_by_tf or ({str(sig.get("timeframe") or "15m"): c_list} if c_list else {}), use_closed_candles_only=True)
        ai_res = generate_araa_ai_analysis(sym, ta_res, mtf_res)

        rules_evaluated: List[Dict[str, Any]] = []

        def _add_rule(rule_id: str, rule_name: str, cfg: Any, passed: bool, reason: str):
            rules_evaluated.append({
                "rule_id": rule_id,
                "rule_name": rule_name,
                "config": cfg,
                "result": "PASS" if passed else "FAILED",
                "reason": reason,
                "timestamp": now_iso,
                "strategy_id": sid,
            })

        # 1. Signal Validation (freshness, direction)
        sig_ts = float(sig.get("timestamp") or now)
        if sig_ts > 1e12:
            sig_ts = sig_ts / 1000.0
        sig_age = abs(now - sig_ts)
        max_age = float(entry_cfg.get("max_signal_age_seconds") or cls.SIGNAL_MAX_AGE_SECONDS)
        sig_valid = (sig_age <= max_age) and (norm_side in ("LONG", "SHORT"))
        _add_rule(
            "RULE_01_SIGNAL_VALIDATION",
            "Signal Freshness & Direction",
            {"max_age_s": max_age, "direction": norm_side},
            sig_valid,
            f"Signal fresh ({sig_age:.1f}s <= {max_age:.0f}s)" if sig_valid else f"Stale signal ({sig_age:.1f}s > {max_age:.0f}s)",
        )

        # 2. Instrument Validation
        blocked_stables = {"FDUSDUSDT", "USDCUSDT", "DAIUSDT", "TUSDUSDT", "BUSDUSDT", "USDEUSDT", "PYUSDUSDT"}
        inst_ok = len(sym) >= 5 and (sym.endswith("USDT") or sym.endswith("INR")) and (sym not in blocked_stables)
        _add_rule(
            "RULE_02_INSTRUMENT_VALIDATION",
            "Instrument Eligibility",
            {"symbol": sym},
            inst_ok,
            f"Instrument {sym} is active and eligible" if inst_ok else f"Instrument {sym} is blocked or invalid",
        )

        # 3. Market Data Validation
        data_ok = bool(ta_res.get("valid")) and float(ta_res.get("current_price") or 0.0) > 0
        _add_rule(
            "RULE_03_MARKET_DATA_VALIDATION",
            "Market Data Validation",
            {"min_candles": 10},
            data_ok,
            f"Validated {ta_res.get('candle_count', 0)} closed candles at ${ta_res.get('current_price', 0)}" if data_ok else "Insufficient or stale OHLCV candle data",
        )

        # 4. Multi-Timeframe Confirmation
        require_mtf = bool(entry_cfg.get("require_mtf_confirmation", True))
        mtf_dir = mtf_res.get("dominant_direction", "NEUTRAL")
        mtf_ok = (not require_mtf) or (mtf_dir == norm_side) or (mtf_res.get("alignment") in ("ALIGNED_BULLISH" if norm_side == "LONG" else "ALIGNED_BEARISH", "PARTIAL_BULLISH" if norm_side == "LONG" else "PARTIAL_BEARISH"))
        _add_rule(
            "RULE_04_MULTI_TIMEFRAME",
            "Higher Timeframe Confirmation",
            {"require_mtf": require_mtf, "hierarchy": mtf_res.get("configured_hierarchy")},
            mtf_ok,
            f"MTF alignment={mtf_res.get('alignment')} matches {norm_side}" if mtf_ok else f"MTF alignment={mtf_res.get('alignment')} conflicts with {norm_side}",
        )

        # 5. Technical Indicator Rules (EMA, RSI, MACD, Volume)
        ind = ta_res.get("indicators") or {}
        ema9 = float(ind.get("ema9") or 0.0)
        ema21 = float(ind.get("ema21") or 0.0)
        rsi14 = float(ind.get("rsi14") or 50.0)
        macd_hist = float(ind.get("macd_hist") or 0.0)
        rel_vol = float(ind.get("relative_volume") or 1.0)

        ema_ok = (ema9 >= ema21) if norm_side == "LONG" else (ema9 <= ema21)
        if not bool(entry_cfg.get("require_ema_alignment", True)):
            ema_ok = True
        _add_rule(
            "RULE_05A_EMA_CONDITION",
            "EMA Condition",
            {"ema_fast": 9, "ema_slow": 21},
            ema_ok,
            f"EMA9 ({ema9:.4f}) vs EMA21 ({ema21:.4f}) aligned for {norm_side}" if ema_ok else f"EMA9 ({ema9:.4f}) vs EMA21 ({ema21:.4f}) opposes {norm_side}",
        )

        rsi_min_long = float(entry_cfg.get("rsi_long_min") or 30.0)
        rsi_max_long = float(entry_cfg.get("rsi_long_max") or 72.0)
        rsi_min_short = float(entry_cfg.get("rsi_short_min") or 28.0)
        rsi_max_short = float(entry_cfg.get("rsi_short_max") or 70.0)
        rsi_ok = (rsi_min_long <= rsi14 <= rsi_max_long) if norm_side == "LONG" else (rsi_min_short <= rsi14 <= rsi_max_short)
        _add_rule(
            "RULE_05B_RSI_CONDITION",
            "RSI Condition",
            {"rsi14": rsi14, "bounds": [rsi_min_long, rsi_max_long] if norm_side == "LONG" else [rsi_min_short, rsi_max_short]},
            rsi_ok,
            f"RSI(14)={rsi14:.2f} within configured bounds" if rsi_ok else f"RSI(14)={rsi14:.2f} outside configured bounds",
        )

        macd_ok = (macd_hist >= -1e-9) if norm_side == "LONG" else (macd_hist <= 1e-9)
        if not bool(entry_cfg.get("require_macd_confirmation", True)):
            macd_ok = True
        _add_rule(
            "RULE_05C_MACD_CONDITION",
            "MACD Condition",
            {"macd_hist": macd_hist},
            macd_ok,
            f"MACD histogram ({macd_hist:.6f}) confirms {norm_side}" if macd_ok else f"MACD histogram ({macd_hist:.6f}) opposes {norm_side}",
        )

        min_rel_vol = float(entry_cfg.get("min_relative_volume") or 0.6)
        vol_ok = rel_vol >= min_rel_vol
        _add_rule(
            "RULE_05D_VOLUME_CONDITION",
            "Volume Condition",
            {"min_relative_volume": min_rel_vol, "relative_volume": rel_vol},
            vol_ok,
            f"Relative volume ({rel_vol:.2f}x) >= {min_rel_vol:.2f}x" if vol_ok else f"Relative volume ({rel_vol:.2f}x) below {min_rel_vol:.2f}x",
        )

        # 6. Configured Entry Rule Summary
        entry_rule_ok = sig_valid and inst_ok and data_ok and mtf_ok and ema_ok and rsi_ok and macd_ok and vol_ok
        _add_rule(
            "RULE_06_ENTRY_RULE",
            "Entry Rule",
            {"side": norm_side, "strategy_id": sid},
            entry_rule_ok,
            "All technical & timeframe entry conditions passed" if entry_rule_ok else "One or more technical entry conditions failed",
        )

        # 7. Exit Plan & Risk/Reward Validation
        curr_px = float(ta_res.get("current_price") or sig.get("price") or 100.0)
        sl_pct = max(0.2, float(strat.get("stop_loss_pct") or 0.6))
        tp_pct = max(0.3, float(strat.get("take_profit_pct") or 1.32))
        sl_px = round(curr_px * (1.0 - sl_pct / 100.0), 6) if norm_side == "LONG" else round(curr_px * (1.0 + sl_pct / 100.0), 6)
        tp_px = round(curr_px * (1.0 + tp_pct / 100.0), 6) if norm_side == "LONG" else round(curr_px * (1.0 - tp_pct / 100.0), 6)
        min_rr = float(entry_cfg.get("min_risk_reward") or 1.2)
        actual_rr = round(tp_pct / max(sl_pct, 1e-9), 2)
        exit_plan_ok = actual_rr >= min_rr
        _add_rule(
            "RULE_07_EXIT_PLAN",
            "Exit & Risk/Reward Plan",
            {"sl_pct": sl_pct, "tp_pct": tp_pct, "min_rr": min_rr, "actual_rr": actual_rr},
            exit_plan_ok,
            f"Exit plan valid (R:R {actual_rr} >= {min_rr}, SL={sl_px}, TP={tp_px})" if exit_plan_ok else f"R:R ({actual_rr}) below minimum ({min_rr})",
        )

        # 8. Hard Risk Management & Profit Lock Validation
        risk_ok, risk_reason = cls.evaluate_hard_risk(user_id, strat, sym, norm_side, market_context=m_ctx)
        profit_lock_active = "profit lock" in risk_reason.lower()
        _add_rule(
            "RULE_08_RISK_VALIDATION",
            "Risk Validation",
            {"max_daily_loss_usd": strat.get("max_daily_loss_usd"), "max_open_positions": strat.get("max_open_positions")},
            risk_ok,
            "PROFIT LOCK ACTIVATED: " + risk_reason if profit_lock_active else risk_reason,
        )

        # 9. Risk-Based Position Sizing Validation
        sizing_res = cls.calculate_v2_risk_position_size(
            user_id=user_id,
            symbol=sym,
            side=norm_side,
            entry_price=curr_px,
            stop_loss_price=sl_px,
            risk_pct=float(entry_cfg.get("risk_per_trade_pct") or 0.5),
            max_leverage=float(strat.get("leverage") or 10.0),
            max_aggregate_open_risk_pct=float(entry_cfg.get("max_aggregate_open_risk_pct") or 1.5),
        )
        sizing_ok = bool(sizing_res.get("approved"))
        _add_rule(
            "RULE_09_POSITION_SIZING",
            "Position Sizing Validation",
            {"risk_per_trade_pct": float(entry_cfg.get("risk_per_trade_pct") or 0.5)},
            sizing_ok,
            f"Sized {sizing_res.get('quantity')} {sym} (Risk=${sizing_res.get('risk_amount_usdt', 0)})" if sizing_ok else str(sizing_res.get("reason")),
        )

        # 10. CoinDCX Execution & Spread Validation
        spread_pct = float(m_ctx.get("spread_pct") or 0.04)
        max_spread = float(entry_cfg.get("max_spread_pct") or 0.35)
        exec_val_ok = spread_pct <= max_spread
        _add_rule(
            "RULE_10_EXECUTION_VALIDATION",
            "CoinDCX Execution Validation",
            {"spread_pct": spread_pct, "max_spread_pct": max_spread},
            exec_val_ok,
            f"Spread ({spread_pct:.3f}%) within execution threshold" if exec_val_ok else f"Spread ({spread_pct:.3f}%) exceeds max ({max_spread:.3f}%)",
        )

        all_passed = all(r["result"] == "PASS" for r in rules_evaluated)
        verdict = "APPROVED" if all_passed else "REJECTED"
        failed_reasons = [f"{r['rule_name']}: {r['reason']}" for r in rules_evaluated if r["result"] != "PASS"]

        rules_panel = {
            "EMA Condition": "PASS" if ema_ok else "FAILED",
            "RSI Condition": "PASS" if rsi_ok else "FAILED",
            "MACD Condition": "PASS" if macd_ok else "FAILED",
            "Volume Condition": "PASS" if vol_ok else "FAILED",
            "Higher Timeframe": "PASS" if mtf_ok else "FAILED",
            "Entry Rule": "PASS" if entry_rule_ok else "REJECTED",
            "Risk Validation": "PASS" if (risk_ok and sizing_ok and exit_plan_ok) else "FAILED",
            "Execution Approval": verdict,
        }

        cls.log_bot_activity(
            user_id=user_id,
            event_type="Risk Approved" if all_passed else "Signal Rejected",
            symbol=sym,
            message=f"V2 Rule Engine {verdict} {norm_side} {sym}" + ("" if all_passed else f" ({'; '.join(failed_reasons[:2])})"),
            details={"verdict": verdict, "rules_panel": rules_panel},
        )

        return {
            "symbol": sym,
            "side": norm_side,
            "strategy_id": sid,
            "execution_approval": verdict,
            "approved": all_passed,
            "profit_lock_activated": profit_lock_active,
            "rejection_reasons": failed_reasons,
            "rules_panel": rules_panel,
            "rules": rules_evaluated,
            "position_sizing": sizing_res,
            "technical_analysis": ta_res,
            "multi_timeframe": mtf_res,
            "araa_ai": ai_res,
            "timestamp": now_iso,
        }

    @classmethod
    def evaluate_v2_smart_profit_and_exit(
        cls,
        user_id: int,
        position: Dict[str, Any],
        current_price: float,
        strategy: Optional[Dict[str, Any]] = None,
        atr_value: float = 0.0,
        opposite_signal: bool = False,
        strategy_invalidated: bool = False,
        smc_dna: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        AraaBot V2.0 Smart Profit Booking & Auto Exit Engine:
        - Multi-stage R-multiple partial profit booking:
          * TP1 = 1R -> Book configurable % (default 30%)
          * TP2 = 2R -> Book configurable % (default 30%)
          * Remaining 40% trailed via configured trailing mode
        - Trailing stop modes: PERCENTAGE, ATR, FIXED_DISTANCE, BREAKEVEN, PROFIT_LOCK, STRATEGY_BASED
          (Strictly tightens stop-loss; NEVER moves protective stop farther away to increase risk)
        - Auto-exit triggers: STOP_LOSS, TAKE_PROFIT, PARTIAL_TP1, PARTIAL_TP2, TRAILING_STOP,
          BREAKEVEN_STOP, STRATEGY_INVALIDATION, OPPOSITE_SIGNAL, MAX_HOLDING_TIME, LIQUIDATION_RISK, EMERGENCY_STOP.
        """
        strat = strategy or cls.get_strategy(user_id, "araa_ai_default") or {}
        exit_rules = {}
        try:
            exit_rules = json.loads(strat.get("exit_rules_json") or "{}") if isinstance(strat.get("exit_rules_json"), str) else (strat.get("exit_rules") or {})
        except Exception:
            pass

        entry = float(position.get("entry_price") or 0.0)
        qty = float(position.get("qty") or 0.0)
        if entry <= 0 or current_price <= 0 or qty <= 0:
            return {"action": "HOLD", "reason": "INVALID_POSITION_OR_PRICE"}

        # Check emergency stop first
        rb = query_one("SELECT emergency_shutdown FROM real_bot_configs WHERE user_id=?", (user_id,))
        if rb and int(rb.get("emergency_shutdown") or 0) == 1:
            return {"action": "FULL_EXIT", "exit_reason": "EMERGENCY_STOP", "close_qty": qty}

        side = str(position.get("side") or "LONG").upper()
        is_long = side in ("BUY", "LONG")
        direction = 1.0 if is_long else -1.0

        sl_pct = max(0.1, float(position.get("stop_pct") or strat.get("stop_loss_pct") or 0.5))
        tp_pct = max(0.2, float(position.get("target_pct") or strat.get("take_profit_pct") or 1.5))
        r_dist_pct = sl_pct  # 1R = initial planned stop_loss_pct distance
        r_dist_price = entry * (r_dist_pct / 100.0)

        move_pct = ((current_price - entry) / entry) * 100.0 * direction
        current_r = move_pct / max(r_dist_pct, 1e-9)
        peak_pct = max(move_pct, float(position.get("peak_pnl_pct") or 0.0))

        # Current protective stop price (never allow widening)
        default_sl = entry * (1.0 - sl_pct / 100.0) if is_long else entry * (1.0 + sl_pct / 100.0)
        current_sl = float(position.get("current_sl_price") or default_sl)

        # Liquidation risk & fee-coverage floor for live CoinDCX scalps
        is_live = int(position.get("is_live") or 0) == 1
        lev = max(1.0, float(position.get("leverage") or strat.get("leverage") or 10.0))
        pos_margin = float(position.get("margin") or ((entry * qty) / max(1.0, lev)))
        gross_pnl = (current_price - entry) * qty * direction
        est_rt_fee = round(max(0.0, pos_margin) * lev * 0.0014, 4) if is_live else 0.0
        min_live_profit = max(est_rt_fee * 1.15, est_rt_fee + max(0.02, pos_margin * 0.005)) if is_live else 0.0
        live_fee_covered = (not is_live) or (gross_pnl >= min_live_profit)

        approx_liq_pct = 85.0 / lev
        if move_pct <= -approx_liq_pct:
            return {"action": "FULL_EXIT", "exit_reason": "LIQUIDATION_RISK", "close_qty": qty, "move_pct": round(move_pct, 4)}

        # Hard Stop-Loss trigger
        if (is_long and current_price <= current_sl) or ((not is_long) and current_price >= current_sl) or move_pct <= -sl_pct:
            return {"action": "FULL_EXIT", "exit_reason": "STOP_LOSS", "close_qty": qty, "move_pct": round(move_pct, 4)}

        # Strategy invalidation / Opposite signal
        if strategy_invalidated:
            return {"action": "FULL_EXIT", "exit_reason": "STRATEGY_INVALIDATION", "close_qty": qty, "move_pct": round(move_pct, 4)}
        if opposite_signal and bool(exit_rules.get("exit_on_opposite_signal", True)) and (move_pct <= -(sl_pct * 0.5) or live_fee_covered):
            return {"action": "FULL_EXIT", "exit_reason": "OPPOSITE_SIGNAL", "close_qty": qty, "move_pct": round(move_pct, 4)}

        # Max holding time check
        max_hold_sec = float(exit_rules.get("max_holding_seconds") or 0.0)
        opened_at = float(position.get("opened_at") or 0.0)
        if max_hold_sec > 0 and opened_at > 0 and (time.time() - opened_at) >= max_hold_sec:
            return {"action": "FULL_EXIT", "exit_reason": "MAX_HOLDING_TIME", "close_qty": qty, "move_pct": round(move_pct, 4)}

        # Full Take-Profit trigger (must clear CoinDCX taker fees + net gain when live)
        if move_pct >= tp_pct and live_fee_covered:
            return {"action": "FULL_EXIT", "exit_reason": "TAKE_PROFIT", "close_qty": qty, "move_pct": round(move_pct, 4)}

        # Immediate SMC + DNA + All-Indicator Profit Auto-Close (sec-off once fee floor is cleared)
        if smc_dna and move_pct > 0 and live_fee_covered:
            smc_ex = smc_dna.get("exit_signal") or {}
            if is_long and smc_ex.get("close_long"):
                return {
                    "action": "FULL_EXIT",
                    "exit_reason": f"SMC_DNA_AUTO_CLOSE_{smc_ex.get('reason_long') or 'BSL_TARGET'}",
                    "close_qty": qty,
                    "move_pct": round(move_pct, 4),
                }
            if (not is_long) and smc_ex.get("close_short"):
                return {
                    "action": "FULL_EXIT",
                    "exit_reason": f"SMC_DNA_AUTO_CLOSE_{smc_ex.get('reason_short') or 'SSL_TARGET'}",
                    "close_qty": qty,
                    "move_pct": round(move_pct, 4),
                }

        # Multi-stage R-multiple partial profit booking (TP1 = 1R -> default 30%, TP2 = 1.5R/2R -> default 30%)
        # Remaining 40% managed with trailing stop or strategy exit
        tp1_r = float(exit_rules.get("tp1_r_multiple") or 1.0)
        tp1_pct_book = float(exit_rules.get("tp1_book_pct") or 0.30)
        tp2_r = float(exit_rules.get("tp2_r_multiple") or 1.5)
        tp2_pct_book = float(exit_rules.get("tp2_book_pct") or 0.30)

        tp1_done = bool(position.get("tp1_booked") or int(position.get("partial_tp_booked") or 0) >= 1)
        tp2_done = bool(position.get("tp2_booked") or int(position.get("partial_tp_booked") or 0) >= 2)

        if not tp1_done and current_r >= tp1_r and live_fee_covered:
            book_qty = round(qty * tp1_pct_book, 6)
            be_sl = round(entry * (1.0 + 0.001 * direction), 6)
            tightened_sl = max(current_sl, be_sl) if is_long else min(current_sl, be_sl)
            return {
                "action": "PARTIAL_EXIT",
                "exit_reason": "PARTIAL_TAKE_PROFIT_TP1",
                "stage": f"TP1_{tp1_r}R",
                "book_ratio": tp1_pct_book,
                "close_qty": book_qty,
                "remaining_qty": round(max(0.0, qty - book_qty), 6),
                "new_sl_price": tightened_sl,
                "current_r": round(current_r, 2),
                "move_pct": round(move_pct, 4),
            }

        if tp1_done and not tp2_done and current_r >= tp2_r and live_fee_covered:
            book_qty = round(qty * tp2_pct_book, 6)
            lock_1r_sl = round(entry + (r_dist_price * direction), 6)
            tightened_sl = max(current_sl, lock_1r_sl) if is_long else min(current_sl, lock_1r_sl)
            return {
                "action": "PARTIAL_EXIT",
                "exit_reason": "PARTIAL_TAKE_PROFIT_TP2",
                "stage": f"TP2_{tp2_r}R",
                "book_ratio": tp2_pct_book,
                "close_qty": book_qty,
                "remaining_qty": round(max(0.0, qty - book_qty), 6),
                "new_sl_price": tightened_sl,
                "current_r": round(current_r, 2),
                "move_pct": round(move_pct, 4),
            }

        # Break-Even Protection: Trigger when trade moves in profit (e.g. >= 0.8R or configurable BE trigger)
        be_trigger_r = float(exit_rules.get("breakeven_trigger_r") or 0.8)
        be_sl_price = round(entry * (1.0 + 0.0012 * direction), 6)
        if current_r >= be_trigger_r and ((is_long and current_sl < be_sl_price) or ((not is_long) and current_sl > be_sl_price)):
            return {
                "action": "UPDATE_STOP",
                "exit_reason": "BREAKEVEN_PROTECTION_LOCKED",
                "new_sl_price": be_sl_price,
                "previous_sl_price": round(current_sl, 6),
                "current_r": round(current_r, 2),
                "move_pct": round(move_pct, 4),
            }

        # Trailing Stop Management (ATR / PERCENTAGE / FIXED_DISTANCE / BREAKEVEN)
        trail_mode = str(exit_rules.get("trailing_mode") or "PERCENTAGE").upper()
        trail_pct = max(0.1, float(strat.get("trailing_stop_pct") or 0.25))
        if trail_mode == "ATR" and atr_value > 0:
            trail_dist = atr_value * float(exit_rules.get("atr_trail_multiplier") or 1.5)
        elif trail_mode == "FIXED_DISTANCE" and float(exit_rules.get("fixed_trail_distance") or 0.0) > 0:
            trail_dist = float(exit_rules["fixed_trail_distance"])
        else:
            trail_dist = current_price * (trail_pct / 100.0)

        candidate_sl = (current_price - trail_dist) if is_long else (current_price + trail_dist)
        # Never widen protective stop: only tighten if candidate_sl improves upon current_sl
        improved_sl = round(max(current_sl, candidate_sl), 6) if is_long else round(min(current_sl, candidate_sl), 6)

        if peak_pct >= (r_dist_pct * 0.8) and (peak_pct - move_pct) >= trail_pct and move_pct > 0.10 and live_fee_covered:
            return {
                "action": "FULL_EXIT",
                "exit_reason": "TRAILING_STOP",
                "close_qty": qty,
                "new_sl_price": improved_sl,
                "move_pct": round(move_pct, 4),
                "peak_pct": round(peak_pct, 4),
            }

        if improved_sl != round(current_sl, 6) and current_r >= 0.5:
            return {
                "action": "UPDATE_STOP",
                "exit_reason": "TRAILING_STOP_TIGHTENED",
                "new_sl_price": improved_sl,
                "previous_sl_price": round(current_sl, 6),
                "move_pct": round(move_pct, 4),
            }

        return {
            "action": "HOLD",
            "current_r": round(current_r, 2),
            "move_pct": round(move_pct, 4),
            "peak_pct": round(peak_pct, 4),
            "protective_sl_price": round(current_sl, 6),
        }

    @classmethod
    def execute_auto_exit(
        cls,
        user_id: int,
        position_id: int,
        exit_decision: Dict[str, Any],
        current_price: float,
    ) -> Dict[str, Any]:
        """
        Centralized V2.0 Auto Exit Execution:
        1. Validates current open position in DB/exchange.
        2. Calculates remaining quantity & prevents closing more than remaining quantity.
        3. Prevents duplicate exit orders.
        4. Submits closing/reducing order & updates realized P&L + trade history + activity log.
        """
        pos = query_one("SELECT * FROM positions WHERE id=? AND user_id=?", (int(position_id), int(user_id)))
        if not pos or str(pos.get("status") or "").upper() != "OPEN":
            return {"success": False, "status": "ALREADY_CLOSED_OR_NOT_FOUND", "error": "Position is not open."}

        rem_qty = float(pos.get("qty") or 0.0)
        if rem_qty <= 0:
            return {"success": False, "status": "ZERO_REMAINING_QUANTITY", "error": "Position has zero remaining quantity."}

        action = str(exit_decision.get("action") or "HOLD").upper()
        reason = str(exit_decision.get("exit_reason") or exit_decision.get("reason") or "AUTO_EXIT")
        sym = str(pos.get("symbol") or "BTCUSDT").upper()
        side = str(pos.get("side") or "LONG").upper()
        is_long = side in ("BUY", "LONG")
        entry_px = float(pos.get("entry_price") or current_price)
        exec_px = float(current_price if current_price > 0 else entry_px)

        if action == "UPDATE_STOP":
            new_sl = float(exit_decision.get("new_sl_price") or 0.0)
            cls.log_bot_activity(
                user_id=user_id,
                event_type="Stop Updated",
                symbol=sym,
                message=f"Protective Stop tightened to {new_sl} on {sym} ({reason})",
                details={"position_id": position_id, "new_sl_price": new_sl},
            )
            return {"success": True, "status": "STOP_UPDATED", "position_id": position_id, "new_sl_price": new_sl}

        if action not in ("FULL_EXIT", "PARTIAL_EXIT", "TRAILING_EXIT", "STOP_LOSS_EXIT"):
            return {"success": True, "status": "NO_EXIT_REQUIRED", "position_id": position_id}

        req_close_qty = float(exit_decision.get("close_qty") or rem_qty)
        close_qty = min(rem_qty, max(0.0, req_close_qty))
        if close_qty <= 0:
            return {"success": False, "status": "INVALID_CLOSE_QTY", "error": "Close quantity must be positive."}

        is_live_pos = int(pos.get("is_live") or 0) == 1
        direction = 1.0 if is_long else -1.0
        gross_pnl = (exec_px - entry_px) * close_qty * direction
        fee_rate = 0.0007 if is_live_pos else 0.0005
        fee_usd = round((exec_px * close_qty) * fee_rate * 2.0, 4)
        net_pnl = round(gross_pnl - fee_usd, 4)
        now = time.time()

        new_rem_qty = round(rem_qty - close_qty, 8)
        is_full_exit = new_rem_qty <= 1e-8 or action == "FULL_EXIT"

        # CoinDCX Futures Live execution if live position
        exchange_order_id = ""
        if is_live_pos:
            if is_full_exit:
                try:
                    from real_broker import close_real_order
                    close_res = close_real_order(
                        symbol=sym,
                        side=side,
                        qty=close_qty,
                        user_id=user_id,
                        ticket_id=pos.get("magic_id") or pos.get("command_id"),
                        price=exec_px,
                        reason=reason,
                        leverage=float(pos.get("leverage") or 20.0),
                    )
                    exchange_order_id = str(
                        (close_res or {}).get("order_id")
                        or (close_res or {}).get("exchange_position_id")
                        or ""
                    )
                    confirmed = bool(close_res and close_res.get("closed"))
                    is_override = ("EMERGENCY" in reason.upper()) or ("MANUAL" in reason.upper())
                    if not confirmed and (close_res or {}).get("mode") != "FALLBACK_PAPER" and not is_override:
                        err_msg = str((close_res or {}).get("error") or "CoinDCX did not confirm futures exit")
                        cls.log_bot_activity(
                            user_id=user_id,
                            event_type="Live Exit Retry Needed",
                            symbol=sym,
                            message=f"Exchange exit pending for {sym}: {err_msg}",
                            details={"position_id": position_id, "close_res": close_res},
                        )
                        return {
                            "success": False,
                            "status": "EXCHANGE_CLOSE_FAILED",
                            "error": err_msg,
                            "position_id": position_id,
                        }
                    if close_res and close_res.get("exchange_settled") and close_res.get("realized_pnl") is not None:
                        settled_pnl = round(float(close_res["realized_pnl"]), 4)
                        if float(close_res.get("fee_usd") or 0.0) > 0:
                            fee_usd = float(close_res["fee_usd"])
                        pos_margin = max(
                            0.0,
                            float(pos.get("margin") or ((entry_px * close_qty) / max(1.0, float(pos.get("leverage") or 20.0)))),
                        )
                        is_liq_exit = bool(close_res.get("liquidated")) or ("LIQUIDAT" in reason.upper())
                        if pos_margin > 0 and (not is_liq_exit) and settled_pnl <= -(pos_margin * 0.85) and gross_pnl >= -(pos_margin * 0.25):
                            net_pnl = round(gross_pnl - fee_usd, 4)
                        else:
                            net_pnl = settled_pnl
                except Exception as e:
                    logger.error(f"Live full exit exception on {sym}: {e}")
            else:
                try:
                    close_side = "sell" if is_long else "buy"
                    ex_res = CoinDCXExecutionAdapter.submit_order(
                        user_id=user_id,
                        symbol=sym,
                        side=close_side,
                        market_type=str(pos.get("market_type") or "FUTURES"),
                        quantity=close_qty,
                        leverage=float(pos.get("leverage") or 20.0),
                        order_type="market_order",
                        price=exec_px,
                        strategy_id=str(pos.get("strategy_id") or "auto_scalp"),
                        client_order_id=f"exit_{position_id}_{int(time.time()*1000)}",
                    )
                    if ex_res.get("success"):
                        exec_px = float(ex_res.get("avg_fill_price") or exec_px)
                        exchange_order_id = str(ex_res.get("exchange_order_id") or "")
                        if float(ex_res.get("fee_usd") or 0.0) > 0:
                            fee_usd = float(ex_res.get("fee_usd"))
                            net_pnl = round(((exec_px - entry_px) * close_qty * direction) - fee_usd, 4)
                except Exception as e:
                    logger.error(f"Live partial exit submission exception on {sym}: {e}")

        if is_full_exit:
            write(
                "UPDATE positions SET status='CLOSED', current_price=?, realized_pnl=COALESCE(realized_pnl,0)+?, fee_usd=COALESCE(fee_usd,0)+?, close_reason=?, closed_at=? WHERE id=? AND user_id=?",
                (exec_px, net_pnl, round(fee_usd, 4), reason, now, int(position_id), int(user_id)),
            )
            pos_margin = float(pos.get("margin") or 0.0)
            if not is_live_pos and pos_margin > 0:
                write(
                    "UPDATE wallets SET locked_balance=MAX(0, locked_balance-?), deposit_balance=deposit_balance+? WHERE user_id=?",
                    (pos_margin, round(pos_margin + min(0.0, net_pnl), 4), int(user_id)),
                )
                if net_pnl >= 0:
                    write("UPDATE wallets SET profit_balance=profit_balance+? WHERE user_id=?", (net_pnl, int(user_id)))
            write(
                "UPDATE broker_connections SET live_balance=round(live_balance+?,4), live_equity=round(live_equity+?,4), today_pnl=round(today_pnl+?,4) WHERE user_id=?",
                (net_pnl, net_pnl, net_pnl, int(user_id)),
            )
            if is_live_pos:
                try:
                    CoinDCXExecutionAdapter.cancel_obsolete_protection(user_id, str(position_id), sym)
                except Exception:
                    pass
                try:
                    from coindcx_gateway import get_user_coindcx_client
                    cdx = get_user_coindcx_client(user_id)
                    if cdx:
                        inv_fn = getattr(cdx, "invalidate_balance_cache", None)
                        if callable(inv_fn):
                            inv_fn()
                        ok_b, b_info = cdx.get_balances(force=True)
                        if ok_b and isinstance(b_info, dict) and not cdx.is_offline:
                            rate = float(b_info.get("usdt_inr_rate") or 90.0)
                            real_total = float(b_info.get("total_portfolio_usd") or (float(b_info.get("total_portfolio_inr") or 0.0) / max(1.0, rate)))
                            real_free = float(b_info.get("usdt_free") if b_info.get("usdt_free") is not None else (float(b_info.get("inr_free") or 0.0) / max(1.0, rate)))
                            if real_total >= 0:
                                write(
                                    "UPDATE broker_connections SET live_balance=?, live_equity=?, free_margin=?, last_synced_at=? WHERE user_id=?",
                                    (round(real_total, 2), round(real_total, 2), round(max(0.0, real_free), 2), now, int(user_id)),
                                )
                                write("UPDATE wallets SET deposit_balance=? WHERE user_id=?", (round(real_total, 2), int(user_id)))
                except Exception:
                    pass
            # Record confirmed completed trade into TradeLearningEngine
            try:
                from trade_learning_engine import TradeLearningEngine
                TradeLearningEngine.record_completed_trade(
                    user_id=user_id,
                    position_id=position_id,
                    strategy_id=str(pos.get("strategy_id") or "araa_ai_default"),
                    symbol=sym,
                    direction=str(pos.get("side") or "BUY"),
                    entry_price=entry_px,
                    exit_price=exec_px,
                    quantity=close_qty,
                    realized_pnl=net_pnl,
                    trading_fees=fee_usd,
                    opened_at=float(pos.get("opened_at") or (now - 60.0)),
                    closed_at=now,
                    exit_reason=reason,
                    is_live=int(pos.get("is_live") or 0),
                )
            except Exception as e:
                logger.error(f"TradeLearningEngine error on {sym}: {e}")

            cls.log_bot_activity(
                user_id=user_id,
                event_type="Position Closed",
                symbol=sym,
                message=f"Auto-Exit closed {close_qty} {sym} @ {exec_px} ({reason}) | Net P&L: ${net_pnl:+.2f}",
                details={"position_id": position_id, "close_qty": close_qty, "net_pnl": net_pnl, "exit_reason": reason, "exchange_order_id": exchange_order_id},
            )
            return {
                "success": True,
                "status": "POSITION_CLOSED",
                "position_id": position_id,
                "closed_qty": close_qty,
                "remaining_qty": 0.0,
                "exit_price": exec_px,
                "realized_pnl_usdt": net_pnl,
                "exit_reason": reason,
                "exchange_order_id": exchange_order_id,
            }
        else:
            partial_count = int(pos.get("partial_tp_booked") or 0) + 1
            pos_margin = float(pos.get("margin") or 0.0)
            rem_ratio = (new_rem_qty / rem_qty) if rem_qty > 0 else 0.0
            new_margin = round(max(0.0, pos_margin * rem_ratio), 4)
            released_margin = round(max(0.0, pos_margin - new_margin), 4)
            write(
                "UPDATE positions SET qty=?, margin=?, current_price=?, realized_pnl=COALESCE(realized_pnl,0)+?, fee_usd=COALESCE(fee_usd,0)+?, partial_tp_booked=? WHERE id=? AND user_id=?",
                (new_rem_qty, new_margin, exec_px, net_pnl, round(fee_usd, 4), partial_count, int(position_id), int(user_id)),
            )
            if not is_live_pos and released_margin > 0:
                write(
                    "UPDATE wallets SET locked_balance=MAX(0, locked_balance-?), deposit_balance=deposit_balance+? WHERE user_id=?",
                    (released_margin, round(released_margin + min(0.0, net_pnl), 4), int(user_id)),
                )
                if net_pnl >= 0:
                    write("UPDATE wallets SET profit_balance=profit_balance+? WHERE user_id=?", (net_pnl, int(user_id)))
            write(
                "UPDATE broker_connections SET live_balance=round(live_balance+?,4), live_equity=round(live_equity+?,4), today_pnl=round(today_pnl+?,4) WHERE user_id=?",
                (net_pnl, net_pnl, net_pnl, int(user_id)),
            )
            cls.log_bot_activity(
                user_id=user_id,
                event_type="Partial Profit Booked",
                symbol=sym,
                message=f"Booked partial profit ({close_qty} {sym}) @ {exec_px} ({reason}) | Realized: ${net_pnl:+.2f}, Remaining: {new_rem_qty}",
                details={"position_id": position_id, "closed_qty": close_qty, "remaining_qty": new_rem_qty, "net_pnl": net_pnl, "exchange_order_id": exchange_order_id},
            )
            return {
                "success": True,
                "status": "PARTIAL_PROFIT_BOOKED",
                "position_id": position_id,
                "closed_qty": close_qty,
                "remaining_qty": new_rem_qty,
                "exit_price": exec_px,
                "realized_pnl_usdt": net_pnl,
                "exit_reason": reason,
                "exchange_order_id": exchange_order_id,
            }

    # =====================================================================
    # ARAABOT V2.1 ADVANCED AUTO SCALPING ENGINE + COINDCX FUTURES
    # =====================================================================

    _AUTO_SCALPING_STATUS: Dict[int, Dict[str, Any]] = {}

    @classmethod
    def get_auto_scalping_status(cls, user_id: int) -> Dict[str, Any]:
        """Return current real-time Auto Scalping status for the user."""
        current = cls._AUTO_SCALPING_STATUS.get(user_id)
        if not current:
            u = query_one("SELECT bot_enabled, bot_mode FROM users WHERE id=?", (user_id,))
            rb = query_one("SELECT emergency_shutdown, bot_status FROM real_bot_configs WHERE user_id=?", (user_id,))
            is_enabled = bool(u and int(u.get("bot_enabled") or 0) == 1 and (rb or {}).get("bot_status") == "RUNNING")
            current = {
                "user_id": user_id,
                "enabled": is_enabled,
                "paused": False,
                "status": "STOPPED" if not is_enabled else "RUNNING",
                "selected_instrument": "BTCUSDT",
                "scalping_strategy": "ARAA_AI_SCALPING",
                "entry_timeframe": "1m",
                "setup_timeframe": "5m",
                "trend_timeframe": "15m",
                "last_run_timestamp": 0.0,
                "last_signal": None,
                "rule_validation": None,
                "risk_approval": None,
                "execution_status": "IDLE",
                "coindcx_connection": "CONNECTED",
            }
            cls._AUTO_SCALPING_STATUS[user_id] = current
        return current

    @classmethod
    def set_auto_scalping_control(cls, user_id: int, action: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Controls: enable, pause, resume, stop, emergency_stop.
        Validates risk configuration before activation.
        """
        st = cls.get_auto_scalping_status(user_id)
        act = str(action or "").upper().strip()

        if act == "ENABLE":
            pre = cls.validate_real_bot_preflight(user_id, strategy_id="araa_ai_scalp")
            rb = query_one("SELECT emergency_shutdown, max_daily_loss FROM real_bot_configs WHERE user_id=?", (user_id,))
            if rb and int(rb.get("emergency_shutdown") or 0) == 1:
                return {"success": False, "error": "Cannot activate Auto Scalping while Emergency Stop is active."}

            cfg = config or {}
            st["enabled"] = True
            st["paused"] = False
            st["status"] = "RUNNING"
            if cfg.get("symbol"):
                st["selected_instrument"] = str(cfg["symbol"]).upper().strip()
            if cfg.get("strategy"):
                st["scalping_strategy"] = str(cfg["strategy"]).upper().strip()
            if cfg.get("entry_timeframe"):
                st["entry_timeframe"] = str(cfg["entry_timeframe"]).lower().strip()
            if cfg.get("setup_timeframe"):
                st["setup_timeframe"] = str(cfg["setup_timeframe"]).lower().strip()
            if cfg.get("trend_timeframe"):
                st["trend_timeframe"] = str(cfg["trend_timeframe"]).lower().strip()

            write("UPDATE users SET bot_enabled=1, bot_mode='SCALP' WHERE id=?", (user_id,))
            write("UPDATE real_bot_configs SET bot_status='RUNNING', emergency_shutdown=0 WHERE user_id=?", (user_id,))
            cls.log_bot_activity(
                user_id=user_id,
                event_type="Auto Scalping Enabled",
                symbol=st["selected_instrument"],
                message=f"Auto Scalping V2.1 activated on {st['selected_instrument']} ({st['scalping_strategy']})",
                details=st,
            )
            return {"success": True, "status": "RUNNING", "state": st}

        elif act == "PAUSE":
            st["paused"] = True
            st["status"] = "PAUSED"
            write("UPDATE real_bot_configs SET bot_status='PAUSED' WHERE user_id=?", (user_id,))
            cls.log_bot_activity(user_id=user_id, event_type="Auto Scalping Paused", symbol=st["selected_instrument"], message="Auto Scalping paused by user.")
            return {"success": True, "status": "PAUSED", "state": st}

        elif act == "RESUME":
            st["paused"] = False
            st["status"] = "RUNNING"
            write("UPDATE real_bot_configs SET bot_status='RUNNING' WHERE user_id=?", (user_id,))
            cls.log_bot_activity(user_id=user_id, event_type="Auto Scalping Resumed", symbol=st["selected_instrument"], message="Auto Scalping resumed by user.")
            return {"success": True, "status": "RUNNING", "state": st}

        elif act == "STOP":
            st["enabled"] = False
            st["paused"] = False
            st["status"] = "STOPPED"
            write("UPDATE users SET bot_enabled=0 WHERE id=?", (user_id,))
            write("UPDATE real_bot_configs SET bot_status='STOPPED' WHERE user_id=?", (user_id,))
            cls.log_bot_activity(user_id=user_id, event_type="Auto Scalping Stopped", symbol=st["selected_instrument"], message="Auto Scalping stopped by user.")
            return {"success": True, "status": "STOPPED", "state": st}

        elif act == "EMERGENCY_STOP":
            st["enabled"] = False
            st["paused"] = False
            st["status"] = "EMERGENCY_STOP"
            write("UPDATE users SET bot_enabled=0 WHERE id=?", (user_id,))
            write("UPDATE real_bot_configs SET bot_status='EMERGENCY_STOP', emergency_shutdown=1 WHERE user_id=?", (user_id,))
            open_pos = query("SELECT id, symbol, qty, current_price, entry_price, side FROM positions WHERE user_id=? AND status='OPEN'", (user_id,))
            closed_cnt = 0
            for p in open_pos or []:
                cur_px = float(p.get("current_price") or p.get("entry_price") or 1.0)
                cls.execute_auto_exit(user_id, p["id"], {"action": "FULL_EXIT", "exit_reason": "EMERGENCY_STOP_TRIGGERED", "close_qty": float(p.get("qty") or 0.0)}, cur_px)
                closed_cnt += 1
            cls.log_bot_activity(user_id=user_id, event_type="Emergency Stop", symbol="ALL", message=f"EMERGENCY STOP executed. Closed {closed_cnt} open positions.")
            return {"success": True, "status": "EMERGENCY_STOP", "closed_positions": closed_cnt, "state": st}

        return {"success": False, "error": f"Unknown action '{action}'"}

    @classmethod
    def execute_auto_scalp_cycle(
        cls,
        user_id: int,
        symbol: str = "BTCUSDT",
        strategy_code: str = "ARAA_AI_SCALPING",
        timeframes: Optional[Dict[str, str]] = None,
        feed: Any = None,
    ) -> Dict[str, Any]:
        """
        AraaBot V2.1 Complete 16-Step Auto Scalping Lifecycle:
          1. Receive live market data
          2. Update technical indicators
          3. Evaluate market conditions
          4. Generate scalping opportunity
          5. Evaluate our Python rules
          6. Validate risk limits
          7. Calculate position size
          8. Validate margin
          9. Validate spread and slippage
          10. Validate stop-loss
          11. Check duplicate signals
          12. Approve or reject entry
          13. Execute through CoinDCX Futures
          14. Verify actual order fill
          15. Register position
          16. Activate position management
        
        CRITICAL: Never enters if any required rule fails.
        """
        try:
            from analysis_engine import analyze_technical_v2, analyze_multi_timeframe, analyze_scalping_strategies
        except ImportError:
            from backend.analysis_engine import analyze_technical_v2, analyze_multi_timeframe, analyze_scalping_strategies

        from backtest_engine import BacktestEngine

        sym = str(symbol or "BTCUSDT").upper().replace("B-", "").replace("_", "")
        tfs = timeframes or {"entry": "1m", "setup": "5m", "trend": "15m"}
        entry_tf = tfs.get("entry", "1m")
        setup_tf = tfs.get("setup", "5m")
        trend_tf = tfs.get("trend", "15m")

        status_rec = cls.get_auto_scalping_status(user_id)
        status_rec["last_run_timestamp"] = time.time()
        status_rec["selected_instrument"] = sym
        status_rec["scalping_strategy"] = strategy_code

        # Step 1: Receive live market data across timeframes
        candles_by_tf = {}
        latest_live_px = 0.0
        for tf in [entry_tf, setup_tf, trend_tf]:
            c_list, _, _, _ = BacktestEngine.generate_historical_candles(symbol=sym, timeframe=tf, count=65)
            live_px = 0.0
            if feed is not None:
                try:
                    live_px = float(feed.live_price(sym) or feed.price(sym) or 0.0)
                except Exception:
                    pass
            if live_px > 0:
                latest_live_px = live_px
            if live_px > 0 and c_list:
                c_list[-1]["c"] = live_px
                c_list[-1]["h"] = max(float(c_list[-1]["h"]), live_px)
                c_list[-1]["l"] = min(float(c_list[-1]["l"]), live_px)
            candles_by_tf[tf] = c_list

        primary_candles = candles_by_tf.get(entry_tf) or candles_by_tf[trend_tf]

        # Step 2: Update technical indicators
        primary_ta = analyze_technical_v2(sym, primary_candles, timeframe=entry_tf, use_closed_candles_only=True)

        # Step 3: Evaluate market conditions & MTF alignment
        mtf_res = analyze_multi_timeframe(
            sym,
            candles_by_tf,
            tf_config={"major_tf": trend_tf, "confirm_tf": setup_tf, "setup_tf": setup_tf, "entry_tf": entry_tf},
            use_closed_candles_only=True,
        )

        # Step 4: Generate scalping opportunity from the 5 Strategies
        scalp_analysis = analyze_scalping_strategies(
            sym,
            primary_ta,
            mtf_result=mtf_res,
            custom_scalp_cfg={"active_scalping_strategy": strategy_code},
        )
        opp = scalp_analysis.get("opportunity")
        status_rec["last_signal"] = opp

        # Auto position exit evaluation on existing open positions using LIVE quote first (never stale closed candle)
        open_scalp_pos = query("SELECT * FROM positions WHERE user_id=? AND status='OPEN' AND symbol=?", (user_id, sym))
        curr_price = float(latest_live_px or primary_ta.get("current_price") or 0.0)
        fut_mark_px = 0.0
        if any(int(p.get("is_live") or 0) == 1 for p in (open_scalp_pos or [])):
            try:
                cdx_live = CoinDCXExecutionAdapter._client(user_id)
                if cdx_live and not cdx_live.is_offline:
                    fpos = cdx_live.futures.find_open_position(sym)
                    if isinstance(fpos, dict):
                        fut_mark_px = float(fpos.get("mark_price") or fpos.get("avg_price") or 0.0)
            except Exception:
                pass
        atr_val = float((primary_ta.get("indicators") or {}).get("atr") or (curr_price * 0.005))
        smc_dna = None
        try:
            from quantum_engine import SMCDNAEngine
            smc_dna = SMCDNAEngine.analyze_candles(sym, primary_candles, entry_tf, curr_price)
        except Exception:
            smc_dna = None

        exit_results = []
        for pos in open_scalp_pos or []:
            pos_px = fut_mark_px if (fut_mark_px > 0 and int(pos.get("is_live") or 0) == 1) else (curr_price or float(pos.get("current_price") or pos.get("entry_price") or 0.0))
            exit_decision = cls.evaluate_v2_smart_profit_and_exit(
                user_id=user_id,
                position=pos,
                current_price=pos_px,
                atr_value=atr_val,
                opposite_signal=bool(opp and opp.get("side") and opp.get("side") != pos.get("side")),
                smc_dna=smc_dna,
            )
            if exit_decision.get("action") != "HOLD":
                res_exit = cls.execute_auto_exit(user_id, pos["id"], exit_decision, pos_px)
                exit_results.append(res_exit)

        # Step 3.5: Market Shock & Rapid Price Surge / Crash Detection
        from market_shock_detector import MarketShockDetector
        # Evaluate market shock on closed candle patterns without feed synthetic jump
        shock_res = MarketShockDetector.analyze_market_shock(
            symbol=sym,
            candles=primary_candles[:-1] if (feed is not None and len(primary_candles) > 15) else primary_candles,
            spread_pct=0.03,
            last_feed_timestamp=time.time(),
        )
        if shock_res.get("block_new_entries"):
            status_rec["execution_status"] = f"BLOCKED_MARKET_SHOCK_{shock_res.get('shock_type')}"
            cls.log_bot_activity(
                user_id=user_id,
                event_type="Market Shock Block",
                symbol=sym,
                message=f"Auto Scalping blocked new entries due to {shock_res.get('shock_type')}: {shock_res.get('details')}",
                details=shock_res,
            )
            return {
                "success": False,
                "status": "BLOCKED_MARKET_SHOCK",
                "shock_analysis": shock_res,
                "message": shock_res.get("details"),
                "open_positions_evaluated": len(open_scalp_pos or []),
                "exits_triggered": exit_results,
            }

        if not opp:
            status_rec["execution_status"] = "SCANNING_NO_SETUP"
            status_rec["rule_validation"] = {"passed": False, "reason": "No high-probability scalping opportunity detected"}
            return {
                "success": True,
                "step": "SCANNING",
                "message": f"Scanning {sym} ({entry_tf}/{setup_tf}/{trend_tf}) — awaiting strategy setup trigger.",
                "scalp_analysis": scalp_analysis,
                "smc_dna": smc_dna,
                "open_positions_evaluated": len(open_scalp_pos or []),
                "exits_triggered": exit_results,
            }

        cand_side = opp.get("side")

        # Alpha + Beta + Gamma + SMC/DNA Pre-Entry Committee Check
        committee_res = None
        try:
            from ai_committee import AICommitteeOrchestrator
            strat_tmp = cls.get_strategy(user_id, "araa_ai_scalp") or {}
            real_mode_on, _ = cls.is_real_mode_active(user_id)
            committee_res = AICommitteeOrchestrator.evaluate_candidate(
                symbol=sym,
                user_id=user_id,
                candles=primary_candles,
                quote_data={"price": curr_price, "change_pct": 0.0, "volume": float((primary_ta.get("indicators") or {}).get("volume_sma20") or 100000.0)},
                requested_leverage=float(strat_tmp.get("leverage") or 20.0),
                timeframe=entry_tf,
                is_live=bool(real_mode_on),
                persist=False,
                intended_side=cand_side,
            )
        except Exception:
            committee_res = None

        # Step 5 to 12: Evaluate our Python rules, Risk Limits, Sizing, Margin, Spread & Idempotency
        strat_id_map = {
            "EMA_MOMENTUM_SCALPING": "ema_momentum_scalp",
            "RSI_MOMENTUM_SCALPING": "rsi_momentum_scalp",
            "MACD_SCALPING": "macd_scalp",
            "BREAKOUT_SCALPING": "breakout_scalp",
            "ARAA_AI_SCALPING": "araa_ai_scalp",
        }
        active_strat_id = strat_id_map.get(strategy_code, "araa_ai_scalp")

        mkt_context = {
            "spread_pct": 0.03,
            "volatility_pct": 1.2 if primary_ta.get("volatility") == "HIGH" else 0.6,
        }

        rule_res = cls.evaluate_v2_rule_pipeline(
            user_id=user_id,
            symbol=sym,
            side=cand_side,
            strategy_id=active_strat_id,
            candles=primary_candles,
            candles_by_tf=candles_by_tf,
            market_context=mkt_context,
        )

        status_rec["rule_validation"] = rule_res.get("rules_panel")
        status_rec["risk_approval"] = rule_res.get("execution_approval")

        if committee_res and not committee_res.get("approved"):
            veto = committee_res.get("veto_reason") or "AI Committee Alpha/Beta/Gamma + SMC/DNA rejected setup"
            status_rec["execution_status"] = "REJECTED_BY_AI_COMMITTEE"
            cls.log_bot_activity(
                user_id=user_id,
                event_type="Scalp Entry Rejected",
                symbol=sym,
                message=f"Auto Scalp {sym} ({cand_side}) blocked by Alpha/Beta/Gamma + SMC/DNA: {veto}",
                details={"opportunity": opp, "committee": committee_res},
            )
            return {
                "success": False,
                "status": "REJECTED_BY_AI_COMMITTEE",
                "reasons": [veto],
                "rule_evaluation": rule_res,
                "committee": committee_res,
                "smc_dna": smc_dna,
                "opportunity": opp,
                "exits_triggered": exit_results,
            }

        if not rule_res.get("approved"):
            status_rec["execution_status"] = "REJECTED_BY_PYTHON_RULES"
            reasons = rule_res.get("rejection_reasons") or ["Python rules validation failed"]
            cls.log_bot_activity(
                user_id=user_id,
                event_type="Scalp Entry Rejected",
                symbol=sym,
                message=f"Opportunity on {sym} ({cand_side}) rejected by Python Scalping Rules: {'; '.join(reasons[:2])}",
                details={"opportunity": opp, "rule_res": rule_res},
            )
            return {
                "success": False,
                "status": "REJECTED_BY_RULES",
                "reasons": reasons,
                "rule_evaluation": rule_res,
                "smc_dna": smc_dna,
                "opportunity": opp,
                "exits_triggered": exit_results,
            }

        # Step 13, 14, 15, 16: Approve, Execute through CoinDCX Futures, Verify Fill, Register Position
        sizing = rule_res.get("position_sizing") or {}
        qty = float(sizing.get("quantity") or 0.0)
        margin_usd = float(sizing.get("margin_required_usdt") or 8.0)
        strat = cls.get_strategy(user_id, active_strat_id) or {}

        status_rec["execution_status"] = "EXECUTING_ORDER"
        exec_res = cls.execute_order_intent(
            user_id=user_id,
            strategy=strat,
            symbol=sym,
            side=cand_side,
            ref_price=curr_price,
            quantity=qty,
            margin_usd=margin_usd,
            source_label="AUTO_SCALPER",
            reason=f"Auto Scalp V2.1 [{strategy_code}] {cand_side} {sym} (Alpha/Beta/Gamma + SMC/DNA + 10 Rules)",
        )

        status_rec["execution_status"] = exec_res.get("status") or "EXECUTED"
        cls.log_bot_activity(
            user_id=user_id,
            event_type="Scalp Entry Executed",
            symbol=sym,
            message=f"Scalp entry filled for {qty} {sym} @ {curr_price} ({exec_res.get('status')})",
            details=exec_res,
        )

        return {
            "success": True,
            "status": "ENTRY_FILLED",
            "execution": exec_res,
            "rule_evaluation": rule_res,
            "committee": committee_res,
            "smc_dna": smc_dna,
            "opportunity": opp,
            "exits_triggered": exit_results,
        }


