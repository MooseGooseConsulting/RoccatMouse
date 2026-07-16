# SPDX-License-Identifier: MIT
"""X-Celerator signal and scroll-event diagnostic monitor for Windows.

This tool deliberately uses the Windows multimedia joystick API and never
sends HID feature/output reports.  It is therefore safe to leave running while
reproducing paddle jitter or a stuck-scroll event.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import statistics
import sys
import threading
import time
from typing import Callable, Iterable
import uuid

from roccatmouse.diagnostics.csv_sink import CsvTelemetryWriter
from roccatmouse.diagnostics.models import (
    CaptureMode,
    Phase,
    SessionState,
    TelemetryEvent,
    TrialLabel,
)
from roccatmouse.diagnostics.session import CaptureSession
from roccatmouse.diagnostics.windows.clock import QpcClock
from roccatmouse.diagnostics.windows.device import TyonDeviceControl
from roccatmouse.diagnostics.windows.raw_input import RawInputSource


AXES = ("x", "y", "z", "r", "u", "v")
JOY_RETURNALL = 0x000000FF
JOYERR_NOERROR = 0
JOYERR_UNPLUGGED = 167
MAX_JOYSTICK_SLOTS = 16
REPORT_ID_INFO = 0x09
INFO_SIZE = 0x08
XCAL_START = 0x08
XCAL_END = 0x0A
SPECIAL_REPORT_ID = 0x03
SPECIAL_TYPE_XCAL = 0xE0

TRIAL_ALIASES = {"paddle": TrialLabel.PADDLE_ONLY, "wheel": TrialLabel.WHEEL_ONLY}


def normalized_trial_label(value: str) -> TrialLabel:
    if value in TRIAL_ALIASES:
        return TRIAL_ALIASES[value]
    return TrialLabel(value)


@dataclass(frozen=True)
class CaptureRequest:
    """The fixed timing and mode used by the compact capture window."""

    trial: str
    start_delay_seconds: float = 1.0
    baseline_seconds: float = 2.0
    action_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.trial not in (
            "paddle",
            "wheel",
            "neutral",
            "paddle_only",
            "wheel_only",
            "symptom_reproduction",
            "general_observation",
        ):
            raise ValueError("unsupported controlled trial label")
        if self.start_delay_seconds < 0:
            raise ValueError("start delay cannot be negative")
        if self.baseline_seconds <= 0:
            raise ValueError("baseline duration must be positive")
        if self.action_seconds <= 0:
            raise ValueError("action duration must be positive")

    @property
    def raw(self) -> bool:
        return self.trial == "paddle"

    @property
    def label(self) -> TrialLabel:
        return normalized_trial_label(self.trial)

    @property
    def monitor_duration(self) -> float:
        """Seconds passed to the legacy monitor loop.

        The normal joystick path takes its baseline before its timed loop; the
        raw paddle path takes it inside that loop.
        """
        if self.raw:
            return self.baseline_seconds + self.action_seconds
        return self.action_seconds


def monitor_args_for_request(request: CaptureRequest, output: str) -> argparse.Namespace:
    """Translate a compact-window request to the existing monitor options."""
    return argparse.Namespace(
        raw=request.raw,
        trial=request.trial,
        device=None,
        duration=request.monitor_duration,
        start_delay=0,
        poll_hz=250.0,
        display_hz=5.0,
        baseline_seconds=request.baseline_seconds,
        away_threshold=1500,
        no_scroll_events=False,
        output=output,
        verbose=False,
        list=False,
    )


def baseline_progress_message(seconds: float) -> str:
    return f"Leave the wheel and paddle untouched for {seconds:g} seconds."


def action_progress_message(args: argparse.Namespace) -> str:
    if args.trial == "neutral":
        duration = f" for {args.duration:g} seconds" if args.duration else " until stopped"
        return f"Keep the wheel and paddle untouched{duration}."
    if args.trial == "symptom_reproduction":
        duration = f" for up to {args.duration:g} seconds" if args.duration else " until marked"
        return f"Use the X-Celerator normally and reproduce the symptom{duration}."
    if args.trial in ("wheel", "wheel_only"):
        action_seconds = args.duration if args.duration else None
        control = "physical wheel up and down"
    else:
        action_seconds = (
            max(0.0, args.duration - args.baseline_seconds)
            if args.raw and args.duration
            else args.duration or None
        )
        control = "X-Celerator paddle up and down"
    duration = f" for {action_seconds:g} seconds" if action_seconds is not None else " until stopped"
    return f"Move ONLY the {control}{duration}."


@dataclass(frozen=True)
class CaptureProgress:
    phase: str
    message: str


@dataclass(frozen=True)
class CaptureResult:
    request: CaptureRequest
    output: Path
    cancelled: bool
    exit_code: int
    summary: dict[str, object]


ProgressCallback = Callable[[CaptureProgress], None]


def _progress(callback: ProgressCallback | None, phase: str, message: str) -> None:
    if callback is not None:
        callback(CaptureProgress(phase, message))


class JOYINFOEX(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("dwXpos", ctypes.c_uint32),
        ("dwYpos", ctypes.c_uint32),
        ("dwZpos", ctypes.c_uint32),
        ("dwRpos", ctypes.c_uint32),
        ("dwUpos", ctypes.c_uint32),
        ("dwVpos", ctypes.c_uint32),
        ("dwButtons", ctypes.c_uint32),
        ("dwButtonNumber", ctypes.c_uint32),
        ("dwPOV", ctypes.c_uint32),
        ("dwReserved1", ctypes.c_uint32),
        ("dwReserved2", ctypes.c_uint32),
    ]


class JOYCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", ctypes.c_uint16),
        ("wPid", ctypes.c_uint16),
        ("szPname", ctypes.c_wchar * 32),
        ("wXmin", ctypes.c_uint32),
        ("wXmax", ctypes.c_uint32),
        ("wYmin", ctypes.c_uint32),
        ("wYmax", ctypes.c_uint32),
        ("wZmin", ctypes.c_uint32),
        ("wZmax", ctypes.c_uint32),
        ("wNumButtons", ctypes.c_uint32),
        ("wPeriodMin", ctypes.c_uint32),
        ("wPeriodMax", ctypes.c_uint32),
        ("wRmin", ctypes.c_uint32),
        ("wRmax", ctypes.c_uint32),
        ("wUmin", ctypes.c_uint32),
        ("wUmax", ctypes.c_uint32),
        ("wVmin", ctypes.c_uint32),
        ("wVmax", ctypes.c_uint32),
        ("wCaps", ctypes.c_uint32),
        ("wMaxAxes", ctypes.c_uint32),
        ("wNumAxes", ctypes.c_uint32),
        ("wMaxButtons", ctypes.c_uint32),
        ("szRegKey", ctypes.c_wchar * 32),
        ("szOEMVxD", ctypes.c_wchar * 260),
    ]


@dataclass(frozen=True)
class JoystickInfo:
    slot: int
    name: str
    axes: int
    buttons: int


@dataclass(frozen=True)
class Sample:
    timestamp: float
    axes: dict[str, int]
    buttons: int
    pov: int


@dataclass
class AxisStats:
    baseline: int
    away_threshold: int
    minimum: int = 0xFFFFFFFF
    maximum: int = 0
    samples: int = 0
    away_samples: int = 0
    current_away_started: float | None = None
    longest_away_seconds: float = 0.0
    return_count: int = 0

    def add(self, timestamp: float, value: int) -> None:
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)
        self.samples += 1
        away = abs(value - self.baseline) > self.away_threshold
        if away:
            self.away_samples += 1
            if self.current_away_started is None:
                self.current_away_started = timestamp
        elif self.current_away_started is not None:
            self.longest_away_seconds = max(
                self.longest_away_seconds,
                timestamp - self.current_away_started,
            )
            self.current_away_started = None
            self.return_count += 1

    def finish(self, timestamp: float) -> None:
        if self.current_away_started is not None:
            self.longest_away_seconds = max(
                self.longest_away_seconds,
                timestamp - self.current_away_started,
            )

    @property
    def span(self) -> int:
        return 0 if self.samples == 0 else self.maximum - self.minimum


class WinMMJoystickApi:
    """Small ctypes wrapper around read-only WinMM joystick calls."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("The X-Celerator monitor currently requires Windows")
        self._winmm = ctypes.WinDLL("winmm")
        self._winmm.joyGetNumDevs.restype = ctypes.c_uint32
        self._winmm.joyGetPosEx.argtypes = [ctypes.c_uint32, ctypes.POINTER(JOYINFOEX)]
        self._winmm.joyGetPosEx.restype = ctypes.c_uint32
        self._winmm.joyGetDevCapsW.argtypes = [
            ctypes.c_size_t,
            ctypes.POINTER(JOYCAPSW),
            ctypes.c_uint32,
        ]
        self._winmm.joyGetDevCapsW.restype = ctypes.c_uint32

    def read(self, slot: int) -> Sample:
        info = JOYINFOEX()
        info.dwSize = ctypes.sizeof(JOYINFOEX)
        info.dwFlags = JOY_RETURNALL
        result = self._winmm.joyGetPosEx(slot, ctypes.byref(info))
        if result != JOYERR_NOERROR:
            detail = "device unplugged" if result == JOYERR_UNPLUGGED else f"error {result}"
            raise OSError(f"joyGetPosEx slot {slot}: {detail}")
        return Sample(
            timestamp=time.perf_counter(),
            axes={
                "x": info.dwXpos,
                "y": info.dwYpos,
                "z": info.dwZpos,
                "r": info.dwRpos,
                "u": info.dwUpos,
                "v": info.dwVpos,
            },
            buttons=info.dwButtons,
            pov=info.dwPOV,
        )

    def devices(self) -> list[JoystickInfo]:
        devices: list[JoystickInfo] = []
        count = min(int(self._winmm.joyGetNumDevs()), MAX_JOYSTICK_SLOTS)
        for slot in range(count):
            try:
                self.read(slot)
            except OSError:
                continue
            caps = JOYCAPSW()
            result = self._winmm.joyGetDevCapsW(
                slot, ctypes.byref(caps), ctypes.sizeof(JOYCAPSW)
            )
            name = caps.szPname if result == JOYERR_NOERROR else "Unknown joystick"
            devices.append(
                JoystickInfo(
                    slot=slot,
                    name=name or "Unknown joystick",
                    axes=int(caps.wNumAxes) if result == JOYERR_NOERROR else 0,
                    buttons=int(caps.wNumButtons) if result == JOYERR_NOERROR else 0,
                )
            )
        return devices


