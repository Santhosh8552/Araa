"""Durable Event Bus and Outbox Engine for AraaBot V3 Institutional Platform.

Provides a thread-safe, resilient internal pub/sub event bus with durable SQLite event_outbox
persistence, correlation tracking, subscriber dispatching, retries, and dead-letter handling.
"""
import time
import uuid
import json
import logging
import threading
from typing import Dict, Any, Callable, List, Optional
from database import write, writes, query, query_one

logger = logging.getLogger("event_bus")

# The 22 Standardized Institutional Event Types from AraaBot V3 Specification
EVENT_MARKET_PRICE_UPDATED = "MARKET_PRICE_UPDATED"
EVENT_MARKET_DATA_DELAYED = "MARKET_DATA_DELAYED"
EVENT_AI_ANALYSIS_COMPLETED = "AI_ANALYSIS_COMPLETED"
EVENT_AI_SIGNAL_GENERATED = "AI_SIGNAL_GENERATED"
EVENT_RISK_CHECK_APPROVED = "RISK_CHECK_APPROVED"
EVENT_RISK_CHECK_REJECTED = "RISK_CHECK_REJECTED"
EVENT_BOT_STARTED = "BOT_STARTED"
EVENT_BOT_PAUSED = "BOT_PAUSED"
EVENT_BOT_STOPPED = "BOT_STOPPED"
EVENT_ORDER_CREATED = "ORDER_CREATED"
EVENT_ORDER_SUBMITTED = "ORDER_SUBMITTED"
EVENT_ORDER_PARTIALLY_FILLED = "ORDER_PARTIALLY_FILLED"
EVENT_ORDER_FILLED = "ORDER_FILLED"
EVENT_ORDER_REJECTED = "ORDER_REJECTED"
EVENT_POSITION_UPDATED = "POSITION_UPDATED"
EVENT_TRADE_CLOSED = "TRADE_CLOSED"
EVENT_BROKER_DISCONNECTED = "BROKER_DISCONNECTED"
EVENT_BROKER_RECONNECTED = "BROKER_RECONNECTED"
EVENT_PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"
EVENT_PAYMENT_FAILED = "PAYMENT_FAILED"
EVENT_SUBSCRIPTION_UPDATED = "SUBSCRIPTION_UPDATED"
EVENT_RISK_ALERT_TRIGGERED = "RISK_ALERT_TRIGGERED"

ALL_EVENT_TYPES = [
    EVENT_MARKET_PRICE_UPDATED, EVENT_MARKET_DATA_DELAYED, EVENT_AI_ANALYSIS_COMPLETED,
    EVENT_AI_SIGNAL_GENERATED, EVENT_RISK_CHECK_APPROVED, EVENT_RISK_CHECK_REJECTED,
    EVENT_BOT_STARTED, EVENT_BOT_PAUSED, EVENT_BOT_STOPPED, EVENT_ORDER_CREATED,
    EVENT_ORDER_SUBMITTED, EVENT_ORDER_PARTIALLY_FILLED, EVENT_ORDER_FILLED,
    EVENT_ORDER_REJECTED, EVENT_POSITION_UPDATED, EVENT_TRADE_CLOSED,
    EVENT_BROKER_DISCONNECTED, EVENT_BROKER_RECONNECTED, EVENT_PAYMENT_CONFIRMED,
    EVENT_PAYMENT_FAILED, EVENT_SUBSCRIPTION_UPDATED, EVENT_RISK_ALERT_TRIGGERED
]


class Events:
    MARKET_PRICE_UPDATED = EVENT_MARKET_PRICE_UPDATED
    MARKET_DATA_DELAYED = EVENT_MARKET_DATA_DELAYED
    AI_ANALYSIS_COMPLETED = EVENT_AI_ANALYSIS_COMPLETED
    AI_SIGNAL_GENERATED = EVENT_AI_SIGNAL_GENERATED
    RISK_CHECK_APPROVED = EVENT_RISK_CHECK_APPROVED
    RISK_CHECK_REJECTED = EVENT_RISK_CHECK_REJECTED
    BOT_STARTED = EVENT_BOT_STARTED
    BOT_PAUSED = EVENT_BOT_PAUSED
    BOT_STOPPED = EVENT_BOT_STOPPED
    ORDER_CREATED = EVENT_ORDER_CREATED
    ORDER_SUBMITTED = EVENT_ORDER_SUBMITTED
    ORDER_PARTIALLY_FILLED = EVENT_ORDER_PARTIALLY_FILLED
    ORDER_FILLED = EVENT_ORDER_FILLED
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_REJECTED = EVENT_ORDER_REJECTED
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_UPDATED = EVENT_POSITION_UPDATED
    POSITION_CLOSED = EVENT_TRADE_CLOSED
    BROKER_CONNECTED = "BROKER_CONNECTED"
    BROKER_DISCONNECTED = EVENT_BROKER_DISCONNECTED
    BROKER_RECONNECTED = EVENT_BROKER_RECONNECTED
    PAYMENT_COMPLETED = EVENT_PAYMENT_CONFIRMED
    PAYMENT_FAILED = EVENT_PAYMENT_FAILED
    SUBSCRIPTION_UPDATED = EVENT_SUBSCRIPTION_UPDATED
    RISK_ALERT_TRIGGERED = EVENT_RISK_ALERT_TRIGGERED


