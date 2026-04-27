"""Simple publish/subscribe event bus for decoupled components."""

import logging
from collections.abc import Callable

from rtl_sdr_analyzer.detection.events import JammingEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[JammingEvent], None]


class EventBus:
    """In-memory pub/sub event bus for :class:`JammingEvent` objects."""

    def __init__(self) -> None:
        self._handlers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        """Register a handler to receive events."""
        if handler not in self._handlers:
            self._handlers.append(handler)
            logger.debug("Subscribed handler %s", handler.__name__)

    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove a previously registered handler."""
        if handler in self._handlers:
            self._handlers.remove(handler)
            logger.debug("Unsubscribed handler %s", handler.__name__)

    def publish(self, event: JammingEvent) -> None:
        """Dispatch an event to all subscribed handlers."""
        for handler in self._handlers:
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001
                logger.error("Event handler %s failed: %s", handler.__name__, exc)