class ScrollCapture:
    """Optional global scroll-event capture using the existing pynput dependency."""

    def __init__(self) -> None:
        self.events: queue.SimpleQueue[tuple[float, int, int]] = queue.SimpleQueue()
        self._listener = None

    def start(self) -> str | None:
        try:
            from pynput import mouse
        except Exception as exc:
            return f"scroll capture unavailable ({exc})"

        def on_scroll(_x: int, _y: int, dx: int, dy: int) -> None:
            # pynput supplies pointer coordinates as callback context. They are
            # not cursor movement and are intentionally excluded from the
            # X-Celerator diagnostic schema.
            self.events.put((time.perf_counter(), int(dx), int(dy)))

        try:
            self._listener = mouse.Listener(on_scroll=on_scroll)
            self._listener.start()
        except Exception as exc:
            self._listener = None
            return f"scroll capture could not start ({exc})"
        return None

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def drain(self) -> Iterable[tuple[float, int, int]]:
        while True:
            try:
                yield self.events.get_nowait()
            except queue.Empty:
                return


class SpecialReportCapture:
    """Read MI_03 reports in normal mode without sending anything to the mouse."""

    def __init__(self) -> None:
        self.events: queue.SimpleQueue[tuple[float, bytes]] = queue.SimpleQueue()
        self._device = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> str | None:
        try:
            import hid
            from tyon_rgb import enumerate_tyon

            chosen = find_raw_interface(enumerate_tyon())
            if chosen is None:
                return "Tyon MI_03 special-report interface was not found"
            path = chosen["path"]
            if isinstance(path, str):
                path = path.encode()
            self._device = hid.device()
            self._device.open_path(path)
        except Exception as exc:
            self._device = None
            return f"special-report capture unavailable ({exc})"

        self._stop.clear()

        def read_loop() -> None:
            while not self._stop.is_set():
                try:
                    report = self._device.read(64, 50)
                except Exception:
                    return
                if report:
                    self.events.put((time.perf_counter(), bytes(report)))

        self._thread = threading.Thread(target=read_loop, daemon=True)
        self._thread.start()
        return None

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.25)
            self._thread = None
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None

    def drain(self) -> Iterable[tuple[float, bytes]]:
        while True:
            try:
                yield self.events.get_nowait()
            except queue.Empty:
                return


