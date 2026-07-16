import unittest

from roccatmouse.diagnostics.windows.raw_input import (
    RI_MOUSE_BUTTON_1_DOWN,
    RI_MOUSE_BUTTON_1_UP,
    RI_MOUSE_HWHEEL,
    RI_MOUSE_WHEEL,
    RawMousePacket,
    is_tyon_device_name,
    parse_raw_mouse,
)


class RawInputParserTests(unittest.TestCase):
    def test_parses_relative_movement_without_screen_coordinates(self):
        events = parse_raw_mouse(RawMousePacket("tyon", dx=12, dy=-8))

        self.assertEqual(events, [("relative_move", {"dx": 12, "dy": -8})])
        self.assertNotIn("x", events[0][1])
        self.assertNotIn("y", events[0][1])

    def test_parses_vertical_wheel_as_signed_delta(self):
        up = parse_raw_mouse(RawMousePacket("tyon", button_flags=RI_MOUSE_WHEEL, button_data=120))
        down = parse_raw_mouse(
            RawMousePacket("tyon", button_flags=RI_MOUSE_WHEEL, button_data=0xFF88)
        )

        self.assertEqual(up, [("wheel", {"delta": 120, "direction": "up"})])
        self.assertEqual(down, [("wheel", {"delta": -120, "direction": "down"})])

    def test_parses_horizontal_wheel_and_buttons(self):
        events = parse_raw_mouse(
            RawMousePacket(
                "tyon",
                button_flags=RI_MOUSE_BUTTON_1_DOWN | RI_MOUSE_BUTTON_1_UP | RI_MOUSE_HWHEEL,
                button_data=120,
            )
        )

        self.assertEqual(events[0], ("button", {"button": "left", "pressed": True}))
        self.assertEqual(events[1], ("button", {"button": "left", "pressed": False}))
        self.assertEqual(events[2], ("horizontal_wheel", {"delta": 120, "direction": "right"}))

    def test_tyon_matcher_is_case_insensitive_and_pid_scoped(self):
        self.assertTrue(is_tyon_device_name(r"\\?\HID#VID_1E7D&PID_2E4A&MI_00"))
        self.assertTrue(is_tyon_device_name(r"\\?\hid#vid_1e7d&pid_2e4b&mi_00"))
        self.assertFalse(is_tyon_device_name(r"\\?\HID#VID_1E7D&PID_2E4C&MI_00"))
        self.assertFalse(is_tyon_device_name(r"\\?\HID#VID_1234&PID_2E4A&MI_00"))


if __name__ == "__main__":
    unittest.main()
