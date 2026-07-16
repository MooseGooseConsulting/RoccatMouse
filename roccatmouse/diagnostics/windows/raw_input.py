"""Device-attributed Win32 Raw Input source for relative mouse events."""

from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

from ..contracts import Clock, EventEmitter
from ..models import Phase, TelemetryEvent

RIM_TYPEMOUSE = 0
RID_INPUT = 0x10000003
RIDI_DEVICENAME = 0x20000007
RIDEV_INPUTSINK = 0x00000100
WM_INPUT = 0x00FF
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_QUIT = 0x0012
MOUSE_MOVE_ABSOLUTE = 0x0001

RI_MOUSE_BUTTON_1_DOWN = 0x0001
RI_MOUSE_BUTTON_1_UP = 0x0002
RI_MOUSE_BUTTON_2_DOWN = 0x0004
RI_MOUSE_BUTTON_2_UP = 0x0008
RI_MOUSE_BUTTON_3_DOWN = 0x0010
RI_MOUSE_BUTTON_3_UP = 0x0020
RI_MOUSE_BUTTON_4_DOWN = 0x0040
RI_MOUSE_BUTTON_4_UP = 0x0080
RI_MOUSE_BUTTON_5_DOWN = 0x0100
RI_MOUSE_BUTTON_5_UP = 0x0200
RI_MOUSE_WHEEL = 0x0400
RI_MOUSE_HWHEEL = 0x0800

_BUTTON_FLAGS = (
    (RI_MOUSE_BUTTON_1_DOWN, "left", True),
    (RI_MOUSE_BUTTON_1_UP, "left", False),
    (RI_MOUSE_BUTTON_2_DOWN, "right", True),
    (RI_MOUSE_BUTTON_2_UP, "right", False),
    (RI_MOUSE_BUTTON_3_DOWN, "middle", True),
    (RI_MOUSE_BUTTON_3_UP, "middle", False),
    (RI_MOUSE_BUTTON_4_DOWN, "x1", True),
    (RI_MOUSE_BUTTON_4_UP, "x1", False),
    (RI_MOUSE_BUTTON_5_DOWN, "x2", True),
    (RI_MOUSE_BUTTON_5_UP, "x2", False),
)


@dataclass(frozen=True, slots=True)
class RawMousePacket:
    device_id: str
    dx: int = 0
    dy: int = 0
    button_flags: int = 0
    button_data: int = 0
    flags: int = 0