def parse_xcelerator_report(report: bytes | bytearray | list[int]) -> int | None:
    """Return the raw 0..255 paddle value from a Tyon calibration report."""
    data = bytes(report)
    if len(data) < 5:
        return None
    if data[0] != SPECIAL_REPORT_ID or data[2] != SPECIAL_TYPE_XCAL:
        return None
    return data[4]


def find_raw_interface(infos: list[dict]) -> dict | None:
    """Find the MI_03 special-input interface used by calibration reports."""
    for info in infos:
        if info.get("interface_number") == 3 and info.get("usage_page") == 0x000A:
            return info
    return None


def find_paired_vendor_interface(infos: list[dict], raw_interface: dict) -> dict | None:
    """Find the Telephony collection belonging to this raw-interface mouse.

    Choosing the first control collection can operate on another physical Tyon
    when two are attached, so multiple devices require an unambiguous serial
    number match.
    """
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
    """Open an already-selected HID collection without re-enumerating."""
    path = info["path"]
    if isinstance(path, str):
        path = path.encode()
    device = hid_module.device()
    device.open_path(path)
    return device


def xcal_command(function: int) -> bytes:
    """Build a non-persistent calibration-mode control report."""
    return bytes((REPORT_ID_INFO, INFO_SIZE, function, 0, 0, 0, 0, 0))


def raw_mode_marker_path() -> Path:
    """Return the per-user marker used to recover interrupted raw sessions."""
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
        self.active = False

    def _send(self, function: int, label: str, *, cleanup: bool = False) -> None:
        try:
            self.check_write(self.device, verbose=self.verbose)
        except Exception:
            if not cleanup:
                raise
        self.write_feature(
            self.device,
            xcal_command(function),
            label,
            self.verbose,
        )
        # A start report is not complete until the device accepts it. Cleanup
        # likewise verifies the end report before its recovery marker is gone.
        if cleanup or function == XCAL_START:
            self.check_write(self.device, verbose=self.verbose)

    def _write_marker(self) -> None:
        self.marker_path.parent.mkdir(parents=True, exist_ok=True)
        self.marker_path.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_utc": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def recover(self) -> bool:
        """End a possibly active prior session before starting another."""
        if not self.marker_path.exists():
            return False
        self._send(XCAL_END, "X-Celerator raw stream recovery end", cleanup=True)
        self.marker_path.unlink(missing_ok=True)
        self.active = False
        return True

    def start(self) -> None:
        if self.marker_path.exists():
            self.recover()
        self._write_marker()
        try:
            self._send(XCAL_START, "X-Celerator raw stream start")
        except BaseException:
            try:
                self.stop()
            except Exception:
                pass
            raise
        self.active = True

    def stop(self) -> bool:
        if not self.active and not self.marker_path.exists():
            return False
        self._send(XCAL_END, "X-Celerator raw stream end", cleanup=True)
        self.marker_path.unlink(missing_ok=True)
        self.active = False
        return True


def choose_device(devices: list[JoystickInfo], requested: int | None) -> JoystickInfo:
    if requested is not None:
        for device in devices:
            if device.slot == requested:
                return device
        raise RuntimeError(f"joystick slot {requested} is not available")
    if not devices:
        raise RuntimeError("no readable Windows joystick devices were found")
    tyon = [device for device in devices if "tyon" in device.name.lower()]
    if len(tyon) == 1:
        return tyon[0]
    if len(devices) == 1:
        return devices[0]
    choices = ", ".join(f"{d.slot}={d.name}" for d in devices)
    raise RuntimeError(f"multiple joysticks found ({choices}); choose one with --device")


