# Continuous Windows telemetry implementation plan

- Status: Planned
- Branch: `feature/continuous-windows-telemetry`
- Depends on: normal-mode capture merged and hardware-accepted

## Why

Controlled trials characterize repeatable behavior, but intermittent drift or stuck scrolling may not appear during a ten-second session. Continuous local observation is required to catch the symptom while keeping full-rate storage bounded and user-controlled.

## Goal

Add an on-demand tray runtime, SQLite WAL storage, numbered migrations, one-second aggregation, discrete events, retention, reconnect recovery, and anomaly markers. Do not enable automatic startup or cloud upload.

## Storage and runtime shape

- `roccatmouse/config.py`: resolve `%APPDATA%\RoccatMouse\config.json`, validate defaults, and perform atomic config replacement.
- `roccatmouse/diagnostics/storage.py`: `SQLiteTelemetryStore` implementing the storage contract.
- `roccatmouse/diagnostics/migrations/`: ordered SQL resources; v1 creates sessions, events, aggregates, anomalies, and exports.
- `roccatmouse/diagnostics/aggregate.py`: deterministic one-second accumulator independent of SQLite.
- `roccatmouse/diagnostics/retention.py`: transactional 30-day continuous-data cleanup.
- `roccatmouse/tray.py`: PySide6 tray controller that starts/stops observation, opens Diagnostics, reports reconnect/cleanup state, and exits cleanly.

The database path is `%LOCALAPPDATA%\RoccatMouse\telemetry.sqlite3`. Use one writer thread, bounded queues, batched transactions, WAL, foreign keys, and a busy timeout. High-fidelity sessions store full-rate events; continuous mode stores one-second aggregates plus discrete wheel/button/anomaly/marker events.

## Test-first implementation sequence

1. Test configuration path resolution, defaults, corrupt-file recovery, and atomic save; then implement config handling.
2. Test migration from an empty database, idempotent reopen, ordered multi-version upgrade, and rollback on failed migration; then implement the migration runner.
3. Test sessions/events/aggregates/anomalies CRUD, sequence uniqueness, clean/unclean completion, export tracking, and cascade deletion; then implement the store.
4. Test one-second aggregation with empty buckets, boundary timestamps, reversals, wheel bursts, and late events; then implement the accumulator.
5. Test retention at 29, 30, and 31 days, preserving marked high-fidelity sessions; then implement cleanup.
6. Test bounded queue backpressure and database failure behavior; preserve anomaly counts instead of blocking input threads indefinitely.
7. Add tray state tests and an offscreen smoke test; then implement start/stop/open/exit actions. Leave autostart absent.
8. Connect session recovery so startup records an unclean prior session, attempts raw-mode exit when its marker exists, and exposes the result in tray status.
9. Add diagnostic database inspection/export commands for test and support use.
10. Update architecture status labels, storage documentation, runtime instructions, and `PROGRESS.md`.

## Failure behavior

- Database unavailability stops persistence, raises a visible anomaly, and does not silently discard an explicitly started high-fidelity session.
- Continuous-mode queue saturation drops aggregate detail in a counted way but preserves discrete symptom markers.
- Reconnect uses exponential backoff with a bounded maximum and records each transition.
- Shutdown drains a bounded batch, marks session state honestly, stops sources, and runs raw cleanup.
- Retention never deletes an active or explicitly retained high-fidelity session.

## Automated validation

- Migration, WAL, ordering, aggregation, retention, cancellation, reconnect, simulated disk failure, and backpressure tests pass.
- Existing capture and configurator tests remain green.
- CI validates a fresh database and upgrades from every committed schema fixture.
- Offscreen tray startup/stop/exit leaves no worker thread running.

## Eight-hour soak

Run continuous observation for eight hours with the Tyon connected. Record initial, one-hour, four-hour, and final process/database metrics. Pass when:

- the runtime remains responsive;
- resident memory growth after the first hour stays below 25 MiB;
- idle CPU averages below 5% of one logical processor;
- database growth is linear with documented event volume;
- WAL checkpoints complete;
- ten disconnect/reconnect cycles do not strand capture or raw mode;
- retention removes synthetic data older than 30 days while preserving retained sessions.

## PR stop condition

Do not open the non-draft PR until the automated suite and eight-hour soak pass and their evidence is committed to `docs/history/`. Self-review, address all valid feedback, merge, and update `main` before dashboard work.
