# Windows controlled-capture acceptance

Run this checklist on Windows 11 with the Tyon connected. Close other tools
that may hold the mouse's HID interfaces. These checks do not save calibration
values or rewrite profiles.

## Preconditions

```pwsh
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tyon_rgb.py --probe
.\.venv\Scripts\python.exe tyon_monitor.py --list
```

Confirm the probe lists the Telephony vendor collection and MI_03 Misc input
collection. Confirm the joystick list has one unambiguous Tyon device, or note
the slot to pass with `--device` for console captures.

Before testing, read the five onboard profiles in the configurator or with
`tyon_rgb.py --read` and retain the output for the final profile-preservation
comparison.

## Paddle-only trial

1. Start `capture-paddle.bat`.
2. Do not touch the paddle or wheel during the two-second baseline.
3. During the action phase, move the X-Celerator paddle repeatedly to both
   endpoints and release it to center. Do not use the physical wheel.
4. Let the capture finish normally.
5. Confirm the summary reports raw packets, a plausible baseline, movement on
   both sides of baseline, and zero unmatched packets under normal conditions.
6. Open the CSV under `captures\` and confirm every row is labelled `paddle`.

## Wheel-only trial

1. Start `capture-wheel.bat`.
2. Do not touch the paddle or wheel during the two-second baseline.
3. During the action phase, scroll only the physical wheel in both directions.
   Do not touch the X-Celerator paddle.
4. Let the capture finish normally.
5. Confirm the summary reports scroll events in both directions.
6. Open the CSV under `captures\` and confirm every row is labelled `wheel`.

Windows does not identify whether a wheel event came from the physical wheel
or a scroll-mapped paddle. The controlled trial label is therefore evidence
about operator intent, not firmware-level source attribution.

## Cancellation and recovery

1. Start a paddle capture and press **Stop capture** during the action phase.
2. Confirm the window reports that it is restoring normal device mode and then
   becomes usable again.
3. Confirm `%LOCALAPPDATA%\RoccatMouse\raw-mode-active.json` is absent after a
   successful stop.
4. Start another paddle capture and close the window during capture. Confirm it
   waits for cleanup before closing.
5. For an unclean-session simulation, create the marker file manually, then
   start a paddle capture. Confirm the console reports prior-session recovery,
   capture proceeds, and the marker is absent after completion.

If cleanup reports a critical error, leave the marker intact, reconnect the
mouse, and start another paddle capture. The new capture must retry the end
command before sending start. Do not delete the marker to hide a failed cleanup.

## Profile preservation

After all trials, read all five profiles again and compare them byte-for-byte
or field-for-field with the pre-test output. RGB, DPI, polling, button, macro,
and game-profile configuration must be unchanged.

