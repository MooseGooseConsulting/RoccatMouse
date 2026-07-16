# Windows input adapters

## Why adapters are separate

The Tyon exposes configuration, raw accelerator data, joystick axes, special reports, and ordinary mouse input through different Windows surfaces. Keeping those surfaces behind contracts prevents capture policy and analysis from depending directly on one API and preserves a future Linux path.

## Planned adapters

- **Telephony device control:** existing HIDAPI routing for configuration and bounded raw-mode start/end.
- **MI_03 special reports:** read raw and normal special reports without conflating them with feature-report control.
- **WinMM accelerator axes:** retain the proven DirectInput-compatible joystick-axis view.
- **Win32 Raw Input:** add device-attributed relative movement, buttons, and wheel deltas. X-Celerator analysis consumes the wheel events; relative movement remains a separate general mouse diagnostic channel.
- **Timestamp source:** capture QPC monotonic time at ingestion and pair it with UTC time plus a per-session sequence.

## Exclusions

- `GetCursorPos` is not part of X-Celerator capture.
- Pointer coordinates supplied by a callback are not movement deltas and are not stored as scroll evidence.
- Raw calibration streaming does not save device calibration.
