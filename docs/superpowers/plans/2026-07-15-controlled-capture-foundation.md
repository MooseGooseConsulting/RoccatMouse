# Controlled Capture Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the Windows-first source audit and make controlled paddle/wheel capture recover safely from cancellation, exceptions, and an unclean prior raw-mode session.

**Architecture:** Keep the working configurator intact. Isolate raw calibration-mode lifecycle in a small controller that owns a durable recovery marker and accepts the existing HID transport functions, then use it from the current capture runner. Continue treating wheel capture as read-only and raw paddle capture as start/end-only.

**Tech Stack:** Python 3.10+, standard library, hidapi, PySide6, unittest

---

### Task 1: Pin and document reference sources

**Files:**
- Modify: `.gitignore`
- Create: `docs/source-audit.md`

- [x] Ignore `.references/` so reference clones cannot enter the product tree.
- [x] Clone all three sources and record their exact commit hashes and licenses.
- [x] Compare discovery, routing, reports, profiles, buttons, macros, calibration, special reports, input monitoring, and platform behavior.
- [x] Record the MIT/GPL reuse boundary and Linux licensing decision gate.

### Task 2: Specify raw-mode recovery behavior with failing tests

**Files:**
- Modify: `tests/test_tyon_monitor.py`
- Modify: `tyon_monitor.py`

- [x] Add a test proving the recovery marker exists before the start report is sent.
- [x] Run that test and confirm it fails because `RawModeLifecycle` does not exist.
- [x] Add tests proving successful end removes the marker, failed end retains it, stale state sends end before a new start, and a failed start attempts cleanup.
- [x] Run the focused tests and confirm they fail for the missing lifecycle behavior.

### Task 3: Implement and integrate raw-mode lifecycle

**Files:**
- Modify: `tyon_monitor.py`

- [x] Add `raw_mode_marker_path()` using `%LOCALAPPDATA%\RoccatMouse\raw-mode-active.json`.
- [x] Add `RawModeLifecycle` with injected `check_write` and `write_feature` callables.
- [x] Write the marker before start, recover a stale marker with end, remove it only after successful end, and never send function `0x0b`.
- [x] Replace the capture runner's Boolean streaming flag with the lifecycle object while preserving device closure and critical cleanup messages.
- [x] Run focused tests until green, then run the complete suite.

### Task 4: Document and verify the controlled workflows

**Files:**
- Modify: `README.md`
- Test: `tests/test_tyon_monitor.py`
- Test: `tests/test_tyon_capture_gui.py`

- [x] Document the downstream relationship, pinned audit, raw-mode marker, stale recovery, and manual hardware acceptance steps.
- [x] Run `python -m unittest discover -s tests -v` in the project virtual environment.
- [x] Run compile/import checks for all Python modules.
- [x] Run hardware-safe discovery/list commands and record whether hardware acceptance is available in this environment.
- [x] Review the diff against the source plan and verify no GPL source or calibration-save command entered the product.
- [x] Commit durable units, push the branch, open or update the reviewable PR, self-review it, and address valid review feedback.
