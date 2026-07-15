import unittest
from pathlib import Path

from tyon_capture_gui import format_summary
from tyon_monitor import CaptureRequest, CaptureResult


class CaptureGuiSummaryTests(unittest.TestCase):
    def test_formats_paddle_result(self):
        result = CaptureResult(
            CaptureRequest("paddle"), Path("captures/paddle.csv"), False, 0,
            {"reports": 1092, "baseline": 115, "baseline_span": 1,
             "raw_range": (24, 210), "scroll_events": 10, "unmatched": 0},
        )

        text = format_summary(result)

        self.assertIn("1,092 raw reports", text)
        self.assertIn("baseline 115", text)
        self.assertIn("24–210", text)

    def test_formats_cancelled_result(self):
        result = CaptureResult(CaptureRequest("wheel"), Path("captures/wheel.csv"), True, 0, {})

        self.assertEqual(format_summary(result), "Capture stopped. No result summary was produced.")


if __name__ == "__main__":
    unittest.main()
