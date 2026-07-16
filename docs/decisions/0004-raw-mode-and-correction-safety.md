# ADR 0004: Bound raw mode and gate corrective writes

- Status: Accepted
- Date: 2026-07-15

## Context

The Tyon calibration protocol includes start, end, and save operations. A diagnostic exception or disconnect can leave the device in an undesirable reporting mode, while an accidental save could change calibration before the fault is understood.

## Decision

Diagnostics send start and end only. A durable marker is written before start, cleanup is attempted on every exit path, and the marker is cleared only after verified end. Corrective writes are a separate, evidence-gated capability with backup, exact preview, explicit confirmation, readback, before/after testing, and rollback.

## Why

Raw sensor evidence is valuable without writing calibration. Separating observation from correction limits recovery risk and prevents a diagnostic session from becoming an undocumented device change.

## Consequences

- The save-calibration function is forbidden in diagnostic code and covered by tests.
- Startup and reconnect attempt cleanup when an unclean marker exists.
- A failed cleanup is visible and keeps the marker for retry.
- No corrective API is exposed until captured evidence identifies the appropriate layer and intervention.
