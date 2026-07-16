"""Windows MI_03 raw X-Celerator source and bounded raw-mode lifecycle."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import threading
import time
from typing import Callable

from ..contracts import Clock, EventEmitter
from ..models import Phase, TelemetryEvent

REPORT_ID_INFO = 0x09
INFO_SIZE = 0x08
XCAL_START = 0x08
XCAL_END = 0x0A
SPECIAL_REPORT_ID = 0x03
SPECIAL_TYPE_XCAL = 0xE0


class RawStreamHealth(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    HEALTHY = "healthy"
    STALE = "stale"
    ERROR = "error"


class _RawLifecycleState(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    ACTIVE = "active"
    STOPPING = "stopping"
    RECOVERING = "recovering"
    ERROR = "error"


def parse_xcelerator_report(report: bytes | bytearray | list[int]) -> int | None:
    """Return the raw 0..255 paddle value from a calibration report."""
    data = bytes(report)
    if len(data) < 5:
        return None
    if data[0] != SPECIAL_REPORT_ID or data[2] != SPECIAL_TYPE_XCAL:
        return None
    return data[4]


def find_raw_interface(infos: list[dict]) -> dict | None:
    """Find the Tyon MI_03 special-input interface."""
    for info in infos:
        if info.get("interface_number") == 3 and info.get("usage_page") == 0x000A:
            return info
    return None


def find_paired_vendor_interface(infos: list[dict], raw_interface: dict) -> dict | None:
    """Pair MI_03 with exactly one Telephony control collection."""
    vendors = [info for info in infos if info.get("usage_page") == 0x000B]
    if len(vendors) == 1:
        return vendors[0]
    raw_serial = raw_interface.get("serial_number")
    if raw_serial:
        matches = [info for info in vendors if info.get("serial_number") == raw_serial]
        if len(matches) == 1:
            return matches[0]
    return None


def open_hid_interface(hid_module: object, info: dict) -> object:
    """Open a selected HID collection without re-enumerating."""
    path = info["path"]
    if isinstance(path, str):
        path = path.encode()
    device = hid_module.device()
    device.open_path(path)
    return device


def xcal_command(function: int) -> bytes:
    """Build only the bounded, non-persistent raw start/end commands."""
    if function not in (XCAL_START, XCAL_END):
        raise ValueError("raw diagnostics permit only start (0x08) and end (0x0a)")
    return bytes((REPORT_ID_INFO, INFO_SIZE, function, 0, 0, 0, 0, 0))


def raw_mode_marker_path() -> Path:
    """Return the per-user recovery marker for interrupted raw sessions."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "RoccatMouse" / "raw-mode-active.json"


