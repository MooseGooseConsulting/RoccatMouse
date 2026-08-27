import csv
import io
import unittest
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tyon_monitor import (
    AxisStats,
    CaptureRequest,
    JoystickInfo,
    RawModeLifecycle,
    action_progress_message,
    baseline_progress_message,
    choose_device,
    find_paired_vendor_interface,
    parse_xcelerator_report,
    monitor_args_for_request,
    normal_trial_acceptance,
    run_capture,
    main,
    write_row,
    xcal_command,
)


class CaptureSchemaTests(unittest.TestCase):
    def test_scroll_rows_exclude_pointer_coordinates(self):
        fields = [
            "elapsed_ms", "utc", "kind", "trial", "x", "y", "z", "r", "u", "v",
            "buttons", "pov", "scroll_dx", "scroll_dy", "raw_hex",
        ]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fields)

        write_row(
            writer,
            started=10.0,
            timestamp=10.5,
            kind="scroll",
            scroll_dx=0,
            scroll_dy=-1,
            trial="wheel",
        )

        row = next(csv.DictReader(io.StringIO(",".join(fields) + "\n" + output.getvalue())))
        self.assertEqual(row["scroll_dy"], "-1")
        self.assertNotIn("cursor_x", row)
        self.assertNotIn("cursor_y", row)


class CaptureRequestTests(unittest.TestCase):
    def test_paddle_request_includes_baseline_in_raw_duration(self):
        request = CaptureRequest("paddle")

        self.assertTrue(request.raw)
        self.assertEqual(request.monitor_duration, 12.0)

    def test_wheel_request_keeps_baseline_outside_monitor_duration(self):
        request = CaptureRequest("wheel", baseline_seconds=2.0, action_seconds=10.0)

        self.assertFalse(request.raw)
        self.assertEqual(request.monitor_duration, 10.0)

    def test_guided_paddle_request_uses_normal_mode_and_normalized_label(self):
        request = CaptureRequest("paddle_only")

        self.assertFalse(request.raw)
        self.assertEqual(request.label.value, "paddle_only")

    def test_legacy_labels_normalize_without_breaking_launchers(self):
        self.assertEqual(CaptureRequest("paddle").label.value, "paddle_only")
        self.assertEqual(CaptureRequest("wheel").label.value, "wheel_only")

    def test_request_rejects_unknown_trial(self):
        with self.assertRaises(ValueError):
            CaptureRequest("trackball")

    def test_request_rejects_zero_baseline(self):
        with self.assertRaises(ValueError):
            CaptureRequest("wheel", baseline_seconds=0)

    def test_request_rejects_zero_action_duration(self):
        with self.assertRaises(ValueError):
            CaptureRequest("wheel", action_seconds=0)

    def test_request_builds_raw_paddle_arguments(self):
        args = monitor_args_for_request(CaptureRequest("paddle"), "paddle.csv")

        self.assertTrue(args.raw)
        self.assertEqual(args.duration, 12.0)
        self.assertEqual(args.output, "paddle.csv")
        self.assertEqual(args.start_delay, 0)

    def test_request_builds_read_only_wheel_arguments(self):
        args = monitor_args_for_request(CaptureRequest("wheel"), "wheel.csv")

        self.assertFalse(args.raw)
        self.assertEqual(args.duration, 10.0)
        self.assertEqual(args.trial, "wheel")

    @patch("tyon_monitor.run_monitor", return_value=0)
    @patch("tyon_monitor.default_log_path", return_value=Path("captures/tyon-xcelerator-base.csv"))
    def test_run_capture_uses_read_only_runner_and_returns_summary(self, default_path, run_monitor):
        result = run_capture(CaptureRequest("wheel", start_delay_seconds=0))

        self.assertEqual(result.output, Path("captures/tyon-wheel-base.csv"))
        self.assertFalse(result.cancelled)
        self.assertEqual(result.exit_code, 0)
        run_monitor.assert_called_once()

    @patch("tyon_monitor.run_raw_monitor", return_value=3)
    @patch("tyon_monitor.default_log_path", return_value=Path("captures/tyon-xcelerator-base.csv"))
    def test_run_capture_uses_raw_runner_for_paddle(self, default_path, run_raw_monitor):
        result = run_capture(CaptureRequest("paddle", start_delay_seconds=0))

        self.assertEqual(result.output, Path("captures/tyon-xcelerator-raw-base.csv"))
        self.assertEqual(result.exit_code, 3)
        run_raw_monitor.assert_called_once()

    def test_progress_messages_reflect_configured_timings(self):
        args = monitor_args_for_request(
            CaptureRequest("paddle", baseline_seconds=0.2, action_seconds=0.8),
            "paddle.csv",
        )

        self.assertIn("0.2 seconds", baseline_progress_message(args.baseline_seconds))
        self.assertIn("0.8 seconds", action_progress_message(args))

    @patch("tyon_monitor.run_raw_monitor")
    @patch("tyon_monitor.run_monitor", return_value=0)
    def test_list_uses_read_only_runner_even_with_raw_flag(self, run_monitor, run_raw_monitor):
        with patch.object(sys, "argv", ["tyon_monitor.py", "--raw", "--list"]):
            self.assertEqual(main(), 0)

        run_monitor.assert_called_once()
        run_raw_monitor.assert_not_called()

    def test_controlled_trial_rejects_missing_wheel_signal(self):
        issues = normal_trial_acceptance(
            CaptureRequest("paddle_only").label,
            input_source="raw_input",
            event_counts={"axis": 100},
            wheel_directions=set(),
            clean_shutdown=True,
            profiles_preserved=True,
        )

        self.assertIn("no vertical wheel events recorded", issues)
        self.assertIn("missing wheel direction(s): down, up", issues)

    def test_controlled_trial_passes_with_both_raw_input_directions(self):
        issues = normal_trial_acceptance(
            CaptureRequest("wheel_only").label,
            input_source="raw_input",
            event_counts={"wheel": 8},
            wheel_directions={"up", "down"},
            clean_shutdown=True,
            profiles_preserved=True,
        )

        self.assertEqual(issues, [])

    def test_neutral_observation_has_no_controlled_signal_requirement(self):
        issues = normal_trial_acceptance(
            CaptureRequest("neutral").label,
            input_source="raw_input",
            event_counts={},
            wheel_directions=set(),
            clean_shutdown=True,
            profiles_preserved=True,
        )

        self.assertEqual(issues, [])

    @patch("tyon_monitor.run_raw_monitor")
    def test_raw_mode_rejects_wheel_trial_label(self, run_raw_monitor):
        with patch.object(
            sys,
            "argv",
            ["tyon_monitor.py", "--raw", "--trial", "wheel", "--duration", "1"],
        ):
            with self.assertRaises(SystemExit):
                main()

        run_raw_monitor.assert_not_called()

    @patch("tyon_monitor.run_raw_monitor")
    def test_raw_mode_rejects_normal_paddle_only_label(self, run_raw_monitor):
        with patch.object(
            sys,
            "argv",
            ["tyon_monitor.py", "--raw", "--trial", "paddle_only", "--duration", "1"],
        ):
            with self.assertRaises(SystemExit):
                main()

        run_raw_monitor.assert_not_called()

    @patch("tyon_monitor.run_raw_monitor")
    def test_raw_paddle_duration_must_leave_time_for_action(self, run_raw_monitor):
        with patch.object(
            sys,
            "argv",
            ["tyon_monitor.py", "--raw", "--trial", "paddle", "--duration", "2", "--baseline-seconds", "2"],
        ):
            with self.assertRaises(SystemExit):
                main()

        run_raw_monitor.assert_not_called()


