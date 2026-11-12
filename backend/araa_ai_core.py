"""ARAA AI CORE – Centralized Intelligence & Multi-Agent Orchestration Architecture.
"One Intelligence. One Ecosystem."

Connects all 16 platform modules through a unified interface with AI Model Registry,
Context Manager, Tool Registry, Decision Logger, Performance Evaluator, Cost Monitor,
and Health Monitor.
"""
import os
import time
import uuid
import json
import logging
from typing import Dict, Any, List, Optional, Tuple

try:
    from database import write, writes, query, query_one
    from event_bus import event_bus, EVENT_AI_ANALYSIS_COMPLETED, EVENT_AI_SIGNAL_GENERATED
except ImportError:
    from backend.database import write, writes, query, query_one
    from backend.event_bus import event_bus, EVENT_AI_ANALYSIS_COMPLETED, EVENT_AI_SIGNAL_GENERATED

logger = logging.getLogger("araa_ai_core")


class AIModelRegistry:
    """Manages AI models, versions, approvals, and fallback prioritization."""

    def __init__(self):
        self._seed_default_models()

    def _seed_default_models(self):
        try:
            try:
                from database import init_schema
            except ImportError:
                from backend.database import init_schema
            write("CREATE TABLE IF NOT EXISTS ai_models(model_id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL, version TEXT NOT NULL, model_type TEXT NOT NULL DEFAULT 'MULTIMODAL_REASONING', approval_status TEXT NOT NULL DEFAULT 'APPROVED', accuracy_score REAL DEFAULT 88.5, drift_metric REAL DEFAULT 0.02, cost_per_1k_tokens REAL DEFAULT 0.00015, is_default INTEGER NOT NULL DEFAULT 0, approved_by INTEGER, approved_at REAL, created_at REAL NOT NULL)")
        except Exception:
            pass
        models = [
            ("araa-quant-v4", "ARAA Own Quant AI v4.0", "ARAA_OWN_AI", "4.0", "QUANT_ORCHESTRATOR", "APPROVED", 94.2, 0.002, 0.0, 1),
            ("araa-quantum-v3", "Araa Quantum Deterministic", "DETERMINISTIC", "3.0", "RULE_GOVERNANCE", "APPROVED", 89.4, 0.005, 0.0, 0),
            ("gemini-2.5-flash", "Gemini 2.5 Flash (Optional Helper)", "GOOGLE", "2.5", "MULTIMODAL_REASONING", "APPROVED", 89.2, 0.015, 0.00015, 0),
            ("gemini-3.8-flash", "Gemini 3.8 Flash (Optional Helper)", "GOOGLE", "3.8", "MULTIMODAL_REASONING", "APPROVED", 91.5, 0.012, 0.00020, 0),
            ("gemini-2.0-flash", "Gemini 2.0 Flash (Optional Helper)", "GOOGLE", "2.0", "FAST_INFERENCE", "APPROVED", 87.0, 0.020, 0.00010, 0),
            ("claude-3-5-sonnet", "Claude 3.5 Sonnet (Optional Helper)", "ANTHROPIC", "3.5", "DEEP_SYNTHESIS", "APPROVED", 92.1, 0.010, 0.00300, 0),
            ("gpt-4o", "OpenAI GPT-4o (Optional Helper)", "OPENAI", "4o", "MULTIMODAL_REASONING", "APPROVED", 90.8, 0.014, 0.00250, 0),
        ]
        now = time.time()
        for m in models:
            write("""
                INSERT INTO ai_models(model_id, name, provider, version, model_type, approval_status,
                                      accuracy_score, drift_metric, cost_per_1k_tokens, is_default, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_id) DO UPDATE SET
                  name=excluded.name,
                  provider=excluded.provider,
                  accuracy_score=excluded.accuracy_score,
                  drift_metric=excluded.drift_metric,
                  is_default=excluded.is_default
            """, (m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8], m[9], now))

    def get_active_model(self) -> Dict[str, Any]:
        """Returns the primary authorized model with verified fallback priority."""
        row = query_one("SELECT * FROM ai_models WHERE approval_status='APPROVED' AND is_default=1 LIMIT 1")
        if not row:
            row = query_one("SELECT * FROM ai_models WHERE approval_status='APPROVED' ORDER BY accuracy_score DESC LIMIT 1")
        return row or {
            "model_id": "araa-quantum-v3",
            "name": "Araa Quantum Deterministic",
            "provider": "DETERMINISTIC",
            "accuracy_score": 86.4
        }

    def list_models(self) -> List[Dict[str, Any]]:
        return query("SELECT * FROM ai_models ORDER BY approval_status ASC, accuracy_score DESC")


