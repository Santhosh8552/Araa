"""Centralized AraaBot StrategyEngine.

Owns all strategy evaluation, risk enforcement, TradingView Pine Script webhook
processing, Araa AI rule governance, and unified Paper vs Real Bot execution.
CoinDCX acts strictly as the permitted exchange execution layer via CoinDCXExecutionAdapter.
"""

import hmac
import json
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
]


class StrategyEngine:
    """Centralized strategy, risk, and execution orchestration engine."""

    SIGNAL_MAX_AGE_SECONDS = 120.0

    @classmethod
    def ensure_user_strategies(cls, user_id: int) -> List[Dict[str, Any]]:
        """Seed default strategies for a user if none exist yet, and return all strategies."""
        rows = query("SELECT * FROM strategy_configs WHERE user_id=? ORDER BY id ASC", (user_id,))
        if not rows:
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
        max_pos = max(1, min(20, int(cfg.get("max_open_positions", (existing or {}).get("max_open_positions", 3)))))
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
    ) -> Tuple[bool, str]:
        """Enforce hard risk controls that Araa AI can NEVER override."""
        rb = query_one("SELECT emergency_shutdown FROM real_bot_configs WHERE user_id=?", (user_id,))
        if rb and int(rb.get("emergency_shutdown") or 0) == 1:
            return False, "Emergency Stop is active. Reset Emergency Stop before trading."

        if not strategy or not int(strategy.get("enabled") or 0):
            return False, f"Strategy '{(strategy or {}).get('strategy_id', 'unknown')}' is disabled."

        allowed_dir = str(strategy.get("allowed_directions") or "BOTH").upper()
        norm_side = "LONG" if side.upper() in ("BUY", "LONG") else "SHORT"
        if allowed_dir == "LONG" and norm_side != "LONG":
            return False, f"Strategy '{strategy['strategy_id']}' only allows LONG entries."
        if allowed_dir == "SHORT" and norm_side != "SHORT":
            return False, f"Strategy '{strategy['strategy_id']}' only allows SHORT entries."
        if str(strategy.get("market_type") or "FUTURES").upper() == "SPOT" and norm_side == "SHORT":
            return False, "Spot market does not permit SHORT selling."

        open_cnt_row = query_one(
            "SELECT COUNT(*) AS c FROM positions WHERE user_id=? AND status IN ('OPEN','PENDING_BROKER')",
            (user_id,),
        )
        open_cnt = int((open_cnt_row or {}).get("c") or 0)
        max_pos = int(strategy.get("max_open_positions") or 3)
        if open_cnt >= max_pos:
            return False, f"Max open positions limit reached ({open_cnt}/{max_pos})."

        # Daily loss limit check (today UTC)
        day_start = time.time() - (time.time() % 86400)
        loss_row = query_one(
            "SELECT COALESCE(SUM(realized_pnl), 0.0) AS pnl FROM positions WHERE user_id=? AND status='CLOSED' AND closed_at>=?",
            (user_id, day_start),
        )
        today_pnl = float((loss_row or {}).get("pnl") or 0.0)
        max_daily_loss = float(strategy.get("max_daily_loss_usd") or 15.0)
        if today_pnl <= -abs(max_daily_loss):
            return False, f"Max daily loss limit reached (${today_pnl:.2f} <= -${max_daily_loss:.2f})."

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
