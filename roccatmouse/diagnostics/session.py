"""Capture-session state machine shared by CLI and GUI workflows."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import CaptureMode, DeviceFingerprint, Phase, SessionResult, SessionState, TrialLabel


class InvalidTransition(RuntimeError):
    """Raised when a capture lifecycle transition would make state ambiguous."""


_ALLOWED: dict[SessionState, set[SessionState]] = {
    SessionState.CREATED: {SessionState.PREPARING, SessionState.CANCELLED, SessionState.FAILED},
    SessionState.PREPARING: {
        SessionState.BASELINE,
        SessionState.CANCELLED,
        SessionState.FAILED,
        SessionState.DISCONNECTED,
    },
    SessionState.BASELINE: {
        SessionState.ACTION,
        SessionState.STOPPING,
        SessionState.CANCELLED,
        SessionState.FAILED,
        SessionState.DISCONNECTED,
    },
    SessionState.ACTION: {
        SessionState.STOPPING,
        SessionState.CANCELLED,
        SessionState.FAILED,
        SessionState.DISCONNECTED,
    },
    SessionState.STOPPING: {
        SessionState.COMPLETED,
        SessionState.CANCELLED,
        SessionState.FAILED,
    },
    SessionState.DISCONNECTED: {
        SessionState.PREPARING,
        SessionState.CANCELLED,
        SessionState.FAILED,
    },
    SessionState.COMPLETED: set(),
    SessionState.CANCELLED: set(),
    SessionState.FAILED: set(),
}

_PHASES = {
    SessionState.CREATED: Phase.NONE,
    SessionState.PREPARING: Phase.PREPARATION,
    SessionState.BASELINE: Phase.BASELINE,
    SessionState.ACTION: Phase.ACTION,
    SessionState.STOPPING: Phase.STOPPING,
    SessionState.COMPLETED: Phase.NONE,
    SessionState.CANCELLED: Phase.NONE,
    SessionState.FAILED: Phase.NONE,
    SessionState.DISCONNECTED: Phase.NONE,
}


@dataclass(slots=True)
class CaptureSession:
    session_id: str
    trial: TrialLabel
    mode: CaptureMode
    fingerprint: DeviceFingerprint | None = None
    state: SessionState = SessionState.CREATED
    history: list[SessionState] = field(default_factory=lambda: [SessionState.CREATED])

    @property
    def phase(self) -> Phase:
        return _PHASES[self.state]

    def _transition(self, target: SessionState) -> None:
        if target not in _ALLOWED[self.state]:
            raise InvalidTransition(f"cannot transition from {self.state.value} to {target.value}")
        self.state = target
        self.history.append(target)

    def prepare(self) -> None:
        self._transition(SessionState.PREPARING)

    def begin_baseline(self) -> None:
        self._transition(SessionState.BASELINE)

    def begin_action(self) -> None:
        self._transition(SessionState.ACTION)

    def stop(self) -> None:
        self._transition(SessionState.STOPPING)

    def disconnect(self) -> None:
        self._transition(SessionState.DISCONNECTED)

    def recover(self) -> None:
        self._transition(SessionState.PREPARING)

    def complete(self, *, clean_shutdown: bool) -> SessionResult:
        self._transition(SessionState.COMPLETED)
        return self._result(clean_shutdown=clean_shutdown)

    def cancel(self, *, clean_shutdown: bool) -> SessionResult:
        self._transition(SessionState.CANCELLED)
        return self._result(clean_shutdown=clean_shutdown)

    def fail(self, error: str, *, clean_shutdown: bool) -> SessionResult:
        self._transition(SessionState.FAILED)
        return self._result(clean_shutdown=clean_shutdown, error=error)

    def _result(self, *, clean_shutdown: bool, error: str | None = None) -> SessionResult:
        return SessionResult(
            session_id=self.session_id,
            trial=self.trial,
            mode=self.mode,
            state=self.state,
            clean_shutdown=clean_shutdown,
            fingerprint=self.fingerprint,
            error=error,
        )
