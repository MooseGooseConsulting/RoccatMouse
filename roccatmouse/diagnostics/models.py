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


class RuntimeMode(str, Enum):
    """Public diagnostic runtime modes shared by every platform adapter."""

    STOPPED = "stopped"
    NORMAL = "normal"
    QUALIFYING = "qualifying"
    LIVE_RAW = "live_raw"
    RECOVERING = "recovering"
    ERROR = "error"


class RawStreamHealth(str, Enum):
    """Platform-neutral health vocabulary for a raw measurement stream."""

    STOPPED = "stopped"
    STARTING = "starting"
    HEALTHY = "healthy"
    STALE = "stale"
    ERROR = "error"


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
class DeviceIdentity:
    """Stable HID identity, deliberately separate from mutable profile data."""

    stable_id: str
    vendor_id: int
    product_id: int
    serial_number: str | None = None
    interface_number: int | None = None


@dataclass(frozen=True, slots=True)
class DiagnosticStatus:
    """Lifecycle and durability status for one diagnostic runtime session."""

    session_id: str | None
    device_identity: DeviceIdentity | None
    mode: RuntimeMode
    lifecycle_state: str
    persistence_state: str
    cleanup_state: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DiagnosticSnapshot:
    """Current measured facts; physical state remains an owner observation."""

    session_id: str | None
    raw_value: int | None
    sample_age_ms: float | None
    sample_rate_hz: float | None
    arithmetic_baseline_delta: int | None
    latest_windows_output: Mapping[str, Any] | None
    marker_status: str
    stream_health: str


@dataclass(frozen=True, slots=True)
class QualificationResult:
    """Exact coexistence verdict with the evidence sessions that support it."""

    passed: bool
    evidence_session_ids: tuple[str, ...]
    pass_reasons: tuple[str, ...] = ()
    failure_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.passed:
            if not self.evidence_session_ids:
                raise ValueError("a passing qualification requires evidence sessions")
            if not self.pass_reasons:
                raise ValueError("a passing qualification requires explicit pass reasons")
            if self.failure_reasons:
                raise ValueError("a passing qualification cannot contain failure reasons")
        else:
            if not self.failure_reasons:
                raise ValueError("a failed qualification requires explicit failure reasons")
            if self.pass_reasons:
                raise ValueError("a failed qualification cannot contain pass reasons")


@dataclass(frozen=True, slots=True)
class SessionResult:
    session_id: str
    trial: TrialLabel
    mode: CaptureMode
    state: SessionState
    clean_shutdown: bool
    fingerprint: DeviceFingerprint | None = None
    error: str | None = None
