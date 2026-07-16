---
title: RoccatMouse Progress
date: 2026-07-15
author: MooseGooseConsulting
status: living
last_confirmed: 2026-07-15
---

# RoccatMouse Progress

## Current State

- PR #1 merged to `main` as `a38f1d6` with the controlled-capture foundation.
- The Windows configurator remains intact.
- Eighty-five unit tests and the Windows CI workflow pass.
- Live discovery confirms the Tyon Telephony control collection and MI_03 special-report interface.
- Raw capture cleanup and all five onboard-profile reads have been verified on the connected Windows 11 system.
- The normal-mode engine records QPC/UTC ordered WinMM, MI_03, and device-attributed Raw Input events; short live neutral captures preserve all five profile fingerprints.
- Existing controlled evidence shows stable one-count raw neutral noise, a raw paddle range of 24–210, asymmetric paddle scroll output (38/12), and balanced physical-wheel output (81/74); see `docs/history/2026-07-15-hardware-capture-evidence.md`.
- Empty controlled paddle/wheel trials now fail explicitly with exit code 5 and exact causes instead of producing a false pass.
- The final live read confirms active profile 1 maps both paddle directions to scrolling, all five profiles remain readable, and no raw-mode recovery marker exists.
- Current hardware proof is complete: direct sensor capture produced 1,092 reports over 26–209; normal paddle output produced 125 Tyon-attributed wheel events in both directions with strict ordering and preserved profiles.
- The continuous runtime now has atomic local config, SQLite/WAL migrations, bounded prioritized persistence, one-second aggregation, 30-day retention, tray start/stop, and immediate symptom markers with context queries.
- A live connected-Tyon smoke stored one session, 11 discrete events, seven aggregates, and one marker; the 30-second context query returned the surrounding data and shutdown was clean.
- Scroll CSVs contain deltas without pointer coordinates; cursor movement is not part of the diagnostic model.

## Active Work

- Branch: `feature/continuous-windows-telemetry`.
- PR #5 is open as a draft and continuous observation is running on the connected Tyon.
- Review remediation on the current branch hardens raw-mode acknowledgement and cleanup reporting, rejects ambiguous multi-Tyon raw/control pairing, preserves raw CSV semantics, detects sequence gaps, and limits controlled-trial acceptance to action-phase wheel events.
- All historical actionable review threads on merged PRs #1, #3, and #4 have replies, fix references, and resolved GitHub thread state; PR #5 currently has no review threads or comments.
- Complete reconnect/recovery, inspection/export, richer device sources, tray verification, and soak instrumentation.

## Blockers

- No repository or architecture blocker.
- No capture-proof blocker remains. The full-time logger, durable storage, symptom markers, and retention are implemented; reconnect/recovery, inspection/export, and soak validation remain.
- Any corrective device write requires the product's explicit preview/confirmation step.

## Next Session Focus

1. Push the review-remediation commit and resolve the corresponding historical PR #1, #3, and #4 review threads.
2. Complete reconnect/recovery, inspection/export, richer device sources, tray verification, and eight-hour soak evidence for PR #5.
3. Begin the analysis dashboard only after the telemetry data and soak evidence make it useful.

## Handoff Pointers

- Intent and boundaries: `NORTH_STAR.md`
- Technical direction: `architecture.md`
- Existing hardware evidence and protocol sources: `docs/source-audit.md`
- Controlled hardware procedure: `docs/workflows/controlled-diagnostics.md`
- Current implementation plan: `docs/superpowers/plans/2026-07-15-normal-mode-xcelerator-capture.md`
