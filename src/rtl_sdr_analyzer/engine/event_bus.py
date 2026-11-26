"""Thread-safe publish/subscribe event bus for RF detection events."""

import logging
import threading
from collections.abc import Callable

from rtl_sdr_analyzer.detection.events import SignalEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[SignalEvent], None]


class EventBus:
    """In-memory pub/sub event bus for :class:`SignalEvent` objects."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handlers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        """Register a handler to receive confirmed signal events."""
        with self._lock:
            if handler not in self._handlers:
                self._handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove a previously registered handler."""
        with self._lock:
            if handler in self._handlers:
                self._handlers.remove(handler)

    def publish(self, event: SignalEvent) -> None:
        """Dispatch an event to all subscribed handlers."""
        with self._lock:
            handlers = list(self._handlers)
        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001
                name = getattr(handler, "__name__", repr(handler))
                logger.error("Event handler %s failed: %s", name, exc)
