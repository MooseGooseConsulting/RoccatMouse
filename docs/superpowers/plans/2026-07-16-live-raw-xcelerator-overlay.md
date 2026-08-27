# Live raw X-Celerator overlay implementation plan

- Status: Ready for the coexistence spike; overlay implementation is gated on its result
- Branch: `feature/continuous-windows-telemetry`
- Product target: Windows 11 and the connected ROCCAT Tyon
- Safety boundary: start/end raw streaming only; never save calibration

## Why

The reported fault feels as though the X-Celerator remains logically stuck in
the up direction after the physical paddle has returned to center. Windows then
receives unwanted alternating or continuing scroll output. The missing evidence
is the raw paddle value at the moment the owner can see that the physical paddle
is centered.

The useful product is therefore a small transparent, always-on-top instrument
that continuously shows exactly what raw value the mouse reports and records it
around a symptom marker. It must not claim to detect physical touch or physical
position. The owner performs that comparison visually.

## Verified facts and limitations

- Raw calibration streaming emits report `0x03`, type `0xe0`, with the 0..255
  X-Celerator value in byte 4 at roughly 90 reports per second on this mouse.
- Raw streaming is entered with function `0x08` and ended with `0x0a`. Function
  `0x0b`, which saves calibration, is forbidden in diagnostics.
- The successful normal paddle-only capture recorded 125 Windows scroll events,
  but every WinMM axis was constant for the entire action phase. WinMM is not a
  paddle-position source on this hardware.
- Normal-mode MI_03 monitoring has not produced a continuous paddle-position
  report. The only verified position stream is calibration raw mode.
- Windows Raw Input identifies the Tyon but does not say whether a wheel-format
  event came from the physical wheel or the scroll-mapped paddle.
- Software cannot detect whether the owner is physically touching or releasing
  the paddle. `hands off`, `released`, and `physically centered` are owner
  annotations.
- Two existing raw captures contain concurrent scroll events; several contain
  none. Those historical runs did not control and attribute the scroll source
  rigorously enough to prove that normal paddle scrolling survives raw mode.

## Gate A: prove raw display and normal scrolling can coexist

This gate runs before building the persistent overlay.

1. Replace the raw runner's global scroll fallback with device-attributed
   `RawInputSource` for the coexistence test.
2. Record a labelled normal-output baseline with the physical wheel untouched.
3. Enter raw streaming through `RawModeLifecycle`, display the live raw value,
   and record raw values plus Tyon-attributed wheel output on one QPC clock.
4. During a labelled action phase, move only the paddle slowly up, center,
   slowly down, center, then repeat quickly in both directions.
5. Repeat across reconnects until both directions and cleanup behavior are
   reproducible, ending raw mode and verifying normal scroll behavior and
   profile fingerprints after every run.
6. Record whether entering raw mode changes, suppresses, delays, or duplicates
   paddle-generated scroll output.

Gate A passes only if raw values and ordinary paddle-generated scroll output are
both present, correctly ordered, and repeatable while raw mode is active. A
successful end command and unchanged profiles are mandatory.

If Gate A fails, do not ship the overlay as a simultaneous symptom diagnostic.
Document that the device cannot expose its raw paddle value without changing the path
under test. The fallback is a clearly labelled sensor-scope mode launched
immediately after a symptom, plus external/user observation; it cannot claim
same-instant causality.

## Overlay behavior after Gate A passes

The overlay is a frameless PySide6 window with configurable opacity and
always-on-top behavior. It has a lockable click-through mode so it cannot steal
mouse input during normal work.

It displays:

- current raw value, exactly as reported, from 0 through 255;
- a large vertical bar/needle so a stuck high or low value is visible at a
  glance;
- read-only stored min/mid/max calibration values when the INFO report exposes
  them successfully;
- delta from the stored midpoint, labelled as arithmetic rather than inferred
  physical position;
- sample age and report rate so a frozen overlay is distinguishable from a
  frozen sensor value;
- raw-stream, device connection, persistence, and cleanup-marker status;
- the most recent Tyon scroll direction as output context, explicitly labelled
  `Windows output`, not `paddle`;
- confirmation that a symptom marker was saved.

The overlay never displays `touched`, `released`, or `physically centered` as a
deduced state. Those words appear only in an owner-authored marker or selected
trial phase.

## Logging model

Raw values are measured continuously while the owner explicitly runs the
overlay session. Automatic startup remains disabled until long-running raw mode
has hardware evidence and an explicit product decision.

- Keep a configurable full-rate rolling raw buffer. Set its initial duration
  from measured owner marker latency rather than an arbitrary soak interval.
