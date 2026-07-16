import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from roccatmouse.diagnostics.observation import ObservationStatus
from roccatmouse.tray import TrayController


class FakeRuntime:
    def __init__(self):
        self.active = False
        self.markers = 0
        self.closed = False

    @property
    def status(self):
        return ObservationStatus(self.active, "s" if self.active else None, None, self.markers, None, None)

    def mark_symptom(self, note="symptom"):
        if not self.active:
            raise RuntimeError("not active")
        self.markers += 1
        return self.markers

    def close(self):
        self.closed = True


class TrayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_marker_actions_follow_observation_state(self):
        runtime = FakeRuntime()
        controller = TrayController(runtime, show=False)
        self.assertFalse(controller.marker_action.isEnabled())
        runtime.active = True
        controller._apply_status(runtime.status)
        self.assertTrue(controller.marker_action.isEnabled())
        controller.mark_symptom()
        self.assertEqual(runtime.markers, 1)

    def test_menu_explains_long_running_actions(self):
        controller = TrayController(FakeRuntime(), show=False)
        labels = [action.text() for action in controller.tray.contextMenu().actions() if action.text()]
        self.assertIn("Start continuous observation", labels)
        self.assertIn("Mark symptom now", labels)
        self.assertIn("Open short capture proofs", labels)


if __name__ == "__main__":
    unittest.main()
