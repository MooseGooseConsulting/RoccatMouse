---
title: RoccatMouse North Star
date: 2026-07-15
author: MooseGooseConsulting
status: living
last_confirmed: 2026-07-15
---

# RoccatMouse North Star

## Why This Exists

RoccatMouse exists to keep the Tyon fully configurable on modern Windows while turning X-Celerator paddle faults from opaque behavior into evidence that can support a safe, reversible fix.

## Goals

### G1 — Preserve complete mouse configuration

- **G1-R1:** RGB, DPI, polling, profiles, button mappings, macros, and game-profile behavior remain available throughout diagnostics work.
- **G1-R2:** Diagnostic captures demonstrate that unrelated onboard profiles are unchanged.

### G2 — Make the X-Celerator signal chain observable

- **G2-R1:** Controlled trials separately record raw paddle sensor behavior and normal Windows scroll behavior.
- **G2-R2:** Every capture records its trial label, phase, monotonic ordering, UTC time, and cleanup outcome.
- **G2-R3:** The product can distinguish sensor, device-mapping, Windows-event, and application-level fault domains from collected evidence.

### G3 — Enable evidence-backed correction

- **G3-R1:** No calibration, mapping, or filtering intervention is proposed until a reproducible capture supports it.
- **G3-R2:** Every supported device change has a backup, exact preview, explicit confirmation, readback verification, before/after trial, and rollback.

### G4 — Grow from a Windows-first base without closing the Linux path

- **G4-R1:** Telemetry models, session lifecycle, storage, and analysis remain platform-neutral behind adapters.
- **G4-R2:** After Windows capture and storage pass the extended soak, a bounded licensing/adapter spike may begin. Full Linux feature implementation begins only if that spike documents a viable approach.

## Anti-Goals

- **AG1 — This is not a cursor-motion explanation for scrolling.** Wheel and paddle-scroll events do not imply cursor movement; pointer position is not evidence in the X-Celerator diagnostic chain.
- **AG2 — This is not an automatic calibration writer.** Raw diagnostics send only bounded start/end commands, and corrective writes never happen silently.
- **AG3 — This is not a cloud telemetry service.** Diagnostic data is local and user-owned unless explicitly exported.
- **AG4 — This is not an unreviewed GPL port.** GPL implementations remain references while Windows deliverables remain MIT; direct reuse requires a deliberate Linux-milestone licensing decision.

## Pillars

### Evidence before intervention

We accept a slower path to correction in exchange for knowing which layer is failing before changing calibration, mappings, or host behavior.

### Windows first

We accept delayed Linux parity in exchange for finishing the working Windows product and validating it against the available hardware.

### Reversible device changes

We accept confirmation and backup friction in exchange for protecting onboard profiles and making every correction recoverable.
