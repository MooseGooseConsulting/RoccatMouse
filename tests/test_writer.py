from datetime import datetime, timezone
import threading
import time
import unittest

from roccatmouse.diagnostics.aggregate import AggregateBucket
from roccatmouse.diagnostics.models import Phase, TelemetryEvent, Timestamp
from roccatmouse.diagnostics.writer import TelemetryWriter


class FakeStore:
    def __init__(self, *, gate=None, fail=False):
        self.gate = gate
        self.fail = fail
        self.events = []
        self.aggregates = []

    def write_event(self, event):
        if self.fail:
            raise OSError("disk unavailable")
        self.events.append(event)

    def write_aggregate(self, bucket):
        if self.gate is not None:
            self.gate.wait(2)
        if self.fail:
            raise OSError("disk unavailable")
        self.aggregates.append(bucket)


def event(sequence=1):
    return TelemetryEvent(
        "s",
        Timestamp(sequence, datetime.now(timezone.utc), sequence),
        "raw_input",
        "wheel",
        Phase.ACTION,
        {"delta": 120},
    )


class WriterTests(unittest.TestCase):
    def test_drains_discrete_events_and_aggregates(self):
        store = FakeStore()
        writer = TelemetryWriter(store, queue_size=2)
        writer.start()
        writer.submit_event(event())
        writer.submit_aggregate(AggregateBucket("s", 0, datetime.now(timezone.utc)))
        stats = writer.stop()
        self.assertEqual((stats.events_written, stats.aggregates_written), (1, 1))

    def test_bulk_queue_drops_are_counted_without_losing_priority_event(self):
        gate = threading.Event()
        store = FakeStore(gate=gate)
        writer = TelemetryWriter(store, queue_size=1)
        writer.start()
        first = AggregateBucket("s", 0, datetime.now(timezone.utc))
        writer.submit_aggregate(first)
        time.sleep(0.05)
        writer.submit_aggregate(AggregateBucket("s", 1, datetime.now(timezone.utc)))
        accepted = writer.submit_aggregate(AggregateBucket("s", 2, datetime.now(timezone.utc)))
        writer.submit_event(event())
        self.assertFalse(accepted)
        gate.set()
        stats = writer.stop()
        self.assertEqual(stats.events_written, 1)
        self.assertGreaterEqual(stats.aggregates_dropped, 1)

    def test_database_failure_is_raised_to_runtime(self):
        writer = TelemetryWriter(FakeStore(fail=True), queue_size=1)
        writer.start()
        writer.submit_event(event())
        time.sleep(0.05)
        with self.assertRaisesRegex(RuntimeError, "disk unavailable"):
            writer.stop()


if __name__ == "__main__":
    unittest.main()
