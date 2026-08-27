"""Bounded single-writer persistence queue for continuous observation."""

from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
from typing import Protocol

from .aggregate import AggregateBucket
from .models import TelemetryEvent


class WriterStore(Protocol):
    def write_event(self, event: TelemetryEvent) -> None: ...
    def write_aggregate(self, bucket: AggregateBucket) -> None: ...


@dataclass(frozen=True, slots=True)
class WriterStats:
    events_written: int
    aggregates_written: int
    aggregates_dropped: int


class TelemetryWriter:
    """Prioritize discrete events while bounding replaceable aggregate work."""

    def __init__(self, store: WriterStore, *, queue_size: int = 10_000) -> None:
        self.store = store
        self._priority: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=512)
        self._bulk: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._events_written = 0
        self._aggregates_written = 0
        self._aggregates_dropped = 0

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("telemetry writer is already running")
        self._stop.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="telemetry-writer", daemon=True)
        self._thread.start()

    def submit_event(self, event: TelemetryEvent) -> None:
        self.raise_if_failed()
        try:
            self._priority.put_nowait(("event", event))
        except queue.Full as exc:
            raise RuntimeError("discrete telemetry queue is full") from exc

    def submit_aggregate(self, bucket: AggregateBucket) -> bool:
        self.raise_if_failed()
        try:
            self._bulk.put_nowait(("aggregate", bucket))
            return True
        except queue.Full:
            self._aggregates_dropped += 1
            return False

    def stop(self, *, timeout: float = 5.0) -> WriterStats:
        thread = self._thread
        if thread is None:
            return self.stats
        self._stop.set()
        thread.join(timeout)
        if thread.is_alive():
            raise RuntimeError("telemetry writer did not drain before timeout")
        self._thread = None
        self.raise_if_failed()
        return self.stats

    def raise_if_failed(self) -> None:
        if self._error is not None:
            raise RuntimeError(f"telemetry persistence failed: {self._error}") from self._error

    @property
    def stats(self) -> WriterStats:
        return WriterStats(
            self._events_written,
            self._aggregates_written,
            self._aggregates_dropped,
        )

    def _run(self) -> None:
        try:
            while not self._stop.is_set() or not self._priority.empty() or not self._bulk.empty():
                item: tuple[str, object] | None = None
                try:
                    item = self._priority.get_nowait()
                except queue.Empty:
                    try:
                        item = self._bulk.get(timeout=0.05)
                    except queue.Empty:
                        continue
                kind, value = item
                if kind == "event":
                    self.store.write_event(value)  # type: ignore[arg-type]
                    self._events_written += 1
                else:
                    self.store.write_aggregate(value)  # type: ignore[arg-type]
                    self._aggregates_written += 1
        except BaseException as exc:
            self._error = exc
            self._stop.set()
