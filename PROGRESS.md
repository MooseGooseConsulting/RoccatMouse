---
title: RoccatMouse Progress
date: 2026-07-15
author: MooseGooseConsulting
status: living
last_confirmed: 2026-07-16
---

# RoccatMouse Progress

## Current State

- PR #1 merged to `main` as `a38f1d6` with the controlled-capture foundation.
- The Windows configurator remains intact.
- Eighty-five unit tests and the Windows CI workflow pass.
- Live discovery confirms the Tyon Telephony control collection and MI_03 special-report interface.
- Raw capture cleanup and all five onboard-profile reads have been verified on the connected Windows 11 system.
- The normal-mode engine records QPC/UTC ordered WinMM, MI_03, and device-attributed Raw Input events, but hardware evidence shows all WinMM axes remain constant during paddle movement and normal MI_03 does not provide a continuous paddle value.
- Existing controlled evidence shows stable one-count raw neutral noise, a raw paddle range of 24–210, asymmetric paddle scroll output (38/12), and balanced physical-wheel output (81/74); see `docs/history/2026-07-15-hardware-capture-evidence.md`.
- Empty controlled paddle/wheel trials now fail explicitly with exit code 5 and exact causes instead of producing a false pass.
- The final live read confirms active profile 1 maps both paddle directions to scrolling, all five profiles remain readable, and no raw-mode recovery marker exists.
- Direct sensor capture produced 1,092 reports over 26–209; a separate normal paddle trial produced 125 Tyon-attributed wheel-format events in both directions. Those separate surfaces do not yet prove same-instant raw-signal/output correlation.
- The continuous runtime now has atomic local config, SQLite/WAL migrations, bounded prioritized persistence, one-second aggregation, 30-day retention, tray start/stop, and immediate symptom markers with context queries.
- A live connected-Tyon smoke stored one session, 11 discrete events, seven aggregates, and one marker; the 30-second context query returned the surrounding data and shutdown was clean.
- Scroll CSVs contain deltas without pointer coordinates; cursor movement is not part of the diagnostic model.

## Active Work

- Branch: `feature/continuous-windows-telemetry`.
- PR #5 is open as a draft and continuous observation is running on the connected Tyon.
- The live raw overlay plan is at `docs/superpowers/plans/2026-07-16-live-raw-xcelerator-overlay.md`; implementation begins with the raw/normal-output coexistence gate.
- Review remediation on the current branch hardens raw-mode acknowledgement and cleanup reporting, rejects ambiguous multi-Tyon raw/control pairing, preserves raw CSV semantics, detects sequence gaps, and limits controlled-trial acceptance to action-phase wheel events.
- All historical actionable review threads on merged PRs #1, #3, and #4 have replies, fix references, and resolved GitHub thread state; PR #5 currently has no review threads or comments.
- Correct the continuous logger's output-only scope, run the coexistence gate, and implement the raw overlay only if the gate passes.

## Blockers

- No repository blocker.
- The critical hardware question is whether calibration raw streaming can coexist reliably with ordinary paddle-generated scrolling. Historical captures are mixed and do not prove it.
- Continuous observation currently records output events and markers but cannot observe physical touch or paddle position.
- Any corrective device write requires the product's explicit preview/confirmation step.

## Next Session Focus

1. Implement and run Gate A from the live raw overlay plan using raw values and device-attributed Raw Input on one clock.
2. If Gate A passes, implement the transparent overlay, rolling raw buffer, and marker-retained incident windows.
3. If Gate A fails, document the no-go result and implement only the explicitly separate sensor-scope fallback.
4. Reconcile PR #5 scope and documentation with the verified hardware result before further dashboard work.

## Handoff Pointers

- Intent and boundaries: `NORTH_STAR.md`
- Technical direction: `architecture.md`
- Existing hardware evidence and protocol sources: `docs/source-audit.md`
- Controlled hardware procedure: `docs/workflows/controlled-diagnostics.md`
- Current implementation plan: `docs/superpowers/plans/2026-07-16-live-raw-xcelerator-overlay.md`
