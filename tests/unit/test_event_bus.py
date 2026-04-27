"""Tests for EventBus."""

from datetime import datetime

from rtl_sdr_analyzer.detection.events import JammingEvent
from rtl_sdr_analyzer.orchestrator.event_bus import EventBus


class TestEventBus:
    def test_subscribe_and_publish(self) -> None:
        bus = EventBus()
        received: list[JammingEvent] = []

        def handler(event: JammingEvent) -> None:
            received.append(event)

        bus.subscribe(handler)
        event = JammingEvent(
            timestamp=datetime.now(),
            frequency=100.0,
            power=-50.0,
            bandwidth=1000.0,
            duration=1.0,
            confidence=2.0,
        )
        bus.publish(event)
        assert len(received) == 1
        assert received[0].frequency == 100.0

    def test_multiple_handlers(self) -> None:
        bus = EventBus()
        counts = [0, 0]

        def handler1(_event: JammingEvent) -> None:
            counts[0] += 1

        def handler2(_event: JammingEvent) -> None:
            counts[1] += 1

        bus.subscribe(handler1)
        bus.subscribe(handler2)
        event = JammingEvent(
            timestamp=datetime.now(),
            frequency=100.0,
            power=-50.0,
            bandwidth=1000.0,
            duration=1.0,
            confidence=2.0,
        )
        bus.publish(event)
        assert counts == [1, 1]

    def test_handler_exception_continues(self) -> None:
        bus = EventBus()
        received = False

        def bad_handler(_event: JammingEvent) -> None:
            raise RuntimeError("boom")

        def good_handler(_event: JammingEvent) -> None:
            nonlocal received
            received = True

        bus.subscribe(bad_handler)
        bus.subscribe(good_handler)
        event = JammingEvent(
            timestamp=datetime.now(),
            frequency=100.0,
            power=-50.0,
            bandwidth=1000.0,
            duration=1.0,
            confidence=2.0,
        )
        bus.publish(event)
        assert received is True

    def test_unsubscribe(self) -> None:
        bus = EventBus()
        received = False

        def handler(_event: JammingEvent) -> None:
            nonlocal received
            received = True

        bus.subscribe(handler)
        bus.unsubscribe(handler)
        event = JammingEvent(
            timestamp=datetime.now(),
            frequency=100.0,
            power=-50.0,
            bandwidth=1000.0,
            duration=1.0,
            confidence=2.0,
        )
        bus.publish(event)
        assert received is False
