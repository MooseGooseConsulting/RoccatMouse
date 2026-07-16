import threading
import unittest

from roccatmouse.diagnostics.arbiter import (
    DeviceSessionArbiter,
    SessionBusyError,
    SessionOwnershipError,
)
from roccatmouse.diagnostics.models import RuntimeMode


class DeviceSessionArbiterTests(unittest.TestCase):
    def test_stopped_to_normal_and_clean_release(self):
        arbiter = DeviceSessionArbiter()
        arbiter.acquire_normal("normal-owner")
        self.assertEqual(arbiter.mode, RuntimeMode.NORMAL)
        self.assertEqual(arbiter.owner_id, "normal-owner")
        arbiter.release_normal("normal-owner")
        self.assertEqual(arbiter.mode, RuntimeMode.STOPPED)

    def test_normal_to_raw_handoff_remembers_and_resumes_normal_owner(self):
        arbiter = DeviceSessionArbiter()
        arbiter.acquire_normal("normal-owner")
        arbiter.handoff_normal_to_raw("normal-owner", "raw-owner", resume_normal=True)
        self.assertEqual(arbiter.mode, RuntimeMode.LIVE_RAW)
        self.assertEqual(arbiter.owner_id, "raw-owner")
        self.assertEqual(arbiter.resume_normal_owner_id, "normal-owner")

        arbiter.release_raw("raw-owner", cleanup_verified=True)

        self.assertEqual(arbiter.mode, RuntimeMode.NORMAL)
        self.assertEqual(arbiter.owner_id, "normal-owner")
        self.assertIsNone(arbiter.resume_normal_owner_id)

    def test_unverified_raw_cleanup_blocks_acquisition_until_explicit_recovery(self):
        arbiter = DeviceSessionArbiter()
        arbiter.acquire_raw("raw-owner", mode=RuntimeMode.QUALIFYING)
        arbiter.release_raw("raw-owner", cleanup_verified=False)
        self.assertEqual(arbiter.mode, RuntimeMode.RECOVERING)

        with self.assertRaises(SessionBusyError):
            arbiter.acquire_normal("competitor")
        with self.assertRaises(SessionBusyError):
            arbiter.acquire_raw("competitor")
        self.assertFalse(arbiter.recover("raw-owner", cleanup_verified=False))
        self.assertEqual(arbiter.mode, RuntimeMode.RECOVERING)
        self.assertTrue(arbiter.recover("raw-owner", cleanup_verified=True))
        self.assertEqual(arbiter.mode, RuntimeMode.STOPPED)

    def test_wrong_or_stale_owner_cannot_release_or_handoff(self):
        arbiter = DeviceSessionArbiter()
        arbiter.acquire_normal("normal-owner")
        with self.assertRaises(SessionOwnershipError):
            arbiter.release_normal("wrong-owner")
        with self.assertRaises(SessionOwnershipError):
            arbiter.handoff_normal_to_raw("wrong-owner", "raw-owner")
        self.assertEqual(arbiter.owner_id, "normal-owner")

    def test_competing_acquisitions_are_thread_safe_and_exclusive(self):
        arbiter = DeviceSessionArbiter()
        barrier = threading.Barrier(9)
        winners = []
        losers = []
        result_lock = threading.Lock()

        def compete(number):
            barrier.wait()
            try:
                arbiter.acquire_normal(f"owner-{number}")
            except SessionBusyError:
                with result_lock:
                    losers.append(number)
            else:
                with result_lock:
                    winners.append(number)

        threads = [threading.Thread(target=compete, args=(number,)) for number in range(8)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        self.assertEqual(len(winners), 1)
        self.assertEqual(len(losers), 7)
        self.assertEqual(arbiter.owner_id, f"owner-{winners[0]}")


if __name__ == "__main__":
    unittest.main()
