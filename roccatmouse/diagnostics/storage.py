"""SQLite WAL telemetry store with numbered schema migrations."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib import resources
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Iterable

from .aggregate import AggregateBucket
from .models import CaptureMode, DeviceFingerprint, SessionResult, TelemetryEvent, Timestamp, TrialLabel


def bundled_migrations() -> list[tuple[int, str]]:
    root = resources.files("roccatmouse.diagnostics.migrations")
    result: list[tuple[int, str]] = []
    for item in sorted(root.iterdir(), key=lambda candidate: candidate.name):
        if item.name[:3].isdigit() and item.name.endswith(".sql"):
            result.append((int(item.name[:3]), item.read_text(encoding="utf-8")))
    return result


def apply_migrations(
    connection: sqlite3.Connection,
    migrations: Iterable[tuple[int, str]],
) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, applied_utc TEXT NOT NULL)"
    )
    applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
    for version, script in sorted(migrations):
        if version in applied:
            continue
        try:
            connection.execute("BEGIN")
            for statement in script.split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_utc) VALUES (?, ?)",
                (version, datetime.now(timezone.utc).isoformat()),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


class SQLiteTelemetryStore:
    def __init__(
        self,
        path: Path,
        *,
        migrations: Iterable[tuple[int, str]] | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.execute("PRAGMA journal_mode=WAL")
        apply_migrations(self.connection, migrations or bundled_migrations())

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def start_session(
        self,
        session_id: str,
        trial: TrialLabel,
        mode: CaptureMode,
        fingerprint: DeviceFingerprint | None,
        *,
        tier: str = "high_fidelity",
        timestamp: Timestamp | None = None,
        notes: str | None = None,
    ) -> None:
        stamp = timestamp or Timestamp(time.perf_counter_ns(), datetime.now(timezone.utc), 0)
        fingerprint_json = None
        if fingerprint is not None:
            fingerprint_json = json.dumps(
                {"device_name": fingerprint.device_name, "profile_hashes": fingerprint.profile_hashes}
            )
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT INTO sessions(id, trial, mode, tier, state, started_monotonic_ns, "
                "started_utc, fingerprint_json, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    trial.value,
                    mode.value,
                    tier,
                    "created",
                    stamp.monotonic_ns,
                    stamp.utc.isoformat(),
                    fingerprint_json,
                    notes,
                ),
            )

    def write_event(self, event: TelemetryEvent) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT INTO events(session_id, monotonic_ns, utc, sequence, source, kind, "
                "phase, device_id, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.session_id,
                    event.timestamp.monotonic_ns,
                    event.timestamp.utc.isoformat(),
                    event.timestamp.sequence,
                    event.source,
                    event.kind,
                    event.phase.value,
                    event.device_id,
                    json.dumps(dict(event.payload), sort_keys=True, separators=(",", ":")),
                ),
            )

    def set_session_state(self, session_id: str, state: str) -> None:
        with self._lock, self.connection:
            self.connection.execute("UPDATE sessions SET state=? WHERE id=?", (state, session_id))

    def write_aggregate(self, bucket: AggregateBucket) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO aggregates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    bucket.session_id,
                    bucket.bucket_start_ns,
                    bucket.bucket_start_utc.isoformat(),
                    bucket.sample_count,
                    bucket.wheel_event_count,
                    bucket.wheel_delta_sum,
                    bucket.wheel_reversals,
                    bucket.movement_count,
                    bucket.movement_dx_sum,
                    bucket.movement_dy_sum,
                    bucket.button_event_count,
                    bucket.anomaly_count,
                    json.dumps(bucket.payload(), sort_keys=True, separators=(",", ":")),
                ),
            )

    def mark_symptom(self, session_id: str, timestamp: Timestamp, note: str = "symptom") -> int:
        with self._lock, self.connection:
            cursor = self.connection.execute(
                "INSERT INTO anomalies(session_id, monotonic_ns, utc, kind, severity, note, "
                "payload_json, user_marked) VALUES (?, ?, ?, 'symptom', 'user', ?, '{}', 1)",
                (session_id, timestamp.monotonic_ns, timestamp.utc.isoformat(), note or "symptom"),
            )
            return int(cursor.lastrowid)

    def finish_session(self, result: SessionResult, *, timestamp: Timestamp | None = None) -> None:
        stamp = timestamp or Timestamp(time.perf_counter_ns(), datetime.now(timezone.utc), 0)
        with self._lock, self.connection:
            self.connection.execute(
                "UPDATE sessions SET state=?, ended_monotonic_ns=?, ended_utc=?, "
                "clean_shutdown=? WHERE id=?",
                (
                    result.state.value,
                    stamp.monotonic_ns,
                    stamp.utc.isoformat(),
                    int(result.clean_shutdown),
                    result.session_id,
                ),
            )

    def context(self, marker_id: int, seconds: int = 30) -> dict[str, list[sqlite3.Row]]:
        with self._lock:
            marker = self.connection.execute(
                "SELECT * FROM anomalies WHERE id=?", (marker_id,)
            ).fetchone()
            if marker is None:
                raise KeyError(marker_id)
            radius = seconds * 1_000_000_000
            parameters = (
                marker["session_id"],
                marker["monotonic_ns"] - radius,
                marker["monotonic_ns"] + radius,
            )
            return {
                "events": list(
                    self.connection.execute(
                        "SELECT * FROM events WHERE session_id=? AND monotonic_ns BETWEEN ? AND ? "
                        "ORDER BY monotonic_ns, sequence",
                        parameters,
                    )
                ),
                "aggregates": list(
                    self.connection.execute(
                        "SELECT * FROM aggregates WHERE session_id=? AND bucket_start_ns BETWEEN ? AND ? "
                        "ORDER BY bucket_start_ns",
                        parameters,
                    )
                ),
            }

    def apply_retention(self, cutoff_utc: datetime) -> int:
        with self._lock, self.connection:
            cursor = self.connection.execute(
                "DELETE FROM sessions WHERE tier='continuous' AND retained=0 "
                "AND ended_utc IS NOT NULL AND ended_utc < ?",
                (cutoff_utc.astimezone(timezone.utc).isoformat(),),
            )
            return cursor.rowcount

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {
                table: int(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("sessions", "events", "aggregates", "anomalies", "exports")
            }