- Store one-second raw aggregates for the entire session: count, first, last,
  min, max, mean, midpoint crossings, report gaps, and time at each extreme
  band.
- On **Mark symptom**, immediately retain the rolling pre-marker buffer and
  continue retaining full-rate samples for the configured post-marker window.
- Record Tyon-attributed Windows scroll events on the same QPC/UTC timeline.
- Let the owner attach exact annotations such as `physical paddle centered;
  overlay still high` or `hands off; unwanted up/down output`.
- Preserve marked full-rate windows until explicit deletion. Unmarked rolling
  samples may be overwritten; their one-second aggregates follow normal local
  retention.

This provides continuous measurement without writing every approximately 90 Hz
sample to permanent storage forever. The marked incident remains full fidelity.

## Components

1. Extract a `RawAcceleratorSource` from `tyon_monitor.py` into
   `roccatmouse/diagnostics/windows/raw_accelerator.py`. It owns MI_03 reads and
   emits timestamped raw-value events; it does not own lifecycle policy.
2. Extend the raw lifecycle controller with explicit health state, last-report
   time, and idempotent cleanup suitable for a long-lived session.
3. Add an overlay-session runtime that coordinates `RawModeLifecycle`,
   `RawAcceleratorSource`, `RawInputSource`, the shared QPC clock, the rolling
   buffer, and durable symptom markers.
4. Add a numbered SQLite migration for raw one-second aggregates and retained
   full-rate marker windows. Use batched writes and bounded queues.
5. Add `roccatmouse/diagnostics/raw_overlay.py` and expose it from both the tray
   menu and Diagnostics page.
6. Add a keyboard shortcut and tray action for an immediate marker. Notes may
   be added after the timestamp is committed.
7. Add an inspection/export command so a marked raw window and its scroll
   context can be reviewed without manually querying SQLite.

## Lifecycle and safety

- Write the recovery marker before sending raw start.
- Verify the device acknowledges raw start before showing live status.
- Send raw end on Stop, window close, application exit, exceptions, source
  stalls, device removal, Windows session end, and recoverable reconnect.
- Keep the recovery marker when end acknowledgement fails. On the next launch,
  retry end before allowing a new start.
- Treat a missing raw report beyond the tested timeout as `stream stalled`, not
  as a stable paddle value.
- Never send calibration-save function `0x0b`.
- Never change button mappings to obtain telemetry in this milestone.
- Fingerprint all five profile settings/button maps before and after each
  bounded hardware acceptance run.

## Tests

Automated tests cover:

- raw report parsing, timestamp order, duplicate and missing reports;
- start acknowledgement, end acknowledgement, stale-marker recovery, and every
  cleanup path;
- coexistence-session ordering of raw values and Raw Input scroll events;
- rolling-buffer eviction and marker-window promotion;
- aggregate calculations and report-gap detection;
- persistence failure, backpressure, device removal, cancellation, and restart;
- overlay stale-sample state, click-through/opacity settings, and offscreen Qt
  startup/stop;
- explicit proof that the software never infers touch or physical position.

## Hardware acceptance

1. Pass Gate A and commit its exact capture evidence.
2. Confirm the overlay visibly follows center, full up, center, full down, and
   center while the owner observes the physical paddle.
3. Leave the overlay active through normal use until either a real symptom is
   marked or the owner ends the work session. No arbitrary fixed soak duration
   is a diagnostic requirement.
4. When the fault occurs, mark whether the physical paddle is centered and
   compare that owner statement with the retained raw value and Windows output.
5. Force-close the process, relaunch, verify stale recovery, and confirm the
   mouse returns to normal operation.
6. Verify unchanged profiles and no calibration save in all captured control
   traffic.
7. Record memory, CPU, database growth, and report gaps for the actual session;
   use those measurements to set retention and batching defaults.

## What the resulting evidence can say

- `Owner says physically centered; raw remains near high endpoint` supports a
  sensor/calibration/device-state fault.
- `Owner says physically centered; raw returns to midpoint; Windows output
  continues` supports a fault downstream of the raw sensor reading.
- `Raw display is stale` says nothing about paddle position and is reported as
  a capture failure.
- Without an owner annotation, the software can describe raw values and output
  timing but cannot assert physical position or intent.

No calibration, remapping, filtering, or correction is implemented by this
plan. A correction proposal follows only after a retained real incident makes
one fault layer materially better supported than the alternatives.

## Ready condition

The overlay scope is ready for review when Gate A passes, the overlay and marker
window work against the connected mouse, every cleanup/recovery test passes, a
real or deliberately controlled marked session exports reproducibly, profiles
remain unchanged, and the documentation states the touch/attribution limits
without inference.
