"""Thin application-facing facade for the platform-neutral diagnostic runtime."""

from __future__ import annotations

from .models import DiagnosticSnapshot, DiagnosticStatus, RuntimeMode
from .runtime import DiagnosticRuntime, EventListener, SnapshotListener, StatusListener


class DiagnosticController:
    def __init__(self, runtime: DiagnosticRuntime) -> None:
        self._runtime = runtime

    def start_normal(self) -> str: return self._runtime.start_normal()
    def stop_normal(self) -> None: self._runtime.stop_normal()
    def start_raw(self, mode: RuntimeMode = RuntimeMode.LIVE_RAW, *, arithmetic_baseline: int | None = None) -> str:
        return self._runtime.start_raw(mode, arithmetic_baseline=arithmetic_baseline)
    def stop_raw(self) -> bool: return self._runtime.stop_raw()
    def recover(self) -> bool: return self._runtime.recover()
    def close(self) -> None: self._runtime.close()
    def health_check(self) -> str: return self._runtime.health_check()
    def status(self) -> DiagnosticStatus: return self._runtime.status()
    def snapshot(self) -> DiagnosticSnapshot: return self._runtime.snapshot()
    def add_status_listener(self, listener: StatusListener) -> None: self._runtime.add_status_listener(listener)
    def remove_status_listener(self, listener: StatusListener) -> None: self._runtime.remove_status_listener(listener)
    def add_snapshot_listener(self, listener: SnapshotListener) -> None: self._runtime.add_snapshot_listener(listener)
    def remove_snapshot_listener(self, listener: SnapshotListener) -> None: self._runtime.remove_snapshot_listener(listener)
    def add_event_listener(self, listener: EventListener) -> None: self._runtime.add_event_listener(listener)
    def remove_event_listener(self, listener: EventListener) -> None: self._runtime.remove_event_listener(listener)


__all__ = ["DiagnosticController", "DiagnosticSnapshot", "DiagnosticStatus", "RuntimeMode"]
