import unittest
from datetime import datetime, timezone

from roccatmouse.diagnostics.contracts import (
    AcceleratorSource,
    Clock,
    DeviceControl,
    InputEventSource,
    TelemetrySink,
)
from roccatmouse.diagnostics.models import DeviceFingerprint, SessionResult, Timestamp


class FakeClock:
    def now(self):
        return Timestamp(1, datetime.now(timezone.utc), 0)


class FakeDevice:
    def fingerprint(self):
        return DeviceFingerprint("fake", ("1", "2", "3", "4", "5"))

    def recover(self):
        return True

    def start_raw(self):
        return None

    def stop_raw(self):
        return True


class FakeSource:
    def start(self, emit):
        self.emit = emit

    def stop(self):
        return None


class FakeSink:
    def start_session(self, session_id, trial, mode, fingerprint):
        return None

    def write_event(self, event):
        return None

    def finish_session(self, result: SessionResult):
        return None


class ContractTests(unittest.TestCase):
    def test_structural_contracts_accept_fakes(self):
        self.assertIsInstance(FakeClock(), Clock)
        self.assertIsInstance(FakeDevice(), DeviceControl)
        self.assertIsInstance(FakeSource(), AcceleratorSource)
        self.assertIsInstance(FakeSource(), InputEventSource)
        self.assertIsInstance(FakeSink(), TelemetrySink)


if __name__ == "__main__":
    unittest.main()
