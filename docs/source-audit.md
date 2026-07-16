# RoccatMouse source audit

This repository is a downstream product based on Randolf Hellmann's MIT-licensed
Windows configurator. The upstream history is retained: commit `b5f9d42` is both
the current upstream tip audited below and an ancestor of this repository's
Windows diagnostics branch.

The two Linux-capable projects are protocol and architecture references only in
the Windows milestones. Their GPL source is not copied into the distributable
Python application. Direct reuse from either GPL project is a licensing decision
gate for the later Linux milestone.

## Pinned references

The working clones live under the gitignored `.references/` directory. Recreate
the audited state with the following commits:

| Project | Role | Audited commit | License |
|---|---|---|---|
| [roccat-tyon-rgb](https://github.com/RandolfHellmann/roccat-tyon-rgb) | Windows/Python downstream base | `b5f9d42bdd86fc61f2bb7ed0c545f61952e13e70` | MIT |
| [RoccatTyon](https://github.com/britus/RoccatTyon) | Qt/C++ platform-adapter and calibration reference | `f9223c3777b5ce4c8641679ac1e728fa3a1fdbe7` | GPL-3.0 |
| [roccat-tools](https://github.com/ngg/roccat-tools) | Historical protocol and event-handler reference | `500e86a6649e8c04d57ef46d4de03f838e038c55` | GPL-2.0 |

To verify the pins:

```pwsh
git -C .references/roccat-tyon-rgb rev-parse HEAD
git -C .references/RoccatTyon rev-parse HEAD
git -C .references/roccat-tools rev-parse HEAD
```

## Comparison matrix

| Surface | RoccatMouse / roccat-tyon-rgb | RoccatTyon | roccat-tools |
|---|---|---|---|
| Device discovery | Python `hid.enumerate` for ROCCAT VID and black/white Tyon PIDs. Windows feature traffic selects the Telephony top-level collection (`usage_page 0x000b`). Diagnostics additionally select MI_03 Misc (`interface_number 3`, `usage_page 0x000a`). | `RTHidLinux` uses HIDAPI enumeration and classifies Mouse/Generic Desktop as control and Misc `0x0a` as X-Celerator input. A separate IOKit-backed macOS adapter implements the same `RTHidDevice` contract. | libgaminggear/roccat device enumeration and hidraw character devices; Tyon feature traffic uses the mouse endpoint selected by the Linux stack. |
| HID routing | Windows control/feature reports use the Telephony collection; raw special input uses MI_03. This routing is Windows-specific and hardware-verified in the downstream base. | `RTHidDevice` separates `HidMouseControl`, `HidMouseInput`, and `HidJoystick`; Linux reads/writes features through hidraw ioctls and monitors the input path on a thread. | Feature reports go through `RoccatDevice`; special events are consumed from the Tyon hidraw/eventhandler channel. |
| Report structures | Python byte buffers implement control `0x04`, profile `0x05`, settings `0x06`, buttons `0x07`, macros `0x08`, info `0x09`, TalkFX `0x10`, and special input `0x03`. | Packed C++ structs in `rttypedefs.h` cover the same profile/control/info/special families plus sensor reports. | Packed C structs in `tyon/libroccattyon` are the historical protocol source for profile, buttons, macro, info, sensor, and special reports. |
| Profiles | Reads, selects, edits, and persistently writes all five onboard profiles. | Full five-profile UI, import/export, reset, and active-profile control. | Full profile read/write library and configuration UI/CLI support. |
| Buttons | Primary physical layer is editable; wheel inversion swaps wheel action slots. | Primary and Easy-Shift layers are exposed. | Full primary/Easy-Shift button structures and action vocabulary. |
| Macros | Builds and reads the two-transfer, 1,997-byte onboard macro structure; GUI records and assigns macros. | Macro assignment and editing through the Qt controller. | Authoritative packed macro structures, action types, and read/write functions. |
| Calibration | Diagnostics send only X-Celerator start `0x08` and end `0x0a`; save/data `0x0b` is intentionally absent. No correction is performed. | X-Celerator wizard streams special report type `0xe0`, calculates min/mid/max, and saves only after explicit confirmation; TCU surface calibration is also implemented. | `tyon_xcelerator.c` defines start/data/end operations and `tyon_info.h` defines the exact function values. |
| Special reports | MI_03 reports are captured to CSV. X-Celerator calibration packets are parsed as the five-byte special structure and unmatched packets are retained as hex. | A background input monitor dispatches report handlers; calibration consumes `TyonSpecial` and reads the raw value from its action byte. | The event-handler channel parses `TyonSpecial` and dispatches profile, CPI, sensitivity, radial menu, multimedia, and other event types. |
| Input monitoring | Windows WinMM joystick axes, optional `pynput` scroll/cursor events, and HIDAPI MI_03 special reports. Controlled trials are explicitly labelled paddle-only or wheel-only. | HID special-report monitoring is present; it does not provide Windows Raw Input or Linux evdev pointer telemetry. | Hidraw special-event monitoring is present; it does not provide a cross-platform cursor or relative-motion telemetry layer. |
| Platform behavior | Windows 10/11 product. The configurator is preserved while diagnostics are added in Python/PySide6. | Linux and macOS adapters share a Qt interface. Linux requires hidraw access; macOS uses IOKit. | Linux-oriented libraries, daemon/event handler, udev integration, and configuration tools. |

## Reuse boundary

- The MIT Windows project remains the product base and may be reorganized or
  reused directly while retaining its copyright and license notice.
- RoccatTyon and roccat-tools are used to verify protocol facts, algorithms, and
  platform boundaries. No GPL implementation file is vendored or translated
  line-for-line into the Windows product in this milestone.
- Linux remains a stretch milestone after the Windows logger and storage soak.
  Its kickoff must decide between GPL reuse/relicensing and an independently
  maintained Python adapter before implementation begins.

## Windows-first conclusions

The existing product already preserves RGB, DPI, polling, profiles, buttons,
macros, and game-profile behavior. The diagnostics branch adds controlled
paddle and wheel captures without writing calibration values. The immediate
foundation work is therefore lifecycle safety: mark entry into raw streaming,
always attempt the matching end command, retain evidence when cleanup fails,
and recover a stale marker before starting another capture.
