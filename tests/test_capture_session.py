import unittest

from roccatmouse.diagnostics.models import CaptureMode, Phase, SessionState, TrialLabel
from roccatmouse.diagnostics.session import CaptureSession, InvalidTransition


class CaptureSessionTests(unittest.TestCase):
    def make_session(self):
        return CaptureSession("session-1", TrialLabel.PADDLE_ONLY, CaptureMode.NORMAL)

    def test_happy_path_visits_each_guided_phase(self):
        session = self.make_session()

        session.prepare()
        session.begin_baseline()
        session.begin_action()
        session.stop()
        result = session.complete(clean_shutdown=True)

        self.assertEqual(
            session.history,
            [
                SessionState.CREATED,
                SessionState.PREPARING,
                SessionState.BASELINE,
                SessionState.ACTION,
                SessionState.STOPPING,
                SessionState.COMPLETED,
            ],
        )
        self.assertEqual(session.phase, Phase.NONE)
        self.assertTrue(result.clean_shutdown)

    def test_invalid_transition_is_rejected(self):
        session = self.make_session()

        with self.assertRaises(InvalidTransition):
            session.begin_action()

    def test_cancel_and_failure_are_honest_terminal_states(self):
        cancelled = self.make_session()
        cancelled.prepare()
        cancel_result = cancelled.cancel(clean_shutdown=True)
        self.assertEqual(cancel_result.state, SessionState.CANCELLED)

        failed = self.make_session()
        failed.prepare()
        fail_result = failed.fail("source unavailable", clean_shutdown=False)
        self.assertEqual(fail_result.state, SessionState.FAILED)
        self.assertEqual(fail_result.error, "source unavailable")
        self.assertFalse(fail_result.clean_shutdown)

    def test_disconnect_can_recover_to_preparing(self):
        session = self.make_session()
        session.prepare()
        session.disconnect()
        session.recover()

        self.assertEqual(session.state, SessionState.PREPARING)
        self.assertEqual(session.history[-2:], [SessionState.DISCONNECTED, SessionState.PREPARING])


if __name__ == "__main__":
    unittest.main()
