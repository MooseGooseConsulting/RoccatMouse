from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from roccatmouse.diagnostics.aggregate import AggregateBucket
from roccatmouse.diagnostics.models import (
    CaptureMode,
    Phase,
    SessionResult,
    SessionState,
    TelemetryEvent,
    Timestamp,
    TrialLabel,
)
from roccatmouse.diagnostics.storage import SQLiteTelemetryStore, apply_migrations


NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "telemetry.sqlite3"
        self.store = SQLiteTelemetryStore(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def start(self, session_id="s1", *, tier="continuous", utc=NOW):
        self.store.start_session(
            session_id,
            TrialLabel.GENERAL_OBSERVATION,
            CaptureMode.NORMAL,
            None,
            tier=tier,
            timestamp=Timestamp(1_000_000_000, utc, 0),
        )

    def test_fresh_database_uses_wal_and_idempotent_migration(self):
        self.assertEqual(self.store.connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(self.store.counts(), {"sessions": 0, "events": 0, "aggregates": 0, "anomalies": 0, "exports": 0})
        self.store.close()
        self.store = SQLiteTelemetryStore(self.path)
        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
            1,
        )

    def test_failed_migration_rolls_back_its_version(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        with self.assertRaises(sqlite3.OperationalError):
            apply_migrations(connection, [(1, "CREATE TABLE ok(id INTEGER);"), (2, "BROKEN SQL")])
        self.assertEqual(connection.execute("SELECT version FROM schema_migrations").fetchall(), [(1,)])

    def test_session_event_aggregate_marker_and_context_round_trip(self):
        self.start()
        stamp = Timestamp(2_000_000_000, NOW + timedelta(seconds=1), 1)
        self.store.write_event(TelemetryEvent("s1", stamp, "raw_input", "wheel", Phase.ACTION, {"delta": -120}))
        self.store.write_aggregate(AggregateBucket("s1", 2_000_000_000, NOW, wheel_event_count=1))
        marker = self.store.mark_symptom("s1", Timestamp(2_100_000_000, NOW, 2), "stuck scroll")
        context = self.store.context(marker, 30)
        self.assertEqual(len(context["events"]), 1)
        self.assertEqual(len(context["aggregates"]), 1)
        self.assertEqual(self.store.counts()["anomalies"], 1)

    def test_duplicate_session_sequence_is_rejected(self):
        self.start()
        stamp = Timestamp(2_000_000_000, NOW, 1)
        event = TelemetryEvent("s1", stamp, "test", "wheel", Phase.ACTION)
        self.store.write_event(event)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.write_event(event)

    def test_retention_deletes_only_old_completed_continuous_sessions(self):
        old = NOW - timedelta(days=31)
        for session_id, tier in (("old", "continuous"), ("kept", "high_fidelity"), ("active", "continuous")):
            self.start(session_id, tier=tier, utc=old)
        for session_id in ("old", "kept"):
            result = SessionResult(
                session_id,
                TrialLabel.GENERAL_OBSERVATION,
                CaptureMode.NORMAL,
                SessionState.COMPLETED,
                True,
            )
            self.store.finish_session(result, timestamp=Timestamp(2_000_000_000, old, 2))
        self.assertEqual(self.store.apply_retention(NOW - timedelta(days=30)), 1)
        remaining = {row[0] for row in self.store.connection.execute("SELECT id FROM sessions")}
        self.assertEqual(remaining, {"kept", "active"})


if __name__ == "__main__":
    unittest.main()