class AxisStatsTests(unittest.TestCase):
    def test_tracks_away_run_and_return(self):
        stats = AxisStats(baseline=32767, away_threshold=100)
        stats.add(1.0, 32767)
        stats.add(2.0, 33000)
        stats.add(3.5, 33100)
        stats.add(4.0, 32770)

        self.assertEqual(stats.minimum, 32767)
        self.assertEqual(stats.maximum, 33100)
        self.assertEqual(stats.away_samples, 2)
        self.assertEqual(stats.return_count, 1)
        self.assertAlmostEqual(stats.longest_away_seconds, 2.0)

    def test_finish_closes_open_away_run(self):
        stats = AxisStats(baseline=1000, away_threshold=10)
        stats.add(5.0, 1200)
        stats.finish(7.25)
        self.assertAlmostEqual(stats.longest_away_seconds, 2.25)


class DeviceSelectionTests(unittest.TestCase):
    def test_prefers_named_tyon(self):
        devices = [
            JoystickInfo(0, "Other controller", 4, 8),
            JoystickInfo(2, "ROCCAT Tyon", 3, 0),
        ]
        self.assertEqual(choose_device(devices, None).slot, 2)

    def test_requires_choice_when_ambiguous(self):
        devices = [
            JoystickInfo(0, "Controller A", 2, 2),
            JoystickInfo(1, "Controller B", 2, 2),
        ]
        with self.assertRaises(RuntimeError):
            choose_device(devices, None)


class RawReportTests(unittest.TestCase):
    def test_parses_calibration_report(self):
        self.assertEqual(parse_xcelerator_report([0x03, 0x00, 0xE0, 0x06, 129]), 129)

    def test_rejects_other_special_report(self):
        self.assertIsNone(parse_xcelerator_report([0x03, 0x00, 0xD1, 0x00, 129]))

    def test_start_and_end_commands_never_contain_save_function(self):
        self.assertEqual(xcal_command(0x08), bytes((0x09, 0x08, 0x08, 0, 0, 0, 0, 0)))
        self.assertEqual(xcal_command(0x0A), bytes((0x09, 0x08, 0x0A, 0, 0, 0, 0, 0)))
        self.assertNotIn(0x0B, xcal_command(0x08)[2:3] + xcal_command(0x0A)[2:3])

    def test_pairs_raw_and_vendor_interfaces_by_serial_when_multiple_tyons_exist(self):
        infos = [
            {"usage_page": 0x000A, "interface_number": 3, "serial_number": "A", "path": "raw-a"},
            {"usage_page": 0x000B, "serial_number": "A", "path": "vendor-a"},
            {"usage_page": 0x000B, "serial_number": "B", "path": "vendor-b"},
        ]

        paired = find_paired_vendor_interface(infos, infos[0])

        self.assertEqual(paired["path"], "vendor-a")

    def test_rejects_ambiguous_vendor_pairing(self):
        infos = [
            {"usage_page": 0x000A, "interface_number": 3, "path": "raw-a"},
            {"usage_page": 0x000B, "path": "vendor-a"},
            {"usage_page": 0x000B, "path": "vendor-b"},
        ]

        self.assertIsNone(find_paired_vendor_interface(infos, infos[0]))


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

    def test_successful_stop_removes_recovery_marker(self):
        with TemporaryDirectory() as directory:
            marker = Path(directory) / "raw-mode-active.json"
            commands = []
            lifecycle = self.make_lifecycle(marker, commands)
            lifecycle.start()

            lifecycle.stop()

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
                device=object(),
                marker_path=marker,
                check_write=check_write,
                write_feature=write_feature,
            )
            lifecycle.start()

            lifecycle.stop()

            self.assertEqual(commands, [0x08, 0x0A])
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
