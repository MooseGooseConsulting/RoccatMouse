import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from tyon_gui import DiagnosticsPage


class DiagnosticsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_exposes_raw_paddle_normal_paddle_and_wheel_trials(self):
        page = DiagnosticsPage()

        labels = {button.text() for button in page.findChildren(QPushButton)}

        self.assertEqual(labels, {"Raw-Sensor", "Paddle-Scrollen", "Physisches Rad"})
        page.close()

    def test_opens_normal_paddle_capture_without_starting_it(self):
        page = DiagnosticsPage()

        page.open_capture("paddle_only")

        self.assertEqual(len(page._capture_windows), 1)
        self.assertEqual(page._capture_windows[0].windowTitle(), "Roccat Tyon — Capture")
        for window in list(page._capture_windows):
            window.close()
        page.close()


if __name__ == "__main__":
    unittest.main()
