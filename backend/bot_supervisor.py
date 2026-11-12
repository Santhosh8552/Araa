"""
ARAA BOT V3 — MULTI-BOT SUPERVISOR & FLEET ORCHESTRATOR
Lifecycle management, multi-bot concurrency, fleet health monitoring,
cloning, configuration isolation, and performance comparison.
"""

import time
import uuid
import json
import logging
from typing import Dict, Any, List, Optional

from database import query, query_one, write, writes
from event_bus import get_event_bus, Events

logger = logging.getLogger("BOT_SUPERVISOR")


class BotLifecycleState:
    DRAFT = "DRAFT"
    BACKTESTING = "BACKTESTING"
    PAPER_TRADING = "PAPER_TRADING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
    ARCHIVED = "ARCHIVED"


class BotSupervisor:
    """Singleton fleet supervisor orchestrating multi-bot instances per customer."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(BotSupervisor, cls).__new__(cls)
        return cls._instance

    @classmethod
    def create_bot(cls, user_id: int, bot_name: str, strategy_id: Optional[str] = "QUANTUM_SCALP",
                   allocated_capital: float = 100.0, max_leverage: float = 20.0,
                   execution_mode: str = "PAPER", config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Creates a new isolated trading bot configuration."""
        bot_id = f"BOT-{str(uuid.uuid4())[:8].upper()}"
        now = time.time()
        cfg_dict = config or {
            "markets": ["CRYPTO"],
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "risk_per_trade_pct": 2.0,
            "max_open_positions": 5,
            "stop_loss_pct": 0.8,
            "take_profit_pct": 1.5,
            "timeframe": "1m",
            "direction": "BOTH"
        }

        write(
            "INSERT INTO trading_bots(bot_id, user_id, name, strategy_id, broker_code, symbol, timeframe, "
            "capital_allocated, risk_pct, leverage, max_positions, status, execution_mode, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, 'COINDCX', 'BTCUSDT', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (bot_id, user_id, bot_name, strategy_id, cfg_dict.get("timeframe", "1m"),
             allocated_capital, float(cfg_dict.get("risk_per_trade_pct", 2.0)), max_leverage,
             int(cfg_dict.get("max_open_positions", 5)), BotLifecycleState.DRAFT,
             execution_mode.upper(), now, now)
        )

        write(
            "INSERT INTO bot_configs(bot_id, parameters_json, custom_rules_json, tp_pct, sl_pct, trailing_stop_pct, updated_at) "
            "VALUES(?, ?, ?, ?, ?, 0.5, ?)",
            (bot_id, json.dumps(cfg_dict), "{}", float(cfg_dict.get("take_profit_pct", 1.5)),
             float(cfg_dict.get("stop_loss_pct", 0.8)), now)
        )

        cls.log_bot_event(bot_id, user_id, "BOT_CREATED", "INFO",
                          f"Bot '{bot_name}' ({bot_id}) created in state DRAFT with ${allocated_capital:.2f} capital.")

        return {
            "success": True,
            "bot_id": bot_id,
            "bot_name": bot_name,
            "status": BotLifecycleState.DRAFT,
            "allocated_capital": allocated_capital,
            "max_leverage": max_leverage,
            "execution_mode": execution_mode.upper(),
            "config": cfg_dict
        }

    @classmethod
    def start_bot(cls, bot_id: str, user_id: int) -> Dict[str, Any]:
        """Activates a trading bot into ACTIVE or PAPER_TRADING state."""
        bot = query_one("SELECT * FROM trading_bots WHERE bot_id=? AND user_id=?", (bot_id, user_id))
        if not bot:
            return {"success": False, "error": "Bot not found"}

        now = time.time()
        target_state = BotLifecycleState.ACTIVE if bot["execution_mode"] == "REAL" else BotLifecycleState.PAPER_TRADING

        write("UPDATE trading_bots SET status=?, last_heartbeat_at=?, updated_at=? WHERE bot_id=?",
              (target_state, now, now, bot_id))
        write("UPDATE users SET bot_enabled=1 WHERE id=?", (user_id,))

        cls.log_bot_event(bot_id, user_id, "BOT_STARTED", "INFO",
                          f"Bot '{bot['name']}' is now {target_state} on {bot['execution_mode']} mode.")

        get_event_bus().publish(Events.BOT_STARTED, bot_id=bot_id, user_id=user_id, mode=bot["execution_mode"])
        return {"success": True, "bot_id": bot_id, "status": target_state}

    @classmethod
    def pause_bot(cls, bot_id: str, user_id: int) -> Dict[str, Any]:
        """Pauses a trading bot without liquidating open positions."""
        bot = query_one("SELECT * FROM trading_bots WHERE bot_id=? AND user_id=?", (bot_id, user_id))
        if not bot:
            return {"success": False, "error": "Bot not found"}

        now = time.time()
        write("UPDATE trading_bots SET status=?, updated_at=? WHERE bot_id=?",
              (BotLifecycleState.PAUSED, now, bot_id))

        cls.log_bot_event(bot_id, user_id, "BOT_PAUSED", "WARNING",
                          f"Bot '{bot['name']}' paused by user.")

        get_event_bus().publish(Events.BOT_PAUSED, bot_id=bot_id, user_id=user_id)
        return {"success": True, "bot_id": bot_id, "status": BotLifecycleState.PAUSED}

    @classmethod
    def stop_bot(cls, bot_id: str, user_id: int, flush_positions: bool = True) -> Dict[str, Any]:
        """Stops bot completely and optionally liquidates open positions."""
        bot = query_one("SELECT * FROM trading_bots WHERE bot_id=? AND user_id=?", (bot_id, user_id))
        if not bot:
            return {"success": False, "error": "Bot not found"}

        now = time.time()
        write("UPDATE trading_bots SET status=?, updated_at=? WHERE bot_id=?",
              (BotLifecycleState.STOPPED, now, bot_id))

        flushed = 0
        if flush_positions:
            try:
                from bot_engine import Bot
                from price_feed import get_price_feed
                b = Bot(get_price_feed())
                _, flushed = b.close_all_for(user_id, reason=f"BOT_STOPPED_{bot_id}")
            except Exception as e:
                logger.warning(f"Error flushing positions for bot {bot_id}: {e}")

        cls.log_bot_event(bot_id, user_id, "BOT_STOPPED", "WARNING",
                          f"Bot '{bot['name']}' stopped. Flushed {flushed} positions.")

        get_event_bus().publish(Events.BOT_STOPPED, bot_id=bot_id, user_id=user_id, flushed_positions=flushed)
        return {"success": True, "bot_id": bot_id, "status": BotLifecycleState.STOPPED, "flushed_positions": flushed}

    @classmethod
    def clone_bot(cls, bot_id: str, user_id: int, new_name: Optional[str] = None) -> Dict[str, Any]:
        """Clones an existing bot's strategy and configuration."""
        bot = query_one("SELECT * FROM trading_bots WHERE bot_id=? AND user_id=?", (bot_id, user_id))
        if not bot:
            return {"success": False, "error": "Source bot not found"}

        cfg_row = query_one("SELECT parameters_json FROM bot_configs WHERE bot_id=?", (bot_id,))
        cfg_dict = json.loads(cfg_row["parameters_json"]) if cfg_row and cfg_row.get("parameters_json") else {}

        clone_name = new_name or f"{bot['name']} (Copy)"
        return cls.create_bot(
            user_id=user_id,
            bot_name=clone_name,
            strategy_id=bot.get("strategy_id"),
            allocated_capital=float(bot.get("capital_allocated") or 100.0),
            max_leverage=float(bot.get("leverage") or 20.0),
            execution_mode=bot.get("execution_mode", "PAPER"),
            config=cfg_dict
        )

    @classmethod
    def list_user_bots(cls, user_id: int) -> List[Dict[str, Any]]:
        """Returns all trading bots owned by user with their live metrics."""
        bots = query("SELECT * FROM trading_bots WHERE user_id=? ORDER BY created_at DESC", (user_id,))
        out = []
        for b in bots:
            cfg_row = query_one("SELECT parameters_json FROM bot_configs WHERE bot_id=?", (b["bot_id"],))
            cfg = json.loads(cfg_row["parameters_json"]) if cfg_row and cfg_row.get("parameters_json") else {}
            trades = query("SELECT realized_pnl FROM trades WHERE user_id=?", (user_id,))
            total_trades = len(trades)
            win_trades = sum(1 for t in trades if float(t["realized_pnl"] or 0) > 0)
            total_pnl = sum(float(t["realized_pnl"] or 0) for t in trades)
            win_rate = round((win_trades / total_trades * 100.0), 1) if total_trades > 0 else 0.0

            out.append({
                "bot_id": b["bot_id"],
                "bot_name": b["name"],
                "strategy_id": b["strategy_id"],
                "status": b["status"],
                "is_active": b["status"] in (BotLifecycleState.ACTIVE, BotLifecycleState.PAPER_TRADING),
                "allocated_capital": float(b.get("capital_allocated") or 0.0),
                "max_leverage": float(b.get("leverage") or 1.0),
                "execution_mode": b["execution_mode"],
                "total_trades": total_trades,
                "win_rate_pct": win_rate,
                "realized_pnl_usd": round(total_pnl, 2),
                "config": cfg,
                "created_at": b["created_at"],
                "updated_at": b["updated_at"]
            })
        return out

    @classmethod
    def log_bot_event(cls, bot_id: str, user_id: int, event_type: str,
                      level: str, message: str, details: Optional[Dict[str, Any]] = None):
        """Records an execution event into bot_execution_logs."""
        now = time.time()
        write(
            "INSERT INTO bot_execution_logs(bot_id, user_id, level, message, details_json, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (bot_id, user_id, level, f"[{event_type}] {message}", json.dumps(details or {}), now)
        )

    @classmethod
    def get_bot_logs(cls, bot_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        return query(
            "SELECT * FROM bot_execution_logs WHERE bot_id=? ORDER BY created_at DESC LIMIT ?",
            (bot_id, limit)
        )
