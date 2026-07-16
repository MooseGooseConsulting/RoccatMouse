# Evidence-gated correction implementation plan

- Status: Planned, gated by a reproducible dashboard diagnosis
- Branch: `feature/evidence-gated-xcelerator-correction`
- Depends on: analysis dashboard merged and diagnosis evidence accepted by its deterministic decision tree

## Why

The project exists to help fix the X-Celerator problem, not only record it. Correction must target the layer that evidence identifies. Writing calibration for a mechanical sensor fault or filtering events caused by an application would hide evidence and risk damaging otherwise-correct profiles.

## Entry gate

This milestone starts only when retained before-state sessions reproduce the symptom and the analyzer classifies one of these paths:

1. **Mechanical/sensor instability:** deliver a hardware diagnosis and verification workflow; expose no device write.
2. **Stable raw signal with inconsistent stored calibration/profile:** implement the supported device calibration or mapping correction.
3. **Stable device state with incorrect Windows events:** implement a reversible host mapping/filter intervention isolated from configurator data.
4. **Correct Windows events with application-only failure:** deliver an application diagnosis; expose no mouse correction.

If evidence is ambiguous, the implementation action is another named controlled trial, not a guessed correction.

## Correction contract

Create a `CorrectionPlan` model containing the diagnosis and supporting session IDs, target layer, affected fields, current/proposed values, unrelated-state fingerprint, backup path/checksum, validation trial, rollback payload, and lifecycle status.

Create `CorrectionProvider` implementations only for the evidence-supported path. Every provider supports `inspect`, `prepare`, `preview`, `apply`, `verify`, and `rollback`. No provider may combine diagnostic raw streaming with a save operation.

## Test-first implementation sequence

1. Commit the diagnosis evidence and identify the single correction path selected by the gate.
2. Test the state machine: apply requires backup and confirmation; verify requires apply; rollback is available after partial write.
3. Test byte-exact protocol or host-rule behavior for the selected provider with fake devices/sources.
4. Implement read-only inspection and backup; verify backup checksums and full profile fingerprints.
5. Implement a UI preview showing every changed field, unchanged-state fingerprint, evidence links, validation steps, and rollback.
6. Add explicit product confirmation scoped to the displayed plan; invalidate it if the device fingerprint changes.
7. Implement the smallest supported write or host intervention followed immediately by readback verification.
8. On mismatch or disconnect, stop further writes, mark failure, and offer rollback from the verified backup.
9. Run the exact before/after controlled trial and store both sessions with the correction plan.
10. Implement one-action rollback and repeat validation to prove reversibility.
11. Update architecture, decisions, component docs, acceptance, and `PROGRESS.md` with the actual supported correction and limits.

## Safety requirements

- Back up affected calibration/profile bytes before any write.
- Preserve RGB, DPI, polling, buttons, macros, and unrelated profiles unless the preview explicitly targets them.
- Never apply automatically on startup, reconnect, or anomaly detection.
- Require device identity and current fingerprint to match the prepared plan.
- Keep the original backup until the owner explicitly deletes it.
- A host intervention defaults off after crash/reinstall and has an immediate disable path.

## Automated validation

- State-machine, confirmation invalidation, byte construction/parsing, partial write, disconnect, readback mismatch, backup corruption, and rollback tests pass.
- Exhaustive fixtures show unrelated bytes remain identical.
- Existing raw-mode tests continue proving that save is absent from observation.
- The full Windows CI and offscreen UI suite pass.

## Hardware acceptance

Retain the before-state symptom session and profile fingerprint; prepare backup and preview; obtain confirmation; apply and read back; repeat neutral, paddle-only, wheel-only, and symptom trials; verify improvement without profile or cleanup regressions; roll back once and verify the original state; reapply only if the corrected state passed.

## PR stop condition

Do not open a non-draft PR for a generic or unproven correction. The PR must name the evidence-supported fault, include before/after/rollback results, preserve unrelated profiles, pass all tests, and document limitations. Self-review, address every valid review, and merge only after correction and rollback are hardware-verified.
