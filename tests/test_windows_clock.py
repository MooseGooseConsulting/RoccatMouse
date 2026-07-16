import unittest
from datetime import datetime, timedelta, timezone

from roccatmouse.diagnostics.windows.clock import QpcClock


class WindowsClockTests(unittest.TestCase):
    def test_sequences_timestamps_and_clamps_monotonic_regression(self):
        values = iter((100, 100, 90, 120))
        utc = datetime(2026, 7, 15, tzinfo=timezone.utc)
        utc_values = iter(utc + timedelta(microseconds=index) for index in range(4))
        clock = QpcClock(
            monotonic_ns=lambda: next(values),
            utc_now=lambda: next(utc_values),
        )

        stamps = [clock.now() for _ in range(4)]

        self.assertEqual([item.sequence for item in stamps], [0, 1, 2, 3])
        self.assertEqual([item.monotonic_ns for item in stamps], [100, 100, 100, 120])


if __name__ == "__main__":
    unittest.main()
