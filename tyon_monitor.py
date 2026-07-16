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


@dataclass(frozen=True)
class CaptureRequest:
    """The fixed timing and mode used by the compact capture window."""

    trial: str
    start_delay_seconds: float = 1.0
    baseline_seconds: float = 2.0
    action_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.trial not in ("paddle", "wheel"):
            raise ValueError("trial must be 'paddle' or 'wheel'")
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
    if args.trial == "wheel":
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

        self._listener = mouse.Listener(on_scroll=on_scroll)
        self._listener.start()
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
        if cleanup:
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
    while True:
        if stop_event is not None and stop_event.is_set():
            return False
        remaining = max(0.0, deadline - time.perf_counter())
        if on_progress is not None:
            _progress(on_progress, "prepare", f"Get ready — starting in {max(1, round(remaining))}s")
        else:
            print(f"Prepare for capture: {max(1, round(remaining))}", flush=True)
        if remaining <= 0:
            return True
        time.sleep(min(0.05, remaining))


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
) -> int:
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
    read = lambda: api.read(device.slot)
    print(f"Monitoring slot {device.slot}: {device.name}")
    print(
        f"Keep the paddle untouched for the {args.baseline_seconds:g}s baseline...",
        flush=True,
    )
    _progress(on_progress, "baseline", baseline_progress_message(args.baseline_seconds))
    baseline, baseline_samples = collect_baseline(
        read, args.baseline_seconds, args.poll_hz
    )
    if stop_event is not None and stop_event.is_set():
        return 0
    print(
        "Baseline: "
        + " ".join(f"{axis}={baseline[axis]}" for axis in AXES)
        + f" ({baseline_samples} samples)"
    )

    capture = ScrollCapture()
    special_capture = SpecialReportCapture()
    if not args.no_scroll_events:
        warning = capture.start()
        if warning:
            print(f"Warning: {warning}")
        else:
            print("Windows scroll-event logging enabled.")
    special_warning = special_capture.start()
    if special_warning:
        print(f"Warning: {special_warning}")
    else:
        print("Tyon MI_03 special-report logging enabled.")

    default_output = default_log_path()
    if args.trial == "wheel":
        default_output = default_output.with_name(
            default_output.stem.replace("tyon-xcelerator", "tyon-wheel") + ".csv"
        )
    path = Path(args.output) if args.output else default_output
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "elapsed_ms", "utc", "kind", "trial", *AXES, "buttons", "pov",
        "scroll_dx", "scroll_dy", "raw_hex",
    ]
    stats = {
        axis: AxisStats(baseline=baseline[axis], away_threshold=args.away_threshold)
        for axis in AXES
    }
    scroll_events = 0
    samples = 0
    started = time.perf_counter()
    deadline = started + args.duration if args.duration else None
    next_display = started
    interval = 1.0 / args.poll_hz
    last_sample: Sample | None = None

    print(f"Writing {path.resolve()}")
    if args.trial == "wheel":
        print("Use ONLY the physical wheel up/down now. Do not touch the paddle.")
    else:
        print("Move and release the paddle normally. Press Ctrl+C to stop.")
    _progress(
        on_progress,
        "action",
        action_progress_message(args),
    )
    try:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            while (deadline is None or time.perf_counter() < deadline) and not (
                stop_event is not None and stop_event.is_set()
            ):
                loop_started = time.perf_counter()
                sample = read()
                last_sample = sample
                samples += 1
                write_row(writer, started=started, timestamp=sample.timestamp,
                          kind="sample", sample=sample, trial=args.trial)
                for axis in AXES:
                    stats[axis].add(sample.timestamp, sample.axes[axis])
                for timestamp, dx, dy in capture.drain():
                    scroll_events += 1
                    write_row(writer, started=started, timestamp=timestamp,
                              kind="scroll", scroll_dx=dx, scroll_dy=dy,
                              trial=args.trial)
                for timestamp, report in special_capture.drain():
                    write_row(writer, started=started, timestamp=timestamp,
                              kind="special", raw_hex=report.hex(" "),
                              trial=args.trial)
                if sample.timestamp >= next_display:
                    values = " ".join(
                        f"{axis}={sample.axes[axis]:5d}({sample.axes[axis] - baseline[axis]:+6d})"
                        for axis in AXES
                    )
                    print(f"\r{values} scroll={scroll_events:4d}", end="", flush=True)
                    next_display = sample.timestamp + 1.0 / args.display_hz
                time.sleep(max(0.0, interval - (time.perf_counter() - loop_started)))
            for timestamp, dx, dy in capture.drain():
                scroll_events += 1
                write_row(writer, started=started, timestamp=timestamp,
                          kind="scroll", scroll_dx=dx, scroll_dy=dy,
                          trial=args.trial)
            for timestamp, report in special_capture.drain():
                write_row(writer, started=started, timestamp=timestamp,
                          kind="special", raw_hex=report.hex(" "),
                          trial=args.trial)
    except KeyboardInterrupt:
        pass
    finally:
        capture.stop()
        special_capture.stop()
        ended = time.perf_counter()
        for item in stats.values():
            item.finish(ended)
        print()

    duration = max(0.001, (last_sample.timestamp if last_sample else ended) - started)
    print(f"Captured {samples} samples and {scroll_events} scroll events over {duration:.2f}s.")
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
    if summary is not None:
        summary.update({
            "samples": samples,
            "scroll_events": scroll_events,
            "primary_axis": primary,
            "primary_span": stats[primary].span,
        })
    return 0


