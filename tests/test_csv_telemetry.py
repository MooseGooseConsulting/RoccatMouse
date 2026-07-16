import csv
import io
import unittest
from datetime import datetime, timezone

from roccatmouse.diagnostics.csv_sink import CsvTelemetryWriter, normalize_capture_row
from roccatmouse.diagnostics.models import CaptureMode, Phase, TelemetryEvent, Timestamp, TrialLabel


class CsvTelemetryTests(unittest.TestCase):
    def make_event(self, kind, payload):
        return self.make_sequenced_event(7, kind, payload)

    def make_sequenced_event(self, sequence, kind, payload):
        return TelemetryEvent(
            session_id="session-1",
            timestamp=Timestamp(
                1_500_000_000 + sequence,
                datetime(2026, 7, 15, tzinfo=timezone.utc),
                sequence,
            ),
            source="raw_input",
            kind=kind,
            phase=Phase.ACTION,
            payload=payload,
            device_id="tyon-path",
        )

    def test_writes_common_wheel_schema_without_pointer_coordinates(self):
        output = io.StringIO()
        writer = CsvTelemetryWriter(output, started_ns=1_000_000_000, trial=TrialLabel.PADDLE_ONLY)

        writer.write_event(self.make_event("wheel", {"delta": -120, "direction": "down"}))

        row = next(csv.DictReader(io.StringIO(output.getvalue())))
        self.assertEqual(row["elapsed_ms"], "500.0")
        self.assertEqual(row["sequence"], "7")
        self.assertEqual(row["source"], "raw_input")
        self.assertEqual(row["scroll_dy"], "-120")
        self.assertNotIn("cursor_x", row)
        self.assertNotIn("cursor_y", row)

    def test_maps_relative_motion_and_buttons_to_separate_columns(self):
        output = io.StringIO()
        writer = CsvTelemetryWriter(output, started_ns=1_000_000_000, trial=TrialLabel.GENERAL_OBSERVATION)
        writer.write_event(self.make_event("relative_move", {"dx": 3, "dy": -2}))
        writer.write_event(self.make_event("button", {"button": "left", "pressed": True}))

        rows = list(csv.DictReader(io.StringIO(output.getvalue())))
        self.assertEqual((rows[0]["mouse_dx"], rows[0]["mouse_dy"]), ("3", "-2"))
        self.assertEqual((rows[1]["mouse_button"], rows[1]["pressed"]), ("left", "True"))

    def test_ordered_writer_waits_for_sequence_gaps(self):
        output = io.StringIO()
        writer = CsvTelemetryWriter(
            output,
            started_ns=1_000_000_000,
            trial=TrialLabel.PADDLE_ONLY,
            ordered_from_sequence=1,
        )

        writer.write_event(self.make_sequenced_event(2, "wheel", {"delta": 120}))
        writer.write_event(self.make_sequenced_event(1, "wheel", {"delta": -120}))
        writer.flush_ordered(force=True)

        rows = list(csv.DictReader(io.StringIO(output.getvalue())))
        self.assertEqual([row["sequence"] for row in rows], ["1", "2"])

    def test_ordered_writer_rejects_a_missing_sequence_on_forced_flush(self):
        output = io.StringIO()
        writer = CsvTelemetryWriter(
            output,
            started_ns=1_000_000_000,
            trial=TrialLabel.PADDLE_ONLY,
            ordered_from_sequence=1,
        )

        writer.write_event(self.make_sequenced_event(2, "wheel", {"delta": 120}))

        with self.assertRaisesRegex(ValueError, "sequence gap: expected 1, received 2"):
            writer.flush_ordered(force=True)

    def test_normalizes_foundation_csv_rows(self):
        legacy = {
            "elapsed_ms": "10.0",
            "utc": "2026-07-15T00:00:00+00:00",
            "kind": "scroll",
            "trial": "wheel",
            "scroll_dy": "1",
        }

        normalized = normalize_capture_row(legacy)

        self.assertEqual(normalized["trial"], "wheel_only")
        self.assertEqual(normalized["source"], "legacy")
        self.assertEqual(normalized["phase"], "")
        self.assertEqual(normalized["capture_mode"], "normal")
        self.assertEqual(normalized["scroll_dy"], "1")

    def test_raw_legacy_rows_preserve_sensor_mode_and_value(self):
        normalized = normalize_capture_row({
            "kind": "raw", "trial": "paddle", "raw_value": "123", "raw_hex": "03 00 e0 06 7b",
        })

        self.assertEqual(normalized["trial"], "paddle")
        self.assertEqual(normalized["capture_mode"], "raw")
        self.assertEqual(normalized["raw_value"], "123")

    def test_writes_raw_accelerator_value_and_mode(self):
        output = io.StringIO()
        writer = CsvTelemetryWriter(
            output,
            started_ns=1_000_000_000,
            trial=TrialLabel.PADDLE_ONLY,
            capture_mode=CaptureMode.RAW,
        )
        writer.write_event(self.make_event("raw_accelerator", {"value": 207, "raw_hex": "03 00 e0 06 cf"}))

        row = next(csv.DictReader(io.StringIO(output.getvalue())))
        self.assertEqual(row["capture_mode"], "raw")
        self.assertEqual(row["raw_value"], "207")
        self.assertEqual(row["raw_hex"], "03 00 e0 06 cf")


if __name__ == "__main__":
    unittest.main()
