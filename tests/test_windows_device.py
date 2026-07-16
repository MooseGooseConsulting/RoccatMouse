import unittest

from roccatmouse.diagnostics.windows.device import TyonDeviceControl


class FakeHandle:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class TyonDeviceControlTests(unittest.TestCase):
    def test_fingerprint_hashes_settings_and_buttons_for_all_profiles(self):
        handles = []

        def open_device():
            handle = FakeHandle()
            handles.append(handle)
            return handle, "Tyon Test"

        control = TyonDeviceControl(
            open_device=open_device,
            read_settings=lambda _device, profile, _verbose: bytes((profile, 1, 2)),
            read_buttons=lambda _device, profile, _verbose: bytes((profile, 3, 4)),
            profile_count=5,
        )

        fingerprint = control.fingerprint()

        self.assertEqual(fingerprint.device_name, "Tyon Test")
        self.assertEqual(len(fingerprint.profile_hashes), 5)
        self.assertEqual(len(set(fingerprint.profile_hashes)), 5)
        self.assertTrue(handles[0].closed)

    def test_raw_lifecycle_methods_delegate_when_supplied(self):
        calls = []

        class Lifecycle:
            def recover(self):
                calls.append("recover")
                return True

            def start(self):
                calls.append("start")

            def stop(self):
                calls.append("stop")
                return True

        control = TyonDeviceControl(raw_lifecycle=Lifecycle())

        self.assertTrue(control.recover())
        control.start_raw()
        self.assertTrue(control.stop_raw())
        self.assertEqual(calls, ["recover", "start", "stop"])


if __name__ == "__main__":
    unittest.main()
