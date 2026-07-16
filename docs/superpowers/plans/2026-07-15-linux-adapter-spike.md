# Linux adapter and licensing spike plan

- Status: Deferred until the Windows continuous logger has measured stability evidence
- Branch: `spike/linux-hardware-adapter`
- Depends on: Windows telemetry, analysis, and packaging evidence

## Why

Linux configuration support appears feasible from RoccatTyon and roccat-tools, but telemetry parity is affected by hidraw permissions, `evdev`, packaging, and desktop security boundaries. GPL reference implementations may be valuable, but direct reuse could change the project license. A bounded spike must answer those questions before promising parity or copying source.

## Goal

Prove the minimum Linux device and telemetry surfaces, document packaging and permissions, and make an explicit licensing recommendation. The spike does not ship full Linux parity.

## Constraints

- Work from the pinned commits in `docs/source-audit.md`.
- Keep GPL repositories in gitignored `.references/`.
- Do not copy GPL implementation source into the MIT product during the spike.
- Reuse the platform-neutral models, storage, session lifecycle, and analysis engine unchanged.
- Do not require global cursor coordinates; required signals are accelerator values, HID reports, relative input, wheel events, and configuration transport.

## Work sequence

1. Reconfirm reference commits, licenses, protocol surfaces, and upstream changes; update the source audit if pins change.
2. Map `DeviceControl`, `AcceleratorSource`, and `InputEventSource` to Linux hidraw/HIDAPI and `evdev` capabilities.
3. Build an independently written proof adapter for VID `0x1e7d`, Tyon PIDs, interface discovery, read-only profile/report access, and MI_03 monitoring.
4. Document and test udev rules that grant only required device access to a non-root user.
5. Prove bounded raw accelerator start/end and recovery-marker behavior without saving calibration.
6. Prove `evdev` relative motion, wheel, and button telemetry with device attribution under a non-root session.
7. Test X11 and Wayland packaging/runtime behavior without screen coordinates.
8. Compare independent implementation cost with the exact GPL functionality that would otherwise be reused.
9. Add a decision recommending independent Python implementation or intentional GPL reuse/relicensing, including affected files and distribution consequences.
10. Write a follow-on Linux implementation plan only if discovery, permissions, telemetry, packaging, and licensing have viable answers.

## Automated validation

- Contract tests run against fake Linux adapters on Windows CI and real adapters on Linux CI where hardware is not required.
- Report parsing, device filtering, permission errors, disconnect, cancellation, raw cleanup, timestamp ordering, and missing optional surfaces have deterministic tests.
- Shared storage and analyzer tests pass without platform-specific branches.

## Hardware acceptance

Discover the intended interfaces as a non-root user; read profile state without modification; record MI_03 and `evdev` events; run bounded raw streaming and verify interrupted cleanup; confirm the shared labels and schema work without cursor coordinates.

## Stop condition

The spike is complete when it commits a working proof where feasible, supported-surface matrix, udev and packaging notes, test evidence, and accepted licensing recommendation. Full Linux implementation requires a new decision-complete plan and must not delay Windows correction work.
