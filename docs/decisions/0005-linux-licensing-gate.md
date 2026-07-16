# ADR 0005: Defer Linux implementation behind an adapter and licensing spike

- Status: Accepted
- Date: 2026-07-15

## Context

RoccatTyon and roccat-tools demonstrate useful Linux transport, calibration, and protocol behavior, but they are GPL-3.0 and GPL-2.0 respectively. Direct source reuse could change the distributable's licensing. Linux input collection also differs across hidraw, `evdev`, udev permissions, X11, and Wayland.

## Decision

Keep platform-neutral models and analysis interfaces now, but defer Linux implementation until the Windows logger completes its extended soak. Begin Linux with a bounded hardware-adapter and licensing spike; do not copy GPL implementation code into the MIT Windows product.

## Why

The spike will reveal which behavior requires source reuse and which can be independently implemented before a licensing commitment is made. It also prevents Wayland cursor restrictions from distorting the Windows-first diagnostic design; global cursor coordinates are not required on either platform.

## Consequences

- The Linux milestone initially delivers evidence and a decision, not parity.
- Required Linux signals are relative input, wheel events, accelerator values, HID reports, and profile/configuration transport.
- Any direct GPL reuse and resulting relicensing requires a new accepted decision.