def collect_baseline(
    read: Callable[[], Sample], seconds: float, poll_hz: float
) -> tuple[dict[str, int], int]:
    values: dict[str, list[int]] = {axis: [] for axis in AXES}
    deadline = time.perf_counter() + seconds
    interval = 1.0 / poll_hz
    count = 0
    while time.perf_counter() < deadline:
        started = time.perf_counter()
        sample = read()
        for axis in AXES:
            values[axis].append(sample.axes[axis])
        count += 1
        time.sleep(max(0.0, interval - (time.perf_counter() - started)))
    return {axis: int(statistics.median(values[axis])) for axis in AXES}, count


def default_log_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("captures") / f"tyon-xcelerator-{stamp}.csv"


def preparation_countdown(
    seconds: float,
    on_progress: ProgressCallback | None = None,
    stop_event: threading.Event | None = None,
) -> bool:
    """Wait before a capture, returning false when a stop was requested."""
    if seconds <= 0:
        return True
    deadline = time.perf_counter() + seconds
    last_displayed: int | None = None
    while True:
        if stop_event is not None and stop_event.is_set():
            return False
        remaining = max(0.0, deadline - time.perf_counter())
        displayed = max(1, int(remaining + 0.999))
        if displayed != last_displayed:
            if on_progress is not None:
                _progress(on_progress, "prepare", f"Get ready — starting in {displayed}s")
            else:
                print(f"Prepare for capture: {displayed}", flush=True)
            last_displayed = displayed
        if remaining <= 0:
            return True
        time.sleep(min(0.05, remaining))


def normal_trial_acceptance(
    trial: TrialLabel,
    *,
    input_source: str,
    event_counts: dict[str, int],
    wheel_directions: set[str],
    clean_shutdown: bool,
    profiles_preserved: bool | None,
) -> list[str]:
    """Return concrete reasons a controlled normal-mode trial did not pass."""
    if trial not in (TrialLabel.PADDLE_ONLY, TrialLabel.WHEEL_ONLY):
        return []
    issues: list[str] = []
    if input_source != "raw_input":
        issues.append(f"device-attributed Raw Input unavailable ({input_source})")
    if event_counts.get("wheel", 0) == 0:
        issues.append("no vertical wheel events recorded")
    missing = {"up", "down"} - wheel_directions
    if missing:
        issues.append("missing wheel direction(s): " + ", ".join(sorted(missing)))
    if not clean_shutdown:
        issues.append("capture sources did not shut down cleanly")
    if profiles_preserved is not True:
        issues.append("profile preservation was not verified")
    return issues


def write_row(
    writer: csv.DictWriter,
    *,
    started: float,
    timestamp: float,
    kind: str,
    sample: Sample | None = None,
    scroll_dx: int | str = "",
    scroll_dy: int | str = "",
    raw_hex: str = "",
    trial: str = "",
) -> None:
    row: dict[str, object] = {
        "elapsed_ms": round((timestamp - started) * 1000.0, 3),
        "utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "kind": kind,
        "trial": trial,
        "buttons": "",
        "pov": "",
        "scroll_dx": scroll_dx,
        "scroll_dy": scroll_dy,
        "raw_hex": raw_hex,
    }
    row.update({axis: "" for axis in AXES})
    if sample is not None:
        row.update(sample.axes)
        row["buttons"] = sample.buttons
        row["pov"] = sample.pov
    writer.writerow(row)


