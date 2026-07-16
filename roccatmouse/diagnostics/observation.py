"""Continuous normal-mode observation lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import threading
import time
import uuid
from typing import Callable

from roccatmouse.config import AppConfig, telemetry_path

from .aggregate import OneSecondAccumulator
from .contracts import Clock, DeviceControl, InputEventSource
from .models import CaptureMode, Phase, SessionResult, SessionState, TrialLabel
from .storage import SQLiteTelemetryStore
from .writer import TelemetryWriter, WriterStats
from .windows.clock import QpcClock
from .windows.device import TyonDeviceControl
from .windows.raw_input import RawInputSource


@dataclass(frozen=True, slots=True)
class ObservationStatus:
    active: bool
    session_id: str | None
    started_utc: datetime | None
    markers: int
    writer: WriterStats | None
    error: str | None


class ObservationRuntime:
    def __init__(
        self,
        store: SQLiteTelemetryStore,
        clock: Clock,
        source_factory: Callable[[str], InputEventSource],
        *,
        device_control: DeviceControl | None = None,
        queue_size: int = 10_000,
    ) -> None:
        self.store = store
        self.clock = clock
        self.source_factory = source_factory
        self.device_control = device_control
        self.queue_size = queue_size
        self._lock = threading.RLock()
        self._session_id: str | None = None
        self._started_utc: datetime | None = None
        self._markers = 0
        self._error: str | None = None
        self._source: InputEventSource | None = None
        self._writer: TelemetryWriter | None = None
        self._accumulator: OneSecondAccumulator | None = None
        self._timer_stop = threading.Event()
        self._timer: threading.Thread | None = None

    @classmethod
    def windows_default(
        cls,
        config: AppConfig,
        *,
        database_path: Path | None = None,
    ) -> "ObservationRuntime":
        store = SQLiteTelemetryStore(database_path or telemetry_path())
        clock = QpcClock()
        runtime: ObservationRuntime
        runtime = cls(
            store,
            clock,
            lambda session_id: RawInputSource(
                session_id,
                clock,
                lambda: Phase.ACTION,
            ),
            device_control=TyonDeviceControl(),
            queue_size=config.queue_size,
        )
        return runtime

    def start(self) -> ObservationStatus:
        with self._lock:
            if self._session_id is not None:
                raise RuntimeError("continuous observation is already active")
            session_id = str(uuid.uuid4())
            started = self.clock.now()
            fingerprint = None
            if self.device_control is not None:
                fingerprint = self.device_control.fingerprint()
            self.store.start_session(
                session_id,
                TrialLabel.GENERAL_OBSERVATION,
                CaptureMode.NORMAL,
                fingerprint,
                tier="continuous",
                timestamp=started,
            )
            writer = TelemetryWriter(self.store, queue_size=self.queue_size)
            writer.start()
            source = self.source_factory(session_id)
            accumulator = OneSecondAccumulator()
            self._session_id = session_id
            self._started_utc = started.utc
            self._markers = 0
            self._error = None
            self._writer = writer
            self._source = source
            self._accumulator = accumulator
            try:
                source.start(self._on_event)
            except BaseException as exc:
                try:
                    source.stop()
                except Exception:
                    pass
                writer.stop()
                result = SessionResult(
                    session_id,
                    TrialLabel.GENERAL_OBSERVATION,
                    CaptureMode.NORMAL,
                    SessionState.FAILED,
                    False,
                    fingerprint,
                    str(exc),
                )
                self.store.finish_session(result, timestamp=self.clock.now())
                self._session_id = None
                self._started_utc = None
                self._writer = None
                self._source = None
                self._accumulator = None
                self._error = str(exc)
                raise
            self._timer_stop.clear()
            self._timer = threading.Thread(
                target=self._timer_loop,
                name="observation-timer",
                daemon=True,
            )
            self._timer.start()
            return self.status

    def mark_symptom(self, note: str = "symptom") -> int:
        with self._lock:
            if self._session_id is None:
                raise RuntimeError("continuous observation is not active")
            if self._writer is not None:
                self._writer.raise_if_failed()
            marker = self.store.mark_symptom(self._session_id, self.clock.now(), note)
            self._markers += 1
            return marker

    def stop(self) -> ObservationStatus:
        with self._lock:
            if self._session_id is None:
                return self.status
            session_id = self._session_id
            source = self._source
            writer = self._writer
            accumulator = self._accumulator
            self._timer_stop.set()
        if self._timer is not None:
            self._timer.join(2)
        clean = True
        error = None
        try:
            if source is not None:
                source.stop()
            if accumulator is not None and writer is not None:
                for bucket in accumulator.flush():
                    writer.submit_aggregate(bucket)
            if writer is not None:
                writer.stop()
        except BaseException as exc:
            clean = False
            error = str(exc)
        state = SessionState.COMPLETED if clean else SessionState.FAILED
        result = SessionResult(
            session_id,
            TrialLabel.GENERAL_OBSERVATION,
            CaptureMode.NORMAL,
            state,
            clean,
            error=error,
        )
        self.store.finish_session(result, timestamp=self.clock.now())
        with self._lock:
            self._session_id = None
            self._started_utc = None
            self._source = None
            self._writer = None
            self._accumulator = None
            self._timer = None
            self._error = error
            return self.status

    @property
    def status(self) -> ObservationStatus:
        writer_stats = self._writer.stats if self._writer is not None else None
        return ObservationStatus(
            self._session_id is not None,
            self._session_id,
            self._started_utc,
            self._markers,
            writer_stats,
            self._error,
        )

    def close(self) -> None:
        self.stop()
        self.store.close()

    def _on_event(self, event) -> None:
        with self._lock:
            if self._accumulator is None or self._writer is None:
                return
            for bucket in self._accumulator.add(event):
                self._writer.submit_aggregate(bucket)
            if event.kind in ("wheel", "horizontal_wheel", "button", "disconnect", "reconnect", "anomaly"):
                self._writer.submit_event(event)

    def _timer_loop(self) -> None:
        while not self._timer_stop.wait(0.25):
            with self._lock:
                if self._session_id is None or self._accumulator is None or self._writer is None:
                    return
                try:
                    for bucket in self._accumulator.advance(self._session_id, self.clock.now()):
                        self._writer.submit_aggregate(bucket)
                    self._writer.raise_if_failed()
                except BaseException as exc:
                    self._error = str(exc)
                    self._timer_stop.set()
                    return
