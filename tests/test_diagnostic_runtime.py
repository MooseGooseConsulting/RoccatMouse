import inspect
import threading
import time
import unittest
from datetime import datetime, timezone

from roccatmouse.diagnostics.models import (
    DeviceFingerprint, DeviceIdentity, Phase, RuntimeMode, TelemetryEvent, Timestamp,
)
from roccatmouse.diagnostics.runtime import DiagnosticRuntime, RawAdapterBundle
from roccatmouse.diagnostics.controller import DiagnosticController


class Clock:
    def __init__(self):
        self.ns = 0
        self.sequence = 0
        self.lock = threading.Lock()

    def now(self):
        with self.lock:
            stamp = Timestamp(self.ns, datetime.now(timezone.utc), self.sequence)
            self.ns += 10_000_000
            self.sequence += 1
            return stamp


class Source:
    def __init__(self, calls, name, fail_start=False):
        self.calls, self.name, self.fail_start = calls, name, fail_start
        self.emit = None
        self.health = "healthy"

    def start(self, emit):
        self.calls.append(f"{self.name}.start")
        if self.fail_start:
            raise RuntimeError(f"{self.name} start failed")
        self.emit = emit

    def stop(self):
        self.calls.append(f"{self.name}.stop")


class Lifecycle:
    def __init__(self, calls, stop_result=True, recover_result=True):
        self.calls, self.stop_result, self.recover_result = calls, stop_result, recover_result

    def start(self): self.calls.append("lifecycle.start")
    def stop(self):
        self.calls.append("lifecycle.stop")
        return self.stop_result
    def recover(self):
        self.calls.append("lifecycle.recover")
        return self.recover_result


class Control:
    def __init__(self, fingerprints): self.fingerprints = list(fingerprints)
    def fingerprint(self): return self.fingerprints.pop(0) if len(self.fingerprints) > 1 else self.fingerprints[0]


class Normal:
    def __init__(self, calls, *, fail_start=False, fail_stop=False, fail_close=False):
        self.calls = calls
        self.fail_start, self.fail_stop, self.fail_close = fail_start, fail_stop, fail_close
    def start(self, emit):
        self.calls.append("normal.start")
        if self.fail_start: raise RuntimeError("normal start failed after acquire")
    def stop(self):
        self.calls.append("normal.stop")
        if self.fail_stop: raise RuntimeError("normal stop failed")
    def close(self):
        self.calls.append("normal.close")
        if self.fail_close: raise RuntimeError("normal close failed")


class Harness:
    def __init__(self, *, stop_result=True, recover_result=True, raw_fail=False, fingerprints=None):
        self.clock, self.calls = Clock(), []
        self.identity = DeviceIdentity("tyon", 0x1E7D, 0x2E4A)
        fp = DeviceFingerprint("Tyon", ("same",) * 5)
        self.fingerprints = fingerprints or [fp, fp]
        self.stop_result, self.recover_result, self.raw_fail = stop_result, recover_result, raw_fail
        self.bundles = []

    def normal_factory(self, session_id, clock):
        return Normal(self.calls)

    def raw_factory(self, session_id, clock, phase):
        bundle = RawAdapterBundle(
            identity=self.identity,
            device_control=Control(self.fingerprints),
            lifecycle=Lifecycle(self.calls, self.stop_result, self.recover_result),
            accelerator_source=Source(self.calls, "raw", self.raw_fail),
            input_source=Source(self.calls, "input"),
            close=lambda: self.calls.append("bundle.close"),
        )
        self.bundles.append(bundle)
        return bundle

    def runtime(self):
        return DiagnosticRuntime(clock=self.clock, normal_factory=self.normal_factory,
                                 raw_factory=self.raw_factory, monitor_interval_seconds=.01)