def _signed_word(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def parse_raw_mouse(packet: RawMousePacket) -> list[tuple[str, dict[str, object]]]:
    """Convert a RAWMOUSE packet into platform-neutral relative events."""
    events: list[tuple[str, dict[str, object]]] = []
    if not packet.flags & MOUSE_MOVE_ABSOLUTE and (packet.dx or packet.dy):
        events.append(("relative_move", {"dx": packet.dx, "dy": packet.dy}))

    for flag, button, pressed in _BUTTON_FLAGS:
        if packet.button_flags & flag:
            events.append(("button", {"button": button, "pressed": pressed}))

    if packet.button_flags & RI_MOUSE_WHEEL:
        delta = _signed_word(packet.button_data)
        if delta:
            events.append(
                ("wheel", {"delta": delta, "direction": "up" if delta > 0 else "down"})
            )
    if packet.button_flags & RI_MOUSE_HWHEEL:
        delta = _signed_word(packet.button_data)
        if delta:
            events.append(
                (
                    "horizontal_wheel",
                    {"delta": delta, "direction": "right" if delta > 0 else "left"},
                )
            )
    return events


def is_tyon_device_name(name: str) -> bool:
    normalized = name.lower()
    return "vid_1e7d" in normalized and ("pid_2e4a" in normalized or "pid_2e4b" in normalized)


class RawInputSource:
    """Run a message-only Win32 window and emit Tyon-attributed Raw Input events."""

    def __init__(
        self,
        session_id: str,
        clock: Clock,
        phase: Callable[[], Phase],
        *,
        device_matcher: Callable[[str], bool] = is_tyon_device_name,
    ) -> None:
        self.session_id = session_id
        self.clock = clock
        self.phase = phase
        self.device_matcher = device_matcher
        self._emit: EventEmitter | None = None
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._device_names: dict[int, str] = {}
        self.dropped_packets = 0

    def start(self, emit: EventEmitter) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Raw Input capture is available only on Windows")
        if self._thread is not None:
            raise RuntimeError("Raw Input capture is already running")
        self._emit = emit
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._message_loop, name="tyon-raw-input", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            try:
                self.stop()
            except Exception as cleanup_exc:
                raise RuntimeError(
                    f"Raw Input window did not start; cleanup failed: {cleanup_exc}"
                ) from cleanup_exc
            raise RuntimeError("Raw Input window did not start")
        if self._error is not None:
            error = self._error
            thread = self._thread
            if thread is not None:
                thread.join(timeout=5)
            self._thread = None
            self._thread_id = 0
            if thread is not None and thread.is_alive():
                raise RuntimeError(
                    f"Raw Input startup failed: {error}; thread did not stop"
                ) from error
            raise RuntimeError(f"Raw Input startup failed: {error}") from error

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("Raw Input thread did not stop")
        failure = self._error
        self._thread = None
        self._thread_id = 0
        if failure is not None:
            raise RuntimeError(f"Raw Input capture failed: {failure}") from failure

    def _emit_packet(self, packet: RawMousePacket) -> None:
        if not self.device_matcher(packet.device_id) or self._emit is None:
            return
        for kind, payload in parse_raw_mouse(packet):
            self._emit(
                TelemetryEvent(
                    session_id=self.session_id,
                    timestamp=self.clock.now(),
                    source="raw_input",
                    kind=kind,
                    phase=self.phase(),
                    payload=payload,
                    device_id=packet.device_id,
                )
            )

    def _message_loop(self) -> None:
        try:
            self._run_message_loop()
        except BaseException as exc:
            self._error = exc
            self._ready.set()

    def _run_message_loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HANDLE,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.UnregisterClassW.restype = wintypes.BOOL
        user32.GetRawInputData.argtypes = [
            wintypes.HANDLE,
            wintypes.UINT,
            wintypes.LPVOID,
            ctypes.POINTER(wintypes.UINT),
            wintypes.UINT,
        ]
        user32.GetRawInputData.restype = wintypes.UINT
        user32.GetRawInputDeviceInfoW.restype = wintypes.UINT
        user32.PostThreadMessageW.argtypes = [
            wintypes.DWORD,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self._thread_id = kernel32.GetCurrentThreadId()

        wndproc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )

        class WindowClass(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", wndproc_type),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        class RawInputDevice(ctypes.Structure):
            _fields_ = [
                ("usUsagePage", wintypes.USHORT),
                ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD),
                ("hwndTarget", wintypes.HWND),
            ]

        class RawInputHeader(ctypes.Structure):
            _fields_ = [
                ("dwType", wintypes.DWORD),
                ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE),
                ("wParam", wintypes.WPARAM),
            ]

        class RawMouse(ctypes.Structure):
            _fields_ = [
                ("usFlags", wintypes.USHORT),
                ("_padding", wintypes.USHORT),
                ("ulButtons", wintypes.ULONG),
                ("ulRawButtons", wintypes.ULONG),
                ("lLastX", wintypes.LONG),
                ("lLastY", wintypes.LONG),
                ("ulExtraInformation", wintypes.ULONG),
            ]

        def device_name(handle: int) -> str:
            if handle in self._device_names:
                return self._device_names[handle]
            size = wintypes.UINT(0)
            user32.GetRawInputDeviceInfoW(wintypes.HANDLE(handle), RIDI_DEVICENAME, None, ctypes.byref(size))
            buffer = ctypes.create_unicode_buffer(size.value + 1)
            result = user32.GetRawInputDeviceInfoW(
                wintypes.HANDLE(handle), RIDI_DEVICENAME, buffer, ctypes.byref(size)
            )
            name = buffer.value if result != 0xFFFFFFFF else f"handle:{handle}"
            self._device_names[handle] = name
            return name

        def read_packet(lparam: int) -> None:
            size = wintypes.UINT(0)
            header_size = ctypes.sizeof(RawInputHeader)
            if user32.GetRawInputData(lparam, RID_INPUT, None, ctypes.byref(size), header_size) == 0xFFFFFFFF:
                self.dropped_packets += 1
                return
            buffer = ctypes.create_string_buffer(size.value)
            if user32.GetRawInputData(lparam, RID_INPUT, buffer, ctypes.byref(size), header_size) == 0xFFFFFFFF:
                self.dropped_packets += 1
                return
            header = RawInputHeader.from_buffer_copy(buffer.raw[:header_size])
            if header.dwType != RIM_TYPEMOUSE:
                return
            mouse = RawMouse.from_buffer_copy(
                buffer.raw[header_size : header_size + ctypes.sizeof(RawMouse)]
            )
            handle = int(header.hDevice or 0)
            self._emit_packet(
                RawMousePacket(
                    device_id=device_name(handle),
                    dx=mouse.lLastX,
                    dy=mouse.lLastY,
                    button_flags=mouse.ulButtons & 0xFFFF,
                    button_data=(mouse.ulButtons >> 16) & 0xFFFF,
                    flags=mouse.usFlags,
                )
            )

        @wndproc_type
        def wndproc(hwnd, message, wparam, lparam):
            try:
                if message == WM_INPUT:
                    read_packet(lparam)
                    return 0
                if message == WM_CLOSE:
                    user32.DestroyWindow(hwnd)
                    return 0
                if message == WM_DESTROY:
                    user32.PostQuitMessage(0)
                    return 0
            except Exception:
                self.dropped_packets += 1
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        instance = kernel32.GetModuleHandleW(None)
        class_name = f"RoccatMouseRawInput_{id(self):x}"
        window_class = WindowClass(lpfnWndProc=wndproc, hInstance=instance, lpszClassName=class_name)
        atom = user32.RegisterClassW(ctypes.byref(window_class))
        if not atom:
            raise ctypes.WinError()
        hwnd_message = wintypes.HWND(-3)
        hwnd = user32.CreateWindowExW(
            0, class_name, class_name, 0, 0, 0, 0, 0, hwnd_message, None, instance, None
        )
        if not hwnd:
            user32.UnregisterClassW(class_name, instance)
            raise ctypes.WinError()
        registration = RawInputDevice(0x01, 0x02, RIDEV_INPUTSINK, hwnd)
        if not user32.RegisterRawInputDevices(
            ctypes.byref(registration), 1, ctypes.sizeof(RawInputDevice)
        ):
            user32.DestroyWindow(hwnd)
            user32.UnregisterClassW(class_name, instance)
            raise ctypes.WinError()
        self._ready.set()
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if user32.IsWindow(hwnd):
                user32.DestroyWindow(hwnd)
            user32.UnregisterClassW(class_name, instance)
