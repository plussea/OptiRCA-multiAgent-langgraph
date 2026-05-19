"""Event-driven message bus for decoupled agent communication.

Provides publish/subscribe pattern for cross-agent communication,
replacing direct function calls between subgraphs with async events.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class EventType(Enum):
    """System event types."""
    ALERT_RECEIVED = "alert.received"
    PERCEPTION_COMPLETE = "perception.complete"
    DIAGNOSIS_STARTED = "diagnosis.started"
    DIAGNOSIS_COMPLETE = "diagnosis.complete"
    DIAGNOSIS_VALIDATED = "diagnosis.validated"
    DIAGNOSIS_REJECTED = "diagnosis.rejected"
    PLANNING_COMPLETE = "planning.complete"
    SOLUTION_GENERATED = "solution.generated"
    SOLUTION_VALIDATED = "solution.validated"
    SOLUTION_REJECTED = "solution.rejected"
    HUMAN_REVIEW_REQUESTED = "human.review.requested"
    HUMAN_DECISION_RECEIVED = "human.decision.received"
    CLOSURE_COMPLETE = "closure.complete"
    ERROR_OCCURRED = "error.occurred"
    STATE_CHANGED = "state.changed"


@dataclass
class Event:
    """Event message."""
    type: EventType
    session_id: str
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now())
    trace_id: Optional[str] = None
    source: Optional[str] = None


EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """Async event bus with typed subscribers and backpressure control."""

    def __init__(self, max_queue_size: int = 1000) -> None:
        self._subscribers: Dict[EventType, Set[EventHandler]] = {}
        self._event_queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=max_queue_size)
        self._running = False
        self._consumer_task: Optional[asyncio.Task] = None
        self._metrics: Dict[str, int] = {
            "published": 0,
            "delivered": 0,
            "dropped": 0,
            "errors": 0,
        }

    async def start(self) -> None:
        """Start the event consumer."""
        if self._running:
            return
        self._running = True
        self._consumer_task = asyncio.create_task(self._consume_events())
        logger.info("Event bus started")

    async def stop(self) -> None:
        """Stop the event consumer."""
        self._running = False
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        logger.info("Event bus stopped")

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = set()
        self._subscribers[event_type].add(handler)
        logger.debug(f"Handler subscribed to {event_type.value}")

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Unsubscribe from an event type."""
        if event_type in self._subscribers:
            self._subscribers[event_type].discard(handler)

    async def publish(self, event: Event) -> bool:
        """Publish an event to the bus."""
        try:
            self._event_queue.put_nowait(event)
            self._metrics["published"] += 1
            return True
        except asyncio.QueueFull:
            self._metrics["dropped"] += 1
            logger.warning(f"Event queue full, dropping {event.type.value}")
            return False

    async def _consume_events(self) -> None:
        """Consume and dispatch events."""
        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(), timeout=1.0
                )
                await self._dispatch(event)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._metrics["errors"] += 1
                logger.error(f"Event consumption error: {e}")

    async def _dispatch(self, event: Event) -> None:
        """Dispatch event to all subscribers."""
        handlers = self._subscribers.get(event.type, set())
        if not handlers:
            return

        # Run handlers concurrently with timeout
        tasks = [
            asyncio.wait_for(handler(event), timeout=30.0)
            for handler in handlers
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for handler, result in zip(handlers, results):
            if isinstance(result, Exception):
                self._metrics["errors"] += 1
                logger.error(
                    f"Handler {handler.__name__} failed for {event.type.value}: {result}"
                )
            else:
                self._metrics["delivered"] += 1

    def get_metrics(self) -> Dict[str, Any]:
        """Get event bus metrics."""
        return {
            **self._metrics,
            "queue_size": self._event_queue.qsize(),
            "subscriber_count": sum(len(h) for h in self._subscribers.values()),
        }


# Global event bus instance
event_bus = EventBus()
