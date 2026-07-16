---
title: RoccatMouse Architecture
date: 2026-07-15
author: MooseGooseConsulting
status: living
last_confirmed: 2026-07-15
---

# RoccatMouse Architecture

## Architecture Thesis

Keep the proven Python/PySide6 Windows configurator as the product base, isolate platform-specific device and input access behind narrow adapters, and treat capture, storage, analysis, and correction as an evidence pipeline with explicit lifecycle and safety boundaries.

## Status Legend

- **Current:** implemented and validated in the repository.
- **Planned:** accepted direction with an implementation plan.
- **Candidate:** plausible direction that still requires evidence or a spike.
- **Deferred:** intentionally outside the active Windows milestone.

## System Shape

| Area | Status | Responsibility |
|---|---|---|
| Windows configurator | Current | RGB, DPI, polling, profiles, buttons, macros, and per-game behavior through the existing Telephony HID route. |
| Controlled capture | Current | Bounded paddle and wheel trials, WinMM axes, MI_03 reports, scroll deltas, raw-mode recovery, CSV export, and compact GUI. |
| Platform contracts | Current | `DeviceControl`, `AcceleratorSource`, `InputEventSource`, `TelemetrySink`, `Clock`, and `CaptureSession` boundaries; persistent store and analysis contracts arrive with their milestones. |
| Normal-mode trial engine | Current | Guided neutral, paddle-only, wheel-only, symptom-reproduction, and general-observation phases without entering raw calibration mode. |
| Continuous observation | Current | On-demand tray runtime, normal Tyon Raw Input, one-second aggregates, discrete events, durable symptom markers, clean start/stop, and 30-day retention. |
| Observation resilience | Planned | Disconnect/reconnect transitions, bounded backoff, startup recovery, inspection/export commands, and eight-hour soak evidence. |
| Telemetry database | Current | Local SQLite database in WAL mode with numbered migrations, sessions/events/aggregates/markers, strict sequence uniqueness, and 30-day continuous-session retention. |
| Analysis dashboard | Planned | Live and historical accelerator/axis/scroll plots, anomaly markers, comparisons, and diagnosis summaries. |
| Corrective tooling | Candidate | Evidence-gated calibration, mapping, or host intervention with backup, preview, confirmation, readback, and rollback. |
| Linux adapter | Deferred | hidraw/HIDAPI, udev, `evdev`, packaging, and licensing spike after the Windows soak. |

## Signal Boundaries

The diagnostic chain is:

`physical paddle → analog sensor → device calibration/profile → HID and Windows wheel events → application scrolling`

Raw calibration streaming exposes sensor truth but may suppress the normal scroll mapping. Raw and normal captures are therefore separate controlled trials unless hardware evidence proves simultaneous observation is reliable. Cursor movement and `GetCursorPos` are outside this chain.

## Core Contracts

- **DeviceControl:** enumerate/open the required collections, read/write feature reports, fingerprint profiles, enter/exit bounded raw mode, and recover an unclean session.
- **AcceleratorSource:** emit timestamped raw accelerator or WinMM axis samples without owning session policy.
- **InputEventSource:** emit device-attributed relative movement, buttons, and wheel deltas; X-Celerator analysis consumes wheel deltas, not cursor coordinates.
- **TelemetryStore:** migrate schemas and persist sessions, events, aggregates, markers, notes, exports, and retention state.
- **CaptureSession:** own state transitions, phase labels, cancellation, disconnect/reconnect, cleanup, and clean/unclean completion.
- **AnalysisEngine:** calculate deterministic metrics from platform-neutral records and produce evidence with its assumptions attached.

## Data and Timestamp Invariants

- Every event has a session ID, monotonically increasing sequence, QPC-derived monotonic timestamp, UTC timestamp, source, kind, and trial phase.
- Continuous observation stores one-second aggregates plus discrete input/anomaly events; explicit high-fidelity sessions store full-rate samples.
- Continuous data expires after 30 days. Marked high-fidelity sessions remain until export or deletion.
- Configuration lives at `%APPDATA%\RoccatMouse\config.json`; telemetry lives at `%LOCALAPPDATA%\RoccatMouse\telemetry.sqlite3`.
- Telemetry is local by default and never requires an account.

## Safety Invariants

- Raw diagnostics send start/end only and never send the save-calibration function.
- A recovery marker exists before raw-mode start and is cleared only after verified exit.
- Cancellation, exceptions, reconnects, and startup after an unclean session all attempt raw-mode exit.
- Corrective device writes remain unavailable until evidence supports a specific intervention.
- Any future correction backs up the affected state and leaves unrelated profile data untouched.

## Decision Index

- `docs/decisions/0001-windows-first-product-base.md`
- `docs/decisions/0002-separate-sensor-and-scroll-truth.md`
- `docs/decisions/0003-local-telemetry-policy.md`
- `docs/decisions/0004-raw-mode-and-correction-safety.md`
- `docs/decisions/0005-linux-licensing-gate.md`
