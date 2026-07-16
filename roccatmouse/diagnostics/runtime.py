"""Platform-neutral ownership and lifecycle for diagnostic device sessions.

Adapters are injected per session.  This module deliberately contains no GUI,
HID, operating-system, persistence, or hardware-discovery implementation.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from .arbiter import DeviceSessionArbiter
from .contracts import AcceleratorSource, Clock, DeviceControl, InputEventSource
from .models import (
    DeviceIdentity,
    DiagnosticSnapshot,
    DiagnosticStatus,
    Phase,
    RawStreamHealth,
    RuntimeMode,
    TelemetryEvent,
)


class NormalObservation(Protocol):
    """One normal-output observation session, opened by an injected factory."""

    def start(self, emit: Callable[[TelemetryEvent], None]) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class RawLifecycle(Protocol):
    def start(self) -> None: ...
    def stop(self) -> bool: ...
    def recover(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class RawAdapterBundle:
    """All adapters tied to one raw session and one physical identity."""

    identity: DeviceIdentity
    device_control: DeviceControl
    lifecycle: RawLifecycle
    accelerator_source: AcceleratorSource
    input_source: InputEventSource
    close: Callable[[], None]
    health_check: Callable[[], str | Enum | None] | None = None


class NormalObservationFactory(Protocol):
    def __call__(self, session_id: str, clock: Clock) -> NormalObservation: ...


class RawAdapterFactory(Protocol):
    def __call__(
        self, session_id: str, clock: Clock, phase: Callable[[], Phase]
    ) -> RawAdapterBundle: ...


StatusListener = Callable[[DiagnosticStatus], None]
SnapshotListener = Callable[[DiagnosticSnapshot], None]
EventListener = Callable[[TelemetryEvent], None]


class DiagnosticRuntime:
    """Thread-safe owner of normal and bounded raw diagnostic lifecycles.

    Raw startup order is Windows-output capture, raw lifecycle acknowledgement,
    then raw measurement capture.  Shutdown reverses source ownership before
    asking the lifecycle to verify raw-mode exit.
    """

    _RAW_MODES = frozenset((RuntimeMode.QUALIFYING, RuntimeMode.LIVE_RAW))

    def __init__(
        self,
        *,
        clock: Clock,
        normal_factory: NormalObservationFactory | None,
        raw_factory: RawAdapterFactory,
        arbiter: DeviceSessionArbiter | None = None,
        monitor_interval_seconds: float = 0.05,
        session_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if monitor_interval_seconds <= 0:
            raise ValueError("monitor_interval_seconds must be positive")
        self._clock = clock
        self._normal_factory = normal_factory
        self._raw_factory = raw_factory
        self._arbiter = arbiter or DeviceSessionArbiter()
        self._monitor_interval = monitor_interval_seconds
        self._new_session_id = session_id_factory or (lambda: str(uuid.uuid4()))
        self._lock = threading.RLock()
        self._normal_id: str | None = None
        self._normal: NormalObservation | None = None
        self._raw_id: str | None = None
        self._raw: RawAdapterBundle | None = None
        self._identity: DeviceIdentity | None = None
        self._phase = Phase.NONE
        self._baseline: int | None = None
        self._before_fingerprint = None
        self._raw_lifecycle_clean = False
        self._raw_lifecycle_required = False
        self._errors: list[str] = []
        self._event_buffer: dict[int, TelemetryEvent] = {}
        self._expected_sequence: int | None = None
        self._ignored_sequences: set[int] = set()
        self._latest_raw_event: TelemetryEvent | None = None
        self._previous_raw_event: TelemetryEvent | None = None
        self._latest_windows_output: dict | None = None
        self._stream_health = RawStreamHealth.STOPPED.value
        self._status_listeners: list[StatusListener] = []
        self._snapshot_listeners: list[SnapshotListener] = []
        self._event_listeners: list[EventListener] = []
        self._listener_deferral = 0
        self._deferred_events: list[TelemetryEvent] = []
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._closed = False

    def _record_error(self, message: str) -> None:
        if message not in self._errors:
            self._errors.append(message)

    def _error_text(self) -> str | None:
        return "; ".join(self._errors) or None

    def _call_listeners(self, listeners: tuple[Callable, ...], value: object) -> None:
        for listener in listeners:
            try:
                listener(value)
            except Exception:
                # Observers cannot take device ownership or session safety down.
                continue

    def _notify_status(self) -> None:
        value = self.status()
        with self._lock:
            listeners = tuple(self._status_listeners)
        self._call_listeners(listeners, value)

    def _notify_snapshot(self) -> None:
        value = self.snapshot()
        with self._lock:
            listeners = tuple(self._snapshot_listeners)
        self._call_listeners(listeners, value)

    def status(self) -> DiagnosticStatus:
        with self._lock:
            ownership = self._arbiter.ownership
            if ownership.mode in self._RAW_MODES or ownership.mode is RuntimeMode.RECOVERING:
                session_id = self._raw_id
            elif ownership.mode is RuntimeMode.NORMAL:
                session_id = self._normal_id
            else:
                session_id = None
            lifecycle = {
                RuntimeMode.STOPPED: "stopped",
                RuntimeMode.NORMAL: "running",
                RuntimeMode.QUALIFYING: "running",
                RuntimeMode.LIVE_RAW: "running",
                RuntimeMode.RECOVERING: "recovering",
                RuntimeMode.ERROR: "error",
            }[ownership.mode]
            cleanup = "unverified" if ownership.mode is RuntimeMode.RECOVERING else (
                "active" if ownership.mode in self._RAW_MODES else "verified"
            )
            return DiagnosticStatus(
                session_id, self._identity, ownership.mode, lifecycle,
                "not_configured", cleanup, self._error_text(),
            )

    def _consume_clock_stamp(self):
        stamp = self._clock.now()
        self._ignored_sequences.add(stamp.sequence)
        if self._expected_sequence is not None:
            while self._expected_sequence in self._ignored_sequences:
                self._ignored_sequences.remove(self._expected_sequence)
                self._expected_sequence += 1
        return stamp

    def snapshot(self) -> DiagnosticSnapshot:
        with self._lock:
            latest = self._latest_raw_event
            now = self._consume_clock_stamp() if latest is not None else None
            raw_value = None if latest is None else latest.payload.get("value")
            age = None
            if latest is not None and now is not None:
                age = max(0.0, (now.monotonic_ns - latest.timestamp.monotonic_ns) / 1_000_000)
            rate = None
            if latest is not None and self._previous_raw_event is not None:
                delta = latest.timestamp.monotonic_ns - self._previous_raw_event.timestamp.monotonic_ns
                if delta > 0:
                    rate = 1_000_000_000 / delta
            baseline_delta = None
            if isinstance(raw_value, int) and self._baseline is not None:
                baseline_delta = raw_value - self._baseline
            session_id = self._raw_id if self._arbiter.mode in self._RAW_MODES else None
            return DiagnosticSnapshot(
                session_id, raw_value if isinstance(raw_value, int) else None,
                age, rate, baseline_delta,
                None if self._latest_windows_output is None else dict(self._latest_windows_output),
                "not_configured", self._stream_health,
            )

    def start_normal(self) -> str:
        with self._lock:
            if self._closed:
                raise RuntimeError("diagnostic runtime is closed")
            if self._normal_factory is None:
                raise RuntimeError("normal observation is not configured")
            session_id = self._new_session_id()
            self._arbiter.acquire_normal(session_id)
            normal = None
            try:
                normal = self._normal_factory(session_id, self._clock)
                self._normal_id, self._normal = session_id, normal
            except BaseException as start_error:
                self._arbiter.release_normal(session_id)
                self._normal_id, self._normal = None, None
                raise
        try:
            normal.start(self._receive_event)
        except BaseException as start_error:
            cleanup_errors = []
            for label, cleanup in (("normal stop", normal.stop), ("normal close", normal.close)):
                try:
                    cleanup()
                except BaseException as exc:
                    cleanup_errors.append(f"{label} failed: {exc}")
            with self._lock:
                self._arbiter.release_normal(session_id)
                self._normal_id, self._normal = None, None
            if cleanup_errors:
                raise RuntimeError(
                    f"{start_error}; cleanup failures: {'; '.join(cleanup_errors)}"
                ) from start_error
            raise
        self._notify_status()
        return session_id

    def stop_normal(self) -> None:
        with self._lock:
            if self._arbiter.mode is not RuntimeMode.NORMAL or self._normal_id is None:
                raise RuntimeError("normal observation is not active")
            try:
                self._stop_normal_adapter()
            finally:
                self._arbiter.release_normal(self._normal_id)
                self._normal_id = None
        self._notify_status()

    def _stop_normal_adapter(self) -> None:
        normal, self._normal = self._normal, None
        if normal is None:
            return
        failure = None
        try:
            normal.stop()
        except BaseException as exc:
            failure = exc
        try:
            normal.close()
        except BaseException as exc:
            failure = failure or exc
        if failure is not None:
            raise failure

    def _pause_normal_adapter(self) -> None:
        """Pause normal capture or restore a coherent normal owner on failure."""
        try:
            self._stop_normal_adapter()
        except BaseException as pause_error:
            rollback_error = None
            replacement = None
            try:
                if self._normal_factory is None or self._normal_id is None:
                    raise RuntimeError("normal observation cannot be reopened")
                replacement = self._normal_factory(self._normal_id, self._clock)
                replacement.start(self._receive_event)
                self._normal = replacement
            except BaseException as exc:
                rollback_error = exc
                if replacement is not None:
                    for cleanup in (replacement.stop, replacement.close):
                        try:
                            cleanup()
                        except BaseException:
                            pass
                self._normal = None
                if self._normal_id is not None:
                    self._arbiter.release_normal(self._normal_id)
                    self._normal_id = None
            if rollback_error is not None:
                raise RuntimeError(
                    f"normal pause failed: {pause_error}; normal reopen failed: {rollback_error}"
                ) from pause_error
            raise

    def _resume_normal(self) -> None:
        with self._lock:
            if self._normal_id is None or self._normal_factory is None:
                return
            normal_id = self._normal_id
            normal_factory = self._normal_factory
        normal = None
        try:
            normal = normal_factory(normal_id, self._clock)
            with self._lock:
                self._normal = normal
            normal.start(self._receive_event)
        except BaseException as exc:
            with self._lock:
                self._record_error(f"normal observation resume failed: {exc}")
            if normal is not None:
                for label, cleanup in (("normal stop", normal.stop), ("normal close", normal.close)):
                    try:
                        cleanup()
                    except BaseException as cleanup_exc:
                        with self._lock:
                            self._record_error(f"normal resume {label} failed: {cleanup_exc}")
            with self._lock:
                try:
                    self._arbiter.release_normal(normal_id)
                finally:
                    self._normal = None
                    self._normal_id = None

    def start_raw(
        self, mode: RuntimeMode = RuntimeMode.LIVE_RAW, *, arithmetic_baseline: int | None = None
    ) -> str:
        if mode not in self._RAW_MODES:
            raise ValueError("raw mode must be qualifying or live_raw")
        if arithmetic_baseline is not None and not 0 <= arithmetic_baseline <= 255:
            raise ValueError("arithmetic_baseline must be in 0..255")
        pending_notifications = []
        with self._lock:
            if self._closed:
                raise RuntimeError("diagnostic runtime is closed")
            raw_id = self._new_session_id()
            normal_id = self._normal_id if self._arbiter.mode is RuntimeMode.NORMAL else None
            if normal_id is not None:
                self._pause_normal_adapter()
                self._arbiter.handoff_normal_to_raw(normal_id, raw_id, mode=mode)
            else:
                self._arbiter.acquire_raw(raw_id, mode=mode)
            self._raw_id = raw_id
            self._phase = Phase.PREPARATION
            self._baseline = arithmetic_baseline
            self._raw_lifecycle_clean = False
            self._raw_lifecycle_required = False
            self._latest_raw_event = self._previous_raw_event = None
            self._latest_windows_output = None
            self._event_buffer.clear(); self._ignored_sequences.clear()
            self._listener_deferral += 1
            start_stamp = self._clock.now()
            self._expected_sequence = start_stamp.sequence + 1
            bundle = None
            input_owned = lifecycle_owned = raw_owned = False
            try:
                bundle = self._raw_factory(raw_id, self._clock, lambda: self._phase)
                self._raw = bundle
                self._identity = bundle.identity
                self._before_fingerprint = bundle.device_control.fingerprint()
                input_owned = True
                bundle.input_source.start(self._receive_event)
                lifecycle_owned = True
                self._raw_lifecycle_required = True
                bundle.lifecycle.start()
                raw_owned = True
                bundle.accelerator_source.start(self._receive_event)
                self._phase = Phase.ACTION
                self._stream_health = self._health_value(bundle.accelerator_source)
            except BaseException as start_error:
                cleanup_verified = True
                cleanup_errors = []
                if raw_owned:
                    try: bundle.accelerator_source.stop()
                    except BaseException as exc:
                        cleanup_verified = False; cleanup_errors.append(f"raw source stop failed: {exc}")
                if lifecycle_owned:
                    try:
                        lifecycle_clean = bool(bundle.lifecycle.stop())
                        self._raw_lifecycle_clean = lifecycle_clean
                        cleanup_verified = lifecycle_clean and cleanup_verified
                    except BaseException as exc:
                        cleanup_verified = False; cleanup_errors.append(f"raw lifecycle end failed: {exc}")
                if input_owned:
                    try: bundle.input_source.stop()
                    except BaseException as exc:
                        cleanup_verified = False; cleanup_errors.append(f"input source stop failed: {exc}")
                if bundle is not None and cleanup_verified:
                    try: bundle.close()
                    except BaseException as exc:
                        cleanup_verified = False; cleanup_errors.append(f"raw adapter close failed: {exc}")
                self._arbiter.release_raw(raw_id, cleanup_verified=cleanup_verified)
                if cleanup_verified:
                    self._raw = None; self._raw_id = None
                    self._raw_lifecycle_clean = False
                    self._raw_lifecycle_required = False
                    if normal_id is not None: self._resume_normal()
                else:
                    detail = f": {'; '.join(cleanup_errors)}" if cleanup_errors else ""
                    self._record_error(f"raw start rollback cleanup unverified: {start_error}{detail}")
                self._listener_deferral -= 1
                self._deferred_events.clear()
                raise
            self._start_monitor()
            self._listener_deferral -= 1
            pending_notifications, self._deferred_events = self._deferred_events, []
        self._dispatch_events(pending_notifications)
        self._notify_status(); self._notify_snapshot()
        return raw_id

    @staticmethod
    def _health_value(source: object) -> str:
        value = getattr(source, "health", RawStreamHealth.HEALTHY)
        value = value() if callable(value) else value
        return value.value if isinstance(value, Enum) else str(value).lower()

    def health_check(self) -> str:
        """Inspect injected operational health and clean up failed raw capture."""
        should_stop = False
        with self._lock:
            if self._arbiter.mode not in self._RAW_MODES or self._raw is None:
                return self._stream_health
            try:
                health = self._health_value(self._raw.accelerator_source)
                extra = self._raw.health_check() if self._raw.health_check is not None else None
                extra_value = extra.value if isinstance(extra, Enum) else (str(extra).lower() if extra else None)
                if extra_value in (RawStreamHealth.STALE.value, RawStreamHealth.ERROR.value):
                    health = extra_value
            except BaseException as exc:
                health = RawStreamHealth.ERROR.value
                self._record_error(f"source/input health check failed: {exc}")
            self._stream_health = health
            if health in (RawStreamHealth.STALE.value, RawStreamHealth.ERROR.value):
                self._record_error(f"capture failure: raw stream {health}")
                should_stop = True
        if should_stop:
            try:
                self.stop_raw()
            except BaseException as exc:
                with self._lock:
                    self._record_error(f"capture failure cleanup raised: {exc}")
        return health

    def _start_monitor(self) -> None:
        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, name="diagnostic-runtime-health", daemon=True
        )
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        while not self._monitor_stop.wait(self._monitor_interval):
            self.health_check()
            with self._lock:
                if self._arbiter.mode not in self._RAW_MODES:
                    return

    def _detach_monitor_locked(self) -> threading.Thread | None:
        self._monitor_stop.set()
        thread, self._monitor_thread = self._monitor_thread, None
        return thread

    def _join_monitor(self, thread: threading.Thread | None) -> None:
        if thread is None or thread is threading.current_thread():
            return
        thread.join(timeout=max(1.0, self._monitor_interval * 4))
        if thread.is_alive():
            raise RuntimeError("diagnostic health monitor did not stop")

    def stop_raw(self) -> bool:
        with self._lock:
            if self._arbiter.mode not in self._RAW_MODES or self._raw is None or self._raw_id is None:
                raise RuntimeError("raw diagnostics are not active")
            if self._phase is Phase.STOPPING:
                raise RuntimeError("raw diagnostics are already stopping")
            self._phase = Phase.STOPPING
            monitor = self._detach_monitor_locked()
            stopping_id = self._raw_id
        self._join_monitor(monitor)
        with self._lock:
            if self._raw_id != stopping_id or self._raw is None:
                raise RuntimeError("raw diagnostics changed while stopping")
            bundle, raw_id = self._raw, self._raw_id
            cleanup_verified = True
            failures = []
            for label, stop in (("raw source", bundle.accelerator_source.stop),
                                ("input source", bundle.input_source.stop)):
                try: stop()
                except BaseException as exc:
                    cleanup_verified = False; failures.append(f"{label}: {exc}")
            try:
                lifecycle_clean = bool(bundle.lifecycle.stop())
                self._raw_lifecycle_clean = lifecycle_clean
                cleanup_verified = lifecycle_clean and cleanup_verified
            except BaseException as exc:
                cleanup_verified = False; failures.append(f"raw lifecycle: {exc}")
            delivered = self._drain_ordered(final=True)
            if cleanup_verified:
                self._check_fingerprint(bundle)
                try:
                    bundle.close()
                except BaseException as exc:
                    cleanup_verified = False
                    self._record_error(f"raw adapter close failed: {exc}")
            if cleanup_verified:
                self._raw = None; self._raw_id = None
                self._raw_lifecycle_clean = False
                self._raw_lifecycle_required = False
                self._stream_health = RawStreamHealth.STOPPED.value
            if not cleanup_verified:
                self._record_error("raw cleanup unverified" + (": " + ", ".join(failures) if failures else ""))
            self._arbiter.release_raw(raw_id, cleanup_verified=cleanup_verified)
            self._phase = Phase.NONE if cleanup_verified else Phase.STOPPING
            resume_normal = cleanup_verified and self._arbiter.mode is RuntimeMode.NORMAL
        self._dispatch_events(delivered)
        if resume_normal:
            self._resume_normal()
        self._notify_status(); self._notify_snapshot()
        return cleanup_verified

    def _check_fingerprint(self, bundle: RawAdapterBundle) -> None:
        try:
            after = bundle.device_control.fingerprint()
            if self._before_fingerprint != after:
                self._record_error("profile fingerprint mismatch after raw session")
        except BaseException as exc:
            self._record_error(f"post-raw fingerprint failed: {exc}")

    def recover(self) -> bool:
        result = False
        with self._lock:
            if self._arbiter.mode is not RuntimeMode.RECOVERING or self._raw is None or self._raw_id is None:
                raise RuntimeError("raw recovery is not pending")
            verified = True
            for label, stop in (("raw source", self._raw.accelerator_source.stop),
                                ("input source", self._raw.input_source.stop)):
                try:
                    stop()
                except BaseException as exc:
                    verified = False
                    self._record_error(f"raw recovery {label} stop failed: {exc}")
            if verified and self._raw_lifecycle_required and not self._raw_lifecycle_clean:
                try:
                    self._raw_lifecycle_clean = bool(self._raw.lifecycle.recover())
                    verified = self._raw_lifecycle_clean
                except BaseException as exc:
                    verified = False; self._record_error(f"raw recovery failed: {exc}")
            if verified:
                self._check_fingerprint(self._raw)
                try:
                    self._raw.close()
                except BaseException as exc:
                    self._record_error(f"raw recovery adapter close failed: {exc}")
                else:
                    raw_id = self._raw_id
                    self._raw = None; self._raw_id = None
                    self._raw_lifecycle_clean = False
                    self._raw_lifecycle_required = False
                    self._stream_health = RawStreamHealth.STOPPED.value
                    self._arbiter.recover(raw_id, cleanup_verified=True)
                    self._phase = Phase.NONE
                    resume_normal = self._arbiter.mode is RuntimeMode.NORMAL
                    result = True
                if not result:
                    resume_normal = False
            else:
                resume_normal = False
        if resume_normal:
            self._resume_normal()
        self._notify_status(); self._notify_snapshot()
        return result

    def _receive_event(self, event: TelemetryEvent) -> None:
        delivered = []
        with self._lock:
            active = self._raw_id if self._arbiter.mode in self._RAW_MODES else self._normal_id
            if event.session_id != active:
                self._record_error(
                    f"wrong-session event rejected: expected {active!r}, got {event.session_id!r}"
                )
                return
            sequence = event.timestamp.sequence
            if self._expected_sequence is None:
                self._expected_sequence = sequence
            if sequence < self._expected_sequence or sequence in self._event_buffer:
                self._record_error(f"duplicate or late sequence {sequence} rejected")
                return
            self._event_buffer[sequence] = event
            delivered = self._drain_ordered(final=False)
        self._dispatch_events(delivered)

    def _drain_ordered(self, *, final: bool) -> list[TelemetryEvent]:
        if self._expected_sequence is None:
            return []
        delivered = []
        while True:
            while self._expected_sequence in self._ignored_sequences:
                self._ignored_sequences.remove(self._expected_sequence)
                self._expected_sequence += 1
            event = self._event_buffer.pop(self._expected_sequence, None)
            if event is None:
                break
            delivered.append(event); self._expected_sequence += 1
        if final and self._event_buffer:
            first = min(self._event_buffer)
            self._record_error(f"irrecoverable sequence gap before {first} at final drain")
            for sequence in sorted(self._event_buffer):
                delivered.append(self._event_buffer[sequence])
            self._event_buffer.clear()
            self._expected_sequence = delivered[-1].timestamp.sequence + 1
        for event in delivered:
            self._apply_measured_event(event)
        return delivered

    def _dispatch_events(self, delivered: list[TelemetryEvent]) -> None:
        with self._lock:
            if self._listener_deferral:
                self._deferred_events.extend(delivered)
                return
        for event in delivered:
            with self._lock:
                listeners = tuple(self._event_listeners)
                snapshot_listeners = tuple(self._snapshot_listeners)
            self._call_listeners(listeners, event)
            if snapshot_listeners:
                value = self.snapshot()
                self._call_listeners(snapshot_listeners, value)

    def _apply_measured_event(self, event: TelemetryEvent) -> None:
        if event.kind == "raw_accelerator" and isinstance(event.payload.get("value"), int):
            self._previous_raw_event, self._latest_raw_event = self._latest_raw_event, event
            self._stream_health = RawStreamHealth.HEALTHY.value
        elif event.kind in ("wheel", "horizontal_wheel"):
            self._latest_windows_output = {
                "kind": event.kind, "source": event.source,
                "timestamp": event.timestamp, **dict(event.payload),
            }

    def add_status_listener(self, listener: StatusListener) -> None:
        with self._lock:
            if listener not in self._status_listeners: self._status_listeners.append(listener)
    def remove_status_listener(self, listener: StatusListener) -> None:
        with self._lock:
            if listener in self._status_listeners: self._status_listeners.remove(listener)
    def add_snapshot_listener(self, listener: SnapshotListener) -> None:
        with self._lock:
            if listener not in self._snapshot_listeners: self._snapshot_listeners.append(listener)
    def remove_snapshot_listener(self, listener: SnapshotListener) -> None:
        with self._lock:
            if listener in self._snapshot_listeners: self._snapshot_listeners.remove(listener)
    def add_event_listener(self, listener: EventListener) -> None:
        with self._lock:
            if listener not in self._event_listeners: self._event_listeners.append(listener)
    def remove_event_listener(self, listener: EventListener) -> None:
        with self._lock:
            if listener in self._event_listeners: self._event_listeners.remove(listener)

    def close(self) -> None:
        with self._lock:
            if self._closed: return
            self._closed = True
            mode = self._arbiter.mode
        if mode in self._RAW_MODES:
            self.stop_raw()
        with self._lock:
            mode = self._arbiter.mode
        if mode is RuntimeMode.RECOVERING:
            self.recover()
        with self._lock:
            mode = self._arbiter.mode
        if mode is RuntimeMode.NORMAL:
            self.stop_normal()


__all__ = [
    "DiagnosticRuntime", "NormalObservation", "NormalObservationFactory",
    "RawAdapterBundle", "RawAdapterFactory", "RawLifecycle",
]
