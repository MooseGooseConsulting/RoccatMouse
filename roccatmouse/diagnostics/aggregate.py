"""Deterministic one-second telemetry aggregation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .models import TelemetryEvent, Timestamp

SECOND_NS = 1_000_000_000


@dataclass(slots=True)
class AggregateBucket:
    session_id: str
    bucket_start_ns: int
    bucket_start_utc: datetime
    sample_count: int = 0
    wheel_event_count: int = 0
    wheel_delta_sum: int = 0
    wheel_reversals: int = 0
    movement_count: int = 0
    movement_dx_sum: int = 0
    movement_dy_sum: int = 0
    button_event_count: int = 0
    anomaly_count: int = 0
    late_event_count: int = 0
    values_min: dict[str, float] = field(default_factory=dict)
    values_max: dict[str, float] = field(default_factory=dict)
    values_sum: dict[str, float] = field(default_factory=dict)
    _last_wheel_direction: int = 0

    def add(self, event: TelemetryEvent) -> None:
        payload = event.payload
        self.sample_count += 1
        if event.kind in ("wheel", "horizontal_wheel"):
            delta = int(payload.get("delta", 0))
            direction = (delta > 0) - (delta < 0)
            self.wheel_event_count += 1
            self.wheel_delta_sum += delta
            if direction and self._last_wheel_direction and direction != self._last_wheel_direction:
                self.wheel_reversals += 1
            if direction:
                self._last_wheel_direction = direction
        elif event.kind == "relative_move":
            self.movement_count += 1
            self.movement_dx_sum += int(payload.get("dx", 0))
            self.movement_dy_sum += int(payload.get("dy", 0))
        elif event.kind == "button":
            self.button_event_count += 1
        elif event.kind in ("anomaly", "disconnect", "reconnect"):
            self.anomaly_count += 1

        numeric = payload.get("values")
        if isinstance(numeric, dict):
            for name, value in numeric.items():
                if not isinstance(value, (int, float)):
                    continue
                number = float(value)
                self.values_min[name] = min(number, self.values_min.get(name, number))
                self.values_max[name] = max(number, self.values_max.get(name, number))
                self.values_sum[name] = self.values_sum.get(name, 0.0) + number

    def payload(self) -> dict[str, Any]:
        return {
            "late_event_count": self.late_event_count,
            "values_min": self.values_min,
            "values_max": self.values_max,
            "values_sum": self.values_sum,
        }


class OneSecondAccumulator:
    def __init__(self) -> None:
        self._current: AggregateBucket | None = None
        self.late_events = 0

    def add(self, event: TelemetryEvent) -> list[AggregateBucket]:
        start_ns = event.timestamp.monotonic_ns // SECOND_NS * SECOND_NS
        if self._current is None:
            self._current = self._new_bucket(event, start_ns)
        elif start_ns < self._current.bucket_start_ns:
            self.late_events += 1
            self._current.late_event_count += 1
            return []
        elif start_ns > self._current.bucket_start_ns:
            completed = [self._current]
            previous = self._current
            next_ns = previous.bucket_start_ns + SECOND_NS
            while next_ns < start_ns:
                completed.append(
                    AggregateBucket(
                        event.session_id,
                        next_ns,
                        previous.bucket_start_utc
                        + timedelta(seconds=(next_ns - previous.bucket_start_ns) / SECOND_NS),
                    )
                )
                next_ns += SECOND_NS
            self._current = self._new_bucket(event, start_ns)
            self._current.add(event)
            return completed
        self._current.add(event)
        return []

    def flush(self) -> list[AggregateBucket]:
        if self._current is None:
            return []
        current = self._current
        self._current = None
        return [current]

    def advance(self, session_id: str, timestamp: Timestamp) -> list[AggregateBucket]:
        """Close elapsed buckets without inventing a telemetry sample."""
        start_ns = timestamp.monotonic_ns // SECOND_NS * SECOND_NS
        if self._current is None:
            offset = (timestamp.monotonic_ns - start_ns) / SECOND_NS
            self._current = AggregateBucket(
                session_id,
                start_ns,
                timestamp.utc - timedelta(seconds=offset),
            )
            return []
        if start_ns <= self._current.bucket_start_ns:
            return []
        completed = [self._current]
        previous = self._current
        next_ns = previous.bucket_start_ns + SECOND_NS
        while next_ns < start_ns:
            completed.append(
                AggregateBucket(
                    session_id,
                    next_ns,
                    previous.bucket_start_utc
                    + timedelta(seconds=(next_ns - previous.bucket_start_ns) / SECOND_NS),
                )
            )
            next_ns += SECOND_NS
        offset = (timestamp.monotonic_ns - start_ns) / SECOND_NS
        self._current = AggregateBucket(
            session_id,
            start_ns,
            timestamp.utc - timedelta(seconds=offset),
        )
        return completed

    @staticmethod
    def _new_bucket(event: TelemetryEvent, start_ns: int) -> AggregateBucket:
        offset = (event.timestamp.monotonic_ns - start_ns) / SECOND_NS
        return AggregateBucket(
            event.session_id,
            start_ns,
            event.timestamp.utc - timedelta(seconds=offset),
        )
