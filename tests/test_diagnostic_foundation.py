import unittest
from dataclasses import fields

from roccatmouse.diagnostics import (
    DeviceIdentity,
    DiagnosticSnapshot,
    DiagnosticStatus,
    QualificationResult,
    RuntimeMode,
)


class DiagnosticFoundationModelTests(unittest.TestCase):
    def test_runtime_mode_values_are_the_public_lifecycle_vocabulary(self):
        self.assertEqual(
            [mode.value for mode in RuntimeMode],
            ["stopped", "normal", "qualifying", "live_raw", "recovering", "error"],
        )

    def test_public_records_expose_identity_status_snapshot_and_qualification_facts(self):
        identity = DeviceIdentity("hid:1e7d:2e4a:serial-1:mi03", 0x1E7D, 0x2E4A, "serial-1", 3)
        status = DiagnosticStatus(
            session_id="session-1",
            device_identity=identity,
            mode=RuntimeMode.LIVE_RAW,
            lifecycle_state="running",
            persistence_state="healthy",
            cleanup_state="marker_present",
        )
        snapshot = DiagnosticSnapshot(
            session_id="session-1",
            raw_value=129,
            sample_age_ms=4.5,
            sample_rate_hz=89.8,
            arithmetic_baseline_delta=3,
            latest_windows_output={"direction": "up", "delta": 120},
            marker_status="saved",
            stream_health="healthy",
        )
        result = QualificationResult(
            passed=False,
            evidence_session_ids=("session-1", "session-2"),
            pass_reasons=("raw reports were ordered",),
            failure_reasons=("missing Tyon output direction(s): down",),
        )

        self.assertEqual(status.device_identity.stable_id, identity.stable_id)
        self.assertEqual(snapshot.arithmetic_baseline_delta, 3)
        self.assertEqual(snapshot.latest_windows_output["direction"], "up")
        self.assertEqual(result.evidence_session_ids, ("session-1", "session-2"))
        self.assertEqual(result.failure_reasons[0], "missing Tyon output direction(s): down")

    def test_public_records_do_not_infer_owner_observations(self):
        forbidden = {"touched", "released", "physically_centered"}
        public_types = (DeviceIdentity, DiagnosticStatus, DiagnosticSnapshot, QualificationResult)

        for record_type in public_types:
            self.assertTrue(forbidden.isdisjoint(field.name for field in fields(record_type)))
            self.assertTrue(forbidden.isdisjoint(dir(record_type)))


if __name__ == "__main__":
    unittest.main()