def run_monitor(
    args: argparse.Namespace,
    on_progress: ProgressCallback | None = None,
    stop_event: threading.Event | None = None,
    summary: dict[str, object] | None = None,
    marker_queue: queue.SimpleQueue[str] | None = None,
) -> int:
    """Run a guided normal-mode capture without entering calibration mode."""
    if not preparation_countdown(args.start_delay, on_progress, stop_event):
        return 0
    api = WinMMJoystickApi()
    devices = api.devices()
    if args.list:
        if not devices:
            print("No readable joystick devices found.")
        for device in devices:
            print(
                f"slot {device.slot}: {device.name} "
                f"({device.axes} axes, {device.buttons} buttons)"
            )
        return 0

    device = choose_device(devices, args.device)
    trial = normalized_trial_label(args.trial)
    device_control = TyonDeviceControl()
    fingerprint_before = None
    try:
        fingerprint_before = device_control.fingerprint()
        print("Captured pre-trial fingerprint for all five onboard profiles.")
    except Exception as exc:
        print(f"Warning: pre-trial profile fingerprint unavailable ({exc})")
    session = CaptureSession(
        str(uuid.uuid4()),
        trial,
        CaptureMode.NORMAL,
        fingerprint=fingerprint_before,
    )
    clock = QpcClock()
    started_stamp = clock.now()
    event_queue: queue.SimpleQueue[TelemetryEvent] = queue.SimpleQueue()
    raw_input: RawInputSource | None = None
    fallback_capture: ScrollCapture | None = None
    special_capture = SpecialReportCapture()
    default_output = default_log_path()
    filename_label = "wheel" if args.trial == "wheel" else trial.value
    default_output = default_output.with_name(
        default_output.stem.replace("tyon-xcelerator", f"tyon-{filename_label}") + ".csv"
    )
    path = Path(args.output) if args.output else default_output
    path.parent.mkdir(parents=True, exist_ok=True)
    baseline_values: dict[str, list[int]] = {axis: [] for axis in AXES}
    stats: dict[str, AxisStats] = {}
    event_counts: dict[str, int] = {}
    action_event_counts: dict[str, int] = {}
    wheel_directions: set[str] = set()
    action_wheel_directions: set[str] = set()
    samples = 0
    input_source_name = "disabled" if args.no_scroll_events else "unavailable"
    next_display = time.perf_counter()
    interval = 1.0 / args.poll_hz
    clean_shutdown = True
    profiles_preserved: bool | None = None
    capture_ended: float | None = None
    writer: CsvTelemetryWriter | None = None

    def make_event(
        source: str,
        kind: str,
        payload: dict[str, object] | None = None,
        *,
        device_id: str | None = None,
    ) -> TelemetryEvent:
        return TelemetryEvent(
            session_id=session.session_id,
            timestamp=clock.now(),
            source=source,
            kind=kind,
            phase=session.phase,
            payload=payload or {},
            device_id=device_id,
        )

    def write_event(
        writer: CsvTelemetryWriter,
        event: TelemetryEvent,
        *,
        sample: Sample | None = None,
        raw_hex: str = "",
        note: str = "",
    ) -> None:
        event_counts[event.kind] = event_counts.get(event.kind, 0) + 1
        if event.phase is Phase.ACTION:
            action_event_counts[event.kind] = action_event_counts.get(event.kind, 0) + 1
        if event.kind == "wheel":
            direction = event.payload.get("direction")
            if direction in ("up", "down"):
                wheel_directions.add(str(direction))
                if event.phase is Phase.ACTION:
                    action_wheel_directions.add(str(direction))
        writer.write_event(
            event,
            axes=sample.axes if sample is not None else None,
            buttons=sample.buttons if sample is not None else "",
            pov=sample.pov if sample is not None else "",
            raw_hex=raw_hex,
            note=note,
        )

    def drain_sources(writer: CsvTelemetryWriter) -> None:
        while True:
            try:
                write_event(writer, event_queue.get_nowait())
            except queue.Empty:
                break
        if fallback_capture is not None:
            for _timestamp, dx, dy in fallback_capture.drain():
                if dx:
                    write_event(
                        writer,
                        make_event(
                            "pynput_fallback",
                            "horizontal_wheel",
                            {"delta": dx, "direction": "right" if dx > 0 else "left"},
                        ),
                    )
                if dy:
                    write_event(
                        writer,
                        make_event(
                            "pynput_fallback",
                            "wheel",
                            {"delta": dy, "direction": "up" if dy > 0 else "down"},
                        ),
                    )
        for _timestamp, report in special_capture.drain():
            write_event(
                writer,
                make_event("mi03", "special", {"length": len(report)}),
                raw_hex=report.hex(" "),
            )
        if marker_queue is not None:
            while True:
                try:
                    note = marker_queue.get_nowait()
                except queue.Empty:
                    break
                write_event(
                    writer,
                    make_event("user", "symptom_marker"),
                    note=note or "symptom",
                )

    def stop_sources() -> None:
        errors: list[Exception] = []
        for source in (raw_input, fallback_capture, special_capture):
            if source is None:
                continue
            try:
                source.stop()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise RuntimeError("; ".join(str(exc) for exc in errors))

    def write_axis_sample(writer: CsvTelemetryWriter, sample: Sample) -> None:
        nonlocal samples
        samples += 1
        write_event(
            writer,
            make_event("winmm", "axis"),
            sample=sample,
        )

    print(f"Monitoring slot {device.slot}: {device.name}")
    print(f"Writing {path.resolve()}")
    session.prepare()

    try:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = CsvTelemetryWriter(
                handle,
                started_ns=started_stamp.monotonic_ns,
                trial=trial,
                ordered_from_sequence=started_stamp.sequence + 1,
            )
            write_event(writer, make_event("session", "phase"), note="preparation")

            if not args.no_scroll_events:
                raw_input = RawInputSource(
                    session.session_id,
                    clock,
                    lambda: session.phase,
                )
                try:
                    raw_input.start(event_queue.put)
                    input_source_name = "raw_input"
                    print("Device-attributed Windows Raw Input logging enabled.")
                except RuntimeError as exc:
                    print(f"Warning: Raw Input unavailable ({exc}); using pynput scroll fallback.")
                    raw_input = None
                    fallback_capture = ScrollCapture()
                    warning = fallback_capture.start()
                    if warning:
                        print(f"Warning: {warning}")
                    else:
                        input_source_name = "pynput_fallback"

            special_warning = special_capture.start()
            if special_warning:
                print(f"Warning: {special_warning}")
            else:
                print("Tyon MI_03 special-report logging enabled.")

            session.begin_baseline()
            write_event(writer, make_event("session", "phase"), note="baseline")
            print(
                f"Keep the paddle and wheel untouched for the {args.baseline_seconds:g}s baseline...",
                flush=True,
            )
            _progress(on_progress, "baseline", baseline_progress_message(args.baseline_seconds))
            baseline_deadline = time.perf_counter() + args.baseline_seconds
            while time.perf_counter() < baseline_deadline and not (
                stop_event is not None and stop_event.is_set()
            ):
                loop_started = time.perf_counter()
                sample = api.read(device.slot)
                write_axis_sample(writer, sample)
                for axis in AXES:
                    baseline_values[axis].append(sample.axes[axis])
                drain_sources(writer)
                time.sleep(max(0.0, interval - (time.perf_counter() - loop_started)))

            if stop_event is None or not stop_event.is_set():
                if not baseline_values[AXES[0]]:
                    raise RuntimeError("no baseline axis samples were received; capture was not started")
                baseline = {
                    axis: int(statistics.median(baseline_values[axis])) for axis in AXES
                }
                stats = {
                    axis: AxisStats(
                        baseline=baseline[axis], away_threshold=args.away_threshold
                    )
                    for axis in AXES
                }
                print(
                    "Baseline: "
                    + " ".join(f"{axis}={baseline[axis]}" for axis in AXES)
                    + f" ({len(baseline_values[AXES[0]])} samples)"
                )
                session.begin_action()
                instruction = action_progress_message(args)
                print(f"GO: {instruction}")
                _progress(on_progress, "action", instruction)
                write_event(writer, make_event("session", "phase"), note="action")
                action_started = time.perf_counter()
                deadline = action_started + args.duration if args.duration else None
                while (deadline is None or time.perf_counter() < deadline) and not (
                    stop_event is not None and stop_event.is_set()
                ):
                    loop_started = time.perf_counter()
                    sample = api.read(device.slot)
                    write_axis_sample(writer, sample)
                    for axis in AXES:
                        stats[axis].add(sample.timestamp, sample.axes[axis])
                    drain_sources(writer)
                    if time.perf_counter() >= next_display:
                        values = " ".join(
                            f"{axis}={sample.axes[axis]:5d}({sample.axes[axis] - baseline[axis]:+6d})"
                            for axis in AXES
                        )
                        wheels = event_counts.get("wheel", 0)
                        print(f"\r{values} wheel={wheels:4d}", end="", flush=True)
                        next_display = time.perf_counter() + 1.0 / args.display_hz
                    time.sleep(max(0.0, interval - (time.perf_counter() - loop_started)))
            drain_sources(writer)

            try:
                stop_sources()
                drain_sources(writer)
                capture_ended = time.perf_counter()
            except Exception as exc:
                clean_shutdown = False
                print(f"Warning: capture source cleanup failed ({exc})", file=sys.stderr)

            if fingerprint_before is not None:
                try:
                    fingerprint_after = device_control.fingerprint()
                    profiles_preserved = fingerprint_after == fingerprint_before
                    write_event(
                        writer,
                        make_event(
                            "device_control",
                            "profile_check",
                            {"preserved": profiles_preserved},
                        ),
                        note="all five profile settings/button maps",
                    )
                    if profiles_preserved:
                        print("All five onboard profile fingerprints are unchanged.")
                    else:
                        print("CRITICAL: an onboard profile fingerprint changed.", file=sys.stderr)
                except Exception as exc:
                    print(f"Warning: post-trial profile fingerprint unavailable ({exc})")

            if stop_event is not None and stop_event.is_set():
                result = session.cancel(clean_shutdown=clean_shutdown)
            else:
                session.stop()
                write_event(writer, make_event("session", "phase"), note="stopping")
                result = session.complete(clean_shutdown=clean_shutdown)
                write_event(writer, make_event("session", "completed"), note=result.state.value)
            writer.flush_ordered(force=True)
    except KeyboardInterrupt:
        try:
            stop_sources()
            result = session.cancel(clean_shutdown=clean_shutdown)
            if writer is not None:
                drain_sources(writer)
                write_event(writer, make_event("session", "cancelled"), note=result.state.value)
                writer.flush_ordered(force=True)
        except Exception:
            pass
    except BaseException as exc:
        try:
            clean_shutdown = False
            stop_sources()
            if session.state not in (SessionState.COMPLETED, SessionState.CANCELLED, SessionState.FAILED):
                result = session.fail(str(exc), clean_shutdown=False)
                if writer is not None:
                    drain_sources(writer)
                    write_event(writer, make_event("session", "failed"), note=result.error or "failed")
                    writer.flush_ordered(force=True)
        except Exception:
            pass
        raise
    finally:
        try:
            stop_sources()
        except Exception:
            pass
        ended = capture_ended or time.perf_counter()
        for item in stats.values():
            item.finish(ended)
        print()

    duration = max(0.001, ended - started_stamp.monotonic_ns / 1_000_000_000.0)
    scroll_events = event_counts.get("wheel", 0) + event_counts.get("horizontal_wheel", 0)
    print(f"Captured {samples} axis samples and {scroll_events} wheel events over {duration:.2f}s.")
    primary = "?"
    if stats:
        print("Axis summary (baseline, min..max, span, time away, longest away, returns):")
        for axis in AXES:
            item = stats[axis]
            away_seconds = item.away_samples / args.poll_hz
            print(
                f"  {axis}: {item.baseline:5d}, {item.minimum:5d}..{item.maximum:5d}, "
                f"span={item.span:5d}, away={away_seconds:6.2f}s, "
                f"longest={item.longest_away_seconds:6.2f}s, returns={item.return_count}"
            )
        primary = max(AXES, key=lambda axis: stats[axis].span)
        print(f"Largest-changing axis: {primary} (span {stats[primary].span})")
    print(f"Capture saved: {path.resolve()}")
    acceptance_issues = normal_trial_acceptance(
        trial,
        input_source=input_source_name,
        event_counts=action_event_counts,
        wheel_directions=action_wheel_directions,
        clean_shutdown=clean_shutdown,
        profiles_preserved=profiles_preserved,
    )
    if acceptance_issues:
        print("CONTROLLED TRIAL DID NOT PASS:", file=sys.stderr)
        for issue in acceptance_issues:
            print(f"  - {issue}", file=sys.stderr)
    if summary is not None:
        summary.update({
            "samples": samples,
            "scroll_events": scroll_events,
            "primary_axis": primary,
            "primary_span": stats[primary].span if primary in stats else 0,
            "input_source": input_source_name,
            "event_counts": dict(event_counts),
            "action_event_counts": dict(action_event_counts),
            "session_id": session.session_id,
            "clean_shutdown": clean_shutdown,
            "profiles_preserved": profiles_preserved,
            "wheel_directions": sorted(action_wheel_directions),
            "acceptance_issues": acceptance_issues,
        })
    if profiles_preserved is False:
        return 4
    return 5 if acceptance_issues else 0


