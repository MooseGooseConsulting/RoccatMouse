import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from roccatmouse.diagnostics.models import Phase, Timestamp
from roccatmouse.diagnostics.windows.raw_accelerator import (
    RawAcceleratorSource,
    RawModeLifecycle,
    RawStreamHealth,
    find_paired_vendor_interface,
    parse_xcelerator_report,
    xcal_command,
)


class FakeClock:
    def __init__(self):
        self.sequence = 0

    def now(self):
        stamp = Timestamp(
            monotonic_ns=1_000_000 + self.sequence,
            utc=datetime(2026, 7, 16, tzinfo=timezone.utc),
            sequence=self.sequence,
        )
        self.sequence += 1
        return stamp


class FakeRawDevice:
    def __init__(self, reports):
        self.reports = list(reports)
        self.closed = False
        self.read_called = threading.Event()

    def read(self, _size, _timeout_ms):
        self.read_called.set()
        if self.reports:
            report = self.reports.pop(0)
            if isinstance(report, BaseException):
                raise report
            return report
        time.sleep(0.001)
        return []

    def close(self):
        self.closed = True


class RawAcceleratorSourceTests(unittest.TestCase):
    def test_emits_ordered_timestamped_raw_events_and_counts_other_reports(self):
        device = FakeRawDevice(
            [
                [0x03, 0x00, 0xE0, 0x06, 128],
                [0x03, 0x00, 0xD1, 0x00, 99],
                [0x03, 0x00, 0xE0, 0x06, 130],
            ]
        )
        ticks = [0]
        events = []
        source = RawAcceleratorSource(
            session_id="session-1",
            clock=FakeClock(),
            phase=lambda: Phase.ACTION,
            device=device,
            device_id="mi03:serial-1",
            stale_after_ms=100,
            monotonic_ns=lambda: ticks[0],
        )

        source.start(events.append)
        deadline = time.monotonic() + 1
        while len(events) < 3 and time.monotonic() < deadline:
            time.sleep(0.001)

        raw_events = [event for event in events if event.kind == "raw_accelerator"]
        other_events = [event for event in events if event.kind == "other_report"]
        self.assertEqual([event.payload["value"] for event in raw_events], [128, 130])
        self.assertEqual([event.timestamp.sequence for event in events], [0, 1, 2])
        self.assertEqual(len(other_events), 1)
        self.assertEqual(other_events[0].payload["raw_hex"], "03 00 d1 00 63")
        self.assertTrue(all(event.source == "mi03_raw" for event in events))
        self.assertEqual(source.other_report_count, 1)
        self.assertNotIn("touched", events[0].payload)
        self.assertNotIn("released", events[0].payload)
        self.assertNotIn("physically_centered", events[0].payload)

        ticks[0] = 200_000_000
        self.assertEqual(source.health, RawStreamHealth.STALE)
        source.stop()
        source.stop()
        self.assertTrue(device.closed)
        self.assertEqual(source.health, RawStreamHealth.STOPPED)

    def test_read_failure_surfaces_error_health(self):
        source = RawAcceleratorSource(
            session_id="session-1",
            clock=FakeClock(),
            phase=lambda: Phase.ACTION,
            device=FakeRawDevice([OSError("device removed")]),
            device_id="mi03:serial-1",
        )

        source.start(lambda _event: None)
        deadline = time.monotonic() + 1
        while source.health is not RawStreamHealth.ERROR and time.monotonic() < deadline:
            time.sleep(0.001)

        self.assertEqual(source.health, RawStreamHealth.ERROR)
        self.assertIsInstance(source.error, OSError)
        source.stop()

    def test_nonterminating_reader_retains_error_and_rejects_restart(self):
        class NonTerminatingDevice:
            def __init__(self):
                self.read_called = threading.Event()
                self.release = threading.Event()
                self.close_calls = 0

            def read(self, _size, _timeout_ms):
                self.read_called.set()
                self.release.wait()
                return []

            def close(self):
                self.close_calls += 1

        device = NonTerminatingDevice()
        source = RawAcceleratorSource(
            session_id="session-1",
            clock=FakeClock(),
            phase=lambda: Phase.ACTION,
            device=device,
            device_id="mi03:serial-1",
            stop_timeout_seconds=0.01,
        )
        source.start(lambda _event: None)
        self.assertTrue(device.read_called.wait(timeout=1))

        with self.assertRaisesRegex(RuntimeError, "thread did not stop"):
            source.stop()

        self.assertEqual(source.health, RawStreamHealth.ERROR)
        self.assertIsNotNone(source._thread)
        self.assertTrue(source._thread.is_alive())
        with self.assertRaises(RuntimeError):
            source.start(lambda _event: None)

        device.release.set()
        source._thread.join(timeout=1)
        source.stop()
        self.assertEqual(source.health, RawStreamHealth.STOPPED)
        self.assertEqual(device.close_calls, 1)

    def test_close_failure_retains_error_and_rejects_restart(self):
        class CloseFailingDevice:
            def read(self, _size, _timeout_ms):
                return []

            def close(self):
                raise OSError("close failed")

        source = RawAcceleratorSource(
            session_id="session-1",
            clock=FakeClock(),
            phase=lambda: Phase.ACTION,
            device=CloseFailingDevice(),
            device_id="mi03:serial-1",
            stop_timeout_seconds=0.01,
        )
        source.start(lambda _event: None, threaded=False)

        with self.assertRaisesRegex(RuntimeError, "close failed"):
            source.stop()

        self.assertEqual(source.health, RawStreamHealth.ERROR)
        with self.assertRaises(RuntimeError):
            source.start(lambda _event: None)


