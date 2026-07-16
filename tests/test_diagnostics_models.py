import unittest
from datetime import datetime, timezone

from roccatmouse.diagnostics.models import (
    CaptureMode,
    DeviceFingerprint,
    Phase,
    SessionResult,
    SessionState,
    TelemetryEvent,
    Timestamp,
    TrialLabel,
)


class DiagnosticsModelTests(unittest.TestCase):
    def test_timestamp_requires_utc_and_nonnegative_sequence(self):
        with self.assertRaises(ValueError):
            Timestamp(1, datetime(2026, 1, 1), 0)
        with self.assertRaises(ValueError):
            Timestamp(1, datetime.now(timezone.utc), -1)

    def test_event_serializes_platform_neutral_fields(self):
        stamp = Timestamp(123, datetime(2026, 7, 15, tzinfo=timezone.utc), 4)
        event = TelemetryEvent(
            session_id="session-1",
            timestamp=stamp,
            source="raw_input",
            kind="wheel",
            phase=Phase.ACTION,
            payload={"delta": -120},
            device_id="tyon",
        )

        data = event.as_dict()

        self.assertEqual(data["sequence"], 4)
        self.assertEqual(data["phase"], "action")
        self.assertEqual(data["payload"], {"delta": -120})
        self.assertNotIn("cursor_x", data["payload"])

    def test_session_result_records_cleanup_and_fingerprint(self):
        fingerprint = DeviceFingerprint("Tyon Black", ("a", "b", "c", "d", "e"))
        result = SessionResult(
            session_id="session-1",
            trial=TrialLabel.PADDLE_ONLY,
            mode=CaptureMode.NORMAL,
            state=SessionState.COMPLETED,
            clean_shutdown=True,
            fingerprint=fingerprint,
        )

        self.assertEqual(result.fingerprint.profile_hashes[1], "b")
        self.assertTrue(result.clean_shutdown)


if __name__ == "__main__":
    unittest.main()