def run_raw_monitor(
    args: argparse.Namespace,
    on_progress: ProgressCallback | None = None,
    stop_event: threading.Event | None = None,
    summary: dict[str, object] | None = None,
) -> int:
    """Temporarily stream raw paddle reports without saving calibration."""
    try:
        import hid
        from tyon_rgb import check_write, enumerate_tyon, write_feature
    except Exception as exc:
        raise RuntimeError(f"raw mode requires the project's hidapi dependency ({exc})") from exc

    infos = enumerate_tyon()
    raw_info = find_raw_interface(infos)
    if raw_info is None:
        raise RuntimeError("Tyon MI_03 raw-report interface was not found")
    vendor_info = find_paired_vendor_interface(infos, raw_info)
    if vendor_info is None:
        raise RuntimeError(
            "could not pair the MI_03 raw interface with exactly one Telephony control interface; "
            "disconnect other Tyons before raw capture"
        )

    raw_device = None
    vendor_device = None
    raw_lifecycle: RawModeLifecycle | None = None
    capture = ScrollCapture()
    default_output = default_log_path()
    output = Path(args.output) if args.output else default_output.with_name(
        default_output.stem.replace("tyon-xcelerator", "tyon-xcelerator-raw") + ".csv"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "elapsed_ms", "utc", "kind", "trial", "raw_value", "raw_hex",
        "scroll_dx", "scroll_dy",
    ]
    values: list[int] = []
    baseline_values: list[int] = []
    scroll_events = 0
    unmatched = 0
    started = 0.0
    deadline = None
    next_display = 0.0
    clean_shutdown = True

    def write_raw_row(
        writer: csv.DictWriter,
        timestamp: float,
        kind: str,
        *,
        value: int | str = "",
        raw_hex: str = "",
        dx: int | str = "",
        dy: int | str = "",
    ) -> None:
        writer.writerow({
            "elapsed_ms": round((timestamp - started) * 1000.0, 3),
            "utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "kind": kind,
            "trial": args.trial,
            "raw_value": value,
            "raw_hex": raw_hex,
            "scroll_dx": dx,
            "scroll_dy": dy,
        })

    print("RAW MODE: no calibration values will be saved.")
    print(f"Writing {output.resolve()}")
    if not preparation_countdown(args.start_delay, on_progress, stop_event):
        return 0
    try:
        raw_device = open_hid_interface(hid, raw_info)
        vendor_device = open_hid_interface(hid, vendor_info)
        device_name = "Tyon"
        print(f"Opened {device_name} vendor control and MI_03 raw input interfaces.")
        raw_lifecycle = RawModeLifecycle(
            device=vendor_device,
            marker_path=raw_mode_marker_path(),
            check_write=check_write,
            write_feature=write_feature,
            verbose=args.verbose,
        )
        if raw_lifecycle.marker_path.exists():
            print("Recovering an unclean prior raw-mode session before capture.")
        raw_lifecycle.start()
        started = time.perf_counter()
        deadline = started + args.duration if args.duration else None
        next_display = started
        print(
            f"Leave the paddle untouched for {args.baseline_seconds:g}s, then move and release it. "
            "Press Ctrl+C to stop."
        )
        _progress(on_progress, "baseline", baseline_progress_message(args.baseline_seconds))
        if not args.no_scroll_events:
            warning = capture.start()
            if warning:
                print(f"Warning: {warning}")

        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            action_announced = False
            while (deadline is None or time.perf_counter() < deadline) and not (
                stop_event is not None and stop_event.is_set()
            ):
                report = raw_device.read(64, 25)
                now = time.perf_counter()
                if report:
                    value = parse_xcelerator_report(report)
                    if value is None:
                        unmatched += 1
                        write_raw_row(writer, now, "other_report", raw_hex=bytes(report).hex(" "))
                    else:
                        values.append(value)
                        if now - started <= args.baseline_seconds:
                            baseline_values.append(value)
                        write_raw_row(writer, now, "raw", value=value,
                                      raw_hex=bytes(report).hex(" "))
                        if now >= next_display:
                            base = int(statistics.median(baseline_values)) if baseline_values else value
                            print(f"\rraw={value:3d} delta={value - base:+4d} reports={len(values):6d} "
                                  f"scroll={scroll_events:4d}", end="", flush=True)
                            next_display = now + 1.0 / args.display_hz
                if not action_announced and now - started >= args.baseline_seconds:
                    instruction = action_progress_message(args)
                    print(f"\nGO: {instruction}")
                    _progress(on_progress, "action", instruction)
                    action_announced = True
                for timestamp, dx, dy in capture.drain():
                    scroll_events += 1
                    write_raw_row(writer, timestamp, "scroll", dx=dx, dy=dy)
            for timestamp, dx, dy in capture.drain():
                scroll_events += 1
                write_raw_row(writer, timestamp, "scroll", dx=dx, dy=dy)
    except KeyboardInterrupt:
        pass
    finally:
        capture.stop()
        print()
        if raw_lifecycle is not None:
            try:
                if raw_lifecycle.stop():
                    print("Raw calibration-report mode ended; no calibration data was saved.")
            except Exception as exc:
                clean_shutdown = False
                print(f"CRITICAL: could not end raw mode cleanly: {exc}", file=sys.stderr)
                print(
                    f"Recovery marker retained at {raw_lifecycle.marker_path}. "
                    "Reconnect the mouse and start another capture to retry cleanup.",
                    file=sys.stderr,
                )
        try:
            if raw_device is not None:
                raw_device.close()
        except Exception:
            pass
        if vendor_device is not None:
            try:
                vendor_device.close()
            except Exception:
                pass

    if values:
        baseline = int(statistics.median(baseline_values)) if baseline_values else values[0]
        baseline_span = (
            max(baseline_values) - min(baseline_values) if baseline_values else 0
        )
        print(
            f"Captured {len(values)} raw reports: baseline={baseline}, "
            f"baseline span={baseline_span}, full range={min(values)}..{max(values)}, "
            f"scroll events={scroll_events}, unmatched reports={unmatched}."
        )
        if summary is not None:
            summary.update({
                "reports": len(values),
                "baseline": baseline,
                "baseline_span": baseline_span,
                "raw_range": (min(values), max(values)),
                "scroll_events": scroll_events,
                "unmatched": unmatched,
                "clean_shutdown": clean_shutdown,
            })
    else:
        print(f"No X-Celerator raw reports received; unmatched reports={unmatched}.")
        if summary is not None:
            summary.update({"reports": 0, "scroll_events": scroll_events, "unmatched": unmatched,
                            "clean_shutdown": clean_shutdown})
    print(f"Capture saved: {output.resolve()}")
    if not clean_shutdown:
        return 6
    return 0 if values else 3


