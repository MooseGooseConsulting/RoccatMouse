# Controlled X-Celerator diagnostics

## Why this workflow exists

Windows cannot reliably distinguish a paddle-generated scroll event from a physical-wheel scroll event on the same mouse. Repeatable, labelled, one-control-at-a-time trials provide the missing attribution and let raw sensor behavior be compared with normal mapped behavior without pretending the two modes are simultaneous.

## Preconditions

1. Close other programs that may hold Tyon HID interfaces.
2. Run the unit suite, `tyon_rgb.py --probe`, `tyon_rgb.py --read`, and `tyon_monitor.py --list`.
3. Record the active profile and fingerprint all five profiles. The current
   diagnostic fingerprint covers profile settings and button mappings;
   diagnostics never write macros, and a full macro/host-game-profile comparison
   remains a manual configurator/readback check until that export exists.
4. If a raw-mode recovery marker exists, do not delete it. Reconnect the mouse
   if necessary and start a raw capture so its startup recovery sends the safe
   end command before any new start command.

## Trial order

1. **Neutral raw:** 60 seconds with hands off the paddle and wheel.
2. **Raw paddle:** five slow upward sweeps, five slow downward sweeps, three-second endpoint holds, and visible return-to-center pauses.
3. **Normal paddle-only:** ten slow actuations per direction followed by twenty quick alternating actuations; do not touch the wheel.
4. **Normal wheel-only:** twenty physical wheel notches per direction; do not touch the paddle.
5. **Symptom reproduction:** use the control normally until the fault occurs, then add a symptom marker and note.
6. **Continuous soak:** eight hours of normal connected operation after storage and retention exist.

## Agent and owner roles

The agent starts and monitors capture, validates report rates, watches cleanup state, ends raw mode, checks the store, analyzes evidence, and handles repository/PR work. The owner only performs the prompted physical motions and confirms a correction after seeing its backup and exact preview.

## Pass conditions

- Trials contain the expected labels and phases in monotonic order.
- Raw captures show plausible neutral, endpoints, and return behavior with no unmatched-report explosion.
- Normal paddle and wheel trials record direction/delta behavior independently.
- Record whether scrolling stops after the paddle returns to neutral. Continued
  scrolling is a symptom reproduction to retain and mark, not an invalid trial.
- Raw mode exits cleanly after normal completion, cancellation, simulated failure, and reconnect.
- All onboard profiles match their pre-test fingerprint.

See `docs/windows-capture-acceptance.md` for the current foundation-specific checklist.
