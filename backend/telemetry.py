"""Clearly labeled, in-memory simulated telemetry for the local demo."""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from uuid import uuid4


@dataclass(frozen=True)
class TelemetryEvent:
    event_id: str
    timestamp: str
    source: str
    event_type: str
    source_interface: str | None = None
    destination_interface: str | None = None
    state: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


class SimulatedTelemetry:
    """A bounded event stream; it never represents live device telemetry."""

    def __init__(self, max_events: int = 200) -> None:
        self._events: deque[TelemetryEvent] = deque(maxlen=max_events)
        self.running = False

    def start(self) -> None:
        self.running = True
        self._record("simulation_started")

    def stop(self) -> None:
        if self.running:
            self._record("simulation_stopped")
        self.running = False

    def record_link_state(
        self, source_interface: str, destination_interface: str, state: str
    ) -> None:
        if self.running:
            self._record(
                "link_state_changed",
                source_interface=source_interface,
                destination_interface=destination_interface,
                state=state,
            )

    def events(self, limit: int = 50) -> list[dict]:
        if not 1 <= limit <= 200:
            raise ValueError("Limit must be between 1 and 200")
        return [event.as_dict() for event in list(self._events)[-limit:]][::-1]

    def _record(self, event_type: str, **kwargs) -> None:
        self._events.append(
            TelemetryEvent(
                event_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc).isoformat(),
                source="simulated",
                event_type=event_type,
                **kwargs,
            )
        )