def capture_output_path(request: CaptureRequest) -> Path:
    """Return the normal timestamped filename for a compact-window capture."""
    output = default_log_path()
    if request.raw:
        name = output.stem.replace("tyon-xcelerator", "tyon-xcelerator-raw")
    else:
        filename_label = "wheel" if request.trial == "wheel" else request.label.value
        name = output.stem.replace("tyon-xcelerator", f"tyon-{filename_label}")
    return output.with_name(name + output.suffix)


def run_capture(
    request: CaptureRequest,
    on_progress: ProgressCallback | None = None,
    stop_event: threading.Event | None = None,
    marker_queue: queue.SimpleQueue[str] | None = None,
) -> CaptureResult:
    """Run a compact-window request through the existing monitor implementation."""
    stop_event = stop_event or threading.Event()
    output = capture_output_path(request)
    if not preparation_countdown(request.start_delay_seconds, on_progress, stop_event):
        return CaptureResult(request, output, True, 0, {})

    args = monitor_args_for_request(request, str(output))
    summary: dict[str, object] = {}
    runner = run_raw_monitor if request.raw else run_monitor
    if request.raw:
        exit_code = runner(args, on_progress, stop_event, summary)
    else:
        exit_code = runner(args, on_progress, stop_event, summary, marker_queue)
    return CaptureResult(
        request=request,
        output=output,
        cancelled=stop_event.is_set(),
        exit_code=exit_code,
        summary=summary,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ROCCAT Tyon X-Celerator signal and scroll diagnostic monitor"
    )
    parser.add_argument("--list", action="store_true", help="list readable joystick slots")
    parser.add_argument("--raw", action="store_true",
                        help="temporarily stream raw 0..255 paddle reports; never saves calibration")
    parser.add_argument(
        "--trial",
        choices=(
            "paddle",
            "wheel",
            "neutral",
            "paddle_only",
            "wheel_only",
            "symptom_reproduction",
            "general_observation",
        ),
        default="paddle",
                        help="labels/instructions for the controlled input trial")
    parser.add_argument("--device", type=int, help="Windows joystick slot (auto if unambiguous)")
    parser.add_argument("--duration", type=float, default=0.0,
                        help="capture seconds; 0 means until Ctrl+C (raw mode includes its baseline window)")
    parser.add_argument("--start-delay", type=int, default=0,
                        help="pre-capture countdown seconds")
    parser.add_argument("--poll-hz", type=float, default=250.0,
                        help="axis samples per second (default: 250)")
    parser.add_argument("--display-hz", type=float, default=5.0,
                        help="console refreshes per second (default: 5)")
    parser.add_argument("--baseline-seconds", type=float, default=2.0,
                        help="untouched baseline duration (default: 2)")
    parser.add_argument("--away-threshold", type=int, default=1500,
                        help="distance from baseline counted as away (default: 1500)")
    parser.add_argument("--no-scroll-events", action="store_true",
                        help="do not capture global scroll events with pynput")
    parser.add_argument("--output", help="CSV output path (default: timestamped captures/ file)")
    parser.add_argument("--verbose", action="store_true", help="show HID control reports in raw mode")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.poll_hz <= 0 or args.display_hz <= 0:
        raise SystemExit("--poll-hz and --display-hz must be positive")
    if args.baseline_seconds <= 0:
        raise SystemExit("--baseline-seconds must be positive")
    if args.duration < 0:
        raise SystemExit("--duration cannot be negative")
    if args.start_delay < 0:
        raise SystemExit("--start-delay cannot be negative")
    if args.raw and args.trial not in ("paddle", "neutral") and not args.list:
        parser.error("--raw only supports paddle or neutral trials")
    try:
        if args.list:
            return run_monitor(args)
        return run_raw_monitor(args) if args.raw else run_monitor(args)
    except (OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
