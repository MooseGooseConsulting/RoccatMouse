# Analysis engine and diagnostics dashboard implementation plan

- Status: Planned
- Branch: `feature/diagnostics-dashboard`
- Depends on: continuous storage merged and measured stability evidence recorded

## Why

Stored samples do not by themselves explain whether the paddle is noisy, drifting, sticking, reversing, or generating scroll after release. A deterministic analysis layer and first-class dashboard turn captures into comparable evidence without asking the owner to inspect CSV rows manually.

## Goal

Add platform-neutral analyzers, live/historical visualizations, anomaly markers and notes, session comparison, export, and deletion inside the configurator. Do not add cursor-movement analysis or corrective writes.

## Analysis API

Create `roccatmouse/diagnostics/analysis/` with pure functions returning versioned result dataclasses:

- neutral noise: median, span, median absolute deviation, and outlier count;
- center drift: change between baseline windows and slope over a neutral soak;
- endpoints: observed min/max and repeatability by direction;
- reversals/hysteresis: direction changes and value difference for matched outbound/return crossings;
- return-to-center: release-to-neutral latency and failure-to-return intervals;
- stuck intervals: duration outside the neutral band after expected release;
- scroll bursts: direction, count, inter-event interval, and post-release repetition;
- timing relationships: nearest MI_03/axis/wheel events using monotonic timestamps;
- diagnosis summary: evidence per signal-chain layer, confidence limitations, and recommended next trial.

Thresholds are stored with the analysis version and session result. Defaults come from each session's measured neutral distribution; they are not hard-coded calibration corrections.

## Dashboard shape

- Add a Diagnostics page reachable from the existing configurator and tray.
- Live view: accelerator/axis traces, wheel deltas, source health, active phase, cleanup state, and symptom marker.
- History view: session list, labels, notes, anomalies, metrics, and retained/exported state.
- Compare view: align two or more sessions by phase and show metric deltas.
- Actions: add note, mark anomaly, export CSV/JSON summary, retain/release retention, and delete with confirmation.
- Draw plots with PySide6 widgets to avoid adding a plotting dependency unless profiling proves that approach inadequate.

## Test-first implementation sequence

1. Add synthetic traces with known noise, drift, endpoints, reversals, return latency, stuck periods, and scroll bursts.
2. Write failing unit tests for every metric and edge case, then implement pure analyzers.
3. Test analysis-version persistence and reproducible reruns against stored sessions.
4. Test diagnosis classification for sensor/mechanical, calibration/profile, Windows output, and application-level evidence; ambiguous evidence must request another trial rather than assert a fix.
5. Add model/view tests for filtering, comparison alignment, export, retained state, and deletion.
6. Implement live plots with bounded in-memory windows and downsampling for display only; never mutate stored raw values.
7. Implement historical views and actions against `TelemetryStore`.
8. Add CSV and JSON export with schema/version metadata and verify round trips.
9. Integrate the dashboard into the configurator and tray, preserving every existing configuration page.
10. Update README, component docs, acceptance workflow, architecture status, and `PROGRESS.md`.

## Automated validation

- Synthetic analyzers produce exact expected metrics and marker locations.
- Timestamp ties, missing sources, empty sessions, cancelled sessions, and corrupted payloads have deterministic outcomes.
- Live plotting remains bounded during an accelerated long-running synthetic stream.
- Export/import round trips preserve event ordering, labels, notes, and analysis version.
- Offscreen dashboard smoke tests and the full Windows CI suite pass.

## Hardware acceptance

Analyze the neutral, raw paddle, normal paddle, wheel-only, and symptom sessions. Confirm the dashboard never treats cursor motion as expected evidence. Produce a committed diagnosis report that identifies the supported fault layer or explicitly states what additional controlled trial is needed.

## PR workflow and ready condition

Open a draft PR after the first coherent dashboard slice is pushed. Mark it ready
after synthetic and hardware sessions render and compare correctly, exports
round-trip, memory remains bounded, and the diagnosis report is reproducible.
Self-review, address all valid feedback, merge, and update `main` before
implementing a correction.