class RawReportHelperTests(unittest.TestCase):
    def test_parses_only_xcelerator_calibration_reports(self):
        self.assertEqual(parse_xcelerator_report([0x03, 0x00, 0xE0, 0x06, 129]), 129)
        self.assertIsNone(parse_xcelerator_report([0x03, 0x00, 0xD1, 0x00, 129]))

    def test_commands_never_contain_save_function(self):
        self.assertEqual(xcal_command(0x08), bytes((0x09, 0x08, 0x08, 0, 0, 0, 0, 0)))
        self.assertEqual(xcal_command(0x0A), bytes((0x09, 0x08, 0x0A, 0, 0, 0, 0, 0)))
        with self.assertRaises(ValueError):
            xcal_command(0x0B)

    def test_pairs_raw_and_vendor_interfaces_by_serial(self):
        infos = [
            {"usage_page": 0x000A, "interface_number": 3, "serial_number": "A", "path": "raw-a"},
            {"usage_page": 0x000B, "serial_number": "A", "path": "vendor-a"},
            {"usage_page": 0x000B, "serial_number": "B", "path": "vendor-b"},
        ]

        self.assertEqual(find_paired_vendor_interface(infos, infos[0])["path"], "vendor-a")


class RawModeLifecycleTests(unittest.TestCase):
    def make_lifecycle(self, marker, commands, *, fail_on=None):
        def check_write(device, verbose=False):
            self.assertIsNotNone(device)

        def write_feature(device, packet, label, verbose=False):
            function = packet[2]
            if function == 0x08:
                self.assertTrue(marker.exists(), "marker must predate raw-mode start")
            commands.append(function)
            if function == fail_on:
                raise OSError(f"simulated function {function:#x} failure")

        return RawModeLifecycle(
            device=object(),
            marker_path=marker,
            check_write=check_write,
            write_feature=write_feature,
        )

    def test_start_writes_recovery_marker_before_start_report(self):
        with TemporaryDirectory() as directory:
            marker = Path(directory) / "raw-mode-active.json"
            commands = []
            lifecycle = self.make_lifecycle(marker, commands)
            lifecycle.start()
            self.assertTrue(marker.exists())
            self.assertEqual(commands, [0x08])
            lifecycle.stop()

    def test_successful_stop_is_verified_and_idempotent(self):
        with TemporaryDirectory() as directory:
            marker = Path(directory) / "raw-mode-active.json"
            commands = []
            lifecycle = self.make_lifecycle(marker, commands)
            lifecycle.start()
            self.assertTrue(lifecycle.stop())
            self.assertFalse(lifecycle.stop())
            self.assertFalse(marker.exists())
            self.assertEqual(commands, [0x08, 0x0A])

    def test_failed_stop_retains_recovery_marker(self):
        with TemporaryDirectory() as directory:
            marker = Path(directory) / "raw-mode-active.json"
            commands = []
            lifecycle = self.make_lifecycle(marker, commands, fail_on=0x0A)
            lifecycle.start()
            with self.assertRaises(OSError):
                lifecycle.stop()
            self.assertTrue(marker.exists())
            self.assertEqual(commands, [0x08, 0x0A])

    def test_stale_marker_is_recovered_before_new_start(self):
        with TemporaryDirectory() as directory:
            marker = Path(directory) / "raw-mode-active.json"
            marker.write_text("{}", encoding="utf-8")
            commands = []
            lifecycle = self.make_lifecycle(marker, commands)
            lifecycle.start()
            self.assertEqual(commands[:2], [0x0A, 0x08])
            lifecycle.stop()

    def test_failed_start_attempts_end_and_clears_marker(self):
        with TemporaryDirectory() as directory:
            marker = Path(directory) / "raw-mode-active.json"
            commands = []
            lifecycle = self.make_lifecycle(marker, commands, fail_on=0x08)
            with self.assertRaises(OSError):
                lifecycle.start()
            self.assertEqual(commands, [0x08, 0x0A])
            self.assertFalse(marker.exists())

    def test_stop_sends_end_even_when_prior_status_check_fails(self):
        with TemporaryDirectory() as directory:
            marker = Path(directory) / "raw-mode-active.json"
            commands = []
            checks = 0

            def check_write(device, verbose=False):
                nonlocal checks
                checks += 1
                if checks == 3:
                    raise OSError("simulated stale start status")

            def write_feature(device, packet, label, verbose=False):
                commands.append(packet[2])

            lifecycle = RawModeLifecycle(
                device=object(), marker_path=marker, check_write=check_write, write_feature=write_feature
            )
            lifecycle.start()
            lifecycle.stop()
            self.assertEqual(commands, [0x08, 0x0A])
            self.assertFalse(marker.exists())

    def test_concurrent_stop_cannot_end_before_start_finishes(self):
        with TemporaryDirectory() as directory:
            marker = Path(directory) / "raw-mode-active.json"
            commands = []
            first_start_check = threading.Event()
            allow_start = threading.Event()
            stop_attempted = threading.Event()
            end_written = threading.Event()
            checks = 0

            def check_write(_device, verbose=False):
                nonlocal checks
                checks += 1
                if checks == 1:
                    first_start_check.set()
                    allow_start.wait()

            def write_feature(_device, packet, _label, verbose=False):
                commands.append(packet[2])
                if packet[2] == 0x0A:
                    end_written.set()

            lifecycle = RawModeLifecycle(
                device=object(),
                marker_path=marker,
                check_write=check_write,
                write_feature=write_feature,
            )
            start_thread = threading.Thread(target=lifecycle.start)

            def stop_lifecycle():
                stop_attempted.set()
                lifecycle.stop()

            stop_thread = threading.Thread(target=stop_lifecycle)
            start_thread.start()
            self.assertTrue(first_start_check.wait(timeout=1))
            self.assertTrue(marker.exists())
            stop_thread.start()
            self.assertTrue(stop_attempted.wait(timeout=1))
            try:
                self.assertFalse(
                    end_written.wait(timeout=0.1),
                    "stop must wait for the serialized start transition",
                )
            finally:
                allow_start.set()
                start_thread.join(timeout=1)
                stop_thread.join(timeout=1)

            self.assertFalse(start_thread.is_alive())
            self.assertFalse(stop_thread.is_alive())
            self.assertEqual(commands, [0x08, 0x0A])
            self.assertFalse(marker.exists())
            self.assertFalse(lifecycle.active)


if __name__ == "__main__":
    unittest.main()
