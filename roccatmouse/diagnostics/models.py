"""Platform-neutral records shared by capture, storage, and analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping


class TrialLabel(str, Enum):
    NEUTRAL = "neutral"
    PADDLE_ONLY = "paddle_only"
    WHEEL_ONLY = "wheel_only"
    SYMPTOM_REPRODUCTION = "symptom_reproduction"
    GENERAL_OBSERVATION = "general_observation"


class CaptureMode(str, Enum):
    NORMAL = "normal"
    RAW = "raw"


class SessionState(str, Enum):
    CREATED = "created"
    PREPARING = "preparing"
    BASELINE = "baseline"
    ACTION = "action"
    STOPPING = "stopping"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    DISCONNECTED = "disconnected"


class Phase(str, Enum):
    NONE = "none"
    PREPARATION = "preparation"
    BASELINE = "baseline"
    ACTION = "action"
    STOPPING = "stopping"


@dataclass(frozen=True, slots=True)
class Timestamp:
    monotonic_ns: int
    utc: datetime
    sequence: int

    def __post_init__(self) -> None:
        if self.monotonic_ns < 0:
            raise ValueError("monotonic_ns cannot be negative")
        if self.sequence < 0:
            raise ValueError("sequence cannot be negative")
        if self.utc.tzinfo is None or self.utc.utcoffset() is None:
            raise ValueError("utc must be timezone-aware")


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    session_id: str
    timestamp: Timestamp
    source: str
    kind: str
    phase: Phase
    payload: Mapping[str, Any] = field(default_factory=dict)
    device_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "monotonic_ns": self.timestamp.monotonic_ns,
            "utc": self.timestamp.utc.isoformat(timespec="microseconds"),
            "sequence": self.timestamp.sequence,
            "source": self.source,
            "kind": self.kind,
            "phase": self.phase.value,
            "device_id": self.device_id,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class DeviceFingerprint:
    device_name: str
    profile_hashes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SessionResult:
    session_id: str
    trial: TrialLabel
    mode: CaptureMode
    state: SessionState
    clean_shutdown: bool
    fingerprint: DeviceFingerprint | None = None
    error: str | None = None