class RawModeLifecycle:
    """Pair raw-stream start/end reports and preserve failed cleanup state."""

    def __init__(
        self,
        *,
        device: object,
        marker_path: Path,
        check_write: Callable[..., object],
        write_feature: Callable[..., object],
        verbose: bool = False,
    ) -> None:
        self.device = device
        self.marker_path = marker_path
        self.check_write = check_write
        self.write_feature = write_feature
        self.verbose = verbose
        self._lock = threading.RLock()
        self._state = _RawLifecycleState.IDLE
        self._active = False

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def _send(self, function: int, label: str, *, cleanup: bool = False) -> None:
        try:
            self.check_write(self.device, verbose=self.verbose)
        except Exception:
            if not cleanup:
                raise
        self.write_feature(self.device, xcal_command(function), label, self.verbose)
        if cleanup or function == XCAL_START:
            self.check_write(self.device, verbose=self.verbose)

    def _write_marker(self) -> None:
        self.marker_path.parent.mkdir(parents=True, exist_ok=True)
        self.marker_path.write_text(
            json.dumps(
                {"pid": os.getpid(), "started_utc": datetime.now(timezone.utc).isoformat()},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def recover(self) -> bool:
        with self._lock:
            return self._recover_locked()

    def _recover_locked(self) -> bool:
        if not self.marker_path.exists():
            return False
        self._state = _RawLifecycleState.RECOVERING
        try:
            self._send(XCAL_END, "X-Celerator raw stream recovery end", cleanup=True)
        except BaseException:
            self._state = _RawLifecycleState.ERROR
            raise
        self.marker_path.unlink(missing_ok=True)
        self._active = False
        self._state = _RawLifecycleState.IDLE
        return True

    def start(self) -> None:
        with self._lock:
            if self._active or self._state in (
                _RawLifecycleState.STARTING,
                _RawLifecycleState.STOPPING,
                _RawLifecycleState.RECOVERING,
            ):
                raise RuntimeError(f"raw lifecycle is already {self._state.value}")
            if self.marker_path.exists():
                self._recover_locked()
            self._write_marker()
            self._state = _RawLifecycleState.STARTING
            try:
                self._send(XCAL_START, "X-Celerator raw stream start")
            except BaseException:
                try:
                    self._stop_locked()
                except Exception:
                    pass
                raise
            self._active = True
            self._state = _RawLifecycleState.ACTIVE

    def stop(self) -> bool:
        with self._lock:
            return self._stop_locked()

    def _stop_locked(self) -> bool:
        if not self._active and not self.marker_path.exists():
            self._state = _RawLifecycleState.IDLE
            return False
        self._state = _RawLifecycleState.STOPPING
        try:
            self._send(XCAL_END, "X-Celerator raw stream end", cleanup=True)
        except BaseException:
            self._state = _RawLifecycleState.ERROR
            raise
        self.marker_path.unlink(missing_ok=True)
        self._active = False
        self._state = _RawLifecycleState.IDLE
        return True


class RawAcceleratorSource:
    """Own MI_03 reads and emit timestamped raw-value telemetry.

    This adapter deliberately does not enter or leave raw mode. Session policy
    belongs to the coordinating runtime and ``RawModeLifecycle``.
    """

    def __init__(
        self,
        session_id: str,
        clock: Clock,
        phase: Callable[[], Phase],
        *,
        device: object,
        device_id: str,
        read_size: int = 64,
        read_timeout_ms: int = 25,
        stale_after_ms: float = 100.0,
        monotonic_ns: Callable[[], int] = time.perf_counter_ns,
        close_device_on_stop: bool = True,
        stop_timeout_seconds: float = 1.0,
    ) -> None:
        self.session_id = session_id
        self.clock = clock
        self.phase = phase
        self.device = device
        self.device_id = device_id
        self.read_size = read_size
        self.read_timeout_ms = read_timeout_ms
        self.stale_after_ns = int(stale_after_ms * 1_000_000)
        self._monotonic_ns = monotonic_ns
        self.close_device_on_stop = close_device_on_stop
        self.stop_timeout_seconds = stop_timeout_seconds
        self._emit: EventEmitter | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._health = RawStreamHealth.STOPPED
        self._started_at_ns: int | None = None
        self._last_report_at_ns: int | None = None
        self._error: BaseException | None = None
        self.other_report_count = 0
        self.report_count = 0
        self._closed = False

    @property
    def error(self) -> BaseException | None:
        with self._lock:
            return self._error

    @property
    def health(self) -> RawStreamHealth:
        with self._lock:
            health = self._health
            reference = self._last_report_at_ns or self._started_at_ns
        if health in (RawStreamHealth.STARTING, RawStreamHealth.HEALTHY) and reference is not None:
            if self._monotonic_ns() - reference > self.stale_after_ns:
                return RawStreamHealth.STALE
        return health

    def start(self, emit: EventEmitter, *, threaded: bool = True) -> None:
        with self._lock:
            if self._health is not RawStreamHealth.STOPPED:
                raise RuntimeError("raw accelerator capture is already running")
            self._emit = emit
            self._stop.clear()
            self._error = None
            self._started_at_ns = self._monotonic_ns()
            self._last_report_at_ns = None
            self._health = RawStreamHealth.STARTING
            if threaded:
                self._thread = threading.Thread(
                    target=self._read_loop, name="tyon-raw-accelerator", daemon=True
                )
                self._thread.start()

    def poll_once(self) -> TelemetryEvent | None:
        """Read and emit one report for a caller-owned synchronous loop."""
        try:
            report = self.device.read(self.read_size, self.read_timeout_ms)
            if not report:
                return None
            raw_hex = bytes(report).hex(" ")
            value = parse_xcelerator_report(report)
            if value is None:
                event = TelemetryEvent(
                    session_id=self.session_id,
                    timestamp=self.clock.now(),
                    source="mi03_raw",
                    kind="other_report",
                    phase=self.phase(),
                    payload={"raw_hex": raw_hex},
                    device_id=self.device_id,
                )
                with self._lock:
                    self.other_report_count += 1
                    emit = self._emit
                if emit is not None:
                    emit(event)
                return event
            event = TelemetryEvent(
                session_id=self.session_id,
                timestamp=self.clock.now(),
                source="mi03_raw",
                kind="raw_accelerator",
                phase=self.phase(),
                payload={"value": value, "raw_hex": raw_hex},
                device_id=self.device_id,
            )
            with self._lock:
                self.report_count += 1
                self._last_report_at_ns = self._monotonic_ns()
                self._health = RawStreamHealth.HEALTHY
                emit = self._emit
            if emit is not None:
                emit(event)
            return event
        except BaseException as exc:
            with self._lock:
                self._error = exc
                self._health = RawStreamHealth.ERROR
            raise

    def _read_loop(self) -> None:
        try:
            while not self._stop.is_set():
                self.poll_once()
        except BaseException:
            return

    def stop(self) -> None:
        with self._lock:
            if self._health is RawStreamHealth.STOPPED:
                return
            self._stop.set()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=self.stop_timeout_seconds)

        close_error: BaseException | None = None
        if self.close_device_on_stop and not self._closed:
            try:
                self.device.close()
                self._closed = True
            except BaseException as exc:
                close_error = exc
        if thread is not None and thread.is_alive():
            thread.join(timeout=self.stop_timeout_seconds)

        thread_alive = thread is not None and thread.is_alive()
        if thread_alive or close_error is not None:
            details: list[str] = []
            if thread_alive:
                details.append("raw accelerator read thread did not stop")
            if close_error is not None:
                details.append(str(close_error))
            failure = RuntimeError("raw accelerator cleanup failed: " + "; ".join(details))
            with self._lock:
                self._emit = None
                if not thread_alive:
                    self._thread = None
                self._error = failure
                self._health = RawStreamHealth.ERROR
            if close_error is not None:
                raise failure from close_error
            raise failure

        with self._lock:
            self._thread = None
            self._emit = None
            self._health = RawStreamHealth.STOPPED


__all__ = [
    "INFO_SIZE",
    "REPORT_ID_INFO",
    "RawAcceleratorSource",
    "RawModeLifecycle",
    "RawStreamHealth",
    "SPECIAL_REPORT_ID",
    "SPECIAL_TYPE_XCAL",
    "XCAL_END",
    "XCAL_START",
    "find_paired_vendor_interface",
    "find_raw_interface",
    "open_hid_interface",
    "parse_xcelerator_report",
    "raw_mode_marker_path",
    "xcal_command",
]
