from datetime import datetime, timezone
import unittest

from roccatmouse.diagnostics.aggregate import OneSecondAccumulator
from roccatmouse.diagnostics.models import Phase, TelemetryEvent, Timestamp


def event(sequence, ns, kind="axis", payload=None):
    return TelemetryEvent(
        "session",
        Timestamp(ns, datetime(2026, 7, 15, tzinfo=timezone.utc), sequence),
        "test",
        kind,
        Phase.ACTION,
        payload or {},
    )


class AggregateTests(unittest.TestCase):
    def test_aggregates_wheel_reversals_movement_and_numeric_values(self):
        accumulator = OneSecondAccumulator()
        accumulator.add(event(1, 100_000_000, "wheel", {"delta": 120}))
        accumulator.add(event(2, 200_000_000, "wheel", {"delta": -120}))
        accumulator.add(event(3, 300_000_000, "relative_move", {"dx": 4, "dy": -2}))
        accumulator.add(event(4, 400_000_000, "axis", {"values": {"y": 10}}))
        accumulator.add(event(5, 500_000_000, "axis", {"values": {"y": 20}}))
        bucket = accumulator.flush()[0]
        self.assertEqual(bucket.wheel_event_count, 2)
        self.assertEqual(bucket.wheel_reversals, 1)
        self.assertEqual((bucket.movement_dx_sum, bucket.movement_dy_sum), (4, -2))
        self.assertEqual((bucket.values_min["y"], bucket.values_max["y"]), (10, 20))

    def test_emits_empty_boundary_buckets(self):
        accumulator = OneSecondAccumulator()
        accumulator.add(event(1, 100_000_000))
        completed = accumulator.add(event(2, 3_100_000_000))
        self.assertEqual([bucket.bucket_start_ns for bucket in completed], [0, 1_000_000_000, 2_000_000_000])
        self.assertEqual(completed[1].sample_count, 0)

    def test_late_event_is_counted_without_rewriting_completed_time(self):
        accumulator = OneSecondAccumulator()
        accumulator.add(event(1, 2_100_000_000))
        accumulator.add(event(2, 1_900_000_000))
        bucket = accumulator.flush()[0]
        self.assertEqual(accumulator.late_events, 1)
        self.assertEqual(bucket.late_event_count, 1)
        self.assertEqual(bucket.sample_count, 1)


if __name__ == "__main__":
    unittest.main()
