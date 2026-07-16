import unittest
from pathlib import Path

from tyon_capture_gui import CaptureWorker, capture_status, format_summary
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

    def test_failed_controlled_trial_shows_acceptance_reasons(self):
        result = CaptureResult(
            CaptureRequest("wheel_only"), Path("captures/wheel.csv"), False, 5,
            {"acceptance_issues": ["no vertical wheel events recorded"]},
        )

        self.assertIn("no vertical wheel events recorded", format_summary(result))

    def test_formats_normal_mode_source_and_cleanup(self):
        result = CaptureResult(
            CaptureRequest("paddle_only"),
            Path("captures/paddle-normal.csv"),
            False,
            0,
            {
                "samples": 3000,
                "scroll_events": 12,
                "primary_axis": "y",
                "primary_span": 32000,
                "input_source": "raw_input",
                "clean_shutdown": True,
            },
        )

        text = format_summary(result)

        self.assertIn("Input source: raw_input", text)
        self.assertIn("clean shutdown: True", text)

    def test_worker_queues_symptom_note_for_normal_capture(self):
        worker = CaptureWorker(CaptureRequest("paddle_only"))

        worker.mark_symptom("continued scrolling after release")

        self.assertEqual(worker.marker_queue.get_nowait(), "continued scrolling after release")


if __name__ == "__main__":
    unittest.main()
