import unittest
from pathlib import Path

from tyon_capture_gui import capture_status, format_summary
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

    def test_nonzero_exit_is_presented_as_failed(self):
        result = CaptureResult(
            CaptureRequest("paddle"), Path("captures/paddle.csv"), False, 3,
            {"reports": 0, "scroll_events": 0, "unmatched": 0},
        )

        self.assertEqual(capture_status(result), "Capture failed (exit code 3).")
        self.assertIn("Capture failed", format_summary(result))


if __name__ == "__main__":
    unittest.main()