class DiagnosticRuntimeTests(unittest.TestCase):
    def test_nonterminating_monitor_does_not_skip_raw_end_and_retains_recovery(self):
        h = Harness(); runtime = h.runtime(); runtime.start_raw()
        class StuckMonitor:
            def join(self, timeout=None): pass
            def is_alive(self): return True
        old = runtime._monitor_thread; runtime._monitor_stop.set()
        if old is not None: old.join(timeout=.5)
        runtime._monitor_thread = StuckMonitor()
        self.assertFalse(runtime.stop_raw())
        self.assertIn("lifecycle.stop", h.calls)
        self.assertEqual(runtime.status().mode, RuntimeMode.RECOVERING)
        runtime.close()
        self.assertFalse(runtime._closed)
        self.assertEqual(runtime.status().mode, RuntimeMode.RECOVERING)

    def test_concurrent_callbacks_preserve_listener_sequence_order(self):
        h = Harness(); runtime = h.runtime(); sid = runtime.start_raw(); seen = []
        first_entered = threading.Event(); release_first = threading.Event()
        def listener(event):
            if event.timestamp.sequence == 1:
                first_entered.set(); release_first.wait(.5)
            seen.append(event.timestamp.sequence)
        runtime.add_event_listener(listener)
        def event(seq):
            return TelemetryEvent(sid, Timestamp(seq, datetime.now(timezone.utc), seq),
                                  "raw_accelerator", "raw_accelerator", Phase.ACTION, {"value": seq})
        first = threading.Thread(target=lambda: runtime._receive_event(event(1)))
        second = threading.Thread(target=lambda: runtime._receive_event(event(2)))
        first.start(); self.assertTrue(first_entered.wait(.5)); second.start()
        time.sleep(.02); release_first.set(); first.join(); second.join()
        self.assertEqual(seen, [1, 2])

    def test_concurrent_stop_waits_for_normal_start_transition(self):
        h = Harness(); entered = threading.Event(); release = threading.Event()
        class BlockingNormal(Normal):
            def start(self, emit):
                self.calls.append("normal.start.begin"); entered.set(); release.wait(.5)
                self.calls.append("normal.start.end")
        runtime = DiagnosticRuntime(clock=h.clock, normal_factory=lambda *_: BlockingNormal(h.calls),
                                    raw_factory=h.raw_factory)
        starter = threading.Thread(target=runtime.start_normal); starter.start()
        self.assertTrue(entered.wait(.5))
        stopper = threading.Thread(target=runtime.stop_normal); stopper.start()
        time.sleep(.02)
        self.assertNotIn("normal.stop", h.calls)
        release.set(); starter.join(); stopper.join()
        self.assertLess(h.calls.index("normal.start.end"), h.calls.index("normal.stop"))

    def test_failed_pause_rollback_sync_event_is_flushed_after_lock_release(self):
        h = Harness(); seen = []; adapters = []
        first = Normal(h.calls, fail_stop=True)
        class EmittingNormal(Normal):
            def start(self, emit):
                super().start(emit)
                emit(TelemetryEvent(normal_id, h.clock.now(), "raw_input", "wheel",
                                    Phase.ACTION, {"delta": 120}))
        adapters.extend((first, EmittingNormal(h.calls)))
        runtime = DiagnosticRuntime(clock=h.clock, normal_factory=lambda *_: adapters.pop(0),
                                    raw_factory=h.raw_factory)
        runtime.add_event_listener(seen.append); normal_id = runtime.start_normal()
        with self.assertRaisesRegex(RuntimeError, "normal stop failed"): runtime.start_raw()
        self.assertEqual(len(seen), 1)
        self.assertEqual(runtime.status().mode, RuntimeMode.NORMAL)

    def test_clean_startup_rollback_resume_sync_event_is_flushed(self):
        h = Harness(); seen = []; adapters = [Normal(h.calls)]
        class EmittingNormal(Normal):
            def start(self, emit):
                super().start(emit)
                emit(TelemetryEvent(normal_id, h.clock.now(), "raw_input", "wheel",
                                    Phase.ACTION, {"delta": -120}))
        adapters.append(EmittingNormal(h.calls))
        runtime = DiagnosticRuntime(clock=h.clock, normal_factory=lambda *_: adapters.pop(0),
                                    raw_factory=lambda sid, clock, phase: RawAdapterBundle(
                                        h.identity, Control(h.fingerprints), Lifecycle(h.calls),
                                        Source(h.calls, "raw"), Source(h.calls, "input", fail_start=True),
                                        lambda: h.calls.append("bundle.close")))
        runtime.add_event_listener(seen.append); normal_id = runtime.start_normal()
        with self.assertRaisesRegex(RuntimeError, "input start failed"): runtime.start_raw()
        self.assertEqual(len(seen), 1)
        self.assertEqual(runtime.status().mode, RuntimeMode.NORMAL)

    def test_normal_start_accepts_synchronous_event_for_pending_session(self):
        h = Harness(); seen = []; reentered = threading.Event()
        class EmittingNormal(Normal):
            def start(self, emit):
                super().start(emit)
                stamp = h.clock.now()
                emit(TelemetryEvent(session_id, stamp, "raw_input", "wheel", Phase.ACTION,
                                    {"delta": 120, "direction": "up"}))
        session_id = "normal-pending"
        runtime = DiagnosticRuntime(clock=h.clock, normal_factory=lambda *_: EmittingNormal(h.calls),
                                    raw_factory=h.raw_factory, session_id_factory=lambda: session_id)
        def listener(event):
            seen.append(event)
            worker = threading.Thread(target=lambda: (runtime.status(), reentered.set()))
            worker.start(); worker.join(timeout=.5)
        runtime.add_event_listener(listener)
        runtime.start_normal()
        self.assertEqual([event.session_id for event in seen], [session_id])
        self.assertTrue(reentered.is_set())
        self.assertNotIn("wrong-session", runtime.status().error or "")

    def test_listener_runs_after_lock_release_and_can_reenter_across_thread(self):
        h = Harness(); runtime = h.runtime(); completed = threading.Event()
        callback_thread = []; lifecycle_thread = []
        def listener(event):
            callback_thread.append(threading.get_ident())
            def stop_from_worker():
                lifecycle_thread.append(threading.get_ident())
                runtime.stop_raw()
                completed.set()
            worker = threading.Thread(target=stop_from_worker)
            worker.start(); worker.join(timeout=.5)
        runtime.add_event_listener(listener)
        sid = runtime.start_raw(); source_thread = threading.get_ident()
        event = TelemetryEvent(sid, h.clock.now(), "raw_accelerator", "raw_accelerator",
                               Phase.ACTION, {"value": 100})
        h.bundles[0].accelerator_source.emit(event)
        self.assertTrue(completed.is_set())
        self.assertEqual(callback_thread, [source_thread])
        self.assertNotEqual(lifecycle_thread, [source_thread])
        self.assertEqual(runtime.status().mode, RuntimeMode.STOPPED)

    def test_pre_lifecycle_close_failure_recovers_by_retrying_close_directly(self):
        h = Harness(); close_attempts = []
        def close():
            close_attempts.append("close")
            if len(close_attempts) == 1: raise RuntimeError("close failed")
        def factory(session_id, clock, phase):
            return RawAdapterBundle(h.identity, Control(h.fingerprints), Lifecycle(h.calls),
                                    Source(h.calls, "raw"), Source(h.calls, "input", fail_start=True), close)
        runtime = DiagnosticRuntime(clock=h.clock, normal_factory=h.normal_factory, raw_factory=factory)
        normal_id = runtime.start_normal()
        with self.assertRaisesRegex(RuntimeError, "input start failed"): runtime.start_raw()
        self.assertEqual(runtime.status().mode, RuntimeMode.RECOVERING)
        self.assertTrue(runtime.recover())
        self.assertEqual(runtime.status().mode, RuntimeMode.NORMAL)
        self.assertEqual(runtime.status().session_id, normal_id)
        self.assertNotIn("lifecycle.recover", h.calls)
        self.assertEqual(close_attempts, ["close", "close"])

    def test_stop_raw_releases_lock_before_joining_monitor(self):
        h = Harness(); runtime = h.runtime(); runtime.start_raw(); acquired = threading.Event()
        class Monitor:
            def join(self, timeout=None):
                worker = threading.Thread(target=lambda: (runtime.status(), acquired.set()))
                worker.start(); worker.join(timeout=.5)
            def is_alive(self): return False
        runtime._monitor_stop.set()
        old = runtime._monitor_thread
        if old is not None: old.join(timeout=.5)
        runtime._monitor_thread = Monitor()
        runtime.stop_raw()
        self.assertTrue(acquired.is_set(), "stop_raw held the runtime lock while joining monitor")

    def test_stop_close_failure_stays_recovering_until_close_retry_then_resumes_normal(self):
        h = Harness(); attempts = []
        def close():
            attempts.append("close")
            if len(attempts) < 2: raise RuntimeError("bundle close failed")
            h.calls.append("bundle.close")
        def factory(session_id, clock, phase):
            return RawAdapterBundle(h.identity, Control(h.fingerprints), Lifecycle(h.calls),
                                    Source(h.calls, "raw"), Source(h.calls, "input"), close)
        runtime = DiagnosticRuntime(clock=h.clock, normal_factory=h.normal_factory, raw_factory=factory)
        normal_id = runtime.start_normal(); runtime.start_raw()
        self.assertFalse(runtime.stop_raw())
        self.assertEqual(runtime.status().mode, RuntimeMode.RECOVERING)
        self.assertEqual(h.calls.count("normal.start"), 1)
        self.assertTrue(runtime.recover())
        self.assertEqual(runtime.status().mode, RuntimeMode.NORMAL)
        self.assertEqual(runtime.status().session_id, normal_id)
        self.assertEqual(h.calls.count("normal.start"), 2)
        self.assertEqual(attempts, ["close", "close"])

    def test_recovery_close_failure_retries_close_without_requiring_lifecycle_recovery_again(self):
        h = Harness(); close_attempts = []; recover_attempts = []
        lifecycle = Lifecycle(h.calls, stop_result=False)
        def recover_once():
            recover_attempts.append("recover")
            h.calls.append("lifecycle.recover")
            return len(recover_attempts) == 1
        lifecycle.recover = recover_once
        def close():
            close_attempts.append("close")
            if len(close_attempts) == 1: raise RuntimeError("bundle close failed")
            h.calls.append("bundle.close")
        bundle = RawAdapterBundle(h.identity, Control(h.fingerprints), lifecycle,
                                  Source(h.calls, "raw"), Source(h.calls, "input"), close)
        runtime = DiagnosticRuntime(clock=h.clock, normal_factory=h.normal_factory,
                                    raw_factory=lambda *_: bundle)
        runtime.start_normal(); runtime.start_raw(); self.assertFalse(runtime.stop_raw())
        self.assertFalse(runtime.recover())
        self.assertEqual(runtime.status().mode, RuntimeMode.RECOVERING)
        self.assertEqual(h.calls.count("normal.start"), 1)
        self.assertTrue(runtime.recover())
        self.assertEqual(runtime.status().mode, RuntimeMode.NORMAL)
        self.assertEqual(h.calls.count("normal.start"), 2)
        self.assertEqual(recover_attempts, ["recover"])
        self.assertEqual(close_attempts, ["close", "close"])

    def test_normal_partial_start_rolls_back_adapter_and_surfaces_cleanup_failure(self):
        h = Harness()
        adapter = Normal(h.calls, fail_start=True, fail_stop=True, fail_close=True)
        runtime = DiagnosticRuntime(clock=h.clock, normal_factory=lambda *_: adapter,
                                    raw_factory=h.raw_factory)
        with self.assertRaisesRegex(RuntimeError, "normal start failed after acquire.*normal stop failed.*normal close failed"):
            runtime.start_normal()
        self.assertEqual(h.calls, ["normal.start", "normal.stop", "normal.close"])
        self.assertEqual(runtime.status().mode, RuntimeMode.STOPPED)

    def test_state_transitions_and_clean_raw_order(self):
        h, runtime = Harness(), None
        runtime = h.runtime()
        self.assertEqual(runtime.status().mode, RuntimeMode.STOPPED)
        runtime.start_raw(RuntimeMode.QUALIFYING)
        self.assertEqual(runtime.status().mode, RuntimeMode.QUALIFYING)
        runtime.stop_raw()
        self.assertEqual(runtime.status().mode, RuntimeMode.STOPPED)
        self.assertEqual(h.calls, ["input.start", "lifecycle.start", "raw.start",
                                  "raw.stop", "input.stop", "lifecycle.stop", "bundle.close"])

    def test_start_rollback_cleans_every_started_part(self):
        h = Harness(raw_fail=True)
        runtime = h.runtime()
        with self.assertRaisesRegex(RuntimeError, "raw start failed"):
            runtime.start_raw(RuntimeMode.LIVE_RAW)
        self.assertEqual(runtime.status().mode, RuntimeMode.STOPPED)
        self.assertIn("lifecycle.stop", h.calls)
        self.assertIn("input.stop", h.calls)
        self.assertIn("bundle.close", h.calls)

    def test_each_raw_component_is_cleanup_owned_before_start_returns(self):
        scenarios = ("input", "lifecycle", "raw")
        for failing in scenarios:
            with self.subTest(failing=failing):
                h = Harness()
                def factory(session_id, clock, phase):
                    input_source = Source(h.calls, "input", failing == "input")
                    lifecycle = Lifecycle(h.calls)
                    raw_source = Source(h.calls, "raw", failing == "raw")
                    if failing == "lifecycle":
                        def fail_start():
                            h.calls.append("lifecycle.start")
                            raise RuntimeError("lifecycle start failed")
                        lifecycle.start = fail_start
                    return RawAdapterBundle(h.identity, Control(h.fingerprints), lifecycle,
                                            raw_source, input_source,
                                            lambda: h.calls.append("bundle.close"))
                runtime = DiagnosticRuntime(clock=h.clock, normal_factory=h.normal_factory,
                                            raw_factory=factory)
                with self.assertRaises(RuntimeError): runtime.start_raw()
                expected_stops = {
                    "input": ("input.stop",),
                    "lifecycle": ("lifecycle.stop", "input.stop"),
                    "raw": ("raw.stop", "lifecycle.stop", "input.stop"),
                }[failing]
                positions = [h.calls.index(call) for call in expected_stops]
                self.assertEqual(positions, sorted(positions))
                self.assertIn("bundle.close", h.calls)
                self.assertEqual(runtime.status().mode, RuntimeMode.STOPPED)

    def test_partial_lifecycle_start_with_unverified_end_stays_recovering(self):
        h = Harness()
        def factory(session_id, clock, phase):
            lifecycle = Lifecycle(h.calls, stop_result=False)
            def fail_start():
                h.calls.append("lifecycle.start")
                raise RuntimeError("lifecycle start failed")
            lifecycle.start = fail_start
            return RawAdapterBundle(h.identity, Control(h.fingerprints), lifecycle,
                                    Source(h.calls, "raw"), Source(h.calls, "input"),
                                    lambda: h.calls.append("bundle.close"))
        runtime = DiagnosticRuntime(clock=h.clock, normal_factory=h.normal_factory, raw_factory=factory)
        with self.assertRaisesRegex(RuntimeError, "lifecycle start failed"):
            runtime.start_raw()
        self.assertEqual(runtime.status().mode, RuntimeMode.RECOVERING)
        self.assertNotIn("bundle.close", h.calls)

    def test_partial_raw_start_recovery_keeps_bundle_and_resumes_normal_only_after_recover(self):
        h = Harness(); lifecycle = Lifecycle(h.calls, stop_result=False, recover_result=True)
        def fail_start():
            h.calls.append("lifecycle.start")
            raise RuntimeError("lifecycle start failed")
        lifecycle.start = fail_start
        bundle = RawAdapterBundle(h.identity, Control(h.fingerprints), lifecycle,
                                  Source(h.calls, "raw"), Source(h.calls, "input"),
                                  lambda: h.calls.append("bundle.close"))
        runtime = DiagnosticRuntime(clock=h.clock, normal_factory=h.normal_factory,
                                    raw_factory=lambda *_: bundle)
        normal_id = runtime.start_normal()
        with self.assertRaisesRegex(RuntimeError, "lifecycle start failed"):
            runtime.start_raw()
        self.assertEqual(runtime.status().mode, RuntimeMode.RECOVERING)
        self.assertEqual(h.calls.count("normal.start"), 1)
        self.assertNotIn("bundle.close", h.calls)
        self.assertTrue(runtime.recover())
        self.assertEqual(runtime.status().mode, RuntimeMode.NORMAL)
        self.assertEqual(runtime.status().session_id, normal_id)
        self.assertEqual(h.calls.count("normal.start"), 2)
        self.assertIn("lifecycle.recover", h.calls)
        self.assertIn("bundle.close", h.calls)

    def test_partial_normal_resume_is_stopped_and_closed_before_ownership_release(self):
        h = Harness()
        adapters = [Normal(h.calls), Normal(h.calls, fail_start=True,
                                            fail_stop=True, fail_close=True)]
        runtime = DiagnosticRuntime(clock=h.clock, normal_factory=lambda *_: adapters.pop(0),
                                    raw_factory=h.raw_factory)
        runtime.start_normal(); runtime.start_raw(); runtime.stop_raw()
        self.assertEqual(runtime.status().mode, RuntimeMode.STOPPED)
        self.assertEqual(h.calls[-3:], ["normal.start", "normal.stop", "normal.close"])
        self.assertIn("normal observation resume failed", runtime.status().error)
        self.assertIn("normal stop failed", runtime.status().error)
        self.assertIn("normal close failed", runtime.status().error)

    def test_failed_normal_pause_reopens_normal_and_never_acquires_raw(self):
        h = Harness(); adapters = [Normal(h.calls, fail_stop=True), Normal(h.calls)]
        def normal_factory(*_): return adapters.pop(0)
        raw_calls = []
        runtime = DiagnosticRuntime(clock=h.clock, normal_factory=normal_factory,
                                    raw_factory=lambda *_: raw_calls.append("raw factory"))
        normal_id = runtime.start_normal()
        with self.assertRaisesRegex(RuntimeError, "normal stop failed"):
            runtime.start_raw()
        self.assertEqual(runtime.status().mode, RuntimeMode.NORMAL)
        self.assertEqual(runtime.status().session_id, normal_id)
        self.assertEqual(h.calls, ["normal.start", "normal.stop", "normal.close", "normal.start"])
        self.assertEqual(raw_calls, [])

    def test_normal_pause_clean_resume(self):
        h, runtime = Harness(), None
        runtime = h.runtime()
        normal_id = runtime.start_normal()
        runtime.start_raw(RuntimeMode.LIVE_RAW)
        self.assertLess(h.calls.index("normal.stop"), h.calls.index("input.start"))
        runtime.stop_raw()
        self.assertEqual(runtime.status().mode, RuntimeMode.NORMAL)
        self.assertEqual(runtime.status().session_id, normal_id)
        self.assertEqual(h.calls.count("normal.start"), 2)

    def test_failed_cleanup_blocks_resume_and_recovery_restores_it(self):
        h, runtime = Harness(stop_result=False), None
        runtime = h.runtime(); runtime.start_normal(); runtime.start_raw(RuntimeMode.LIVE_RAW)
        self.assertFalse(runtime.stop_raw())
        self.assertEqual(runtime.status().mode, RuntimeMode.RECOVERING)
        self.assertEqual(h.calls.count("normal.start"), 1)
        self.assertTrue(runtime.recover())
        self.assertEqual(runtime.status().mode, RuntimeMode.NORMAL)
        self.assertEqual(h.calls.count("normal.start"), 2)

    def test_stale_and_error_health_trigger_cleanup(self):
        for health in ("stale", "error"):
            with self.subTest(health=health):
                h = Harness(); runtime = h.runtime(); runtime.start_raw(RuntimeMode.LIVE_RAW)
                h.bundles[0].accelerator_source.health = health
                deadline = time.monotonic() + .5
                while runtime.status().mode is not RuntimeMode.STOPPED and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(runtime.status().mode, RuntimeMode.STOPPED)
                self.assertIn("capture failure", runtime.status().error)

    def test_reconnect_recovery_path_and_fingerprint_mismatch(self):
        changed = DeviceFingerprint("Tyon", ("changed",) * 5)
        h = Harness(stop_result=False, fingerprints=[DeviceFingerprint("Tyon", ("same",) * 5), changed])
        runtime = h.runtime(); runtime.start_raw(RuntimeMode.LIVE_RAW); runtime.stop_raw(); runtime.recover()
        self.assertEqual(runtime.status().mode, RuntimeMode.STOPPED)
        self.assertIn("fingerprint mismatch", runtime.status().error)

    def test_orders_interleaved_events_and_rejects_wrong_session_and_gap(self):
        h = Harness(); runtime = h.runtime(); seen = []; runtime.add_event_listener(seen.append)
        sid = runtime.start_raw(RuntimeMode.LIVE_RAW); raw = h.bundles[0].accelerator_source; inp = h.bundles[0].input_source
        def event(seq, source="raw_accelerator", kind="raw_accelerator", session=sid, payload=None):
            return TelemetryEvent(session, Timestamp(seq * 1_000_000, datetime.now(timezone.utc), seq), source, kind,
                                  Phase.ACTION, payload or {"value": seq})
        inp.emit(event(3, "raw_input", "wheel", payload={"delta": 120, "direction": "up"}))
        raw.emit(event(2)); raw.emit(event(4)); raw.emit(event(5, session="wrong"))
        runtime.stop_raw()
        self.assertEqual([e.timestamp.sequence for e in seen], [2, 3, 4])
        self.assertIn("wrong-session", runtime.status().error)
        # A second session with a missing sequence surfaces the final-drain gap.
        sid = runtime.start_raw(RuntimeMode.LIVE_RAW); seen.clear(); raw = h.bundles[1].accelerator_source
        start = h.clock.sequence
        raw.emit(event(start + 1, session=sid)); runtime.stop_raw()
        self.assertIn("sequence gap", runtime.status().error)

    def test_snapshot_contains_only_measured_values(self):
        h = Harness(); runtime = h.runtime(); sid = runtime.start_raw(RuntimeMode.LIVE_RAW, arithmetic_baseline=100)
        raw, inp = h.bundles[0].accelerator_source, h.bundles[0].input_source
        first = h.clock.now(); second = h.clock.now()
        raw.emit(TelemetryEvent(sid, first, "raw_accelerator", "raw_accelerator", Phase.ACTION, {"value": 104}))
        raw.emit(TelemetryEvent(sid, second, "raw_accelerator", "raw_accelerator", Phase.ACTION, {"value": 106}))
        wheel = h.clock.now(); inp.emit(TelemetryEvent(sid, wheel, "raw_input", "horizontal_wheel", Phase.ACTION,
                                                       {"delta": -120, "direction": "left"}))
        snap = runtime.snapshot()
        self.assertEqual((snap.raw_value, snap.arithmetic_baseline_delta), (106, 6))
        self.assertAlmostEqual(snap.sample_rate_hz, 100.0)
        self.assertEqual(snap.latest_windows_output["kind"], "horizontal_wheel")
        self.assertGreaterEqual(snap.sample_age_ms, 0)

    def test_controller_is_thin_and_platform_neutral(self):
        source = inspect.getsource(DiagnosticController)
        for forbidden in ("hid", "ctypes", "PySide6", "windows"):
            self.assertNotIn(forbidden, source)
        h = Harness(); runtime = h.runtime(); controller = DiagnosticController(runtime)
        self.assertEqual(controller.start_normal(), runtime.status().session_id)
        self.assertEqual(controller.status(), runtime.status())

    def test_concurrent_start_is_exclusive(self):
        h = Harness(); runtime = h.runtime(); barrier = threading.Barrier(9); outcomes = []; lock = threading.Lock()
        def compete():
            barrier.wait()
            try: runtime.start_normal(); result = "won"
            except RuntimeError: result = "lost"
            with lock: outcomes.append(result)
        threads = [threading.Thread(target=compete) for _ in range(8)]
        for thread in threads: thread.start()
        barrier.wait()
        for thread in threads: thread.join()
        self.assertEqual(outcomes.count("won"), 1)

    def test_public_runtime_has_no_physical_state_inference(self):
        text = inspect.getsource(DiagnosticRuntime).lower()
        for forbidden in ("touched", "released", "physically_centered"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
