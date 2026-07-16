# ADR 0001: Use the Windows configurator as the product base

- Status: Accepted
- Date: 2026-07-15

## Context

The inherited Python/PySide6 project already configures the connected Tyon on Windows 11 and contains the verified Telephony HID routing required by this device. The Linux/macOS projects are useful protocol and abstraction references but use GPL licenses and do not reduce the immediate Windows hardware risk as much as the working MIT base.

## Decision

Retain the full MIT history and configurator as RoccatMouse. Deliver Windows diagnostics first and design adapter boundaries that permit a later Linux implementation.

## Why

This keeps working RGB, DPI, profile, button, macro, and game-profile functionality while focusing new effort on the unresolved X-Celerator fault. It avoids re-deriving transport behavior or delaying the available Windows hardware feedback loop.

## Consequences

- Windows packaging and hardware acceptance come first.
- Linux parity is not a prerequisite for Windows milestones.
- GPL reference code is studied but not copied into the MIT Windows product.