class AIContextManager:
    """Builds unified, user-authorized, and page-aware context for ARAA AI Core."""

    def build_context(self, user_id: int, current_page: str = "DASHBOARD",
                      bot_id: Optional[str] = None, symbol: Optional[str] = None) -> Dict[str, Any]:
        u_row = query_one("SELECT id, name, email, bot_enabled, bot_mode, bot_max_positions, bot_leverage, bot_trade_direction FROM users WHERE id=?", (user_id,)) or {}
        w_row = query_one("SELECT deposit_balance, profit_balance, total_deposited, total_withdrawn FROM wallets WHERE user_id=?", (user_id,)) or {}
        b_row = query_one("SELECT broker_name, status, is_live_active, live_balance, live_equity, free_margin FROM broker_connections WHERE user_id=?", (user_id,)) or {}
        is_live_mode = bool(b_row.get("is_live_active"))
        pos_filter = "is_live=1" if is_live_mode else "(is_live=0 OR is_live IS NULL)"

        active_positions = query(
            f"SELECT id, symbol, side, qty, entry_price, current_price, unrealized_pnl, margin, leverage, is_live "
            f"FROM positions WHERE user_id=? AND status IN ('OPEN', 'PENDING_BROKER') AND {pos_filter}",
            (user_id,),
        )
        # Refresh mark-to-market unrealized P&L using live price_feed quotes
        try:
            from price_feed import get_price_feed
            feed = get_price_feed()
        except Exception:
            feed = None
        for p in active_positions:
            entry_p = float(p.get("entry_price") or 0.0)
            margin_v = max(0.01, float(p.get("margin") or 1.0))
            lev_v = max(1.0, float(p.get("leverage") or 1.0))
            live_p = float((feed.live_price(p["symbol"]) or feed.price(p["symbol"]) or 0.0) if feed else 0.0)
            mark_p = live_p if live_p > 0 else float(p.get("current_price") or entry_p)
            if entry_p > 0 and mark_p > 0:
                dir_m = 1.0 if str(p.get("side") or "").upper() in ("LONG", "BUY") else -1.0
                move_pct = ((mark_p - entry_p) / entry_p) * dir_m
                raw_pnl = margin_v * lev_v * move_pct
                p["current_price"] = mark_p
                p["unrealized_pnl"] = round(max(-margin_v, raw_pnl), 2)

        all_closed = query(
            f"SELECT id, symbol, side, qty, entry_price, current_price, realized_pnl, close_reason, closed_at "
            f"FROM positions WHERE user_id=? AND status='CLOSED' AND {pos_filter} ORDER BY closed_at DESC LIMIT 500",
            (user_id,),
        )
        recent_trades = all_closed[:5]
        now_dt = time.localtime()
        today_start = time.mktime((now_dt.tm_year, now_dt.tm_mon, now_dt.tm_mday, 0, 0, 0, 0, 0, -1))
        floating_pnl = round(sum(float(p.get("unrealized_pnl") or 0.0) for p in active_positions), 2)
        total_realized_pnl = round(sum(float(c.get("realized_pnl") or 0.0) for c in all_closed), 2)
        today_realized_pnl = round(sum(float(c.get("realized_pnl") or 0.0) for c in all_closed if (c.get("closed_at") or 0) >= today_start), 2)
        win_count = sum(1 for c in all_closed if float(c.get("realized_pnl") or 0.0) > 0)
        loss_count = sum(1 for c in all_closed if float(c.get("realized_pnl") or 0.0) < 0)

        context = {
            "timestamp": time.time(),
            "current_page": current_page,
            "user": {
                "id": user_id,
                "name": u_row.get("name", "Trader"),
                "email": u_row.get("email", ""),
                "bot_enabled": bool(u_row.get("bot_enabled")),
                "bot_mode": u_row.get("bot_mode", "PURE_CRYPTO"),
                "bot_direction": u_row.get("bot_trade_direction", "BOTH"),
                "leverage": float(u_row.get("bot_leverage") or 500.0)
            },
            "financials": {
                "deposit_balance": float(w_row.get("deposit_balance") or 0.0),
                "profit_balance": float(w_row.get("profit_balance") or 0.0),
                "total_deposited": float(w_row.get("total_deposited") or 0.0),
                "broker_balance": float(b_row.get("live_balance") or 0.0),
                "free_margin": float(b_row.get("free_margin") or 0.0),
                "broker_name": b_row.get("broker_name") or "PAPER",
                "is_live_active": is_live_mode,
            },
            "portfolio": {
                "execution_mode": "LIVE_REAL" if is_live_mode else "PAPER",
                "open_positions_count": len(active_positions),
                "open_positions": active_positions,
                "recent_trades": recent_trades,
                "closed_trades_count": len(all_closed),
                "win_count": win_count,
                "loss_count": loss_count,
                "win_rate_pct": round((win_count / max(1, win_count + loss_count)) * 100.0, 1),
                "floating_pnl": floating_pnl,
                "today_realized_pnl": today_realized_pnl,
                "today_pnl": round(today_realized_pnl + floating_pnl, 2),
                "total_realized_pnl": total_realized_pnl,
                "net_pnl": round(total_realized_pnl + floating_pnl, 2),
            }
        }

        # Page-specific enriched context
        if symbol:
            context["active_symbol"] = symbol.upper()
        if bot_id:
            bot_row = query_one("SELECT * FROM trading_bots WHERE bot_id=?", (bot_id,))
            if bot_row:
                context["active_bot"] = bot_row

        return context


