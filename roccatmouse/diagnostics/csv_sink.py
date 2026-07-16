"""Versioned CSV sink and compatibility normalization for capture files."""

from __future__ import annotations

import csv
import heapq
import json
from typing import IO, Mapping

from .models import CaptureMode, TelemetryEvent, TrialLabel

AXIS_FIELDS = ("x", "y", "z", "r", "u", "v")
CSV_FIELDS = (
    "schema_version",
    "session_id",
    "elapsed_ms",
    "monotonic_ns",
    "utc",
    "sequence",
    "kind",
    "source",
    "phase",
    "trial",
    "capture_mode",
    "device_id",
    *AXIS_FIELDS,
    "buttons",
    "pov",
    "scroll_dx",
    "scroll_dy",
    "mouse_dx",
    "mouse_dy",
    "mouse_button",
    "pressed",
    "raw_hex",
    "raw_value",
    "note",
    "payload_json",
)

_LEGACY_TRIALS = {"paddle": "paddle_only", "wheel": "wheel_only"}


class CsvTelemetryWriter:
    def __init__(
        self,
        handle: IO[str],
        *,
        started_ns: int,
        trial: TrialLabel,
        capture_mode: CaptureMode = CaptureMode.NORMAL,
        ordered_from_sequence: int | None = None,
    ) -> None:
        self.started_ns = started_ns
        self.trial = trial
        self.capture_mode = capture_mode
        self.writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        self.writer.writeheader()
        self._next_sequence = ordered_from_sequence
        self._pending: list[tuple[int, dict[str, object]]] = []

    def write_event(
        self,
        event: TelemetryEvent,
        *,
        axes: Mapping[str, int] | None = None,
        buttons: int | str = "",
        pov: int | str = "",
        raw_hex: str = "",
        note: str = "",
    ) -> None:
        payload = dict(event.payload)
        row: dict[str, object] = {field: "" for field in CSV_FIELDS}
        row.update(
            {
                "schema_version": 3,
                "session_id": event.session_id,
                "elapsed_ms": round(
                    (event.timestamp.monotonic_ns - self.started_ns) / 1_000_000.0, 3
                ),
                "monotonic_ns": event.timestamp.monotonic_ns,
                "utc": event.timestamp.utc.isoformat(timespec="microseconds"),
                "sequence": event.timestamp.sequence,
                "kind": event.kind,
                "source": event.source,
                "phase": event.phase.value,
                "trial": self.trial.value,
                "capture_mode": self.capture_mode.value,
                "device_id": event.device_id or "",
                "buttons": buttons,
                "pov": pov,
                "raw_hex": raw_hex,
                "note": note,
                "payload_json": json.dumps(payload, sort_keys=True, separators=(",", ":")),
            }
        )
        if axes is not None:
            row.update({axis: axes.get(axis, "") for axis in AXIS_FIELDS})
        if event.kind == "wheel":
            row["scroll_dy"] = payload.get("delta", "")
        elif event.kind == "horizontal_wheel":
            row["scroll_dx"] = payload.get("delta", "")
        elif event.kind == "relative_move":
            row["mouse_dx"] = payload.get("dx", "")
            row["mouse_dy"] = payload.get("dy", "")
        elif event.kind == "button":
            row["mouse_button"] = payload.get("button", "")
            row["pressed"] = payload.get("pressed", "")
        elif event.kind in ("raw", "raw_accelerator"):
            row["raw_value"] = payload.get("value", "")
            if not raw_hex:
                row["raw_hex"] = payload.get("raw_hex", "")
        if self._next_sequence is None:
            self.writer.writerow(row)
            return
        heapq.heappush(self._pending, (event.timestamp.sequence, row))
        self.flush_ordered()

    def flush_ordered(self, *, force: bool = False) -> None:
        if self._next_sequence is None:
            return
        if force and self._pending and self._pending[0][0] != self._next_sequence:
            raise ValueError(
                f"telemetry sequence gap: expected {self._next_sequence}, "
                f"received {self._pending[0][0]}"
            )
        while self._pending and self._pending[0][0] == self._next_sequence:
            sequence, row = heapq.heappop(self._pending)
            self.writer.writerow(row)
            self._next_sequence = sequence + 1


def normalize_capture_row(row: Mapping[str, str]) -> dict[str, str]:
    """Normalize a foundation or current CSV row for shared readers."""
    normalized = {field: row.get(field, "") for field in CSV_FIELDS}
    normalized["schema_version"] = normalized["schema_version"] or "1"
    is_raw = row.get("kind", "") == "raw" or row.get("capture_mode", "") == "raw"
    legacy_trial = row.get("trial", "")
    normalized["trial"] = legacy_trial if is_raw else _LEGACY_TRIALS.get(legacy_trial, legacy_trial)
    normalized["capture_mode"] = row.get("capture_mode", "") or ("raw" if is_raw else "normal")
    normalized["source"] = normalized["source"] or "legacy"
    return normalized
