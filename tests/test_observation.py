from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from roccatmouse.diagnostics.models import Phase, TelemetryEvent, Timestamp
from roccatmouse.diagnostics.observation import ObservationRuntime
from roccatmouse.diagnostics.storage import SQLiteTelemetryStore


class FakeClock:
    def __init__(self):
        self.ns = 1_000_000_000
        self.sequence = 0

    def now(self):
        self.sequence += 1
        self.ns += 1_000_000_000
        return Timestamp(self.ns, datetime.now(timezone.utc), self.sequence)


class FakeSource:
    def __init__(self):
        self.emit = None
        self.stopped = False

    def start(self, emit):
        self.emit = emit

    def stop(self):
        self.stopped = True


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SQLiteTelemetryStore(Path(self.temp.name) / "telemetry.sqlite3")
        self.clock = FakeClock()
        self.source = FakeSource()
        self.runtime = ObservationRuntime(
            self.store,
            self.clock,
            lambda _session: self.source,
            queue_size=10,
        )

    def tearDown(self):
        if self.runtime.status.active:
            self.runtime.stop()
        self.store.close()
        self.temp.cleanup()

    def test_start_event_marker_and_clean_stop(self):
        status = self.runtime.start()
        event = TelemetryEvent(
            status.session_id,
            self.clock.now(),
            "raw_input",
            "wheel",
            Phase.ACTION,
            {"delta": -120, "direction": "down"},
        )
        self.source.emit(event)
        marker = self.runtime.mark_symptom("continued after release")
        stopped = self.runtime.stop()
        self.assertFalse(stopped.active)
        self.assertTrue(self.source.stopped)
        self.assertEqual(self.store.counts()["events"], 1)
        self.assertEqual(self.store.counts()["anomalies"], 1)
        self.assertEqual(len(self.store.context(marker)["events"]), 1)
        session = self.store.connection.execute("SELECT state, clean_shutdown FROM sessions").fetchone()
        self.assertEqual(tuple(session), ("completed", 1))

    def test_double_start_is_rejected(self):
        self.runtime.start()
        with self.assertRaisesRegex(RuntimeError, "already active"):
            self.runtime.start()


if __name__ == "__main__":
    unittest.main()
