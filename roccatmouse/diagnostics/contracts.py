"""Structural contracts for platform adapters and diagnostics services."""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from .models import (
    CaptureMode,
    DeviceFingerprint,
    SessionResult,
    TelemetryEvent,
    Timestamp,
    TrialLabel,
)

EventEmitter = Callable[[TelemetryEvent], None]


@runtime_checkable
class Clock(Protocol):
    def now(self) -> Timestamp: ...


@runtime_checkable
class DeviceControl(Protocol):
    def fingerprint(self) -> DeviceFingerprint: ...

    def recover(self) -> bool: ...

    def start_raw(self) -> None: ...

    def stop_raw(self) -> bool: ...


@runtime_checkable
class AcceleratorSource(Protocol):
    def start(self, emit: EventEmitter) -> None: ...

    def stop(self) -> None: ...


@runtime_checkable
class InputEventSource(Protocol):
    def start(self, emit: EventEmitter) -> None: ...

    def stop(self) -> None: ...


@runtime_checkable
class TelemetrySink(Protocol):
    def start_session(
        self,
        session_id: str,
        trial: TrialLabel,
        mode: CaptureMode,
        fingerprint: DeviceFingerprint | None,
    ) -> None: ...

    def write_event(self, event: TelemetryEvent) -> None: ...

    def finish_session(self, result: SessionResult) -> None: ...
