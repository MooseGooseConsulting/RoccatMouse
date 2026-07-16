# Reusable X-Celerator diagnostic runtime implementation plan

- Status: In progress on draft PR #6
- Branch: `feature/live-raw-xcelerator-overlay`
- Base: stacked on `feature/continuous-windows-telemetry` until PR #5 merges
- Product target: Windows 11 and the connected ROCCAT Tyon
- Safety boundary: raw start/end only; never save calibration
- Last confirmed: 2026-07-16

## Product decision

The earlier PowerShell-timed coexistence capture was an execution harness around
Gate A, not product architecture. It remains uncontrolled evidence and cannot
qualify the live overlay.

PR #6 becomes one integrated diagnostic product. Tray, configurator, CLI,
qualification, overlay, persistence, export, and later analysis all use the same
`DiagnosticController` and `DiagnosticRuntime`. No UI opens HID devices directly.

## Target architecture

```text
Tray / Configurator / CLI
          |
          v
DiagnosticController
          |
          v
DiagnosticRuntime + DeviceSessionArbiter
          |- DeviceControl / RawModeLifecycle
          |- RawAcceleratorSource (MI_03)
          |- RawInputSource (Windows output)
          |- RollingBuffer + RawAggregator
          `- MarkerWindowRecorder
                    |
                    v
           TelemetryWriter -> SQLite
                    |
                    v
        DiagnosticSnapshot -> OverlayWindow
