"""Thread-safe ownership arbitration for mutually exclusive device sessions."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from .models import RuntimeMode


class SessionArbiterError(RuntimeError):
    """Base class for device-session arbitration failures."""


class SessionBusyError(SessionArbiterError):
    """Raised when another session already owns or must recover the device."""


class SessionOwnershipError(SessionArbiterError):
    """Raised when a stale or unrelated owner attempts a transition."""


@dataclass(frozen=True, slots=True)
class DeviceSessionOwnership:
    mode: RuntimeMode
    owner_id: str | None
    resume_normal_owner_id: str | None


class DeviceSessionArbiter:
    """Represent the single normal/raw owner of one physical device.

    Raw acquisition can either begin from stopped or use an explicit handoff
    from the current normal owner. Unverified cleanup is sticky: no acquisition
    is possible until the recovering owner reports verified explicit recovery.
    """

    _RAW_MODES = frozenset((RuntimeMode.QUALIFYING, RuntimeMode.LIVE_RAW))

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._mode = RuntimeMode.STOPPED
        self._owner_id: str | None = None
        self._resume_normal_owner_id: str | None = None

    @property
    def ownership(self) -> DeviceSessionOwnership:
        with self._lock:
            return DeviceSessionOwnership(
                self._mode, self._owner_id, self._resume_normal_owner_id
            )

    @property
    def mode(self) -> RuntimeMode:
        return self.ownership.mode

    @property
    def owner_id(self) -> str | None:
        return self.ownership.owner_id

    @property
    def resume_normal_owner_id(self) -> str | None:
        return self.ownership.resume_normal_owner_id

    @staticmethod
    def _validate_owner(owner_id: str) -> None:
        if not owner_id:
            raise ValueError("owner_id cannot be empty")

    def _require_stopped(self) -> None:
        if self._mode is not RuntimeMode.STOPPED:
            raise SessionBusyError(
                f"device is owned by {self._owner_id!r} in {self._mode.value} mode"
            )

    def _require_owner(self, owner_id: str, modes: frozenset[RuntimeMode]) -> None:
        if self._mode not in modes or self._owner_id != owner_id:
            raise SessionOwnershipError(
                f"owner {owner_id!r} does not own {self._mode.value} mode"
            )

    @classmethod
    def _validate_raw_mode(cls, mode: RuntimeMode) -> None:
        if mode not in cls._RAW_MODES:
            raise ValueError("raw ownership mode must be qualifying or live_raw")

    def acquire_normal(self, owner_id: str) -> None:
        self._validate_owner(owner_id)
        with self._lock:
            self._require_stopped()
            self._mode = RuntimeMode.NORMAL
            self._owner_id = owner_id

    def release_normal(self, owner_id: str) -> None:
        self._validate_owner(owner_id)
        with self._lock:
            self._require_owner(owner_id, frozenset((RuntimeMode.NORMAL,)))
            self._mode = RuntimeMode.STOPPED
            self._owner_id = None

    def acquire_raw(
        self, owner_id: str, *, mode: RuntimeMode = RuntimeMode.LIVE_RAW
    ) -> None:
        self._validate_owner(owner_id)
        self._validate_raw_mode(mode)
        with self._lock:
            self._require_stopped()
            self._mode = mode
            self._owner_id = owner_id
            self._resume_normal_owner_id = None

    def handoff_normal_to_raw(
        self,
        normal_owner_id: str,
        raw_owner_id: str,
        *,
        resume_normal: bool = True,
        mode: RuntimeMode = RuntimeMode.LIVE_RAW,
    ) -> None:
        self._validate_owner(normal_owner_id)
        self._validate_owner(raw_owner_id)
        self._validate_raw_mode(mode)
        with self._lock:
            self._require_owner(normal_owner_id, frozenset((RuntimeMode.NORMAL,)))
            self._resume_normal_owner_id = normal_owner_id if resume_normal else None
            self._mode = mode
            self._owner_id = raw_owner_id

    def release_raw(self, owner_id: str, *, cleanup_verified: bool) -> None:
        self._validate_owner(owner_id)
        with self._lock:
            self._require_owner(owner_id, self._RAW_MODES)
            if not cleanup_verified:
                self._mode = RuntimeMode.RECOVERING
                return
            self._finish_raw_ownership()

    def recover(self, owner_id: str, *, cleanup_verified: bool) -> bool:
        self._validate_owner(owner_id)
        with self._lock:
            self._require_owner(owner_id, frozenset((RuntimeMode.RECOVERING,)))
            if not cleanup_verified:
                return False
            self._finish_raw_ownership()
            return True

    def _finish_raw_ownership(self) -> None:
        normal_owner = self._resume_normal_owner_id
        self._resume_normal_owner_id = None
        if normal_owner is None:
            self._mode = RuntimeMode.STOPPED
            self._owner_id = None
        else:
            self._mode = RuntimeMode.NORMAL
            self._owner_id = normal_owner


__all__ = [
    "DeviceSessionArbiter",
    "DeviceSessionOwnership",
    "SessionArbiterError",
    "SessionBusyError",
    "SessionOwnershipError",
]
