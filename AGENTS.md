Read NORTH_STAR.md first. Do not infer intent from code.

# Agent Router

## Authority

Authority flows from `NORTH_STAR.md` to `architecture.md` to `PROGRESS.md`. This file routes; it does not redefine them.

## Route by Task

- Understand purpose, goals, or boundaries: `NORTH_STAR.md`
- Make an architectural decision: `architecture.md`, then `docs/decisions/`
- Implement or debug active work: `PROGRESS.md`, then the active file in `docs/superpowers/plans/`
- Work on a subsystem: `docs/components/`
- Run a hardware or delivery procedure: `docs/workflows/`
- Review protocol sources or licenses: `docs/source-audit.md`, then `docs/decisions/0005-linux-licensing-gate.md`
- Look up completed work: `docs/history/`
- Write or reconcile authority documentation: invoke the `project-docs` skill
- Cross a goal, anti-goal, pillar, or safety invariant: stop and surface the conflict

## Commands

- Install: `python -m pip install -r requirements.txt`
- Test: `python -m unittest discover -s tests -p "test_*.py" -v`
- Compile: `python -m compileall -q tyon_capture_gui.py tyon_gui.py tyon_input.py tyon_monitor.py tyon_rgb.py tyon_store.py tyon_widgets.py tests`
- Probe device: `python tyon_rgb.py --probe`
- Read profiles: `python tyon_rgb.py --read`
- List diagnostic axes safely: `python tyon_monitor.py --list`
- Launch configurator: `gui.bat`
- Launch controlled capture: `capture-gui.bat`

## Working Rules

- Preserve RGB, DPI, polling, profiles, buttons, macros, and game-profile behavior.
- Never save calibration during diagnostic raw streaming.
- Do not treat pointer coordinates or cursor motion as scroll evidence.
- Keep GPL reference source outside the MIT distributable until the Linux licensing gate is decided.
- Stage only files belonging to the active scope; preserve user captures and unrelated worktree changes.
- Open a non-draft PR only after the scoped implementation and validation are complete.
- After opening a PR, self-review it and address valid inline feedback before merge.

## Handoff

Before ending substantial work, update `PROGRESS.md` with current state, active work, blockers, next-session focus, and links to new decisions or plans. Move older completed narrative into `docs/history/`.