```

`DeviceSessionArbiter` permits exactly one normal or raw hardware session.
Starting qualification or the overlay pauses normal observation. Normal
observation resumes only after verified raw cleanup. Failed cleanup leaves the
runtime recovering and blocks another device session.

Public runtime facts are `RuntimeMode`, `DeviceIdentity`, `DiagnosticStatus`,
`DiagnosticSnapshot`, and `QualificationResult`. They describe measured values,
ordering, durability, cleanup, and exact verdict reasons. They never infer
`touched`, `released`, or `physically_centered`; those concepts may appear only
as explicit owner observations attached to markers.

## Implementation sequence and stop conditions

### 1. Shared runtime foundation

Status: implemented and reviewed; checkpoint publication to draft PR #6 is the current pause point.

- [x] Extract MI_03 parsing, HID pairing, `RawAcceleratorSource`, and
  `RawModeLifecycle` from `tyon_monitor.py`.
- [x] Preserve unmatched reports as evidence and forbid calibration-save `0x0b`.
- [x] Add public runtime/status/snapshot/qualification types without physical-state
  inference.
- [x] Add thread-safe exclusive `DeviceSessionArbiter` with sticky recovery.
- [x] Add platform-neutral, dependency-injected `DiagnosticRuntime` and thin
  `DiagnosticController`.
- [x] Cover ordered mixed-source events, normal/raw handoff, cleanup, recovery,
  stale streams, fingerprint mismatch, and measured-only snapshots.

Durable commits: `1f50220`, `99f7cdc`, `2ee5dbb`, `6e05271`, `a8cc506`, `9acc3b2`, `9a9ca81`, `e2c25f6`, and `91ecec9`.

### 2. Incident persistence and export

Status: next implementation unit.

- [ ] Add a configurable 30-second full-rate rolling raw buffer and 30-second
  post-marker recorder.
- [ ] Persist one-second raw aggregates for every explicit overlay session:
  count, first, last, min, max, mean, midpoint crossings, report gaps, and
  time in endpoint bands.
- [ ] Add a numbered SQLite migration for raw aggregates, marker windows,
  deduplicated raw samples, typed owner observations, qualification evidence,
  and cleanup status.
- [ ] Persist Windows output immediately on the same QPC/UTC sequence.
- [ ] Make overlapping marker windows reference each raw event once.
- [ ] Retain marked sessions until explicit deletion; expire unmarked sessions
  after 30 days.
- [ ] Export a reproducible incident bundle with session metadata, raw samples,
  Windows output, aggregates, markers/observations, fingerprints, and cleanup.
- [ ] Generate bounded evidence statements: owner-reported center plus endpoint
  raw supports sensor/device-state fault; baseline raw plus continuing output
  supports a downstream fault; stale raw is capture failure only.

Stop condition: storage, overlap, retention, persistence-failure, backpressure,
export, and non-overclaim tests pass.

### 3. Integrated qualification

Status: pending persistence.

- [ ] Add **Qualify live paddle monitoring** to tray and Diagnostics page.
- [ ] Raise a PySide6 qualification window, play a system cue, and wait
  indefinitely for a recorded **I'm ready** acknowledgement.
- [ ] Run tool-owned countdown, baseline, GO cue, instructions, verification,
  cleanup, and result display.
- [ ] Require two acknowledged controlled passes, one after reconnect.
- [ ] Each pass requires raw values on both sides of baseline, healthy rate/gaps,
  Tyon Windows output in both directions, zero Raw Input drops, a complete
  window, verified cleanup, and unchanged profile fingerprints.
- [ ] Persist evidence session IDs and exact pass/failure reasons.
- [ ] Unlock the simultaneous live monitor only after a passing qualification.
  Otherwise expose only a clearly labelled sensor-scope mode with no
  simultaneous-output claim.

Stop condition: acknowledgement, two-pass/reconnect, failure-reason, cleanup,
and durable-unlock tests pass offscreen. Physical qualification remains pending
until the owner operates and reconnects the mouse.

### 4. Windows composition and thin CLI

Status: pending runtime persistence.

- [ ] Add the Windows adapter factory that pairs stable Tyon identity, control,
  MI_03 raw input, Raw Input output, and shared QPC clock.
- [ ] Make `tyon_monitor.py` a thin client of `DiagnosticController` rather than
  a second session runtime.
- [ ] Retain historical unattended captures as uncontrolled evidence only; they
  cannot change qualification state.
- [ ] Cover disconnect/reconnect, startup recovery, source stalls, cancellation,
  and every partial-start/cleanup path.

Stop condition: the CLI, tray, and configurator construct the same runtime and
no UI or CLI path opens HID independently.

### 5. Live overlay and application integration

Status: pending qualification implementation.

- [ ] Add transparent, frameless, always-on-top `OverlayWindow` with adjustable
  opacity and lockable click-through mode.
- [ ] Show raw value/bar, sample age/rate, stale warning, arithmetic baseline
  delta, stream/persistence/cleanup state, and separately labelled latest
  `Windows output`.
- [ ] Add immediate marker, typed owner-observation shortcuts, tray notification,
  overlay controls, and optional hotkey.
- [ ] Add tray and Diagnostics-page launch actions. Starting raw overlay pauses
  normal observation and verified cleanup resumes it.
- [ ] Test offscreen startup/stop, click-through flag preservation, opacity,
  stale display, marker confirmation, and absence of inferred physical state.

Stop condition: automated UI/runtime tests pass and the live monitor remains
locked behind persisted qualification.

### 6. Documentation, review, and hardware acceptance

Status: pending implementation.

- [ ] Add the single-runtime ADR and reconcile `architecture.md`, `PROGRESS.md`,
  and component documentation. The overlay remains `Candidate` until controlled
  qualification passes and becomes `Current` only when shipped.
- [ ] Run the complete unit suite, compileall, diff check, and bounded resource
  tests.
- [ ] After PR #5 merges, retarget draft PR #6 to `main`.
- [ ] Self-review PR #6 and address every valid unresolved comment/thread.
- [ ] Keep PR #6 draft while implementation or hardware acceptance remains.

Hardware acceptance requires two acknowledged controlled qualification runs,
one after reconnect; unchanged profiles; visible endpoint/center tracking; a
marked export; verified cleanup/recovery; and bounded CPU, memory, and database
growth during an actual work session.

## Explicit exclusions

Calibration, remapping, filtering, or other corrective writes remain unavailable.
A correction proposal begins only after a real marked incident supports one
intervention and its backup, preview, confirmation, readback, before/after trial,
and rollback workflow.
