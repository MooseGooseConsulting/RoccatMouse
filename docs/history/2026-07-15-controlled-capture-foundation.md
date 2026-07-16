# Controlled-capture foundation completed

- Date: 2026-07-15
- Merge: PR #1, commit `a38f1d6`

RoccatMouse retained the MIT Windows configurator and added bounded paddle/wheel capture, a compact PySide6 launcher, MI_03 monitoring, recoverable raw accelerator streaming, controlled-trial labels, CSV output, hardware acceptance documentation, and Windows CI.

All review findings were addressed and resolved. The final branch had 29 passing unit tests. Live Windows verification found the Tyon Telephony and MI_03 collections, confirmed safe read-only listing, and read all five onboard profiles after the final change. Pointer coordinates were removed from scroll CSVs because callback coordinates are not cursor movement and do not belong in the X-Celerator signal chain.

The completed implementation record remains at `docs/superpowers/plans/2026-07-15-controlled-capture-foundation.md`.
