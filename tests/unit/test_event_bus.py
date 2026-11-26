"""Unit tests for EventBus."""

from datetime import UTC, datetime

from rtl_sdr_analyzer.detection.events import SignalEvent
from rtl_sdr_analyzer.engine.event_bus import EventBus


def _sample_event() -> SignalEvent:
    return SignalEvent(
        timestamp=datetime.now(UTC),
        frequency=98.5,
        power=-30.0,
        bandwidth=90_000.0,
        duration=0.4,
        confidence=2.1,
        snr=45.0,
    )


def test_event_bus_subscribe_publish_and_error_isolation() -> None:
    bus = EventBus()
    received: list[SignalEvent] = []

    def bad(_ev: SignalEvent) -> None:
        raise RuntimeError("boom")

    def good(ev: SignalEvent) -> None:
        received.append(ev)

    bus.subscribe(bad)
    bus.subscribe(good)
    bus.publish(_sample_event())
    assert len(received) == 1

    bus.unsubscribe(good)
    bus.publish(_sample_event())
    assert len(received) == 1