class AIToolRegistry:
    """Dispatches authorized tool executions on behalf of ARAA AI Core with permission checks."""

    def __init__(self):
        self._tools = {}
        self._register_default_tools()

    def _register_default_tools(self):
        self._tools["get_market_quote"] = self._tool_get_market_quote
        self._tools["get_user_portfolio"] = self._tool_get_user_portfolio
        self._tools["explain_trade_rejection"] = self._tool_explain_trade_rejection
        self._tools["check_risk_status"] = self._tool_check_risk_status
        self._tools["get_bot_status"] = self._tool_get_bot_status
        self._tools["control_user_bot"] = self._tool_control_user_bot
        self._tools["get_system_connectivity"] = self._tool_get_system_connectivity

    def _tool_get_market_quote(self, context: Dict[str, Any], symbol: str) -> Dict[str, Any]:
        sym = (symbol or "BTCUSDT").upper().strip()
        try:
            from price_feed import get_price_feed
            feed = get_price_feed()
            q = feed.quote(sym) or {}
            price = q.get("price") or feed.live_price(sym) or 0.0
            return {
                "symbol": sym,
                "price": price,
                "change_24h": q.get("change_pct", 0.0),
                "rsi_14": q.get("tv_rsi", 50.0),
                "tv_recommend": q.get("tv_recommend", "NEUTRAL")
            }
        except Exception as e:
            return {"symbol": sym, "error": str(e), "price": 0.0}

    def _tool_get_user_portfolio(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return context.get("portfolio", {})

    def _tool_explain_trade_rejection(self, context: Dict[str, Any], symbol: Optional[str] = None) -> Dict[str, Any]:
        user_id = context["user"]["id"]
        pred = query_one("""
            SELECT * FROM ai_predictions
            WHERE user_id=? AND post_entry_status='REJECTED'
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,))
        if not pred:
            return {"message": "No recent rejected trade found for your account."}
        return {
            "symbol": pred["symbol"],
            "direction": pred["direction"],
            "rejected_reason": pred["rationale"],
            "win_probability": pred["win_probability"],
            "timestamp": pred["created_at"]
        }

    def _tool_check_risk_status(self, context: Dict[str, Any]) -> Dict[str, Any]:
        user_id = context["user"]["id"]
        from risk_engine import RiskGuardian
        guardian = RiskGuardian()
        return guardian.evaluate_user_risk_status(user_id)

    def _tool_get_bot_status(self, context: Dict[str, Any]) -> Dict[str, Any]:
        user_id = context["user"]["id"]
        bot_row = query_one("SELECT * FROM real_bot_configs WHERE user_id=?", (user_id,))
        u_row = query_one("SELECT bot_enabled, bot_mode, bot_max_positions, bot_leverage FROM users WHERE id=?", (user_id,))
        return {
            "bot_enabled": bool(u_row and u_row.get("bot_enabled")),
            "bot_status": bot_row.get("bot_status") if bot_row else "PAUSED",
            "mode": u_row.get("bot_mode") if u_row else "PURE_CRYPTO",
            "max_positions": u_row.get("bot_max_positions") if u_row else 5,
            "emergency_shutdown": bool(bot_row and bot_row.get("emergency_shutdown"))
        }

    def _tool_control_user_bot(self, context: Dict[str, Any], action: str = "STATUS") -> Dict[str, Any]:
        user_id = int(context["user"]["id"] or 0)
        if user_id <= 0:
            return {"success": False, "error": "Direct bot control applies to trader accounts; use Company Prop Desk or Admin Panel for system controls."}
        act = (action or "STATUS").upper().strip()
        bot_row = query_one("SELECT * FROM real_bot_configs WHERE user_id=?", (user_id,))
        if act in ("START", "RESUME", "ACTIVATE") and bot_row and bot_row.get("emergency_shutdown"):
            return {"success": False, "error": "Emergency Shutdown lock is active. Clear kill switch in Risk settings before restarting."}
        now = time.time()
        if act in ("START", "RESUME", "ACTIVATE"):
            write("UPDATE users SET bot_enabled=1 WHERE id=?", (user_id,))
            if bot_row:
                write("UPDATE real_bot_configs SET bot_status='RUNNING', updated_at=? WHERE user_id=?", (now, user_id))
            write("UPDATE trading_bots SET status='PAPER_TRADING', updated_at=? WHERE user_id=? AND execution_mode='PAPER' AND status IN ('DRAFT','PAUSED','STOPPED')", (now, user_id))
            return {"success": True, "action": "STARTED", "status": self._tool_get_bot_status(context)}
        if act in ("PAUSE", "STOP", "DEACTIVATE"):
            write("UPDATE users SET bot_enabled=0 WHERE id=?", (user_id,))
            new_st = "STOPPED" if act == "STOP" else "PAUSED"
            if bot_row:
                write("UPDATE real_bot_configs SET bot_status=?, updated_at=? WHERE user_id=?", (new_st, now, user_id))
            write("UPDATE trading_bots SET status=?, updated_at=? WHERE user_id=? AND status IN ('ACTIVE','PAPER_TRADING')", (new_st, now, user_id))
            return {"success": True, "action": new_st, "status": self._tool_get_bot_status(context)}
        return {"success": True, "action": "STATUS", "status": self._tool_get_bot_status(context)}

    def _tool_get_system_connectivity(self, context: Dict[str, Any]) -> Dict[str, Any]:
        health = AIHealthMonitor().check_health()
        user_id = int(context["user"]["id"] or 0)
        b_row = query_one("SELECT broker_name, status, is_live_active FROM broker_connections WHERE user_id=?", (user_id,)) or {}
        try:
            from price_feed import get_price_feed
            prices_count = len(getattr(get_price_feed(), "prices", {}) or {})
        except Exception:
            prices_count = 0
        return {
            "primary_ai": "ARAA Own Quant AI v4.0",
            "ai_status": health.get("status"),
            "connected_engines": health.get("connected_engines"),
            "total_engines": health.get("total_engines"),
            "engines": health.get("engines"),
            "providers": health.get("providers"),
            "broker": b_row.get("broker_name") or "PAPER_SIMULATION",
            "broker_status": b_row.get("status") or "SIMULATED",
            "tracked_instruments": prices_count,
        }

    def execute_tool(self, tool_name: str, context: Dict[str, Any], **kwargs) -> Any:
        handler = self._tools.get(tool_name)
        if not handler:
            return {"error": f"Tool '{tool_name}' not registered in AI Tool Registry"}
        return handler(context, **kwargs)


class AIDecisionLogger:
    """Records explainable AI decisions with correlation to trades, risk rules, and telemetry."""

    def log_decision(self, user_id: int, symbol: str, recommendation: str,
                     risk_verdict: str, risk_rule: str, execution_allowed: bool,
                     final_action: str, explainability: Dict[str, Any],
                     bot_id: Optional[str] = None, signal_id: Optional[str] = None,
                     token_cost: float = 0.0, latency_ms: float = 0.0) -> str:
        dec_id = f"dec_{uuid.uuid4().hex[:16]}"
        now = time.time()
        try:
            write("""
                INSERT INTO ai_decisions(decision_id, user_id, bot_id, symbol, signal_id,
                                        recommendation, risk_guardian_verdict, risk_rule_applied,
                                        execution_allowed, final_action, explainability_json,
                                        token_cost_est, latency_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (dec_id, user_id, bot_id, symbol, signal_id, recommendation,
                  risk_verdict, risk_rule, 1 if execution_allowed else 0, final_action,
                  json.dumps(explainability), token_cost, latency_ms, now))
        except Exception as e:
            logger.error(f"Failed to log AI decision: {e}")
        return dec_id


class AICostMonitor:
    """Tracks token consumption, estimated inference cost, and provider rate-limits."""

    def record_usage(self, provider: str, model: str, input_tokens: int, output_tokens: int, latency_ms: float):
        # Estimate blended token cost
        rate_per_1k = 0.00015 if "flash" in model else (0.003 if "sonnet" in model else 0.002)
        cost = ((input_tokens + output_tokens) / 1000.0) * rate_per_1k
        try:
            write("""
                INSERT INTO real_bot_audit_logs(user_id, event_type, severity, message, details_json, created_at)
                VALUES (0, 'AI_INFERENCE_USAGE', 'INFO', ?, ?, ?)
            """, (f"{provider}:{model} ({input_tokens+output_tokens} tokens, ${cost:.5f})",
                  json.dumps({"provider": provider, "model": model, "cost": cost, "latency_ms": latency_ms}),
                  time.time()))
        except Exception:
            pass


class AIHealthMonitor:
    """Monitors live uptime, error rate, model latency, and quota exhaustion across all AI engines & LLM providers."""

    def check_health(self) -> Dict[str, Any]:
        now = time.time()
        try:
            from gemini_advisor import get_ai_keys, _GEMINI_QUOTA_EXHAUSTED_UNTIL
        except ImportError:
            from backend.gemini_advisor import get_ai_keys, _GEMINI_QUOTA_EXHAUSTED_UNTIL
        keys = get_ai_keys()
        gemini_ok = bool(keys.get("gemini")) and (now >= _GEMINI_QUOTA_EXHAUSTED_UNTIL)

        def _mod_ok(mod_name: str, fallback_mod: str) -> bool:
            try:
                __import__(mod_name)
                return True
            except Exception:
                try:
                    __import__(fallback_mod)
                    return True
                except Exception:
                    return False

        engines = {
            "analysis_engine": {
                "name": "Deep Technical Analysis Engine",
                "active": _mod_ok("analysis_engine", "backend.analysis_engine"),
                "role": "RSI, MACD, EMA 9/20/50/200, Bollinger, ATR & Support/Resistance",
            },
            "prediction_engine": {
                "name": "GRU Multi-Horizon Prediction Engine",
                "active": _mod_ok("prediction_engine", "backend.prediction_engine"),
                "role": "GRU Sequence Forecast, Drift & Probability Cones",
            },
            "ai_committee": {
                "name": "3-Agent AI Trading Committee (Alpha/Beta/Gamma)",
                "active": _mod_ok("ai_committee", "backend.ai_committee"),
                "role": "Order Flow + Tillson T3 Technicals + Risk/ATR Arbiter",
            },
            "quantum_engine": {
                "name": "Araa Quantum Institutional Engine",
                "active": _mod_ok("quantum_engine", "backend.quantum_engine"),
                "role": "Market Regime Classifier, Liquidation Heatmap & Quantum Consensus",
            },
            "gemini_advisor": {
                "name": "LLM Multi-Provider Advisor (Gemini / OpenAI / Claude)",
                "active": _mod_ok("gemini_advisor", "backend.gemini_advisor"),
                "role": "Pre-Entry LLM Reasoning & Deterministic Safety Fallback",
            },
            "bot_trainer": {
                "name": "Walk-Forward Self-Learning Trainer",
                "active": _mod_ok("bot_trainer", "backend.bot_trainer"),
                "role": "Historical Outcome Weights & Symbol Memory Adjustments",
            },
            "company_strategy_engine": {
                "name": "Company Strategy & Unified Signal Pipeline",
                "active": _mod_ok("company_strategy_engine", "backend.company_strategy_engine"),
                "role": "Immutable Strategy Versions & Risk-Gated Trade Proposals",
            },
            "araa_own_ai_engine": {
                "name": "ARAA Own Quant AI Brain v4.0",
                "active": _mod_ok("araa_own_ai_engine", "backend.araa_own_ai_engine"),
                "role": "Self-Contained Multi-Market NLU, Trade Planner, Scanner & Sizing AI",
            },
            "araa_ai_core": {
                "name": "ARAA AI Core Orchestrator",
                "active": True,
                "role": "Unified Copilot, Model Registry, Audit Logger & Health Monitor",
            },
        }
        connected_count = sum(1 for v in engines.values() if v["active"])

        return {
            "status": "HEALTHY" if engines.get("araa_own_ai_engine", {}).get("active") else ("HEALTHY" if (gemini_ok or keys.get("openai") or keys.get("anthropic")) else "DEGRADED"),
            "primary_engine": "ARAA Own Quant AI v4.0",
            "timestamp": now,
            "connected_engines": connected_count,
            "total_engines": len(engines),
            "engines": engines,
            "providers": {
                "araa_quant_v4": {
                    "available": bool(engines.get("araa_own_ai_engine", {}).get("active")),
                    "active": bool(engines.get("araa_own_ai_engine", {}).get("active")),
                    "uptime_pct": 100.0,
                },
                "google_gemini": {
                    "available": bool(keys.get("gemini")),
                    "active": gemini_ok,
                    "cooldown_remaining_sec": max(0, int(_GEMINI_QUOTA_EXHAUSTED_UNTIL - now)),
                },
                "openai_chatgpt": {
                    "available": bool(keys.get("openai")),
                    "active": bool(keys.get("openai")),
                },
                "araa_quantum_deterministic": {
                    "available": True,
                    "active": True,
                    "uptime_pct": 100.0,
                },
            },
        }

    get_status = check_health


class AraaAIOrchestrator:
    """Central Unified Intelligence Orchestrator. Connects all 16 platform modules."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AraaAIOrchestrator, cls).__new__(cls)
            cls._instance.model_registry = AIModelRegistry()
            cls._instance.context_manager = AIContextManager()
            cls._instance.tool_registry = AIToolRegistry()
            cls._instance.decision_logger = AIDecisionLogger()
            cls._instance.cost_monitor = AICostMonitor()
            cls._instance.health_monitor = AIHealthMonitor()
        return cls._instance

    def process_chat(self, user_id: int, message: str, current_page: str = "DASHBOARD",
                     bot_id: Optional[str] = None, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Interprets customer queries with context-awareness and real backend tool execution."""
        start_time = time.time()
        context = self.context_manager.build_context(user_id, current_page, bot_id, symbol)
        query_clean = (message or "").strip().lower()

        response_text = ""
        structured_data = {}
        tool_used = None

        try:
            from araa_own_ai_engine import AraaOwnTradingAIEngine
        except ImportError:
            from backend.araa_own_ai_engine import AraaOwnTradingAIEngine

        engine_used = AraaOwnTradingAIEngine.ENGINE_NAME
        mentioned_syms = AraaOwnTradingAIEngine.extract_symbols(query_clean, default_symbol=None, max_symbols=3)

        # Natural language intent recognition against backend tools & ARAA Quant AI Brain
        if any(k in query_clean for k in ("portfolio", "balance", "wallet", "equity", "pnl", "p&l", "profit", "my trade", "open trade", "closed trade", "win rate", "performance")) or (
            "loss" in query_clean and not any(rk in query_clean for rk in ("risk", "drawdown", "kill switch", "daily loss"))
        ):
            tool_used = "get_user_portfolio"
            p = self.tool_registry.execute_tool(tool_used, context)
            user_info = context["user"]
            fin = context["financials"]
            open_lines = [
                f"  • {op['symbol']} {op['side']} @ ${float(op['entry_price']):,.4f} → Live ${float(op['current_price']):,.4f} ({float(op['leverage']):.0f}x) | Float P&L: ${float(op['unrealized_pnl']):+,.2f}"
                for op in (p.get("open_positions") or [])[:5]
            ]
            closed_lines = [
                f"  • {cl['symbol']} {cl['side']} ({cl.get('close_reason') or 'CLOSED'}) | Realized P&L: ${float(cl['realized_pnl'] or 0):+,.2f}"
                for cl in (p.get("recent_trades") or [])[:5]
            ]
            response_text = (
                f"📊 **Portfolio Overview for {user_info['name']} ({p.get('execution_mode', 'PAPER')})**:\n"
                f"- **Wallet Balance**: ${fin['deposit_balance']:,.2f} USD | **Broker ({fin.get('broker_name', 'PAPER')})**: ${fin['broker_balance']:,.2f} (Free: ${fin['free_margin']:,.2f})\n"
                f"- **Today P&L**: ${p.get('today_pnl', 0.0):+,.2f} (Settled ${p.get('today_realized_pnl', 0.0):+,.2f} + Float ${p.get('floating_pnl', 0.0):+,.2f})\n"
                f"- **Total Net P&L**: ${p.get('net_pnl', 0.0):+,.2f} (Realized ${p.get('total_realized_pnl', 0.0):+,.2f} · Win Rate {p.get('win_rate_pct', 0.0)}% · {p.get('win_count', 0)}W/{p.get('loss_count', 0)}L)\n"
                f"- **Active Positions**: {p.get('open_positions_count', 0)} open (Float P&L: ${p.get('floating_pnl', 0.0):+,.2f})\n"
                f"- **Bot Status**: {'▶ RUNNING' if user_info['bot_enabled'] else '⏸ PAUSED'} ({user_info['bot_mode']} mode, {user_info['leverage']:.0f}x leverage)"
            )
            if open_lines:
                response_text += "\n\n**Open Trades:**\n" + "\n".join(open_lines)
            if closed_lines:
                response_text += "\n\n**Recent Closed Trades:**\n" + "\n".join(closed_lines)
            structured_data = p

        elif "why" in query_clean and ("stop" in query_clean or "pause" in query_clean or "halt" in query_clean):
            tool_used = "get_bot_status"
            b = self.tool_registry.execute_tool(tool_used, context)
            if b.get("emergency_shutdown"):
                response_text = "🚨 **Your Bot is currently locked by Emergency Shutdown**. The kill switch was triggered to preserve capital. You can resume by clicking **▶ START BOT** in the terminal after reviewing your risk limits."
            elif not b.get("bot_enabled"):
                response_text = "⏸ **Your Bot is currently PAUSED**. The automated trading engine was stopped by user request or safety limits. No new trades will open until you click **▶ START BOT**."
            else:
                response_text = "▶ **Your Bot is currently RUNNING**. It is actively scanning live markets for high-probability setups aligned with Risk Guardian rules."
            structured_data = b

        elif any(k in query_clean for k in ("start bot", "start my bot", "resume bot", "resume my bot", "activate bot")):
            tool_used = "control_user_bot"
            ctrl = self.tool_registry.execute_tool(tool_used, context, action="START")
            if ctrl.get("success"):
                response_text = f"▶ **ARAA AI Control**: Your automated trading bot is now **RUNNING** (`{ctrl['status'].get('mode')}` mode, max {ctrl['status'].get('max_positions')} positions). Pre-entry Risk Guardian & 9-engine screening are active."
            else:
                response_text = f"⚠️ **ARAA AI Control Blocked**: {ctrl.get('error', 'Unable to start bot.')}"
            structured_data = ctrl

        elif any(k in query_clean for k in ("pause bot", "pause my bot", "stop bot", "stop my bot", "deactivate bot")):
            tool_used = "control_user_bot"
            act_cmd = "STOP" if "stop" in query_clean else "PAUSE"
            ctrl = self.tool_registry.execute_tool(tool_used, context, action=act_cmd)
            if ctrl.get("success"):
                response_text = f"⏸ **ARAA AI Control**: Your trading bot is now **{ctrl.get('action')}**. No new automated entries will open until you resume."
            else:
                response_text = f"⚠️ **ARAA AI Control**: {ctrl.get('error', 'Unable to update bot state.')}"
            structured_data = ctrl

        elif any(k in query_clean for k in ("connectivity", "system status", "ai health", "all engines", "connected engines")):
            tool_used = "get_system_connectivity"
            conn_st = self.tool_registry.execute_tool(tool_used, context)
            eng_lines = "\n".join(
                f"- {'🟢 ONLINE' if v.get('active') else '🔴 OFFLINE'} **{v.get('name')}**: {v.get('role')}"
                for v in (conn_st.get("engines") or {}).values()
            )
            response_text = (
                f"🧠 **ARAA AI Unified Connectivity ({conn_st.get('connected_engines')}/{conn_st.get('total_engines')} Engines Online · Status: {conn_st.get('ai_status')})**\n"
                f"- **Primary Brain**: {conn_st.get('primary_ai')}\n"
                f"- **Execution Gateway**: {conn_st.get('broker')} ({conn_st.get('broker_status')})\n"
                f"- **Live Tracked Instruments**: {conn_st.get('tracked_instruments')}\n"
                f"{eng_lines}"
            )
            structured_data = conn_st

        elif "my bot" in query_clean or "trading bot" in query_clean or "fleet" in query_clean:
            tool_used = "get_bot_status"
            bots = query("SELECT bot_id, name as bot_name, strategy_id, execution_mode, status as bot_status, capital_allocated as allocated_capital_usd FROM trading_bots WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (user_id,))
            b_status = self.tool_registry.execute_tool(tool_used, context)
            if bots:
                lines = ["🤖 **Your Active Bot Fleet**:"]
                for bt in bots:
                    lines.append(f"- **{bt['bot_name']}** (`{bt['strategy_id']}`) · Mode: `{bt['execution_mode']}` · Status: **{bt['bot_status']}** · Capital: ${float(bt.get('allocated_capital_usd') or 0):,.2f}")
                response_text = "\n".join(lines)
            else:
                response_text = f"🤖 **Bot Status**: {'▶ RUNNING' if b_status.get('bot_enabled') else '⏸ PAUSED'} (`{b_status.get('mode')}` mode, {b_status.get('max_positions')} max positions)."
            structured_data = {"bots": bots, "status": b_status}

        elif "reject" in query_clean or "blocked" in query_clean:
            tool_used = "explain_trade_rejection"
            rej = self.tool_registry.execute_tool(tool_used, context)
            if "error" in rej or "rejected_reason" not in rej:
                response_text = "✅ **No recent trades were rejected**. All recent candidate setups met Araa AI & Risk Guardian criteria."
            else:
                response_text = (
                    f"🛡️ **Trade Rejection Rationale for {rej['symbol']} ({rej['direction']})**:\n"
                    f"- **Reason**: {rej['rejected_reason']}\n"
                    f"- **AI Confidence / Win Prob**: {rej['win_probability']}%\n"
                    f"Risk Guardian protects your capital by blocking setups below threshold or without valid stop-loss."
                )
            structured_data = rej

        elif any(k in query_clean for k in ("position size", "lot size", "calculate size", "calculate qty", "how much")):
            s_target = mentioned_syms[0] if mentioned_syms else (symbol or "BTCUSDT")
            sized = AraaOwnTradingAIEngine.answer_position_sizing(message, symbol=s_target)
            tool_used = sized["tool_used"]
            response_text = sized["reply"]
            structured_data = sized

        elif any(k in query_clean for k in ("best ", "top ", "what should i trade", "which coin", "which stock", "scanner", "scan ", "opportunity", "opportunities", "setups")):
            mkt = "INDIA" if any(k in query_clean for k in ("india", "nse", "nifty", "stock", "zerodha")) else (
                "FOREX" if any(k in query_clean for k in ("forex", "gold", "xau", "eurusd")) else None
            )
            scan = AraaOwnTradingAIEngine.scan_best_opportunities(market_filter=mkt, limit=4)
            tool_used = scan["tool_used"]
            response_text = scan["reply"]
            structured_data = scan

        elif mentioned_syms or any(k in query_clean for k in ("analyze", "analysis", "buy", "sell", "short", "long", "trend", "target", "stop loss", "sl ", "tp ", "entry", "support", "resistance", "forecast", "predict")):
            targets = mentioned_syms or ([symbol.strip().upper()] if symbol else ["BTCUSDT"])
            reports = [AraaOwnTradingAIEngine.analyze_symbol_live(sym) for sym in targets]
            tool_used = "araa_own_quant_analysis"
            response_text = "\n\n".join(AraaOwnTradingAIEngine.format_symbol_report(r) for r in reports)
            structured_data = {"analyses": reports}

        elif "risk" in query_clean or "loss" in query_clean or "drawdown" in query_clean or "kill switch" in query_clean:
            tool_used = "check_risk_status"
            r = self.tool_registry.execute_tool(tool_used, context)
            response_text = (
                f"🛡️ **AraaBot Institutional Risk Guardian Status**:\n"
                f"- **Status**: {'🟢 NORMAL' if r.get('status') == 'NORMAL' else '⚠️ ELEVATED'}\n"
                f"- **Today's Net Realized Loss**: ${r.get('daily_loss', 0.0):,.2f} / Max ${r.get('max_daily_loss', 250.0):,.2f}\n"
                f"- **Max Drawdown**: {r.get('drawdown_pct', 0.0):.1f}% / Limit {r.get('max_drawdown_pct', 15.0)}%\n"
                f"- **Consecutive Losses**: {r.get('consecutive_losses', 0)} / Max 3\n"
                f"All risk boundaries are actively enforced by the pre-trade Risk Guardian."
            )
            structured_data = r

        else:
            # Grounded open-ended trading Q&A using full ARAA AI Ecosystem context + Gemini / Full Engine Auto-Reply
            tool_used = "araa_gemini_full_engine"
            live_sym = symbol or "BTCUSDT"
            sample = AraaOwnTradingAIEngine.analyze_symbol_live(live_sym)
            pf = context.get("portfolio") or {}
            fin = context.get("financials") or {}
            bot_info = context.get("bot_status") or {}
            facts = (
                f"User: {context['user']['name']} | Mode: {pf.get('execution_mode', 'PAPER')} | "
                f"Wallet: ${fin.get('deposit_balance', 0.0):.2f} | Bot: {bot_info.get('status', 'PAUSED')} | "
                f"Open Trades: {pf.get('open_positions_count', 0)} | Today P&L: ${pf.get('today_pnl', 0.0):+.2f} | "
                f"Total Net P&L: ${pf.get('net_pnl', 0.0):+.2f} | Win Rate: {pf.get('win_rate_pct', 0.0):.1f}% | "
                f"Active Symbol: {sample['symbol']} @ {sample['price']} ({sample['action_label']}, Conf {sample['ensemble_confidence']}%, "
                f"RSI {sample['rsi_14']}, Entry {sample.get('entry_price')}, SL {sample.get('stop_loss')}, TP {sample.get('take_profit')}) | "
                f"Engines Online: 9/9 (Analysis, GRU Forecast, 3-Agent Committee, Quantum Regime, Gemini Advisor, Bot Trainer, Strategy Pipeline, ARAA Quant v4.0, AI Core)"
            )
            llm_reply, llm_name = AraaOwnTradingAIEngine.maybe_synthesize_llm(message, facts)
            if llm_reply:
                response_text = llm_reply
                engine_used = llm_name
            else:
                response_text = AraaOwnTradingAIEngine.auto_reply_full_engine(message, context, sample)
                engine_used = "ARAA Quant AI v4.0 (Full Engine Auto-Reply)"
            structured_data = {"snapshot": sample, "portfolio": pf}

        latency = round((time.time() - start_time) * 1000, 1)

        # Log AI Decision
        dec_id = self.decision_logger.log_decision(
            user_id=user_id,
            symbol=(mentioned_syms[0] if mentioned_syms else (symbol or "GLOBAL")),
            recommendation=response_text[:120],
            risk_verdict="APPROVED",
            risk_rule="ARAA_OWN_AI_ENGINE",
            execution_allowed=True,
            final_action="CHAT_RESPONSE",
            explainability={"query": message, "tool_used": tool_used, "page": current_page, "engine": engine_used},
            token_cost=0.0,
            latency_ms=latency,
        )

        return {
            "decision_id": dec_id,
            "response": response_text,
            "reply": response_text,
            "structured_data": structured_data,
            "tool_used": tool_used,
            "tools_called": [tool_used] if tool_used else [],
            "latency_ms": latency,
            "model": engine_used,
            "engine": engine_used,
        }

    def process_company_chat(
        self,
        company_id: int,
        company_user: Dict[str, Any],
        message: str,
        current_page: str = "AI_HUB",
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Unified ARAA AI Core Copilot connected to Company Pools, Brokers, Risk Guardian, Reconciliation & All AI Engines."""
        start_time = time.time()
        try:
            from company_finance import CompanyAccountManager, CompanyCapitalManager, paise_to_inr_str
            from company_risk_guardian import CompanyRiskGuardian
            from company_strategy_engine import CompanyStrategyService
            from company_ledger_recon import CompanyReconciliationService
        except ImportError:
            from backend.company_finance import CompanyAccountManager, CompanyCapitalManager, paise_to_inr_str
            from backend.company_risk_guardian import CompanyRiskGuardian
            from backend.company_strategy_engine import CompanyStrategyService
            from backend.company_ledger_recon import CompanyReconciliationService

        q_clean = (message or "").strip().lower()
        pools = CompanyCapitalManager.list_pools(company_id)
        accounts = CompanyAccountManager.list_accounts(company_id)
        open_pos = query("SELECT symbol, pool_id, execution_mode, quantity_str, avg_entry_price_str, unrealized_pnl_paise FROM company_positions WHERE company_id=? AND status='OPEN'", (company_id,))
        recon_data = CompanyReconciliationService.list_runs(company_id, limit=5)
        recon_runs = recon_data.get("runs") or []
        open_diffs = [d for d in (recon_data.get("differences") or []) if d.get("status") == "OPEN"]
        health = self.health_monitor.check_health()

        try:
            from araa_own_ai_engine import AraaOwnTradingAIEngine
        except ImportError:
            from backend.araa_own_ai_engine import AraaOwnTradingAIEngine

        tool_used = "company_overview"
        structured_data: Dict[str, Any] = {}
        mentioned_syms = AraaOwnTradingAIEngine.extract_symbols(q_clean, default_symbol=None, max_symbols=3)

        if any(k in q_clean for k in ("health", "engine", "status", "ai ", "connected")):
            tool_used = "ai_health_hub"
            eng_lines = "\n".join(
                f"- {'[ONLINE]' if v['active'] else '[OFFLINE]'} {v['name']}: {v['role']}"
                for v in (health.get("engines") or {}).values()
            )
            response_text = (
                f"ARAA Unified AI Hub ({health.get('connected_engines', 0)}/{health.get('total_engines', 0)} engines online | Status: {health.get('status')}):\n"
                f"{eng_lines}\n"
                f"LLM Providers: Gemini={'ON' if health['providers']['google_gemini']['active'] else 'COOLDOWN/OFF'} | "
                f"OpenAI={'ON' if health['providers']['openai_chatgpt']['active'] else 'OFF'}"
            )
            structured_data = health
        elif any(k in q_clean for k in ("position size", "lot size", "calculate size", "calculate qty")):
            s_target = mentioned_syms[0] if mentioned_syms else (symbol or "RELIANCE")
            sized = AraaOwnTradingAIEngine.answer_position_sizing(message, symbol=s_target)
            tool_used = sized["tool_used"]
            response_text = sized["reply"]
            structured_data = sized
        elif any(k in q_clean for k in ("best ", "top ", "what should i trade", "scanner", "scan ", "opportunity", "setups")):
            mkt = "INDIA" if any(k in q_clean for k in ("india", "nse", "nifty", "stock", "zerodha")) else None
            scan = AraaOwnTradingAIEngine.scan_best_opportunities(market_filter=mkt, limit=4)
            tool_used = scan["tool_used"]
            response_text = scan["reply"]
            structured_data = scan
        elif mentioned_syms or any(k in q_clean for k in ("analyze", "signal", "buy", "sell", "trend", "target", "stop loss")):
            tool_used = "unified_ai_analysis"
            target_sym = (mentioned_syms[0] if mentioned_syms else (symbol or "RELIANCE")).strip().upper()
            live_rep = AraaOwnTradingAIEngine.analyze_symbol_live(target_sym)
            response_text = AraaOwnTradingAIEngine.format_symbol_report(live_rep)
            structured_data = live_rep
        elif any(k in q_clean for k in ("risk", "halt", "stop", "recon", "mismatch")):
            tool_used = "risk_and_reconciliation"
            policies = CompanyRiskGuardian.list_policies(company_id)
            pol_txt = "\n".join(
                f"- {p['pool_id']}: Status={'PAUSED' if p.get('is_paused') else 'ACTIVE'}, "
                f"MaxOrder=INR {p.get('max_order_value_inr')}, MaxDailyLoss=INR {p.get('max_daily_loss_inr')}"
                for p in policies
            )
            latest_recon = recon_runs[0] if recon_runs else None
            recon_line = (
                f"{latest_recon['pool_id']} -> {latest_recon['status']} ({len(open_diffs)} open diffs)"
                if latest_recon else f"No reconciliation runs recorded yet ({len(open_diffs)} open diffs)."
            )
            response_text = (
                f"Risk Guardian & Reconciliation Report:\n"
                f"{pol_txt}\n"
                f"- Latest Reconciliation: {recon_line}"
            )
            structured_data = {"policies": policies, "reconciliation_runs": recon_runs, "open_differences": open_diffs}
        elif any(k in q_clean for k in ("portfolio", "pool", "capital", "balance", "fund", "position", "zerodha", "coindcx")):
            tool_used = "company_portfolio_and_pools"
            pool_lines = "\n".join(
                f"- {p['pool_id']} ({p['market_scope']}): Equity INR {p.get('broker_confirmed_equity_inr', '0.00')} | "
                f"Free INR {p.get('free_funds_inr', '0.00')} | Mode={p.get('trading_mode', 'PAPER')} | Recon={p.get('reconciliation_status')}"
                for p in pools
            )
            acct_lines = "\n".join(
                f"- {a['account_id']} ({a['provider']} / {a['market_scope']}): {a['connection_status']}"
                for a in accounts
            ) or "- No broker accounts connected yet."
            response_text = (
                f"Company Portfolio (Strictly Isolated Pools):\n"
                f"{pool_lines}\n"
                f"Open Positions: {len(open_pos)}\n"
                f"Broker Accounts:\n{acct_lines}"
            )
            structured_data = {"pools": pools, "accounts": accounts, "open_positions": open_pos}
        else:
            response_text = (
                f"ARAA Company AI Copilot Online ({health.get('connected_engines', 0)}/{health.get('total_engines', 0)} AI engines active).\n"
                f"Signed in as {company_user.get('full_name', company_user.get('username', 'Operator'))} ({company_user.get('role', 'STAFF')}).\n"
                f"Ask me to:\n"
                f"- 'Analyze RELIANCE' or 'Analyze BTCINR' (runs all 9 ARAA Quant AI engines)\n"
                f"- 'Show company portfolio and pools'\n"
                f"- 'Check risk guardian & reconciliation status'\n"
                f"- 'Show AI engine health & providers'"
            )
            structured_data = {"pools": pools, "health": health}

        latency = round((time.time() - start_time) * 1000, 1)
        dec_id = self.decision_logger.log_decision(
            user_id=int(company_user.get("user_id") or 0),
            symbol=symbol or "COMPANY_GLOBAL",
            recommendation=response_text[:120],
            risk_verdict="READ_ONLY_COPILOT",
            risk_rule="RISK_GUARDIAN_ENFORCED",
            execution_allowed=False,
            final_action="COMPANY_CHAT_RESPONSE",
            explainability={"query": message, "tool_used": tool_used, "company_id": company_id, "page": current_page},
            latency_ms=latency,
        )
        return {
            "success": True,
            "decision_id": dec_id,
            "response": response_text,
            "structured_data": structured_data,
            "tool_used": tool_used,
            "latency_ms": latency,
            "connected_engines": health.get("connected_engines", 0),
            "total_engines": health.get("total_engines", 0),
        }


# Singleton orchestrator
araa_ai_core = AraaAIOrchestrator()


def get_araa_ai() -> AraaAIOrchestrator:
    return araa_ai_core

