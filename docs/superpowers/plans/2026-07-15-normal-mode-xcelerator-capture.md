# Normal-mode X-Celerator capture implementation plan

- Status: Planned
- Branch: `feature/normal-mode-xcelerator-diagnostics`
- Depends on: controlled-capture foundation and documentation authority merged to `main`

## Why

Raw capture proved that the analog paddle can be observed, but raw calibration mode may suppress the ordinary scroll mapping. The next missing evidence is a guided normal-mode paddle trial that records the Windows-facing behavior without entering raw mode. This is what separates a stable sensor with bad mapping/output from a genuinely unstable sensor.

## Goal

Deliver platform-neutral capture contracts and a guided normal-mode session engine that records labelled phases, WinMM axes, MI_03 reports, and device-attributed Windows Raw Input events with QPC/UTC timestamps. Preserve the existing raw workflow, CSV compatibility, and configurator behavior.

## Public model and contracts

Create `roccatmouse/diagnostics/` with:

- `models.py`: `TrialLabel`, `CaptureMode`, `SessionState`, `Phase`, `Timestamp`, `TelemetryEvent`, `DeviceFingerprint`, and `SessionResult` dataclasses/enums.
- `contracts.py`: runtime-checkable `Protocol` definitions for `DeviceControl`, `AcceleratorSource`, `InputEventSource`, `TelemetrySink`, and `Clock`.
- `session.py`: the only owner of preparation, baseline, action, cancellation, reconnect, cleanup, and completion transitions.
- `windows/clock.py`: QPC monotonic timestamp paired with UTC and session sequence.
- `windows/winmm.py`: adapter around the existing WinMM code.
- `windows/mi03.py`: adapter around existing normal/raw special-report reads.
- `windows/raw_input.py`: hidden-window Raw Input loop using `ctypes`, registering the target mouse and emitting relative movement, button, and wheel events with device identity.

Do not expose screen coordinates or `GetCursorPos`. Relative motion remains a general input event; X-Celerator analysis consumes accelerator, special-report, and wheel events.

## Test-first implementation sequence

1. Add model tests for enum values, immutable timestamps, monotonic sequence, and serializable event payloads; then implement `models.py`.
2. Add contract conformance tests using fake sources/sinks; then implement `contracts.py`.
3. Add session tests for the valid state graph: `created → preparing → baseline → action → stopping → completed`, plus cancelled, failed, disconnected, and recovered outcomes; then implement `session.py`.
4. Extract existing WinMM and MI_03 behavior behind adapters without changing report bytes. Run the existing 29 tests after each extraction.
5. Add synthetic Raw Input parser tests for movement, buttons, vertical wheel, horizontal wheel, target-device filtering, and malformed packets; then implement the hidden-window adapter.
6. Add a CSV sink that writes the new common event schema while continuing to read foundation CSVs that contain the old fields. New files never include `cursor_x` or `cursor_y`.
7. Update `tyon_monitor.py` to compose the adapters and session engine while preserving existing CLI arguments. Add `neutral`, `paddle_only`, `wheel_only`, `symptom_reproduction`, and `general_observation` labels; retain `paddle`/`wheel` as accepted CLI aliases for existing scripts.
8. Update `tyon_capture_gui.py` with guided phase prompts, visible per-source event counts, a symptom-marker button, notes, cancellation state, and cleanup status.
9. Add a Diagnostics entry point to the main configurator without moving or changing existing configuration pages.
10. Update README, component documentation, acceptance workflow, and `PROGRESS.md` with actual commands and current status.

## Failure behavior

- Source startup failure fails the session with the source name and leaves already-started sources stopped.
- Disconnect records a marker, stops ingestion, attempts safe reconnect, and never restarts raw mode without a fresh lifecycle transition.
- Cancellation is cooperative and bounded; raw cleanup still runs.
- Events with duplicate QPC values remain ordered by sequence.
- A Raw Input device mismatch is discarded and counted, not silently accepted.
- Raw mode continues to reject wheel-only trials and never saves calibration.

## Automated validation

- Existing foundation tests remain green.
- Model, contract, session lifecycle, Raw Input parsing, timestamp ordering, cancellation, reconnect, and CSV compatibility tests pass.
- Compilation and offscreen GUI smoke tests pass.
- `--raw --list` remains read-only.
- CI runs on Windows and exercises every non-hardware code path.

## Hardware acceptance

Run the workflow in `docs/workflows/controlled-diagnostics.md` through the normal paddle-only and wheel-only trials. Confirm MI_03, WinMM, and Raw Input event counts; verify wheel direction/deltas; confirm no cursor movement expectation exists; compare all five profile fingerprints before and after.

## PR stop condition

Open a non-draft PR only after automated checks and both controlled normal-mode trials pass. Self-review the complete diff, address and resolve every valid review thread, rerun CI/hardware-safe checks, merge, update `main`, and only then begin continuous telemetry.