def run_raw_monitor(
    args: argparse.Namespace,
    on_progress: ProgressCallback | None = None,
    stop_event: threading.Event | None = None,
    summary: dict[str, object] | None = None,
) -> int:
    """Temporarily stream raw paddle reports without saving calibration."""
    try:
        import hid
        from tyon_rgb import check_write, enumerate_tyon, open_tyon, write_feature
    except Exception as exc:
        raise RuntimeError(f"raw mode requires the project's hidapi dependency ({exc})") from exc

    infos = enumerate_tyon()
    chosen = find_raw_interface(infos)
    if chosen is None:
        raise RuntimeError("Tyon MI_03 raw-report interface was not found")
    path_value = chosen["path"]
    if isinstance(path_value, str):
        path_value = path_value.encode()

    raw_device = hid.device()
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
        raw_device.open_path(path_value)
        vendor_device, device_name = open_tyon()
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
                print(f"CRITICAL: could not end raw mode cleanly: {exc}", file=sys.stderr)
                print(
                    f"Recovery marker retained at {raw_lifecycle.marker_path}. "
                    "Reconnect the mouse and start another capture to retry cleanup.",
                    file=sys.stderr,
                )
        try:
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
            })
    else:
        print(f"No X-Celerator raw reports received; unmatched reports={unmatched}.")
        if summary is not None:
            summary.update({"reports": 0, "scroll_events": scroll_events, "unmatched": unmatched})
    print(f"Capture saved: {output.resolve()}")
    return 0 if values else 3


def capture_output_path(request: CaptureRequest) -> Path:
    """Return the normal timestamped filename for a compact-window capture."""
    output = default_log_path()
    if request.raw:
        name = output.stem.replace("tyon-xcelerator", "tyon-xcelerator-raw")
    else:
        name = output.stem.replace("tyon-xcelerator", "tyon-wheel")
    return output.with_name(name + output.suffix)


def run_capture(
    request: CaptureRequest,
    on_progress: ProgressCallback | None = None,
    stop_event: threading.Event | None = None,
) -> CaptureResult:
    """Run a compact-window request through the existing monitor implementation."""
    stop_event = stop_event or threading.Event()
    output = capture_output_path(request)
    if not preparation_countdown(request.start_delay_seconds, on_progress, stop_event):
        return CaptureResult(request, output, True, 0, {})

    args = monitor_args_for_request(request, str(output))
    summary: dict[str, object] = {}
    runner = run_raw_monitor if request.raw else run_monitor
    exit_code = runner(args, on_progress, stop_event, summary)
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
    parser.add_argument("--trial", choices=("paddle", "wheel"), default="paddle",
                        help="labels/instructions for the controlled input trial")
    parser.add_argument("--device", type=int, help="Windows joystick slot (auto if unambiguous)")
    parser.add_argument("--duration", type=float, default=0.0,
                        help="capture seconds; 0 means until Ctrl+C")
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
    if args.raw and args.trial != "paddle" and not args.list:
        parser.error("--raw only supports --trial paddle")
    try:
        if args.list:
            return run_monitor(args)
        return run_raw_monitor(args) if args.raw else run_monitor(args)
    except (OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
