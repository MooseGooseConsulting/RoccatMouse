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
- Fifty-four unit tests and the Windows CI workflow pass.
- Live discovery confirms the Tyon Telephony control collection and MI_03 special-report interface.
- Raw capture cleanup and all five onboard-profile reads have been verified on the connected Windows 11 system.
- The normal-mode engine records QPC/UTC ordered WinMM, MI_03, and device-attributed Raw Input events; short live neutral captures preserve all five profile fingerprints.
- Scroll CSVs contain deltas without pointer coordinates; cursor movement is not part of the diagnostic model.

## Active Work

- Branch: `feature/normal-mode-xcelerator-diagnostics`.
- Complete controlled normal-mode paddle-only and wheel-only hardware acceptance, then publish the finished milestone.

## Blockers

- No repository or architecture blocker.
- Fresh hardware acceptance for later milestones requires the owner to move the paddle and wheel when prompted.
- Any corrective device write requires the product's explicit preview/confirmation step.

## Next Session Focus

1. Run the prompted normal paddle-only and physical-wheel trials.
2. Validate source attribution, deltas, ordered timestamps, and profile preservation.
3. Complete self-review and Windows CI, merge the milestone, and begin continuous telemetry.

## Handoff Pointers

- Intent and boundaries: `NORTH_STAR.md`
- Technical direction: `architecture.md`
- Existing hardware evidence and protocol sources: `docs/source-audit.md`
- Controlled hardware procedure: `docs/workflows/controlled-diagnostics.md`
- Current implementation plan: `docs/superpowers/plans/2026-07-15-normal-mode-xcelerator-capture.md`
