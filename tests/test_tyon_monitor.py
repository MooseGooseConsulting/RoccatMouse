import unittest

from tyon_monitor import (
    AxisStats,
    JoystickInfo,
    choose_device,
    parse_xcelerator_report,
    xcal_command,
)


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


if __name__ == "__main__":
    unittest.main()