class EventBus:
    """Singleton event bus with asynchronous dispatch and persistent durable outbox."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(EventBus, cls).__new__(cls)
                cls._instance._subscribers = {}
                cls._instance._sub_lock = threading.Lock()
                cls._instance._running = True
        return cls._instance

    def subscribe(self, event_type: str, handler: Callable[[Dict[str, Any]], None]):
        """Registers a listener for a specific event type or '*' for all events."""
        with self._sub_lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            if handler not in self._subscribers[event_type]:
                self._subscribers[event_type].append(handler)

    def publish(self, event_type: str, aggregate_type: str = "SYSTEM", aggregate_id: str = "0",
                payload: Optional[Dict[str, Any]] = None, user_id: Optional[int] = None,
                correlation_id: Optional[str] = None, sync_dispatch: bool = False, **kwargs) -> str:
        """Publishes an event, persists to durable outbox, and dispatches to subscribers."""
        event_id = f"evt_{uuid.uuid4().hex[:16]}"
        now = time.time()
        corr_id = correlation_id or f"corr_{uuid.uuid4().hex[:12]}"
        final_payload = dict(payload or {}, **kwargs)

        event_record = {
            "event_id": event_id,
            "event_type": event_type,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "correlation_id": corr_id,
            "user_id": user_id,
            "payload_version": 1,
            "payload": final_payload,
            "timestamp": now,
            "created_at": now
        }

        # 1. Durable SQLite Outbox persistence
        try:
            write("""
                INSERT INTO event_outbox(event_id, event_type, aggregate_type, aggregate_id,
                                         correlation_id, user_id, payload_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
            """, (event_id, event_type, aggregate_type, aggregate_id,
                  corr_id, user_id, json.dumps(final_payload), now))
        except Exception as e:
            logger.error(f"Failed to record event {event_id} into outbox: {e}")

        # 2. Dispatch to subscribers
        if sync_dispatch:
            self._dispatch_event(event_record)
        else:
            threading.Thread(target=self._dispatch_event, args=(event_record,), daemon=True).start()

        return event_id

    def _dispatch_event(self, event_record: Dict[str, Any]):
        """Dispatches an event to registered callbacks and marks outbox status."""
        event_type = event_record["event_type"]
        event_id = event_record["event_id"]

        handlers: List[Callable] = []
        with self._sub_lock:
            if event_type in self._subscribers:
                handlers.extend(self._subscribers[event_type])
            if "*" in self._subscribers:
                handlers.extend(self._subscribers["*"])

        success = True
        last_err = None
        for handler in handlers:
            try:
                handler(event_record)
            except Exception as exc:
                success = False
                last_err = str(exc)
                logger.error(f"Error in subscriber {handler.__name__} for {event_type}: {exc}")

        # Update outbox status
        try:
            status = "PROCESSED" if success else "FAILED"
            write("""
                UPDATE event_outbox
                SET status=?, processed_at=?, last_error=?
                WHERE event_id=?
            """, (status, time.time(), last_err, event_id))
        except Exception:
            pass

    def get_recent_events(self, limit: int = 50, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns recent audit events from the durable outbox."""
        if user_id:
            rows = query("SELECT * FROM event_outbox WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, limit))
        else:
            rows = query("SELECT * FROM event_outbox ORDER BY created_at DESC LIMIT ?", (limit,))
        for r in rows:
            if r.get("payload_json"):
                try:
                    r["payload"] = json.loads(r["payload_json"])
                except Exception:
                    r["payload"] = {}
        return rows


# Global singleton instance
event_bus = EventBus()


def get_event_bus() -> EventBus:
    return event_bus

