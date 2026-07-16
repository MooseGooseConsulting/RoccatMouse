"""Windows Tyon control adapter for read-only fingerprints and raw lifecycle delegation."""

from __future__ import annotations

import hashlib
from typing import Any, Callable

from ..models import DeviceFingerprint

OpenDevice = Callable[[], tuple[Any, str]]
ProfileReader = Callable[[Any, int, bool], bytes | bytearray]


class TyonDeviceControl:
    def __init__(
        self,
        *,
        open_device: OpenDevice | None = None,
        read_settings: ProfileReader | None = None,
        read_buttons: ProfileReader | None = None,
        profile_count: int = 5,
        raw_lifecycle: Any | None = None,
    ) -> None:
        self._open_device = open_device
        self._read_settings = read_settings
        self._read_buttons = read_buttons
        self.profile_count = profile_count
        self.raw_lifecycle = raw_lifecycle

    def _profile_functions(self) -> tuple[OpenDevice, ProfileReader, ProfileReader]:
        if self._open_device and self._read_settings and self._read_buttons:
            return self._open_device, self._read_settings, self._read_buttons
        from tyon_rgb import open_tyon, read_profile_buttons, read_profile_settings

        return (
            self._open_device or open_tyon,
            self._read_settings or read_profile_settings,
            self._read_buttons or read_profile_buttons,
        )

    def fingerprint(self) -> DeviceFingerprint:
        open_device, read_settings, read_buttons = self._profile_functions()
        device, name = open_device()
        hashes: list[str] = []
        try:
            for profile in range(self.profile_count):
                digest = hashlib.sha256()
                digest.update(bytes(read_settings(device, profile, False)))
                digest.update(b"\x00ROCCATMOUSE-PROFILE-BOUNDARY\x00")
                digest.update(bytes(read_buttons(device, profile, False)))
                hashes.append(digest.hexdigest())
        finally:
            device.close()
        return DeviceFingerprint(name, tuple(hashes))

    def recover(self) -> bool:
        if self.raw_lifecycle is None:
            return False
        return bool(self.raw_lifecycle.recover())

    def start_raw(self) -> None:
        if self.raw_lifecycle is None:
            raise RuntimeError("raw lifecycle is not attached to this device-control instance")
        self.raw_lifecycle.start()

    def stop_raw(self) -> bool:
        if self.raw_lifecycle is None:
            return False
        return bool(self.raw_lifecycle.stop())
